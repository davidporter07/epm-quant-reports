"""PR D: data freshness checks — unit tests for services/data_freshness.py."""
import json
from pathlib import Path

import pytest

from services import data_freshness as df

TODAY = "2026-06-10"
MARKET_OPEN = True
MARKET_CLOSED = False


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def _write(path: Path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)):
        path.write_text(json.dumps(content), encoding="utf-8")
    else:
        path.write_text(str(content), encoding="utf-8")


def _fresh_ycharts(data_dir: Path, scrape_date: str = TODAY):
    _write(data_dir / "ycharts_live.json", {"scrape_date": scrape_date, "funds": {}})


def _fresh_features(data_dir: Path):
    _write(data_dir / "features_from_ycharts.csv", "ticker,Price\nAAPL,200\n")


def _fresh_arbitrated(data_dir: Path, arb_date: str = TODAY):
    _write(data_dir / "market_data_arbitrated.json", {"arbitrated_date": arb_date})


def _fresh_enrichment(data_dir: Path):
    _write(data_dir / "enrichment.json", {"cnn_fear_greed": 50})


def _fresh_econ_calendar(data_dir: Path, event_date: str = TODAY):
    _write(data_dir / "economic_calendar.json",
           {"events": [{"date": event_date, "event": "CPI"}]})


def _fresh_dl_forecasts(data_dir: Path):
    _write(data_dir / "dl_forecasts.csv", "ticker,forecast\nAAPL,0.01\n")


def _all_fresh(data_dir: Path):
    _fresh_ycharts(data_dir)
    _fresh_features(data_dir)
    _fresh_arbitrated(data_dir)
    _fresh_enrichment(data_dir)
    _fresh_econ_calendar(data_dir)
    _fresh_dl_forecasts(data_dir)


# ---------------------------------------------------------------------------
# 1. All fresh
# ---------------------------------------------------------------------------

def test_all_fresh_no_failures(tmp_path):
    _all_fresh(tmp_path)
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    failing = [r for r in results if not r.ok and r.status != "skipped"]
    assert failing == [], f"unexpected failures: {failing}"
    assert df.gate_message(results) is None
    assert df.warn_lines(results) == []


# ---------------------------------------------------------------------------
# 2. Stale inputs
# ---------------------------------------------------------------------------

def test_ycharts_stale_critical_fail(tmp_path):
    _fresh_ycharts(tmp_path, scrape_date="2026-06-05")  # 5 days old, max=3
    _fresh_features(tmp_path)
    _fresh_arbitrated(tmp_path)
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    yc = next(r for r in results if r.name == "ycharts_scrape")
    assert yc.ok is False
    assert yc.status == "stale"
    assert yc.critical is True
    assert "5 day" in yc.detail


def test_arbitrated_stale_critical_fail(tmp_path):
    _fresh_ycharts(tmp_path)
    _fresh_features(tmp_path)
    _fresh_arbitrated(tmp_path, arb_date="2026-06-09")  # yesterday
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    arb = next(r for r in results if r.name == "arbitrated")
    assert arb.ok is False
    assert arb.status == "stale"
    assert arb.critical is True


def test_ycharts_exactly_at_max_age_passes(tmp_path):
    # scrape_date 3 days ago with max_age=3 is still fresh (<=)
    _fresh_ycharts(tmp_path, scrape_date="2026-06-07")  # 3 days old
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    yc = next(r for r in results if r.name == "ycharts_scrape")
    assert yc.ok is True
    assert yc.status == "fresh"


# ---------------------------------------------------------------------------
# 3. Missing files
# ---------------------------------------------------------------------------

def test_ycharts_missing_critical_fail(tmp_path):
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    yc = next(r for r in results if r.name == "ycharts_scrape")
    assert yc.ok is False
    assert yc.status == "missing"
    assert yc.critical is True


