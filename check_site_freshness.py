"""check_site_freshness.py — verify the LIVE public site is not serving stale analysis.

Background: the daily report is generated + emailed from the laptop, but the public
site is only updated when post_run.py's sync runs. If sync is skipped, the email is
fresh while the website silently serves week-old analysis. This script makes that
failure loud: it reads the live /api/commentary and checks report_date == today on
market days.

Designed to be both imported (for tests) and run as a CLI. The network fetch and the
market-open / today calculations are injectable so the core logic is testable offline.

Exit codes (CLI):
  0  site is fresh, or market is closed (staleness not expected)
  2  site is STALE or unreachable on a market day
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from typing import Callable, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

try:
    import holidays as _holidays
except Exception:  # pragma: no cover
    _holidays = None

DEFAULT_URL = "https://epm-market-intelligence.com/api/commentary"
# Match send_email.py's reporting timezone (US Central) so "today" is consistent
# with how report_date is stamped by the pipeline.
_REPORT_TZ = "America/Chicago"


def today_str(tz: str = _REPORT_TZ) -> str:
    if ZoneInfo is not None:
        try:
            return datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d")
        except Exception:
            pass
    return date.today().isoformat()


def market_is_open(d: Optional[date] = None) -> bool:
    """US equity trading day: weekday and not a US market holiday."""
    d = d or date.today()
    if d.weekday() >= 5:
        return False
    if _holidays is not None:
        try:
            return d not in _holidays.US()
        except Exception:
            return True
    return True


def _fetch_report_date(url: str, timeout: int = 15) -> Optional[str]:
    """GET the commentary JSON and return its report_date, or None on any failure."""
    try:
        import requests
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data.get("report_date") or None


def is_site_fresh(
    url: str = DEFAULT_URL,
    today: Optional[str] = None,
    *,
    fetch: Optional[Callable[[str], Optional[str]]] = None,
    market_open: Optional[bool] = None,
) -> Tuple[bool, str]:
    """Return (fresh, detail).

    - On a closed market day, always (True, ...) — no fresh report is expected.
    - On a market day, fresh iff the live report_date equals `today`.
    """
    today = today or today_str()
    if market_open is None:
        market_open = market_is_open()
    if not market_open:
        return True, "market closed — staleness not expected"

    fetch = fetch or _fetch_report_date
    report_date = fetch(url)
    if not report_date:
        return False, f"could not read report_date from {url} (site unreachable or malformed)"
    if report_date == today:
        return True, f"fresh — site report_date={report_date}"
    return False, f"STALE — site report_date={report_date}, expected {today}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check that the live site is not serving stale analysis.")
    ap.add_argument("--url", default=DEFAULT_URL)
    args = ap.parse_args(argv)

    fresh, detail = is_site_fresh(args.url)
    if fresh:
        print(f"[FRESH] {detail}")
        return 0
    print(f"[STALE] {detail}")
    print("        The public site is NOT showing today's analysis. Re-run the sync "
          "(python post_run.py) and investigate why it was skipped.")
    return 2


if __name__ == "__main__":
    sys.exit(main())
