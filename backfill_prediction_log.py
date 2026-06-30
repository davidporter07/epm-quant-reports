"""backfill_prediction_log.py

Honest, point-in-time reconstruction of model forecasts into
data/prediction_log.parquet.

WHY THIS EXISTS
---------------
The leaderboard (model_leaderboard.py) scores whatever forecasts the log holds.
When a model's DEFINITION changes, its old logged rows no longer represent the
current model and silently corrupt its leaderboard metrics (and, since 6/29, the
consensus skill-gate that reads those metrics) until they age out of the 1-year
window. This tool re-derives a model's forecast for past RunDates under its CURRENT
logic, using ONLY information available on each RunDate, and replaces the stale rows.

HONESTY RULES (do not break these)
----------------------------------
1. NO LOOK-AHEAD. A reconstruction for RunDate t may train only on observations
   whose 21-day forward return had already MATURED by t (feature date <= t - 21
   trading days), and may read factors only from prices on/before t.
2. ONLY models that are a deterministic function of as-of-date data may be
   reconstructed. DeepLearning is EXCLUDED: its daily warm-started weights encode
   information learned from data AFTER any past t, so replaying today's checkpoint
   over history would leak the future. (Pre-t checkpoints exist only from 2026-05-29
   in models/history/, not far enough back to help.)
3. Reconstructed rows are tagged Source="backfill" so they stay auditable and never
   masquerade as a live point-in-time log.
4. All models are kept on the SAME evaluation window — we do not extend one model's
   history past the others, which would make the per-ticker leaderboard comparison
   (and the skill-gate) apples-to-oranges.

Currently registered reconstructors: QuantConnect (multivariate factor model).
"""
from __future__ import annotations

import argparse
from datetime import timedelta
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

import quantconnect_model as qc

DATA_DIR = Path("data")
LOG_PATH = DATA_DIR / "prediction_log.parquet"
HORIZON = 21
TRAIN_WINDOW_TD = 504  # ~2 trading years, matching the live model's lookback
LOG_COLS = ["RunDate", "Ticker", "Model", "Horizon", "ForecastPct", "CI_Lower", "CI_Upper", "AsOfDate", "Source"]

# Models that must never be reconstructed (see HONESTY RULES #2).
LOOKAHEAD_EXCLUDED = {"DeepLearning"}


def _reconstruct_quantconnect(run_dates: List[pd.Timestamp], tickers: List[str]) -> pd.DataFrame:
    """Point-in-time QuantConnect forecasts for each RunDate.

    For RunDate t: fit on the trailing ~2y of factor rows whose forward return had
    matured by t, then forecast the cross-section using factors as of t."""
    if not run_dates:
        return pd.DataFrame(columns=LOG_COLS)

    start = min(run_dates) - timedelta(days=900)   # warmup for 12M return + MA200
    end = max(run_dates) + timedelta(days=2)
    print(f" Downloading {len(tickers)} tickers {start.date()} -> {end.date()} for QC reconstruction...")
    prices = qc.fetch_data(tickers, start=start, end=end)
    if prices.empty:
        print(" No price data — cannot reconstruct QuantConnect.")
        return pd.DataFrame(columns=LOG_COLS)

    signals = qc.compute_signals(prices, tickers)
    if signals.empty:
        print(" No signals — cannot reconstruct QuantConnect.")
        return pd.DataFrame(columns=LOG_COLS)

    sig_idx = pd.DatetimeIndex(signals.index)
    price_idx = pd.DatetimeIndex(pd.to_datetime(prices.index)).tz_localize(None)

    rows = []
    skipped = 0
    for t in run_dates:
        t = pd.Timestamp(t).normalize()
        # Last trading day on/before the RunDate.
        pos = price_idx.searchsorted(t, side="right") - 1
        if pos < HORIZON:
            skipped += 1
            continue
        asof_td = price_idx[pos]
        matured_cutoff = price_idx[pos - HORIZON]          # labels known by t
        window_start = price_idx[max(0, pos - HORIZON - TRAIN_WINDOW_TD)]

        train = signals[(sig_idx > window_start) & (sig_idx <= matured_cutoff)]
        model = qc.fit_forecast_model(train)
        if model is None:
            skipped += 1
            continue

        live = signals[sig_idx == asof_td].copy()
        if live.empty:
            skipped += 1
            continue

        fc = qc.forecast_cross_section(model, live)
        for _, r in fc.iterrows():
            rows.append({
                "RunDate": t.date().isoformat(),
                "Ticker": str(r["Ticker"]).upper().strip(),
                "Model": "QuantConnect",
                "Horizon": HORIZON,
                "ForecastPct": float(r["QuantConnect Forecast (%)"]),
                "CI_Lower": np.nan,
                "CI_Upper": np.nan,
                "AsOfDate": asof_td.date().isoformat(),
                "Source": "backfill",
            })

    if skipped:
        print(f" QuantConnect: {skipped} RunDate(s) skipped (insufficient point-in-time history).")
    return pd.DataFrame(rows, columns=LOG_COLS)