def test_features_csv_missing_critical_fail(tmp_path):
    _fresh_ycharts(tmp_path)
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    feat = next(r for r in results if r.name == "features_csv")
    assert feat.ok is False
    assert feat.status == "missing"
    assert feat.critical is True


def test_arbitrated_missing_on_market_day_critical_fail(tmp_path):
    _fresh_ycharts(tmp_path)
    _fresh_features(tmp_path)
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    arb = next(r for r in results if r.name == "arbitrated")
    assert arb.ok is False
    assert arb.status == "missing"


def test_optional_enrichment_missing_is_not_critical(tmp_path):
    # enrichment is optional — should not block even with enforce=1
    _fresh_ycharts(tmp_path)
    _fresh_features(tmp_path)
    _fresh_arbitrated(tmp_path)
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    enr = next(r for r in results if r.name == "enrichment")
    assert enr.ok is False
    assert enr.critical is False


def test_optional_dl_forecasts_missing_is_not_critical(tmp_path):
    _fresh_ycharts(tmp_path)
    _fresh_features(tmp_path)
    _fresh_arbitrated(tmp_path)
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    dl = next(r for r in results if r.name == "dl_forecasts")
    assert dl.ok is False
    assert dl.critical is False


# ---------------------------------------------------------------------------
# 4. Malformed files
# ---------------------------------------------------------------------------

def test_ycharts_malformed_json(tmp_path):
    (tmp_path / "ycharts_live.json").write_text("{not valid json", encoding="utf-8")
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    yc = next(r for r in results if r.name == "ycharts_scrape")
    assert yc.ok is False
    assert yc.status == "malformed"


def test_ycharts_missing_scrape_date_field(tmp_path):
    _write(tmp_path / "ycharts_live.json", {"funds": {}})  # valid JSON, no scrape_date
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    yc = next(r for r in results if r.name == "ycharts_scrape")
    assert yc.ok is False
    assert yc.status == "malformed"
    assert "scrape_date" in yc.detail


def test_ycharts_bad_date_format(tmp_path):
    _write(tmp_path / "ycharts_live.json", {"scrape_date": "June 5 2026"})
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    yc = next(r for r in results if r.name == "ycharts_scrape")
    assert yc.ok is False
    assert yc.status == "malformed"


def test_arbitrated_malformed_json(tmp_path):
    _fresh_ycharts(tmp_path)
    _fresh_features(tmp_path)
    (tmp_path / "market_data_arbitrated.json").write_text("{bad", encoding="utf-8")
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    arb = next(r for r in results if r.name == "arbitrated")
    assert arb.ok is False
    assert arb.status == "malformed"


# ---------------------------------------------------------------------------
# 5. Market-closed
# ---------------------------------------------------------------------------

def test_arbitrated_skipped_when_market_closed(tmp_path):
    _fresh_ycharts(tmp_path)
    _fresh_features(tmp_path)
    # No arbitrated file — market closed so check must be skipped, not failed
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_CLOSED)
    arb = next(r for r in results if r.name == "arbitrated")
    assert arb.ok is True
    assert arb.status == "skipped"


def test_enrichment_skipped_when_market_closed(tmp_path):
    # No enrichment file — market closed so check must be skipped, not failed
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_CLOSED)
    enr = next(r for r in results if r.name == "enrichment")
    assert enr.ok is True
    assert enr.status == "skipped"


def test_ycharts_stale_still_fails_when_market_closed(tmp_path):
    # Age-window check runs regardless of market_open — a frozen scraper
    # must be visible even on weekends/holidays.
    _fresh_ycharts(tmp_path, scrape_date="2026-06-05")  # 5 days old
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_CLOSED)
    yc = next(r for r in results if r.name == "ycharts_scrape")
    assert yc.ok is False
    assert yc.status == "stale"


# ---------------------------------------------------------------------------
# 6. warn-only vs enforce
# ---------------------------------------------------------------------------

