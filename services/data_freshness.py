"""Data freshness checks for the daily pipeline (PR D).

Guards against stale data inputs silently producing reports — the root cause of
the 2026-06-01 incident where models consumed frozen YCharts fund metrics for 24+
days with no blocking gate.

Design:
  - run_checks() returns a list of CheckResult. All params are injectable for tests.
  - gate_message() returns a [BLOCK] string ONLY when DATA_FRESHNESS_ENFORCE=1 AND
    a *critical* check failed. Optional checks never block.
  - warn_lines() returns warn lines for every failing check regardless of enforce.
  - write_report() persists results to data/data_freshness.json for /api/health to
    surface. Never raises — pipeline must not abort due to a report write failure.
  - /api/health reads the persisted report; it does NOT re-run checks on the server
    (mtime-based checks are laptop-side only; scp does not preserve mtimes).

Deployment mode:
  DATA_FRESHNESS_ENFORCE=0  warn-only (default). Observe the first run;
  DATA_FRESHNESS_ENFORCE=1  critical failures block the email send (exit 1 from
                             send_email.py, which causes run_daily to abort and alert).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

_BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = _BASE_DIR / "data"

_ENFORCE_ENV = "DATA_FRESHNESS_ENFORCE"
_MAX_AGE_ENV = "FRESH_YCHARTS_MAX_AGE_DAYS"
_DEFAULT_MAX_AGE_DAYS = 3


@dataclass
class CheckResult:
    name: str
    critical: bool
    ok: bool
    detail: str
    status: str  # "fresh" | "stale" | "missing" | "malformed" | "skipped"


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def enforce_enabled() -> bool:
    """True when DATA_FRESHNESS_ENFORCE=1. Read at call-time so tests can monkeypatch."""
    return os.getenv(_ENFORCE_ENV, "0").strip() == "1"


def _max_age_days() -> int:
    try:
        return int(os.getenv(_MAX_AGE_ENV, str(_DEFAULT_MAX_AGE_DAYS)))
    except Exception:
        return _DEFAULT_MAX_AGE_DAYS


def _today_cst() -> str:
    """Today in YYYY-MM-DD Central Time (matches send_email.py TZ)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Chicago")).strftime("%Y-%m-%d")
    except Exception:
        return date.today().isoformat()


def _market_open_default() -> bool:
    try:
        import holidays as _hol
        today = date.today()
        return today.weekday() < 5 and today not in _hol.US()
    except Exception:
        return date.today().weekday() < 5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> tuple:
    """Return (data_or_None, status_str). status: 'ok' | 'missing' | 'malformed'."""
    if not path.exists():
        return None, "missing"
    try:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh), "ok"
    except Exception:
        return None, "malformed"


def _file_age_days(path: Path, today_d: date) -> Optional[int]:
    """Calendar days between file mtime-date and today_d. None if stat fails."""
    try:
        mtime_d = datetime.fromtimestamp(path.stat().st_mtime).date()
        return (today_d - mtime_d).days
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_ycharts_scrape(data_dir: Path, today_str: str, max_age: int) -> CheckResult:
    path = data_dir / "ycharts_live.json"
    data, load_status = _load_json(path)
    if load_status != "ok":
        return CheckResult("ycharts_scrape", True, False,
                           f"ycharts_live.json {load_status}", load_status)
    scrape_date = (data or {}).get("scrape_date", "")
    if not scrape_date:
        return CheckResult("ycharts_scrape", True, False,
                           "ycharts_live.json missing scrape_date field", "malformed")
    try:
        age = (date.fromisoformat(today_str) - date.fromisoformat(scrape_date)).days
    except Exception:
        return CheckResult("ycharts_scrape", True, False,
                           f"scrape_date {scrape_date!r} is not YYYY-MM-DD", "malformed")
    if age > max_age:
        return CheckResult("ycharts_scrape", True, False,
                           f"scrape_date {scrape_date} is {age} day(s) old (max {max_age})", "stale")
    return CheckResult("ycharts_scrape", True, True,
                       f"scrape_date {scrape_date} ({age} day(s) old)", "fresh")


def _check_features_csv(data_dir: Path, today_str: str, max_age: int) -> CheckResult:
    path = data_dir / "features_from_ycharts.csv"
    if not path.exists():
        return CheckResult("features_csv", True, False,
                           "features_from_ycharts.csv missing", "missing")
    age = _file_age_days(path, date.fromisoformat(today_str))
    if age is None:
        return CheckResult("features_csv", True, True,
                           "features_from_ycharts.csv exists (mtime unavailable)", "fresh")
    if age > max_age:
        return CheckResult("features_csv", True, False,
                           f"features_from_ycharts.csv is {age} day(s) old (max {max_age})", "stale")
    return CheckResult("features_csv", True, True,
                       f"features_from_ycharts.csv ({age} day(s) old)", "fresh")