RECONSTRUCTORS = {
    "QuantConnect": _reconstruct_quantconnect,
}


def _ensure_source(df: pd.DataFrame) -> pd.DataFrame:
    """Existing rows predate the Source column — they were genuine live logs."""
    df = df.copy()
    if "Source" not in df.columns:
        df["Source"] = "live"
    else:
        df["Source"] = df["Source"].fillna("live")
    return df


def backfill(models: List[str], log_path: Path = LOG_PATH, dry_run: bool = False) -> pd.DataFrame:
    if not log_path.exists():
        raise FileNotFoundError(f"Missing prediction log: {log_path}")

    log = _ensure_source(pd.read_parquet(log_path))
    # NB: keep RunDate as its stored string form so non-reconstructed models stay
    # byte-for-byte untouched. Parse locally only where we need dates.

    new_blocks = []
    done_models: List[str] = []
    for model in models:
        if model in LOOKAHEAD_EXCLUDED:
            print(f" SKIP {model}: excluded (look-ahead — see HONESTY RULES).")
            continue
        fn = RECONSTRUCTORS.get(model)
        if fn is None:
            print(f" SKIP {model}: no point-in-time reconstructor registered.")
            continue

        run_dates = sorted(log.loc[log["Model"] == model, "RunDate"].dropna().unique())
        run_dates = [pd.Timestamp(d) for d in run_dates]
        tickers = sorted(log.loc[log["Model"] == model, "Ticker"].dropna().str.upper().unique().tolist())
        if not run_dates:
            print(f" SKIP {model}: no existing RunDates in the log to align to.")
            continue

        print(f" Reconstructing {model} over {len(run_dates)} RunDate(s)...")
        block = fn(run_dates, tickers)
        if block.empty:
            print(f" {model}: reconstruction produced no rows; leaving existing rows untouched.")
            continue

        # Dedup WITHIN the reconstructed block only (a clean reconstruction has
        # one row per RunDate/Ticker, but guard against accidental repeats).
        block = block.drop_duplicates(subset=["RunDate", "Ticker", "Model"], keep="last")

        # Spread diagnostic (parse dates locally; never mutate the stored log).
        before = log[log["Model"] == model].copy()
        before["_rd"] = pd.to_datetime(before["RunDate"], errors="coerce")
        old_spread = before.groupby("_rd")["ForecastPct"].agg(lambda s: s.max() - s.min()).median()
        b = block.copy(); b["_rd"] = pd.to_datetime(b["RunDate"], errors="coerce")
        new_spread = b.groupby("_rd")["ForecastPct"].agg(lambda s: s.max() - s.min()).median()
        print(f" {model}: replaced {len(before)} rows -> {len(block)} reconstructed. "
              f"Median cross-sectional spread {old_spread:.2f}% -> {new_spread:.2f}%.")

        # Drop ONLY this model's rows; every other model is left byte-for-byte.
        log = log[log["Model"] != model].copy()
        new_blocks.append(block)
        done_models.append(model)

    if not new_blocks:
        print(" Nothing reconstructed.")
        return log

    # Align column set without disturbing untouched rows' values.
    recon = pd.concat(new_blocks, ignore_index=True)
    for c in log.columns:
        if c not in recon.columns:
            recon[c] = np.nan
    recon = recon[log.columns]
    combined = pd.concat([log, recon], ignore_index=True)

    if dry_run:
        print(f" [DRY-RUN] Would write {len(combined)} rows to {log_path} (not written).")
        return combined

    backup = log_path.with_name(f"prediction_log_backup_{pd.Timestamp.today().date().isoformat()}.parquet")
    pd.read_parquet(log_path).to_parquet(backup, index=False)
    print(f" Backed up original log -> {backup}")
    combined.to_parquet(log_path, index=False)
    print(f" Wrote {len(combined)} rows -> {log_path}")
    return combined


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", type=str, default="QuantConnect",
                    help="Comma-separated models to reconstruct (default: QuantConnect).")
    ap.add_argument("--dry-run", action="store_true", help="Compute and report, but do not write the log.")
    args = ap.parse_args()
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    backfill(models, dry_run=bool(args.dry_run))


if __name__ == "__main__":
    main()