def test_gate_none_when_enforce_off_despite_critical_fail(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_FRESHNESS_ENFORCE", "0")
    _fresh_ycharts(tmp_path, scrape_date="2026-06-05")  # stale critical
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    assert df.gate_message(results) is None
    # Warn lines are still emitted
    warns = df.warn_lines(results)
    assert any("ycharts_scrape" in w for w in warns)
    assert any("CRITICAL" in w for w in warns)


def test_gate_blocks_when_enforce_on_and_critical_fail(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_FRESHNESS_ENFORCE", "1")
    _fresh_ycharts(tmp_path, scrape_date="2026-06-05")  # stale critical
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    msg = df.gate_message(results)
    assert msg is not None
    assert "[BLOCK]" in msg
    assert "ycharts_scrape" in msg
    assert "DATA_FRESHNESS_ENFORCE=0" in msg


def test_gate_none_when_only_optional_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_FRESHNESS_ENFORCE", "1")
    # All critical checks pass; optional files absent
    _fresh_ycharts(tmp_path)
    _fresh_features(tmp_path)
    _fresh_arbitrated(tmp_path)
    # enrichment/economic_calendar/dl_forecasts are all absent (optional)
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    assert df.gate_message(results) is None


def test_warn_lines_include_optional_failures(tmp_path):
    _fresh_ycharts(tmp_path)
    _fresh_features(tmp_path)
    _fresh_arbitrated(tmp_path)
    # enrichment missing (optional)
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    warns = df.warn_lines(results)
    assert any("enrichment" in w for w in warns)
    assert any("OPTIONAL" in w for w in warns)


def test_warn_lines_empty_when_all_pass(tmp_path):
    _all_fresh(tmp_path)
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    assert df.warn_lines(results) == []


# ---------------------------------------------------------------------------
# 7. Report writer
# ---------------------------------------------------------------------------

def test_write_report_produces_valid_json(tmp_path):
    _all_fresh(tmp_path)
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    report_path = tmp_path / "data_freshness.json"
    df.write_report(results, today=TODAY, path=report_path)
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert "ts" in payload
    assert payload["today"] == TODAY
    assert isinstance(payload["enforce"], bool)
    assert isinstance(payload["results"], list)
    assert all("name" in r and "ok" in r and "status" in r for r in payload["results"])


def test_write_report_swallows_failure(tmp_path, monkeypatch, capsys):
    def _raise_on_replace(self, target):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", _raise_on_replace)
    # Must not raise
    df.write_report([], today=TODAY, path=tmp_path / "out.json")
    captured = capsys.readouterr()
    assert "report write failed" in captured.out


# ---------------------------------------------------------------------------
# 8. Utility + invariants
# ---------------------------------------------------------------------------

def test_run_checks_returns_six_results(tmp_path):
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    assert len(results) == 6


def test_run_checks_never_raises_on_empty_dir(tmp_path):
    # Should not raise; every check handles missing files gracefully
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    assert isinstance(results, list)


def test_enforce_enabled_reads_env_at_call_time(monkeypatch):
    monkeypatch.setenv("DATA_FRESHNESS_ENFORCE", "1")
    assert df.enforce_enabled() is True
    monkeypatch.setenv("DATA_FRESHNESS_ENFORCE", "0")
    assert df.enforce_enabled() is False
    monkeypatch.delenv("DATA_FRESHNESS_ENFORCE", raising=False)
    assert df.enforce_enabled() is False


def test_max_age_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("FRESH_YCHARTS_MAX_AGE_DAYS", "1")
    # scrape_date 2 days ago, max_age now 1 → should fail
    _fresh_ycharts(tmp_path, scrape_date="2026-06-08")  # 2 days old
    results = df.run_checks(data_dir=tmp_path, today=TODAY, market_open=MARKET_OPEN)
    yc = next(r for r in results if r.name == "ycharts_scrape")
    assert yc.ok is False
    assert yc.status == "stale"
