"""Point-in-time backfill of the prediction log.

These tests stub the reconstructor (no network) and focus on the safety contract:
- ONLY the reconstructed model's rows change; every other model is left untouched.
- Look-ahead-prone models (DeepLearning) are never reconstructed.
- Reconstructed rows are tagged Source="backfill"; the row total is preserved.
"""
import numpy as np
import pandas as pd
import pytest

bf = pytest.importorskip("backfill_prediction_log")


def _make_log(tmp_path):
    """A small multi-model log: near-constant (stale) QuantConnect + others."""
    rows = []
    run_dates = ["2026-05-01", "2026-05-15", "2026-06-01"]
    tickers = ["AAPL", "MSFT", "AMZN"]
    for rd in run_dates:
        for t in tickers:
            # Stale QC: near-constant ~2.0 regardless of ticker.
            rows.append({"RunDate": rd, "Ticker": t, "Model": "QuantConnect", "Horizon": 21,
                         "ForecastPct": 2.0, "CI_Lower": np.nan, "CI_Upper": np.nan, "AsOfDate": rd})
            # A couple of other models with distinctive values.
            rows.append({"RunDate": rd, "Ticker": t, "Model": "Linear", "Horizon": 21,
                         "ForecastPct": 5.5, "CI_Lower": 1.0, "CI_Upper": 9.0, "AsOfDate": rd})
            rows.append({"RunDate": rd, "Ticker": t, "Model": "DeepLearning", "Horizon": 21,
                         "ForecastPct": -1.2, "CI_Lower": -8.0, "CI_Upper": 6.0, "AsOfDate": rd})
    df = pd.DataFrame(rows)
    path = tmp_path / "prediction_log.parquet"
    df.to_parquet(path, index=False)
    return path, df


def _stub_reconstructor(run_dates, tickers):
    """Dispersed, deterministic 'reconstruction' — distinct value per ticker."""
    bump = {"AAPL": 1.0, "MSFT": 3.0, "AMZN": -2.0}
    out = []
    for d in run_dates:
        for t in tickers:
            out.append({"RunDate": pd.Timestamp(d).date().isoformat(), "Ticker": t,
                        "Model": "QuantConnect", "Horizon": 21, "ForecastPct": bump[t],
                        "CI_Lower": np.nan, "CI_Upper": np.nan,
                        "AsOfDate": pd.Timestamp(d).date().isoformat(), "Source": "backfill"})
    return pd.DataFrame(out, columns=bf.LOG_COLS)


def test_only_target_model_changes(tmp_path, monkeypatch):
    path, orig = _make_log(tmp_path)
    monkeypatch.setitem(bf.RECONSTRUCTORS, "QuantConnect", _stub_reconstructor)

    out = bf.backfill(["QuantConnect"], log_path=path, dry_run=True)

    # Other models are byte-for-byte identical in value.
    for model in ["Linear", "DeepLearning"]:
        a = orig[orig.Model == model].sort_values(["RunDate", "Ticker"]).reset_index(drop=True)
        b = out[out.Model == model].sort_values(["RunDate", "Ticker"]).reset_index(drop=True)
        for col in ["RunDate", "Ticker", "ForecastPct", "CI_Lower", "CI_Upper", "AsOfDate"]:
            assert a[col].astype(str).tolist() == b[col].astype(str).tolist(), f"{model}.{col} changed"


def test_target_model_is_replaced_and_dispersed(tmp_path, monkeypatch):
    path, orig = _make_log(tmp_path)
    monkeypatch.setitem(bf.RECONSTRUCTORS, "QuantConnect", _stub_reconstructor)
    out = bf.backfill(["QuantConnect"], log_path=path, dry_run=True)

    qc = out[out.Model == "QuantConnect"]
    # Old QC had zero cross-sectional spread; reconstruction disperses it.
    spread = qc.groupby("RunDate")["ForecastPct"].agg(lambda s: s.max() - s.min())
    assert (spread > 0).all()
    assert set(qc["ForecastPct"].unique()) == {1.0, 3.0, -2.0}


def test_reconstructed_rows_tagged_backfill(tmp_path, monkeypatch):
    path, _ = _make_log(tmp_path)
    monkeypatch.setitem(bf.RECONSTRUCTORS, "QuantConnect", _stub_reconstructor)
    out = bf.backfill(["QuantConnect"], log_path=path, dry_run=True)
    assert (out[out.Model == "QuantConnect"]["Source"] == "backfill").all()
    # Untouched models keep the implicit "live" provenance.
    assert (out[out.Model == "Linear"]["Source"] == "live").all()


def test_row_total_preserved(tmp_path, monkeypatch):
    path, orig = _make_log(tmp_path)
    monkeypatch.setitem(bf.RECONSTRUCTORS, "QuantConnect", _stub_reconstructor)
    out = bf.backfill(["QuantConnect"], log_path=path, dry_run=True)
    assert len(out) == len(orig)


def test_deeplearning_is_never_reconstructed(tmp_path, monkeypatch):
    path, orig = _make_log(tmp_path)
    # Even if someone registers a DL reconstructor, the look-ahead guard must skip it.
    monkeypatch.setitem(bf.RECONSTRUCTORS, "DeepLearning", _stub_reconstructor)
    out = bf.backfill(["DeepLearning"], log_path=path, dry_run=True)
    a = orig[orig.Model == "DeepLearning"].sort_values(["RunDate", "Ticker"]).reset_index(drop=True)
    b = out[out.Model == "DeepLearning"].sort_values(["RunDate", "Ticker"]).reset_index(drop=True)
    assert a["ForecastPct"].tolist() == b["ForecastPct"].tolist()


def test_dry_run_does_not_write(tmp_path, monkeypatch):
    path, orig = _make_log(tmp_path)
    monkeypatch.setitem(bf.RECONSTRUCTORS, "QuantConnect", _stub_reconstructor)
    bf.backfill(["QuantConnect"], log_path=path, dry_run=True)
    on_disk = pd.read_parquet(path)
    # File unchanged: QC still the stale near-constant 2.0.
    assert (on_disk[on_disk.Model == "QuantConnect"]["ForecastPct"] == 2.0).all()


def test_real_write_backs_up_and_persists(tmp_path, monkeypatch):
    path, orig = _make_log(tmp_path)
    monkeypatch.setitem(bf.RECONSTRUCTORS, "QuantConnect", _stub_reconstructor)
    bf.backfill(["QuantConnect"], log_path=path, dry_run=False)
    on_disk = pd.read_parquet(path)
    assert set(on_disk[on_disk.Model == "QuantConnect"]["ForecastPct"].unique()) == {1.0, 3.0, -2.0}
    # A dated backup of the original was written alongside.
    backups = list(tmp_path.glob("prediction_log_backup_*.parquet"))
    assert backups, "expected a backup of the original log"
    assert (pd.read_parquet(backups[0])[lambda d: d.Model == "QuantConnect"]["ForecastPct"] == 2.0).all()