def _check_arbitrated(data_dir: Path, today_str: str, market_open: bool) -> CheckResult:
    if not market_open:
        return CheckResult("arbitrated", True, True,
                           "market closed — arbitration check skipped", "skipped")
    path = data_dir / "market_data_arbitrated.json"
    data, load_status = _load_json(path)
    if load_status != "ok":
        return CheckResult("arbitrated", True, False,
                           f"market_data_arbitrated.json {load_status}", load_status)
    arb_date = (data or {}).get("arbitrated_date", "")
    if not arb_date:
        return CheckResult("arbitrated", True, False,
                           "market_data_arbitrated.json missing arbitrated_date field", "malformed")
    if arb_date != today_str:
        return CheckResult("arbitrated", True, False,
                           f"arbitrated_date {arb_date!r} != today {today_str!r}", "stale")
    return CheckResult("arbitrated", True, True,
                       f"arbitrated_date {arb_date}", "fresh")


def _check_enrichment(data_dir: Path, today_str: str, market_open: bool) -> CheckResult:
    if not market_open:
        return CheckResult("enrichment", False, True,
                           "market closed — enrichment check skipped", "skipped")
    path = data_dir / "enrichment.json"
    if not path.exists():
        return CheckResult("enrichment", False, False,
                           "enrichment.json missing", "missing")
    age = _file_age_days(path, date.fromisoformat(today_str))
    if age is not None and age > 1:
        return CheckResult("enrichment", False, False,
                           f"enrichment.json is {age} day(s) old (expected <=1)", "stale")
    return CheckResult("enrichment", False, True,
                       f"enrichment.json ({age if age is not None else '?'} day(s) old)", "fresh")


def _check_economic_calendar(data_dir: Path, today_str: str) -> CheckResult:
    path = data_dir / "economic_calendar.json"
    data, load_status = _load_json(path)
    if load_status != "ok":
        return CheckResult("economic_calendar", False, False,
                           f"economic_calendar.json {load_status}", load_status)
    events = (data or {}).get("events", [])
    future = [e for e in events if isinstance(e, dict) and e.get("date", "") >= today_str]
    if not future:
        return CheckResult("economic_calendar", False, False,
                           f"no events on/after {today_str} in economic_calendar.json", "stale")
    return CheckResult("economic_calendar", False, True,
                       f"{len(future)} event(s) on/after {today_str}", "fresh")


def _check_dl_forecasts(data_dir: Path, today_str: str) -> CheckResult:
    path = data_dir / "dl_forecasts.csv"
    if not path.exists():
        return CheckResult("dl_forecasts", False, False,
                           "dl_forecasts.csv missing", "missing")
    age = _file_age_days(path, date.fromisoformat(today_str))
    if age is not None and age > 2:
        return CheckResult("dl_forecasts", False, False,
                           f"dl_forecasts.csv is {age} day(s) old (expected <=2)", "stale")
    return CheckResult("dl_forecasts", False, True,
                       f"dl_forecasts.csv ({age if age is not None else '?'} day(s) old)", "fresh")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_checks(
    *,
    data_dir: Optional[Path] = None,
    today: Optional[str] = None,
    market_open: Optional[bool] = None,
) -> list:
    """Run all freshness checks. Returns list[CheckResult]. Never raises."""
    _data_dir = data_dir if data_dir is not None else DATA_DIR
    _today = today if today is not None else _today_cst()
    _mkt = market_open if market_open is not None else _market_open_default()
    _max_age = _max_age_days()

    results: list[CheckResult] = []
    checks = [
        lambda: _check_ycharts_scrape(_data_dir, _today, _max_age),
        lambda: _check_features_csv(_data_dir, _today, _max_age),
        lambda: _check_arbitrated(_data_dir, _today, _mkt),
        lambda: _check_enrichment(_data_dir, _today, _mkt),
        lambda: _check_economic_calendar(_data_dir, _today),
        lambda: _check_dl_forecasts(_data_dir, _today),
    ]
    for fn in checks:
        try:
            results.append(fn())
        except Exception as exc:
            results.append(CheckResult("unknown", False, False,
                                       f"check raised unexpectedly: {exc}", "malformed"))
    return results


def gate_message(results: list) -> Optional[str]:
    """Return a [BLOCK] string if enforce=1 AND any critical check failed, else None.
    Optional checks never contribute to a block even when enforce is on."""
    if not enforce_enabled():
        return None
    failing = [r for r in results if r.critical and not r.ok]
    if not failing:
        return None
    names = ", ".join(r.name for r in failing)
    details = "; ".join(r.detail for r in failing)
    return (
        f"[BLOCK] Data freshness gate failed ({names}): {details}. "
        f"Set DATA_FRESHNESS_ENFORCE=0 to demote to warn-only."
    )


def warn_lines(results: list) -> list:
    """One [WARN][DATA-FRESHNESS] line per failing check (critical or optional)."""
    lines = []
    for r in results:
        if not r.ok and r.status != "skipped":
            tier = "CRITICAL" if r.critical else "OPTIONAL"
            lines.append(f"[WARN][DATA-FRESHNESS][{tier}] {r.name}: {r.detail}")
    return lines


def write_report(
    results: list,
    today: Optional[str] = None,
    path: Optional[Path] = None,
) -> None:
    """Write data/data_freshness.json with a summary of results. Never raises."""
    _path = path if path is not None else (DATA_DIR / "data_freshness.json")
    try:
        _path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "today": today if today is not None else _today_cst(),
            "enforce": enforce_enabled(),
            "results": [asdict(r) for r in results],
        }
        tmp = _path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(_path)
    except Exception as exc:
        print(f"[data_freshness] (report write failed: {exc})")
