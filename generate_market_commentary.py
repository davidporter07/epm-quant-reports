"""
generate_market_commentary.py

Generates market-level narrative commentary sections for the EPM Market Report PDF.
Pulls live market data (US equities, global indices, commodities, currencies, bonds),
loads portfolio features, calls Ollama, and merges the result into
data/latest_commentary.json alongside the existing MAG7 commentary fields.

Fields written to latest_commentary.json:
  Narrative:
    pre_market_bullets          list of 4-6 bullet strings (Pre-Market Look)
    equities_commentary         paragraph
    fixed_income_commentary     paragraph
    commodities_commentary      paragraph
    currencies_commentary       paragraph
    economics_commentary        paragraph (economic data releases)
    market_outlook_label        "Bullish" | "Cautious" | "Neutral" | "Bearish"
    market_outlook_rationale    2-sentence explanation
    tactical_outperforming      comma-separated sectors/themes outperforming
    tactical_underperforming    comma-separated sectors/themes underperforming
    asset_class_outlooks        dict: Equities, Fixed Income, Commodities, US Dollar
                                  each has "label" and "rationale"
    portfolio_spotlight_winners list of {ticker, metric_label, commentary}
    portfolio_spotlight_watch   list of {ticker, metric_label, commentary}
  Market data:
    market_snapshot             US key assets (S&P, Nasdaq, DXY, Gold, WTI, 10-Yr)
    global_markets              major global equity indices
    commodities_table           DBC, Gold, Silver, Copper, WTI, Brent, NatGas, RBOB
    currencies_table            DXY, EUR/USD, GBP/USD, USD/JPY, USD/CAD, AUD/USD
    bonds_table                 2yr, 10yr, 30yr yields + 10s2s spread
    report_date                 YYYY-MM-DD
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    from json_repair import repair_json as _repair_json
except ImportError:
    _repair_json = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
from services import runtime_config as _rc

OLLAMA_HOST    = _rc.ollama_url()
OLLAMA_MODEL   = _rc.commentary_model()
OLLAMA_TIMEOUT = int(os.getenv("LOCAL_OLLAMA_TIMEOUT", "900"))

# Topic spotlight: detect dominant news theme, write grounded story with fund tie-ins
TOPIC_SPOTLIGHT_ENABLED = True
MIN_TOPIC_HEADLINES     = 4   # min distinct matching headlines to gate the spotlight in
MIN_TOPIC_SOURCES       = 2   # min distinct sources required
MAX_CRAWL_ARTICLES      = 6   # max article URLs to crawl for fund grounding + analysis excerpts
MAX_SPOTLIGHT_FUNDS     = 5   # max verified funds to cite

ROOT             = Path(__file__).resolve().parent
DATA_DIR         = ROOT / "data"
COMMENTARY_PATH  = DATA_DIR / "latest_commentary.json"

# Core market tickers for pre-market snapshot
MARKET_TICKERS: dict[str, str] = {
    "S&P 500":           "^GSPC",
    "Nasdaq 100":        "^NDX",
    "U.S. Dollar (DXY)": "DX-Y.NYB",
    "Gold":              "GC=F",
    "WTI Crude":         "CL=F",
    "10-Yr Yield":       "^TNX",
}

GLOBAL_TICKERS: dict[str, str] = {
    "Dow Jones":         "^DJI",
    "Russell 2000":      "^RUT",
    "TSX Composite":     "^GSPTSE",
    "Euro Stoxx 50":     "^STOXX50E",
    "FTSE 100":          "^FTSE",
    "Nikkei 225":        "^N225",
    "Hang Seng":         "^HSI",
    "ASX 200":           "^AXJO",
}

COMMODITY_TICKERS: dict[str, str] = {
    "DBC (Cmdty ETF)":   "DBC",
    "Gold":              "GC=F",
    "Silver":            "SI=F",
    "Copper":            "HG=F",
    "WTI Crude":         "CL=F",
    "Brent Crude":       "BZ=F",
    "Natural Gas":       "NG=F",
    "RBOB Gasoline":     "RB=F",
    "Wheat":             "ZW=F",
    "DBA (Ag ETF)":      "DBA",
}

CURRENCY_TICKERS: dict[str, str] = {
    "Dollar Index":      "DX-Y.NYB",
    "EUR/USD":           "EURUSD=X",
    "GBP/USD":           "GBPUSD=X",
    "USD/JPY":           "JPY=X",
    "USD/CAD":           "CAD=X",
    "AUD/USD":           "AUDUSD=X",
    "USD/BRL":           "BRL=X",
    "Bitcoin":           "BTC-USD",
}

BOND_TICKERS: dict[str, str] = {
    "2-Year Yield":      "^IRX",    # 13-wk proxy; override below
    "10-Year Yield":     "^TNX",
    "30-Year Yield":     "^TYX",
}

SECTOR_TICKERS: dict[str, str] = {
    "Technology":        "XLK",
    "Financials":        "XLF",
    "Health Care":       "XLV",
    "Energy":            "XLE",
    "Consumer Discr":    "XLY",
    "Industrials":       "XLI",
    "Consumer Staples":  "XLP",
    "Utilities":         "XLU",
    "Materials":         "XLB",
    "Real Estate":       "XLRE",
    "Communication":     "XLC",
}

# ---------------------------------------------------------------------------
# Market data helpers
# ---------------------------------------------------------------------------
def _last_completed_session(today) -> "date":
    """Most recent NYSE trading day STRICTLY before `today` (skips weekends + holidays).

    Used to decide whether a daily-bar feed is genuinely lagging. In the US-morning run,
    the latest *completed* session is always the prior trading day — today's session has
    not closed yet — so a fresh daily bar should already carry this date. (`_is_us_market_holiday`
    is resolved at call time; defined below.)"""
    from datetime import timedelta as _td
    d = today - _td(days=1)
    for _ in range(10):
        if d.weekday() < 5 and not _is_us_market_holiday(d.isoformat()):
            return d
        d -= _td(days=1)
    return d


def _fetch_quote(ticker: str, days_back: int = 7, prev_close: float | None = None,
                 mode: str = "eod", verify_fresh: bool = False) -> dict | None:
    """Return {level, change, pct_change} for a single ticker, or None.

    mode="eod"  — use completed daily-bar closes only (authoritative yesterday's close).
                  Never returns intraday data — safe to call at any time of day.
    mode="live" — try fast_info first (live intraday), fall back to daily bars.
                  Use for pre-market futures block only.

    verify_fresh=True (eod path, non-rolling symbols only — indices/ETFs, NOT =F futures):
        cross-check the most-recent daily-bar close against Yahoo's official
        fast_info.previous_close. The daily-bar feed can lag the official settle by a full
        session (e.g. ^GSPC not yet posting Monday's bar at a 9am run), silently printing
        Friday's close beside live futures. When the official previous_close reveals a newer
        completed session, roll forward so the snapshot can't show a stale prior close.
    """
    if yf is None:
        return None
    # --- live path: fast_info intraday quote (futures/live tables only) ---
    if mode == "live":
        try:
            fi = yf.Ticker(ticker).fast_info
            last = float(fi.last_price)
            prev_fi = float(fi.previous_close)
            if last > 0 and prev_fi > 0:
                # Prefer Yahoo's official previous_close (the prior settle, already
                # holiday/roll aware). Only fall back to a stored prev_close when it is
                # FRESH — within 0.3% of prev_fi (a consecutive-session run). A stale
                # stored value (skipped run) would span the gap, so we ignore it.
                prev = prev_fi
                if prev_close and prev_close > 0 and abs(prev_close - prev_fi) / prev_fi <= 0.003:
                    prev = prev_close
                change = last - prev
                pct    = (change / prev) * 100
                return {
                    "level":      round(last, 4),
                    "change":     round(change, 4),
                    "pct_change": round(pct, 2),
                }
        except Exception:
            pass
    # --- eod path: completed daily-bar closes (default, all snapshot/table fetchers) ---
    try:
        end   = datetime.today()
        start = end - timedelta(days=days_back)
        data  = yf.download(ticker, start=start, end=end,
                            progress=False, auto_adjust=True)
        if data.empty:
            return None
        closes = data["Close"].dropna()
        if hasattr(closes, "squeeze"):
            closes = closes.squeeze()
        # Drop any bar dated today or later. During an intraday re-run yfinance can
        # return a partial in-progress bar for the current session; including it would
        # mislabel today's live print as "yesterday's close" (same-day rerun corruption).
        try:
            _today = end.date()
            closes = closes[[ts.date() < _today for ts in closes.index]]
        except Exception:
            pass
        if len(closes) < 2:
            return None
        arr    = closes.to_numpy()
        latest = float(arr[-1])               # most recent COMPLETED session
        # The true prior trading session is always arr[-2]. Unlike a stored prev_close
        # it is robust to skipped runs (weekends/holidays): a stored prev_close goes
        # stale across a skipped session and spans the gap, producing wrong-sign or
        # oversized moves (e.g. Brent shown -9.9% after the Memorial Day holiday when it
        # actually rose). Yahoo restitches continuous futures (=F) series, so
        # arr[-2]->arr[-1] is on a consistent contract basis (no roll artifact). Mirrors
        # the fetch_global_markets fix, extended here to commodities/currencies/metals.
        prev   = float(arr[-2])
        # Staleness cross-check for non-rolling symbols (indices/ETFs). Yahoo's
        # fast_info.previous_close is the authoritative most-recent settle and updates
        # promptly; if it reveals a completed session newer than our latest daily bar,
        # roll forward (latest <- official close, prev <- our former latest) so a lagging
        # daily-bar feed can't print a stale prior close next to live futures.
        if verify_fresh:
            try:
                # Roll forward ONLY when the daily bar is genuinely STALE — i.e. it has not
                # yet posted the most recent completed trading session. fast_info.previous_close
                # is normally the authoritative latest settle, but at a pre-market run it can
                # ITSELF lag the daily bar by a session. Rolling on a bare value mismatch then
                # corrupts a FRESH daily bar with a STALE fast_info close — and because the swap
                # moves `latest` into `prev`, it INVERTS the sign. 2026-06-29: Nasdaq 100's true
                # -1.09% Friday close (29,118.24, the fresh daily bar) was flipped to +1.11%
                # (29,440.32, a stale Thursday fast_info.previous_close), fabricating a "tech
                # rally" the tape never had. Gate on a DATE check so the roll fires only for a
                # bar that is actually behind the last completed session.
                latest_date = closes.index[-1].date()
                bar_is_stale = latest_date < _last_completed_session(end.date())
                if bar_is_stale:
                    official_prev = float(yf.Ticker(ticker).fast_info.previous_close)
                    if official_prev > 0 and abs(official_prev - latest) / latest > 0.004:
                        print(f"  [SNAP] {ticker}: daily-bar close {latest:.4f} (dated {latest_date}) "
                              f"is stale vs the last completed session; official previous_close "
                              f"{official_prev:.4f} ({(official_prev-latest)/latest*100:+.2f}%) "
                              f"— rolling forward to the newer session.")
                        prev, latest = latest, official_prev
            except Exception:
                pass
        change = latest - prev
        pct    = (change / prev) * 100
        return {
            "level":      round(latest, 4),
            "change":     round(change, 4),
            "pct_change": round(pct, 2),
        }
    except Exception:
        return None


# Gold sourcing: report SPOT, not COMEX futures. GC=F trades at a contango basis to spot,
# which made the snapshot read off spot-quoting desks (and the Sevens Report) in 2026-06-04/05
# side-by-sides. yfinance's only direct spot symbol (XAUUSD=X) 404s intermittently, so gold
# uses a three-tier fallback (see _fetch_gold_quote):
#   1. XAUUSD=X                — true spot (preferred)
#   2. GLD * calibrated ratio  — physically-backed spot-gold ETF, never 404s; scaled to a spot
#                                level by a ratio that SELF-CALIBRATES off XAUUSD=X whenever
#                                spot is live, so the slowly-drifting oz/share never rots
#   3. GC=F                     — COMEX futures, last resort (contango basis; logged loudly)
GOLD_SPOT_TICKER      = "XAUUSD=X"
GOLD_FUTURES_TICKER   = "GC=F"
GOLD_GLD_PROXY_TICKER = "GLD"
# ~1/0.0913 oz of gold per GLD share today; SEED only — overwritten live from XAUUSD=X/GLD.
GOLD_GLD_RATIO_SEED   = 10.95
GOLD_GLD_RATIO_PATH   = DATA_DIR / "gold_gld_ratio.json"


def _load_gld_spot_ratio() -> float:
    """The cached spot/GLD ratio (refreshed whenever XAUUSD=X is live), else the seed.
    Sanity-banded so a corrupt/implausible cache can never poison the gold level."""
    try:
        d = json.loads(GOLD_GLD_RATIO_PATH.read_text(encoding="utf-8"))
        r = float(d.get("ratio"))
        if 8.0 < r < 14.0:
            return r
    except Exception:
        pass
    return GOLD_GLD_RATIO_SEED


def _save_gld_spot_ratio(spot_level: float, gld_level: float) -> None:
    """Persist spot/GLD so a future spot-feed outage can scale GLD back to a spot level.
    Only writes a plausible ratio (8-14); never raises."""
    try:
        if spot_level and gld_level and gld_level > 0:
            ratio = float(spot_level) / float(gld_level)
            if 8.0 < ratio < 14.0:
                GOLD_GLD_RATIO_PATH.write_text(json.dumps({
                    "ratio": round(ratio, 4),
                    "spot_level": round(float(spot_level), 2),
                    "gld_level": round(float(gld_level), 2),
                    "date": datetime.today().strftime("%Y-%m-%d"),
                }, indent=2), encoding="utf-8")
    except Exception:
        pass


def _fetch_gold_quote(prev_close: float | None = None, mode: str = "eod",
                      verify_fresh: bool = False) -> dict | None:
    """Gold {level, change, pct_change, _source}, reporting SPOT via a three-tier fallback.

    1. XAUUSD=X true spot (preferred). On success we ALSO recalibrate the GLD ratio so the
       proxy below stays accurate.
    2. GLD * calibrated ratio — GLD is physically-backed spot gold and never 404s; scaling by
       the self-calibrating spot/GLD ratio yields a spot-level price that tracks spot within
       fees. Scaling preserves the daily %; level and $ change scale by the ratio.
    3. GC=F COMEX futures, last resort (contango basis; logged loudly).
    The eod path computes change off each series' own prior bar (arr[-2]), so every source
    yields a self-consistent same-source move — no cross-source prev_close leak."""
    # 1. True spot — and recalibrate the GLD ratio while we have a live spot print.
    spot = _fetch_quote(GOLD_SPOT_TICKER, prev_close=prev_close, mode=mode, verify_fresh=verify_fresh)
    if spot and spot.get("level"):
        spot["_source"] = GOLD_SPOT_TICKER
        gld_now = _fetch_quote(GOLD_GLD_PROXY_TICKER, mode=mode)
        if gld_now and gld_now.get("level"):
            _save_gld_spot_ratio(spot["level"], gld_now["level"])
        return spot
    # 2. GLD-derived spot proxy — closest spot-level number when the direct feed is down.
    gld = _fetch_quote(GOLD_GLD_PROXY_TICKER, mode=mode, verify_fresh=verify_fresh)
    if gld and gld.get("level"):
        ratio = _load_gld_spot_ratio()
        proxy = {
            "level":      round(ratio * float(gld["level"]), 2),
            "change":     round(ratio * float(gld.get("change") or 0.0), 2),
            "pct_change": gld.get("pct_change"),
            "_source":    f"GLD*{ratio:.3f}",
        }
        print(f"  [INFO] Gold spot feed ({GOLD_SPOT_TICKER}) unavailable — using calibrated "
              f"GLD-derived spot {proxy['level']} (ratio {ratio:.3f}); tracks spot within fees.")
        return proxy
    # 3. Futures last resort — loud, because it reads off spot-quoting desks.
    fut = _fetch_quote(GOLD_FUTURES_TICKER, prev_close=prev_close, mode=mode)
    if fut and fut.get("level"):
        fut["_source"] = GOLD_FUTURES_TICKER
        print(f"  [WARN] Gold spot AND GLD proxy unavailable — using COMEX futures "
              f"({GOLD_FUTURES_TICKER}) at {fut.get('level')}. Futures carry a contango basis, "
              f"so today's gold level may read ~$30-40 off spot-quoting desks.")
    return fut


def _gold_tier_rank(q: dict | None) -> int:
    """Rank a gold quote by source tier: spot (0) < GLD proxy (1) < COMEX futures (2).
    A higher tier carries a contango basis / staleness risk, so the lower-ranked quote
    is the one to trust when the snapshot and commodities table disagree. Unknown or
    missing source sorts last."""
    src = str((q or {}).get("_source") or "")
    if src == GOLD_FUTURES_TICKER:
        return 2
    if src.startswith("GLD*"):
        return 1
    if src == GOLD_SPOT_TICKER:
        return 0
    return 3


def _reconcile_gold(snapshot: dict, commodities_tbl: dict) -> dict | None:
    """Force the snapshot and commodities table to share ONE gold quote.

    Both tables fetch gold independently through the three-tier spot/proxy/futures
    fallback, with different prev_close baselines. When the intermittent XAUUSD=X spot
    feed 404s for one call but not the other, the two land on different tiers and diverge
    in BOTH level and sign — 2026-06-18: snapshot $4,300 +1.06% (it fell to COMEX futures,
    contango-inflated) vs commodities table $4,255 -2.27% (spot, the correct read), truth
    ≈ -2%. Pick the better-tier quote (spot > GLD proxy > futures) and mirror it into both
    so the snapshot, prose, and commodities table can never disagree. Returns the canonical
    quote, or None when gold is absent from either table."""
    gs = snapshot.get("Gold") if isinstance(snapshot, dict) else None
    gt = commodities_tbl.get("Gold") if isinstance(commodities_tbl, dict) else None
    if not (isinstance(gs, dict) and isinstance(gt, dict)):
        return None
    canonical = gs if _gold_tier_rank(gs) <= _gold_tier_rank(gt) else gt
    snapshot["Gold"]        = dict(canonical)
    commodities_tbl["Gold"] = dict(canonical)
    return canonical


def _is_us_market_holiday(date_str: str) -> bool:
    """True when date_str (YYYY-MM-DD) is a US EQUITY-MARKET holiday (NYSE/Nasdaq closed).

    Uses the `holidays` library's NYSE financial calendar — NOT the federal calendar, which
    over-filters (the NYSE is OPEN on Columbus/Veterans Day). Non-failing: returns False if
    the library is unavailable or the date can't be parsed.

    2026-06-18: the report looked ahead to "Friday's Philly Fed" when Fri 6/19 was Juneteenth
    (market closed) and Philly Fed had already printed Thursday. Calendar feeds happily list a
    release on a closed day, so we drop holiday-dated events before they reach the scenario
    picker / what-to-watch."""
    try:
        from datetime import date as _date
        import holidays as _holidays
        d = _date.fromisoformat(str(date_str)[:10])
        try:
            cal = _holidays.financial_holidays("NYSE")
        except Exception:
            cal = _holidays.US()   # fallback: federal calendar (over-filters Columbus/Veterans)
        return d in cal
    except Exception:
        return False


def _event_day_from_dates(event_date: str, today_date: str) -> str:
    """Human day label for an event relative to today: 'today', 'tomorrow', or weekday.

    Used so a forward-looking scenario built on a future catalyst (e.g. Thursday's GDP
    report selected on a Wednesday) is labelled by its real day instead of "today".
    """
    try:
        ed = datetime.strptime(str(event_date)[:10], "%Y-%m-%d").date()
        td = datetime.strptime(str(today_date)[:10], "%Y-%m-%d").date()
    except Exception:
        return ""
    delta = (ed - td).days
    if delta <= 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    return ed.strftime("%A")   # e.g. "Thursday"


def _catalyst_priority(event_name: str) -> int:
    """Rank for scenario-event selection when events share the soonest date: the
    bigger market mover wins (FOMC decision > CPI/Jobs > PPI/PCE > Retail Sales >
    jobless claims > everything else). Lower = higher priority.

    2026-06-15: the Warsh FOMC decision and Retail Sales both fell on 6/17; the
    rate decision must anchor the scenarios, not the retail print.
    """
    n = (event_name or "").lower()
    if "fomc" in n and "minutes" in n:
        return 1                                   # minutes rank below the decision
    if "fomc" in n or "rate decision" in n:
        return 0
    if "cpi" in n or "non-farm" in n or "payroll" in n or "jobs report" in n:
        return 1
    if "ppi" in n or "pce" in n or "personal income" in n:
        return 2
    if "retail sales" in n:
        return 3
    if "jobless claims" in n:
        return 4
    return 6


def _prev_level(prev_data: dict | None, name: str) -> float | None:
    """Extract the stored previous level for a named instrument, or None."""
    if not prev_data:
        return None
    try:
        val = float(prev_data.get(name, {}).get("level") or 0)
        return val if val > 0 else None
    except Exception:
        return None


def _guard_snapshot_drift(new_snapshot: dict, prev_path: "Path") -> None:
    """Warn loudly if same-session re-run produces materially different levels.

    A >1% level shift for the same report_date almost certainly means a bad
    data fetch (e.g. intraday print mis-labeled as a prior close). Prints a
    warning but does NOT block the write — the alert is enough to catch issues
    during the daily review.
    """
    try:
        if not prev_path.exists():
            return
        import json as _json
        prev_full = _json.loads(prev_path.read_text(encoding="utf-8"))
        prev_snap = prev_full.get("market_snapshot", {})
        # Only compare if both describe the same session date
        if prev_full.get("report_date") != datetime.today().strftime("%Y-%m-%d"):
            return
        _DRIFT_KEYS = ("S&P 500", "Nasdaq 100", "Gold", "10-Yr Yield")
        for key in _DRIFT_KEYS:
            old = (prev_snap.get(key) or {}).get("level")
            new = (new_snapshot.get(key) or {}).get("level")
            if old and new and old > 0 and abs(new - old) / old > 0.01:
                print(
                    f"[WARN] Snapshot drift guard: {key} shifted {old:.4f} → {new:.4f} "
                    f"({(new-old)/old*100:+.2f}%) within same session. "
                    f"Possible bad fast_info read — verify data before trusting."
                )
    except Exception:
        pass


def fetch_market_snapshot(prev_data: dict | None = None) -> dict[str, dict]:
    result: dict[str, dict] = {}
    # Cross-check daily-bar freshness against the live official close for non-rolling
    # symbols (indices/ETFs). NOT the =F futures (WTI), whose roll handling relies on the
    # same-series arr[-2] prev and must not be second-guessed by fast_info.
    _verify_fresh_names = {"S&P 500", "Nasdaq 100", "U.S. Dollar (DXY)", "10-Yr Yield", "Gold"}
    for name, ticker in MARKET_TICKERS.items():
        _vf = name in _verify_fresh_names
        # Gold reports spot (XAUUSD=X) with a futures fallback so the snapshot matches the
        # spot convention; everything else uses its mapped ticker directly.
        if name == "Gold":
            q = _fetch_gold_quote(prev_close=_prev_level(prev_data, name), verify_fresh=_vf)
        else:
            q = _fetch_quote(ticker, prev_close=_prev_level(prev_data, name), verify_fresh=_vf)
        if q:
            result[name] = q
    return result


# Asian CASH indices: yfinance's daily-bar feed (history/download) lags ~1 session
# for these, but the exchange has long since CLOSED by the time the pipeline runs in
# the US morning, so fast_info.last_price already holds the true latest completed
# close — the same session Sevens reports. (European indices are deliberately NOT in
# this set: they are still OPEN at the US-morning run, so their fast_info would be a
# live intraday tick, not a settled close.)
_ASIAN_INDEX_TICKERS = {"^N225", "^HSI", "^AXJO"}


def _reconcile_asian_index_close(ticker: str, q: dict, *, now_utc=None) -> dict:
    """Roll an Asian index forward to its latest SETTLED close when the daily bar lags.

    2026-06-26: the Nikkei daily bar carried the 6/25 Tokyo close (+4.61%) while the
    actual 6/26 close was -4.15% (the value Sevens printed). The fresh close sits in
    fast_info.last_price; adopt it as the level, keeping the daily bar (q['level']) as
    the prior session so the % move matches. Gated to 08:00-22:00 UTC, the window in
    which Tokyo/Hong Kong/Sydney are all closed, so an in-session intraday tick can
    never be mistaken for a settled close. Shape-preserving; never raises.
    """
    try:
        from datetime import datetime as _dt, timezone as _tz
        hour = (now_utc or _dt.now(_tz.utc)).hour
        if not (8 <= hour < 22):
            return q
        prior = q.get("level")
        if not prior:
            return q
        last = getattr(yf.Ticker(ticker).fast_info, "last_price", None)
        if last is None:
            return q
        last = float(last)
        # Adopt only a DIFFERENT, sane session (a newer close not yet in the daily
        # bars). The sanity band rejects a garbage quote; the 0.05% floor ignores
        # rounding noise when the daily bar is already current.
        if 0.5 < last / prior < 2.0 and abs(last / prior - 1) > 0.0005:
            q = dict(q)
            q["level"] = round(last, 4)
            q["change"] = round(last - prior, 4)
            q["pct_change"] = round((last / prior - 1) * 100, 2)
        return q
    except Exception:
        return q


def fetch_global_markets(prev_data: dict | None = None) -> dict[str, dict]:
    # NOTE: unlike commodities/futures, global equity INDICES do not roll contracts, so
    # the stored prev_close mechanism (designed for BZ=F/CL=F/GC=F roll protection) is the
    # wrong reference here — when a run is skipped (weekend/holiday) the stored level is
    # several sessions stale, producing gap artifacts (e.g. Nikkei "+5.37%" or a 0.00%
    # change when stored == latest). The true prior session is always _fetch_quote's
    # arr[-2], which is robust to skipped runs. `prev_data` is accepted for call-site
    # compatibility but intentionally not used as prev_close.
    _ = prev_data
    result: dict[str, dict] = {}
    for name, ticker in GLOBAL_TICKERS.items():
        q = _fetch_quote(ticker)
        if q:
            if ticker in _ASIAN_INDEX_TICKERS:
                q = _reconcile_asian_index_close(ticker, q)
            result[name] = q
    return result


def fetch_commodities_table(prev_data: dict | None = None) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for name, ticker in COMMODITY_TICKERS.items():
        # Keep Gold on the same spot source as the snapshot so the two tables never disagree
        # by the futures basis (would re-open the 2026-06-01-style snapshot↔table split).
        if name == "Gold":
            q = _fetch_gold_quote(prev_close=_prev_level(prev_data, name))
        else:
            q = _fetch_quote(ticker, prev_close=_prev_level(prev_data, name))
        if q:
            result[name] = q
    return result


def fetch_currencies_table(prev_data: dict | None = None) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for name, ticker in CURRENCY_TICKERS.items():
        q = _fetch_quote(ticker, prev_close=_prev_level(prev_data, name))
        if q:
            result[name] = q
    return result


FUTURES_TICKERS: dict[str, str] = {
    "S&P 500 Futures":      "ES=F",
    "Nasdaq 100 Futures":   "NQ=F",
    "Dow Futures":          "YM=F",
    "Russell 2000 Futures": "RTY=F",
}


def fetch_futures_table(prev_data: dict | None = None) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for name, ticker in FUTURES_TICKERS.items():
        q = _fetch_quote(ticker, mode="live", prev_close=_prev_level(prev_data, name))
        if q:
            result[name] = q
    return result


def _fetch_treasury_gov_yields() -> dict[str, dict]:
    """Fetch official US Treasury yield curve data from home.treasury.gov.
    Returns a bonds_table-compatible dict with 2Y, 10Y, 30Y yields and the 10s-2s spread.
    Falls back to an empty dict if the endpoint is unavailable."""
    try:
        import urllib.request
        import xml.etree.ElementTree as ET
        from datetime import datetime, timedelta

        ns = {
            "a": "http://www.w3.org/2005/Atom",
            "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
            "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
        }

        def _fetch_month(ym: str) -> dict:
            url = (
                "https://home.treasury.gov/resource-center/data-chart-center/"
                f"interest-rates/pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value_month={ym}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                root = ET.fromstring(resp.read().decode("utf-8"))
            rows = {}
            for entry in root.findall(".//a:entry", ns):
                props = entry.find(".//m:properties", ns)
                if props is None:
                    continue
                row = {child.tag.split("}")[-1]: child.text for child in props}
                date = (row.get("NEW_DATE") or "")[:10]
                rows[date] = row
            return rows

        today = datetime.today()
        ym_cur  = today.strftime("%Y%m")
        prev_month = (today.replace(day=1) - timedelta(days=1))
        ym_prev = prev_month.strftime("%Y%m")

        rows = _fetch_month(ym_cur)
        if len(rows) < 2:
            rows.update(_fetch_month(ym_prev))

        # Fetch January data for YTD baseline when current/prev months don't cover it
        ym_jan = f"{today.year}01"
        if ym_jan not in (ym_cur, ym_prev):
            rows.update(_fetch_month(ym_jan))

        sorted_dates = sorted(rows.keys())
        if len(sorted_dates) < 2:
            return {}

        today_row = rows[sorted_dates[-1]]
        prev_row  = rows[sorted_dates[-2]]
        week_row  = rows[sorted_dates[-6]] if len(sorted_dates) >= 6 else None
        jan_dates = [d for d in sorted_dates if d.startswith(str(today.year))]
        ytd_row   = rows[jan_dates[0]] if jan_dates else None

        def _get_val(row: dict | None, field: str) -> float | None:
            if row is None:
                return None
            try:
                return float(row[field])
            except Exception:
                return None

        def _build(field: str) -> dict | None:
            try:
                cur  = float(today_row[field])
                prev = float(prev_row[field])
                chg  = round(cur - prev, 3)
                pct  = round(chg / prev * 100, 2) if prev else None
                entry: dict = {"level": cur, "change": chg, "pct_change": pct}
                wk = _get_val(week_row, field)
                if wk is not None:
                    entry["bp_change_1w"] = round((cur - wk) * 100, 1)
                yt = _get_val(ytd_row, field)
                if yt is not None:
                    entry["bp_change_ytd"] = round((cur - yt) * 100, 1)
                return entry
            except Exception:
                return None

        result: dict[str, dict] = {}
        for name, field in [
            ("2-Year Yield",  "BC_2YEAR"),
            ("10-Year Yield", "BC_10YEAR"),
            ("30-Year Yield", "BC_30YEAR"),
        ]:
            entry = _build(field)
            if entry:
                result[name] = entry

        y10     = result.get("10-Year Yield", {}).get("level")
        y2      = result.get("2-Year Yield",  {}).get("level")
        y10_chg = result.get("10-Year Yield", {}).get("change")
        y2_chg  = result.get("2-Year Yield",  {}).get("change")
        if y10 is not None and y2 is not None:
            spread_chg = None
            if y10_chg is not None and y2_chg is not None:
                spread_chg = round((y10_chg - y2_chg) * 100, 1)
            spread_entry: dict = {
                "level": round((y10 - y2) * 100, 1),
                "change": spread_chg,
                "pct_change": None,
            }
            y10_1w = result.get("10-Year Yield", {}).get("bp_change_1w")
            y2_1w  = result.get("2-Year Yield",  {}).get("bp_change_1w")
            if y10_1w is not None and y2_1w is not None:
                spread_entry["bp_change_1w"] = round(y10_1w - y2_1w, 1)
            y10_yt = result.get("10-Year Yield", {}).get("bp_change_ytd")
            y2_yt  = result.get("2-Year Yield",  {}).get("bp_change_ytd")
            if y10_yt is not None and y2_yt is not None:
                spread_entry["bp_change_ytd"] = round(y10_yt - y2_yt, 1)
            result["10s-2s Spread"] = spread_entry
        return result

    except Exception as exc:
        print(f"[WARN] Treasury.gov fetch failed: {exc}")
        return {}


def fetch_bonds_table() -> dict[str, dict]:
    # Primary: official US Treasury yield curve (always accurate, no API key needed)
    result = _fetch_treasury_gov_yields()
    if result:
        return result

    # Fallback: yfinance (less reliable for Treasury data)
    result = {}
    bond_map = {
        "10-Year Yield": "^TNX",
        "30-Year Yield": "^TYX",
    }
    for name, ticker in bond_map.items():
        q = _fetch_quote(ticker)
        if q:
            result[name] = q

    y10 = result.get("10-Year Yield", {}).get("level")
    y2  = result.get("2-Year Yield",  {}).get("level")
    if y10 is not None and y2 is not None:
        spread_bp = round((y10 - y2) * 100, 1)
        result["10s-2s Spread"] = {"level": spread_bp, "change": None, "pct_change": None}

    return result


# Treasury.gov publishes the daily curve with a lag: on some mornings its latest XML row is
# still the PRIOR session. 2026-07-01: it carried 6/29's 10Y=4.372 as "latest" while the 6/30
# close was ~4.44, and _fetch_treasury_gov_yields blindly takes sorted_dates[-1] as today. That
# stale row was synced into the snapshot + narrative and INVERTED the rates story ("yield fell
# 2 bp" when it actually rose ~6 bp). The arbitrated curve (YCharts primary, written by
# data_arbiter) had the fresh level, so cross-check against it: when the arbitrated level is
# fresh and materially diverges from Treasury.gov's, adopt the arbitrated level and treat the
# stale Treasury.gov value as the prior session (its lag is exactly one session), which recovers
# the correct daily change. Same "prefer the fresh source, reconcile the laggard" philosophy as
# _reconcile_asian_index_close.
_YIELD_RECON_TENORS = ("2-Year Yield", "10-Year Yield", "30-Year Yield")
_YIELD_DIVERGE_BP = 0.02      # >2 bp gap ⇒ Treasury.gov is stale, not rounding noise
_YIELD_MAX_DAILY  = 0.50      # >50 bp/day ⇒ artefact, don't apply


def _adopt_arbitrated_change(bonds_tbl: dict, name: str, tsy: dict, arb: dict) -> bool:
    """Levels agree but the reported DAILY bp CHANGE diverges (each source computes it off
    its own prior close). Adopt the authoritative arbitrated (YCharts) change + pct_change so
    the recap's "rose N bp" matches our curve. Mutates bonds_tbl; returns True if it changed."""
    try:
        arb_chg = float(arb.get("change"))
    except (TypeError, ValueError):
        return False
    if abs(arb_chg) > _YIELD_MAX_DAILY:
        return False
    try:
        tsy_chg = float(tsy.get("change"))
    except (TypeError, ValueError):
        tsy_chg = None
    if tsy_chg is not None and abs(arb_chg - tsy_chg) <= _YIELD_DIVERGE_BP:
        return False  # changes already agree within rounding — leave it
    new = dict(tsy)
    new["change"] = round(arb_chg, 3)
    try:
        new["pct_change"] = round(float(arb.get("pct_change")), 2)
    except (TypeError, ValueError):
        try:
            prev = float(new.get("level")) - arb_chg
            new["pct_change"] = round(arb_chg / prev * 100, 2) if prev else None
        except (TypeError, ValueError):
            new["pct_change"] = None
    new["_reconciled"] = "arbitrated_change"
    bonds_tbl[name] = new
    return True


def _reconcile_bonds_with_arbitrated(bonds_tbl: dict, arb_curve: dict) -> int:
    """Prefer the fresh arbitrated (YCharts/FRED) yield level over a lagging Treasury.gov row
    for 2Y/10Y/30Y. Mutates bonds_tbl in place; returns the count of tenors corrected. Only the
    caller (which gates on arbitrated freshness) decides whether to invoke this. Never raises."""
    if not isinstance(bonds_tbl, dict) or not isinstance(arb_curve, dict) or not arb_curve:
        return 0
    fixed = 0
    for name in _YIELD_RECON_TENORS:
        arb = arb_curve.get(name)
        if not isinstance(arb, dict) or arb.get("level") is None:
            continue
        try:
            arb_lvl = float(arb["level"])
        except (TypeError, ValueError):
            continue
        tsy = bonds_tbl.get(name)
        if not isinstance(tsy, dict) or tsy.get("level") is None:
            # No Treasury.gov value at all — adopt the arbitrated level/change wholesale.
            bonds_tbl[name] = {"level": round(arb_lvl, 3), "change": arb.get("change"),
                               "pct_change": arb.get("pct_change"), "_reconciled": "arbitrated_curve"}
            fixed += 1
            continue
        try:
            tsy_lvl = float(tsy["level"])
        except (TypeError, ValueError):
            continue
        if abs(arb_lvl - tsy_lvl) <= _YIELD_DIVERGE_BP:
            # Levels agree (Treasury.gov/yfinance fresh) — but the daily bp CHANGE can still
            # diverge off differing prior closes (2026-07-02: 30Y showed +11 bp vs the
            # authoritative +5 bp). Align the change to the arbitrated curve when it does.
            if _adopt_arbitrated_change(bonds_tbl, name, tsy, arb):
                fixed += 1
            continue
        chg = round(arb_lvl - tsy_lvl, 3)
        if abs(chg) > _YIELD_MAX_DAILY:
            continue  # implausible daily move — likely bad data, don't apply
        new = dict(tsy)
        new["level"]      = round(arb_lvl, 3)
        new["change"]     = chg
        new["pct_change"] = round(chg / tsy_lvl * 100, 2) if tsy_lvl else None
        new["_reconciled"] = "arbitrated_curve"
        bonds_tbl[name] = new
        fixed += 1

    if fixed:  # rebuild the 10s-2s spread off the reconciled 2Y/10Y so it can't disagree
        y10 = bonds_tbl.get("10-Year Yield", {})
        y2  = bonds_tbl.get("2-Year Yield", {})
        if y10.get("level") is not None and y2.get("level") is not None:
            sp = dict(bonds_tbl.get("10s-2s Spread") or {})
            sp["level"] = round((float(y10["level"]) - float(y2["level"])) * 100, 1)
            if y10.get("change") is not None and y2.get("change") is not None:
                sp["change"] = round((float(y10["change"]) - float(y2["change"])) * 100, 1)
            bonds_tbl["10s-2s Spread"] = sp
    return fixed


def fetch_technical_levels(current_overrides: dict | None = None) -> dict[str, dict]:
    """Compute 20d/50d/200d MAs, 52-wk high/low for key assets.

    current_overrides maps asset name → canonical current price (from the market
    snapshot). When supplied, it overrides yfinance's last bar as `current` so the
    technicals table never disagrees with the snapshot/commodities tables on the
    displayed price (fixes the 2026-06-01 split where the snapshot showed Gold
    $4,560.50 / S&P 7,580.06 but the technicals table showed 4,518.40 / 7,612.37
    from an independent, later/intraday yfinance pull). MAs, 52-wk extremes, and
    swing levels still come from the daily history — only `current` is reconciled,
    and support/resistance is then computed against that reconciled price."""
    current_overrides = current_overrides or {}
    assets = {
        "S&P 500":      "^GSPC",
        "Nasdaq 100":   "^NDX",
        "Gold":         "GC=F",
        "WTI Crude":    "CL=F",
        "10-Yr Yield":  "^TNX",
        "VIX":          "^VIX",
    }
    result: dict[str, dict] = {}
    if yf is None:
        return result

    end   = datetime.today()
    start = end - timedelta(days=400)   # need 200d + some buffer

    for name, ticker in assets.items():
        try:
            data = yf.download(ticker, start=start, end=end,
                               progress=False, auto_adjust=True)
            if data.empty:
                continue
            closes = data["Close"].dropna()
            if hasattr(closes, "squeeze"):
                closes = closes.squeeze()
            arr = closes.to_numpy()
            if len(arr) < 2:
                continue

            current = float(arr[-1])
            _override = current_overrides.get(name)
            if _override is not None:
                try:
                    current = float(_override)
                except (TypeError, ValueError):
                    pass
            high52  = float(closes.tail(252).max())
            low52   = float(closes.tail(252).min())
            ma20    = float(closes.tail(20).mean())  if len(arr) >= 20  else None
            ma50    = float(closes.tail(50).mean())  if len(arr) >= 50  else None
            ma200   = float(closes.tail(200).mean()) if len(arr) >= 200 else None

            # ── Pillar 3: deterministic key support / resistance ────────────
            # Combine swing extrema in the last ~90 trading days with MAs and 52w
            # levels, cluster nearby candidates, and pick the closest 1-2 above
            # (resistance) and below (support) the current price. All numeric, no
            # LLM — Sevens-style "key support X / resistance Y" with zero hallucination
            # risk. Wrapped so a numeric error never blocks the technicals table.
            support: list[dict] = []
            resistance: list[dict] = []
            try:
                import numpy as _np
                arr_recent = arr[-min(90, len(arr)):]
                # Simple symmetric-window local extrema (window radius 5 days).
                W = 5
                peaks: list[tuple[float, int]] = []
                troughs: list[tuple[float, int]] = []
                for i in range(W, len(arr_recent) - W):
                    seg = arr_recent[i - W : i + W + 1]
                    if arr_recent[i] >= seg.max():
                        peaks.append((float(arr_recent[i]), i))
                    if arr_recent[i] <= seg.min():
                        troughs.append((float(arr_recent[i]), i))
                # Tag candidates with their origin.
                cand: list[tuple[float, str, int]] = []  # (level, tag, recency_idx)
                for lvl, idx in peaks:
                    cand.append((lvl, "swing high", idx))
                for lvl, idx in troughs:
                    cand.append((lvl, "swing low", idx))
                _N = len(arr_recent)
                if ma20:   cand.append((ma20,   "20d MA",   _N))
                if ma50:   cand.append((ma50,   "50d MA",   _N))
                if ma200:  cand.append((ma200,  "200d MA",  _N))
                cand.append((high52, "52w high", _N))
                cand.append((low52,  "52w low",  _N))
                # Cluster within 0.8% of current — keep the strongest tag (prefer
                # MA/52w label over generic swing) per cluster, AND keep the level
                # closest to the cluster centroid. For ties prefer the more recent.
                _tol = max(abs(current) * 0.008, 1e-9)
                _CAND_RANK = {"52w high": 3, "52w low": 3, "200d MA": 3, "50d MA": 2,
                              "20d MA": 2, "swing high": 1, "swing low": 1}
                grouped: list[dict] = []
                for lvl, tag, idx in sorted(cand, key=lambda x: x[0]):
                    if grouped and abs(lvl - grouped[-1]["level"]) <= _tol:
                        # Merge into the current cluster — upgrade tag if better.
                        if _CAND_RANK.get(tag, 0) > _CAND_RANK.get(grouped[-1]["tag"], 0):
                            grouped[-1]["tag"] = tag
                            grouped[-1]["level"] = lvl
                        elif idx > grouped[-1]["recency"]:
                            grouped[-1]["recency"] = idx
                        continue
                    grouped.append({"level": lvl, "tag": tag, "recency": idx})
                # Pick closest 2 support (< current) and 2 resistance (> current),
                # excluding any further than 15% from current (off the radar) AND any
                # within 0.25% of current (trivially close — visually looks like an
                # error e.g. "support 4.48" when the current print is 4.48).
                _floor, _ceil = current * 0.85, current * 1.15
                _near = abs(current) * 0.0025
                below = [g for g in grouped if _floor <= g["level"] <= current - _near]
                above = [g for g in grouped if current + _near <= g["level"] <= _ceil]
                below.sort(key=lambda g: current - g["level"])    # closest first
                above.sort(key=lambda g: g["level"] - current)
                support    = [{"level": round(g["level"], 2), "tag": g["tag"]} for g in below[:2]]
                resistance = [{"level": round(g["level"], 2), "tag": g["tag"]} for g in above[:2]]
            except Exception as _sr_exc:
                print(f"[WARN] support/resistance compute failed for {name}: {_sr_exc}")

            result[name] = {
                "current": round(current, 2),
                "52w_high": round(high52, 2),
                "52w_low":  round(low52,  2),
                "ma20":  round(ma20,  2) if ma20  else None,
                "ma50":  round(ma50,  2) if ma50  else None,
                "ma200": round(ma200, 2) if ma200 else None,
                "support":    support,
                "resistance": resistance,
            }
        except Exception:
            pass

    return result


def _completed_daily_change(closes, today) -> tuple[float, float] | None:
    """(pct_change, last_level) from the last two COMPLETED daily closes.

    Anchors to the last finished session, matching the page-1 snapshot ("prices
    taken at previous day market close"). The pipeline runs at 9am CST = 10am ET,
    AFTER the 9:30 ET open, so a daily yfinance pull can carry a live, partial
    current-day bar. Treating that partial bar as the "last close" computes
    TODAY's intraday move (often a bounce) instead of yesterday's completed
    session — the session the recap narrates. That mismatch caused the 2026-06-18
    defect: 8/11 sectors green ("Technology +2.46%") on a day recapped as
    S&P -1.21%. Drop any bar dated >= today so the change is always prior-session.
    Returns None when fewer than two completed closes are available.
    """
    try:
        if hasattr(closes, "squeeze"):
            closes = closes.squeeze()
        if len(closes) and hasattr(closes.index[-1], "date") and closes.index[-1].date() >= today:
            closes = closes.iloc[:-1]
        arr = closes.to_numpy()
    except Exception:
        return None
    if len(arr) < 2:
        return None
    last = float(arr[-1])
    prev = float(arr[-2])
    pct = round((last - prev) / prev * 100, 2) if prev else 0.0
    return pct, round(last, 2)


def fetch_sector_performance() -> list[dict]:
    """Return daily % change for all 11 SPDR sector ETFs, sorted best to worst.

    Each entry: {"name": str, "ticker": str, "pct_change": float, "level": float}
    Returns empty list if yfinance unavailable.
    """
    if yf is None:
        return []
    try:
        tickers = list(SECTOR_TICKERS.values())
        end   = datetime.today()
        start = end - timedelta(days=7)
        data  = yf.download(tickers, start=start, end=end,
                            progress=False, auto_adjust=True, group_by="ticker")
        _today = datetime.today().date()
        results: list[dict] = []
        for name, ticker in SECTOR_TICKERS.items():
            try:
                if len(tickers) == 1:
                    closes = data["Close"].dropna()
                else:
                    closes = data[ticker]["Close"].dropna()
                chg = _completed_daily_change(closes, _today)
                if chg is None:
                    continue
                pct, last = chg
                results.append({"name": name, "ticker": ticker,
                                 "pct_change": pct, "level": last})
            except Exception:
                continue
        results.sort(key=lambda x: x["pct_change"], reverse=True)
        top3    = results[:3]
        bottom3 = results[-3:][::-1]
        print(f"  [OK] Sectors: top={top3[0]['name']} {top3[0]['pct_change']:+.2f}%  "
              f"bottom={bottom3[0]['name']} {bottom3[0]['pct_change']:+.2f}%")
        return results
    except Exception as exc:
        print(f"[WARN] fetch_sector_performance failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Portfolio data
# ---------------------------------------------------------------------------
def load_portfolio_df() -> pd.DataFrame:
    path = DATA_DIR / "features.parquet"
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_parquet(path)
        df["Ticker"] = df["Ticker"].astype(str).str.upper().str.strip()
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
            df = df.sort_values("Date").groupby("Ticker", as_index=False).tail(1)
        else:
            df = df.drop_duplicates(subset=["Ticker"], keep="last")
        return df
    except Exception as exc:
        print(f"[WARN] Could not load features.parquet: {exc}")
        return pd.DataFrame()


def _safe_float(val: Any, scale: float = 1.0) -> float | None:
    try:
        v = float(val)
        return round(v * scale, 3) if v == v else None
    except Exception:
        return None


# Fund descriptions — tells the LLM what each ticker actually is so it doesn't hallucinate sector attributions
FUND_DESCRIPTIONS: dict[str, str] = {
    "BUFR":  "FolioBeyond Rising Rates ETF — tactical rate-hedged fixed income",
    "CGDV":  "Capital Group Dividend Value ETF — dividend-focused large-cap US value equities",
    "AUSF":  "Global X Adaptive U.S. Factor ETF — multi-factor US equities",
    "SDVD":  "Siren DIVCON Dividend Defender ETF — dividend growth, hedged against dividend cutters",
    "DIVO":  "Amplify CWP Enhanced Dividend Income ETF — dividend income with covered call overlay",
    "XLG":   "Invesco S&P 500 Top 50 ETF — mega-cap US equities (top 50 in S&P 500)",
    "TMFC":  "Motley Fool 100 Index ETF — 100 largest Motley Fool-recommended US stocks",
    "XNTK":  "SPDR NYSE Technology ETF — US technology sector equities",
    "RLY":   "SPDR SSgA Multi-Asset Real Return ETF — real assets and inflation protection",
    "EFAA":  "Columbia Adaptive Risk Allocation ETF — multi-asset adaptive allocation",
    "LVHI":  "Legg Mason International Low Volatility High Dividend ETF — international low-volatility dividend equities (NOT tech)",
    "SGIIX": "Segall Bryant & Hamill International Small Cap Fund — international small-cap equities",
    "JFNIX": "John Hancock Fundamental All Cap Core Fund — all-cap US equities, fundamental strategy",
    "IXJ":   "iShares Global Healthcare ETF — global healthcare equities (NOT consumer discretionary)",
    "VSMIX": "Vanguard Strategic Small-Cap Equity Fund — US small-cap equities",
    "JAAA":  "Janus Henderson AAA CLO ETF — AAA-rated CLOs, short-duration investment-grade fixed income",
    "WCPBX": "Western Asset Core Plus Bond Fund — core plus multi-sector fixed income",
    "ADVNX": "BlackRock Advantage International Fund — international developed market equities",
    "EVTR":  "Eaton Vance Tax-Managed Diversified Equity Income Fund — tax-managed equity income",
    "SUBFX": "Semper Short Duration Fund — short-duration fixed income",
    "KORP":  "American Century Diversified Corporate Bond ETF — investment-grade corporate bonds",
    "JHPI":  "John Hancock Preferred Income Fund — preferred securities and income",
    "JHMB":  "John Hancock Mortgage-Backed Securities ETF — agency MBS fixed income",
    "JMST":  "JPMorgan Ultra-Short Municipal Income ETF — ultra-short tax-exempt munis",
    "JSI":   "Janus Henderson Securitized Income ETF — securitized credit (ABS, MBS, CLOs)",
    "FDUIX": "Federated Hermes Ultrashort Duration Fund — ultra-short investment-grade bonds",
    # Added 2026-06-15 to match the 2026-06-02 EPM models workbook universe
    "AVLV":  "Avantis U.S. Large Cap Value ETF — large-cap US value equities",
    "BPTIX": "Baron Partners Fund — concentrated US large-cap growth equities (mutual fund)",
    "DYNF":  "iShares U.S. Equity Factor Rotation Active ETF — multi-factor US large-cap equities",
    "EMEQ":  "Nomura Focused Emerging Markets Equity ETF — emerging-market equities",
    "FLMI":  "Franklin Dynamic Municipal Bond ETF — tax-exempt municipal bonds (fixed income, NOT equities)",
    "FWD":   "AB Disruptors ETF — global growth / disruptive-innovation equities",
    "MFSB":  "MFS Active Core Plus Bond ETF — core-plus multi-sector fixed income",
    "TAXF":  "American Century Diversified Municipal Bond ETF — tax-exempt municipal bonds (fixed income)",
    "TDI":   "Touchstone Dynamic International ETF — international developed-market equities",
    "XMMO":  "Invesco S&P MidCap Momentum ETF — US mid-cap momentum equities",
    "QQA":   "Invesco QQA Nasdaq 100 ETF — Nasdaq 100 large-cap technology-heavy index",
    "SHLD":  "Global X Defense Tech ETF — defense and aerospace technology equities",
}


# The fresh trailing 1-month return lives in "1M Return_enrich" (yfinance, recomputed
# every run by features.enrich_features_with_missing_metrics). A merge-suffix collision
# means it never overwrites the bare "1M Return", which therefore carries the STALE
# YCharts scrape value (e.g. 2026-06-01 showed XNTK 24.82% stale vs 19.88% fresh). DISPLAY
# consumers must prefer the enriched column. The bare "1M Return" is deliberately left
# intact — it is also a model input feature (forecast_common → qc_ret_1m, quantconnect_model),
# so overwriting it at the source would risk train/serve skew; fix display only.
_FRESH_1M_COLS = ("1M Return_enrich", "Forward Return", "1M Return")


def _fresh_1m_col(columns) -> str | None:
    """Return the freshest available trailing-1M-return column name, or None."""
    for c in _FRESH_1M_COLS:
        if c in columns:
            return c
    return None


def build_portfolio_spotlight(df: pd.DataFrame) -> tuple[list, list]:
    try:
        from universe_config import get_portfolio_tickers, get_tracking_only_tickers
    except Exception:
        return [], []

    tracking_only = set(get_tracking_only_tickers())  # MAG7 + active MANGOS (e.g. SPCX)
    all_port = get_portfolio_tickers()
    funds    = df[df["Ticker"].isin([t for t in all_port if t not in tracking_only])].copy()

    ret_col = _fresh_1m_col(funds.columns)
    if funds.empty or ret_col is None:
        return [], []

    funds[ret_col] = pd.to_numeric(funds[ret_col], errors="coerce")
    funds = funds.dropna(subset=[ret_col]).sort_values(ret_col, ascending=False)

    def to_dict(row: pd.Series) -> dict:
        ret = _safe_float(row[ret_col], scale=100) or 0.0
        ticker = row["Ticker"]
        d: dict[str, Any] = {
            "ticker":      ticker,
            "description": FUND_DESCRIPTIONS.get(ticker, ""),
            "return_1m":   ret,
            "metric_label": f"{ret:+.1f}% (1M)",
        }
        for col, label in [
            ("Sharpe (3Y)",       "sharpe_3y"),
            ("3Y Sharpe",         "sharpe_3y"),
            ("Max Drawdown 3Y",   "max_drawdown"),
            ("Volatility",        "volatility"),
            ("Alpha (3Y)",        "alpha"),
        ]:
            if col in row.index and d.get(label) is None:
                v = _safe_float(row[col])
                if v is not None:
                    d[label] = v
        return d

    winners = [to_dict(r) for _, r in funds.head(3).iterrows()]
    watch   = [to_dict(r) for _, r in funds.tail(2).iterrows()]
    return winners, watch


# Cyclical/growth proxies vs defensives — used to classify the sector tilt for the
# tactical-positioning stance. These are sector ETF tickers, not single stocks.
_CYC_SECTORS: frozenset[str] = frozenset({"XLK", "XLY", "XLI", "XLC", "XLF", "XLB"})
_DEF_SECTORS: frozenset[str] = frozenset({"XLP", "XLU", "XLV", "XLRE"})


def build_tactical_positioning(
    df: "pd.DataFrame | None",
    sector_perf: list[dict] | None,
    vix_level: float | None,
) -> dict:
    """Compute a DETERMINISTIC tactical-positioning snapshot from the 30-fund book +
    sector tilt + VIX. EPM's structural edge over the Sevens: the Sevens uses SPHB/SPLV
    qualitatively; we synthesize a *quantitative* stance from the actual portfolio.

    Returns {} on insufficient data so renderers can omit the section gracefully — this
    new section is wrapped in try/except so a failure here NEVER kills the pipeline.
    Output keys: stance, stance_detail, top_funds[], bottom_funds[], factor_read, takeaway.
    """
    try:
        import pandas as _pd
        # ── 1. Stance from sector tilt ────────────────────────────────────────
        sp = [s for s in (sector_perf or [])
              if s.get("ticker") and s.get("pct_change") is not None]
        if not sp:
            return {}
        sp_sorted = sorted(sp, key=lambda s: float(s["pct_change"]), reverse=True)
        top3, bot3 = sp_sorted[:3], sp_sorted[-3:]
        cyc_top = sum(1 for s in top3 if s["ticker"] in _CYC_SECTORS)
        def_top = sum(1 for s in top3 if s["ticker"] in _DEF_SECTORS)
        cyc_bot = sum(1 for s in bot3 if s["ticker"] in _CYC_SECTORS)
        def_bot = sum(1 for s in bot3 if s["ticker"] in _DEF_SECTORS)
        if cyc_top >= 2 and def_bot >= 1:
            stance = "Risk-on, pro-cyclical"
        elif def_top >= 2 and cyc_bot >= 1:
            # "Risk-off" implies fear; only assert it when VIX corroborates. On a
            # subdued VIX the same defensive sector tilt is a rotation, not risk
            # aversion. 2026-07-06: labeled "Risk-off, defensive bid" beside VIX 15.99
            # (-11.8% vs 20d) — Sevens correctly read the same tape as calendar/quarter-
            # end rotation, not fear. Reserve "risk-off" for VIX >= 20 (the fear line).
            _vix_calm = False
            if vix_level is not None:
                try:
                    _vix_calm = float(vix_level) < 20.0
                except Exception:
                    _vix_calm = False
            stance = "Defensive rotation" if _vix_calm else "Risk-off, defensive bid"
        elif cyc_top >= 2:
            stance = "Pro-cyclical lean"
        elif def_top >= 2:
            stance = "Defensive lean"
        else:
            stance = "Mixed signals"
        if vix_level is not None:
            try:
                v = float(vix_level)
                if v < 14:
                    stance += " (calm tape)"
                elif v >= 25:
                    stance += " (elevated vol)"
            except Exception:
                pass
        stance_detail = (
            "Leading: " + ", ".join(f"{s['name']} {s['pct_change']:+.1f}%" for s in top3)
            + ". Lagging: " + ", ".join(f"{s['name']} {s['pct_change']:+.1f}%" for s in bot3) + "."
        )

        # ── 2. Top / bottom portfolio funds by 1M return ──────────────────────
        top_funds: list[dict] = []
        bot_funds: list[dict] = []
        factor_read = ""
        _ret_col = _fresh_1m_col(df.columns) if (df is not None and not df.empty) else None
        if _ret_col:
            try:
                from universe_config import get_portfolio_tickers, get_tracking_only_tickers
                _tracking_only = set(get_tracking_only_tickers())  # MAG7 + active MANGOS
                _port = [t for t in get_portfolio_tickers() if t not in _tracking_only]
                funds = df[df["Ticker"].isin(_port)].copy()
                funds["_1m_num"] = _pd.to_numeric(funds[_ret_col], errors="coerce")
                funds = funds.dropna(subset=["_1m_num"])
                # Normalize: some rows store decimals (0.087), others percent (8.7).
                funds["_1m_pct"] = funds["_1m_num"].apply(
                    lambda v: float(v) * 100 if abs(float(v)) < 1 else float(v)
                )
                funds = funds.sort_values("_1m_pct", ascending=False)

                def _row(r: "_pd.Series") -> dict:
                    d: dict[str, Any] = {
                        "ticker":  str(r["Ticker"]),
                        "ret_1m":  float(r["_1m_pct"]),
                        "tag":     FUND_DESCRIPTIONS.get(str(r["Ticker"]), "")[:80],
                    }
                    for col, k in [("Sharpe (3Y)", "sharpe"), ("Alpha (3Y)", "alpha"),
                                   ("Beta (3Y)", "beta"), ("Max Drawdown 3Y", "max_dd")]:
                        if col in r.index and _pd.notna(r[col]):
                            try:
                                d[k] = float(r[col])
                            except Exception:
                                pass
                    return d

                top_funds = [_row(r) for _, r in funds.head(3).iterrows()]
                bot_funds = [_row(r) for _, r in funds.tail(2).iterrows()]

                # Factor read — compare avg beta of leaders vs laggards. NOTE: this is a
                # TRAILING-1M read, whereas `stance` above is TODAY's sector tilt. The two
                # windows can legitimately diverge, so when the beta tilt conflicts with
                # today's stance we frame it as a trailing-leaderboard divergence rather than
                # asserting the opposite risk posture — the bald "risk-on positioning" line
                # under a "Risk-off, defensive bid" header read as a self-contradiction.
                tb = [f["beta"] for f in top_funds if f.get("beta") is not None]
                bb = [f["beta"] for f in bot_funds if f.get("beta") is not None]
                if tb and bb:
                    at, ab = sum(tb)/len(tb), sum(bb)/len(bb)
                    _risk_off_today = stance.startswith(("Risk-off", "Defensive"))
                    _risk_on_today = stance.startswith(("Risk-on", "Pro-cyclical"))
                    if at - ab > 0.2:
                        if _risk_off_today:
                            factor_read = (f"Trailing-1M leaders skew high-beta (avg β {at:.2f} vs laggards "
                                           f"{ab:.2f}) — a risk-on tilt in the month's leaderboard that runs "
                                           f"counter to today's defensive rotation.")
                        else:
                            factor_read = (f"High-beta leading — leaders carry avg β {at:.2f} vs laggards {ab:.2f}; "
                                           f"consistent with risk-on positioning.")
                    elif ab - at > 0.2:
                        if _risk_on_today:
                            factor_read = (f"Trailing-1M laggards carry higher avg β ({ab:.2f}) than leaders "
                                           f"({at:.2f}) — a defensive tilt in the month's leaderboard that runs "
                                           f"counter to today's pro-cyclical move.")
                        else:
                            factor_read = (f"Low-vol bid — laggards carry higher avg β ({ab:.2f}) than leaders "
                                           f"({at:.2f}); defensive rotation under way.")
                    else:
                        factor_read = f"No clear beta tilt — leaders β {at:.2f} vs laggards β {ab:.2f}."
            except Exception as _exc:
                print(f"[WARN] Tactical fund ranking failed: {_exc}")

        # ── 3. Takeaway sentence ─────────────────────────────────────────────
        # Descriptive relative-momentum read, not a buy/sell directive (2026-06-15:
        # "Lean into X; trim Y" reads as advice; these are model-ranked 1M leaders/laggards).
        bits: list[str] = []
        if top_funds:
            bits.append("leaders " + ", ".join(f["ticker"] for f in top_funds[:3]))
        if bot_funds:
            bits.append("laggards " + ", ".join(f["ticker"] for f in bot_funds))
        takeaway = ("Relative 1M momentum — " + "; ".join(bits) + ".") if bits else ""
        return {
            "stance":         stance,
            "stance_detail":  stance_detail,
            "top_funds":      top_funds,
            "bottom_funds":   bot_funds,
            "factor_read":    factor_read,
            "takeaway":       takeaway,
        }
    except Exception as _exc:
        # Never fail the pipeline because of this new section.
        print(f"[WARN] Tactical positioning compute failed: {_exc}")
        return {}


def _build_quant_desk_read(tp: dict, mag7_consensus: dict) -> str:
    """Fuse EPM's three quant lenses — the day's sector-tilt STANCE, the portfolio
    FACTOR tilt (leader vs laggard beta), and the MAG7 MODEL forecast — into one
    interpretive 'Quant Desk Read'. This is the differentiated edge the Sevens cannot
    reproduce (it has no model book): it surfaces AGREEMENT or DISSENT across the lenses.

    INTERPRETIVE, never a directive — no buy/sell/lean/trim (2026-06-15 advice
    constraint). Returns "" when inputs are too thin to synthesize."""
    if not isinstance(tp, dict):
        return ""
    low = str(tp.get("stance") or "").lower()
    tape_riskon = low.startswith(("risk-on", "pro-cyclical"))
    tape_riskoff = low.startswith(("risk-off", "defensive"))
    tb = [f.get("beta") for f in (tp.get("top_funds") or []) if f.get("beta") is not None]
    bb = [f.get("beta") for f in (tp.get("bottom_funds") or []) if f.get("beta") is not None]
    if not tb or not bb:
        return ""
    at, ab = sum(tb) / len(tb), sum(bb) / len(bb)
    port_highbeta = at - ab > 0.2
    port_lowbeta = ab - at > 0.2

    cons = [v.get("consensus") for v in (mag7_consensus or {}).values()
            if isinstance(v, dict) and v.get("consensus") is not None]
    if not cons:
        return ""
    n = len(cons)
    bullish = sum(1 for c in cons if c > 0)
    bearish = sum(1 for c in cons if c < 0)
    avg = sum(cons) / n
    weakest, wv = None, None
    for t, v in (mag7_consensus or {}).items():
        c = v.get("consensus") if isinstance(v, dict) else None
        if c is not None and (wv is None or c < wv):
            wv, weakest = c, t
    models_riskoff = avg < 0
    models_riskon = avg > 0

    # ── Part 1: the tape + the book (sector stance vs portfolio beta tilt) ──
    if port_highbeta:
        beta_clause = (f"high-beta names lead the 1-month leaderboard (leaders avg "
                       f"β {at:.2f} vs laggards {ab:.2f})")
    elif port_lowbeta:
        beta_clause = (f"the 1-month leaderboard skews low-beta (leaders avg β {at:.2f} "
                       f"vs laggards {ab:.2f})")
    else:
        beta_clause = f"the 1-month leaderboard shows no clear beta tilt (β {at:.2f} vs {ab:.2f})"
    if tape_riskon and port_highbeta:
        part1 = f"The book and the tape agree on risk-on — {beta_clause} and the sector tilt is pro-cyclical."
    elif tape_riskoff and port_lowbeta:
        part1 = f"The book and the tape agree on a defensive posture — {beta_clause} and the sector tilt is risk-off."
    else:
        _tape = "pro-cyclical" if tape_riskon else ("defensive" if tape_riskoff else "mixed")
        part1 = f"The tape's tilt is {_tape} while {beta_clause}."

    # ── Part 2: the MAG7 model lens — does it confirm or dissent? ──
    bear_stats = f"{avg:+.2f}% consensus, {bearish} of {n} bearish" + (f", {weakest} weakest" if weakest else "")
    bull_stats = f"{avg:+.2f}% consensus, {bullish} of {n} bullish"
    if models_riskoff and tape_riskon:
        part2 = (f"The dissent is in the models: MAG7 forecasts skew defensive ({bear_stats}), "
                 f"so leadership is narrow and mega-cap tech screens as the rally's soft spot "
                 f"rather than its engine.")
    elif models_riskon and tape_riskoff:
        part2 = (f"The models are more constructive than the tape ({bull_stats}), pointing to "
                 f"mega-cap tech as a potential stabilizer if the defensive rotation fades.")
    elif models_riskoff and tape_riskoff:
        part2 = f"The models concur: MAG7 consensus is {bear_stats}, reinforcing the defensive read."
    elif models_riskon and tape_riskon:
        part2 = f"The models concur: MAG7 consensus is {bull_stats}, reinforcing the risk-on read."
    else:
        part2 = f"The MAG7 model lens is roughly balanced ({avg:+.2f}% consensus, {bullish} up / {bearish} down)."
    return f"{part1} {part2}"


def build_mag7_consensus(df: pd.DataFrame) -> dict[str, dict]:
    """Return per-ticker dict with consensus, confidence, agreement, winning model."""
    try:
        from universe_config import get_mag7
        mag7 = get_mag7()
    except Exception:
        return {}

    result: dict[str, dict] = {}
    mag7_df = df[df["Ticker"].isin(mag7)]
    for _, row in mag7_df.iterrows():
        ticker = row["Ticker"]
        entry: dict[str, Any] = {}
        for col in ("Consensus_Forecast", "Consensus Forecast (%)"):
            if col in row.index:
                v = _safe_float(row[col])
                if v is not None:
                    entry["consensus"] = round(v * 100 if abs(v) < 1 else v, 2)
                    break
        entry["confidence"]    = str(row.get("Confidence_Label", "") or "")
        entry["agreement"]     = _safe_float(row.get("Agreement_Ratio"))
        entry["winning_model"] = str(row.get("Winning_Model", "") or "")
        result[ticker] = entry

    return result


# ---------------------------------------------------------------------------
# News loading
# ---------------------------------------------------------------------------
_NEWS_BUCKETS: dict[str, list[str]] = {
    "commodities":  ["oil", "crude", "gold", "commodity", "commodities", "energy", "opec", "brent", "wti", "copper", "silver", "gas"],
    "fixed_income": ["fed", "federal reserve", "rate", "yield", "treasury", "inflation", "cpi", "fomc", "interest", "bonds", "debt", "credit"],
    "equities":     ["stock", "equity", "equities", "nasdaq", "s&p", "earnings", "shares", "market rally", "selloff", "ipo", "dividend"],
    "currencies":   ["dollar", "dxy", "currency", "forex", "yen", "euro", "pound", "fx", "bitcoin", "crypto"],
    "macro":        ["gdp", "recession", "growth", "unemployment", "jobs", "economy", "economic", "jolts", "pce", "consumer"],
}

# Promotional/sponsored content patterns to exclude from LLM context
_NOISE_KEYWORDS: frozenset[str] = frozenset({
    "ebook", "webinar", "whitepaper", "free report", "trading guide",
    "free download", "cfd broker", " cfds ", "sponsored", "advertisement",
    "launches free", "free tool", "sign up", "newsletter", "free access",
    "claim your", "download now", "register now", "watch now",
})

# US-relevance ranking for the LLM news corpus. We DE-PRIORITIZE (never drop) headlines
# about foreign-domestic markets/regulators with little direct US read-through (India/RBI,
# SE-Asia) so they sink below US-relevant stories in each bucket's top-N cut. A headline
# carrying a US hook (matches both lists) nets toward neutral and is retained.
_US_RELEVANCE_RE = re.compile(
    r"\b(fed|federal reserve|fomc|powell|treasury|u\.?s\.?|united states|wall street|"
    r"s&p|nasdaq|dow jones|dow|russell|vix|dollar|greenback|cpi|pce|payrolls?|jobless|"
    r"ism|gdp|white house|congress)\b",
    re.I,
)
_REGIONAL_DEPRIORITIZE_RE = re.compile(
    r"\b(india|indian|rbi|nifty|sensex|rupee|mumbai|sebi|malaysia|malaysian|ringgit|"
    r"indonesia|rupiah|jakarta|philippine|philippines|peso|thailand|baht|vietnam)\b",
    re.I,
)


def _us_relevance_score(text: str) -> int:
    """Higher = more US-relevant. Foreign-domestic-only headlines score negative so a
    stable sort sinks them in each bucket's top-N cut (de-prioritized, never dropped)."""
    low = text or ""
    return len(_US_RELEVANCE_RE.findall(low)) - len(_REGIONAL_DEPRIORITIZE_RE.findall(low))


def bucket_headlines(entries: list[str]) -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {k: [] for k in _NEWS_BUCKETS}
    buckets["other"] = []
    for entry in entries:
        lower   = entry.lower()
        matched = False
        for bucket, keywords in _NEWS_BUCKETS.items():
            if any(kw in lower for kw in keywords):
                buckets[bucket].append(entry)
                matched = True
                break
        if not matched:
            buckets["other"].append(entry)
    return {k: v for k, v in buckets.items() if v}


def load_news_headlines() -> dict[str, list[str]]:
    parquet_path = DATA_DIR / "news_store.parquet"
    csv_path     = DATA_DIR / "news_headlines.csv"

    df = None
    if parquet_path.exists():
        try:
            df = pd.read_parquet(parquet_path)
        except Exception:
            pass

    if df is None or df.empty:
        if csv_path.exists():
            try:
                df = pd.read_csv(csv_path)
            except Exception:
                return {}
        else:
            return {}

    if df is None or df.empty:
        return {}

    try:
        from news_store import _story_quality
        df["_q"] = df.apply(_story_quality, axis=1)
        df = df.sort_values("_q", ascending=False)
    except Exception:
        pass

    headline_col = next((c for c in df.columns if c.lower() in ("headline", "title", "head")), None)
    summary_col  = next((c for c in df.columns if c.lower() in ("summary", "description", "body")), None)
    if headline_col is None:
        return {}

    entries = []
    for _, row in df.head(60).iterrows():
        headline = str(row.get(headline_col, "") or "").strip()
        if not headline:
            continue
        summary = str(row.get(summary_col, "") or "").strip() if summary_col else ""
        if summary and summary.lower() not in ("nan", "none", ""):
            entries.append(f"{headline}  {summary}")
        else:
            entries.append(headline)

    return bucket_headlines(entries)


# --- TradingView public news wire (institutional, headless, no-key) -----------
# The FMP `news.world` feed that fed the macro layer is a retail content farm
# (24/7 Wall St./Stocktwits/GuruFocus — ~60% of 6/24's payload, 23% pure evergreen
# SEO filler) that BOTH starved substance (no same-day econ/markets analysis: flash
# PMI, breadth, commodity reads) AND injected evergreen spam into the Topic Spotlight.
# See memory project_world_news_feed_quality. TradingView's PUBLIC news-headlines
# JSON endpoint (the one that powers its web news widget — distinct from the
# interactive desktop MCP, which is dev-time only) is a free, no-key, headless wire
# carrying Reuters / Dow Jones Newswires / Trading-Economics / CNBC headlines. We
# prepend it so its quality items win the de-dup and the 40-slot cap, putting
# institutional macro coverage at the top of what the Spotlight + commentary see.
_TV_HEADLINES_URL = "https://news-headlines.tradingview.com/v2/headlines?client=overview&lang=en"
# Display names for TradingView's provider codes (everything here is a real wire —
# the whole point of the source swap).
_TV_PROVIDER_NAMES = {
    "reuters": "Reuters",
    "dow-jones": "Dow Jones Newswires",
    "trading-economics": "Trading Economics",
    "cnbctv": "CNBC",
    "dpa_afx": "dpa-AFX",
    "moneycontrol": "Moneycontrol",
    "tmx_newsfile": "TMX Newsfile",
}


def fetch_tradingview_headlines(limit: int = 40) -> list[dict]:
    """Pull macro/markets headlines from TradingView's public news widget API and
    map them to the same article shape fetch_world_news emits. Headless + no-key;
    fails soft (returns []) so it can never break the pipeline."""
    out: list[dict] = []
    try:
        import urllib.request as _ur
        req = _ur.Request(_TV_HEADLINES_URL, headers={
            "User-Agent": "Mozilla/5.0",
            "Origin": "https://www.tradingview.com",
            "Referer": "https://www.tradingview.com/",
            "Accept": "application/json",
        })
        with _ur.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"[WARN] TradingView headlines fetch failed: {exc}")
        return out

    for it in (payload.get("items") or []):
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip()
        if not title:
            continue
        prov = str(it.get("provider") or "").strip()
        source = str(it.get("source") or "").strip() or _TV_PROVIDER_NAMES.get(prov, prov)
        # published is a unix timestamp (seconds) — normalise to an ISO string.
        published_at = ""
        ts = it.get("published")
        if isinstance(ts, (int, float)) and ts > 0:
            try:
                published_at = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            except Exception:
                published_at = ""
        story = str(it.get("storyPath") or "").strip()
        url = ("https://www.tradingview.com" + story) if story.startswith("/") else story
        # Surface the wire's own ticker tags as a lightweight summary hint so the
        # downstream bucketer/Spotlight can connect a headline to fund symbols.
        rels = it.get("relatedSymbols") or []
        syms = [str(r.get("symbol", "")).split(":")[-1] for r in rels if isinstance(r, dict)]
        summary = ("Related: " + ", ".join(s for s in syms if s)) if syms else ""
        out.append({
            "title":        title,
            "summary":      summary,
            "source":       source,
            "published_at": published_at,
            "url":          url,
            "category":     "world",
        })
        if len(out) >= limit:
            break
    if out:
        print(f"[OK] TradingView headlines: {len(out)} institutional items "
              f"({', '.join(sorted({a['source'] for a in out}))[:120]})")
    return out


def fetch_world_news() -> list[dict]:
    # Quality wire FIRST so its institutional items win de-dup + the 40-slot cap.
    articles: list[dict] = fetch_tradingview_headlines(limit=40)

    try:
        from providers.openbb_provider import OpenBBProvider
        provider = OpenBBProvider()
        if getattr(provider, "obb", None) is not None:
            resp = provider.obb.news.world(limit=40, provider="fmp")
            results = resp.results if hasattr(resp, "results") else []
            for r in results:
                r = r.__dict__ if hasattr(r, "__dict__") else (r if isinstance(r, dict) else {})
                title = str(r.get("title") or r.get("headline") or "").strip()
                if not title:
                    continue
                articles.append({
                    "title":        title,
                    "summary":      str(r.get("text") or r.get("summary") or r.get("description") or "").strip()[:300],
                    "source":       str(r.get("source") or r.get("publisher") or "").strip(),
                    "published_at": str(r.get("date") or r.get("published_at") or ""),
                    "url":          str(r.get("url") or r.get("link") or ""),
                    "category":     "world",
                })
    except Exception as exc:
        print(f"[WARN] OpenBB world news failed: {exc}")

    if not articles and yf is not None:
        try:
            for sym in ("SPY", "QQQ", "TLT", "GLD", "UUP", "^VIX"):
                tkr  = yf.Ticker(sym)
                news = getattr(tkr, "news", None) or []
                for item in news[:10]:
                    content = item.get("content") if isinstance(item.get("content"), dict) else {}
                    title   = str(content.get("title") or item.get("title") or "").strip()
                    if not title:
                        continue
                    articles.append({
                        "title":        title,
                        "summary":      str(content.get("summary") or "").strip()[:300],
                        "source":       str((content.get("provider") or {}).get("displayName") or item.get("publisher") or "").strip(),
                        "published_at": str(content.get("pubDate") or item.get("providerPublishTime") or ""),
                        "url":          str((content.get("canonicalUrl") or {}).get("url") or item.get("link") or ""),
                        "category":     "world",
                    })
        except Exception:
            pass

    seen: set[str] = set()
    unique: list[dict] = []
    for a in articles:
        key = a["title"].lower()[:60]
        if key and key not in seen:
            seen.add(key)
            text = (a["title"] + " " + a["summary"]).lower()
            for bucket, keywords in _NEWS_BUCKETS.items():
                if any(kw in text for kw in keywords):
                    a["category"] = bucket
                    break
            unique.append(a)

    result = unique[:40]

    try:
        out = DATA_DIR / "world_news.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump({"updated": datetime.today().strftime("%Y-%m-%d"), "articles": result}, f,
                      indent=2, ensure_ascii=False, default=str)
        print(f"[OK] World news saved -> {out} ({len(result)} articles)")
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Geopolitical grounding — an always-on direction signal for the narrative
# ---------------------------------------------------------------------------
# 2026-07-02: the rates/FX/gold sections invoked a US-Iran storyline with the WRONG
# direction ("fading hopes for a peace deal fuelled inflation worries") while the real
# tape was de-escalation (peace progressing, Hormuz reopening, oil down). Root cause:
# the model grounded on STALE headlines already in the corpus ("Iran war caution",
# "US-Iran tensions") because no FRESH Iran source was consulted — the spotlight crawler
# only fetches Iran when it is the day's DOMINANT topic, and on 7/2 that was tech. This
# pass ALWAYS fetches fresh Google-News headlines for the storyline and classifies the
# CURRENT direction, so the narrative uses the right sign or — when the fresh read is
# ambiguous — drops geopolitical causation entirely instead of guessing.

# Storyline appears in the day's own corpus → worth grounding (so we don't fetch on quiet days).
_GEO_TRIGGER_RE = re.compile(
    r"\b(iran|iranian|tehran|hormuz|israel\w*|gaza|houthi|ceasefire|cease-fire|"
    r"middle\s+east|persian\s+gulf)\b", re.IGNORECASE)

# Google-News RSS search queries, tight to the market-moving storyline.
_GEO_NEWS_QUERIES = ("US Iran", "Iran ceasefire Hormuz")

_GEO_ESCALATION_RE = re.compile(
    r"\b(strikes?|struck|attack\w*|missile\w*|retaliat\w*|escalat\w+|war\b|threat\w*|"
    r"seiz\w+|blockad\w+|denies?|denied|reject\w+|stall\w*|collaps\w+|breaks?\s+down|"
    r"walk\w+\s+out|enrich\w+|sanction\w*)\b", re.IGNORECASE)

_GEO_EASING_RE = re.compile(
    r"\b(ceasefire|cease-fire|truce|peace|de-?escalat\w+|eas(?:e|es|ing|ed)|reopen\w*|"
    r"resum\w+|diplomat\w+|negotiat\w+|agreement|accord|withdraw\w+|progress\w*|"
    r"talks?\s+advanc\w*|deal\b)\b", re.IGNORECASE)


def _fetch_geopolitical_headlines(queries=_GEO_NEWS_QUERIES, max_items: int = 20,
                                  max_age_days: int = 3) -> list[dict]:
    """FRESH Google-News RSS search results for the geopolitical storyline. No key,
    fails soft (returns []). Returns [{'title','published'}] within max_age_days."""
    import urllib.request as _ur
    import urllib.parse as _up
    import xml.etree.ElementTree as _ET
    from email.utils import parsedate_to_datetime
    out: list[dict] = []
    seen: set[str] = set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    for q in queries:
        url = ("https://news.google.com/rss/search?q=" + _up.quote(q)
               + "&hl=en-US&gl=US&ceid=US:en")
        try:
            req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with _ur.urlopen(req, timeout=12) as resp:
                root = _ET.fromstring(resp.read())
        except Exception as exc:
            print(f"[WARN] geo news fetch failed for {q!r}: {exc}")
            continue
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            key = title.lower()
            if not title or key in seen:
                continue
            pub = None
            try:
                pub = parsedate_to_datetime(item.findtext("pubDate") or "")
                if pub is not None and pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
            except Exception:
                pub = None
            if pub is not None and pub < cutoff:
                continue
            seen.add(key)
            out.append({"title": title, "published": pub.isoformat() if pub else ""})
            if len(out) >= max_items:
                return out
    return out


def _classify_geo_direction(headlines: list[dict]) -> dict:
    """Score fresh geopolitical headlines: escalating vs easing. Deterministic + testable.
    Requires a clear margin (dominant side >=1.5x the other AND ahead by >=2 hits); anything
    mixed/thin is 'unclear' so the narrative drops geo causation rather than guess."""
    esc = ease = 0
    basis: list[str] = []
    for h in headlines:
        t = str(h.get("title") or "")
        e = len(_GEO_ESCALATION_RE.findall(t))
        s = len(_GEO_EASING_RE.findall(t))
        if e or s:
            basis.append(t)
        esc += e
        ease += s
    # A directional call requires a CLEAN signal: a clear margin AND the minority side no more
    # than ~25% of the total. A genuinely contested picture (both sides substantial, e.g. "Iran
    # war" headlines beside "talks progress") resolves to 'unclear' — the safe outcome that drops
    # geopolitical causation and leans on the data-grounded drivers, rather than guessing a sign.
    total = esc + ease
    if total < 2:
        direction = "unclear"
    elif ease > esc and esc <= 0.25 * total and (ease - esc) >= 2:
        direction = "easing"
    elif esc > ease and ease <= 0.25 * total and (esc - ease) >= 2:
        direction = "escalating"
    else:
        direction = "unclear"
    return {"direction": direction, "escalate": esc, "ease": ease, "basis": basis[:5]}


def build_geopolitical_context(existing_headlines: list[str] | None = None,
                               fetch_fn=None) -> dict | None:
    """Always-on geopolitical grounding for the narrative payload. Gates on the day's own
    corpus mentioning the storyline (skip the fetch on quiet days), pulls a FRESH read, and
    classifies the current direction. Non-fatal. Returns None to mean 'no grounded
    geopolitical driver' — i.e. the narrative must not attribute market moves to it.

    fetch_fn is injectable for tests (defaults to the live Google-News fetch)."""
    corpus_txt = " ".join(h for h in (existing_headlines or []) if isinstance(h, str))
    if existing_headlines is not None and not _GEO_TRIGGER_RE.search(corpus_txt):
        return None  # storyline not in play today
    try:
        fresh = (fetch_fn or _fetch_geopolitical_headlines)()
    except Exception as exc:
        print(f"[WARN] geopolitical grounding failed: {exc}")
        return None
    if not fresh:
        return None
    cls = _classify_geo_direction(fresh)
    as_of = datetime.now(timezone.utc).date().isoformat()
    if cls["direction"] == "unclear":
        print(f"  [GEO] fresh read ambiguous (esc={cls['escalate']} ease={cls['ease']}) "
              f"— instructing narrative to drop geopolitical causation.")
        return {
            "topic": "US-Iran / Middle East", "direction": "unclear",
            "instruction": ("Do NOT attribute any market move to Iran / the Middle East / a "
                            "ceasefire — the current state is unclear. Use the data-grounded "
                            "drivers (sector rotation, the day's macro releases, Fed/rate expectations)."),
            "basis": cls["basis"], "as_of": as_of,
        }
    phrase = ("de-escalating — peace/ceasefire talks progressing; the risk and oil-supply "
              "premium is DRAINING (supportive of lower oil and a softer safe-haven bid)"
              if cls["direction"] == "easing" else
              "escalating — rising conflict risk; the risk and oil-supply premium is RISING")
    print(f"  [GEO] fresh read: {cls['direction'].upper()} "
          f"(esc={cls['escalate']} ease={cls['ease']}, {len(cls['basis'])} basis headlines).")
    return {
        "topic": "US-Iran / Middle East", "direction": cls["direction"],
        "instruction": (f"The Iran / Middle-East storyline is {phrase}. Every geopolitical "
                        f"causal clause MUST match this direction; never ground one on a stale "
                        f"headline that contradicts it."),
        "basis": cls["basis"], "as_of": as_of,
    }


# The narrative generation and the sanitize-time scrubber run in separate passes, so the geo
# direction is handed off through a tiny dated sidecar (mirrors how the yield-bp corrector reads
# the arbitrated curve). direction is None when there was no grounded read (no storyline in the
# corpus or the fresh fetch was empty) — which, like "unclear", means the scrubber should drop
# any geo causal clause the model invented.
_GEO_SIDECAR = "geopolitical_context.json"


def _write_geo_sidecar(ctx: dict | None) -> None:
    """Persist today's geo direction for the sanitize-time scrubber. Non-fatal."""
    try:
        (DATA_DIR / _GEO_SIDECAR).write_text(json.dumps({
            "date": datetime.today().strftime("%Y-%m-%d"),
            "direction": (ctx or {}).get("direction"),  # easing | escalating | unclear | None
        }), encoding="utf-8")
    except Exception:
        pass


def _read_geo_direction() -> str | None:
    """Today's grounded geo direction, or 'absent' when there is no fresh grounded read.
    Returns the sentinel 'stale' when the sidecar is missing/old so callers can no-op safely."""
    try:
        sc = json.loads((DATA_DIR / _GEO_SIDECAR).read_text(encoding="utf-8"))
    except Exception:
        return "stale"
    if str(sc.get("date", ""))[:10] != datetime.today().strftime("%Y-%m-%d"):
        return "stale"
    d = sc.get("direction")
    return d if d in ("easing", "escalating", "unclear") else "absent"


# --- global central-bank decision feeds (official RSS) ------------------------
# Authoritative, free, no-key source for foreign CB DECISIONS — the timely layer the
# news wire and the US-only econ calendar both miss (EPM missed the BOJ hike on 6/18 &
# 6/22). Mirrors the Fed calendar.json approach: pull each bank's official press/news
# RSS, keep only recent DECISION-titled entries, and hand the LLM structured events.
# SNB/PBoC are intentionally left to the news-wire harvester
# (_harvest_global_macro_from_news) — no stable English decision RSS — so this set is
# the high-US-impact majors with feeds verified reachable (2026-06-22).
_CB_RSS_FEEDS = (
    ("ECB", "https://www.ecb.europa.eu/rss/press.html"),
    ("BoE", "https://www.bankofengland.co.uk/rss/news"),
    ("BoC", "https://www.bankofcanada.ca/feed/"),
    ("BOJ", "https://www.boj.or.jp/en/rss/whatsnew.xml"),
    ("RBA", "https://www.rba.gov.au/rss/rss-cb-media-releases.xml"),
)
# A title denoting an actual POLICY DECISION/announcement — not a speech, data release,
# or MINUTES (minutes lag and are lower-impact, so they are deliberately NOT matched).
_CB_DECISION_TITLE_RE = re.compile(
    r"monetary\s+policy\s+(?:decision|statement|assessment)"
    r"|statement\s+on\s+monetary\s+policy"
    r"|interest\s+rate\s+announcement"
    r"|\bbank\s+rate\b|\bcash\s+rate\b"
    r"|policy\s+rate\s+(?:decision|announcement)"
    r"|rate\s+(?:decision|announcement)",
    re.IGNORECASE)
# Minutes are NOT a fresh decision — screen them even if a title also matches above.
_CB_MINUTES_RE = re.compile(r"\bminutes\b", re.IGNORECASE)


def _parse_rss_items(xml_text) -> list[dict]:
    """Namespace-agnostic RSS/RDF/Atom item extractor. Returns [{title,link,summary,date}]
    with date a datetime or None. Handles RSS 2.0 (pubDate), RSS 1.0/RDF (dc:date) and
    Atom (published/updated) by matching each tag's LOCAL name, so one walk covers all
    three formats the central-bank feeds use."""
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    from datetime import datetime as _dt
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except Exception:
        return []

    def _local(tag: str) -> str:
        return str(tag).rsplit("}", 1)[-1].lower()

    def _parse_date(s: str):
        s = (s or "").strip()
        if not s:
            return None
        try:
            return parsedate_to_datetime(s)                       # RFC822 (RSS 2.0)
        except Exception:
            pass
        try:
            return _dt.fromisoformat(s.replace("Z", "+00:00"))   # ISO (dc:date / Atom)
        except Exception:
            return None

    items: list[dict] = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        row = {"title": "", "link": "", "summary": "", "date": None}
        for child in el:
            ln = _local(child.tag)
            txt = (child.text or "").strip()
            if ln == "title" and not row["title"]:
                row["title"] = txt
            elif ln == "link":
                row["link"] = txt or child.get("href", "") or row["link"]
            elif ln in ("description", "summary", "content") and not row["summary"]:
                row["summary"] = re.sub(r"<[^>]+>", "", txt)[:300]
            elif ln in ("pubdate", "date", "published", "updated") and row["date"] is None:
                row["date"] = _parse_date(txt)
        if row["title"]:
            items.append(row)
    return items


def fetch_global_cb_decisions(recency_days: int = 5, now=None) -> list[dict]:
    """Foreign central-bank DECISIONS from official RSS, filtered to the last
    `recency_days`. Returns up to 6 rows {institution, headline, date, summary, url},
    newest first, one per institution. Per-feed try/except — a dead feed never breaks
    the run; total failure returns []. `now` is injectable for testing."""
    from datetime import datetime, timezone, timedelta
    _now = now or datetime.now(timezone.utc)
    cutoff = _now - timedelta(days=recency_days)
    rows: list[dict] = []
    for inst, url in _CB_RSS_FEEDS:
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if resp.status_code != 200 or not resp.text:
                continue
            for it in _parse_rss_items(resp.text):
                title = it["title"]
                if not _CB_DECISION_TITLE_RE.search(title) or _CB_MINUTES_RE.search(title):
                    continue
                dt = it["date"]
                # Require a real date in the PAST window. Several feeds (e.g. BoC) list
                # FUTURE scheduled announcements in advance — surfacing one as a decision
                # would be a temporal-grounding error ("the BoC announced..." before it
                # has). Undated entries are dropped: we can't confirm they are fresh.
                if dt is None:
                    continue
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < cutoff or dt > _now:
                    continue
                rows.append({
                    "institution": inst,
                    "headline": title[:200],
                    "date": (dt.date().isoformat() if dt else ""),
                    "summary": it["summary"][:300],
                    "url": it["link"],
                    "_dt": dt,
                })
        except Exception as exc:
            print(f"[WARN] CB RSS fetch failed ({inst}): {exc}")
    _floor = datetime.min.replace(tzinfo=timezone.utc)
    rows.sort(key=lambda r: (r.get("_dt") or _floor), reverse=True)
    seen: set[str] = set()
    out: list[dict] = []
    for r in rows:
        if r["institution"] in seen:
            continue
        seen.add(r["institution"])
        r.pop("_dt", None)
        out.append(r)
    return out[:6]


def _fetch_fed_speakers_json(today_str: str) -> list[dict]:
    """Today's Fed speaker events from the Fed's structured calendar JSON feed.

    federalreserve.gov/json/calendar.json is the official data behind the HTML calendar —
    2,500+ events, each with title (e.g. "Speech - Governor Lisa D. Cook"), description
    (topic), time, month (YYYY-MM), days, type, location. Far more reliable than scraping
    the rendered HTML (the CSS-selector scrape silently missed Cook & Jefferson on 5/27).
    Returns [] on any failure so the caller can fall back.
    """
    import urllib.request as _ur
    req = _ur.Request("https://www.federalreserve.gov/json/calendar.json",
                      headers={"User-Agent": "Mozilla/5.0"})
    with _ur.urlopen(req, timeout=14) as _resp:
        raw = _resp.read().decode("utf-8-sig", errors="replace")  # strip BOM
    events = json.loads(raw)
    if isinstance(events, dict):
        events = events.get("events") or events.get("days") or []
    out: list[dict] = []
    for ev in (events if isinstance(events, list) else []):
        # Date = month (YYYY-MM) + zero-padded day.
        month = str(ev.get("month", "")).strip()
        day   = str(ev.get("days", "")).strip()
        if not (month and day):
            continue
        ev_date = f"{month}-{int(day):02d}" if day.isdigit() else ""
        if ev_date != today_str:
            continue
        title = str(ev.get("title", "")).strip()
        etype = str(ev.get("type", "")).strip().lower()
        # Speaker events: type "Speeches"/"Testimony", or a title naming an official role.
        _is_speaker = (
            etype in ("speeches", "testimony")
            or any(r in title for r in ("Chair", "Governor", "President", "Vice Chair"))
        )
        if not _is_speaker or len(title) < 4:
            continue
        # Titles read "Speech - Governor Lisa D. Cook" / "Discussion - Vice Chair Philip
        # N. Jefferson". Strip the leading event-kind so the render shows just the role +
        # name (the topic field already conveys what kind of appearance it is).
        speaker = title.split(" - ", 1)[1].strip() if " - " in title else title
        out.append({
            "speaker": speaker,                                 # e.g. "Governor Lisa D. Cook"
            "time_et": str(ev.get("time", "")).strip(),
            "venue":   str(ev.get("location", "")).strip()[:160],
            "topic":   str(ev.get("description", "")).strip()[:200],
        })
    return out


def fetch_fed_speakers() -> list[dict]:
    """Return today's Fed speaker events.

    Primary: the Fed's structured calendar JSON feed (reliable, official). Fallbacks, in
    order: scraping the HTML calendar, then data/fed_speakers_2026.json.
    Output: list of {"speaker": str, "time_et": str, "venue": str, "topic": str}
    """
    today_str = datetime.today().strftime("%Y-%m-%d")
    today_dt  = datetime.today().date()

    def _from_fallback() -> list[dict]:
        path = DATA_DIR / "fed_speakers_2026.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [e for e in (data if isinstance(data, list) else [])
                    if str(e.get("date", ""))[:10] == today_str]
        except Exception:
            return []

    # ── Primary: structured JSON feed ─────────────────────────────────────────
    try:
        _json_speakers = _fetch_fed_speakers_json(today_str)
        if _json_speakers:
            print(f"[FED] {len(_json_speakers)} Fed speaker event(s) today (source: calendar.json).")
            return _json_speakers
    except Exception as _exc:
        print(f"[FED] calendar.json feed failed ({_exc}); trying HTML scrape.")

    # ── Fallback 1: HTML calendar scrape ──────────────────────────────────────
    try:
        import urllib.request as _ur
        from bs4 import BeautifulSoup
        req = _ur.Request(
            "https://www.federalreserve.gov/newsevents/calendar.htm",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with _ur.urlopen(req, timeout=14) as _resp:
            html_bytes = _resp.read()
        soup = BeautifulSoup(html_bytes.decode("utf-8", errors="replace"), "html.parser")

        speakers: list[dict] = []
        # The Fed calendar renders events grouped by date. Each group has a date header
        # (h5 or h4 with a parseable date string) followed by event rows.
        current_date: str | None = None
        for tag in soup.find_all(True):
            # Date header — e.g. <h5 class="...">May 7, 2026</h5>
            if tag.name in ("h4", "h5"):
                txt = tag.get_text(strip=True)
                try:
                    from datetime import datetime as _dtp
                    parsed = _dtp.strptime(txt.strip(), "%B %d, %Y")
                    current_date = parsed.strftime("%Y-%m-%d")
                except Exception:
                    pass
                continue
            # Event rows: look for divs with "eventlist__event" or similar markers
            if tag.name == "div" and current_date == today_str:
                cls = " ".join(tag.get("class") or [])
                if "eventlist__event" not in cls and "row" not in cls:
                    continue
                time_tag    = tag.select_one(".eventlist__time, .col-xs-12.col-md-3")
                heading_tag = tag.select_one(".eventlist__heading, h4, h5, .col-xs-12.col-md-9")
                desc_tag    = tag.select_one(".eventlist__description, p")
                time_et  = time_tag.get_text(strip=True)    if time_tag    else ""
                heading  = heading_tag.get_text(strip=True) if heading_tag else ""
                topic    = desc_tag.get_text(strip=True)    if desc_tag    else ""
                if heading and len(heading) > 3:
                    speakers.append({
                        "speaker":  heading,
                        "time_et":  time_et,
                        "venue":    "",
                        "topic":    topic[:200],
                    })

        if speakers:
            print(f"[FED] Scraped {len(speakers)} Fed event(s) for today.")
            return speakers
    except Exception as _exc:
        print(f"[FED] Fed calendar scrape failed ({_exc}); using fallback.")

    result = _from_fallback()
    if not result:
        print("[FED] No Fed speakers scheduled today (fallback empty).")
    return result


def fetch_economic_calendar() -> list[dict]:
    """Fetch upcoming macro events. Primary: FRED releases. Fallback: NASDAQ.
    Saves results to data/economic_calendar.json for the website to read."""
    events: list[dict] = []
    today     = datetime.today()
    next_4w   = today + timedelta(days=28)

    # ── FRED releases calendar (primary) ─────────────────────────────────────
    # Explicit blocklist — checked before EVENT_MAP so these never match a keyword
    _SKIP_KEYWORDS = {
        # ── daily market/rate series ─────────────────────────────────────────
        "federal funds data", "coinbase", "dow jones", "nasdaq daily",
        "nikkei", "cboe market statistics", "commercial paper",
        "euro short term rate", "interest rate on reserve", "overnight bank",
        "secured overnight", "historical overnight", "optimal blue",
        "ice bofa", "moody", "recession indicator", "key ecb",
        "interest rate spreads", "economic policy uncertainty",
        "kansas city fed policy", "bankrate", "daily treasury", "h.15 selected",
        "temporary open market operations", "tri-party general collateral",
        "sofr averages", "sonia interest rate benchmark",
        # ── commodity / rate surveys (not macro releases) ────────────────────
        "natural gas spot", "gasoline and diesel",
        "primary mortgage market survey",           # weekly Freddie Mac mortgage rates
        # ── state / metro / sub-national breakdowns ──────────────────────────
        "state unemployment insurance weekly claims",  # fires Fri after Thu national release
        "personal income by state", "monthly state retail sales",
        "state employment and unemployment", "state and metro area employment",
        "metropolitan area employment", "labor force participation by state",
        "texas employment data", "alternative measures of labor underutilization",
        # ── derived / model / academic indexes ──────────────────────────────
        "st. louis fed financial stress", "st. louis fed economic news",
        "chicago fed national financial conditions",
        "chicago fed advance",                      # retail trade summary, not CFNAI
        "kansas city financial stress",
        "weekly economic index",                    # Lewis-Mertens-Stock composite
        "brave-butters-kelley",                     # alternative activity index
        "hornstein-kudlyak-lange",                  # non-employment index
        "university of louisville",                 # academic LoDI index
        "fujita, moscarini",                        # academic transition series
        "u.s. recession probabilities",
        "gdp-based recession indicator",
        "debt to gross domestic product",           # ratio series, not a release
        "money velocity", "real money stock",
        "st. louis fed price pressures",
        # ── CPI / PCE variant series (headline already captured) ─────────────
        "current median cpi", "sticky price cpi",
        "research consumer price index", "average price data",
        # ── foreign / international data ────────────────────────────────────
        "bank of japan", "swiss national bank",
        "weekly financial statements of the eurosystem",
        "turkish foreign exchange", "international financial statistics",
        "h.10 foreign exchange", "quarterly national accounts",  # OECD/IMF series
        "financial soundness indicators", "summary measures of the foreign exchange",
        "bis effective exchange rate",
        # ── miscellaneous low-signal series ─────────────────────────────────
        "market hotness index", "visa spending momentum",
        "housing inventory core metrics", "housing vacancies and homeownership",
        "manufactured housing survey",
        "minimum wage rates",
        "market value of u.s. government debt",
        "selected property price", "national rates and rate caps",
        "h.4.1 factors affecting reserve",         # weekly Fed balance sheet
        "h.8 assets and liabilities",              # weekly bank assets
        "h.6 money stock",                         # M2 (low calendar impact)
        "select time series based on",             # SWAA working arrangements research
        "transportation services index",
        "supplemental estimates",                   # GDP supplemental tables
        "gross domestic product by industry",       # deduped anyway, cleaner to skip
        "gross domestic product by state",
        "survey of business uncertainty",
    }
    # Whitelist: only releases matching a keyword below appear on the calendar.
    # ORDER MATTERS — first match wins, so more-specific keys must come first.
    _EVENT_MAP = {
        "fomc minutes":                                    ("Fed FOMC Minutes",                       "high"),
        "minutes of the federal open market committee":    ("Fed FOMC Minutes",                       "high"),
        "fomc press release":                              ("FOMC Meeting / Rate Decision",           "high"),
        "gdpnow":                                      ("Atlanta Fed GDPNow Estimate",            "medium"),
        "consumer price index":                        ("CPI Inflation Report",                   "high"),
        "employment situation":                        ("Non-Farm Payrolls / Jobs Report",         "high"),
        "adp national employment":                     ("ADP Employment Report",                   "high"),
        "producer price index":                        ("PPI Inflation Report",                    "high"),
        "advance monthly sales for retail":            ("Retail Sales",                            "high"),
        "g.17 industrial production":                  ("Industrial Production",                   "medium"),
        # nonmanufacturing MUST precede manufacturing — it's a substring match trap
        "nonmanufacturing business outlook":           ("ISM Non-Manufacturing",                   "medium"),
        "manufacturing business outlook survey":       ("Philly Fed Manufacturing Index",          "medium"),
        "empire state manufacturing survey":           ("Empire State Manufacturing",              "medium"),
        "texas manufacturing outlook":                 ("Dallas Fed Manufacturing",                "medium"),
        "survey of regional conditions and expectations": ("Richmond Fed Survey (SORCE)",          "medium"),
        "harmonized indices of consumer prices":       ("EU CPI / HICP",                          "medium"),
        "national accounts - gdp (eurostat)":          ("Eurozone GDP",                           "medium"),
        "gross domestic product":                      ("GDP Report",                             "high"),
        "unemployment insurance weekly claims":        ("Initial Jobless Claims",                 "high"),
        "ism report on business":                      ("ISM Manufacturing / Services",            "medium"),
        # "surveys of consumers" is FRED's actual release name for UMich
        "surveys of consumers":                        ("UMich Consumer Sentiment",                "high"),
        "university of michigan":                      ("UMich Consumer Sentiment",                "high"),
        "personal income and outlays":                 ("Personal Income & PCE",                   "high"),
        "personal income":                             ("Personal Income & PCE",                   "high"),
        "employment cost index":                       ("Employment Cost Index",                   "medium"),
        "durable goods":                               ("Durable Goods Orders",                    "medium"),
        "manufacturer's shipments, inventories":       ("Factory Orders / Durable Goods",          "medium"),
        "manufacturing and trade inventories":         ("Business Inventories",                    "medium"),
        # new residential sales before new residential — avoid substring mismatch
        "new residential sales":                       ("New Home Sales",                          "medium"),
        "new residential":                             ("Housing Starts / Building Permits",       "medium"),
        "housing units authorized by building permits":("Housing Starts / Building Permits",       "medium"),
        "u.s. international trade in goods":           ("Trade Balance",                           "medium"),
        "trade balance":                               ("Trade Balance",                           "medium"),
        "u.s. import and export price indexes":        ("Import & Export Price Indexes",            "medium"),
        "monthly treasury statement":                  ("Federal Budget Statement",                "medium"),
        "trimmed mean pce":                            ("PCE Inflation (Trimmed Mean)",             "medium"),
        "job openings":                                ("JOLTS Job Openings",                      "medium"),
        "consumer confidence":                         ("Consumer Confidence",                     "medium"),
        "existing home sales":                         ("Existing Home Sales",                     "medium"),
        "new home sales":                              ("New Home Sales",                          "medium"),
        "factory orders":                              ("Factory Orders",                          "medium"),
        "wholesale trade":                             ("Wholesale Inventories",                   "medium"),
        "g.19 consumer credit":                        ("Consumer Credit",                         "medium"),
        "productivity and costs":                      ("Productivity & Unit Labor Costs",          "medium"),
        "construction spending":                       ("Construction Spending",                   "medium"),
        "s&p cotality case-shiller":                   ("Case-Shiller Home Price Index",            "medium"),
        "house price index":                           ("FHFA House Price Index",                  "medium"),
        "advance economic indicators":                 ("Advance Trade & Inventories",             "medium"),
        "chicago fed national activity":               ("Chicago Fed National Activity Index",      "medium"),
        "flash composite pmi":                         ("S&P Global Flash PMI",                   "high"),
        "flash manufacturing pmi":                     ("S&P Global Flash PMI",                   "high"),
        "flash services pmi":                          ("S&P Global Flash PMI",                   "high"),
    }
    try:
        from epm_secrets import FRED_API_KEY as _fk
        # Single call for the full 4-week window (limit=1000 covers all releases)
        _r = requests.get(
            "https://api.stlouisfed.org/fred/releases/dates",
            params={
                "api_key": _fk, "file_type": "json",
                "realtime_start": today.strftime("%Y-%m-%d"),
                "realtime_end":   next_4w.strftime("%Y-%m-%d"),
                "include_release_dates_with_no_data": "true",
                "limit": 1000,
            },
            timeout=30,
        )
        _r.raise_for_status()
        all_release_dates: list[dict] = _r.json().get("release_dates", [])
        seen: set[tuple] = set()
        for rel in all_release_dates:
            name_lc   = rel["release_name"].lower()
            date_str  = rel["date"]
            if any(kw in name_lc for kw in _SKIP_KEYWORDS):
                continue
            clean, imp = None, "medium"
            for kw, (cn, ci) in _EVENT_MAP.items():
                if kw in name_lc:
                    clean, imp = cn, ci
                    break
            if clean is None:
                continue   # whitelist-only: skip anything not in EVENT_MAP
            key = (date_str, clean)
            if key in seen:
                continue
            seen.add(key)
            events.append({"date": date_str, "event": clean, "country": "US",
                           "importance": imp, "actual": None, "consensus": None, "previous": None})
        events.sort(key=lambda x: x["date"])
        # ── Deduplicate FOMC: FRED emits one entry per day for multi-day meetings.
        # Keep only the LAST date per FOMC meeting (the announcement day).
        # Two FOMC entries within 4 days of each other = same meeting.
        fomc_label = "FOMC Meeting / Rate Decision"
        fomc_events = [e for e in events if e["event"] == fomc_label]
        non_fomc    = [e for e in events if e["event"] != fomc_label]
        merged_fomc: list[dict] = []
        for ev in fomc_events:
            from datetime import date as _date
            ev_date = _date.fromisoformat(ev["date"])
            absorbed = False
            for existing in merged_fomc:
                ex_date = _date.fromisoformat(existing["date"])
                if abs((ev_date - ex_date).days) <= 4:
                    # Keep the later date (announcement day)
                    if ev_date > ex_date:
                        existing["date"] = ev["date"]
                    absorbed = True
                    break
            if not absorbed:
                merged_fomc.append(dict(ev))
        events = sorted(non_fomc + merged_fomc, key=lambda x: x["date"])
        print(f"[CAL] Fetched {len(events)} economic events from FRED releases.")
        # Enrich FRED events with Finnhub consensus/previous (FRED never returns these)
        try:
            from epm_secrets import FINNHUB_KEY as _fhk_enrich
            _fh_enr = requests.get(
                "https://finnhub.io/api/v1/calendar/economic",
                params={"from": today.strftime("%Y-%m-%d"),
                        "to": (today + timedelta(days=7)).strftime("%Y-%m-%d"),
                        "token": _fhk_enrich},
                timeout=12,
            )
            _fh_enr.raise_for_status()
            _fh_ev_list = _fh_enr.json().get("economicCalendar", [])
            # Index Finnhub events by date + lowercased event name
            _fh_idx: dict[str, dict[str, dict]] = {}
            for _fhe in _fh_ev_list:
                _fhd = str(_fhe.get("time", ""))[:10]
                _fhn = str(_fhe.get("event", "")).lower().strip()
                _fh_idx.setdefault(_fhd, {})[_fhn] = {
                    "consensus": _fhe.get("estimate"),
                    "previous":  _fhe.get("prev"),
                }
            _enriched_count = 0
            for _ev in events:
                if _ev.get("consensus") is not None:
                    continue
                _evd  = _ev["date"]
                _evn  = _ev["event"].lower().strip()
                _day  = _fh_idx.get(_evd, {})
                # Direct name match first
                if _evn in _day:
                    _ev["consensus"] = _day[_evn]["consensus"]
                    _ev["previous"]  = _day[_evn]["previous"]
                    _enriched_count += 1
                    continue
                # Partial match: ≥2 shared words
                _ev_words = set(_evn.split())
                for _fn, _fd in _day.items():
                    if len(_ev_words & set(_fn.split())) >= 2:
                        _ev["consensus"] = _fd["consensus"]
                        _ev["previous"]  = _fd["previous"]
                        _enriched_count += 1
                        break
            if _enriched_count:
                print(f"[CAL] Finnhub enriched {_enriched_count} event(s) with consensus/previous.")

            # FRED's release calendar structurally OMITS ISM (private ISM, Inc. data), so
            # ISM Manufacturing/Services never appear above even though they are top-tier
            # market movers — the recurring "missed ISM Services" gap. Finnhub DOES carry
            # them, so ingest the allowlisted, US-only events here and append any not already
            # present. Kept to a tight allowlist so Finnhub's noisy global calendar can't
            # pollute the FRED-curated list.
            _FINNHUB_ADD = {
                "ism services":          ("ISM Services Index",      "high"),
                "ism non-manufacturing": ("ISM Services Index",      "high"),
                "ism manufacturing":     ("ISM Manufacturing Index", "high"),
            }
            _have = {(e["date"], e["event"]) for e in events}
            _added = 0
            for _fhe in _fh_ev_list:
                if str(_fhe.get("country", "")).upper() not in ("US", "USA", "UNITED STATES"):
                    continue
                _nm = str(_fhe.get("event", "")).lower().strip()
                _match = next(((cn, ci) for kw, (cn, ci) in _FINNHUB_ADD.items() if kw in _nm), None)
                if _match is None:
                    continue
                _clean, _imp = _match
                _d = str(_fhe.get("time", ""))[:10]
                if not _d or (_d, _clean) in _have:
                    continue
                _have.add((_d, _clean))
                events.append({"date": _d, "event": _clean, "country": "US",
                               "importance": _imp, "actual": _fhe.get("actual"),
                               "consensus": _fhe.get("estimate"), "previous": _fhe.get("prev")})
                _added += 1
            if _added:
                events.sort(key=lambda x: x["date"])
                print(f"[CAL] Added {_added} Finnhub-only event(s) FRED omits (e.g. ISM).")
        except Exception:
            pass  # enrichment is best-effort; FRED events still ship without it
    except Exception as exc:
        print(f"[WARN] FRED economic calendar failed: {exc} — trying NASDAQ fallback")
        try:
            url = ("https://api.nasdaq.com/api/calendar/economicevents"
                   f"?date={today.strftime('%Y-%m-%d')}&dateend={(today+timedelta(days=28)).strftime('%Y-%m-%d')}")
            rows = (requests.get(url, headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"},
                                  timeout=15).json().get("data") or {}).get("rows") or []
            for r in rows:
                imp = str(r.get("importance") or "").lower()
                if imp not in ("high","moderate","medium","low"):
                    imp = "medium"
                events.append({"date": str(r.get("eventDate") or ""), "event": str(r.get("eventName") or ""),
                               "country": str(r.get("country") or "US"), "importance": imp,
                               "actual": r.get("actual"), "consensus": r.get("consensus"),
                               "previous": r.get("previous")})
            print(f"[CAL] NASDAQ fallback: {len(events)} events.")
        except Exception as exc2:
            print(f"[WARN] NASDAQ fallback also failed: {exc2}")
        if not events:
            try:
                from epm_secrets import FINNHUB_KEY as _fhk
                r = requests.get(
                    "https://finnhub.io/api/v1/calendar/economic",
                    params={"from": today.strftime("%Y-%m-%d"),
                            "to": (today + timedelta(days=28)).strftime("%Y-%m-%d"),
                            "token": _fhk},
                    timeout=12,
                )
                r.raise_for_status()
                fh_events = r.json().get("economicCalendar", [])
                for e in fh_events:
                    imp_raw = str(e.get("impact") or "").lower()
                    imp = {"high": "high", "medium": "moderate", "low": "low"}.get(imp_raw, "low")
                    events.append({"date": str(e.get("time", ""))[:10], "event": str(e.get("event", "")),
                                   "country": str(e.get("country", "US")), "importance": imp,
                                   "actual": e.get("actual"), "consensus": e.get("estimate"),
                                   "previous": e.get("prev")})
                print(f"[CAL] Finnhub fallback: {len(events)} events.")
            except Exception as exc3:
                print(f"[WARN] Finnhub calendar fallback also failed: {exc3}")

    # ── Inject FOMC dates from the Fed's published schedule. ─────────────────
    # FRED's /releases/dates API misses the current meeting when the press
    # release falls on or before today's realtime_start boundary. We supplement
    # from the Fed's own JSON calendar (with a hardcoded 2026 fallback) so the
    # FOMC always appears in the 4-week view regardless of FRED timing.
    import calendar as _cal_mod
    from datetime import date as _ddate
    _today_d  = today.date() if hasattr(today, "date") else _ddate.fromisoformat(str(today)[:10])
    _next4w_d = next_4w.date() if hasattr(next_4w, "date") else _ddate.fromisoformat(str(next_4w)[:10])
    _fomc_label = "FOMC Meeting / Rate Decision"
    _fomc_dates: list[str] = []
    try:
        _fed_r = requests.get(
            "https://www.federalreserve.gov/monetarypolicy/json/fomcCalendars.json",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        _fed_r.raise_for_status()
        _fed_json = _fed_r.json()
        # Format: list of year-blocks, each with "year" and list of meeting dicts.
        # Each meeting has "month" (name string) and "day" (e.g. "27-28" or "28").
        for _yr_block in (_fed_json if isinstance(_fed_json, list) else []):
            try:
                _yr = int(_yr_block.get("year", 0))
            except (ValueError, TypeError):
                continue
            for _mtg in (_yr_block.get("meetings") or []):
                _month_str = str(_mtg.get("month") or _mtg.get("Month") or "").strip().capitalize()
                _day_str   = str(_mtg.get("day")   or _mtg.get("Day")   or "").strip()
                if not _month_str or not _day_str:
                    continue
                try:
                    _month_num = list(_cal_mod.month_name).index(_month_str)
                    _last_day  = int(_day_str.split("-")[-1].strip())
                    _fomc_dates.append(f"{_yr:04d}-{_month_num:02d}-{_last_day:02d}")
                except Exception:
                    continue
        if _fomc_dates:
            print(f"[CAL] Fed calendar: {len(_fomc_dates)} FOMC announcement dates fetched.")
    except Exception as _fe:
        print(f"[CAL] Fed calendar fetch failed ({_fe}); using hardcoded 2026 FOMC dates.")

    if not _fomc_dates:
        # Announcement dates (last day of each 2026 FOMC meeting).
        # Source: Federal Reserve published schedule.
        # Update annually when the Fed releases the following year's dates (usually November).
        # 2026-06-15: June corrected 06-10 -> 06-17 (the Warsh-led meeting concludes Wed 6/17);
        # the stale 6/10 sat in the past by mid-week so the decision never entered the forward
        # calendar and the scenario engine missed it. NOTE: fomcCalendars.json 404s — this
        # hardcoded list is the sole source until the Fed JSON endpoint is fixed.
        _fomc_dates = [
            "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
            "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
        ]

    # Add any FOMC date in [today, next_4w] not already covered in events.
    _existing_fomc = {e["date"] for e in events if e["event"] == _fomc_label}
    for _fd in _fomc_dates:
        try:
            _fd_d = _ddate.fromisoformat(_fd)
        except ValueError:
            continue
        if _fd_d < _today_d or _fd_d > _next4w_d:
            continue
        # Skip if already present within ±2 days (catches FRED's day-1 variant)
        if any(abs((_fd_d - _ddate.fromisoformat(_ex)).days) <= 2 for _ex in _existing_fomc):
            continue
        events.append({
            "date": _fd, "event": _fomc_label, "country": "US",
            "importance": "high", "actual": None, "consensus": None, "previous": None,
        })
        _existing_fomc.add(_fd)
        print(f"[CAL] Injected FOMC date: {_fd}")
    # ── Inject FOMC Minutes dates (3 weeks / 21 days after each announcement). ─
    # FRED never surfaces these; Fed website JSON is unreliable. Derive from the
    # same hardcoded/fetched announcement list so Minutes always appear in the
    # 4-week view when due.
    _minutes_label = "Fed FOMC Minutes"
    _existing_minutes = {e["date"] for e in events if e["event"] == _minutes_label}
    for _fd in _fomc_dates:
        try:
            _min_d = _ddate.fromisoformat(_fd) + timedelta(days=21)
        except (ValueError, TypeError):
            continue
        _min_str = _min_d.isoformat()
        if _min_d < _today_d or _min_d > _next4w_d:
            continue
        if any(abs((_min_d - _ddate.fromisoformat(_ex)).days) <= 1 for _ex in _existing_minutes):
            continue
        events.append({
            "date": _min_str, "event": _minutes_label, "country": "US",
            "importance": "high", "actual": None, "consensus": None, "previous": None,
        })
        _existing_minutes.add(_min_str)
        print(f"[CAL] Injected FOMC Minutes date: {_min_str}")

    # ── Inject Flash PMI dates (3rd Friday of each month, S&P Global). ──────
    # S&P Global Flash PMI is not a FRED release. Published ~3rd Friday monthly.
    _pmi_label = "S&P Global Flash PMI"
    _existing_pmi = {e["date"] for e in events if e["event"] == _pmi_label}
    for _yr, _mo in {(_today_d.year, _today_d.month), (_next4w_d.year, _next4w_d.month)}:
        # Find 3rd Friday of month (try/except guards short months)
        _fridays = []
        for _d in range(1, 32):
            try:
                _day = _ddate(_yr, _mo, _d)
            except ValueError:
                break
            if _day.weekday() == 4:
                _fridays.append(_day)
        if len(_fridays) < 3:
            continue
        _pmi_d   = _fridays[2]
        _pmi_str = _pmi_d.isoformat()
        if _pmi_d < _today_d or _pmi_d > _next4w_d:
            continue
        if _pmi_str in _existing_pmi:
            continue
        events.append({
            "date": _pmi_str, "event": _pmi_label, "country": "US",
            "importance": "high", "actual": None, "consensus": None, "previous": None,
        })
        _existing_pmi.add(_pmi_str)
        print(f"[CAL] Injected Flash PMI date: {_pmi_str}")

    events.sort(key=lambda x: x["date"])

    try:
        cal_path = DATA_DIR / "economic_calendar.json"
        with open(cal_path, "w", encoding="utf-8") as f:
            json.dump({"updated": today.strftime("%Y-%m-%d"), "events": events},
                      f, indent=2, ensure_ascii=False, default=str)
    except Exception as exc:
        print(f"[WARN] Could not save economic_calendar.json: {exc}")

    return [e for e in events if e["importance"] in ("high", "moderate", "medium")]


RECENT_EARNINGS_LOOKBACK_DAYS = 7


def load_recent_earnings_actuals() -> list[dict]:
    """Return tickers with confirmed actuals released within the last N days.

    Reads data/earnings_releases.json (written by earnings_refresh.py) and
    surfaces the structured result to the LLM prompt so it knows which tickers
    have ALREADY reported and can cite actual EPS / surprise figures instead of
    writing 'upcoming earnings' for them.
    """
    path = DATA_DIR / "earnings_releases.json"
    if not path.exists():
        return []
    try:
        releases = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_EARNINGS_LOOKBACK_DAYS)
    out: list[dict] = []
    for ticker, rec in (releases or {}).items():
        if not rec.get("actuals_available"):
            continue
        try:
            as_of = datetime.fromisoformat(str(rec.get("as_of", "")).replace("Z", "+00:00"))
        except Exception:
            continue
        if as_of < cutoff:
            continue
        out.append({
            "ticker":           ticker,
            "earnings_date":    rec.get("earnings_date"),
            "eps_actual":       rec.get("eps_actual"),
            "eps_estimate":     rec.get("eps_estimate"),
            "eps_surprise_pct": rec.get("eps_surprise_pct"),
        })
    out.sort(key=lambda r: abs(r.get("eps_surprise_pct") or 0), reverse=True)
    return out


# Macro series to surface as "recently released" prints, with display formatting.
# fmt: "k"=raw count→thousands (claims), "kth"=already-thousands (NFP),
#      "pct"=percent YoY/QoQ, "num"=raw number.
_MACRO_PRINT_SPEC = [
    ("Core PCE (YoY)",         "Core PCE (YoY)",            "pct"),
    ("PCE (YoY)",              "PCE (YoY)",                 "pct"),
    ("Core CPI (YoY)",         "Core CPI (YoY)",            "pct"),
    ("CPI (YoY)",              "CPI (YoY)",                 "pct"),
    ("GDP Growth (QoQ)",       "GDP Growth (QoQ, ann.)",    "pct"),
    # ISM Manufacturing is a top-tier market mover (YCharts-sourced; FRED omits it —
    # see the Finnhub calendar backfill). It was in arbitrated econ but absent from
    # this spec, so it never reached the recap: on 2026-07-02 the day's headline ISM
    # print (53.3 vs 54.0) was missed and the model led with stale Consumer Sentiment.
    ("ISM Manufacturing PMI",  "ISM Manufacturing PMI",     "raw"),
    ("Initial Jobless Claims", "Initial Jobless Claims",    "k"),
    ("Nonfarm Payrolls",       "Nonfarm Payrolls",          "kth"),
    ("JOLTS Job Openings",     "JOLTS Job Openings",        "m"),
    ("Retail Sales (MoM)",     "Retail Sales (MoM)",        "pct"),
    ("Unemployment Rate",      "Unemployment Rate",         "pct"),
    ("PPI (YoY)",              "PPI (YoY)",                 "pct"),
    ("Consumer Sentiment",     "Consumer Sentiment",        "raw"),
]


# Words too common to distinguish one macro indicator from another — excluded when
# matching a calendar event name against a macro-print label.
_MACRO_STOPWORDS = frozenset({
    "the", "of", "and", "index", "rate", "report", "data", "yoy", "qoq", "mom",
    "job", "jobs", "monthly", "annual", "us", "u.s", "final", "prelim", "preliminary",
})


def _significant_tokens(name: str) -> set:
    """Distinctive lowercased word tokens of a macro name (e.g. 'JOLTS Job Openings' ->
    {'jolts','openings'}). Used to match a calendar event to a macro-print label."""
    toks = re.findall(r"[a-z]{3,}", str(name or "").lower())
    return {t for t in toks if t not in _MACRO_STOPWORDS}


def _recent_calendar_release_names(cutoff) -> list[str]:
    """Event names from economic_calendar.json whose RELEASE date is within [cutoff, today].
    Best-effort; returns [] on any error or missing file."""
    try:
        cal_path = DATA_DIR / "economic_calendar.json"
        if not cal_path.exists():
            return []
        cal = json.loads(cal_path.read_text(encoding="utf-8"))
        today = datetime.today().date()
        names = []
        for ev in (cal.get("events") or []):
            d = str(ev.get("date", ""))[:10]
            try:
                dd = datetime.strptime(d, "%Y-%m-%d").date()
            except ValueError:
                continue
            if cutoff <= dd <= today:
                nm = str(ev.get("event", "")).strip()
                if nm:
                    names.append(nm)
        return names
    except Exception:
        return []


# In recent_only mode, one of these is retained as inflation context even when stale
# (preference order — the richest core gauge first).
_INFLATION_ANCHORS = ("Core PCE (YoY)", "PCE (YoY)", "Core CPI (YoY)", "CPI (YoY)")


def load_recent_macro_prints(lookback_days: int = 10, recent_only: bool = False) -> list[dict]:
    """Return recently-released macro prints with actual + prior values for the
    economics recap. Reads data/market_data_arbitrated.json (written by
    data_arbiter.py). Supplies the ACTUAL figures so economics_commentary recaps
    real releases (e.g. "Jobless Claims 215k vs 210k prior") instead of
    hallucinating numbers — the 2026-06-01 report invented "211k in line with
    211k prior" because no claims value was ever passed to the model.

    Filtered to series whose latest observation date is within lookback_days, so
    only genuinely-recent releases surface (monthly/quarterly series with stale
    observation dates are dropped rather than misframed as "this week")."""
    path = DATA_DIR / "market_data_arbitrated.json"
    if not path.exists():
        return []
    try:
        econ = (json.loads(path.read_text(encoding="utf-8")) or {}).get("economics") or {}
    except Exception:
        return []

    def _fmt(val, kind: str) -> str | None:
        try:
            v = float(val)
        except (TypeError, ValueError):
            return None
        if kind == "k":
            return f"{v/1000:.0f}k"
        if kind == "kth":
            return f"{v:.0f}k"
        if kind == "m":              # level in thousands -> millions (JOLTS: 7620 -> "7.62M")
            return f"{v/1000:.2f}M"
        if kind == "pct":
            # YCharts API v4 supplies pct econ values as decimal fractions
            # (0.042 = 4.2%); the legacy scraper supplied them already as
            # percentages (4.2). Normalise both: a magnitude < 1 is a decimal
            # fraction -> scale to percent. Without this, the 6/25 YCharts
            # migration made EVERY econ print render "0.0%" (decimal 0.042 -> 0.0%).
            if abs(v) < 1:
                v *= 100
            return f"{v:.1f}%"
        return f"{v:.1f}"

    cutoff = (datetime.today() - timedelta(days=lookback_days)).date()

    # Release-date awareness: a monthly series is RELEASED ~1 month after its reference
    # month, so its observation date lags (JOLTS for May prints end of June). Keying
    # "recent" purely on the observation date drops a freshly-RELEASED print on its release
    # day (2026-07-01: May JOLTS, the day's headline release, looked "stale"). Cross-check
    # the economic calendar: an indicator whose release is dated within the lookback window
    # counts as recent even when its reference-month observation is older.
    _released_names = _recent_calendar_release_names(cutoff)

    def _released_recently(label: str) -> bool:
        toks = _significant_tokens(label)
        return any(toks & _significant_tokens(nm) for nm in _released_names)

    out: list[dict] = []
    for src_key, label, kind in _MACRO_PRINT_SPEC:
        rec = econ.get(src_key)
        if not isinstance(rec, dict):
            continue
        actual = _fmt(rec.get("value"), kind)
        prior  = _fmt(rec.get("prev_value"), kind)
        if actual is None:
            continue
        date_str = str(rec.get("date", ""))[:10]
        try:
            obs_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            obs_date = None
        # Weekly series (claims) carry a recent observation date; monthly/quarterly series
        # lag — keep the latter as "recent" if the observation is within lookback OR the
        # calendar shows it was released within the window.
        is_recent = (obs_date is not None and obs_date >= cutoff) or _released_recently(label)
        out.append({
            "indicator": label,
            "actual":    actual,
            "prior":     prior,
            "as_of":     date_str,
            "recent":    is_recent,
        })
    # Recent releases first, then by indicator order already established.
    out.sort(key=lambda r: (not r["recent"],))
    # recent_only honours this loader's contract for the LLM payload: a monthly/quarterly
    # series whose observation is stale AND that was not released within the window is DROPPED
    # rather than handed to the model, which otherwise recaps a 39-day-old PCE as if it were
    # current inflation (2026-07-09: "inflation remains sticky at 4.1% YoY" cited a 5/31 PCE).
    # Exception: retain ONE inflation gauge as context so the recap isn't left bland when no
    # inflation print is fresh (2026-07-10: economics went generic with zero figures) — the
    # single latest YoY reading is legitimate context, framed by the prompt as "the latest".
    if recent_only:
        kept = [r for r in out if r["recent"]]
        if not any(r["indicator"] in _INFLATION_ANCHORS for r in kept):
            for pref in _INFLATION_ANCHORS:
                anchor = next((r for r in out if r["indicator"] == pref), None)
                if anchor:
                    kept.append(anchor)
                    break
        out = kept
    return out


# ---------------------------------------------------------------------------
# LLM prompts  split into two focused calls to stay within 14B model limits
# ---------------------------------------------------------------------------

WRITING_RULES = """You are a senior market strategist writing for EPM Financial's daily Market Intelligence Report.
Rules: tight analytical prose; no filler; present tense; active voice.
NEVER use: "geopolitical tensions", "geopolitical risks", "global uncertainties", "amid uncertainty", "amid concerns", "it is worth noting", "in conclusion", "overall,", "moving forward".
All market directions MUST match the sign of pct_change values provided.
Do NOT describe a yield or price as "unchanged" if a non-zero pct_change is provided — state the actual direction (rose/fell) and magnitude instead.
Do not invent figures or events not in the payload.
Do NOT attribute geopolitical actions, policy proposals, or peace initiatives to specific companies or financial institutions — if a headline mentions a bank alongside a geopolitical event, the bank is a commentator or stakeholder, not the actor proposing the policy.
Do NOT escalate the severity of geopolitical events beyond the exact language in the payload — if headlines say "tensions" or "conflict", do not write "war"; if they say "negotiations", do not write "deal reached".
NARRATIVE COHERENCE: All sections must describe the same geopolitical reality. If one section cites escalating risk ("expanded strikes", "rising tensions"), no other section may simultaneously frame the same situation as de-escalating ("easing tensions", "peace deal hopes", "ceasefire optimism"). Pick the dominant tone from the headlines payload and apply it consistently across every section.
GEOPOLITICAL GROUNDING (critical): The payload's geopolitical_context is the AUTHORITATIVE current state of the Iran / Middle-East storyline — it is FRESHLY sourced and overrides any older headline elsewhere in the payload. Obey it exactly: (a) when geopolitical_context.direction is "easing", the storyline is de-escalating and any geopolitical clause must reflect that a DRAINING risk/oil-supply premium pushes oil LOWER and softens the safe-haven bid (this is risk-ON) — you may NOT write "fading peace hopes", "rising tensions", or "supply fears" as a driver; (b) when it is "escalating", the risk premium is RISING (higher oil, firmer safe-havens); (c) when geopolitical_context.direction is "unclear", OR geopolitical_context is absent/null, do NOT attribute ANY market move to Iran / the Middle East / a ceasefire in ANY section — drop the geopolitical causal clause entirely and lead with the data-grounded drivers (sector rotation, the day's macro releases from recent_macro_prints, Fed/rate expectations). NEVER contradict geopolitical_context.direction, and NEVER resurrect a stale Iran headline that conflicts with it.
LEAD WITH THE MARKET DRIVER, NOT ONE HEADLINE: identify what actually moved the tape from the DATA — the leading/lagging sectors (sector_top3/sector_bottom3) and the biggest single-name movers — and lead with that. Do NOT frame the entire session around one geopolitical storyline (e.g., a ceasefire) when sector and price action point elsewhere: if Technology leads on AI/earnings while geopolitics is a side note, the lead is the tech/AI move and geopolitics is secondary context — not the headline. Avoid monothematic commentary where every section repeats the same single theme; each section should add a distinct, data-grounded angle. STORYLINE DE-DUPLICATION: a single geopolitical storyline (e.g. a "pause in strikes" / ceasefire / Middle East de-escalation) may be the explicit causal driver in AT MOST two sections. Where it is genuinely relevant elsewhere, reference it once and briefly (a clause, not a re-explanation) or vary the framing — do NOT repeat the same "pause in [Middle East hostilities/strikes]" clause verbatim in the recap, rates, commodities, FX, synthesis, AND outlook. Each section's causal clause should foreground that section's OWN dominant driver.
ONE-SHOT CALIBRATION — geopolitical tone (follow this pattern exactly):
  Headline in payload: "U.S. and Israel expand strikes near Iranian facilities; diplomatic talks stall"
  BAD: "Mounting costs of the Iran war strain U.S. finances as the conflict widens."
  GOOD: "Markets are pricing a higher risk premium after reports of expanded strikes near Iranian facilities; diplomatic talks remain unresolved."
  Rule: mirror the payload's exact language — do not upgrade 'strikes' to 'war', do not assert fiscal or political consequences as fact, do not name a conflict as an ongoing war unless the payload explicitly uses that word.
UNCONFIRMED EVENTS ARE NOT FACTS (critical): A ceasefire, truce, peace deal, or agreement is NOT confirmed until a payload headline states it has been signed/finalized/reached. Until then, frame it as expectation, not accomplishment: "ceasefire hopes", "reported/expected ceasefire", "if the truce holds", "markets are pricing a ceasefire". NEVER write that an unconfirmed event "validates", "confirms", "eases", or "removes" anything, and NEVER cite a "memorandum", "agreement", or "deal" as a settled driver unless a headline names it as signed. The same restraint applies symmetrically to de-escalation and escalation.
  ONE-SHOT CALIBRATION — unconfirmed ceasefire (follow exactly):
    Headline in payload: "Markets still expect a US-Iran ceasefire in coming days; the two sides again exchanged limited strikes"
    BAD: "The 60-day truce memorandum validates the soft-landing narrative; the ceasefire eases supply fears."
    GOOD: "Stocks held gains on continued ceasefire hopes even as the two sides exchanged limited strikes; a signed truce remains the key unconfirmed catalyst."
WINDOW & SUPERLATIVE FIDELITY: any claim about a multi-day window or a superlative MUST match the sign of that window's data. Do NOT say the dollar made its "biggest weekly gain", "best week", or "hit a six-week high" when DXY's daily or weekly pct_change is negative — if the dollar fell, say it fell. Do NOT say "rising yields"/"higher yields" as a current driver when the 10-Yr bp_change is <= 0 on the day and on the week. A DECLINE can never be attributed to a bullish driver: if WTI fell, do NOT explain it with "supply shocks", "renewed tensions", or "supply disruption" — a falling price reflects easing supply fear, not rising it. Match driver polarity to the move.
Do NOT cite foreign central banks (BoE, ECB, BoJ, PBoC, RBA, BoC, SNB) or foreign sovereign yields (Gilts, Bunds, JGBs) as drivers of US asset moves unless a US-asset headline in the payload explicitly names that institution. Foreign monetary policy may move foreign assets in the international section; for US equities, US bonds, and US dollar commentary, drivers must come from the US payload.
EMERGING-MARKET DEBT IS OFF-UNIVERSE (critical): emerging-market bonds / EM debt / EM local-currency bonds are NOT part of this report's universe. When the payload carries a Fed-hawkishness headline framed around EM bonds (e.g. "hawkish Fed challenges the EM bond rally"), express the Fed angle in US equities, US Treasuries, the dollar, and commodities sections through its US effect ONLY — firmer-for-longer US yields, growth-multiple pressure, a firmer dollar — NEVER as an "emerging-market bond rally/recovery/selloff". Do NOT close a Commodities or US-Dollar line on EM bonds; they do not move crude or DXY.
SINGLE-CATALYST ATTRIBUTION ON A FLAT TAPE (critical): when the S&P 500's daily move is within ±0.25%, do NOT name a single off-universe or niche cross-asset storyline (e.g. an EM-bond item, one foreign print) as THE cause of the index's move — a flat tape is rotation/positioning, not one headline. State the rotation; if you cite the catalyst at all, frame it as a backdrop that "caps risk appetite", not the driver of the close.
COMMITTED VOICE: take a side. The reader pays to know what YOU think, not which way it could go. Forbidden: "investors should watch", "remains to be seen", "wait-and-see", "could go either way", "markets face headwinds", "cautious optimism", "the outlook is mixed", "uncertainty persists". State the directional view, then the conditions that would invalidate it.
CAUSAL LINKAGE: every commentary section must name a cause and effect, not just describe a level. Wrong: "the 10-year yield fell 6 bp to 4.50%." Right: "the 10-year yield fell 6 bp to 4.50% as falling oil prices eased the inflation impulse, providing relief to growth-name multiples." Connect at least one named driver and one downstream effect.
GROWTH-MULTIPLE DIRECTION (critical): Falling oil prices and falling Treasury yields are TAILWINDS for growth/tech equity multiples — they relieve discount-rate and inflation pressure, they do not compress it. NEVER attribute a technology or growth-equity selloff, or "compressed/compressing multiples", to lower oil or lower yields. If tech fell on a day when oil and/or yields also fell, the tech driver is its OWN story (AI-capex sustainability doubts, stretched valuations, a single-name disappointment, a broken deal) — name that driver, and treat the lower oil/yields as a partial OFFSET, not the cause. The only correct direction: oil/yields DOWN → multiples RELIEVED; oil/yields UP → multiples PRESSURED.
RISK-ON / RISK-OFF POLARITY (critical): "risk-off" means investors flee TO safety — equities FALL while safe-havens (gold, Treasuries, the yen, VIX) RISE. "risk-on" is the mirror image — equities RISE while safe-havens fall. Match the label to the tape: if the S&P 500 closed higher and equities rallied, the regime is RISK-ON, even when the catalyst is geopolitical de-escalation — a peace deal or ceasefire that drains the safe-haven and oil-supply premium is RISK-ON, not risk-off. NEVER call falling gold or falling oil "risk-off sentiment" (a falling safe-haven is risk-ON), NEVER write that a "risk-off backdrop supported/lifted equities", and NEVER call risk-off "the dominant theme" on a day the S&P closed higher (and vice-versa for risk-on on a down day). The only exception is genuine cross-asset divergence, which you must state explicitly (e.g. "equities rallied even as a residual bid for Treasuries signaled lingering caution"). CROSS-SECTION CONSISTENCY (2026-06-26): pick ONE characterization of the session's risk regime and use it in EVERY section — never label the same day "risk-on" in one place (recap, quant read) and "risk-off" in another (spotlight, outlook). When the tape is genuinely flat or mixed (|S&P 500 daily move| < ~0.25%, or cyclical-sector leadership coexisting with a geopolitical safe-haven bid), call it a "mixed session" explicitly rather than asserting opposite regimes in different sections.
RELEVANCE — NO TANGENTIAL COLOR (critical): Every causal clause must explain the session's actual price move or a near-term catalyst the reader is positioning for. Do NOT decorate a market line with color that does not move the tape: a public figure's reaction or endorsement (a politician's, central banker's, or clergy member's statement of thanks/approval), or a single company's distant forward-quarter revenue/earnings ESTIMATE, do not belong in a pre-market bullet or commentary sentence unless that specific item is what moved the price. If a detail is real but does not bear on the move or an imminent catalyst, omit it — restraint beats embellishment.
FORWARD HOOK: each commentary section's closing sentence must name a specific price level, threshold, or catalyst the reader is watching next — never generic ("traders will be watching" is banned).
Return ONLY valid JSON  no markdown fences, no explanation."""

# Call 1: Market narrative sections
SYSTEM_PROMPT_NARRATIVE = WRITING_RULES + """

Return JSON with EXACTLY these 6 keys (no others):
pre_market_bullets, equities_commentary, fixed_income_commentary, commodities_commentary, currencies_commentary, economics_commentary

{"pre_market_bullets":["...","...","...","...","..."],"equities_commentary":"...","fixed_income_commentary":"...","commodities_commentary":"...","currencies_commentary":"...","economics_commentary":"..."}

SESSION FRAME: The payload "date" field is the report date. All pct_change, level, and bp_change values in market_levels, bonds, commodities, and currencies reflect the PREVIOUS SESSION's closing values — that is the session you are narrating. recent_earnings_actuals contain results released AFTER that session's close; they did NOT move session equity returns. Mention them in equities_commentary as "after the close" or "in extended trading" only — NEVER credit them as drivers of the day's S&P 500 return.

FLAT-DAY EQUITY RULE: If market_levels["S&P 500"]["pct_change"] is between -0.30% and +0.30%, do NOT write "rallied", "surged", "soared", "jumped", or "plunged" for the overall market. Instead write "closed essentially flat", "ended little changed", or "traded in a narrow range" and pivot to sector rotation or a specific catalyst story.

NUMBER FIDELITY (non-negotiable):
- Every percent and price you cite MUST equal the value in the payload to within 0.01.
- S&P 500: use market_levels["S&P 500"]["pct_change"] for the percent; ["level"] for the price.
- Apply the same rule for Nasdaq 100, DXY, Gold, WTI Crude against market_levels / commodities_top6 / currencies_top5.
- For 10-Yr Yield: cite the daily move in BASIS POINTS using market_levels["10-Yr Yield"]["bp_change"] (e.g. "+2 bp", "-5 bp"). NEVER write a percent sign after a yield move ("+0.44%" is wrong; "+2 bp" is correct).
- Direction words (rose/fell/gained/slid) MUST agree with the SIGN of pct_change. A pct_change of -0.04% is "essentially flat" or "barely changed" — NOT "lower" or "fell".
- SIGN PRESERVATION (most-violated rule): If pct_change is negative, the cited percent must be negative AND the verb must be "fell"/"slid"/"declined". If pct_change is positive, the cited percent must be positive AND the verb must be "rose"/"gained"/"climbed". Magnitude alone is wrong — sign and verb must both match.
  BAD: snapshot WTI Crude pct_change=-0.79 → "WTI rose 0.79% on supply concerns" (sign flipped, verb wrong)
  GOOD: snapshot WTI Crude pct_change=-0.79 → "WTI fell 0.79% to $94.99 on softer Asian demand"
- MAGNITUDE FIDELITY: Always cite the percent figure from pct_change, never the raw dollar delta. A $2.20 move on $4720 gold is +0.05%, not +2.2%. If you find yourself writing a number like "2.2002" or any figure that looks like a dollar amount rather than a percent, stop and use the pct_change from the payload instead.
- CAUSAL CONSISTENCY: The driver you cite must logically support the direction you report. "Fewer/lower rate hike expectations" and "peace deal hopes" both pull yields DOWN — if yields rose, do not use these as drivers. "Hawkish Fed/inflation data" pulls the dollar UP. Safe-haven buying pushes gold UP. If your verb says "rose" but your driver implies "down", rewrite either the verb or the driver to eliminate the contradiction.
- If a number is missing from the payload, OMIT it entirely. Do NOT estimate, round, or invent.
- Tickers in recent_earnings_actuals have ALREADY released earnings this week — never write "later this week" or "upcoming earnings" for them. If you mention one, cite the reported EPS and surprise % from the payload.

pre_market_bullets: Array of 5 strings:
  [0] Use the following template verbatim as the first bullet, replacing {catalyst} with one specific driver from recent_headlines (e.g. "megacap earnings beat", "tariff headlines"). Keep all numbers exactly as given — do NOT alter them. Template: BULLET_0_TEMPLATE
  [1] International/macro driver — cite one specific market-moving event (earnings beat/miss, geopolitical development, central bank action, major economic data). NEVER cite broker promotions, ebooks, webinars, or sponsored content.
  [2] Economic calendar: check todays_economic_events first. If it has entries, cite the most important one — include scheduled time and consensus vs prior — format: "Key data today: [Event] at [time] ET — consensus [X] vs prior [Y]; a [beat/miss] would [1-sentence market implication]." If todays_economic_events is EMPTY, cite the next important event from week_ahead_econ_events by its WEEKDAY name — format: "[Weekday]'s [Event] (consensus [X] vs prior [Y]) will be the next macro test." NEVER call a week_ahead_econ_events entry "today". If both lists are empty, OMIT this bullet and produce only 4 items total.
  [3] Fed/rates: cite 10-yr yield level and direction in basis points with a specific driver.
  [4] Top commodity or currency move. If recent_headlines contains a specific commodity move with a named driver (oil on Iran/OPEC/supply, gold on rates/dollar), cite that headline's development as the pre-market story. Otherwise describe the largest mover from commodities_top6 as yesterday's closing change with its driver.

FLAT-DAY CALIBRATION: when |pct_change| < 0.10 for an index, write "essentially flat at [level]" instead of citing only a percent. Example:
  BAD: "S&P 500 unchanged% at 7,365.12"   (template substitution failure)
  BAD: "S&P 500 +0.04% — markets unchanged" (contradictory)
  GOOD: "S&P 500 closed essentially flat at 7,365.12 (+0.04%)"
  GOOD: "Markets closed mixed — S&P 500 essentially flat (+0.04%), Nasdaq 100 -0.12%; [catalyst]"

equities_commentary: 5-8 sentences — write all 8 if the data supports it; never truncate at 4. Lead with S&P 500 direction and level. SECTOR ROTATION (required): cite the top 2 sectors from sector_top3 and bottom 2 from sector_bottom3 by name and pct_change — e.g. "Technology led (+1.2%), followed by Financials (+0.8%), while Energy (-1.1%) and Real Estate (-0.9%) lagged." Use sector_top3 and sector_bottom3 from the payload. Include VIX level from technical_context and characterize it by BAND — below 15 = "subdued"/"calm"; 15-20 = "contained"/"below-average"; 20-30 = "elevated"; above 30 = "stressed". NEVER call a sub-20 VIX "elevated" or "high". State whether SPX is above or below its 200-day MA. If recent_earnings_actuals is non-empty, name 1-2 specific tickers from it with their EPS surprise % (e.g., "AMD's 12% EPS beat lifted semis") — use only eps_surprise_pct values from the payload. Do NOT cite a specific corporate action (dividend change %, buyback size, guidance figure) unless that exact number appears in the payload — never invent a figure like "raised its dividend 2,400%". Name at least one specific catalyst from recent_headlines. Global market context: cite one or two international index moves. Forward: what level or catalyst traders are watching next.

fixed_income_commentary: 5-6 sentences on TREASURY MARKET dynamics, the yield curve, and Fed policy implications. SCOPE: yield levels, curve shape, Fed rate-path expectations, and equity-multiple effects ONLY. Do NOT write about covered-call ETFs, JEPQ, equity-linked notes, CLOs, retail income strategies, or bond substitutes.
  Sentence 1 MUST begin: "The [10/30]-year Treasury yield [rose/fell/held] [N] bp[s] to [X.XX]% ..." — use bp_change from bonds["10-Year Yield"]["bp_change"] and level from market_levels["10-Yr Yield"]["level"]. If |bp_change| < 1, write "held near [level]%."
  Sentence 2: 30-yr yield level and any notable threshold; or 2-yr yield if 30-yr absent.
  Sentence 3: Yield curve shape — bonds["10s-2s Spread"]["change"] negative = NARROWED, positive = WIDENED; state magnitude in bps.
  Sentence 4: Fed policy — connect yield move to rate expectations or a named FOMC official/event from news_by_category["fixed_income"].
  Sentence 5: Equity multiple implication of the current 10-yr yield level.
  ANTI-COPY RULE (critical): The STYLE REFERENCE below shows SENTENCE SHAPE ONLY. Its specific facts are placeholders — do NOT reproduce any of them. Never output a named official or nomination (e.g. "Warsh nomination"), a specific forward P/E ("32x"), a probability ("80%"), or a "first time since [year]" claim unless that exact fact is present in the payload or news_by_category. Fill every bracket from the payload; if a fact isn't in the payload, omit the clause.
  STYLE REFERENCE (shape only — substitute payload values for ALL bracketed parts, drop any clause you lack data for): "The 10-year Treasury yield [rose/fell/held] [N] bps to [X.XX]%, [extending/reversing] a recent move driven by [a driver from news_by_category]. The 30-year yield [moved] to [X.XX]%, [a notable threshold if relevant]. The 2s10s spread [widened/narrowed] [N] bps to [Y] bps as [front/back]-end [buying/selling] led. [A Fed rate-path sentence ONLY if news_by_category names a specific FOMC official/event — otherwise omit]. At a 10-year yield near [X.XX]%, elevated yields imply [an equity-multiple effect] on growth names."

commodities_commentary: 5-6 sentences. WTI direction and level first, then gold. Specific fundamental driver for each. Key price level nearby. Connect to macro thesis.

currencies_commentary: 4-5 sentences. DXY direction and level. Rate differential or trade-flow driver. EUR/USD and JPY if notable. EM implication. SCOPE: name only currencies in the report's currency table — the US dollar (DXY), euro, sterling, yen, Canadian dollar, Australian dollar, Brazilian real, and Bitcoin. Do NOT introduce off-universe currencies (ringgit, peso, rupee, lira, won, rand, etc.) pulled from a headline; the EM implication should be expressed through the dollar or the in-table pairs.

economics_commentary: 4-5 sentences. RECAP LATEST READINGS FIRST: recent_macro_prints is a list of {indicator, actual, prior, as_of} carrying the ACTUAL figures — open by recapping the 1-2 most important entries (prioritise Core PCE, GDP, ISM Manufacturing/Services, jobless claims, CPI, payrolls), citing indicator + actual + prior and interpreting the beat/miss vs prior. PREVIEW→RECAP LINKAGE: if prior_scenario_event names the catalyst the prior session flagged (e.g. "CPI Inflation Report") and a matching entry now appears in recent_macro_prints, LEAD with that release — the reader was told to watch it, so do not skip it; cite its actual vs prior and the market's read. A fresh JOLTS Job Openings print (a labor-demand gauge) is market-relevant — feature it when present. PHRASING: weekly jobless claims may be called "the latest weekly jobless claims (215k vs 210k prior)"; monthly/quarterly series MUST be referred to as "the latest [indicator] reading" (e.g. "the latest Core PCE reading at 3.3% YoY vs 3.2% prior") — do NOT assert a specific release weekday for them, because the payload gives the observation period, not the publication date. NUMBER SOURCE (non-negotiable): cite macro figures ONLY from recent_macro_prints — NEVER invent or round a number outside that list (the prior report fabricated "211k in line with 211k prior"; the real value was 215k vs 210k). If recent_macro_prints is empty, cite no specific macro figure. Never frame a past reading as an upcoming release. After the recap, give macro-cycle context (soft landing, slowdown, re-acceleration) and the Fed rate-trajectory implication. Do NOT reproduce the example numbers above as literal output.
  DATE GUARD (critical): If todays_economic_events is EMPTY there is NO release scheduled today — do NOT write that any report is "scheduled today", "due this morning", or "at 8:30 AM ET today", and do NOT invent a release that is not in todays_economic_events or week_ahead_econ_events. Refer to any upcoming release by its WEEKDAY (e.g., "Thursday's GDP report"), and anchor the paragraph in the macro cycle rather than a fictitious same-day calendar.
  RELEVANCE GUARD (critical): The recap MUST center on the most market-relevant U.S. macro releases in recent_macro_prints. Do NOT lead with, or feature, a minor or foreign data point (e.g., a foreign government's quarterly spending, an overseas survey) — if it is not in recent_macro_prints it does not belong in the recap at all. Do NOT open economics_commentary with an event that is still UPCOMING today (e.g., a JOLTS or ADP print due later today) framed as if it already printed; upcoming releases belong in watch_today as forward catalysts, not in the recap.

ONE-SHOT EXAMPLE — bullet format reference ONLY. Use payload-specific numbers; do NOT copy these specifics:
{"pre_market_bullets":["Markets closed mixed — S&P 500 -0.12%, Nasdaq 100 +0.08%; megacap tech offset weakness in regional banks after Q1 deposit guidance.","Hang Seng rose 0.9% as PBoC drained liquidity at a slower pace, easing Q2 tightening fears.","Key data today: ISM Services PMI (high importance) at 10:00 AM ET — consensus 52.0 vs prior 51.4; a beat would reinforce the soft-landing thesis and add upward pressure to long-end yields.","10-yr yield fell 3 bps to 4.36%; breakevens widened on stronger jobless claims.","WTI rose 1.2% to $77.40 on OPEC+ extending production cuts through Q3."],"equities_commentary":"...","fixed_income_commentary":"...","commodities_commentary":"...","currencies_commentary":"...","economics_commentary":"..."}"""

# Call 1r: Refinement/generation pass — deepens existing sections AND generates any missing ones.
# Input shape: {"draft": {...}, "source_data": {...}, "missing_keys": [...]}
# "missing_keys" is populated when Call 1 returned an incomplete draft — the model must
# GENERATE those sections from scratch using source_data rather than leaving them absent.
SYSTEM_PROMPT_REFINE = WRITING_RULES + """
You are a financial editor reviewing a draft market commentary. You will receive a JSON object with these keys:
- "draft": the commentary to review (partial or complete 6-key schema)
- "source_data": the market data payload used to generate the draft
- "missing_keys": list of keys that are ABSENT from the draft and MUST be written from scratch

Your job:

1. GENERATE MISSING — For every key in missing_keys, write the section from scratch using source_data. Follow the same length and specificity rules as the primary call. This takes priority over everything else.
2. LENGTH — For sections already in the draft: if equities_commentary, fixed_income_commentary, commodities_commentary, currencies_commentary, or economics_commentary has fewer than 6 sentences, add sentences grounded in specific facts from source_data (named tickers, price levels, pct changes, economic releases). Do NOT add vague filler.
3. SPECIFICITY — If any sentence makes a directional claim without a supporting data point (no ticker, no price, no pct, no named event), replace it with one that cites the relevant number from source_data.
4. SIGN ACCURACY — Verify every direction word (rose/fell/gained/slid) matches the sign of pct_change in source_data. Correct any mismatches silently.
5. PRESERVE GOOD SECTIONS — If a section already meets the length and specificity standard, return it verbatim. Do not rewrite for its own sake.
6. FIXED INCOME SCOPE CHECK — If the draft's fixed_income_commentary discusses covered-call ETFs, yield-alternative products (JEPQ, ELNs, CLOs), retail income strategies, or bond substitutes, it is off-scope and MUST be rewritten entirely from the bonds data in source_data. A valid fixed_income_commentary MUST begin with the 10-year Treasury yield level and daily bp move, then cover 30-yr yield context, yield curve shape (2s10s spread), Fed rate-path expectations, and equity multiple implications. Nothing else.
7. pre_market_bullets — only change a bullet if it is factually wrong per source_data or cites sponsored/promotional content. Otherwise return unchanged.

Return JSON with ALL 6 keys — generate any that are absent from the draft:
{"pre_market_bullets":["...","...","...","...","..."],"equities_commentary":"...","fixed_income_commentary":"...","commodities_commentary":"...","currencies_commentary":"...","economics_commentary":"..."}"""

# Call 2: Outlook, allocation, portfolio spotlight
SYSTEM_PROMPT_OUTLOOK = WRITING_RULES + """

Return JSON with EXACTLY these 7 keys:

market_outlook_label: Exactly one of: "Bullish", "Cautious", "Neutral", "Bearish"  near-term 4-6 week equity view.

market_outlook_rationale: Exactly 2 sentences. If prior_day_label is provided and market_outlook_label differs from it, Sentence 1 MUST explain what changed and why the view shifted since the prior session — and if the label reverses prior_day_label by two or more notches (ordering: Bearish < Cautious < Neutral < Bullish), Sentence 1 must explicitly justify the SHARP reversal, not merely restate the new view. If mag7_consensus_forecasts carries a net signal that conflicts with market_outlook_label (e.g., a net-negative/defensive MAG7 consensus under a Bullish label), name and reconcile that tension in one clause rather than ignoring it. Otherwise Sentence 1 is the primary supporting factor. Sentence 2: key risk that could change the label.

tactical_outperforming: Short phrase (3-5 words) — sectors/themes outperforming. Ground in sector_top3 from the payload (e.g., "Technology, Financials, semis").

tactical_underperforming: Short phrase (3-5 words) — sectors/themes lagging. Ground in sector_bottom3 from the payload (e.g., "Energy, Real Estate, utilities").

asset_class_outlooks: Object with keys "Equities", "Fixed Income", "Commodities", "US Dollar". Each: {"label": one of Bullish/Cautious/Neutral/Bearish, "rationale": "1-2 sentences"}.
CRITICAL: asset_class_outlooks rationales are LONG-TERM FUNDAMENTAL views (3-6 month horizon) — they MUST be substantively different from market_outlook_rationale (which is the 4-6 week tactical view). The Equities rationale specifically MUST focus on FUNDAMENTAL drivers (earnings trajectory, multiple expansion/compression, capex cycle, structural themes like AI infrastructure) — NOT on today's index move, today's sector tilt, or today's specific news. Do not echo market_outlook_rationale; if the Equities rationale begins with "The S&P 500's [pct]% advance" or mentions today's price move, you have failed this rule. Start the Equities rationale with the fundamental driver (e.g., "Forward earnings growth of...", "AI capex commitments of...", "Multiple expansion supported by...").
STANCE COHERENCE (critical): the rationale's leading driver MUST point the same direction as the label. A Bearish or Cautious Equities label must OPEN with a bearish fundamental driver (decelerating earnings, multiple compression, capex retrenchment, concentration risk) — it must NOT open "Forward earnings growth remains robust/strong" or any bullish premise under a bearish label. A Bullish label must open with a bullish driver. The same rule applies to Fixed Income, Commodities, and US Dollar: never lead with a driver whose polarity contradicts the label you assigned.

portfolio_spotlight_winners: Array of up to 3 objects for tickers with positive return_1m: {"ticker":"...","metric_label":"...","commentary":"2 sentences on what drives outperformance and whether it persists."}. IMPORTANT: each entry in portfolio_top_performers includes a "description" field — use it to understand what the fund actually is. Write commentary grounded in that actual strategy. Do NOT invent sector attributions.
ONE-SHOT EXAMPLE for portfolio_spotlight_winners:
  Input: {"ticker":"JAAA","description":"Janus Henderson AAA CLO ETF — AAA-rated CLOs, short-duration investment-grade fixed income","return_1m":0.4,"metric_label":"+0.4% (1M)"}
  BAD commentary: "JAAA benefited from the technology rally and strong consumer spending data."
  GOOD commentary: "JAAA's AAA-rated CLO exposure insulates the fund from credit spread widening, making it a relative shelter as equity volatility rises. The short duration profile limits rate sensitivity, so outperformance should persist as long as credit markets remain orderly."

portfolio_spotlight_watch: MUST contain exactly one entry for EACH ticker listed in portfolio_names_to_watch — use the exact ticker symbol and metric_label from that input, do not substitute other tickers. {"ticker":"...","metric_label":"...","commentary":"2 sentences on what to monitor for this fund given current market conditions."}. IMPORTANT: use the "description" field to write accurate, strategy-specific commentary. Do NOT describe a bond or income fund as an equity fund.

JSON template:
{"market_outlook_label":"...","market_outlook_rationale":"...","tactical_outperforming":"...","tactical_underperforming":"...","asset_class_outlooks":{"Equities":{"label":"...","rationale":"..."},"Fixed Income":{"label":"...","rationale":"..."},"Commodities":{"label":"...","rationale":"..."},"US Dollar":{"label":"...","rationale":"..."}},"portfolio_spotlight_winners":[{"ticker":"...","metric_label":"...","commentary":"..."}],"portfolio_spotlight_watch":[{"ticker":"...","metric_label":"...","commentary":"..."}]}"""

# --- stance-stability guard (spec #2): a sharp near-term reversal must be explained ---
# 2026-06-15 weekly frame: the near-term stance ran BEARISH (6/8, at the low) -> BULLISH
# (6/15, at the high) — a full reversal that chased the tape. The prompt asks the model to
# explain a changed label; this ENFORCES it for sharp (>=2-notch) reversals by forcing a
# retry when the rationale never acknowledges the shift.
_STANCE_ORDER = {"bearish": 0, "cautious": 1, "neutral": 2, "bullish": 3}
# Tokens that count as acknowledging a shift in the rationale prose.
_STANCE_SHIFT_RE = re.compile(
    r"\b(shift\w*|revers\w*|chang\w*|flip\w*|pivot\w*|turn\w*|swung|swing|"
    r"previously|prior|from\s+(?:bearish|cautious|neutral|bullish)|"
    r"upgrad\w*|downgrad\w*|no\s+longer)\b",
    re.IGNORECASE)


def _stance_notch_distance(prev_label, cur_label) -> int:
    """Absolute notch distance between two near-term stance labels (0 if either is unknown)."""
    p = _STANCE_ORDER.get(str(prev_label or "").strip().lower())
    c = _STANCE_ORDER.get(str(cur_label or "").strip().lower())
    if p is None or c is None:
        return 0
    return abs(c - p)


def _check_stance_reversal_unexplained(data: dict, prior_label) -> str:
    """Return a violation string if the stance reverses prior_label by >=2 notches and the
    rationale never acknowledges the shift; '' otherwise. Drives a Call-2 retry."""
    cur = data.get("market_outlook_label")
    if _stance_notch_distance(prior_label, cur) < 2:
        return ""
    rationale = str(data.get("market_outlook_rationale") or "")
    if _STANCE_SHIFT_RE.search(rationale):
        return ""
    return f"{prior_label}->{cur} reversal unexplained in rationale"


# Call 3: Session recap, watch-today, international section
SYSTEM_PROMPT_RECAP = WRITING_RULES + """

Return JSON with EXACTLY these 3 keys:

session_recap: Array of exactly 3 strings summarising the PREVIOUS trading session:
  [0] "S&P 500 [closed higher/lower] at {level}, [pct]%; [single specific catalyst from news]."
  [1] Fixed income/rates recap: 10-yr yield level and direction with one specific driver.
  [2] Top non-equity mover: the most notable commodity OR currency with exact level and driver.

watch_today: Array of exactly 3 strings — actionable items for TODAY's session:
  [0] Economic data: cite the most important event from todays_economic_events ONLY. If todays_economic_events is empty, output exactly "No major data today." NEVER promote an event from week_ahead_econ_events into this slot — those belong to future days.
  [1] Earnings/corporate: cite from todays_earnings ONLY (entries whose date == today). If todays_earnings is empty, output exactly "No major earnings today." NEVER assign a future-day entry from this_week_earnings to today.
  [2] Technical level or market structure: one specific price level or spread to monitor.

international_section: 3-4 sentences covering non-US market impact on US outlook. Use global_markets and international_macro data. Include at least one of: EU/ECB, Japan/BOJ, China/Asia. Connect explicitly to how it affects US equities, rates, or commodities.
  CENTRAL-BANK PRIORITY: if international_macro.global_central_bank_events is non-empty, you MUST lead this section with the most material action listed there — name the institution, state the action exactly as the headline reports it (e.g. "the BOJ raised its policy rate 25 bp to a 31-year high"), and give the read-through to US Treasury yields, the dollar, or equities. Do NOT invent or assume any central-bank action that is not in that list, and do NOT overstate one that is.

Tickers in recent_earnings_actuals have ALREADY released earnings this week — never write "later this week" or "upcoming earnings" for them in watch_today or session_recap.

JSON template:
{"session_recap":["...","...","..."],"watch_today":["...","...","..."],"international_section":"..."}"""

# Call 4: Cross-asset synthesis — runs AFTER parts 1-3, reads their output
SYSTEM_PROMPT_SYNTHESIS = WRITING_RULES + """

Return JSON with EXACTLY one key:

cross_asset_synthesis: Exactly 3-4 sentences. This is the "Market Take" wrap-up that ties together equities, rates, commodities, and the forward catalyst into a single coherent thesis.

Rules:
- Commit to a directional view — do NOT hedge with "risk remains elevated", "uncertainty persists", or "the outlook is mixed".
- Name the dominant cross-asset linkage (e.g., "oil is driving yields which is compressing tech multiples" — pick the actual theme from the payload).
- Name the single most important upcoming catalyst: use todays_economic_events if non-empty (call it "today"), otherwise use the first entry of week_ahead_econ_events (name it by weekday, e.g., "Thursday's Initial Jobless Claims") or this_week_earnings. State exactly what outcome you are watching for (beat vs miss, hawkish vs dovish).
- The tone MUST be consistent with market_outlook_label: if Cautious, explain the specific mechanism of risk without adding false balance; if Bullish, name the specific driver without inventing caveats.
- 3-4 sentences total. No preamble. No conclusion phrase. Start directly with the cross-asset theme.
- DATE CONSISTENCY: If todays_economic_events is EMPTY, there are NO economic releases today — do NOT call any event "today" or "this morning". Events in week_ahead_econ_events are FUTURE; always name them by their weekday (e.g., "Wednesday's Fed minutes", "Thursday's Flash PMI"). NEVER assign a week_ahead event to "today".

ONE-SHOT EXAMPLE:
  market_outlook_label: "Cautious"
  BAD: "Markets face multiple headwinds but show resilience; the outlook remains mixed as investors weigh risks against opportunities."
  GOOD: "WTI's 6% surge above $105 is feeding directly into 10-yr yield pressure at 4.36%, which in turn is compressing Nasdaq multiples — the oil-rates-tech linkage is the dominant driver today. The dollar's modest strengthening (+0.2%) confirms the market is pricing a sticky-inflation regime rather than a growth shock. Friday's Core PCE print is the key release: an above-consensus read would validate the hawkish rate path and add another leg down in tech; a miss would relieve duration pressure and let the MAG7 stabilize."

JSON template:
{"cross_asset_synthesis":"..."}"""

ETF_WHITELIST: frozenset = frozenset({
    "XLF","XLE","XLY","XLI","XLP","XLU","XLB","XLK","XLC","XLV","XLRE",
    "IWM","IJH","FLOT","BIL","SHY","IEF","TLT","GLD","GDX","SLV",
    "USO","BNO","UUP","UDN","FXI","EEM","EFA","SPY","QQQ","DIA",
    "SQQQ","SDS","SH","PSQ","UVXY","VIXY",
})

# Call 5: Scenario framework — "Too Hot / In Line / Too Cold" for today's key event
SYSTEM_PROMPT_SCENARIOS = WRITING_RULES + """

You are building a Sevens-Report-style scenario framework for today's most important economic release.

Return JSON with EXACTLY these 2 keys:

scenarios: Array of EXACTLY 3 scenario objects in this order:
  1. "Hot" — the hawkish surprise (stronger data / higher inflation / tighter labor). Yields rise, dollar up, equities under pressure, gold falls.
  2. "In Line" — outcome roughly matches consensus. Limited cross-asset reaction.
  3. "Cold" — the dovish surprise (weaker data / lower inflation / softer labor). Yields fall, dollar down, equities rally, gold rises.

Each scenario object has EXACTLY these 6 keys:
  label:      Short label with outcome range, e.g. "Hot (<195K)" or "Cold (>215K)"
              POLARITY — derive the inequality direction FROM THE INDICATOR; do NOT assume "Hot = lower number":
                • Activity / inflation / sentiment indicators where a HIGHER print is hawkish
                  (ISM, PMI, CPI, PCE, GDP, retail sales, consumer confidence, nonfarm payrolls):
                  Hot is the HIGH side  → "Hot (>X)";  Cold is the LOW side → "Cold (<Y)";  with X >= Y.
                • Labor-slack indicators where a HIGHER print is dovish
                  (initial/continuing jobless claims, unemployment rate):
                  Hot is the LOW side   → "Hot (<X)";  Cold is the HIGH side → "Cold (>Y)";  with X <= Y.
              The Hot and Cold ranges MUST NOT overlap — the In Line band sits strictly between them.
              Example (ISM Non-Manufacturing, consensus 50.0): "Hot (>52.0)", "In Line (48.0-52.0)", "Cold (<48.0)".
              Example (Jobless Claims, consensus 205K):        "Hot (<195K)", "In Line (195K-215K)", "Cold (>215K)".
  thesis:     1 sentence. The macro narrative if this scenario plays out.
  rates:      Expected 10-yr yield move with direction and approximate bp range.
  equities:   Expected S&P 500 move with approximate % range and one sector note.
  commodities: Gold and/or oil reaction in 1 short sentence.
  tickers:    Array of 3-5 ETF tickers from ONLY this list (choose the best fit for this scenario):
              XLF XLE XLY XLI XLP XLU XLB XLK XLC XLV XLRE IWM IJH FLOT BIL SHY IEF TLT GLD GDX SLV USO UUP UDN SPY QQQ

levels_to_watch: Array of EXACTLY 3 level objects. Pick the 3 most relevant assets given today's primary event.
  asset:        Asset name — one of: S&P 500, 10-Yr Yield, Gold, WTI Crude, VIX, U.S. Dollar (DXY)
  level:        Specific numeric price/rate level as a float (e.g. 4.5 for yield, 5500 for S&P)
  significance: 1 sentence explaining why this level matters right now.

Hot scenario tickers should favor defensives/cash/short-duration: XLP, XLU, FLOT, BIL, SHY, UUP, SH.
Cold scenario tickers should favor risk-on/duration: TLT, GLD, QQQ, XLK, IWM, XLY, UDN.
In-Line scenario tickers should be balanced: mix of cyclicals and core benchmarks (SPY, XLF, XLI, XLE).

JSON template:
{"scenarios":[{"label":"Hot (...)","thesis":"...","rates":"...","equities":"...","commodities":"...","tickers":["...","...","..."]},{"label":"In Line (...)","thesis":"...","rates":"...","equities":"...","commodities":"...","tickers":["...","...","..."]},{"label":"Cold (...)","thesis":"...","rates":"...","equities":"...","commodities":"...","tickers":["...","...","..."]}],"levels_to_watch":[{"asset":"...","level":0.0,"significance":"..."},{"asset":"...","level":0.0,"significance":"..."},{"asset":"...","level":0.0,"significance":"..."}]}"""


# Call 6: Trending-topic spotlight — optional, fires only when one topic dominates the day's news
SYSTEM_PROMPT_TOPIC_SCAN = """
You are a financial news editor. Scan today's headlines and decide whether ONE financial topic dominates with unusual market significance.

Return JSON with EXACTLY these 6 keys (no others):
{"has_spotlight":false,"topic":"","topic_keywords":[],"category":"","why_now":"","candidate_funds":[]}

has_spotlight: true ONLY when a single topic appears in 4 or more headlines from multiple outlets.
topic: concise name, e.g. "SpaceX IPO Filing", "U.S.-Iran Ceasefire", "NVIDIA Earnings Beat".
topic_keywords: 2-4 lowercase keywords that uniquely identify this topic, e.g. ["spacex","ipo","spcx"].
category: exactly one of: ipo, geopolitical, sector_catalyst, macro, earnings.
why_now: one sentence — what happened today that made this topic financially significant.
candidate_funds: 2-5 REAL fund or ETF tickers with meaningful exposure to this topic. Only use tickers you are confident exist. Common examples: ARKVX, DXYZ, XOVR for private-company exposure; XLE, USO for oil/energy; SHLD, ITA for defense.

Rules:
- has_spotlight=false for generic broad-market moves (routine S&P daily move, standard Fed statement, typical earnings).
- Topics must have direct investment implications: an IPO filing, geopolitical event affecting energy/trade/rates, sector breakthrough, macro regime shift.
- If no single dominant topic, set has_spotlight=false and all other fields to empty strings or empty arrays.
- PREFER THE MARKET DRIVER: sector_leaders shows what actually moved the tape. If a sector posted a clear move (>=1.5%) AND headlines corroborate a theme behind it (e.g., Technology leading with AI/chip/Computex headlines), choose THAT theme over a geopolitical storyline that did not drive prices. A geopolitical topic should win only when it BOTH dominates the headlines AND is consistent with the day's sector/price action — do not default to the loudest geopolitical headline when the data points to a different driver.

ONE-SHOT EXAMPLE:
Input headlines include 6 articles about SpaceX filing an IPO prospectus.
{"has_spotlight":true,"topic":"SpaceX IPO Filing","topic_keywords":["spacex","ipo","spcx"],"category":"ipo","why_now":"SpaceX formally filed its prospectus targeting NASDAQ at a $1.75T valuation, triggering broad financial media coverage.","candidate_funds":["ARKVX","DXYZ","XOVR","BPTRX"]}
"""

SYSTEM_PROMPT_MOVER_SCAN = (
    "You identify the single biggest SINGLE-STOCK premarket move in today's financial headlines. "
    "Return STRICT JSON: {\"ticker\": str, \"company\": str, \"pct\": float (signed FRACTION, e.g. "
    "-0.13 for -13%), \"catalyst\": short phrase, \"sector\": str} for the one company whose shares "
    "are moving the most premarket on a clear catalyst (earnings, guidance, M&A, capital raise). "
    "If no single stock clearly dominates, return {\"ticker\": \"\"}. Never invent a ticker; use the "
    "real US-listed symbol (Broadcom -> AVGO). pct is your best estimate; it will be price-verified."
)

SYSTEM_PROMPT_TOPIC_SPOTLIGHT = """
You are a senior markets analyst writing the FLAGSHIP deep-dive for an institutional daily report — the kind of piece that explains a theme so well a portfolio manager forwards it. The topic is today's confirmed dominant financial theme. Write with the depth and authority of a top sell-side strategist note: explain the MECHANISM, judge whether it is SUSTAINABLE, and lay out how the view could be expressed — as OPTIONS, not advice.

Ground EVERY factual claim in the provided source_excerpts, supporting_headlines, and market_context (sector tilt + tactical positioning the report's data tables already publish). Do NOT invent figures, company actions, valuations, or timelines that are not in those inputs. When market_context.is_data_driven_theme is true, the theme itself was selected from the day's market data — write a sector/macro deep-dive grounded in that data and the verified_funds; the mechanism paragraph should explain WHY this sector or theme moved (cite the sector pct_change from market_context, factor read, and any corroborating headlines).

Return JSON with EXACTLY these 4 keys (no others):
{"title":"","body":"","funds":[],"category":""}

title: Punchy, specific headline, max 12 words. Headline the THEME and its stakes (e.g. "The Memory Shortage Powering the Next Leg of the AI Trade"). Do NOT assert a daily index move/level ("Dow Surges 250 Points", "Oil Crashes") unless that exact move appears in the inputs — the report's data tables already report the close.

body: A genuine analytical deep-dive of 4-6 paragraphs as a SINGLE string, with paragraphs separated by a DOUBLE NEWLINE (\\n\\n). Each paragraph 3-5 sentences. Follow this arc:
  Paragraph 1 — WHAT & WHY IT MATTERS: the development and the specific numbers behind it (from source_excerpts). Establish the stakes.
  Paragraph 2 — THE MECHANISM: explain WHY this is happening — the underlying driver, the chain of cause and effect. Teach the reader the thing they did not already know. This is the paragraph that separates a deep-dive from a blurb.
  Paragraph 3 — IS IT SUSTAINABLE / VALUATION & DATA CONTEXT: the analytical judgment. Supply/demand, earnings, valuation, positioning, the bear case vs the bull case — grounded in the excerpts. Take a side.
  Paragraph 4 — HOW TO EXPRESS IT (options, not advice): which exposures benefit or face headwinds, and how the view COULD be expressed using the verified_funds — framed as options, never as instructions. Name at LEAST TWO verified_funds (when two are available) as alternative ways to gain or reduce exposure, include the bear-case/counter consideration, and close with the SPECIFIC near-term catalyst or price level that confirms or breaks the thesis. Use "one way to express this is…", "X offers exposure to…", "for those reducing exposure, Y…" — NOT "investors should buy", "lean into", or "trim".
funds: Array of fund objects using ONLY tickers from the verified_funds input. If verified_funds is empty, set funds=[].
  Each object has exactly: ticker, name, type, exposure_note (one sentence on how it relates to the theme; no fabricated %/AUM).
category: carry through the category from the input.

Rules:
- GROUNDED: cite specifics only from source_excerpts/supporting_headlines. No invented numbers. Cite ONLY verified_funds tickers — never invent a ticker.
- TEACH, then CONCLUDE: the mechanism paragraph must explain a cause-and-effect a smart non-expert would not already know. Commit to a view — forbidden hedges: "investors should watch", "uncertainty remains", "markets face headwinds", "time will tell", "remains to be seen".
- Active voice, present tense. No preamble, no summary sentence, no "in conclusion". Start the body with the development itself.
- NON-ADVICE FRAMING: never instruct the reader to buy/sell/"lean into"/"trim"/"should express this view by leaning into". Present vehicles as OPTIONS with a counter/caveat. Cite at least two verified_funds when two or more are available; a single sole "buy this" recommendation is forbidden.
- Geopolitical themes: market-impact framing only (energy, currencies, supply chains, rate path).
- SESSION-SPECIFIC, NOT EVERGREEN: every paragraph must be about TODAY's theme and the current session. Do NOT pad with timeless personal-finance rules (e.g. the "4% retirement rule"), long-horizon household wealth-distribution statistics ("the top 20% account for X% of spending"), or other generic tangents that are not specific to today's move — they read as stale filler scraped from unrelated articles.
- LONG ETFs ARE NOT HEDGES: a long sector/index ETF (XLK, QQQ, SPY, SMH, a sector SPDR, etc.) falls WITH its sector — it does NOT offer "inverse beta", "inverse exposure", or a hedge to its own decline. To REDUCE exposure to a selloff, one underweights/avoids the long ETF or rotates to defensives; only an explicitly inverse/short product (e.g. an "-inverse"/"short" ETF) provides inverse beta. Never describe a long ETF as inverse to the move it participates in.
- EARNINGS-DRIVEN MOVES: if `earnings_grounding` is present in the input, the spotlight subject moved on its OWN earnings/guidance release. Attribute the move to the company-specific results (revenue, guidance/outlook, bookings, margins, segment weakness) named in earnings_grounding — NOT to the day's macro or geopolitical theme. A single company's earnings-day move is NOT caused by a war, ceasefire, deal, or rate decision; do not write that it was, even if those themes dominate the wire. Lead Paragraph 1 with the earnings/guidance fact.

ONE-SHOT EXAMPLE (abbreviated — yours must be 4-6 full paragraphs):
{"title":"The Memory Shortage Powering the Next Leg of the AI Trade","body":"Large-cap memory makers have become the market's best performers, with Micron, SanDisk and Western Digital up roughly 115%, 145% and 87% over two months as the entire tech sector re-rates higher on their backs.\\n\\nThe driver is physical, not sentiment: AI processors can execute trillions of operations per second, but performance was capped by how fast memory could feed them data — the 'memory wall.' Stacking high-bandwidth memory directly atop the processor shattered that ceiling, and in doing so multiplied the number of memory chips a single AI server needs from eight to roughly ninety-six.\\n\\nThat demand shock is durable on a multi-year horizon. Micron's 2026 capacity is already sold out, new clean-room supply is years away, and trailing free cash flow is inflecting from under $2B to an expected $10B — which is why valuations have stayed near 10x forward earnings despite triple-digit rallies; earnings are outrunning the share price.\\n\\nThe cleanest expression is direct memory exposure, which most tech ETFs are structurally underweight. The thesis breaks only if hyperscalers cut data-center capex — the order book to watch into next quarter.","funds":[{"ticker":"SMH","name":"VanEck Semiconductor ETF","type":"ETF","exposure_note":"Holds the large-cap memory names driving the move, though weighted toward logic chipmakers."}],"category":"sector_catalyst"}
"""

# Sensational escalation phrases that are stripped from spotlight text.
# Much narrower than BANNED_PHRASES — factual geopolitical nouns (war, conflict, ceasefire) are allowed.
SPOTLIGHT_ESCALATION_PHRASES: list[str] = [
    "all-out war", "world war", "nuclear strike", "nuclear attack", "nuclear war",
    "apocalyptic", "catastrophic conflict", "total collapse", "economic collapse",
    "financial armageddon", "global meltdown",
]

BANNED_PHRASES = [
    "geopolitical tensions", "geopolitical risks", "global uncertainties",
    "global instability", "amid uncertainty", "amid concerns", "amid heightened",
    "uncertain environment", "uncertain outlook", "it is worth noting",
    "it should be noted", "importantly,", "in conclusion", "overall,",
    "needless to say", "at the end of the day", "moving forward",
    # Pillar 4: hedges that dilute a committed analytical voice. The report's job is to
    # take a side based on the data, not survey possibilities. These all force retries.
    "investors should watch", "investors will watch", "remains to be seen",
    "time will tell", "wait-and-see", "wait and see", "could go either way",
    "markets face headwinds", "cautious optimism", "exercise caution",
    "the outlook is mixed", "outlook remains mixed", "uncertainty persists",
    "uncertainty remains", "risk remains elevated", "risk remains skewed",
    "remain on the sidelines", "stay on the sidelines",
]

# Alias map at module level so retry loops can remap keys before scrubbing.
# Scrub only operates on canonical NARRATIVE_KEYS — remapping must happen first.
LLM_KEY_ALIASES: dict[str, str] = {
    "currencies":        "currencies_commentary",
    "macro":             "economics_commentary",
    "economics":         "economics_commentary",
    "commodities":       "commodities_commentary",
    "fixed_income":      "fixed_income_commentary",
    "equities":          "equities_commentary",
    "pre_market":        "pre_market_bullets",
    # Common key drift patterns from qwen2.5:14b
    "pre_market_summary":   "pre_market_bullets",
    "market_performance":   "equities_commentary",
    "economic_news":        "economics_commentary",
    "company_news":         "equities_commentary",
    "sector_news":          "equities_commentary",
    "global_events":        "economics_commentary",
    "market_summary":       "equities_commentary",
    "market_overview":      "equities_commentary",
    "equity_commentary":    "equities_commentary",
    "bond_commentary":      "fixed_income_commentary",
    "rate_commentary":      "fixed_income_commentary",
    "commodity_commentary": "commodities_commentary",
    "currency_commentary":  "currencies_commentary",
    # Fallback: model occasionally returns last narrative section as 'other'
    "other":             "economics_commentary",
    # Consistent qwen2.5:14b typo: "outlight" instead of "outlook"
    "market_outlight_rationale": "market_outlook_rationale",
}

# Financially accurate replacements applied after generation.
# Filler phrases map to "" (removed). Substantive phrases map to precise alternatives.
PHRASE_REPLACEMENTS = {
    "geopolitical tensions":  "cross-border conflict risk",
    "geopolitical risks":     "political risk",
    "global uncertainties":   "macro cross-currents",
    "global instability":     "broad market stress",
    "amid uncertainty":       "against a mixed macro backdrop",
    "amid concerns":          "on rising risk premium",
    "amid heightened":        "against elevated",
    "uncertain environment":  "uneven macro backdrop",
    "uncertain outlook":      "mixed near-term visibility",
    "it is worth noting":     "",
    "it should be noted":     "",
    "importantly,":           "",
    "in conclusion":          "",
    "overall,":               "on balance,",
    "needless to say":        "",
    "at the end of the day":  "",
    "moving forward":         "looking ahead",
}


def _scrub_text(text: str) -> str:
    """Apply PHRASE_REPLACEMENTS to a single string, preserving sentence-start capitalisation."""
    import re
    for phrase, replacement in PHRASE_REPLACEMENTS.items():
        def _replace(m: re.Match) -> str:
            original = m.group(0)
            result = replacement
            if not result:
                return result
            # If the matched phrase started a sentence (first char uppercase), capitalise replacement
            if original[0].isupper():
                result = result[0].upper() + result[1:]
            return result
        text = re.sub(re.escape(phrase), _replace, text, flags=re.IGNORECASE)
    # Clean up double spaces and leading/trailing whitespace from removed phrases
    text = re.sub(r"  +", " ", text).strip()
    # Fix sentence-start punctuation artefacts like ". ," or " ,"
    text = re.sub(r"\.\s+,", ".", text)
    text = re.sub(r"\s+,", ",", text)
    # Strip redundant +/- after directional verbs ("fell -5.55%" → "fell 5.55%")
    text = _strip_double_signs(text)
    return text


def _scrub_nested(val):
    """Recursively scrub banned phrases from strings inside any nested structure."""
    if isinstance(val, str):
        return _scrub_text(val)
    if isinstance(val, list):
        return [_scrub_nested(item) for item in val]
    if isinstance(val, dict):
        return {k: _scrub_nested(v) for k, v in val.items()}
    return val


def scrub_banned_phrases(data: dict) -> dict:
    """Post-process commentary dict: replace banned phrases with accurate alternatives."""
    for key in NARRATIVE_KEYS:
        if key in data:
            data[key] = _scrub_nested(data[key])
    return data

NARRATIVE_KEYS = [
    "pre_market_bullets", "equities_commentary", "fixed_income_commentary",
    "commodities_commentary", "currencies_commentary", "economics_commentary",
    "market_outlook_rationale",
    "session_recap", "watch_today", "international_section",
    "cross_asset_synthesis",
]


def _warmup_ollama_async() -> threading.Thread:
    """Fire-and-forget pre-warm of the commentary model.

    On a freshly-restarted or idle Ollama the first real LLM call (the narrative
    call, which cold-loads at num_ctx=16384) pays a from-scratch model load. On this
    server qwen3.5:9b (6.6GB) doesn't fully fit the A2000's ~5.75GB VRAM, so the cold
    load + first inference is slow enough to drop the connection (WinError 10054/10065)
    and force the deterministic fallback that fails the email gate.

    This loads the model NOW, in a daemon thread, so it warms concurrently with the
    several-minute market-data gathering in main() and is resident before call_ollama
    runs. num_ctx MUST match the narrative call (16384) or Ollama reloads the model on
    the first real call (cold again). keep_alive holds it resident until then. Strictly
    best-effort: any failure is swallowed — call_ollama's normal retry logic still applies.
    """
    def _warm() -> None:
        try:
            requests.post(
                f"{OLLAMA_HOST}/api/chat",
                json={
                    "model":    OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": "ok"}],
                    "stream":   False,
                    "think":    False,
                    "keep_alive": "20m",
                    "options":  {"num_predict": 1, "num_ctx": 16384},
                },
                timeout=OLLAMA_TIMEOUT,
            )
            print("  [WARMUP] Ollama commentary model pre-warmed (resident for this run).")
        except Exception as exc:
            print(f"  [WARMUP] Pre-warm skipped ({exc}); first LLM call will cold-load.")

    t = threading.Thread(target=_warm, name="ollama-warmup", daemon=True)
    t.start()
    return t


def _preflight_gpu_check(warmup: "threading.Thread | None" = None) -> "str | None":
    """Verify Ollama is serving the commentary model on the GPU. Returns an error
    string if not (caller blocks the run), else None.

    When the server's GPU driver is down (e.g. an unattended kernel upgrade leaves
    nvidia.ko unloaded — the 2026-06-03 incident), Ollama silently falls back to
    100% CPU, where qwen3.5:9b runs ~10x slower. The narrative step then grinds for
    over an hour and the run looks hung. This probes /api/ps and fails in seconds
    with an actionable message instead.

    Healthy = size_vram > 0. ANY GPU offload counts: on the 6GB A2000 the 9.5GB
    model is only partially resident (~5GB VRAM, rest CPU) — that is the NORMAL
    state, so the bar is >0, not full residency. The async warmup loads the model
    concurrently with market-data gathering; we join it first so /api/ps reflects a
    loaded model. Set EPM_SKIP_GPU_PREFLIGHT=1 to bypass (intentional CPU-only host).
    """
    if os.getenv("EPM_SKIP_GPU_PREFLIGHT") == "1":
        print("  [PREFLIGHT] GPU check skipped (EPM_SKIP_GPU_PREFLIGHT=1).")
        return None

    if warmup is not None and warmup.is_alive():
        warmup.join(timeout=OLLAMA_TIMEOUT)

    def _resident() -> "dict | None":
        r = requests.get(f"{OLLAMA_HOST}/api/ps", timeout=30)
        r.raise_for_status()
        return next((m for m in r.json().get("models", []) if m.get("name") == OLLAMA_MODEL), None)

    try:
        entry = _resident()
        if entry is None:
            # Warmup didn't leave it resident — do one blocking minimal load, then re-check.
            requests.post(
                f"{OLLAMA_HOST}/api/chat",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": "ok"}],
                    "stream": False, "think": False, "keep_alive": "20m",
                    "options": {"num_predict": 1, "num_ctx": 16384},
                },
                timeout=OLLAMA_TIMEOUT,
            )
            entry = _resident()
    except Exception as exc:
        return (
            f"[FATAL] GPU preflight: Ollama unreachable at {OLLAMA_HOST} ({exc}). "
            f"Cannot generate narrative — aborting before any CPU-fallback grind. "
            f"Check the ollama service and the GPU (nvidia-smi)."
        )

    if entry is None:
        return (
            f"[FATAL] GPU preflight: {OLLAMA_MODEL} could not be loaded on {OLLAMA_HOST}. Aborting."
        )

    vram = entry.get("size_vram", 0) or 0
    total = entry.get("size", 0) or 0
    if vram <= 0:
        return (
            f"[FATAL] GPU preflight: {OLLAMA_MODEL} is running 100% on CPU "
            f"(size_vram=0, size={total / 1e9:.1f}GB) on {OLLAMA_HOST}. The GPU driver is "
            f"likely down — narrative generation would grind for ~1h on CPU, so aborting now. "
            f"Fix on the server: `nvidia-smi` (should list the GPU); if it errors, "
            f"`sudo modprobe nvidia` (ensure linux-modules-nvidia matches `uname -r`), then "
            f"`sudo systemctl restart ollama`. See memory incident_gpu_driver_kernel_mismatch."
        )

    pct = (vram / total * 100) if total else 100
    print(f"  [PREFLIGHT] GPU OK — {OLLAMA_MODEL} resident, {vram / 1e9:.1f}GB in VRAM ({pct:.0f}% offloaded).")
    return None


def _call_ollama_raw(system: str, user_payload: dict, num_ctx: int = 8192) -> dict:
    body = {
        "model":   OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": json.dumps(user_payload, default=str)},
        ],
        "stream": False,
        "format": "json",
        "think":  False,
        "options": {
            "temperature": 0,
            "num_predict": 4096,
            "num_ctx":     num_ctx,
        },
    }
    resp = requests.post(
        f"{OLLAMA_HOST}/api/chat",
        json=body,
        timeout=OLLAMA_TIMEOUT,
    )
    resp.raise_for_status()
    content = resp.json()["message"]["content"]
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        if _repair_json is not None:
            parsed = json.loads(_repair_json(content))
        else:
            raise
    return _hoist_nested_dicts(parsed)


def _hoist_nested_dicts(data: dict) -> dict:
    """Fix LLM output where sub-keys were embedded as dicts inside a string array.

    qwen3.5:4b sometimes generates:
      {"pre_market_bullets": ["str1", ..., {"equities_commentary": "..."}]}
    instead of closing the array and opening a new top-level key.
    Runs iteratively until no more hoisting is possible (handles multi-level nesting).
    """
    result = dict(data)
    changed = True
    while changed:
        changed = False
        for key in list(result.keys()):
            value = result[key]
            if isinstance(value, list):
                has_strings = any(isinstance(item, str) for item in value)
                has_dicts = any(isinstance(item, dict) for item in value)
                # Only hoist when the list is mixed (strings + dicts). A pure dict
                # list (e.g. scenarios, portfolio_spotlight) is intentional — leave it.
                if has_strings and has_dicts:
                    result[key] = [item for item in value if isinstance(item, str)]
                    for item in value:
                        if isinstance(item, dict):
                            result.update(item)
                    changed = True
    return result


def _repair_scenario_labels(scenarios: list) -> int:
    """Detect and repair self-contradictory Hot/Cold threshold labels.

    Scenario labels may carry a numeric outcome range, e.g. "Hot (<50.0)". The
    Hot and Cold bands must not overlap: for indicators where higher = hotter
    (ISM/PMI, CPI, sentiment) the valid form is Hot (>X) / Cold (<Y) with X>=Y;
    for indicators where lower = hotter (jobless claims, unemployment) it is
    Hot (<X) / Cold (>Y) with X<=Y. When the parsed bands overlap (the LLM
    inverted the polarity, e.g. Hot (<50.0) + Cold (>48.0)), strip the numeric
    parenthetical from all three labels so we never ship a contradictory range —
    the thesis/rates/equities text already carries the directional meaning.

    Returns the number of labels stripped (0 = labels left intact).
    """
    def _parse(label: str):
        m = re.search(r'([<>])\s*=?\s*([0-9][0-9,\.]*)\s*([KkMmBb]?)', label or "")
        if not m:
            return None
        try:
            val = float(m.group(2).replace(",", ""))
        except ValueError:
            return None
        mult = {"k": 1e3, "m": 1e6, "b": 1e9}.get(m.group(3).lower(), 1.0)
        return m.group(1), val * mult

    if not scenarios or len(scenarios) < 3:
        return 0

    hot, cold = _parse(str(scenarios[0].get("label", ""))), _parse(str(scenarios[2].get("label", "")))
    if not hot or not cold:
        return 0
    hot_op, hot_val = hot
    cold_op, cold_val = cold

    if hot_op == "<" and cold_op == ">":
        overlap = hot_val > cold_val          # valid (jobless-claims style) needs hot_val <= cold_val
    elif hot_op == ">" and cold_op == "<":
        overlap = hot_val < cold_val          # valid (ISM/PMI style) needs hot_val >= cold_val
    else:
        overlap = True                        # same operator on both sides is always contradictory

    if not overlap:
        return 0

    stripped = 0
    for sc in scenarios[:3]:
        lbl = str(sc.get("label", ""))
        new = re.sub(r'\s*\([^)]*\)\s*$', '', lbl).strip()
        if new != lbl:
            sc["label"] = new
            stripped += 1
    return stripped


def _strip_unanchored_scenario_thresholds(scenarios: list, consensus) -> int:
    """Strip numeric outcome ranges from scenario labels when there is no numeric
    consensus to anchor them.

    Regression 2026-06-05: NFP consensus was 85K but the calendar feed carried no
    consensus value, so scenario_consensus was null and the LLM invented buckets
    "Hot (<220K) / In Line (220K-240K) / Cold (>240K)" — bands that bear no relation
    to the actual 85K print. A threshold we cannot anchor is a fabricated number; drop
    the parenthetical so the labels read "Hot / In Line / Cold" (the thesis text already
    carries the directional meaning) rather than asserting a false range. When a numeric
    consensus IS present the LLM payload + _repair_scenario_labels anchor it, so this is
    a no-op. Returns the number of labels stripped."""
    if consensus is not None and re.search(r"\d", str(consensus)):
        return 0  # have a numeric consensus → labels are anchored, leave them
    if not scenarios:
        return 0
    stripped = 0
    for sc in scenarios[:3]:
        if not isinstance(sc, dict):
            continue
        lbl = str(sc.get("label", ""))
        # Only strip a parenthetical that actually carries a number (a bare
        # qualitative aside like "(dovish)" is fine to keep).
        if re.search(r"\([^)]*\d[^)]*\)\s*$", lbl):
            new = re.sub(r"\s*\([^)]*\)\s*$", "", lbl).strip()
            if new != lbl:
                sc["label"] = new
                stripped += 1
    return stripped


# Key-asset terms whose hard numbers (levels/percents) the LLM tends to hallucinate
# in pre_market_bullets. Any LLM bullet (beyond the deterministic opener) that names
# one of these AND cites a digit is dropped and replaced with a snapshot-derived line.
_PMB_DATA_TERMS = (
    "yield", "treasury", "10-yr", "10-year", "10yr",
    "gold", "dxy", "dollar index", "u.s. dollar", "us dollar",
    "bitcoin", "btc", "wti", "crude",
    "s&p", "nasdaq",
)


def _enforce_pre_market_data_bullets(bullets: list, snapshot: dict) -> tuple[list, int]:
    """Replace LLM-written market-DATA bullets with snapshot-derived deterministic lines.

    Root cause this guards: the LLM free-writes pre_market_bullets[1:] and hallucinates
    absolute levels (e.g. 10-Yr yield "3.92%", gold "$2,680", DXY "98.42", BTC "$1.28")
    even though the correct snapshot is in its context. Only bullet[0] is deterministic
    today, so it is the only reliably-correct numeric bullet.

    Strategy (mirrors the deterministic opener + safety-net fallback):
      * keep bullet[0] (deterministic opener + LLM catalyst) untouched
      * drop any later LLM bullet that names a tracked key asset AND cites a digit
        (these are the hallucination-prone "data" lines; BTC has no snapshot level so
        a bad BTC line is simply removed)
      * insert canonical yield / WTI+gold / DXY lines computed from the snapshot
      * preserve genuine narrative bullets (sector leaders, fear & greed, company news,
        economic calendar) verbatim — they carry no tracked key-asset hard numbers

    Returns (new_bullets, num_data_bullets_replaced). Idempotent and snapshot-partial safe.
    """
    if not isinstance(bullets, list) or not bullets:
        return bullets, 0

    snapshot = snapshot or {}
    _DIGIT = re.compile(r"\d")

    def _word(pct: float | None) -> str:
        if pct is None:
            return "was little changed"
        if pct > 0.5:   return "rose"
        if pct > 0.1:   return "edged higher"
        if pct < -0.5:  return "fell"
        if pct < -0.1:  return "edged lower"
        return "was little changed"

    def _g(key: str, field: str):
        return (snapshot.get(key) or {}).get(field)

    # Build canonical data bullets from the snapshot (skip any with a missing level).
    data_bullets: list[str] = []

    tyr_lvl = _g("10-Yr Yield", "level")
    tyr_chg = _g("10-Yr Yield", "change")
    if tyr_lvl is not None:
        bp = round(float(tyr_chg) * 100) if tyr_chg is not None else 0
        _ylvl = f"{float(tyr_lvl):.3f}%"
        if bp > 0:
            data_bullets.append(f"10-Yr Treasury yield rose {bp} bp to {_ylvl}.")
        elif bp < 0:
            data_bullets.append(f"10-Yr Treasury yield fell {abs(bp)} bp to {_ylvl}.")
        else:
            data_bullets.append(f"10-Yr Treasury yield held steady at {_ylvl}.")

    wti_lvl = _g("WTI Crude", "level")
    wti_pct = _g("WTI Crude", "pct_change")
    gld_lvl = _g("Gold", "level")
    gld_pct = _g("Gold", "pct_change")
    if wti_lvl is not None and gld_lvl is not None:
        data_bullets.append(
            f"WTI crude {_word(wti_pct)} {float(wti_pct or 0):+.2f}% to ${float(wti_lvl):,.2f}; "
            f"gold {_word(gld_pct)} {float(gld_pct or 0):+.2f}% to ${float(gld_lvl):,.2f}."
        )
    elif wti_lvl is not None:
        data_bullets.append(f"WTI crude {_word(wti_pct)} {float(wti_pct or 0):+.2f}% to ${float(wti_lvl):,.2f}.")
    elif gld_lvl is not None:
        data_bullets.append(f"Gold {_word(gld_pct)} {float(gld_pct or 0):+.2f}% to ${float(gld_lvl):,.2f}.")

    dxy_lvl = _g("U.S. Dollar (DXY)", "level")
    dxy_pct = _g("U.S. Dollar (DXY)", "pct_change")
    if dxy_lvl is not None:
        data_bullets.append(
            f"Dollar Index (DXY) {_word(dxy_pct)} {float(dxy_pct or 0):+.2f}% to {float(dxy_lvl):.2f}."
        )

    # Nothing to substitute with → leave bullets unchanged rather than gutting them.
    if not data_bullets:
        return bullets, 0

    opener = bullets[0]
    narrative: list[str] = []
    replaced = 0
    for bullet in bullets[1:]:
        btext = str(bullet).lower()
        is_data = bool(_DIGIT.search(btext)) and any(term in btext for term in _PMB_DATA_TERMS)
        if is_data:
            replaced += 1
        else:
            narrative.append(bullet)

    return [opener, *data_bullets, *narrative], replaced


def call_ollama(payload: dict, snapshot: dict) -> dict:
    """Two-shot generation: narrative sections then outlook/portfolio."""

    # Trim news to 4 items per bucket to keep payload small
    news = payload.get("news_by_section") or {}
    news_trimmed = {k: v[:4] for k, v in news.items()}

    # Narrow market_levels to just the key assets
    levels = payload.get("market_levels") or {}

    # Global markets: top 5 only
    gm = dict(list((payload.get("global_markets") or {}).items())[:5])

    # Commodities: top 6 only
    cmdty = dict(list((payload.get("commodities") or {}).items())[:6])

    # Currencies: top 5 only
    fx = dict(list((payload.get("currencies") or {}).items())[:5])

    # Bonds: all (small)
    bonds = payload.get("bonds") or {}

    # Economic events: keep the soonest few for focus, but NEVER drop an upcoming
    # HIGH-importance catalyst (e.g. FOMC) that sorts behind same-week medium prints by
    # date — the [:5] head-slice previously hid the 6/17 FOMC decision from both the
    # scenario picker and the prompt.
    _all_econ = payload.get("upcoming_economic_events") or []
    # Drop FUTURE events dated on a US market holiday (NYSE/Nasdaq closed) — they cannot be
    # that session's catalyst, and surfacing one invites a "Friday's <event>" framing on a
    # closed day (2026-06-18: Juneteenth 6/19). Today's events are kept regardless so a
    # holiday-day run still reports correctly.
    _today_str0 = (payload.get("date") or "")[:10]
    _all_econ = [
        e for e in _all_econ
        if str(e.get("date", ""))[:10] <= _today_str0
        or not _is_us_market_holiday(str(e.get("date", "")))
    ]
    econ = _all_econ[:5] + [e for e in _all_econ[5:] if e.get("importance") == "high"]

    # Split events and earnings into today vs. rest-of-week so prompts can distinguish them.
    today_str  = payload.get("date") or ""
    # Order today's events by catalyst priority — the SAME key the scenario picker uses for
    # _today_events — so the highest-priority today event leads. This keeps the email's first
    # what-to-watch item (watch_today[0], built from today_econ[0]) and the scenario "Primary
    # event" (scenario_event) pointing at the SAME catalyst. 2026-06-18: raw feed order put
    # Philly Fed first (→ watch item) while priority ranked Initial Jobless Claims first
    # (→ Primary event), so the two surfaces named different primary events on one page.
    today_econ = sorted(
        (e for e in econ if str(e.get("date", ""))[:10] == today_str),
        key=lambda e: _catalyst_priority(e.get("event", "")),
    )
    # Order the week-ahead list by (date, catalyst priority) so the biggest upcoming mover
    # leads when several share the soonest date (FOMC ahead of Retail Sales on 6/17).
    week_econ  = sorted(
        (e for e in econ if str(e.get("date", ""))[:10] != today_str),
        key=lambda e: (str(e.get("date", ""))[:10], _catalyst_priority(e.get("event", ""))),
    )
    earn       = payload.get("earnings_calendar") or []
    today_earn = [e for e in earn if str(e.get("date", ""))[:10] == today_str]
    week_earn  = [e for e in earn if str(e.get("date", ""))[:10] != today_str][:5]

    # Flatten news to a plain headline list — avoids model templating output after section names
    # Articles in llm_buckets are pre-formatted strings (headline + summary snippet)
    # Priority order: "general" (Finnhub Reuters/AP breaking news) first, then equities/rates,
    # then commodities/world — prevents stale ETF-flow articles from crowding out breaking stories.
    _NEWS_PRIORITY = ["general", "equities", "fixed_income", "currencies", "commodities", "world"]
    _ordered_news = (
        [(k, news_trimmed[k]) for k in _NEWS_PRIORITY if k in news_trimmed]
        + [(k, v) for k, v in news_trimmed.items() if k not in _NEWS_PRIORITY]
    )
    flat_headlines = [
        a if isinstance(a, str) else (a.get("headline") or a.get("title") or "")
        for _, articles in _ordered_news
        for a in articles
        if a
    ][:15]

    # Sector leaders/laggards for narrative — item #2
    _sp = payload.get("sector_performance") or []
    _sector_top3    = _sp[:3]
    _sector_bottom3 = _sp[-3:][::-1] if len(_sp) >= 3 else []

    # Technical context for equities commentary — item #3
    _tl = payload.get("technical_levels") or {}
    _spx_tl = _tl.get("S&P 500", {})
    _vix_tl = _tl.get("VIX", {})
    _technical_context = {
        "vix":           _vix_tl.get("current"),
        "spx_ma200":     _spx_tl.get("ma200"),
        "spx_52w_high":  _spx_tl.get("52w_high"),
        "spx_current":   _spx_tl.get("current"),
        "spx_above_ma200": (
            bool(_spx_tl.get("current") and _spx_tl.get("ma200") and
                 _spx_tl["current"] > _spx_tl["ma200"])
        ),
    }

    # Week-over-week return context — item #5
    _week_context = {
        "SP500_1w_pct":   (levels.get("S&P 500") or {}).get("pct_change_1w"),
        "NDX_1w_pct":     (levels.get("Nasdaq 100") or {}).get("pct_change_1w"),
        "Gold_1w_pct":    (levels.get("Gold") or {}).get("pct_change_1w"),
        "Yield10_bp_1w":  (bonds.get("10-Year Yield") or {}).get("bp_change_1w"),
        "DXY_1w_pct":     (levels.get("U.S. Dollar (DXY)") or {}).get("pct_change_1w"),
    }

    # Deterministic opener for pre_market_bullets[0] — item #6
    # Compute from snapshot to guarantee number accuracy; LLM fills [catalyst] only.
    _sp500 = levels.get("S&P 500", {})
    _ndx   = levels.get("Nasdaq 100", {})
    _sp_pct  = _sp500.get("pct_change")
    _ndx_pct = _ndx.get("pct_change")
    _sp_lvl  = _sp500.get("level")
    _direction = "higher" if (_sp_pct or 0) >= 0 else "lower"
    _sp_str  = f"{float(_sp_pct):+.2f}%" if _sp_pct is not None else "N/A"
    _ndx_str = f"{float(_ndx_pct):+.2f}%" if _ndx_pct is not None else "N/A"
    _lvl_str = f"{float(_sp_lvl):,.2f}" if _sp_lvl is not None else ""
    _deterministic_opener = (
        f"Markets closed {_direction} — S&P 500 {_sp_str} to {_lvl_str}, "
        f"Nasdaq 100 {_ndx_str}; {{catalyst}}"
    )

    # Always-on geopolitical grounding: fetch a FRESH read of the Iran/Middle-East storyline
    # and pin its direction so the narrative can't invert it off a stale headline (2026-07-02).
    _geo_ctx = build_geopolitical_context(flat_headlines)
    _write_geo_sidecar(_geo_ctx)  # so the sanitize-time scrubber knows whether to drop geo causation

    narrative_payload = {
        "date":                     payload.get("date"),
        "geopolitical_context":     _geo_ctx,
        "market_levels":            levels,
        "bonds":                    bonds,
        "global_markets_top5":      gm,
        "commodities_top6":         cmdty,
        "currencies_top5":          fx,
        "todays_economic_events":   today_econ,
        "week_ahead_econ_events":   week_econ,
        # item #7: bucketed headlines so model knows which category each story belongs to
        "news_by_category":         news_trimmed,
        "recent_headlines":         flat_headlines,   # flat list kept as fallback
        "recent_earnings_actuals":  payload.get("recent_earnings_actuals") or [],
        "recent_macro_prints":      payload.get("recent_macro_prints") or [],
        "prior_scenario_event":     payload.get("prior_scenario_event"),
        # items #2–#6
        "sector_top3":              _sector_top3,
        "sector_bottom3":           _sector_bottom3,
        "technical_context":        _technical_context,
        "fear_greed":               payload.get("fear_greed") or {},
        "week_context":             _week_context,
    }

    # Inline the opener into the system prompt (not the payload) so the model cannot
    # echo the key name as its sole output — the sentinel is replaced with the actual
    # template string before every Call 1 attempt.
    _narrative_sys = SYSTEM_PROMPT_NARRATIVE.replace("BULLET_0_TEMPLATE", _deterministic_opener)

    print("  [LLM Call 1/3] Generating market narrative sections...")
    part1 = {}
    for attempt in range(4):
        try:
            part1 = _call_ollama_raw(_narrative_sys, narrative_payload, num_ctx=16384)
            print(f"    Keys returned: {list(part1.keys())}")
            # Remap aliases to canonical keys BEFORE scrubbing so scrubber finds them.
            # Only remap when the value is a non-empty string — a dict value (e.g. market_summary
            # returned as a nested object) must not become equities_commentary.
            for alias, canonical in LLM_KEY_ALIASES.items():
                if alias in part1 and canonical not in part1:
                    _v = part1[alias]
                    if isinstance(_v, str) and _v.strip():
                        part1[canonical] = part1.pop(alias)
                    else:
                        part1.pop(alias)  # discard non-string alias values
            part1 = scrub_banned_phrases(part1)
            banned = find_banned_phrases(part1)
            leaks = find_leaked_placeholders(part1)
            sign_fixes = _correct_sign_mismatches(part1, snapshot)
            if sign_fixes:
                print(f"  [CORRECT] Auto-corrected {sign_fixes} sign mismatch(es) in Call 1 output.")
            dir_fixes = _correct_direction_words(part1, snapshot)
            if dir_fixes:
                print(f"  [CORRECT] Auto-corrected {dir_fixes} direction-word/superlative contradiction(s) in Call 1 output.")
            _call1_required = {
                "pre_market_bullets", "equities_commentary", "fixed_income_commentary",
                "currencies_commentary", "commodities_commentary", "economics_commentary",
            }
            missing_required = _call1_required - set(part1.keys())
            if missing_required:
                print(f"  [RETRY] Attempt {attempt + 1} missing required narrative keys: {sorted(missing_required)}. Retrying...")
                continue
            numeric = _check_numeric_consistency(part1, snapshot)
            causal = _check_causal_logic(part1, snapshot)
            gm_inv = _check_growth_multiple_inversion(part1, snapshot)
            risk_pol = _check_risk_polarity_inversion(part1, snapshot)
            direction = _check_direction_words(part1, snapshot)
            corp_actions = _check_fabricated_corporate_actions(part1)
            # When there are NO economic releases dated today, the narrative must not
            # frame any release as "today"/"this morning" — catches the LLM pulling a
            # week-ahead catalyst (e.g. Thursday's GDP) forward and dating it today.
            dating = _check_event_dating(part1, today_has_econ=bool(today_econ))
            move_sig = _check_move_significance(part1, snapshot)
            superlatives = _check_unsourced_superlatives(part1, flat_headlines)
            editorial = _check_editorial_contradictions(part1, snapshot)
            peace_coh = _check_peace_narrative_coherence(part1)
            if (not banned and not leaks and not numeric and not causal and not gm_inv and not dating
                    and not move_sig and not superlatives and not direction and not corp_actions
                    and not editorial and not risk_pol and not peace_coh):
                break
            if banned:
                print(f"  [RETRY] Attempt {attempt + 1} still contained banned phrases after scrub: {banned}. Retrying...")
            if leaks:
                print(f"  [RETRY] Attempt {attempt + 1} contained leaked placeholders: {leaks}. Retrying...")
            if numeric:
                print(f"  [RETRY] Attempt {attempt + 1} had numeric consistency violations: {numeric}. Retrying...")
            if causal:
                print(f"  [RETRY] Attempt {attempt + 1} had causal logic inversions: {causal}. Retrying...")
            if gm_inv:
                print(f"  [RETRY] Attempt {attempt + 1} blamed multiple compression on falling oil/yields: {gm_inv}. Retrying...")
            if risk_pol:
                print(f"  [RETRY] Attempt {attempt + 1} mislabeled the session's risk regime: {risk_pol}. Retrying...")
            if dating:
                print(f"  [RETRY] Attempt {attempt + 1} dated a non-today event as today: {dating}. Retrying...")
            if move_sig:
                print(f"  [RETRY] Attempt {attempt + 1} framed a noise-level move as direction: {move_sig}. Retrying...")
            if superlatives:
                print(f"  [RETRY] Attempt {attempt + 1} made unsourced superlative/geopolitical claims: {superlatives}. Retrying...")
            if direction:
                print(f"  [RETRY] Attempt {attempt + 1} had direction-word/superlative contradictions: {direction}. Retrying...")
            if corp_actions:
                print(f"  [RETRY] Attempt {attempt + 1} made fabricated corporate-action claims: {corp_actions}. Retrying...")
            if editorial:
                print(f"  [RETRY] Attempt {attempt + 1} had editorial contradictions vs snapshot: {editorial}. Retrying...")
            if peace_coh:
                print(f"  [RETRY] Attempt {attempt + 1} framed the peace/ceasefire storyline incoherently: {peace_coh}. Retrying...")
        except Exception as exc:
            print(f"  [WARN] Narrative call failed (attempt {attempt + 1}): {exc}")
            part1 = {}

    # Refinement pass: deepen existing sections AND generate any that Call 1 missed.
    if part1:
        print("  [LLM Call 1r] Refining narrative sections...")
        _call1_required = {
            "pre_market_bullets", "equities_commentary", "fixed_income_commentary",
            "currencies_commentary", "commodities_commentary", "economics_commentary",
        }
        _missing_after_loop = sorted(_call1_required - set(part1.keys()))
        if _missing_after_loop:
            print(f"  [GENERATE] Refinement pass will generate missing keys: {_missing_after_loop}")
        refinement_input = {
            "draft":        part1,
            "source_data":  narrative_payload,
            "missing_keys": _missing_after_loop,
        }
        for attempt in range(2):
            try:
                part1_refined = _call_ollama_raw(SYSTEM_PROMPT_REFINE, refinement_input)
                for key in ["equities_commentary", "fixed_income_commentary",
                            "commodities_commentary", "currencies_commentary", "economics_commentary"]:
                    refined_val = part1_refined.get(key, "")
                    if refined_val and len(refined_val) > len(part1.get(key, "")):
                        part1[key] = refined_val
                if (isinstance(part1_refined.get("pre_market_bullets"), list)
                        and len(part1_refined["pre_market_bullets"]) >= 4):
                    part1["pre_market_bullets"] = part1_refined["pre_market_bullets"]
                print(f"    Refinement pass complete (attempt {attempt + 1}).")
                break
            except Exception as exc:
                print(f"  [WARN] Refinement pass attempt {attempt + 1} failed: {exc}")

    # Safety net: if pre_market_bullets is still absent after all LLM attempts + refinement,
    # inject snapshot-derived bullets so validate_commentary passes with narrative_source='llm'.
    if not isinstance(part1.get("pre_market_bullets"), list) or not part1["pre_market_bullets"]:
        def _snap_val(key, field, default=0.0):
            return (snapshot.get(key) or {}).get(field) or default
        def _snap_dir(pct):
            return "gained" if pct >= 0 else "fell"
        _sp_pct  = _snap_val("S&P 500",           "pct_change")
        _sp_lvl  = _snap_val("S&P 500",           "level")
        _ndx_pct = _snap_val("Nasdaq 100",         "pct_change")
        _tyr_lvl = _snap_val("10-Yr Yield",        "level")
        _wti_pct = _snap_val("WTI Crude",          "pct_change")
        _wti_lvl = _snap_val("WTI Crude",          "level")
        _gld_pct = _snap_val("Gold",               "pct_change")
        _dxy_pct = _snap_val("U.S. Dollar (DXY)",  "pct_change")
        _dxy_lvl = _snap_val("U.S. Dollar (DXY)",  "level")
        part1["pre_market_bullets"] = [
            f"S&P 500 {_snap_dir(_sp_pct)} {_sp_pct:+.2f}% to {_sp_lvl:,.0f}; Nasdaq 100 {_snap_dir(_ndx_pct)} {_ndx_pct:+.2f}%.",
            f"10-Yr yield at {_tyr_lvl:.3f}%.",
            f"WTI crude {_snap_dir(_wti_pct)} {_wti_pct:+.2f}% to ${_wti_lvl:.2f}.",
            f"DXY {_snap_dir(_dxy_pct)} {_dxy_pct:+.2f}% to {_dxy_lvl:.2f}.",
        ]
        print("  [FALLBACK] Injected deterministic pre_market_bullets (LLM failed to generate).")

    # Replace LLM-hallucinated market-data bullets (levels/percents for yield, WTI,
    # gold, DXY, BTC) with snapshot-derived deterministic lines. Runs after Call 1,
    # refinement, AND the fallback so every path is covered. Keeps bullet[0] (the
    # deterministic opener) and genuine narrative bullets untouched.
    _pmb_fixed, _pmb_replaced = _enforce_pre_market_data_bullets(
        part1.get("pre_market_bullets"), snapshot
    )
    if _pmb_replaced:
        part1["pre_market_bullets"] = _pmb_fixed
        print(f"  [ENFORCE] Replaced {_pmb_replaced} LLM data bullet(s) with snapshot-derived lines.")

    # Compact payload for outlook call — items #2 (sectors) and #8 (prior-day continuity)
    outlook_payload = {
        "date":                      payload.get("date"),
        "market_levels":             levels,
        "key_data_summary":          payload.get("key_data_summary"),
        "portfolio_top_performers":  payload.get("portfolio_top_performers"),
        "portfolio_names_to_watch":  payload.get("portfolio_names_to_watch"),
        "mag7_consensus_forecasts":  payload.get("mag7_consensus_forecasts"),
        "news_headlines":            {k: v[:2] for k, v in news_trimmed.items()},
        "sector_top3":               _sector_top3,
        "sector_bottom3":            _sector_bottom3,
        "prior_day_label":           payload.get("prior_day_label"),
        "prior_day_synthesis":       payload.get("prior_day_synthesis"),
    }

    print("  [LLM Call 2/3] Generating market outlook and portfolio intelligence...")
    part2 = {}
    for attempt in range(4):
        try:
            part2 = _call_ollama_raw(SYSTEM_PROMPT_OUTLOOK, outlook_payload)
            print(f"    Keys returned: {list(part2.keys())}")
            part2 = scrub_banned_phrases(part2)
            banned = find_banned_phrases(part2)
            leaks = find_leaked_placeholders(part2)
            echo = _check_equities_rationale_echo(part2)
            move_sig = _check_move_significance(part2, snapshot)
            superlatives = _check_unsourced_superlatives(part2, flat_headlines)
            dir_fixes = _correct_direction_words(part2, snapshot)
            if dir_fixes:
                print(f"  [CORRECT] Auto-corrected {dir_fixes} direction-word/superlative contradiction(s) in Call 2/3 output.")
            direction = _check_direction_words(part2, snapshot)
            corp_actions = _check_fabricated_corporate_actions(part2)
            editorial = _check_editorial_contradictions(part2, snapshot)
            stance_rev = _check_stance_reversal_unexplained(part2, outlook_payload.get("prior_day_label"))
            aco_coh = _check_asset_class_stance_coherence(part2)
            gm_inv2 = _check_growth_multiple_inversion(part2, snapshot)
            risk_pol2 = _check_risk_polarity_inversion(part2, snapshot)
            if (not banned and not leaks and not echo and not move_sig and not superlatives
                    and not direction and not corp_actions and not editorial and not stance_rev
                    and not aco_coh and not gm_inv2 and not risk_pol2):
                break
            if banned:
                print(f"  [RETRY] Attempt {attempt + 1} still contained banned phrases after scrub: {banned}. Retrying...")
            if leaks:
                print(f"  [RETRY] Attempt {attempt + 1} contained leaked placeholders: {leaks}. Retrying...")
            if echo:
                print(f"  [RETRY] Attempt {attempt + 1} echo violation: {echo}. Retrying...")
            if move_sig:
                print(f"  [RETRY] Attempt {attempt + 1} framed a noise-level move as direction: {move_sig}. Retrying...")
            if superlatives:
                print(f"  [RETRY] Attempt {attempt + 1} made unsourced superlative/geopolitical claims: {superlatives}. Retrying...")
            if direction:
                print(f"  [RETRY] Attempt {attempt + 1} had direction-word/superlative contradictions: {direction}. Retrying...")
            if corp_actions:
                print(f"  [RETRY] Attempt {attempt + 1} made fabricated corporate-action claims: {corp_actions}. Retrying...")
            if editorial:
                print(f"  [RETRY] Attempt {attempt + 1} had editorial contradictions vs snapshot: {editorial}. Retrying...")
            if stance_rev:
                print(f"  [RETRY] Attempt {attempt + 1} sharp stance reversal unexplained: {stance_rev}. Retrying...")
            if aco_coh:
                print(f"  [RETRY] Attempt {attempt + 1} asset-class label/rationale polarity clash: {aco_coh}. Retrying...")
            if gm_inv2:
                print(f"  [RETRY] Attempt {attempt + 1} blamed multiple compression on falling oil/yields: {gm_inv2}. Retrying...")
            if risk_pol2:
                print(f"  [RETRY] Attempt {attempt + 1} outlook mislabeled the session's risk regime: {risk_pol2}. Retrying...")
        except Exception as exc:
            print(f"  [WARN] Outlook call failed (attempt {attempt + 1}): {exc}")
            part2 = {}

    # Focused payload for session recap / watch-today / international section
    recap_payload = {
        "date":                     payload.get("date"),
        "market_levels":            levels,
        "bonds":                    bonds,
        "global_markets_top3":      dict(list(gm.items())[:3]),
        "commodities_top3":         dict(list(cmdty.items())[:3]),
        "currencies_top3":          dict(list(fx.items())[:3]),
        "todays_economic_events":   today_econ,
        "week_ahead_econ_events":   week_econ,
        "todays_earnings":          today_earn,
        "this_week_earnings":       week_earn,
        "international_macro":      payload.get("international_macro") or {},
        "fear_greed":               payload.get("fear_greed") or {},
        "news_headlines":           {k: v[:2] for k, v in news_trimmed.items()},
        "recent_earnings_actuals":  payload.get("recent_earnings_actuals") or [],
    }

    print("  [LLM Call 3/3] Generating session recap and watch-today section...")
    part3 = {}
    for attempt in range(4):
        try:
            part3 = _call_ollama_raw(SYSTEM_PROMPT_RECAP, recap_payload)
            print(f"    Keys returned: {list(part3.keys())}")
            part3 = scrub_banned_phrases(part3)
            banned = find_banned_phrases(part3)
            leaks = find_leaked_placeholders(part3)
            risk_pol3 = _check_risk_polarity_inversion(part3, snapshot)
            if not banned and not leaks and not risk_pol3:
                break
            if banned:
                print(f"  [RETRY] Attempt {attempt + 1} still contained banned phrases after scrub: {banned}. Retrying...")
            if leaks:
                print(f"  [RETRY] Attempt {attempt + 1} contained leaked placeholders: {leaks}. Retrying...")
            if risk_pol3:
                print(f"  [RETRY] Attempt {attempt + 1} recap mislabeled the session's risk regime: {risk_pol3}. Retrying...")
        except Exception as exc:
            print(f"  [WARN] Recap call failed (attempt {attempt + 1}): {exc}")
            part3 = {}

    # Deterministic watch_today — slots [0] (today's econ) and [1] (today's earnings) are
    # pure data lookups, so we ALWAYS compute them from the SAME today_econ/today_earn the
    # report/email blocks render. This guarantees they can never contradict those blocks
    # (the LLM has emitted "No major earnings today" while 8 names reported today, and has
    # dated week-ahead events as "today"). Slot [2] (a technical level/structure call) stays
    # LLM-authored when present, else a deterministic yield watch.
    _llm_wt = list(part3.get("watch_today") or [])
    if today_econ:
        _e0 = today_econ[0]
        _nm0, _imp0 = _e0.get("event", ""), _e0.get("importance", "")
        _wt0 = f"{_nm0} ({_imp0})" if (_nm0 and _imp0) else (_nm0 or "No major data today.")
    else:
        _wt0 = "No major data today."
    if today_earn:
        _syms = [e.get("symbol", "") for e in today_earn[:5] if e.get("symbol")]
        _wt1 = "Earnings due: " + ", ".join(_syms) + (", among others." if len(today_earn) > 5 else ".")
    else:
        _wt1 = "No major earnings today."
    _wt2 = _llm_wt[2].strip() if (len(_llm_wt) > 2 and str(_llm_wt[2]).strip()) else ""
    if not _wt2:
        _y10 = (bonds.get("10-Year Yield") or {}).get("level")
        _wt2 = (f"Monitor the 10-year Treasury yield near {float(_y10):.2f}%."
                if _y10 is not None else "Monitor key technical levels into the next session.")
    part3["watch_today"] = [_wt0, _wt1, _wt2]
    print("  [WATCH] watch_today [0]/[1] set deterministically from today's calendar.")

    # Collect known tickers from the portfolio payload for post-generation validation
    known_tickers: set[str] = set()
    for entry in (payload.get("mag7_consensus_forecasts") or {}).keys():
        known_tickers.add(str(entry).upper())
    for entry in (payload.get("portfolio_top_performers") or []):
        if isinstance(entry, dict) and entry.get("ticker"):
            known_tickers.add(str(entry["ticker"]).upper())
    for entry in (payload.get("portfolio_names_to_watch") or []):
        if isinstance(entry, dict) and entry.get("ticker"):
            known_tickers.add(str(entry["ticker"]).upper())

    # Compact synthesis payload — reads already-generated text, no raw market data needed
    synthesis_payload = {
        "date":                     today_str,
        "market_outlook_label":     part2.get("market_outlook_label"),
        "equities_commentary":      part1.get("equities_commentary", ""),
        "fixed_income_commentary":  part1.get("fixed_income_commentary", ""),
        "commodities_commentary":   part1.get("commodities_commentary", ""),
        "currencies_commentary":    part1.get("currencies_commentary", ""),
        "economics_commentary":     part1.get("economics_commentary", ""),
        "todays_economic_events":   today_econ,
        "week_ahead_econ_events":   week_econ,
        "todays_earnings":          today_earn,
        "this_week_earnings":       week_earn[:3],
    }

    print("  [LLM Call 4/4] Generating cross-asset synthesis...")
    part4 = {}
    for attempt in range(4):
        try:
            part4 = _call_ollama_raw(SYSTEM_PROMPT_SYNTHESIS, synthesis_payload)
            print(f"    Keys returned: {list(part4.keys())}")
            part4 = scrub_banned_phrases(part4)
            banned = find_banned_phrases(part4)
            leaks = find_leaked_placeholders(part4)
            dating = _check_event_dating(part4, today_has_econ=bool(today_econ))
            yld_err = _check_synthesis_yield_direction(part4, snapshot)
            gm_inv4 = _check_growth_multiple_inversion(part4, snapshot)
            risk_pol4 = _check_risk_polarity_inversion(part4, snapshot)
            if not banned and not leaks and not dating and not yld_err and not gm_inv4 and not risk_pol4:
                break
            if banned:
                print(f"  [RETRY] Attempt {attempt + 1} synthesis still had banned phrases: {banned}. Retrying...")
            if leaks:
                print(f"  [RETRY] Attempt {attempt + 1} contained leaked placeholders: {leaks}. Retrying...")
            if dating:
                print(f"  [RETRY] Attempt {attempt + 1} synthesis dated a non-today event as today: {dating}. Retrying...")
            if yld_err:
                print(f"  [RETRY] Attempt {attempt + 1} 10Y direction wrong: {yld_err}. Retrying...")
            if gm_inv4:
                print(f"  [RETRY] Attempt {attempt + 1} synthesis blamed multiple compression on falling oil/yields: {gm_inv4}. Retrying...")
            if risk_pol4:
                print(f"  [RETRY] Attempt {attempt + 1} synthesis mislabeled the session's risk regime: {risk_pol4}. Retrying...")
        except Exception as exc:
            print(f"  [WARN] Synthesis call failed (attempt {attempt + 1}): {exc}")
            part4 = {}

    # ── Call 5: Scenario framework (the soonest high-importance catalyst) ──
    part5: dict = {}
    _today_date = (payload.get("date") or datetime.today().strftime("%Y-%m-%d"))[:10]
    _today_events = sorted(
        (e for e in econ
         if str(e.get("date", ""))[:10] == _today_date and e.get("importance") == "high"),
        key=lambda e: _catalyst_priority(e.get("event", "")),
    )
    # Pick the scenario's primary event. Prefer a high-importance event TODAY; otherwise
    # fall back to the soonest UPCOMING high-importance event (else the soonest event).
    # Crucially we no longer mislabel a future event as "today": we compute the event's
    # day label and pass it through so the section is titled correctly (e.g. "Thursday's
    # Scenarios") instead of presenting Thursday's GDP as today's catalyst.
    if _today_events:
        _primary_event, _event_day_label = _today_events[0], "today"
    else:
        # Sort by (date, catalyst priority) so the soonest date wins, and within the
        # soonest date the bigger market mover wins (FOMC > Retail Sales on 6/17).
        _future = sorted(
            (e for e in econ if str(e.get("date", ""))[:10] > _today_date),
            key=lambda e: (str(e.get("date", ""))[:10], _catalyst_priority(e.get("event", ""))),
        )
        _hi_future = [e for e in _future if e.get("importance") == "high"]
        _primary_event = (_hi_future or _future or econ or [None])[0]
        _event_day_label = _event_day_from_dates(
            str((_primary_event or {}).get("date", "")), _today_date
        )
    if _primary_event:
        _ev_name = _primary_event.get("event", "")
        _ev_cons = _primary_event.get("consensus")
        _ev_prev = _primary_event.get("previous")
        scenarios_payload = {
            "primary_event":    _ev_name,
            "event_day":        _event_day_label or "today",  # "today"/"tomorrow"/weekday
            "consensus":        _ev_cons,
            "previous":         _ev_prev,
            "market_snapshot":  {k: v for k, v in list(levels.items())[:8]},
            "bonds":            bonds,
            "upcoming_events":  econ[:3],
        }
        print("  [LLM Call 5/5] Generating scenario framework...")
        for attempt in range(3):
            try:
                part5 = _call_ollama_raw(SYSTEM_PROMPT_SCENARIOS, scenarios_payload)
                print(f"    Keys returned: {list(part5.keys())}")
                _scens = part5.get("scenarios") or []
                _lvls  = part5.get("levels_to_watch") or []
                # Validate tickers against whitelist; strip any bad ones
                _any_bad = False
                for _sc in _scens:
                    _raw_tickers = [str(t).upper() for t in (_sc.get("tickers") or [])]
                    _clean = [t for t in _raw_tickers if t in ETF_WHITELIST]
                    if len(_clean) < len(_raw_tickers):
                        _any_bad = True
                        _sc["tickers"] = _clean
                if _any_bad:
                    print(f"  [VALIDATE] Stripped non-whitelist ticker(s) from scenarios.")
                # Guard against inverted Hot/Cold threshold polarity (e.g. "Hot (<50)" + "Cold (>48)").
                _stripped = _repair_scenario_labels(_scens)
                if _stripped:
                    print(f"  [VALIDATE] Inverted scenario thresholds — stripped numeric range from {_stripped} label(s).")
                _unanchored = _strip_unanchored_scenario_thresholds(_scens, _ev_cons)
                if _unanchored:
                    print(f"  [VALIDATE] No numeric consensus — stripped ungrounded threshold from {_unanchored} scenario label(s).")
                # Accept if we have at least 3 scenarios; levels_to_watch is optional
                if len(_scens) >= 3:
                    part5["scenarios"]       = _scens[:3]
                    part5["levels_to_watch"] = _lvls  # may be empty — render handles gracefully
                    part5["scenario_event"]     = _ev_name
                    part5["scenario_consensus"] = str(_ev_cons) if _ev_cons is not None else None
                    part5["scenario_event_day"] = _event_day_label or "today"
                    break
                print(f"  [RETRY] Attempt {attempt+1}: got {len(_scens)} scenarios, {len(_lvls)} levels. Retrying...")
                part5 = {}
            except Exception as exc:
                print(f"  [WARN] Scenarios call failed (attempt {attempt + 1}): {exc}")
                part5 = {}
    else:
        print("  [LLM Call 5/5] Skipped — no high-importance events today.")

    merged = {**part1, **part2, **part3, **part4, **part5}

    # Remap any remaining aliases (part1 loop already remapped its keys; this catches part2/3 stragglers)
    for alias, canonical in LLM_KEY_ALIASES.items():
        if alias in merged and canonical not in merged:
            merged[canonical] = merged.pop(alias)

    # Scrub hallucinated off-narrative conflicts (e.g. "Russian attacks on Ukrainian
    # cities" injected into a US-Iran session) — any conflict entity absent from the
    # source headline corpus is fabricated. Runs here where flat_headlines is in scope.
    geo_scrubbed = _scrub_offnarrative_geopolitics(merged, " ".join(flat_headlines))
    if geo_scrubbed:
        print(f"[VALIDATE] Scrubbed off-narrative geopolitical hallucination from {geo_scrubbed} field(s).")

    # Strip any keys not in the expected output schema — prevents LLM "response",
    # "portfolio_spotlight_losers", "summary", and other hallucinated fields from
    # leaking into latest_commentary.json.
    _ALLOWED_LLM_KEYS = {
        "pre_market_bullets", "equities_commentary", "fixed_income_commentary",
        "commodities_commentary", "currencies_commentary", "economics_commentary",
        "market_outlook_label", "market_outlook_rationale",
        "tactical_outperforming", "tactical_underperforming", "asset_class_outlooks",
        "portfolio_spotlight_winners", "portfolio_spotlight_watch",
        "session_recap", "watch_today", "international_section",
        "cross_asset_synthesis",
        # Phase 4: scenario framework
        "scenarios", "levels_to_watch", "scenario_event", "scenario_consensus", "scenario_event_day",
        # Phase 6: trending-topic spotlight (generated outside call_ollama, listed for documentation)
        "topic_spotlight",
    }
    unexpected = set(merged) - _ALLOWED_LLM_KEYS
    if unexpected:
        print(f"[VALIDATE] Stripping unexpected LLM keys: {sorted(unexpected)}")
    merged = {k: v for k, v in merged.items() if k in _ALLOWED_LLM_KEYS}

    return merged, known_tickers


def _extract_text_recursive(val) -> str:
    """Extract all text from a nested string/list/dict structure."""
    if isinstance(val, str):
        return val
    if isinstance(val, list):
        return " ".join(_extract_text_recursive(item) for item in val)
    if isinstance(val, dict):
        return " ".join(_extract_text_recursive(v) for v in val.values())
    return ""


def find_banned_phrases(data: dict) -> list[str]:
    found = []
    for key in NARRATIVE_KEYS:
        val = data.get(key, "")
        text = _extract_text_recursive(val).lower()
        for phrase in BANNED_PHRASES:
            if phrase in text and phrase not in found:
                found.append(phrase)
    return found


_PLACEHOLDER_PATTERNS = [
    re.compile(r"\{[a-z_][a-z0-9_]*\}"),           # {spx_pct}, {ust10_level}
    re.compile(r"\[[a-z_][a-z0-9_/ +-]*\]"),        # [value], [higher/lower], [implication]
]


def find_leaked_placeholders(data: dict) -> list[str]:
    """Detect prompt-template placeholders that leaked through into LLM output."""
    found = []
    for key in NARRATIVE_KEYS:
        val = data.get(key, "")
        text = " ".join(val) if isinstance(val, list) else str(val)
        for pat in _PLACEHOLDER_PATTERNS:
            for m in pat.findall(text):
                if m not in found:
                    found.append(m)
    return found


_EVENT_KEYWORDS = (
    "gdp", "gdpnow", "cpi", "pce", "ppi", "jobless claims", "initial claims",
    "nonfarm", "non-farm", "payroll", "ism", "pmi", "retail sales",
    "housing starts", "building permits", "factory orders", "durable goods",
    "consumer confidence", "consumer sentiment", "jolts", "fomc", "fed minutes",
    "rate decision", "trade balance", "industrial production",
)
_TODAY_WORDS_RE = re.compile(r"\b(today|this morning|this afternoon|8:30\s*am|10:00\s*am)\b", re.I)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _check_event_dating(data: dict, today_has_econ: bool) -> list[str]:
    """Flag narrative that dates an economic release as 'today' when none is scheduled.

    Only active when today_has_econ is False (no release dated today in our calendar):
    in that state ANY sentence pairing an econ-release keyword with a today-word is a
    false same-day claim (the LLM pulled a week-ahead catalyst forward). Returns a list
    of offending snippets (empty = clean). Scans pre_market_bullets + economics_commentary.
    """
    if today_has_econ:
        return []
    chunks: list[str] = []
    pmb = data.get("pre_market_bullets")
    if isinstance(pmb, list):
        chunks.extend(str(b) for b in pmb)
    elif isinstance(pmb, str):
        chunks.append(pmb)
    if data.get("economics_commentary"):
        chunks.append(str(data["economics_commentary"]))
    if data.get("cross_asset_synthesis"):
        chunks.append(str(data["cross_asset_synthesis"]))
    violations: list[str] = []
    for chunk in chunks:
        for sent in _SENTENCE_SPLIT_RE.split(chunk):
            low = sent.lower()
            if not _TODAY_WORDS_RE.search(sent):
                continue
            if any(kw in low for kw in _EVENT_KEYWORDS):
                violations.append(sent.strip()[:90])
    return violations[:4]


# ---------------------------------------------------------------------------
# Credibility guardrails (PR 0/1): noise-as-signal + unsourced superlatives.
# Same contract as the other _check_* validators: return list[str] of issues
# (empty = clean) so the existing Call-1/Call-2 retry loops can re-roll.
# ---------------------------------------------------------------------------

# A daily index move smaller than this (in %) is statistical noise and must not
# be described as confirming/driving a directional bias.
_NOISE_MOVE_PCT = 0.25

# "0.02% advance confirms a bullish bias" — confirmation-of-bias language, which
# is essentially never legitimate on a flat tape. Also index-tied strong-move verbs.
_BIAS_CONFIRM_RE = re.compile(
    r"(confirm\w*|cement\w*|reinforc\w*|signal\w*|underscor\w*|solidif\w*)\s+"
    r"(an?\s+|the\s+|a\s+continued\s+|its\s+)?(bull\w*|bear\w*|up\s*trend|down\s*trend|risk-?on|risk-?off)"
    r"|\b(bull\w*|bear\w*)\s+bias\b",
    re.IGNORECASE,
)
_INDEX_STRONG_MOVE_RE = re.compile(
    r"\b(s&p\s*500|s&p|nasdaq|dow|the\s+index|the\s+market|equities|stocks)\b"
    r"[^.]{0,40}\b(rallied|rally|surg\w+|soar\w+|plung\w+|tumbl\w+|crater\w+|"
    r"sold\s+off|sell-?off|spiked?|cratered)\b"
    r"|\b(rallied|surg\w+|soar\w+|plung\w+|tumbl\w+)\b[^.]{0,30}\b(s&p|nasdaq|dow|index|market)\b",
    re.IGNORECASE,
)


def _index_daily_pct(snapshot: dict) -> float | None:
    """Best-effort daily % change of the broad equity tape from the snapshot."""
    for key in ("S&P 500", "S&P 500 (SPX)", "SPX", "Nasdaq 100"):
        entry = (snapshot or {}).get(key)
        if isinstance(entry, dict) and entry.get("pct_change") is not None:
            try:
                return float(entry["pct_change"])
            except (TypeError, ValueError):
                continue
    return None


def _check_move_significance(data: dict, snapshot: dict) -> list[str]:
    """Flag directional/bias language attached to a noise-level index move.

    Only fires when |S&P daily %| < _NOISE_MOVE_PCT. Scans the index-level
    narrative fields (equities_commentary, market_outlook_rationale) for
    confirmation-of-bias phrasing or index-tied strong-move verbs. Sector- and
    single-name moves are NOT scanned, so legitimate "Energy fell -1.5%" is fine.
    """
    pct = _index_daily_pct(snapshot)
    if pct is None or abs(pct) >= _NOISE_MOVE_PCT:
        return []
    violations: list[str] = []
    for field in ("equities_commentary", "market_outlook_rationale"):
        text = data.get(field)
        if not isinstance(text, str) or not text.strip():
            continue
        for sent in _SENTENCE_SPLIT_RE.split(text):
            if _BIAS_CONFIRM_RE.search(sent) or _INDEX_STRONG_MOVE_RE.search(sent):
                violations.append(f"{field}: noise move ({pct:+.2f}%) framed as direction — '{sent.strip()[:80]}'")
    return violations[:4]


# Historical-comparison superlatives ("widest ... in 25 years", "most since 2008").
# These imply a checkable research claim and must be corroborated by a headline.
# NOTE: plain technical levels like "52-week high of 7,520" do NOT match (no
# in/since-<time> qualifier), so data-derived facts are not flagged.
_HIST_SUPERLATIVE_RE = re.compile(
    r"\b(widest|narrowest|biggest|largest|smallest|strongest|weakest|fastest|"
    r"steepest|highest|lowest|best|worst|most|sharpest|deepest)\b"
    r"[^.]{0,40}\b(in|since|over)\b[^.]{0,24}"
    r"(\d{2,4}|\b(?:one|two|three|four|five|ten|twenty|thirty)\b|year|years|decade|month)",
    re.IGNORECASE,
)
# Specific geopolitical EVENT claims (not just nouns) that need a source.
_GEO_EVENT_RE = re.compile(
    r"\b(air\s*strikes?|strikes?|missile\w*|invasion|invaded|ceasefire|truce|"
    r"sanction\w*|coup|nuclear\s+\w+|peace\s+deal|peace\s+talks?|bombard\w*|"
    r"retaliat\w*|escalat\w*)\b",
    re.IGNORECASE,
)
_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "over", "than",
    "have", "has", "was", "were", "are", "its", "their", "amid", "after", "while",
    "as", "of", "to", "in", "on", "by", "at", "a", "an", "is", "be", "it",
}


def _content_tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9.&-]{3,}", text.lower()) if w not in _STOPWORDS}


def _check_unsourced_superlatives(data: dict, headlines: list) -> list[str]:
    """Flag historical-superlative or geopolitical-event claims with no headline support.

    A claim is "supported" if its sentence shares at least one distinctive content
    token with the available headlines. Catches fabrications like "South Korean
    equities outpaced U.S. tech by the widest margin in 25 years" and unsourced
    "fresh U.S. strikes on Iran" when no headline corroborates them.
    """
    hl_text = " ".join(str(h) for h in (headlines or [])).lower()
    hl_tokens = _content_tokens(hl_text)
    fields = (
        "equities_commentary", "fixed_income_commentary", "commodities_commentary",
        "currencies_commentary", "economics_commentary", "market_outlook_rationale",
        "cross_asset_synthesis",
    )
    violations: list[str] = []
    for field in fields:
        text = data.get(field)
        if not isinstance(text, str) or not text.strip():
            continue
        for sent in _SENTENCE_SPLIT_RE.split(text):
            is_superlative = bool(_HIST_SUPERLATIVE_RE.search(sent))
            is_geo = bool(_GEO_EVENT_RE.search(sent))
            if not (is_superlative or is_geo):
                continue
            sent_tokens = _content_tokens(sent)
            if hl_tokens and (sent_tokens & hl_tokens):
                continue  # corroborated by at least one headline token
            kind = "superlative" if is_superlative else "geopolitical"
            violations.append(f"{field}: unsourced {kind} claim — '{sent.strip()[:80]}'")
    return violations[:4]


def _check_equities_rationale_echo(part2: dict) -> str | None:
    """Flag when asset_class_outlooks.Equities.rationale duplicates market_outlook_rationale.

    The two are supposed to occupy different time horizons in the report — the Near-Term
    Market Outlook box is 4-6 weeks (price-action driven), and the Long-Term Fundamental
    Outlook Equities row is 3-6 months (earnings/multiples driven). The LLM has a strong
    habit of echoing the same paragraph into both slots, so the reader sees the same text
    twice on page 7. Return a violation string when the two rationales overlap heavily
    (>=85% of the first 200 chars match after lowercasing/normalising whitespace), so the
    Call 2 retry loop can re-roll. Returns None when clean.
    """
    near = (part2.get("market_outlook_rationale") or "").strip()
    aco  = part2.get("asset_class_outlooks") or {}
    long_eq = ((aco.get("Equities") or {}).get("rationale") or "").strip()
    if not near or not long_eq:
        return None
    import re as _re
    _norm = lambda s: _re.sub(r"\s+", " ", s.lower())
    n, l = _norm(near)[:240], _norm(long_eq)[:240]
    if not n or not l:
        return None
    # Verbatim or substring containment is a hard fail.
    if n == l or n in l or l in n:
        return "Equities rationale duplicates market_outlook_rationale verbatim"
    # Token-set Jaccard overlap — catches single-word paraphrases that shift character
    # positions but preserve the underlying word bag (e.g. swapping "despite" for "while").
    _stop = {"the","a","an","and","or","of","to","in","on","as","is","are","was","were",
             "be","by","for","with","that","this","at","from","it","its"}
    tok_n = {w for w in _re.findall(r"[a-z0-9.%-]+", n) if w not in _stop and len(w) > 1}
    tok_l = {w for w in _re.findall(r"[a-z0-9.%-]+", l) if w not in _stop and len(w) > 1}
    if tok_n and tok_l:
        jaccard = len(tok_n & tok_l) / len(tok_n | tok_l)
        if jaccard >= 0.80:
            return f"Equities rationale {jaccard:.0%} token overlap with market_outlook_rationale"
    return None


# --- asset-class stance↔rationale coherence guard -----------------------------
# Regression 2026-06-17: asset_class_outlooks["Equities"] was labeled "Bearish" but its
# rationale OPENED "Forward earnings growth remains robust." — a bullish premise under a
# bearish label. The prompt forces a fundamental-driver opener (which tends to read bullish),
# so label and leading driver can drift apart. Flag a clear polarity clash so the Call-2 retry
# re-rolls. Fires only on UNAMBIGUOUS clashes (bearish/cautious label + overtly bullish opener,
# or bullish label + overtly bearish opener); neutral labels and hedged openers pass.
_ACO_BULLISH_DRIVER_RE = re.compile(
    r"\b(robust|strong(?:er|ly)?|resilient|solid|healthy|accelerat\w+|expand\w+|"
    r"improv\w+|upbeat|durable|booming|surg\w+|tailwind\w*|record(?:-?high)?)\b",
    re.IGNORECASE)
_ACO_BEARISH_DRIVER_RE = re.compile(
    r"\b(deceler\w+|slow(?:ing|down|er)?|weak\w+|contract\w+|compress\w+|retrench\w+|"
    r"deteriorat\w+|stretched|overvalued|headwind\w*|downgrad\w+|recession\w*|"
    r"margin\s+pressure|earnings\s+cut\w*|fragile)\b",
    re.IGNORECASE)


def _check_asset_class_stance_coherence(part2: dict) -> str | None:
    """Flag asset_class_outlooks rows whose rationale OPENS with a driver whose polarity
    contradicts the row's label. Returns the first violation (or None when clean)."""
    aco = part2.get("asset_class_outlooks")
    if not isinstance(aco, dict):
        return None
    for name, row in aco.items():
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip().lower()
        rationale = str(row.get("rationale") or "").strip()
        if not label or not rationale:
            continue
        opener = re.split(r"(?<=[.!?])\s+", rationale)[0]
        bull = bool(_ACO_BULLISH_DRIVER_RE.search(opener))
        bear = bool(_ACO_BEARISH_DRIVER_RE.search(opener))
        if bull == bear:
            continue  # neither, or both → ambiguous; do not enforce
        if label in ("bearish", "cautious", "negative") and bull:
            return (f"asset_class_outlooks[{name}]: {label} label opens with a bullish driver "
                    f"— \"{opener.strip()[:90]}\"")
        if label == "bullish" and bear:
            return (f"asset_class_outlooks[{name}]: bullish label opens with a bearish driver "
                    f"— \"{opener.strip()[:90]}\"")
    return None


# --- growth-multiple causal-inversion guard -----------------------------------
# Regression 2026-06-17: cross_asset_synthesis + equities_commentary blamed the tech selloff on
# FALLING oil / FALLING yields — "the peace deal removed the Hormuz premium, causing WTI to
# plunge ... and compressing tech multiples." Backwards: lower oil and lower yields RELIEVE
# growth multiples (lower discount rate, lower inflation impulse), they do not compress them.
# Only the inverted direction is wrong — "RISING yields compress multiples" is correct — so the
# guard is gated on the snapshot actually showing the tailwind (oil and/or 10Y DOWN). Left to the
# retry loop + prompt (no scrub): the inversion is usually embedded in an otherwise-factual
# sentence, and surgically rewriting causality is unsafe (same philosophy as the oil-causality
# editorial guard). Regeneration with the sharpened GROWTH-MULTIPLE DIRECTION rule is the fix.
_GM_COMPRESS_RE = re.compile(
    r"\b(?:compress\w*|pressur\w+|weigh\w+\s+on|weighed\s+on|drag\w+\s+(?:on|down)|"
    r"crush\w*|squeez\w*|depress\w+)\b[^.;]{0,40}\b(?:tech\w*|growth|equity|multiple)s?\b"
    r"|\b(?:tech\w*|growth|equity)\s+multiples?\b[^.;]{0,40}\b(?:compress\w*|pressur\w+|"
    r"weigh\w+|drag\w+|crush\w*|squeez\w*|depress\w+)\b",
    re.IGNORECASE)
# Two distinct inverted-driver families:
#  (a) falling oil / falling yields — gated on the snapshot, because the MIRROR
#      claim ("RISING yields compress multiples") is correct. Only enforce the
#      inversion on days the tailwind actually happened (oil and/or 10Y DOWN).
#  (b) de-escalation / inflation-premium REMOVAL (peace deal, ceasefire, "removal
#      of the Hormuz premium") — UNGATED, because removing an inflation impulse is
#      disinflationary: it lowers the discount rate and RELIEVES growth multiples
#      regardless of that day's tick. Blaming multiple COMPRESSION on it is always
#      backwards. Regression 2026-06-18: "the removal of the Hormuz disruption
#      premium compressed tech multiples" slipped through because oil/yields rose
#      that day, so the (a)-style snapshot gate suppressed the whole check.
_GM_OILYIELD_DOWN_RE = re.compile(
    r"\b(?:oil|crude|wti|brent|yields?|treasur\w+|rates?)\b[^.;]{0,40}"
    r"\b(?:fell|fall\w*|declin\w+|slid\w*|drop\w+|lower|plunge\w*|plummet\w*|sank|tumbl\w+|eas\w+|retreat\w*)\b"
    r"|\b(?:falling|lower|declining|easing|tumbling|plunging|sliding)\s+(?:oil|crude|wti|brent|yields?|rates?|treasur\w+)\b",
    re.IGNORECASE)
_GM_DEESCALATION_RE = re.compile(
    r"\bremov\w+\s+(?:the\s+)?[^.;]{0,30}\bpremium\b"
    r"|\b(?:peace\s+deal|truce|ceasefire|de-?escalat\w+)\b",
    re.IGNORECASE)
# Concessive framings flip the de-escalation from CAUSE to CONTRAST — e.g.
# "compressing multiples DESPITE the peace deal" is correct (the hawkish Fed is
# the cause; the deal is the foil). Don't flag those.
_GM_CONCESSIVE_RE = re.compile(
    r"\b(?:despite|even\s+(?:as|after|with|though)|notwithstanding|regardless\s+of|in\s+spite\s+of)\b",
    re.IGNORECASE)


def _check_growth_multiple_inversion(data: dict, snapshot: dict) -> list[str]:
    """Flag sentences that wrongly blame growth/tech multiple compression on a
    DISINFLATIONARY force. Two families: falling oil/yields (snapshot-gated) and
    de-escalation / inflation-premium removal (ungated — always inverted)."""
    snap = snapshot or {}
    wti = (snap.get("WTI Crude") or {}).get("pct_change")
    y10 = snap.get("10-Yr Yield") or {}
    bp = y10.get("bp_change")
    if bp is None:
        bp = y10.get("change")
    tailwind = (wti is not None and wti < -0.3) or (bp is not None and bp <= 0)
    violations: list[str] = []
    for field in ("equities_commentary", "cross_asset_synthesis",
                  "market_outlook_rationale", "fixed_income_commentary"):
        text = data.get(field)
        if not isinstance(text, str) or not text:
            continue
        for sent in re.split(r"(?<=[.!?])\s+", text):
            if not _GM_COMPRESS_RE.search(sent):
                continue
            # (a) falling oil/yields — only wrong on a day they actually fell.
            if tailwind and _GM_OILYIELD_DOWN_RE.search(sent):
                violations.append(
                    f"{field}: falling oil/yields wrongly compressing growth multiples "
                    f"— \"{sent.strip()[:90]}\"")
                break
            # (b) de-escalation / premium removal — always inverted, unless the
            #     phrase sits behind a concessive ("despite the deal").
            deesc = _GM_DEESCALATION_RE.search(sent)
            if deesc and not _GM_CONCESSIVE_RE.search(sent[:deesc.start()]):
                violations.append(
                    f"{field}: de-escalation/premium-removal wrongly compressing growth "
                    f"multiples (disinflation relieves them) — \"{sent.strip()[:90]}\"")
                break
    return violations[:4]


# --- risk-on / risk-off polarity guard ----------------------------------------
# Regression 2026-06-22: a clearly RISK-ON session (S&P +1.08%, equities rallying on
# Iran de-escalation, gold/oil falling as the geopolitical premium unwound) was
# repeatedly labeled "risk-off" — "peace talks provided a risk-off backdrop that
# SUPPORTED broad equities", "risk-off sentiment ... is the dominant cross-asset
# theme", and falling silver "reflecting broader risk-off sentiment". De-escalation
# that drains the safe-haven and oil-supply premium (gold/oil DOWN) while equities
# RISE is risk-ON, not risk-off. Three families of error:
#   (A) self-contradiction — "risk-off" in the same sentence as equities RISING (or
#       "risk-on" with equities FALLING). Always wrong, ungated.
#   (B) theme mismatch — "risk-off" called the dominant/prevailing theme on a day the
#       S&P ROSE (symmetric for "risk-on" on a down day). Snapshot-gated.
#   (C) falling safe-haven — a safe-haven (gold/silver/Treasuries/yen/VIX) FALLING in
#       the same sentence as "risk-off". Risk-off LIFTS safe-havens. Ungated.
# Retry-feedback only (no scrub): "risk-off" sits inside otherwise-factual prose and
# rewriting the regime word in place is unsafe; regeneration with the sharpened
# RISK-ON/RISK-OFF POLARITY rule is the fix (same approach as the growth-multiple guard).
_RISKOFF_RE = re.compile(r"\brisk[\s-]?off\b", re.IGNORECASE)
_RISKON_RE = re.compile(r"\brisk[\s-]?on\b", re.IGNORECASE)
_EQ_NOUN = (r"(?:equit\w+|stocks?|shares?|S&P(?:\s?500)?|Nasdaq|Dow|small[\s-]caps?|"
            r"broad\s+market|the\s+tape|risk\s+assets?)")
_EQ_UP = (r"(?:support\w*|lift\w*|boost\w*|buoy\w*|underpin\w*|fuel\w*|propel\w*|power\w*|"
          r"rallie?\w*|rally|rose|rising|gain\w*|advanc\w*|surg\w*|climb\w*|jump\w*|"
          r"higher|outperform\w*)")
_EQ_DOWN = (r"(?:weigh\w*|pressur\w*|drag\w*|sank|sold\s+off|sell[\s-]?off|fell|declin\w*|"
            r"slump\w*|slid\w*|drop\w+|tumbl\w*|sink\w*|retreat\w*|underperform\w*|lower)")
# Verb must sit NEAR its equity noun (within ~30 chars, either order) so a coherent
# divergence sentence ("the S&P 500 fell and Treasuries rallied") does not trip on the
# unrelated verb attached to the OTHER asset.
_EQ_UP_ASSOC_RE = re.compile(
    rf"\b{_EQ_NOUN}\b[^.;]{{0,30}}\b{_EQ_UP}\b|\b{_EQ_UP}\b[^.;]{{0,30}}\b{_EQ_NOUN}\b", re.IGNORECASE)
_EQ_DOWN_ASSOC_RE = re.compile(
    rf"\b{_EQ_NOUN}\b[^.;]{{0,30}}\b{_EQ_DOWN}\b|\b{_EQ_DOWN}\b[^.;]{{0,30}}\b{_EQ_NOUN}\b", re.IGNORECASE)
_SAFE_HAVEN = (r"(?:gold|bullion|silver|treasur\w+|sovereign\s+bonds?|the\s+yen|japanese\s+yen|"
               r"swiss\s+franc|VIX|safe[\s-]haven\w*)")
_DOWN_WORD = (r"(?:fell|fall\w*|declin\w+|slid\w*|slipp\w*|slip|drop\w+|lower|plunge\w*|plummet\w*|"
              r"sank|tumbl\w+|eas\w+|retreat\w*|weaken\w*|softer|down)")
_FALLING_WORD = r"(?:falling|lower|sliding|tumbling|plunging|sinking|weaker|declining)"
# Falling-safe-haven: the down word must sit close to the safe-haven noun, OR a falling
# adjective directly precedes it — again to avoid catching a down verb from another asset.
_SAFE_HAVEN_FALLING_RE = re.compile(
    rf"\b{_SAFE_HAVEN}\b[^.;,]{{0,25}}\b{_DOWN_WORD}\b|\b{_FALLING_WORD}\s+{_SAFE_HAVEN}\b", re.IGNORECASE)
_THEME_MARKER_RE = re.compile(
    r"\b(?:dominant|dominat\w*|prevail\w*|overarching|defining|primary|principal)\b"
    # noun may be PLURAL ("the dominant drivers") — the singular-only `\bdriver\b` missed the
    # 2026-06-23 synthesis line "...are the dominant drivers" and let a risk-on label survive.
    r"[^.;]{0,40}\b(?:theme|driver|narrative|sentiment|backdrop|tone|mood|story|force)s?\b"
    r"|\bcross[\s-]asset\s+(?:theme|driver|narrative)s?\b",
    re.IGNORECASE)
# A DIRECT regime assertion ("risk-on environment", "risk-off regime") — a stronger claim than
# a passing mention. Family D flags it when it contradicts the session's S&P sign, gated only on
# that sign (not on a theme-marker noun) and NOT excused by the broad concessive skip — a trailing
# "...despite <other thing>" must not license a wrong regime label (2026-06-23 commodities line).
_RISK_ENV_RE = re.compile(
    r"\brisk[\s-]?(on|off)\s+(?:environment|regime|backdrop|conditions?|tone|mood|"
    r"sentiment|footing|tape|posture)\b",
    re.IGNORECASE)
# The FADING carve-out, isolated from _RISK_SKIP_RE: a regime described as DECREASING
# ("risk-off environment faded") is coherent even against the session sign.
_RISK_FADING_RE = re.compile(
    r"risk[\s-]?o(?:ff|n)\s+(?:\w+\s+){0,3}(?:fad\w+|eas\w+|ebb\w+|reced\w+|unwind\w+|abat\w+|wan\w+|diminish\w+)"
    r"|(?:fad\w+|eas\w+|ebb\w+|reced\w+|unwind\w+|abat\w+|wan\w+|diminish\w+)\s+(?:the\s+)?risk[\s-]?o(?:ff|n)",
    re.IGNORECASE)
# Skip sentences where the risk regime is framed as a CONTRAST (concessive) or as
# DECREASING (fading/easing/unwinding) — "equities shrugged off risk-off positioning to
# rally" and "Treasuries fell as risk-off faded" are both coherent, not inversions.
_RISK_SKIP_RE = re.compile(
    r"\b(?:despite|even\s+(?:as|though|after|with)|notwithstanding|regardless|"
    r"in\s+spite\s+of|shrug\w+|ignor\w+|brush\w*\s+aside|defy\w*|defied)\b"
    r"|\blook\w*\s+past\b"
    r"|risk[\s-]?o(?:ff|n)\s+(?:\w+\s+){0,2}(?:fad\w+|eas\w+|ebb\w+|reced\w+|unwind\w+|abat\w+|wan\w+|diminish\w+)"
    r"|(?:fad\w+|eas\w+|ebb\w+|reced\w+|unwind\w+|abat\w+|wan\w+|diminish\w+)\s+(?:the\s+)?risk[\s-]?o(?:ff|n)",
    re.IGNORECASE)


def _check_risk_polarity_inversion(data: dict, snapshot: dict) -> list[str]:
    """Flag prose that mislabels the session's risk regime. Three families A/B/C
    (see comment above). Scans str AND list[str] commentary fields. Returns up to 4
    violation strings (empty when clean). Retry-feedback only — never scrubs.

    Family A is session-gated: a "risk-off + equities-up" pairing only fires when the
    day was NOT itself risk-off (and the mirror for risk-on), so a genuine divergence
    on a down day ("risk-off dominated as the S&P fell while havens caught a bid") is
    left alone. Families B (theme-vs-tape) gate on the S&P sign; C (falling safe-haven
    called risk-off) is always wrong, hence ungated."""
    snap = snapshot or {}
    spx = (snap.get("S&P 500") or {}).get("pct_change")
    risk_on_session = spx is not None and spx > 0.3
    risk_off_session = spx is not None and spx < -0.3
    fields = ("equities_commentary", "commodities_commentary", "fixed_income_commentary",
              "currencies_commentary", "economics_commentary", "cross_asset_synthesis",
              "market_outlook_rationale", "international_section", "session_recap")
    scan_items: list[tuple[str, object]] = [(f, data.get(f)) for f in fields]
    # The Long-Term Fundamental Outlook table prose lives in the NESTED
    # data["asset_class_outlooks"][name]["rationale"], not a flat field — so the scan above
    # never reached it. Regression 2026-06-24: the Commodities row asserted a "risk-on
    # environment" on a risk-OFF day while every flat field was clean. Pull each rationale in.
    aco = data.get("asset_class_outlooks")
    if isinstance(aco, dict):
        for _name, _row in aco.items():
            if isinstance(_row, dict):
                scan_items.append((f"asset_class_outlooks[{_name}]", _row.get("rationale")))
    violations: list[str] = []
    for field, val in scan_items:
        texts = val if isinstance(val, list) else [val]
        for text in texts:
            if not isinstance(text, str) or not text:
                continue
            for sent in re.split(r"(?<=[.!?])\s+", text):
                has_off = bool(_RISKOFF_RE.search(sent))
                has_on = bool(_RISKON_RE.search(sent))
                if not has_off and not has_on:
                    continue
                # (D) direct "risk-on/off environment|regime|..." assertion vs the session sign.
                # Checked BEFORE the broad concessive skip: only the explicit FADING carve-out
                # excuses a regime label, so a trailing "despite <X>" cannot mask a wrong one.
                env_m = _RISK_ENV_RE.search(sent)
                if env_m and not _RISK_FADING_RE.search(sent):
                    regime = env_m.group(1).lower()
                    if regime == "on" and risk_off_session:
                        violations.append(f"{field}: a 'risk-on environment/regime' asserted on a "
                                          f"risk-OFF day (S&P down) — \"{sent.strip()[:90]}\"")
                        break
                    if regime == "off" and risk_on_session:
                        violations.append(f"{field}: a 'risk-off environment/regime' asserted on a "
                                          f"risk-ON day (S&P up) — \"{sent.strip()[:90]}\"")
                        break
                    # Flat/mixed tape: the rules say call it a "mixed session", not assert a hard
                    # risk regime. 2026-07-02: currencies asserted a "risk-off regime" on a -0.22%
                    # S&P while the report's own spotlight framed a risk-ON rotation — the label
                    # contradicts the session's own characterization. Flag either regime on a flat day.
                    # EXEMPT international_section: it describes FOREIGN indices with their own
                    # direction, so "global risk-off" when Europe/Asia fell is legitimate even when
                    # the US S&P was flat (2026-07-02: Europe -0.72%, Nikkei -2.47%).
                    if spx is not None and abs(spx) < 0.3 and field != "international_section":
                        violations.append(f"{field}: a hard 'risk-{regime} environment/regime' asserted on a "
                                          f"FLAT/mixed tape (S&P {spx:+.2f}% — call it a mixed session, not a "
                                          f"regime) — \"{sent.strip()[:90]}\"")
                        break
                if _RISK_SKIP_RE.search(sent):
                    continue  # concessive / regime fading — coherent, not an inversion
                # (A) self-contradiction — risk regime vs nearby equity direction
                if has_off and not risk_off_session and _EQ_UP_ASSOC_RE.search(sent):
                    violations.append(f"{field}: 'risk-off' paired with RISING equities "
                                      f"— \"{sent.strip()[:90]}\"")
                    break
                if has_on and not risk_on_session and _EQ_DOWN_ASSOC_RE.search(sent):
                    violations.append(f"{field}: 'risk-on' paired with FALLING equities "
                                      f"— \"{sent.strip()[:90]}\"")
                    break
                # (C) falling safe-haven labeled risk-off (always inverted)
                if has_off and _SAFE_HAVEN_FALLING_RE.search(sent):
                    violations.append(f"{field}: a FALLING safe-haven labeled 'risk-off' "
                                      f"(risk-off lifts safe-havens) — \"{sent.strip()[:90]}\"")
                    break
                # (B) theme mismatch vs the session's S&P direction
                if _THEME_MARKER_RE.search(sent):
                    if risk_on_session and has_off:
                        violations.append(f"{field}: 'risk-off' called the dominant theme on a "
                                          f"risk-ON day (S&P up) — \"{sent.strip()[:90]}\"")
                        break
                    if risk_off_session and has_on:
                        violations.append(f"{field}: 'risk-on' called the dominant theme on a "
                                          f"risk-OFF day (S&P down) — \"{sent.strip()[:90]}\"")
                        break
        if len(violations) >= 4:
            break
    return violations[:4]


# --- flat-tape risk-regime scrub (forces what the retry-check only nudges) -----
# _check_risk_polarity_inversion flags a hard "risk-on/off <regime>" label on a flat tape but
# only feeds it back as a retry hint; when the model is stubborn (2026-07-02: "broader risk-off
# sentiment" in the Commodities outlook survived all 4 retries) it ships anyway. On a flat tape
# (|S&P| < 0.3%) the session is a "mixed" one — rewrite the hard label deterministically.
# international_section is exempt (foreign markets have their own direction).
_RISK_REGIME_NOUN_RE = re.compile(
    r"\brisk-(on|off)\s+(regime|environment|sentiment|backdrop|tone|mood|mode|conditions?|theme)\b",
    re.IGNORECASE)


def _scrub_flat_tape_risk_regime(data: dict, snapshot: dict | None = None) -> int:
    """On a flat tape rewrite a hard 'risk-on/off <noun>' label to 'mixed'. Skips fading
    contexts and international_section. Mutates data; returns fix count."""
    snap = snapshot or {}
    spx = (snap.get("S&P 500") or {}).get("pct_change")
    if spx is None or abs(spx) >= 0.3:
        return 0

    def _repl(m):
        noun = m.group(2).lower()
        rep = "mixed session" if noun == "regime" else f"mixed {noun}"
        return rep[0].upper() + rep[1:] if m.group(0)[:1].isupper() else rep

    def _fix(text: str) -> tuple[str, int]:
        n = 0
        out = []
        for sent in re.split(r"(?<=[.!?])\s+", text):
            if _RISK_REGIME_NOUN_RE.search(sent) and not _RISK_FADING_RE.search(sent):
                sent, k = _RISK_REGIME_NOUN_RE.subn(_repl, sent)
                n += k
            out.append(sent)
        return " ".join(out), n

    fixes = 0
    for field in ("equities_commentary", "commodities_commentary", "fixed_income_commentary",
                  "currencies_commentary", "economics_commentary", "cross_asset_synthesis",
                  "market_outlook_rationale", "session_recap"):
        v = data.get(field)
        if isinstance(v, str) and v:
            nv, k = _fix(v)
            if k:
                data[field] = nv
                fixes += k
        elif isinstance(v, list):
            new, ch = [], 0
            for it in v:
                if isinstance(it, str):
                    ni, k = _fix(it)
                    new.append(ni)
                    ch += k
                else:
                    new.append(it)
            if ch:
                data[field] = new
                fixes += ch
    aco = data.get("asset_class_outlooks")
    if isinstance(aco, dict):
        for av in aco.values():
            if isinstance(av, dict) and isinstance(av.get("rationale"), str):
                nv, k = _fix(av["rationale"])
                if k:
                    av["rationale"] = nv
                    fixes += k
    return fixes


# --- peace/ceasefire narrative-coherence guard --------------------------------
# 2026-07-01: the report framed the SAME US-Iran situation two opposite ways at once —
# "peace deal hopes lifted markets" (recap/synthesis/spotlight) beside "fading hopes for a
# peace deal fuelled inflation worries" (bullet/gold/economics). The WRITING_RULES
# NARRATIVE-COHERENCE clause is meant to prevent this but the model leaked it. Detect a
# report that contains BOTH a RISING-peace framing and a FADING-peace framing for the same
# de-escalation storyline and force a regeneration (retry-feedback, like the risk-polarity
# guard — rewriting the semantics in place is unsafe). Conservative: a sentence must pair a
# peace/ceasefire NOUN with a polarity verb, and a sentence carrying BOTH polarities (e.g.
# "fading peace hopes lifted gold") is skipped as ambiguous.
_PEACE_NOUN_RE = re.compile(
    r"\b(?:peace\s+deal|peace\s+talks?|peace\s+hopes?|cease[\s-]?fire|truce|"
    r"de[\s-]?escalation|diplomatic\s+(?:breakthrough|progress))\b", re.IGNORECASE)
_PEACE_FADING_RE = re.compile(
    r"\b(?:fad\w+|reced\w+|receded|dwindl\w+|dimm\w+|dim|evaporat\w+|collaps\w+|"
    r"unravel\w+|denied|stall\w+|faltered|crumbl\w+|off\s+the\s+table)\b", re.IGNORECASE)
# Only UNAMBIGUOUSLY-positive framing counts as "rising". Neutral words that co-occur with
# a fading storyline ("fading HOPES", "FUELLED inflation worries") are excluded so a fading
# sentence isn't misread as carrying both polarities.
_PEACE_RISING_RE = re.compile(
    r"\b(?:optimis\w+|lift\w+|lifted|drove|driven|buoy\w+|rally\w+|rallied|rising|"
    r"grow\w+|renew\w+|revive\w+|gain\w+\s+traction)\b", re.IGNORECASE)


def _check_peace_narrative_coherence(data: dict) -> list[str]:
    """Return a violation when the report frames the peace/ceasefire storyline as BOTH rising
    and fading. Empty list = coherent (or the theme is absent)."""
    fading_hit = rising_hit = None
    for field in _ALL_PROSE_FIELDS:
        v = data.get(field)
        texts = []
        if isinstance(v, str) and v:
            texts = re.split(r"(?<=[.!?])\s+", v)
        elif isinstance(v, list):
            texts = [s for s in v if isinstance(s, str)]
        for sent in texts:
            if not _PEACE_NOUN_RE.search(sent):
                continue
            fad = bool(_PEACE_FADING_RE.search(sent))
            ris = bool(_PEACE_RISING_RE.search(sent))
            if fad == ris:
                continue  # neither, or ambiguous (both) — not a clean polarity signal
            if fad and fading_hit is None:
                fading_hit = f"{field}: \"{sent.strip()[:90]}\""
            elif ris and rising_hit is None:
                rising_hit = f"{field}: \"{sent.strip()[:90]}\""
    if fading_hit and rising_hit:
        return [f"peace/ceasefire framed both fading [{fading_hit}] and rising [{rising_hit}]"]
    return []


def _check_synthesis_yield_direction(part4: dict, snapshot: dict) -> str | None:
    """Detect 10-year yield direction contradiction in cross_asset_synthesis.

    The existing `_check_numeric_consistency` validator scans
    equities/commodities/currencies/fixed_income for PERCENT-format sign mismatches
    but does NOT scan cross_asset_synthesis, and does not understand BASIS-POINT
    (`bp`) phrasing. Real-world failure observed 2026-05-28: snapshot 10Y bp_change
    was -2.0 (yield FELL) yet synthesis claimed "the 10-year yield's 2 bp rise to
    4.48%" — a hard factual contradiction with the pre-market bullets and fixed
    income commentary on the same page.

    Heuristic: scan synthesis text for any sentence mentioning 10-year/10-yr yield
    that also names a direction verb. Compare verb's implied sign against the
    snapshot's 10-Yr Yield bp_change (or change). Returns a single violation
    string (or None when clean). Tolerant of phrasings with bp OR percent OR no
    unit — only the direction word matters.
    """
    syn = (part4.get("cross_asset_synthesis") or "").strip()
    if not syn:
        return None
    snap10 = (snapshot or {}).get("10-Yr Yield") or {}
    truth = snap10.get("bp_change")
    if truth is None:
        truth = snap10.get("change")
    if truth is None or abs(truth) < 0.5:
        # Near-zero move (< 0.5 bp): the direction call is too noisy to enforce.
        return None
    truth_up = truth > 0

    import re as _re
    _UP_WORDS   = {"rose", "rise", "rises", "rising", "climbed", "climb", "jumped",
                   "jump", "ticked up", "surged", "surge", "advanced", "advance",
                   "gained", "gain", "higher", "increase", "increased", "increasing"}
    _DOWN_WORDS = {"fell", "fall", "falls", "falling", "dropped", "drop", "slipped",
                   "slip", "ticked down", "tumbled", "tumble", "declined", "decline",
                   "slid", "slide", "lower", "decrease", "decreased", "decreasing",
                   "eased", "ease", "retreated", "retreat"}
    _YIELD_KW   = ("10-year", "10-yr", "ten-year", "10y yield", "10-year yield",
                   "10-yr yield", "10-year treasury", "ten year yield")

    # Operate on sentences so a single piece can match yield + direction in the same clause.
    for sent in _re.split(r"(?<=[.!?])\s+", syn):
        low = sent.lower()
        if not any(kw in low for kw in _YIELD_KW):
            continue
        words = set(_re.findall(r"[a-z-]+", low))
        cited_up = bool(words & _UP_WORDS)
        cited_dn = bool(words & _DOWN_WORDS)
        # Skip sentences that cite both (e.g. "fell from a 10-yr high") — too ambiguous.
        if cited_up == cited_dn:
            continue
        if cited_up != truth_up:
            actual = "rose" if truth_up else "fell"
            cited  = "rose" if cited_up else "fell"
            return (f"cross_asset_synthesis says 10Y yield {cited} but snapshot "
                    f"bp_change={truth:+.1f} (actually {actual}): \"{sent.strip()[:120]}\"")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Post-process scrub: kill "fell -5.55%" double-negative artefacts where a
# directional verb is paired with a redundant minus sign on the percent. The
# LLM occasionally emits both a verb-of-direction and a signed percent, which
# reads as a double negation. Idempotent — fixes only the verb-immediately-
# adjacent case; standalone signed percents (e.g. "the close was -5.55%") are
# left untouched. Applies in scrub_banned_phrases for all narrative fields.
# ─────────────────────────────────────────────────────────────────────────────
_DOUBLE_NEG_RE = re.compile(
    r"\b(fell|fall|falls|dropped|drop|drops|declined|decline|declines|slid|slipped|"
    r"slips|slipping|tumbled|tumbles|plunged|plunges|retreated|sank|sinks|lost|"
    r"shed|sheds)\b(\s+(?:by\s+|to\s+)?)-(\d)",
    re.IGNORECASE,
)
_DOUBLE_POS_RE = re.compile(
    r"\b(rose|rise|rises|climbed|climbs|jumped|jumps|gained|gains|surged|surges|"
    r"advanced|advances|rallied|rallies|soared|soars|ticked\s+up)\b(\s+(?:by\s+|to\s+)?)"
    r"\+(\d)",
    re.IGNORECASE,
)


def _strip_double_signs(text: str) -> str:
    """Strip redundant +/- after directional verbs (e.g. 'fell -5.55%' → 'fell 5.55%').

    Only matches when the verb is IMMEDIATELY followed by the signed number (optional
    'by'/'to' filler permitted). Standalone signed percents in non-verb contexts
    (e.g. 'closed at -5.55%') are left untouched.
    """
    if not isinstance(text, str) or not text:
        return text
    text = _DOUBLE_NEG_RE.sub(r"\1\g<2>\3", text)
    text = _DOUBLE_POS_RE.sub(r"\1\g<2>\3", text)
    return text


def _check_numeric_consistency(data: dict, snapshot: dict) -> list[str]:
    """Compare sign/magnitude of LLM narrative numbers against the market snapshot.

    Returns a list of violation strings (empty = clean). Checks the first percent
    figure in equity/commodities/currencies commentary against pct_change in the
    snapshot (tolerance: 0.5pp; sign mismatch always fails). Also checks
    direction-word contradictions and pre_market_bullets sign consistency.
    """
    import re
    PCT_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*%")

    def _first_pct(text: str) -> float | None:
        m = PCT_RE.search(text or "")
        return float(m.group(1)) if m else None

    def _pct_after_keyword(text: str, keyword: str) -> float | None:
        """Find the first % figure at or after `keyword` in text."""
        lower = (text or "").lower()
        idx = lower.find(keyword.lower())
        if idx == -1:
            return None
        m = PCT_RE.search(text, idx)
        return float(m.group(1)) if m else None

    # Magnitude + sign check: (narrative_key, snap_key, keyword_or_None).
    # fixed_income excluded — yield level (e.g. "4.39%") ≠ yield pct_change.
    # keyword_or_None: if set, find the first % AFTER that keyword in the prose
    # (needed for sections where multiple assets appear, e.g. commodities).
    checks = [
        ("equities_commentary",    "S&P 500",            None),
        ("commodities_commentary", "WTI Crude",           None),
        ("commodities_commentary", "Gold",                "gold"),
        ("currencies_commentary",  "U.S. Dollar (DXY)",   None),
    ]
    violations = []
    for narrative_key, snap_key, kw in checks:
        snap = (snapshot or {}).get(snap_key) or {}
        truth_pct = snap.get("pct_change")
        if truth_pct is None:
            continue
        prose = data.get(narrative_key, "")
        prose_str = prose if isinstance(prose, str) else " ".join(prose or [])
        if abs(truth_pct) < 0.02:
            # Near-zero: skip magnitude/sign check, but flag strong directional language
            # in equities_commentary — catches "rallied over 1%" on flat-close days.
            if narrative_key == "equities_commentary":
                _STRONG_MOVES = {
                    "rallied", "surged", "soared", "jumped", "skyrocketed",
                    "plunged", "collapsed", "tumbled", "sold off sharply",
                    "rose sharply", "fell sharply",
                }
                cited_strong = [w for w in _STRONG_MOVES if w in prose_str.lower()]
                if cited_strong:
                    violations.append(
                        f"{snap_key}: snapshot {truth_pct:+.2f}% (essentially flat) "
                        f"but equities_commentary uses strong directional language: {cited_strong}"
                    )
            continue
        cited = _first_pct(prose_str) if kw is None else _pct_after_keyword(prose_str, kw)
        if cited is None:
            continue
        if (truth_pct >= 0) != (cited >= 0):
            violations.append(
                f"{snap_key}: snapshot {truth_pct:+.2f}%, narrative cited {cited:+.2f}% (sign mismatch)"
            )
        elif abs(truth_pct - cited) > 0.5:
            violations.append(
                f"{snap_key}: snapshot {truth_pct:+.2f}%, narrative cited {cited:+.2f}% (magnitude > 0.5pp)"
            )

    # Direction-word check: strong directional words that contradict the snapshot sign.
    # Scoped to the ASSET'S OWN SENTENCE (must share a clause with an asset keyword) so a
    # commodities field that says "gold plunged" on a down-gold day is not mis-flagged as a
    # WTI contradiction, and so the validator only demands what the scoped _correct_direction_words
    # corrector can actually deliver. 2026-07-09: WTI +4.37% on the Iran spike but the LLM's
    # crude language ("selloff"/"collapse") kept tripping the old field-global word-set check —
    # words the flip map didn't cover and that weren't adjacent to a "crude" keyword — forcing a
    # deterministic fallback and a blocked send.
    _BEARISH_STRONG = {"selloff", "sell-off", "selling", "plunged", "plunge", "plunging",
                       "collapsed", "collapse", "collapsing", "tumbled", "tumble", "tumbling"}
    _BULLISH_STRONG = {"surged", "surge", "surging", "soared", "soar", "soaring",
                       "skyrocketed", "skyrocketing"}
    _FIELD_ASSET = {
        "equities_commentary":     "S&P 500",
        "commodities_commentary":  "WTI Crude",
        "currencies_commentary":   "U.S. Dollar (DXY)",
        "fixed_income_commentary": "10-Yr Yield",
    }
    # Substrings that anchor a sentence to a given asset (case-insensitive).
    _ASSET_ANCHOR = {
        "S&P 500":            ("s&p", "500", "equit", "stock", "index", "benchmark"),
        "WTI Crude":          ("wti", "crude", "oil"),
        "U.S. Dollar (DXY)":  ("dollar", "dxy", "greenback"),
        "10-Yr Yield":        ("10-year", "10-yr", "10 year", "treasur", "yield", "note", "bond"),
    }
    # Synthesis fields discuss several assets at once, so scan them against EVERY asset
    # (still sentence-scoped). 2026-07-09: the shipped "Market Synthesis" said "tumbling WTI
    # crude (+4.37%)" — a pre-modifier gerund in market_outlook_rationale, a field the old
    # check never scanned, so nothing flagged it.
    _SYNTH_FIELDS = ("cross_asset_synthesis", "market_outlook_rationale")

    def _strong_word_hit(prose_str: str, snap_key: str) -> bool:
        truth = ((snapshot or {}).get(snap_key) or {}).get("pct_change")
        if truth is None:
            return False
        wrong = _BEARISH_STRONG if truth > 0.3 else (_BULLISH_STRONG if truth < -0.3 else set())
        if not wrong:
            return False
        anchors = _ASSET_ANCHOR.get(snap_key, ())
        for sent in re.split(r"(?<=[.!?])\s+", prose_str):
            sl = sent.lower()
            if anchors and not any(a in sl for a in anchors):
                continue
            if {w.strip(".,;:!?\"'()[]") for w in sl.split()} & wrong:
                return True
        return False

    def _flag(snap_key: str) -> None:
        truth = ((snapshot or {}).get(snap_key) or {}).get("pct_change")
        polarity = "positive" if truth > 0 else "negative"
        kind = "bearish" if truth > 0 else "bullish"
        msg = f"{snap_key}: snapshot {truth:+.2f}% ({polarity}) but narrative uses strongly {kind} language"
        if msg not in violations:
            violations.append(msg)

    for narrative_key, snap_key in _FIELD_ASSET.items():
        prose = data.get(narrative_key, "")
        prose_str = prose if isinstance(prose, str) else " ".join(prose or [])
        if _strong_word_hit(prose_str, snap_key):
            _flag(snap_key)

    for narrative_key in _SYNTH_FIELDS:
        prose = data.get(narrative_key, "")
        prose_str = prose if isinstance(prose, str) else " ".join(prose or [])
        if not prose_str:
            continue
        for snap_key in _ASSET_ANCHOR:
            if _strong_word_hit(prose_str, snap_key):
                _flag(snap_key)

    # pre_market_bullets: each bullet that names a known asset and cites a % must match sign.
    _ASSET_KW = {
        "s&p": "S&P 500",
        "nasdaq": "Nasdaq 100",
        "wti": "WTI Crude",
        "crude": "WTI Crude",
        "gold": "Gold",
        "dxy": "U.S. Dollar (DXY)",
    }
    bullets = data.get("pre_market_bullets", [])
    if isinstance(bullets, list):
        for bullet in bullets:
            btext = str(bullet).lower()
            m = PCT_RE.search(btext)
            if not m:
                continue
            cited = float(m.group(1))
            for kw, snap_key in _ASSET_KW.items():
                if kw in btext:
                    snap = (snapshot or {}).get(snap_key) or {}
                    truth_pct = snap.get("pct_change")
                    if truth_pct is not None:
                        if (truth_pct >= 0) != (cited >= 0):
                            violations.append(
                                f"pre_market_bullets: mentions {snap_key} {cited:+.2f}% but snapshot is {truth_pct:+.2f}% (sign mismatch)"
                            )
                        elif abs(truth_pct) >= 0.02 and abs(truth_pct - cited) > 0.5:
                            violations.append(
                                f"pre_market_bullets: mentions {snap_key} {cited:+.2f}% but snapshot is {truth_pct:+.2f}% (magnitude > 0.5pp)"
                            )
                    break

    return violations


# Verbs that imply direction. If the cited percent has the wrong sign, flip
# the verb in the same clause so the rewritten prose stays grammatical.
_VERB_FLIP_TO_DOWN = {
    "rose": "fell",
    "gained": "slid",
    "climbed": "declined",
    "advanced": "retreated",
    "rallied": "sold off",
    "surged": "tumbled",
    "soared": "plunged",
    "jumped": "dropped",
}
_VERB_FLIP_TO_UP = {v: k for k, v in _VERB_FLIP_TO_DOWN.items()}


def _rewrite_first_pct_sign(text: str, truth_pct: float) -> tuple[str, bool]:
    """Rewrite the first percent figure in `text` to match `truth_pct`'s sign.
    Also flips a nearby preceding directional verb when present.
    Idempotent: if signs already agree, returns text unchanged.
    Returns (new_text, changed).
    """
    if not isinstance(text, str) or not text:
        return text, False
    pct_re = re.compile(r"([-+]?)(\d+(?:\.\d+)?)\s*%")
    m = pct_re.search(text)
    if not m:
        return text, False
    sign_str, mag_str = m.group(1), m.group(2)
    cited = float((sign_str or "") + mag_str)
    if (cited >= 0) == (truth_pct >= 0):
        return text, False  # already aligned

    # Look for a nearby preceding directional verb to flip.
    flip_map = _VERB_FLIP_TO_DOWN if truth_pct < 0 else _VERB_FLIP_TO_UP
    verb_re = re.compile(
        r"\b(" + "|".join(re.escape(v) for v in flip_map.keys()) + r")\b",
        re.IGNORECASE,
    )
    window_start = max(0, m.start() - 120)
    window = text[window_start:m.start()]
    verb_match = None
    matches = list(verb_re.finditer(window))
    if matches:
        verb_match = matches[-1]

    # Positive truth with verb flip: bare magnitude is unambiguous (no leading sign = positive).
    # Negative truth: always emit explicit "-" so the validator can read the sign from the number
    # itself, regardless of whether a verb flip also occurs.
    if verb_match is not None and truth_pct >= 0:
        new_pct = f"{abs(truth_pct):.2f}%"
    else:
        new_sign = "-" if truth_pct < 0 else "+"
        new_pct = f"{new_sign}{abs(truth_pct):.2f}%"
    new_text = text[:m.start()] + new_pct + text[m.end():]

    if verb_match is not None:
        verb_text = verb_match.group(1)
        flipped = flip_map[verb_text.lower()]
        if verb_text[0].isupper():
            flipped = flipped[0].upper() + flipped[1:]
        abs_start = window_start + verb_match.start()
        abs_end = window_start + verb_match.end()
        new_text = new_text[:abs_start] + flipped + new_text[abs_end:]
    return new_text, True


def _rewrite_pct_sign_after_keyword(text: str, keyword: str, truth_pct: float) -> tuple[str, bool]:
    """Rewrite the first percent figure AFTER `keyword` in `text` to match `truth_pct`'s sign.
    Slices from the keyword position and delegates to _rewrite_first_pct_sign, then stitches back.
    Idempotent. Returns (new_text, changed).
    """
    if not isinstance(text, str) or not text:
        return text, False
    idx = text.lower().find(keyword.lower())
    if idx == -1:
        return text, False
    new_suffix, changed = _rewrite_first_pct_sign(text[idx:], truth_pct)
    if not changed:
        return text, False
    return text[:idx] + new_suffix, True


def _rewrite_first_pct_magnitude(text: str, truth_pct: float) -> tuple[str, bool]:
    """Rewrite the first percent figure in `text` to match `truth_pct`'s magnitude.
    Only fires when signs already agree — sign mismatches are left to _rewrite_first_pct_sign.
    Idempotent: returns text unchanged if within 0.5pp or signs disagree.
    Returns (new_text, changed).
    """
    if not isinstance(text, str) or not text:
        return text, False
    pct_re = re.compile(r"([-+]?)(\d+(?:\.\d+)?)\s*%")
    m = pct_re.search(text)
    if not m:
        return text, False
    sign_str, mag_str = m.group(1), m.group(2)
    cited = float((sign_str or "") + mag_str)
    if (cited >= 0) != (truth_pct >= 0):
        return text, False  # sign mismatch — handled by _rewrite_first_pct_sign
    if abs(truth_pct - cited) <= 0.5:
        return text, False  # within tolerance
    new_pct = f"{sign_str}{abs(truth_pct):.2f}%"
    return text[:m.start()] + new_pct + text[m.end():], True


def _rewrite_pct_magnitude_after_keyword(text: str, keyword: str, truth_pct: float) -> tuple[str, bool]:
    """Rewrite the first percent figure AFTER `keyword` in `text` to match `truth_pct`'s magnitude.
    Slices from the keyword position and delegates to _rewrite_first_pct_magnitude.
    Idempotent. Returns (new_text, changed).
    """
    if not isinstance(text, str) or not text:
        return text, False
    idx = text.lower().find(keyword.lower())
    if idx == -1:
        return text, False
    new_suffix, changed = _rewrite_first_pct_magnitude(text[idx:], truth_pct)
    if not changed:
        return text, False
    return text[:idx] + new_suffix, True


def _correct_sign_mismatches(data: dict, snapshot: dict) -> int:
    """Rewrite sign-flipped percents in narrative fields to match snapshot.
    Mutates data in place. Returns number of corrections applied.
    Idempotent — safe to call multiple times.
    """
    if not snapshot:
        return 0
    fixes = 0

    section_checks = [
        ("equities_commentary",    "S&P 500",            None),
        ("commodities_commentary", "WTI Crude",          "wti"),
        ("commodities_commentary", "Gold",               "gold"),
        ("currencies_commentary",  "U.S. Dollar (DXY)",  None),
    ]
    for narrative_key, snap_key, kw in section_checks:
        truth_pct = (snapshot.get(snap_key) or {}).get("pct_change")
        if truth_pct is None or abs(truth_pct) < 0.02:
            continue
        prose = data.get(narrative_key)
        if not isinstance(prose, str):
            continue
        if kw is None:
            new_prose, changed = _rewrite_first_pct_sign(prose, truth_pct)
        else:
            new_prose, changed = _rewrite_pct_sign_after_keyword(prose, kw, truth_pct)
        if changed:
            data[narrative_key] = new_prose
            fixes += 1

    asset_kw = {
        "s&p":    "S&P 500",
        "nasdaq": "Nasdaq 100",
        "wti":    "WTI Crude",
        "crude":  "WTI Crude",
        "gold":   "Gold",
        "dxy":    "U.S. Dollar (DXY)",
    }
    bullets = data.get("pre_market_bullets")
    if isinstance(bullets, list):
        new_bullets = []
        for bullet in bullets:
            if not isinstance(bullet, str):
                new_bullets.append(bullet)
                continue
            btext_lower = bullet.lower()
            corrected = bullet
            for kw, snap_key in asset_kw.items():
                if kw in btext_lower:
                    truth_pct = (snapshot.get(snap_key) or {}).get("pct_change")
                    if truth_pct is None or abs(truth_pct) < 0.02:
                        break
                    corrected, changed = _rewrite_first_pct_sign(corrected, truth_pct)
                    if changed:
                        fixes += 1
                    break
            new_bullets.append(corrected)
        data["pre_market_bullets"] = new_bullets

    return fixes


def _correct_magnitude_mismatches(data: dict, snapshot: dict) -> int:
    """Rewrite magnitude-divergent percents in narrative fields to match snapshot.
    Must run AFTER _correct_sign_mismatches — only fires when signs already agree.
    Mutates data in place. Returns number of corrections applied. Idempotent.
    """
    if not snapshot:
        return 0
    fixes = 0

    section_checks = [
        ("equities_commentary",    "S&P 500",            None),
        ("commodities_commentary", "WTI Crude",          "wti"),
        ("commodities_commentary", "Gold",               "gold"),
        ("currencies_commentary",  "U.S. Dollar (DXY)",  None),
    ]
    for narrative_key, snap_key, kw in section_checks:
        truth_pct = (snapshot.get(snap_key) or {}).get("pct_change")
        if truth_pct is None or abs(truth_pct) < 0.02:
            continue
        prose = data.get(narrative_key)
        if not isinstance(prose, str):
            continue
        if kw is None:
            new_prose, changed = _rewrite_first_pct_magnitude(prose, truth_pct)
        else:
            new_prose, changed = _rewrite_pct_magnitude_after_keyword(prose, kw, truth_pct)
        if changed:
            data[narrative_key] = new_prose
            fixes += 1

    asset_kw = {
        "s&p":    "S&P 500",
        "nasdaq": "Nasdaq 100",
        "wti":    "WTI Crude",
        "crude":  "WTI Crude",
        "gold":   "Gold",
        "dxy":    "U.S. Dollar (DXY)",
    }
    bullets = data.get("pre_market_bullets")
    if isinstance(bullets, list):
        new_bullets = []
        for bullet in bullets:
            if not isinstance(bullet, str):
                new_bullets.append(bullet)
                continue
            btext_lower = bullet.lower()
            corrected = bullet
            for kw, snap_key in asset_kw.items():
                if kw in btext_lower:
                    truth_pct = (snapshot.get(snap_key) or {}).get("pct_change")
                    if truth_pct is None or abs(truth_pct) < 0.02:
                        break
                    corrected, changed = _rewrite_first_pct_magnitude(corrected, truth_pct)
                    if changed:
                        fixes += 1
                    break
            new_bullets.append(corrected)
        data["pre_market_bullets"] = new_bullets

    return fixes


def _correct_yield_pct_to_bp(data: dict, snapshot: dict) -> int:
    """Replace yield-move percent citations with basis-point figures in Calls 2/3 output fields.

    Calls 2/3 (outlook, recap) may write "yields fell 2.14%" where 2.14 is the yield's
    pct_change — which is meaningless and wrong per NUMBER FIDELITY. This corrector finds
    the exact pct_change string (e.g. "2.14%") in yield-adjacent fields and replaces it
    with the correct bp expression (e.g. "10 bps").
    Mutates data in place. Returns number of corrections applied.
    """
    if not snapshot:
        return 0
    y10 = snapshot.get("10-Yr Yield") or {}
    pct_change = y10.get("pct_change")
    bp_change  = y10.get("bp_change")
    if pct_change is None or bp_change is None or abs(bp_change) < 1:
        return 0

    abs_pct = abs(pct_change)
    bp_abs  = abs(bp_change)
    bp_sfx  = "bp" if bp_abs == 1 else "bps"

    # Build exact string targets: "2.14%" and "-2.14%" and "+2.14%"
    targets = {
        f"{abs_pct:.2f}%",
        f"-{abs_pct:.2f}%",
        f"+{abs_pct:.2f}%",
    }
    replacement = f"{bp_abs:.0f} {bp_sfx}"

    fields = ["market_outlook_rationale", "cross_asset_synthesis"]
    fixes = 0

    def _fix_text(text: str) -> tuple[str, bool]:
        changed = False
        for t in targets:
            if t in text:
                text = text.replace(t, replacement)
                changed = True
        return text, changed

    for field in fields:
        val = data.get(field)
        if isinstance(val, str):
            new_val, changed = _fix_text(val)
            if changed:
                data[field] = new_val
                fixes += 1

    # session_recap is a list of strings
    recap = data.get("session_recap")
    if isinstance(recap, list):
        new_recap = []
        changed_any = False
        for item in recap:
            if isinstance(item, str):
                new_item, ch = _fix_text(item)
                new_recap.append(new_item)
                if ch:
                    changed_any = True
            else:
                new_recap.append(item)
        if changed_any:
            data["session_recap"] = new_recap
            fixes += 1

    # asset_class_outlooks is a nested dict
    aclooks = data.get("asset_class_outlooks")
    if isinstance(aclooks, dict):
        for asset_val in aclooks.values():
            if isinstance(asset_val, dict):
                rationale = asset_val.get("rationale", "")
                if isinstance(rationale, str):
                    new_r, ch = _fix_text(rationale)
                    if ch:
                        asset_val["rationale"] = new_r
                        fixes += 1

    return fixes


# --- yield bp-magnitude correction (prose vs the authoritative curve) --------
# 2026-07-02: the reconciled curve carried 30Y +5 bp but the model wrote "the 30-year
# yield climbed 10 bp", and labelled a POSITIVE +32 bp 2s10s spread a "curve inversion".
# The bp figure is the one number the reader trusts, so force each tenor's stated bp move
# to match the arbitrated (YCharts) curve, and fix the inverted/positive-spread mislabel.
_YLD_MOVE_VERB = (r"(?:rose|fell|climbed|increased|decreased|declined|dropped|jumped|"
                  r"slipped|gained|added|shed|advanced|retreated|edged\s+\w+|ticked\s+\w+|"
                  r"moved|up|down|higher|lower)")

_TENOR_BP_RES = {
    "2-Year Yield":  re.compile(r"(2[-\s]?(?:year|yr)\b[^.;]{0,32}?" + _YLD_MOVE_VERB +
                                r"\s+(?:by\s+)?)(\d+(?:\.\d+)?)(\s*bps?\b)", re.IGNORECASE),
    "10-Year Yield": re.compile(r"(10[-\s]?(?:year|yr)\b[^.;]{0,32}?" + _YLD_MOVE_VERB +
                                r"\s+(?:by\s+)?)(\d+(?:\.\d+)?)(\s*bps?\b)", re.IGNORECASE),
    "30-Year Yield": re.compile(r"(30[-\s]?(?:year|yr)\b[^.;]{0,32}?" + _YLD_MOVE_VERB +
                                r"\s+(?:by\s+)?)(\d+(?:\.\d+)?)(\s*bps?\b)", re.IGNORECASE),
}
# 2s10s mislabelled "inverted" while positive: narrow, high-confidence phrase swaps.
_INVERSION_PHRASES = (
    (re.compile(r"\bcurve inversion\b", re.IGNORECASE), "positive curve slope"),
    (re.compile(r"\b(remains?|stays?|still)\s+inverted\b", re.IGNORECASE), r"\1 positively sloped"),
    (re.compile(r"\bthe\s+inverted\s+(yield\s+)?curve\b", re.IGNORECASE), r"the positively sloped \1curve"),
    (re.compile(r"\bcurve\s+remains\s+inverted\b", re.IGNORECASE), "curve remains positively sloped"),
)

# 10s-2s slope DIRECTION vs the authoritative curve. 2026-07-09: the model wrote "narrowing
# the 10s-2s spread by 1 bp to 35 bps" while 10Y rose 7 bp vs 2Y +6 bp — the spread WIDENED
# (steepened) by 1 bp. The spread's own arbitrated `change` field is degenerate (0.0), so the
# true direction is recomputed from the tenor deltas (10Y_chg - 2Y_chg). Only the verb is
# flipped (the "1 bp"/"35 bps" figures are left intact); tense/case preserved. Gated to
# sentences naming the curve/2s10s and never a "credit spread" clause.
_SPREAD_CTX_RE = re.compile(r"10s[-\s]?2s|2s[-\s]?10s|yield\s+curve|\bthe\s+curve\b", re.IGNORECASE)
_SPREAD_NARROW_TO_WIDEN = {
    "narrowed": "widened", "narrowing": "widening", "narrows": "widens", "narrow": "widen",
    "flattened": "steepened", "flattening": "steepening", "flattens": "steepens", "flatten": "steepen",
    "tightened": "widened", "tightening": "widening", "tightens": "widens", "tighten": "widen",
}
_SPREAD_WIDEN_TO_NARROW = {
    "widened": "narrowed", "widening": "narrowing", "widens": "narrows", "widen": "narrow",
    "steepened": "flattened", "steepening": "flattening", "steepens": "flattens", "steepen": "flatten",
}
_SPREAD_NARROW_RE = re.compile(
    r"\b(" + "|".join(sorted(_SPREAD_NARROW_TO_WIDEN, key=len, reverse=True)) + r")\b", re.IGNORECASE)
_SPREAD_WIDEN_RE = re.compile(
    r"\b(" + "|".join(sorted(_SPREAD_WIDEN_TO_NARROW, key=len, reverse=True)) + r")\b", re.IGNORECASE)


def _fix_spread_direction(text: str, spread_chg_bp: float | None) -> tuple[str, int]:
    """Flip a 10s-2s slope verb (narrow/flatten/tighten <-> widen/steepen) that contradicts
    the recomputed spread change. Per-sentence, gated to curve context, credit-spread safe."""
    if spread_chg_bp is None or abs(spread_chg_bp) < 0.5:
        return text, 0
    mapping = _SPREAD_NARROW_TO_WIDEN if spread_chg_bp > 0 else _SPREAD_WIDEN_TO_NARROW
    rx = _SPREAD_NARROW_RE if spread_chg_bp > 0 else _SPREAD_WIDEN_RE
    n = 0
    out = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if _SPREAD_CTX_RE.search(sent) and "credit" not in sent.lower():
            def _sub(m):
                nonlocal n
                w = m.group(1)
                repl = mapping.get(w.lower())
                if not repl:
                    return w
                n += 1
                return repl[0].upper() + repl[1:] if w[:1].isupper() else repl
            sent = rx.sub(_sub, sent)
        out.append(sent)
    return " ".join(out), n


# --- adjacent duplicate-word scrub -------------------------------------------
# 2026-07-10: session_recap shipped "priced in higher higher-for-longer rate path risks".
# Collapse an immediately-repeated identical word, restricted to a safelist of function words
# and directional modifiers so a legitimate repeat is never touched.
_DUP_WORD_RE = re.compile(
    r"\b(higher|lower|further|sharply|slightly|modestly|steadily|broadly|materially|"
    r"significantly|marginally|notably|the|a|to|of|in|on|and)\s+\1\b",
    re.IGNORECASE)


def _dedup_repeated_words(data: dict) -> int:
    return _map_all_prose(data, lambda t: _DUP_WORD_RE.sub(lambda m: m.group(1), t))


# --- yield DIRECTION (verb/noun) vs the authoritative curve sign --------------
# 2026-07-10: cross_asset_synthesis wrote "the 10-year yield's 1 bp fall" while the 10Y ROSE
# +1 bp (arbitrated/snapshot/fixed_income/recap all say rose), and fixed_income said "the
# 30-year yield slipped 1 bp" against a +1 bp arbitrated move. Yields are deliberately excluded
# from _correct_direction_words (a yield's level != its pct_change), so an inverted yield VERB
# or trailing NOUN ("...'s 1 bp fall") had no guard. This flips it to agree with the curve.
# Yield-specific vocabulary (no FX "firmed/strengthened"); verb + noun forms.
_YIELD_DIR_DOWN_TO_UP = {
    "fell": "rose", "fall": "rise", "falls": "rises", "falling": "rising",
    "slipped": "rose", "slip": "rise", "slips": "rises", "slipping": "rising",
    "slid": "rose", "slide": "rise", "sliding": "rising",
    "eased": "rose", "ease": "rise", "eases": "rises", "easing": "rising",
    "declined": "climbed", "decline": "gain", "declines": "gains", "declining": "climbing",
    "dropped": "climbed", "drop": "gain", "drops": "gains", "dropping": "climbing",
    "dipped": "climbed", "dip": "gain", "dips": "gains", "dipping": "climbing",
    "retreated": "climbed", "retreat": "gain", "retreats": "gains", "retreating": "climbing",
    "sank": "jumped", "sink": "jump", "sinking": "jumping",
}
_YIELD_DIR_UP_TO_DOWN = {
    "rose": "fell", "rise": "fall", "rises": "falls", "rising": "falling",
    "climbed": "slipped", "climb": "slip", "climbs": "slips", "climbing": "slipping",
    "jumped": "dropped", "jump": "drop", "jumps": "drops", "jumping": "dropping",
    "gained": "declined", "gain": "decline", "gains": "declines", "gaining": "declining",
    "advanced": "declined", "advance": "decline", "advances": "declines", "advancing": "declining",
    "increased": "decreased", "increase": "decrease",
    "surged": "sank", "spiked": "dropped", "spike": "drop",
}
_YIELD_TENOR_RES = [
    (re.compile(r"\b2[-\s]?(?:year|yr)\b", re.IGNORECASE),  "2-Year Yield"),
    (re.compile(r"\b10[-\s]?(?:year|yr)\b", re.IGNORECASE), "10-Year Yield"),
    (re.compile(r"\b30[-\s]?(?:year|yr)\b", re.IGNORECASE), "30-Year Yield"),
]
_YIELD_DIR_DOWN_RE = re.compile(
    r"\b(" + "|".join(sorted(_YIELD_DIR_DOWN_TO_UP, key=len, reverse=True)) + r")\b", re.IGNORECASE)
_YIELD_DIR_UP_RE = re.compile(
    r"\b(" + "|".join(sorted(_YIELD_DIR_UP_TO_DOWN, key=len, reverse=True)) + r")\b", re.IGNORECASE)


def _yield_dir_scope(text: str, start: int, self_tenor: str) -> int:
    """End index of the direction-rewrite scope for a tenor keyword at `start`: capped at the
    first causal/driver conjunction, the next DIFFERENT tenor keyword, a comma/semicolon/colon,
    or 80 chars — so one tenor's fix never reaches another's clause or a driver clause."""
    end = len(text)
    m = _DIR_CLAUSE_BOUNDARY_RE.search(text[start:], 1)
    if m:
        end = min(end, start + m.start())
    for rx, ten in _YIELD_TENOR_RES:
        if ten == self_tenor:
            continue
        mm = rx.search(text, start + 1)
        if mm:
            end = min(end, mm.start())
    for b in (",", ";", ":"):
        p = text.find(b, start + 1)
        if p != -1:
            end = min(end, p)
    return min(end, start + 80)


def _fix_yield_direction(text: str, tenor_chg: dict) -> tuple[str, int]:
    """Flip a yield's directional verb/noun to agree with the arbitrated tenor change sign.
    Scoped per-tenor to that tenor's own clause. Sub-0.5bp (~flat) tenors are left alone."""
    if not isinstance(text, str) or not text or not tenor_chg:
        return text, 0
    n = 0
    for rx, tenor in _YIELD_TENOR_RES:
        chg = tenor_chg.get(tenor)
        if chg is None or abs(chg) < 0.005:
            continue
        up = chg > 0
        mp = _YIELD_DIR_DOWN_TO_UP if up else _YIELD_DIR_UP_TO_DOWN
        flip_rx = _YIELD_DIR_DOWN_RE if up else _YIELD_DIR_UP_RE
        search_from = 0
        while True:
            m = rx.search(text, search_from)
            if not m:
                break
            s = m.start()
            e = _yield_dir_scope(text, s, tenor)

            def _sub(mm):
                nonlocal n
                w = mm.group(1)
                repl = mp.get(w.lower())
                if not repl:
                    return w
                n += 1
                return repl[0].upper() + repl[1:] if w[:1].isupper() else repl

            seg2 = flip_rx.sub(_sub, text[s:e])
            if seg2 != text[s:e]:
                text = text[:s] + seg2 + text[e:]
                e = s + len(seg2)
            search_from = max(e, s + 1)
    return text, n

_YIELD_BP_FIELDS = ("fixed_income_commentary", "market_outlook_rationale",
                    "cross_asset_synthesis", "economics_commentary")


def _correct_yield_bp_magnitude(data: dict, snapshot: dict | None = None) -> int:
    """Force each tenor's stated bp move to match the authoritative arbitrated (YCharts)
    curve, and fix a 2s10s spread mislabelled 'inverted' when it is positive. Reads
    data/market_data_arbitrated.json (gated on today). Mutates data; returns fix count."""
    try:
        arb = json.loads((DATA_DIR / "market_data_arbitrated.json").read_text(encoding="utf-8"))
    except Exception:
        return 0
    if str((arb or {}).get("arbitrated_date", ""))[:10] != datetime.today().strftime("%Y-%m-%d"):
        return 0
    curve = (arb or {}).get("yield_curve") or {}

    # Correct bp per tenor (rounded); tolerate a 1 bp rounding gap.
    tenor_bp: dict[str, int] = {}
    for tenor in _TENOR_BP_RES:
        chg = (curve.get(tenor) or {}).get("change")
        try:
            tenor_bp[tenor] = int(round(abs(float(chg)) * 100))
        except (TypeError, ValueError):
            continue

    # 2s10s sign — for the inversion-label fix.
    try:
        y2 = float((curve.get("2-Year Yield") or {}).get("level"))
        y10 = float((curve.get("10-Year Yield") or {}).get("level"))
        spread_positive = (y10 - y2) > 0.03  # >3 bp clearly not inverted
    except (TypeError, ValueError):
        spread_positive = False

    # 2s10s slope CHANGE (bp) recomputed from the tenor deltas — the spread's own arbitrated
    # `change` is often degenerate (0.0), so derive direction from 10Y_chg - 2Y_chg.
    try:
        y2c = float((curve.get("2-Year Yield") or {}).get("change"))
        y10c = float((curve.get("10-Year Yield") or {}).get("change"))
        spread_chg_bp = round((y10c - y2c) * 100, 1)
    except (TypeError, ValueError):
        spread_chg_bp = None

    # Signed tenor changes for the yield-DIRECTION corrector (verb/noun vs the curve sign).
    tenor_chg: dict[str, float] = {}
    for _t in ("2-Year Yield", "10-Year Yield", "30-Year Yield"):
        try:
            tenor_chg[_t] = float((curve.get(_t) or {}).get("change"))
        except (TypeError, ValueError):
            pass

    def _fix_text(text: str) -> tuple[str, int]:
        n = 0
        for tenor, correct in tenor_bp.items():
            rx = _TENOR_BP_RES[tenor]

            def _sub(m):
                nonlocal n
                try:
                    cur = float(m.group(2))
                except ValueError:
                    return m.group(0)
                if abs(cur - correct) < 1.5:
                    return m.group(0)  # already matches within rounding
                n += 1
                return f"{m.group(1)}{correct}{m.group(3)}"
            text = rx.sub(_sub, text)
        if spread_positive:
            for rx, repl in _INVERSION_PHRASES:
                text, k = rx.subn(repl, text)
                n += k
        text, k = _fix_spread_direction(text, spread_chg_bp)
        n += k
        text, k = _fix_yield_direction(text, tenor_chg)
        n += k
        return text, n

    fixes = 0
    for field in _YIELD_BP_FIELDS:
        val = data.get(field)
        if isinstance(val, str) and val:
            new, k = _fix_text(val)
            if k:
                data[field] = new
                fixes += k
    # session_recap (list) + asset_class_outlooks[*].rationale (nested)
    recap = data.get("session_recap")
    if isinstance(recap, list):
        for i, item in enumerate(recap):
            if isinstance(item, str) and item:
                new, k = _fix_text(item)
                if k:
                    recap[i] = new
                    fixes += k
    aco = data.get("asset_class_outlooks")
    if isinstance(aco, dict):
        for row in aco.values():
            if isinstance(row, dict) and isinstance(row.get("rationale"), str):
                new, k = _fix_text(row["rationale"])
                if k:
                    row["rationale"] = new
                    fixes += k
    return fixes


# --- direction-word / superlative correction -------------------------------
# Guards a failure class the percent-sign correctors miss: prose whose cited
# percent has the CORRECT sign but whose directional VERB or recency SUPERLATIVE
# contradicts the snapshot. Regression: 2026-06-01 shipped
#   "Gold slipped 1.36% to $4,560.50, falling to a two-month low"
# while gold was +1.36% (up). "1.36%" is bare-positive and matches the snapshot,
# so _correct_sign_mismatches/_correct_magnitude_mismatches both pass it — only
# the verb ("slipped"/"falling") and superlative ("two-month low") are wrong.
_DIR_DOWN_TO_UP = {
    "slipped": "rose", "slip": "rise", "slips": "rises", "slipping": "rising",
    "slid": "climbed", "slide": "climb", "slides": "climbs", "sliding": "climbing",
    "fell": "rose", "fall": "rise", "falls": "rises", "falling": "rising", "fallen": "risen",
    "declined": "advanced", "decline": "advance", "declines": "advances", "declining": "advancing",
    "dropped": "climbed", "drop": "climb", "drops": "climbs", "dropping": "climbing",
    "eased": "firmed", "ease": "firm", "eases": "firms", "easing": "firming",
    "retreated": "advanced", "retreat": "advance", "retreats": "advances", "retreating": "advancing",
    "sank": "surged", "sink": "surge", "sinks": "surges", "sinking": "surging",
    "weakened": "strengthened", "weaken": "strengthen", "weakens": "strengthens", "weakening": "strengthening",
    "softened": "firmed", "soften": "firm", "softens": "firms", "softening": "firming",
    "tumbled": "surged", "tumble": "surge", "tumbles": "surges", "tumbling": "surging",
    "plunged": "soared", "plunge": "soar", "plunges": "soars", "plunging": "soaring",
    "collapsed": "surged", "collapse": "surge", "collapses": "surges", "collapsing": "surging",
    "sold off": "rallied", "selling off": "rallying", "selloff": "rally", "sell-off": "rally",
}
_DIR_UP_TO_DOWN = {
    "rose": "fell", "rise": "fall", "rises": "falls", "rising": "falling", "risen": "fallen",
    "climbed": "slid", "climb": "slide", "climbs": "slides", "climbing": "sliding",
    "gained": "lost", "gain": "lose", "gains": "loses", "gaining": "losing",
    "advanced": "declined", "advance": "decline", "advances": "declines", "advancing": "declining",
    "jumped": "dropped", "jump": "drop", "jumps": "drops", "jumping": "dropping",
    "surged": "tumbled", "surge": "tumble", "surges": "tumbles", "surging": "tumbling",
    "soared": "plunged", "soar": "plunge", "soars": "plunges", "soaring": "plunging",
    "skyrocketed": "collapsed",
    "rallied": "sold off", "rallies": "sold off", "rallying": "selling off",
    "firmed": "eased", "firm": "ease", "firms": "eases", "firming": "easing",
    "strengthened": "weakened", "strengthen": "weaken",
}

# Subordinating/causal conjunctions that introduce a NEW clause about drivers or context
# (not the asset's price move). The rewrite scope stops here so "easing tensions" /
# "rising fears" in a driver clause are never mistaken for the asset's own direction.
_DIR_CLAUSE_BOUNDARY_RE = re.compile(
    r"\b(?:as|that|which|because|since|amid|reflecting|validat\w+|driven|fueled|powered|"
    r"despite|although|though|while|due|owing)\b",
    re.IGNORECASE,
)

# Every directional word we know how to flip, either direction. Used (direction-agnostic) to
# recognise an asset's ADJACENT pre-modifier ("tumbling WTI") so one asset's forward scope
# does not swallow — and mis-flip — the directional word attached to the NEXT asset's noun.
_DIR_ALL_WORDS = sorted(set(_DIR_DOWN_TO_UP) | set(_DIR_UP_TO_DOWN), key=len, reverse=True)
# Optional -ly adverb ("sharply") + a directional word, immediately before end-of-string.
_DIR_PREMOD_RE = re.compile(
    r"(?:\b\w+ly\s+)?\b(?:" + "|".join(re.escape(w) for w in _DIR_ALL_WORDS) + r")\s*$",
    re.IGNORECASE,
)


def _dir_scope_len(tail: str, snap_key: str) -> int:
    """Length of the rewrite scope inside `tail` (which starts at an asset keyword):
    capped at the first causal/driver conjunction or the next *different* asset keyword —
    and, when it caps at another asset, backed off further to leave that asset's own
    adjacent directional pre-modifier ('... surging WTI') to it, not this asset."""
    tl = tail.lower()
    cut = len(tail)
    m = _DIR_CLAUSE_BOUNDARY_RE.search(tail, 1)
    if m:
        cut = min(cut, m.start())
    for okw, osnap in _DIR_KW_MAP:
        if osnap == snap_key:
            continue
        p = tl.find(okw, 1)
        if p != -1:
            pm = _DIR_PREMOD_RE.search(tail[:p])
            cut = min(cut, pm.start() if pm else p)
    return cut


# Snapshot keys that carry a pct_change usable for direction checks (yields excluded —
# their level ≠ their pct_change, handled by the causal/bp correctors instead).
_DIR_KW_MAP = [
    ("gold", "Gold"),
    ("wti", "WTI Crude"),
    ("crude", "WTI Crude"),
    ("s&p", "S&P 500"),
    ("nasdaq", "Nasdaq 100"),
    ("dollar index", "U.S. Dollar (DXY)"),
    ("dxy", "U.S. Dollar (DXY)"),
]


def _flip_direction_words(text: str, truth_pct: float) -> tuple[str, bool]:
    """Flip directional verbs + recency superlatives in `text` to agree with truth_pct's sign.
    Snapshot UP → fix down-words ("slipped"→"rose") and "...-month low"→"...-month high".
    Snapshot DOWN → the inverse. Case-preserving. Returns (new_text, changed)."""
    if not isinstance(text, str) or not text:
        return text, False
    up = truth_pct >= 0
    flip_map = _DIR_DOWN_TO_UP if up else _DIR_UP_TO_DOWN
    super_from, super_to = ("low", "high") if up else ("high", "low")
    changed = False

    verb_re = re.compile(r"\b(" + "|".join(re.escape(k) for k in flip_map) + r")\b", re.IGNORECASE)

    def _verb_sub(m: "re.Match") -> str:
        nonlocal changed
        w = m.group(0)
        repl = flip_map.get(w.lower())
        if not repl:
            return w
        changed = True
        return repl[0].upper() + repl[1:] if w[:1].isupper() else repl

    # Directional trend-NOUNS first (before the verb pass, so "gains/losses" here are
    # handled as nouns, not the verb-map's "gains"->"loses"). "extended losses" /
    # "extension of losses" / "added to its declines" is a noun-phrase trend the
    # verb-only map missed. 2026-06-26: gold rose +0.97% on the day yet
    # commodities_commentary + cross_asset_synthesis said "Gold extended losses to
    # $4,045.59 (+0.97%)" / "extension of losses". Flip only the trend NOUN (keep the
    # verb), and only when it rides a trend-CONTINUATION verb so reversal phrasing
    # ("pared/trimmed losses", coherent on an up day) and unrelated "losses" are left
    # untouched.
    _wrong_nouns = r"loss(?:es)?|declines?" if up else r"gains?|advances?"
    _right_noun = "gains" if up else "losses"
    _trend_noun_re = re.compile(
        r"\b(extend\w*|extension\s+of|deepen\w*|add\w*\s+to|continu\w*|mount\w*)"
        r"((?:\s+(?:its|their))?\s+)(" + _wrong_nouns + r")\b",
        re.IGNORECASE,
    )

    def _trend_noun_sub(m: "re.Match") -> str:
        nonlocal changed
        changed = True
        orig = m.group(3)
        repl = _right_noun[0].upper() + _right_noun[1:] if orig[:1].isupper() else _right_noun
        return m.group(1) + m.group(2) + repl

    text = _trend_noun_re.sub(_trend_noun_sub, text)

    text = verb_re.sub(_verb_sub, text)

    # Recency/extreme superlative: "two-month low", "record low", "fresh 6-week low", etc.
    super_re = re.compile(
        r"((?:record|all-time|fresh|new|multi-(?:day|week|month|year)|"
        r"(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)[\-\s]?(?:day|week|month|year))[\-\s]?)"
        r"(" + super_from + r")\b",
        re.IGNORECASE,
    )

    def _super_sub(m: "re.Match") -> str:
        nonlocal changed
        changed = True
        orig = m.group(2)
        tail = super_to[0].upper() + super_to[1:] if orig[:1].isupper() else super_to
        return m.group(1) + tail

    text = super_re.sub(_super_sub, text)
    return text, changed


def _correct_direction_words(data: dict, snapshot: dict) -> int:
    """Rewrite directional verbs/superlatives that contradict the snapshot sign even when
    the cited percent's sign is already correct. Mutates data in place. Idempotent.
    Scoped per-sentence, per-asset, and capped at the next other-asset mention so one
    asset's correction never touches another's clause. Returns number of fields corrected.
    """
    if not snapshot:
        return 0
    fixes = 0

    def _fix_field(text: str) -> str:
        nonlocal fixes
        if not isinstance(text, str) or not text:
            return text
        out_sents = []
        for sent in re.split(r"(?<=[.!?])\s+", text):
            new_sent = sent
            handled: set[str] = set()
            for kw, snap_key in _DIR_KW_MAP:
                if snap_key in handled:
                    continue
                sl = new_sent.lower()
                idx = sl.find(kw)
                if idx == -1:
                    continue
                truth_pct = (snapshot.get(snap_key) or {}).get("pct_change")
                if truth_pct is None or abs(truth_pct) < 0.02:
                    continue
                head, tail = new_sent[:idx], new_sent[idx:]
                cut = _dir_scope_len(tail, snap_key)
                scope, rest = tail[:cut], tail[cut:]
                scope2, changed_fwd = _flip_direction_words(scope, truth_pct)
                # Backward pass: a directional word can PRE-modify the asset noun
                # ("tumbling WTI crude"), which the forward scope never reaches. Flip only
                # an adjacent pre-modifier (optional -ly adverb + one directional word) so a
                # prior asset's clause ("the S&P's decline ... and WTI") is left untouched.
                changed_pre = False
                pm = _DIR_PREMOD_RE.search(head)
                if pm:
                    seg2, changed_pre = _flip_direction_words(head[pm.start():], truth_pct)
                    if changed_pre:
                        head = head[:pm.start()] + seg2
                if changed_fwd or changed_pre:
                    new_sent = head + scope2 + rest
                    handled.add(snap_key)
                    fixes += 1
            out_sents.append(new_sent)
        return " ".join(out_sents)

    for field in (
        "equities_commentary", "commodities_commentary", "currencies_commentary",
        "cross_asset_synthesis", "market_outlook_rationale", "international_section",
    ):
        val = data.get(field)
        if isinstance(val, str):
            nv = _fix_field(val)
            if nv != val:
                data[field] = nv

    aco = data.get("asset_class_outlooks")
    if isinstance(aco, dict):
        for av in aco.values():
            if isinstance(av, dict) and isinstance(av.get("rationale"), str):
                nv = _fix_field(av["rationale"])
                if nv != av["rationale"]:
                    av["rationale"] = nv

    for list_field in ("session_recap", "pre_market_bullets"):
        recap = data.get(list_field)
        if isinstance(recap, list):
            data[list_field] = [
                _fix_field(x) if isinstance(x, str) else x for x in recap
            ]

    return fixes


def _check_direction_words(data: dict, snapshot: dict) -> list[str]:
    """Detect residual direction-word/superlative contradictions (post-correction = none).
    A clause is a violation if _flip_direction_words would still change it. Defense-in-depth
    so the retry loop catches anything the corrector could not scope safely."""
    if not snapshot:
        return []
    violations: list[str] = []
    fields = (
        "equities_commentary", "commodities_commentary", "currencies_commentary",
        "cross_asset_synthesis", "market_outlook_rationale",
    )
    for field in fields:
        text = data.get(field)
        if not isinstance(text, str) or not text:
            continue
        for sent in re.split(r"(?<=[.!?])\s+", text):
            sl = sent.lower()
            seen: set[str] = set()
            for kw, snap_key in _DIR_KW_MAP:
                if snap_key in seen or kw not in sl:
                    continue
                truth_pct = (snapshot.get(snap_key) or {}).get("pct_change")
                if truth_pct is None or abs(truth_pct) < 0.02:
                    continue
                idx = sl.find(kw)
                tail = sent[idx:]
                cut = _dir_scope_len(tail, snap_key)
                _, changed = _flip_direction_words(tail[:cut], truth_pct)
                if changed:
                    seen.add(snap_key)
                    violations.append(
                        f"{field}: {snap_key} snapshot {truth_pct:+.2f}% but prose uses "
                        f"contradictory direction/superlative — '{sent.strip()[:80]}'"
                    )
    return violations[:4]


# --- fabricated corporate-action guard -------------------------------------
# The report has NO dividend / buyback / split data feed, so any corporate-action
# claim in the narrative is a hallucination. Regression: 2026-06-01 shipped
#   "Nvidia's 2,400% dividend hike reshapes S&P 500 income streams"
# echoed into the Equities outlook and the XNTK spotlight. Detect → force retry;
# scrub the offending clause as a deterministic safety net if retries exhaust.
_CORP_ACTION_RE = re.compile(
    r"\b(?:dividend|buyback|buybacks|share\s+repurchase|stock\s+split|"
    r"special\s+dividend|payout)\b",
    re.IGNORECASE,
)


def _check_fabricated_corporate_actions(data: dict) -> list[str]:
    """Flag unsupported corporate-action claims (dividend/buyback/split) in narrative prose.
    No such data feed exists, so any mention is fabricated. Returns violation strings."""
    fields = (
        "equities_commentary", "fixed_income_commentary", "commodities_commentary",
        "currencies_commentary", "economics_commentary", "market_outlook_rationale",
        "cross_asset_synthesis", "international_section",
    )
    violations: list[str] = []
    for field in fields:
        text = data.get(field)
        if isinstance(text, str) and _CORP_ACTION_RE.search(text):
            m = _CORP_ACTION_RE.search(text)
            ctx = text[max(0, m.start() - 30): m.end() + 20].strip()
            violations.append(f"{field}: unsupported corporate-action claim — '{ctx}'")
    # spotlight commentary is a list of dicts
    for list_key in ("portfolio_spotlight_winners", "portfolio_spotlight_watch"):
        for entry in data.get(list_key, []) or []:
            c = entry.get("commentary") if isinstance(entry, dict) else None
            if isinstance(c, str) and _CORP_ACTION_RE.search(c):
                violations.append(
                    f"{list_key}[{entry.get('ticker', '?')}]: unsupported corporate-action claim"
                )
    # asset_class_outlooks rationales
    aco = data.get("asset_class_outlooks")
    if isinstance(aco, dict):
        for name, av in aco.items():
            r = av.get("rationale") if isinstance(av, dict) else None
            if isinstance(r, str) and _CORP_ACTION_RE.search(r):
                violations.append(f"asset_class_outlooks[{name}]: unsupported corporate-action claim")
    return violations[:6]


def _scrub_fabricated_corporate_actions(data: dict) -> int:
    """Deterministic safety net: surgically remove fabricated corporate-action clauses.
    Strips the offending clause (not the whole sentence) and tidies leftover punctuation.
    Mutates data in place. Returns number of fields scrubbed."""
    fixes = 0

    def _clean(text: str) -> tuple[str, bool]:
        if not isinstance(text, str) or not _CORP_ACTION_RE.search(text):
            return text, False
        kept: list[str] = []
        for sent in re.split(r"(?<=[.!?])\s+", text):
            m = _CORP_ACTION_RE.search(sent)
            if not m:
                kept.append(sent)
                continue
            # Embedded clause? Find the nearest *clause* comma before the action — one
            # followed by whitespace, so thousands separators ("2,400") never count.
            comma = -1
            for cm in re.finditer(r",(?=\s)", sent[:m.start()]):
                comma = cm.start()
            if comma != -1:
                rest = sent[m.end():]
                nxt = re.search(r",(?=\s)", rest)
                end = m.end() + nxt.start() if nxt else len(sent)
                cleaned = (sent[:comma] + sent[end:]).strip()
                cleaned = re.sub(r"\s+([.,;])", r"\1", cleaned)
                # Restore terminal punctuation if the excision removed it.
                if cleaned and cleaned[-1] not in ".!?":
                    cleaned += "."
                if cleaned and not _CORP_ACTION_RE.search(cleaned):
                    kept.append(cleaned)
                # else: clause couldn't be isolated → drop the whole sentence
            # No preceding clause comma → action is the main subject/predicate → drop sentence.
        new = " ".join(s for s in kept if s).strip()
        return new, (new != text)

    for field in (
        "equities_commentary", "fixed_income_commentary", "commodities_commentary",
        "currencies_commentary", "economics_commentary", "market_outlook_rationale",
        "cross_asset_synthesis", "international_section",
    ):
        val = data.get(field)
        if isinstance(val, str):
            nv, changed = _clean(val)
            if changed:
                data[field] = nv
                fixes += 1

    for list_key in ("portfolio_spotlight_winners", "portfolio_spotlight_watch"):
        for entry in data.get(list_key, []) or []:
            if isinstance(entry, dict) and isinstance(entry.get("commentary"), str):
                nv, changed = _clean(entry["commentary"])
                if changed:
                    entry["commentary"] = nv
                    fixes += 1

    aco = data.get("asset_class_outlooks")
    if isinstance(aco, dict):
        for av in aco.values():
            if isinstance(av, dict) and isinstance(av.get("rationale"), str):
                nv, changed = _clean(av["rationale"])
                if changed:
                    av["rationale"] = nv
                    fixes += 1

    return fixes


def _check_causal_logic(data: dict, snapshot: dict) -> list[str]:
    """Detect causal-logic inversions: driver implies one direction but prose says the opposite.
    Checks sentence-level contradictions in fixed_income_commentary only (the highest-error section).
    Returns violation strings (empty = clean).
    """
    import re
    violations = []

    fi_prose = data.get("fixed_income_commentary", "")
    if not isinstance(fi_prose, str) or not fi_prose:
        return violations

    sentences = re.split(r'(?<=[.!?])\s+', fi_prose)
    for sent in sentences:
        sl = sent.lower()
        yield_rose = bool(re.search(
            r'\byield[s]?\b.{0,60}\b(rose|climbed|jumped|surged|advanced|pushed\s+higher|moved\s+up)\b', sl
        ))
        if not yield_rose:
            continue
        # "Fewer/lower/reduced rate-hike expectations" pulls yields DOWN — contradicts "rose".
        if re.search(r'\b(fewer|lower|reduced)\b.{0,80}\b(rate\s*hikes?|hikes?|tightening|rate\s*increases?)\b', sl):
            violations.append(
                "fixed_income_commentary: causal inversion — 'fewer/lower rate hikes' driver should pull "
                "yields DOWN, but prose says they rose"
            )
            break
        # "Rate cut hopes / dovish expectations" pulls yields DOWN — contradicts "rose".
        if re.search(r'\b(rate\s+cut|cut\s+expectation|dovish|fewer\s+hike|cut\s+hope)\b', sl):
            violations.append(
                "fixed_income_commentary: causal inversion — rate-cut/dovish driver should pull "
                "yields DOWN, but prose says they rose"
            )
            break

    return violations


# --- editorial contradiction guard -----------------------------------------
# Catches window/superlative/causal claims that contradict the snapshot even though
# no single percent is wrong. Regressions seen 2026-06-01:
#   • "rising yields powering the dollar's biggest weekly gain in months" — 10Y was
#     flat on the day and DOWN 13bp on the week; DXY was down on day and week.
#   • "the dollar hits a six-week high" — DXY fell -0.11% (same paragraph says "fell").
#   • "WTI Crude fell … as renewed Middle East tensions fuel inflation fears and supply
#     shocks" — a price DECLINE cannot be driven by a bullish supply-shock/escalation story.
_DOLLAR_STRENGTH_RE = re.compile(
    r"\b(?:biggest|largest|strongest|best)\b[^.;]*\b(?:weekly\s+)?(?:gain|advance|rally|week|run)\b"
    r"|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|multi|\d+)[\-\s]?(?:week|month)[\-\s]?high\b"
    r"|\bhits?\s+a\s+(?:fresh|new|multi[\-\s]?\w+|\d+[\-\s]?(?:week|month))[\-\s]?high\b",
    re.IGNORECASE,
)
# Generic "rising yields"/"higher rates" used as a market DRIVER. Deliberately the
# adjective form only — a tenor-specific factual move ("the 30-year yield rose 1 bp")
# is legitimate and must NOT be flagged just because the 10-Yr was flat.
_YIELD_RISING_RE = re.compile(
    r"\b(?:rising|climbing|surging)\s+(?:treasury\s+)?(?:yields|rates)\b"
    r"|\bhigher\s+(?:treasury\s+)?(?:yields|rates)\b(?!\s+(?:would|could|may|might))",
    re.IGNORECASE,
)
_OIL_BULL_DRIVER_RE = re.compile(
    r"supply\s+shock|supply\s+disruption|renewed\b[^.;]{0,24}\btension|escalat|fuel[^.;]{0,20}inflation",
    re.IGNORECASE,
)
_OIL_DOWN_VERB_RE = re.compile(r"\b(?:fell|declined|slid|dropped|lower|sank|tumbled)\b", re.IGNORECASE)

_EDITORIAL_FIELDS = (
    "equities_commentary", "fixed_income_commentary", "commodities_commentary",
    "currencies_commentary", "cross_asset_synthesis", "market_outlook_rationale",
    "international_section",
)


def _editorial_violations_in_sentence(sent: str, snapshot: dict) -> list[str]:
    """Return editorial-contradiction tags for one sentence given the snapshot."""
    sl = sent.lower()
    out: list[str] = []
    snap = snapshot or {}

    dxy = snap.get("U.S. Dollar (DXY)") or {}
    dxy_d, dxy_1w = dxy.get("pct_change"), dxy.get("pct_change_1w")
    dxy_fell = (dxy_1w is not None and dxy_1w < -0.05) or (dxy_d is not None and dxy_d < -0.05)
    if dxy_fell and ("dollar" in sl or "dxy" in sl) and _DOLLAR_STRENGTH_RE.search(sent):
        out.append("dollar-strength superlative but DXY fell on the day/week")

    y = snap.get("10-Yr Yield") or {}
    bp, bp1w = y.get("bp_change"), y.get("bp_change_1w")
    yields_not_up = (bp is None or bp <= 0) and (bp1w is None or bp1w <= 0) and not (bp is None and bp1w is None)
    if yields_not_up and _YIELD_RISING_RE.search(sent):
        out.append("'rising yields' claim but 10Y was flat/down on the day and week")

    wti = snap.get("WTI Crude") or {}
    wti_pct = wti.get("pct_change")
    if (wti_pct is not None and wti_pct < -0.05
            and ("wti" in sl or "crude" in sl or " oil" in sl)
            and _OIL_DOWN_VERB_RE.search(sl) and _OIL_BULL_DRIVER_RE.search(sl)):
        out.append("oil decline attributed to a bullish supply-shock/escalation driver")
    return out


def _check_editorial_contradictions(data: dict, snapshot: dict) -> list[str]:
    """Flag window/superlative/causal contradictions vs the snapshot (empty = clean)."""
    if not snapshot:
        return []
    violations: list[str] = []
    for field in _EDITORIAL_FIELDS:
        text = data.get(field)
        if not isinstance(text, str) or not text:
            continue
        for sent in re.split(r"(?<=[.!?])\s+", text):
            for tag in _editorial_violations_in_sentence(sent, snapshot):
                violations.append(f"{field}: {tag} — '{sent.strip()[:80]}'")
    return violations[:6]


def _scrub_false_weekly_claims(data: dict, snapshot: dict) -> int:
    """Deterministic safety net: drop sentences that make a dollar-strength superlative
    while DXY fell on the day/week. These are pure embellishment — the factual currency
    levels live in other sentences, so dropping them is safe (and today's offending
    sentence also carries the "rising yields are powering …" clause, removed with it).
    'rising yields' alone and oil-causality are NOT scrubbed (they can sit in otherwise
    useful/factual sentences) — left to the retry loop + prompt. Returns fields changed."""
    if not snapshot:
        return 0
    fixes = 0
    for field in ("currencies_commentary", "fixed_income_commentary",
                  "cross_asset_synthesis", "market_outlook_rationale"):
        text = data.get(field)
        if not isinstance(text, str) or not text:
            continue
        kept = []
        changed = False
        for sent in re.split(r"(?<=[.!?])\s+", text):
            tags = _editorial_violations_in_sentence(sent, snapshot)
            if any("dollar-strength" in t for t in tags):
                changed = True
                continue
            kept.append(sent)
        if changed:
            data[field] = " ".join(kept).strip()
            fixes += 1
    return fixes


# --- shared prose-field iteration for deterministic correctors --------------
# session_recap + pre_market_bullets are list fields generated on a separate LLM
# call (Call 3 / Call 1) that the earlier per-field correctors only partially
# covered. Regression 2026-06-02: every direction/window/hallucination error this
# run lived in session_recap or pre_market_bullets while the structured narrative
# was clean. This helper lets the new correctors sweep EVERY rendered text field.
_ALL_PROSE_FIELDS = (
    "equities_commentary", "fixed_income_commentary", "commodities_commentary",
    "currencies_commentary", "economics_commentary", "cross_asset_synthesis",
    "market_outlook_rationale", "international_section",
)
_ALL_PROSE_LISTS = ("session_recap", "pre_market_bullets", "watch_today")


def _map_all_prose(data: dict, fn) -> int:
    """Apply fn(str)->str to every prose field, recap/bullet list item, and each
    asset_class_outlooks rationale. Returns the number of fields/lists changed."""
    changed = 0
    for field in _ALL_PROSE_FIELDS:
        v = data.get(field)
        if isinstance(v, str) and v:
            nv = fn(v)
            if nv != v:
                data[field] = nv
                changed += 1
    for field in _ALL_PROSE_LISTS:
        lst = data.get(field)
        if isinstance(lst, list):
            new, any_ch = [], False
            for it in lst:
                if isinstance(it, str):
                    ni = fn(it)
                    if ni != it:
                        any_ch = True
                    new.append(ni)
                else:
                    new.append(it)
            if any_ch:
                data[field] = new
                changed += 1
    aco = data.get("asset_class_outlooks")
    if isinstance(aco, dict):
        for av in aco.values():
            if isinstance(av, dict) and isinstance(av.get("rationale"), str) and av["rationale"]:
                nv = fn(av["rationale"])
                if nv != av["rationale"]:
                    av["rationale"] = nv
                    changed += 1
    return changed


# --- degenerate-repetition guard (Fix: 2026-06-15 economics loop) ------------
# Regression 2026-06-15 economics_commentary: the LLM ran away into a repetition
# loop, emitting the same ~3-sentence block ~40 times and opening mid-clause with
# "vs 0.5% prior indicates a robust economy." No value/narrative scrubber catches
# this — they validate CONTENT, not runaway GENERATION. This collapses verbatim
# duplicate sentences (keeping the first occurrence, in order) across every prose
# field/list/rationale, and trims mid-clause fragments (prose never opens with a
# lowercase word). Idempotent and length-agnostic.
_REPEAT_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
# Lowercase words that, when they OPEN a "sentence", mark it as a mid-clause fragment
# (a truncation/loop artifact) rather than real prose. Brand names that legitimately
# start lowercase (xAI, iPhone, iShares, eBay) are NOT in this set, so they survive.
_FRAGMENT_OPENERS = frozenset({
    "vs", "versus", "and", "but", "or", "nor", "as", "while", "whereas", "which",
    "than", "because", "so", "yet", "plus", "with", "of", "to", "in", "on", "at",
    "for", "from", "by", "into", "onto",
})


def _scrub_degenerate_repetition(data: dict) -> int:
    """Drop verbatim-duplicate sentences within any prose field and strip mid-clause
    fragments. Guards against LLM runaway-repetition (2026-06-15)."""
    def _norm(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip().lower()

    def _dedupe(text: str) -> str:
        seen: set[str] = set()
        kept: list[str] = []
        leading = True  # in the run of leading sentences (front-truncation territory)
        for raw in _REPEAT_SENT_SPLIT_RE.split(text):
            s = raw.strip()
            if not s:
                continue
            first = s.split(None, 1)[0].strip(",.;:").lower()
            is_lower_open = s[:1].islower()
            # Drop: any lowercase-opener in the leading run (front-truncation), and
            # any interior lowercase-opener whose first word is a connector ("vs ...").
            if is_lower_open and (leading or first in _FRAGMENT_OPENERS):
                continue
            leading = False
            key = _norm(s)
            if len(key) > 20:
                if key in seen:
                    continue
                seen.add(key)
            kept.append(s)
        return " ".join(kept).strip()

    return _map_all_prose(data, _dedupe)


# --- dollar direction + window correction (Fix: recap arrays bypass guards) -
# _DIR_KW_MAP only matches "dollar index"/"dxy", so bare-"dollar" prose slipped the
# direction-word corrector, and a multi-day WINDOW claim is invisible to a day-change
# check. Regression 2026-06-02 session_recap: "rising yields powered the dollar's
# weekly gain" (DXY +0.29% on the DAY but DOWN on the WEEK) and "a weaker dollar ...
# drove investors toward oil" (DXY rose on the day). Rewrite bare-dollar adjectives +
# verbs to the day sign, and "weekly gain/loss" to "daily" when the week disagrees.
_DOLLAR_TOKEN_RE = re.compile(r"\b(?:dollar|greenback|dxy)\b", re.IGNORECASE)
_DOLLAR_ADJ_UP = {  # snapshot UP → flip these weak adjectives to strong
    "weaker": "stronger", "softer": "firmer", "weak": "strong", "soft": "firm",
    "weakening": "strengthening", "softening": "firming",
}
_DOLLAR_ADJ_DOWN = {v: k for k, v in _DOLLAR_ADJ_UP.items()}  # snapshot DOWN → inverse
_DOLLAR_VERB_UP = {  # snapshot UP → flip these down-verbs to up
    # past tense
    "weakened": "strengthened", "softened": "firmed", "slipped": "rose", "fell": "rose",
    "slid": "climbed", "eased": "firmed", "declined": "advanced", "dropped": "climbed",
    "lost": "gained", "sank": "surged",
    # present tense — the asset-class outlook boxes are written in present tense
    # ("the dollar strengthens"), which the past-tense-only map missed (2026-06-30).
    "weakens": "strengthens", "softens": "firms", "slips": "rises", "falls": "rises",
    "slides": "climbs", "eases": "firms", "declines": "advances", "drops": "climbs",
    "loses": "gains", "sinks": "surges", "dips": "climbs", "retreats": "advances",
}
_DOLLAR_VERB_DOWN = {  # snapshot DOWN → flip these up-verbs to down
    # past tense
    "strengthened": "weakened", "firmed": "softened", "rose": "fell", "climbed": "slid",
    "advanced": "declined", "gained": "lost", "rallied": "fell", "jumped": "dropped",
    "surged": "sank",
    # present tense
    "strengthens": "weakens", "firms": "softens", "rises": "falls", "climbs": "slides",
    "advances": "declines", "gains": "loses", "rallies": "falls", "jumps": "drops",
    "surges": "sinks",
}
_EURO_TOKEN_RE = re.compile(r"\beuro\b", re.IGNORECASE)
_DOLLAR_GAIN_NOUNS = ("gains", "gain", "advance", "rally", "run", "strength")
_DOLLAR_LOSS_NOUNS = ("losses", "loss", "decline", "weakness", "drop", "slide", "pullback")


def _correct_dollar_direction(data: dict, snapshot: dict) -> int:
    """Rewrite bare-dollar direction adjectives/verbs to the DXY day sign and convert
    'weekly gain/loss' to 'daily' when the week's sign disagrees. Mutates in place."""
    if not snapshot:
        return 0
    dxy = snapshot.get("U.S. Dollar (DXY)") or {}
    day = dxy.get("pct_change")
    wk = dxy.get("pct_change_1w")
    if day is not None and abs(day) < 0.02:
        day = None
    if day is None and wk is None:
        return 0

    adj_map = verb_map = None
    if day is not None:
        adj_map = _DOLLAR_ADJ_UP if day > 0 else _DOLLAR_ADJ_DOWN
        verb_map = _DOLLAR_VERB_UP if day > 0 else _DOLLAR_VERB_DOWN
        adj_re = re.compile(
            r"\b(" + "|".join(map(re.escape, adj_map)) + r")(\s+(?:u\.?s\.?\s+)?(?:dollar|greenback|dxy))",
            re.IGNORECASE)
        verb_re = re.compile(
            r"((?:dollar|greenback|dxy)(?:'s)?\s+(?:\w+\s+){0,1})("
            + "|".join(map(re.escape, verb_map)) + r")\b",
            re.IGNORECASE)
    win_re = None
    if wk is not None and abs(wk) >= 0.05:
        nouns = _DOLLAR_GAIN_NOUNS if wk < 0 else _DOLLAR_LOSS_NOUNS
        win_re = re.compile(r"\bweekly(\s+(?:" + "|".join(nouns) + r"))\b", re.IGNORECASE)

    # Euro direction is the dollar's inverse (EUR is ~58% of the DXY basket), so a material
    # DXY move pins the euro's sign: dollar DOWN ⇒ euro stronger, dollar UP ⇒ euro weaker.
    # Catches "a weaker euro" sitting beside a falling dollar (2026-06-30 US-Dollar outlook).
    # Keyed on the DXY sign we already trust, so it needs no separate EUR/USD snapshot key.
    euro_adj = euro_re = None
    if day is not None:
        euro_adj = _DOLLAR_ADJ_UP if day < 0 else _DOLLAR_ADJ_DOWN
        euro_re = re.compile(
            r"\b(" + "|".join(map(re.escape, euro_adj)) + r")(\s+euro)\b", re.IGNORECASE)

    def _case(repl: str, orig: str) -> str:
        return repl[0].upper() + repl[1:] if orig[:1].isupper() else repl

    def _fix(text: str) -> str:
        out = []
        for sent in re.split(r"(?<=[.!?])\s+", text):
            new = sent
            if _DOLLAR_TOKEN_RE.search(sent):
                if adj_map:
                    new = adj_re.sub(lambda m: _case(adj_map[m.group(1).lower()], m.group(1)) + m.group(2), new)
                    new = verb_re.sub(lambda m: m.group(1) + _case(verb_map[m.group(2).lower()], m.group(2)), new)
                if win_re is not None:
                    new = win_re.sub(
                        lambda m: ("Daily" if m.group(0)[:1].isupper() else "daily") + m.group(1), new)
            if euro_re is not None and _EURO_TOKEN_RE.search(new):
                new = euro_re.sub(
                    lambda m: _case(euro_adj[m.group(1).lower()], m.group(1)) + m.group(2), new)
            out.append(new)
        return " ".join(out)

    return _map_all_prose(data, _fix)


# --- off-narrative geopolitical hallucination scrub ------------------------
# Regression 2026-06-02: a US-Iran/Middle-East session had "heavy Russian attacks on
# Ukrainian cities" injected into pre_market_bullets + equities_commentary — a conflict
# absent from every source headline. A named conflict entity that appears NOWHERE in the
# source corpus is a hallucination: strip the subordinate clause that carries it, or drop
# the whole sentence/bullet if the entity is the main subject.
_GEO_ENTITY_RES = [
    re.compile(r"\b(?:russia|russian|moscow|kremlin|putin|ukraine|ukrainian|kyiv|kiev|zelensky)\b", re.IGNORECASE),
    re.compile(r"\b(?:north\s+korea|north\s+korean|pyongyang|kim\s+jong)\b", re.IGNORECASE),
    re.compile(r"\b(?:venezuela|venezuelan|maduro|caracas)\b", re.IGNORECASE),
]
_GEO_CLAUSE_BOUNDARY_RE = re.compile(
    r"\s+(?:despite|amid|as|while|after|following|even\s+as|though|although|on\s+reports|on\s+news)\b",
    re.IGNORECASE)


def _scrub_offnarrative_geopolitics(data: dict, source_text: str) -> int:
    """Remove conflict-entity mentions that are absent from the source corpus."""
    src = (source_text or "").lower()
    off = [rx for rx in _GEO_ENTITY_RES if not rx.search(src)]
    if not off:
        return 0

    def _present(s: str) -> bool:
        return any(rx.search(s) for rx in off)

    def _clean_sentence(sent: str):
        if not _present(sent):
            return sent
        best = None
        for m in _GEO_CLAUSE_BOUNDARY_RE.finditer(sent):
            head, tail = sent[:m.start()], sent[m.start():]
            if _present(tail) and not _present(head) and len(head.strip()) > 15:
                best = m.start()
        if best is not None:
            h = sent[:best].rstrip(" ,;:")
            if h and h[-1] not in ".!?":
                h += "."
            return h
        return None  # entity in main clause → drop sentence

    fixes = 0
    for field in _ALL_PROSE_FIELDS:
        v = data.get(field)
        if not isinstance(v, str) or not v or not _present(v):
            continue
        kept = [cs for sent in re.split(r"(?<=[.!?])\s+", v)
                if (cs := _clean_sentence(sent))]
        nv = " ".join(kept).strip()
        if nv != v:
            data[field] = nv
            fixes += 1
    for field in _ALL_PROSE_LISTS:
        lst = data.get(field)
        if not isinstance(lst, list):
            continue
        new, ch = [], False
        for it in lst:
            if isinstance(it, str) and _present(it):
                ch = True
                cs = _clean_sentence(it)
                if cs:
                    new.append(cs)
            else:
                new.append(it)
        if ch:
            data[field] = new
            fixes += 1
    aco = data.get("asset_class_outlooks")
    if isinstance(aco, dict):
        for av in aco.values():
            if isinstance(av, dict) and isinstance(av.get("rationale"), str) and _present(av["rationale"]):
                kept = [cs for sent in re.split(r"(?<=[.!?])\s+", av["rationale"])
                        if (cs := _clean_sentence(sent))]
                nv = " ".join(kept).strip()
                if nv != av["rationale"]:
                    av["rationale"] = nv
                    fixes += 1
    return fixes


# --- ungrounded Iran/Middle-East causal-clause scrub -----------------------
# 2026-07-02: even with the "drop geo causation when unclear" prompt rule, the model leaked
# "fading ceasefire hopes... drove the commodity divergence" into secondary sections. When the
# fresh geo read is unclear or absent (see build_geopolitical_context + the dated sidecar), no
# market move may be attributed to the storyline — strip the geo causal clause, or drop the
# sentence when the storyline is its main subject. The prompt rule nudges; this FORCES it.
_GEO_STORY_RE = re.compile(
    r"\b(iran|iranian|tehran|hormuz|houthi|persian\s+gulf|strait\s+of\s+hormuz|"
    r"cease-?fire|truce|peace\s+(?:deal|talks|hopes|negotiat\w*|process|plan)|"
    r"middle[\s-]east(?:ern)?)\b", re.IGNORECASE)


def _scrub_ungrounded_geo_causation(data: dict) -> int:
    """Strip Iran/Middle-East causal clauses when the fresh geo read is unclear/absent (per the
    geo sidecar). Mirrors _scrub_offnarrative_geopolitics' clause removal. Returns fix count."""
    if _read_geo_direction() not in ("unclear", "absent"):
        return 0  # grounded (easing/escalating), or no fresh read (stale) → leave prose alone

    def _clean_sentence(sent: str):
        if not _GEO_STORY_RE.search(sent):
            return sent
        best = None
        for m in _GEO_CLAUSE_BOUNDARY_RE.finditer(sent):
            head, tail = sent[:m.start()], sent[m.start():]
            if _GEO_STORY_RE.search(tail) and not _GEO_STORY_RE.search(head) and len(head.strip()) > 15:
                best = m.start()
        if best is not None:
            h = sent[:best].rstrip(" ,;:")
            if h and h[-1] not in ".!?":
                h += "."
            return h
        return None  # storyline is the main subject → drop the sentence

    fixes = 0
    for field in _ALL_PROSE_FIELDS:
        v = data.get(field)
        if not isinstance(v, str) or not v or not _GEO_STORY_RE.search(v):
            continue
        kept = [cs for sent in re.split(r"(?<=[.!?])\s+", v) if (cs := _clean_sentence(sent))]
        nv = " ".join(kept).strip()
        if nv != v:
            data[field] = nv
            fixes += 1
    for field in _ALL_PROSE_LISTS:
        lst = data.get(field)
        if not isinstance(lst, list):
            continue
        new, ch = [], False
        for it in lst:
            if isinstance(it, str) and _GEO_STORY_RE.search(it):
                ch = True
                if (cs := _clean_sentence(it)):
                    new.append(cs)
            else:
                new.append(it)
        if ch:
            data[field] = new
            fixes += 1
    aco = data.get("asset_class_outlooks")
    if isinstance(aco, dict):
        for av in aco.values():
            if isinstance(av, dict) and isinstance(av.get("rationale"), str) and _GEO_STORY_RE.search(av["rationale"]):
                kept = [cs for sent in re.split(r"(?<=[.!?])\s+", av["rationale"]) if (cs := _clean_sentence(sent))]
                nv = " ".join(kept).strip()
                if nv != av["rationale"]:
                    av["rationale"] = nv
                    fixes += 1
    return fixes


# --- Fed "rate hike" language correction -----------------------------------
# The report has no rate-expectations feed, and in the current regime the Fed is not
# expected to HIKE — the live debate is cuts vs. higher-for-longer. Regression 2026-06-02:
# "Fed hike expectations returned/renewed" across fixed_income/currencies/economics/
# session_recap. Reframe to the defensible "higher-for-longer" (preserving the hawkish
# polarity that matched the day's +yield/+dollar). Idempotent — leaves no "hike" to re-hit.
_FED_HIKE_SUBS = [
    # "interest rate hike" is a COMPOUND — the bare `rate hikes?` rule below strips only
    # "rate hike" and orphans "interest", yielding the ungrammatical "...Federal Reserve
    # interest higher-for-longer rates..." (2026-06-23). Capture the whole compound first so
    # the reframe reads cleanly; idempotent (leaves "rate path", no "hike" to re-hit).
    (re.compile(r"\binterest[\-\s]?rate\s+hikes?\b", re.IGNORECASE),
     "higher-for-longer rate path"),
    (re.compile(r"\b(?:renewed|rising|growing|fresh)\s+(?:rate[\-\s]?hike|fed[\-\s]?hike|hike)\s+expectations\b", re.IGNORECASE),
     "renewed higher-for-longer rate expectations"),
    (re.compile(r"\b(?:rate[\-\s]?hike|fed[\-\s]?hike|hike)\s+expectations\b", re.IGNORECASE),
     "higher-for-longer rate expectations"),
    (re.compile(r"\b(?:rate[\-\s]?hike|hike)\s+fears\b", re.IGNORECASE),
     "higher-for-longer rate concerns"),
    (re.compile(r"\b(?:rate[\-\s]?hike|hike)\s+bias\b", re.IGNORECASE),
     "higher-for-longer bias"),
    (re.compile(r"\bfed\s+rate\s+hikes?\b", re.IGNORECASE),
     "a higher-for-longer Fed stance"),
    # Split singular vs plural: the SINGULAR "rate hike" is a discrete event and usually
    # carries a determiner ("a potential rate hike", "the next scheduled rate hike"), so the
    # plural "higher-for-longer rates" orphaned it into nonsense (2026-06-24: "a potential
    # higher-for-longer rates", "the next scheduled higher-for-longer rates"). The singular
    # state-noun "rate path" reads cleanly under any determiner; reserve the plural for the
    # bare plural "rate hikes". (\b after "hike" keeps the singular rule off "hikes".)
    (re.compile(r"\brate\s+hikes\b", re.IGNORECASE),
     "higher-for-longer rates"),
    (re.compile(r"\brate\s+hike\b", re.IGNORECASE),
     "higher-for-longer rate path"),
]


def _correct_fed_hike_language(data: dict) -> int:
    """Reframe unsupported Fed rate-HIKE claims as 'higher-for-longer'. Mutates in place.
    Capitalizes the replacement only at a sentence start (the matched token is often the
    proper noun 'Fed', which must not force a mid-sentence capital)."""
    def _fix(text: str) -> str:
        for rx, repl in _FED_HIKE_SUBS:
            def _sub(m, r=repl, _t=text):
                prev = _t[:m.start()].rstrip()
                at_start = (not prev) or prev[-1] in ".!?:"
                return (r[0].upper() + r[1:]) if at_start else r
            text = rx.sub(_sub, text)
        return text
    return _map_all_prose(data, _fix)


# --- foreign-macro trivia scrub (Fix: US econ recap polluted by foreign data) -
# economics_commentary must recap U.S. releases from recent_macro_prints; foreign
# context belongs in international_section. Regression 2026-06-02: the econ recap led
# with "Australian government spending flat in Q1". Drop any sentence whose subject is a
# foreign economy's macro release.
_FOREIGN_ECON_RE = re.compile(
    r"\b(?:australia|australian|china|chinese|japan|japanese|europe|european|eurozone|germany|"
    r"german|france|french|u\.?k\.?|british|britain|canada|canadian|india|indian|brazil|"
    r"brazilian|mexico|mexican|korea|korean|spain|spanish|italy|italian)\b",
    re.IGNORECASE)
_MACRO_NOUN_RE = re.compile(
    r"\b(?:spending|gdp|inflation|cpi|ppi|pmi|retail\s+sales|industrial\s+production|output|"
    r"unemployment|payrolls?|jobless|sentiment|trade\s+balance|current\s+account|"
    r"manufacturing|services\s+index|housing\s+starts|exports?|imports?)\b",
    re.IGNORECASE)


def _scrub_foreign_macro_lead(data: dict) -> int:
    """Drop foreign-economy macro-data sentences from economics_commentary (US-centric)."""
    text = data.get("economics_commentary")
    if not isinstance(text, str) or not text:
        return 0
    kept, changed = [], False
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if _FOREIGN_ECON_RE.search(sent) and _MACRO_NOUN_RE.search(sent):
            changed = True
            continue
        kept.append(sent)
    if changed:
        data["economics_commentary"] = " ".join(kept).strip()
        return 1
    return 0


# --- safe-haven causal-inversion scrub -------------------------------------
# A risk/volatility driver pushes capital TOWARD safe havens, not toward equities/oil.
# Regression 2026-06-02 session_recap: "Gold fell ... as a stronger dollar and geopolitical
# volatility drove investors toward oil and equities" — geopolitical volatility driving a
# risk-ON rotation is reversed. Strip the offending trailing clause (keep the factual lead).
_SAFE_HAVEN_DRIVER_RE = re.compile(
    r"\b(?:geopolitical\s+(?:volatility|risk|tension|uncertainty|turmoil)|"
    r"safe[\-\s]haven\s+(?:demand|buying)|risk[\-\s]off|war\s+fears?|escalat\w+)\b",
    re.IGNORECASE)
_RISK_ON_TARGET_RE = re.compile(
    r"\b(?:drove|driving|pushed|pushing|sent|sending|steer\w+|propell\w+|lured?|luring)\b"
    r"[^.;]{0,40}\b(?:toward|towards|into)\b[^.;]{0,40}"
    r"\b(?:equit|stocks?|oil|crude|risk\s+assets?|cyclical)",
    re.IGNORECASE)
_SAFE_HAVEN_CLAUSE_BOUNDARY_RE = re.compile(
    r"\s+(?:as|amid|because|since|with|while)\b", re.IGNORECASE)


def _scrub_safe_haven_inversion(data: dict) -> int:
    """Remove reversed safe-haven causality (risk driver -> risk-on rotation)."""
    def _clean(sent: str):
        if not (_SAFE_HAVEN_DRIVER_RE.search(sent) and _RISK_ON_TARGET_RE.search(sent)):
            return sent
        best = None
        for m in _SAFE_HAVEN_CLAUSE_BOUNDARY_RE.finditer(sent):
            head, tail = sent[:m.start()], sent[m.start():]
            if (_SAFE_HAVEN_DRIVER_RE.search(tail) and _RISK_ON_TARGET_RE.search(tail)
                    and not _SAFE_HAVEN_DRIVER_RE.search(head) and len(head.strip()) > 15):
                best = m.start()
        if best is not None:
            h = sent[:best].rstrip(" ,;:")
            return (h + ".") if h and h[-1] not in ".!?" else h
        return None  # whole sentence is the inversion → drop

    fixes = 0
    for field in ("equities_commentary", "commodities_commentary", "currencies_commentary",
                  "market_outlook_rationale", "cross_asset_synthesis"):
        text = data.get(field)
        if not isinstance(text, str) or not text:
            continue
        kept = [cs for sent in re.split(r"(?<=[.!?])\s+", text) if (cs := _clean(sent))]
        nv = " ".join(kept).strip()
        if nv != text:
            data[field] = nv
            fixes += 1
    recap = data.get("session_recap")
    if isinstance(recap, list):
        new = [(_clean(s) if isinstance(s, str) else s) for s in recap]
        new = [s for s in new if s]
        if new != recap:
            data["session_recap"] = new
            fixes += 1
    return fixes


# --- off-universe currency scrub ----------------------------------------------
# Regression 2026-06-17: currencies_commentary appended "with the ringgit opening higher
# against the US dollar on Fed hold expectations" — the Malaysian ringgit is not in the report's
# currency universe (USD/DXY, EUR, GBP, JPY, CAD, AUD, BRL, BTC), just headline-scrape noise
# pulled into a US-centric FX section. Trim the clause naming a peripheral off-universe currency
# (keep the factual head). Scoped to currencies_commentary only — international_section may
# legitimately discuss foreign FX. The list excludes yuan/renminbi/franc/krona (majors-adjacent,
# can be genuinely relevant) to avoid over-stripping.
_OFFUNIVERSE_CCY_RE = re.compile(
    r"\b(ringgit|peso|pesos|rupee|rupees|rupiah|lira|liras|won|rand|zloty|baht|forint|"
    r"shekel|shekels|koruna|dong|naira|hryvnia|ruble|rubles|rouble|roubles)\b",
    re.IGNORECASE)
_CCY_CLAUSE_BOUNDARY_RE = re.compile(
    r"\s+(?:with|as|while|and|,|;)\s+", re.IGNORECASE)


def _scrub_offuniverse_currency(data: dict) -> int:
    """Trim clauses naming an off-universe currency from currencies_commentary."""
    def _clean(sent: str):
        if not _OFFUNIVERSE_CCY_RE.search(sent):
            return sent
        best = None
        for m in _CCY_CLAUSE_BOUNDARY_RE.finditer(sent):
            head, tail = sent[:m.start()], sent[m.start():]
            if (_OFFUNIVERSE_CCY_RE.search(tail) and not _OFFUNIVERSE_CCY_RE.search(head)
                    and len(head.strip()) > 20):
                best = m.start()
        if best is not None:
            h = sent[:best].rstrip(" ,;:")
            return (h + ".") if h and h[-1] not in ".!?" else h
        return None  # whole sentence is the off-universe aside → drop it

    text = data.get("currencies_commentary")
    if not isinstance(text, str) or not text:
        return 0
    kept = [cs for sent in re.split(r"(?<=[.!?])\s+", text) if (cs := _clean(sent))]
    nv = " ".join(kept).strip()
    if nv != text:
        data["currencies_commentary"] = nv
        return 1
    return 0


# --- off-topic emerging-market-bond scrub -------------------------------------
# 2026-06-29: a real but NICHE wire item ("Hawkish Fed throws down challenge for the EM bond
# rally" / "Warsh disrupts emerging-market bond recovery") was elevated into the PRIMARY driver
# of a FLAT US tape — the session-recap LEAD pinned the S&P's -0.05% on "Warsh disrupted
# emerging-market bond recovery," and the Commodities and US-Dollar asset-class outlooks both
# CLOSED on "the Fed's challenge to emerging-market bond rallies," a non-sequitur for crude and
# DXY. EM debt is off-universe for US equities, commodities, and the dollar: Fed hawkishness
# belongs in those sections as its US effect (firmer-for-longer yields, growth-multiple pressure,
# a firmer dollar), not an EM-bond storyline. Trim the trailing EM-bond clause (keep the factual
# head); drop a whole sentence that is ONLY the EM-bond aside. fixed_income_commentary is EXEMPT
# (Fed rate-path context there is legitimate). Mirrors _scrub_offuniverse_currency.
_EM_BOND_RE = re.compile(
    r"\b(?:emerging[-\s]?market|EM)\s+(?:bond|debt|local[-\s]?currency)\w*",
    re.IGNORECASE)
_EM_CLAUSE_BOUNDARY_RE = re.compile(
    r"(?:\s+(?:as|with|while|and|that|which|given|amid)\s+|,\s+|;\s+)", re.IGNORECASE)


def _em_clean_sentence(sent: str):
    """Trim a trailing EM-bond clause from one sentence; None = whole sentence is the aside."""
    if not _EM_BOND_RE.search(sent):
        return sent
    best = None
    for m in _EM_CLAUSE_BOUNDARY_RE.finditer(sent):
        head, tail = sent[:m.start()], sent[m.start():]
        if (_EM_BOND_RE.search(tail) and not _EM_BOND_RE.search(head)
                and len(head.strip()) > 20):
            best = m.start()
    if best is not None:
        h = sent[:best].rstrip(" ,;:")
        return (h + ".") if h and h[-1] not in ".!?" else h
    return None  # whole sentence is the EM-bond aside → drop it


def _em_clean_text(text):
    """Sentence-wise EM-bond trim for a prose field; returns (new_text, changed)."""
    if not isinstance(text, str) or not text or not _EM_BOND_RE.search(text):
        return text, False
    kept = [cs for sent in re.split(r"(?<=[.!?])\s+", text)
            if (cs := _em_clean_sentence(sent))]
    nv = " ".join(kept).strip()
    return (nv, True) if nv != text else (text, False)


def _scrub_offtopic_em_bonds(data: dict) -> int:
    """Trim off-topic emerging-market-bond clauses from US-asset sections. Non-failing."""
    n = 0
    # Prose fields where EM debt is off-universe (NOT fixed_income — Fed context legitimate there).
    for key in ("commodities_commentary", "currencies_commentary", "market_outlook_rationale",
                "cross_asset_synthesis"):
        nv, changed = _em_clean_text(data.get(key))
        if changed:
            data[key] = nv
            n += 1
    # Asset-class outlook rationales: only Commodities / US Dollar (Equities/Fixed Income exempt).
    aco = data.get("asset_class_outlooks")
    if isinstance(aco, dict):
        for cls in ("Commodities", "US Dollar"):
            row = aco.get(cls)
            if isinstance(row, dict):
                nv, changed = _em_clean_text(row.get("rationale"))
                if changed:
                    row["rationale"] = nv
                    n += 1
    # session_recap bullets: trim the EM-bond causal clause but never drop a whole bullet
    # (each leads with the index level — losing it would blank the recap line).
    recap = data.get("session_recap")
    if isinstance(recap, list):
        for i, bullet in enumerate(recap):
            if not isinstance(bullet, str):
                continue
            trimmed = _em_clean_sentence(bullet)
            if trimmed is not None and trimmed != bullet:
                recap[i] = trimmed
                n += 1
    return n


# --- "Tomorrow's <event>" / "Friday's <event>" slip when the event is actually today ----
# The scenarios block carries the canonical event timing (scenario_event_day). When that is
# "today" but the synthesis prose calls the same event "tomorrow's", the reader sees a
# temporal contradiction side-by-side (2026-06-04: "Tomorrow's Initial Jobless Claims" in
# Today's Take while the Scenarios header, econ calendar, and What-to-Watch all said today).
# 2026-06-18 extension: the prose also attached the WRONG WEEKDAY NAME — "Friday's Philly Fed"
# when Philly Fed printed today/Thursday (and Fri 6/19 was Juneteenth, market closed). We
# rewrite a weekday possessive near a TODAY event to "today's" — but ONLY when that weekday
# isn't today's actual weekday, so a legitimately-correct "Friday's <event>" on a Friday is
# left alone. Only the unambiguous today-case is corrected; a genuinely future event is left
# alone, and a reference to a different (truly later) event is never touched (proximity gated).
_WEEKDAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _correct_event_day_slip(data: dict) -> int:
    event = str(data.get("scenario_event") or "").strip()
    day = str(data.get("scenario_event_day") or "").strip().lower()
    if not event or day not in ("", "today"):
        return 0
    ev_rx = re.compile(re.escape(event), re.IGNORECASE)
    tom_rx = re.compile(r"\btomorrow(?:'s|’s)?\b", re.IGNORECASE)
    # Weekday-name possessive corrector — gated on a confirmed "today" event (not the empty
    # case, since an unknown day can't disprove a weekday name) and on knowing today's weekday.
    wd_rx = None
    if day == "today":
        _today_wd = ""
        try:
            from datetime import date as _date
            _rd = str(data.get("report_date") or data.get("narrative_source_date") or "")[:10]
            if _rd:
                _today_wd = _date.fromisoformat(_rd).strftime("%A").lower()
        except Exception:
            _today_wd = ""
        _wrong = [w for w in _WEEKDAY_NAMES if w != _today_wd]
        if _wrong:
            wd_rx = re.compile(r"\b(" + "|".join(_wrong) + r")(?:'s|’s)\b", re.IGNORECASE)

    def _fix(text: str) -> str:
        if not ev_rx.search(text):
            return text
        spans = [m.span() for m in ev_rx.finditer(text)]

        def _near_event(pos: int) -> bool:
            return any(s - 50 <= pos <= e + 50 for s, e in spans)

        def _event_just_after(end: int) -> bool:
            # An event mention starts within ~25 chars AFTER this token — i.e. the token is a
            # day-label modifying the event ("Friday's Philly Fed"), not a stray nearby weekday.
            return any(end <= s <= end + 25 for s, e in spans)

        def _replace(rx, target: str, forward_only: bool = False) -> None:
            """Rewrite the day word in tokens matched by `rx` to `target`, preserving the
            possessive suffix ('s / ’s) and lead capitalization. `forward_only` restricts the
            match to a day-label that DIRECTLY precedes the event (avoids rewriting a different
            day legitimately mentioned nearby)."""
            nonlocal text
            out, last = [], 0
            for m in rx.finditer(text):
                ok = _event_just_after(m.end()) if forward_only else _near_event(m.start())
                if not ok:
                    continue
                tok = m.group(0)
                mposs = re.search(r"(['’]s)$", tok)        # trailing possessive, if any
                suffix = mposs.group(1) if mposs else ""
                repl = (target.capitalize() if tok[0].isupper() else target) + suffix
                out.append(text[last:m.start()])
                out.append(repl)
                last = m.end()
            out.append(text[last:])
            text = "".join(out)

        _replace(tom_rx, "today")                          # tomorrow → today (proximity)
        if wd_rx is not None:
            _replace(wd_rx, "today", forward_only=True)    # "Friday's <event>" → "today's <event>"
        return text

    return _map_all_prose(data, _fix)


# --- TODAY-scheduled econ-event weekday corrector -----------------------------
# _correct_event_day_slip only rewrites a wrong weekday possessive sitting next to the
# SCENARIO event, and only fires when scenario_event_day is itself "today". So when the
# scenario's primary catalyst is a LATER event (2026-06-30: ADP on Wednesday), a
# "Friday's FHFA House Price Index and JOLTS Job Openings" slip in the synthesis /
# Today's-Take went uncorrected — FHFA and JOLTS both printed THAT day (Tuesday). This
# corrector is independent of the scenario event: it keys on the economic-calendar events
# dated today and rewrites a wrong weekday possessive that DIRECTLY precedes one of those
# event names to "today's". Best-effort and non-failing (silently no-ops on any error or
# a missing/empty calendar); proximity-gated so a genuinely later "Thursday's NFP" is left
# alone, and a possessive that is actually today's weekday is never a candidate.
def _correct_today_econ_event_weekday(data: dict) -> int:
    try:
        from datetime import date as _date
        _rd = str(data.get("report_date") or data.get("narrative_source_date") or "")[:10]
        if not _rd:
            _rd = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_iso = _rd
        today_wd = _date.fromisoformat(_rd).strftime("%A").lower()
    except Exception:
        return 0
    wrong = [w for w in _WEEKDAY_NAMES if w != today_wd]
    if not wrong:
        return 0

    names: list[str] = []
    try:
        cal_path = DATA_DIR / "economic_calendar.json"
        if cal_path.exists():
            with open(cal_path, "r", encoding="utf-8") as f:
                cal = json.load(f)
            for ev_obj in (cal.get("events") or []):
                if str(ev_obj.get("date", ""))[:10] == today_iso:
                    nm = str(ev_obj.get("event", "")).strip()
                    if len(nm) >= 4:
                        names.append(nm)
    except Exception:
        return 0
    if not names:
        return 0

    wd_rx = re.compile(r"\b(" + "|".join(wrong) + r")(['’]s)\b", re.IGNORECASE)
    ev_res = [re.compile(re.escape(nm), re.IGNORECASE) for nm in names]

    def _fix(text: str) -> str:
        if not wd_rx.search(text):
            return text
        spans = [m.span() for rx in ev_res for m in rx.finditer(text)]
        if not spans:
            return text

        def _event_just_after(end: int) -> bool:
            # The event name starts within ~25 chars AFTER the weekday token — i.e. the
            # weekday is a day-label modifying THIS event ("Friday's FHFA …"), not a stray
            # nearby weekday.
            return any(end <= s <= end + 25 for s, _e in spans)

        out, last = [], 0
        for m in wd_rx.finditer(text):
            if not _event_just_after(m.end()):
                continue
            repl = ("Today" if m.group(1)[:1].isupper() else "today") + m.group(2)
            out.append(text[last:m.start()])
            out.append(repl)
            last = m.end()
        out.append(text[last:])
        return "".join(out)

    return _map_all_prose(data, _fix)


# --- FUTURE econ-event weekday corrector --------------------------------------
# _correct_today_econ_event_weekday fixes a wrong weekday on events dated TODAY. A wrong
# weekday on a FUTURE event slips both it and _correct_event_day_slip (2026-07-01: prose
# said "Friday's Non-Farm Payrolls" but NFP was Thursday 7/2 — a holiday-shortened week
# moved it off the usual Friday; the calendar had it right, the prose didn't). This corrector
# keys on economic-calendar events dated in the near future (within ~7 days) and rewrites a
# weekday possessive that DIRECTLY precedes the event name to the event's ACTUAL weekday when
# they disagree. Leaves a correct weekday alone; proximity-gated so an unrelated nearby weekday
# is untouched. Best-effort and non-failing.
def _correct_future_econ_event_weekday(data: dict) -> int:
    try:
        from datetime import date as _date
        _rd = str(data.get("report_date") or data.get("narrative_source_date") or "")[:10]
        if not _rd:
            _rd = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_dt = _date.fromisoformat(_rd)
    except Exception:
        return 0

    # event name (lowercased) -> (correct weekday lowercase, original-cased name)
    ev_correct: dict[str, tuple[str, str]] = {}
    try:
        cal_path = DATA_DIR / "economic_calendar.json"
        if not cal_path.exists():
            return 0
        cal = json.loads(cal_path.read_text(encoding="utf-8"))
        rows = []
        for ev_obj in (cal.get("events") or []):
            d = str(ev_obj.get("date", ""))[:10]
            nm = str(ev_obj.get("event", "")).strip()
            if len(nm) < 4 or not d:
                continue
            try:
                dd = _date.fromisoformat(d)
            except ValueError:
                continue
            if dd <= today_dt or (dd - today_dt).days > 7:
                continue  # today/past → other corrector; >1 week out → don't hijack the label
            rows.append((dd, nm))
        for dd, nm in sorted(rows):        # nearest future occurrence per event name wins
            ev_correct.setdefault(nm.lower(), (dd.strftime("%A").lower(), nm))
    except Exception:
        return 0
    if not ev_correct:
        return 0

    wd_rx = re.compile(r"\b(" + "|".join(_WEEKDAY_NAMES) + r")(['’]s)\b", re.IGNORECASE)

    def _name_variants(nm: str) -> list[str]:
        # The calendar name and the prose phrasing often differ by an agency prefix
        # (2026-07-06: calendar 'Fed FOMC Minutes' vs prose "Thursday's FOMC minutes"
        # slipped the exact-substring match). Register a prefix-stripped core variant
        # so the possessive weekday still binds to the event.
        out = [nm]
        core = re.sub(r"^(?:the\s+|u\.?s\.?\s+|fed\s+)+", "", nm, flags=re.IGNORECASE).strip()
        if core and core.lower() != nm.lower() and len(core) >= 4:
            out.append(core)
        # Leading acronym: prose abbreviates a report to its acronym ("CPI Inflation Report"
        # -> "Thursday's CPI print"), which neither the full name nor the prefix-stripped core
        # substring-matches. Register a 3-6 char leading acronym so the possessive weekday
        # still binds (2026-07-10: "Thursday's CPI" survived while CPI was Tuesday).
        acro = re.match(r"^([A-Z]{3,6})\b", nm)
        if acro:
            out.append(acro.group(1))
        return out

    ev_items = [
        (re.compile(re.escape(var), re.IGNORECASE), cwd)
        for (cwd, nm) in ev_correct.values()
        for var in _name_variants(nm)
    ]

    # Plain (non-possessive) weekday, for the weekday-AFTER-event form; excludes the
    # possessive so a token is handled by exactly one pass.
    wd_plain_rx = re.compile(r"\b(" + "|".join(_WEEKDAY_NAMES) + r")\b(?![’'`]s)", re.IGNORECASE)
    # The gap between an event name and a trailing weekday must be ONLY scheduling filler
    # ("... scheduled for Thursday", "... is due Thursday", "... on Thursday") — this gates
    # the after-event pass so an unrelated later weekday is never rewritten.
    _SCHED_GAP_RE = re.compile(
        r"^[\s,]*(?:is\s+|are\s+|will\s+be\s+|be\s+)?"
        r"(?:scheduled|slated|set|planned|due|expected|coming(?:\s+up)?|out|held|"
        r"released|reported|happening)?[\s,]*(?:for|on|out|this|next)?[\s,]*$",
        re.IGNORECASE)

    def _fix(text: str) -> str:
        ev_occ = [(m.start(), m.end(), cwd) for rx, cwd in ev_items for m in rx.finditer(text)]
        if not ev_occ:
            return text
        fixes: list[tuple[int, int, str]] = []
        # Pass A — possessive weekday BEFORE the event ("Thursday's FOMC minutes").
        for m in wd_rx.finditer(text):
            correct = next((cwd for (s, e, cwd) in ev_occ if m.end() <= s <= m.end() + 25), None)
            if correct and m.group(1).lower() != correct:
                repl = (correct.capitalize() if m.group(1)[:1].isupper() else correct) + m.group(2)
                fixes.append((m.start(), m.end(), repl))
        # Pass B — plain weekday AFTER the event, linked by a scheduling phrase
        #   ("Fed FOMC Minutes scheduled for Thursday"). 2026-07-07 blind spot.
        for m in wd_plain_rx.finditer(text):
            correct = next(
                (cwd for (s, e, cwd) in ev_occ
                 if e <= m.start() <= e + 40 and _SCHED_GAP_RE.match(text[e:m.start()])),
                None)
            if correct and m.group(1).lower() != correct:
                repl = correct.capitalize() if m.group(1)[:1].isupper() else correct
                fixes.append((m.start(), m.end(), repl))
        if not fixes:
            return text
        fixes.sort()
        out, last = [], 0
        for s, e, repl in fixes:
            if s < last:
                continue  # overlap guard
            out.append(text[last:s])
            out.append(repl)
            last = e
        out.append(text[last:])
        return "".join(out)

    return _map_all_prose(data, _fix)


# --- #3 belt-and-suspenders: same-day tactical stance vs multi-week outlook ----
# The deterministic Quant Tactical Read (tactical_positioning.stance) is a SAME-DAY
# sector-tilt read; market_outlook_label is the LLM's 4-6 week equity view. They can
# legitimately diverge — a one-session bounce inside a bearish regime — but a bald
# "Risk-on, pro-cyclical" badge sitting beside a "Bearish" stamp reads as a
# self-contradiction (2026-06-18: "Quant Tactical Read: RISK-ON ... Tech leading +2.5%"
# under a BEARISH stance stamped everywhere else). Item #2 (sector-data integrity) fixes
# the usual root cause — stale/partial sector bars flipping the stance — but when a genuine
# one-day move still points opposite the multi-week call, append a one-clause reconciliation
# to stance_detail framing it as a single session within the multi-week view, rather than
# forcing the two horizons to agree. Same philosophy as the trailing-1M-vs-today factor_read
# reconciliation already in build_tactical_positioning.
def _reconcile_tactical_stance_with_outlook(data: dict) -> int:
    tp = data.get("tactical_positioning")
    if not isinstance(tp, dict):
        return 0
    stance = str(tp.get("stance") or "").strip()
    label_raw = str(data.get("market_outlook_label") or "").strip()
    if not stance or not label_raw:
        return 0
    low = stance.lower()
    label = label_raw.lower()
    tactical_riskon  = low.startswith(("risk-on", "pro-cyclical"))
    tactical_riskoff = low.startswith(("risk-off", "defensive"))
    label_bear = label in ("bearish", "cautious")
    label_bull = label == "bullish"
    conflict = (tactical_riskon and label_bear) or (tactical_riskoff and label_bull)
    if not conflict:
        return 0
    note = (f" Note: this is a single-session sector tilt; the {label_raw} call is the "
            f"4-6 week view.")
    detail = str(tp.get("stance_detail") or "").rstrip()
    if note.strip() in detail:
        return 0
    tp["stance_detail"] = (detail + note) if detail else note.strip()
    return 1


# --- ungrounded Fed-official attribution scrub --------------------------------
# The report has no Fed-speech transcript feed. Attributing a specific market signal to a
# named official who never appears in the source-headline corpus is fabrication (2026-06-04:
# "Fed President Beth Hammack signaled higher-for-longer" across fixed_income / economics /
# outlook / Today's Take, with no Hammack mention anywhere in the headlines). Names that ARE
# grounded — present in the headlines or on today's scheduled-speaker list — are left intact.
# Ungrounded names are de-personalized to "Fed officials" / "the Fed" (possessive), preserving
# the surrounding (data-consistent) hawkish/dovish framing.
_FED_SURNAMES = (
    "Powell", "Warsh", "Waller", "Bowman", "Barkin", "Daly", "Williams", "Goolsbee",
    "Bostic", "Kashkari", "Logan", "Musalem", "Schmid", "Cook", "Jefferson", "Collins",
    "Kugler", "Hammack", "Mester", "Harker", "Barr",
)
_FED_TITLE = (r"(?:Fed(?:eral\s+Reserve)?\s+)?"
              r"(?:President|Chair(?:man)?|Governor|Vice\s+Chair(?:\s+for\s+Supervision)?)\s+")

# Tokens that confirm a surname mention is about the central bank (guards against
# collisions like Tim Cook / Serena Williams when harvesting speakers from the wire).
_FED_CONTEXT_TOKENS = ("fed", "federal reserve", "fomc", "central bank")
_FED_TIME_RE = re.compile(r"(\d{1,2}:\d{2}\s*(?:[ap]\.?m\.?)?(?:\s*ET)?)", re.IGNORECASE)
# A harvested row must describe an actual SPEAKING event, not just a news story that
# mentions an official. Regression 2026-06-05: "Fed's Warsh inherits economy increasingly
# squeezed by inflation ..." (a profile of the incoming chair) was harvested as a scheduled
# speaker. Require a speaking-context verb so profiles/analysis pieces are excluded.
_FED_SPEAK_TOKENS_RE = re.compile(
    r"\b(?:speak\w*|spoke|says?|said|remark\w*|comment(?:s|ed|ing)?|testif\w*|testimony|"
    r"address(?:es|ed|ing)?|speech\w*|panel|interview\w*|discuss\w*|told|q&a|"
    r"fireside|moderat\w*|deliver\w*)\b",
    re.IGNORECASE)
# A THIRD PARTY (a bank, analyst, strategist, executive...) commenting ABOUT a Fed official is
# not a Fed speaking event — the official is the OBJECT of someone else's remark, not the agent.
# Regression 2026-06-23: "JPMorgan Executive Says Fed Chair Kevin Warsh Could Raise Rates ..."
# was harvested as a "Fed's Warsh" speaker slot (Sevens correctly carried NO Fed speakers that
# day). Reject when a non-Fed firm/role is the subject of the speaking verb.
_THIRD_PARTY_SPEAKER_RE = re.compile(
    r"\b(?:JPMorgan|JP\s?Morgan|Goldman(?:\s+Sachs)?|Morgan\s+Stanley|Citi\w*|"
    r"Bank\s+of\s+America|BofA|Wells\s+Fargo|Barclays|UBS|Deutsche\s+Bank|Nomura|"
    r"BlackRock|Pimco|Vanguard|Fidelity|executive\w*|CEO|CIO|CFO|strateg\w*|"
    r"analyst\w*|investor\w*|trader\w*|hedge\s+fund\w*)\b"
    r"(?:\s+\w+){0,3}\s+(?:says?|said|sees?|expects?|predicts?|warns?|argues?|notes?|"
    r"suggests?|believes?|thinks?|forecasts?|claims?|told)\b",
    re.IGNORECASE)


# A genuine schedule/quote entry attributes the speaking verb to the OFFICIAL: the surname
# (optionally possessive) sits within ~2 words BEFORE the verb as its subject ("Fed's Daly
# says...", "Barkin speaks at 8:30", "Cook to deliver remarks"), or the verb precedes the
# surname in a "remarks by/from <surname>" / "speech by <surname>" frame. Regression
# 2026-06-24: "Fed's Warsh — The Dollar Just Hit A 13-Month High On Warsh's Hawkish Debut:
# History Says Don't" was harvested as a "Fed's Warsh" slot because the editorial "History
# Says" tripped the bare speak-token gate while Warsh was only NAMED, not the speaker
# (Sevens carried NO Fed speakers). Require the surname to be the verb's subject.
_FED_SPEAK_VERB = (r"(?:speak\w*|to\s+speak|spoke|says?|said|remark\w*|comment(?:s|ed|ing)?|"
                   r"testif\w*|testimony|address(?:es|ed|ing)?|speech\w*|interview\w*|"
                   r"discuss\w*|told|deliver\w*|moderat\w*|reiterat\w*|reaffirm\w*|"
                   r"notes?|noted|noting|signals?|signal(?:ed|ing)|warns?|warned|"
                   r"sees?|expects?|urges?|stress\w*|emphasiz\w*|downplay\w*|"
                   r"reassur\w*|argues?|argued|flag\w*|hints?|hinted)")


def _surname_is_speaker(text: str, surname: str) -> bool:
    """True when `surname` is the agent of a speaking event in `text` (not merely mentioned):
    subject-before-verb within a 0-3 word window ("Daly says", "Daly of the Fed speaks"),
    a colon attribution ("Fed's Daly: ..."), or a "remarks by/from <surname>" frame.
    A dash after the surname does NOT count — "Fed's Warsh — <market-action headline>" is an
    article ABOUT the official, not a quote (2026-06-24 regression)."""
    sn = re.escape(surname)
    subj_before = re.compile(
        r"\b" + sn + r"(?:'s|’s)?\b(?:\s+\w+){0,3}\s+" + _FED_SPEAK_VERB + r"\b",
        re.IGNORECASE)
    colon_attrib = re.compile(r"\b" + sn + r"(?:'s|’s)?\s*:", re.IGNORECASE)
    verb_before = re.compile(
        r"\b(?:remark\w*|comment\w*|speech\w*|testimony|address(?:es|ed|ing)?|interview\w*)\b"
        r"\s+(?:by|from)\s+(?:\w+\s+){0,2}" + sn + r"\b",
        re.IGNORECASE)
    return bool(subj_before.search(text) or colon_attrib.search(text) or verb_before.search(text))


# Common market-headline lead subjects. When one of these appears mid-topic (a lowercase
# word directly before it), it almost always marks where a SECOND wire headline was
# concatenated onto the first (2026-07-01: "...if inflation persists Stocks rise on Q2").
_HEADLINE_JOIN_RE = re.compile(
    r"\s+(?=(?:Stocks|Shares|Markets|Wall\s+Street|Wall\s+St|Dow|Nasdaq|S&P|Futures|"
    r"Oil|Crude|Gold|Silver|Copper|Bitcoin|Treasur\w+|Yields|Bonds|Dollar|Euro|"
    r"Asian|European|Equit\w+)\b)")


def _clean_fed_topic(text: str, surname: str) -> str:
    """Normalise a harvested Fed-speaker topic (a raw news headline) into a short, clean
    detail. Strips a redundant leading "Fed's <Surname> <verb>" (the row already labels the
    speaker), cuts a concatenated second headline, then a trailing sentence, then word-caps.
    Returns "" when nothing meaningful survives (caller drops the detail gracefully)."""
    t = re.sub(r"\s+", " ", str(text or "")).strip()
    # Drop a leading "the Fed's <Surname>" / "Fed <Surname>" plus an optional speaking verb.
    t = re.sub(rf"^(?:the\s+)?fed(?:'s|’s)?\s+{re.escape(surname)}\b[:,]?\s*", "", t, flags=re.I)
    t = re.sub(r"^(?:says?|said|speaks?|spoke|warns?|warned|notes?|noted|tells?|told|"
               r"signals?|signall?ed|comments?|adds?|added|states?|stated)\b[:,]?\s*",
               "", t, flags=re.I)
    # Cut a concatenated second headline ("...persists Stocks rise on Q2" -> "...persists").
    m = _HEADLINE_JOIN_RE.search(t)
    if m and m.start() > 0:
        t = t[:m.start()]
    # Cut at the first sentence boundary if one exists.
    ms = re.search(r"[.!?]", t)
    if ms:
        t = t[:ms.start()]
    words = t.split()
    if len(words) > 16:                       # backstop against a punctuation-less run-on
        t = " ".join(words[:16])
    return t.strip()


def _harvest_fed_speakers_from_news(headlines, existing_speakers=None) -> list[dict]:
    """Supplement the Governors-only calendar feed with regional reserve-bank presidents
    named in today's news wire.

    federalreserve.gov/json/calendar.json (the primary fetch_fed_speakers source) carries
    Board of Governors events only, so regional Fed presidents — Barkin/Richmond, Daly/SF,
    Musalem/St. Louis, etc. — never appear there even when they speak (2026-06-04: Sevens
    listed Barkin 8:30 + Daly 1:10; EPM had only Governor Bowman). There is no unified free
    feed of their schedules, but they routinely surface in the wire we already crawl
    ("Fed's Daly says...", "Richmond Fed President Barkin speaks at 8:30 a.m."). Scan for
    known surnames that co-occur with Fed context, dedupe against speakers we already have
    (by surname), and return supplemental rows shaped like the calendar feed.

    Returns list of {"speaker": "Fed's <Surname>", "time_et": str, "venue": "", "topic": str}.
    """
    rows: list[dict] = []
    if not headlines:
        return rows

    existing_surnames = set()
    for sp in (existing_speakers or []):
        who = str((sp.get("speaker", "") if isinstance(sp, dict) else sp) or "").lower()
        existing_surnames.update(n.lower() for n in _FED_SURNAMES if n.lower() in who)

    seen: set[str] = set()
    for raw in headlines:
        text = str(raw or "").strip()
        if not text:
            continue
        low = text.lower()
        if not any(tok in low for tok in _FED_CONTEXT_TOKENS):
            continue   # no central-bank context — skip (Tim Cook, Serena Williams, ...)
        if not _FED_SPEAK_TOKENS_RE.search(text):
            continue   # mentions an official but not a speaking event — skip profiles/analysis
        if _THIRD_PARTY_SPEAKER_RE.search(text):
            continue   # a bank/analyst/exec commenting ABOUT the Fed — not a Fed speaking event
        for surname in _FED_SURNAMES:
            sl = surname.lower()
            if sl in existing_surnames or sl in seen:
                continue
            if re.search(r"\b" + re.escape(sl) + r"\b", low) and _surname_is_speaker(text, surname):
                _m = _FED_TIME_RE.search(text)
                rows.append({
                    "speaker": f"Fed's {surname}",
                    "time_et": (_m.group(1).strip() if _m else ""),
                    "venue":   "",
                    "topic":   _clean_fed_topic(text, surname),
                })
                seen.add(sl)
    return rows


# --- global central-bank event harvester --------------------------------------
# The economic calendar is US-only by design (fetch_economic_calendar._SKIP_KEYWORDS
# explicitly drops "bank of japan", "key ecb", "swiss national bank", etc.), so a
# foreign central-bank DECISION never reaches the LLM through the calendar. Sevens
# leads its macro recap with these (2026-06-18/22: a BOJ 25bp hike to a 31-year high;
# EPM missed it both days). There is no unified free feed of global CB decisions, but
# they surface in the same news wire we already crawl ("BOJ raises rates to highest
# since 1995", "ECB holds, signals..."). Mirror the Fed-speaker harvest: scan the
# corpus for an institution token co-occurring with a policy-action token, dedupe by
# institution, and hand the LLM a structured list it must lead the international
# section with (and must not invent beyond).
# US-material majors only. RBI/RBNZ/Banxico are deliberately excluded: their decisions
# carry little US read-through and India/RBI is the dominant foreign-domestic NOISE in
# this wire (the existing _us_relevance_score already de-prioritizes it) — surfacing RBI
# commentary as a "must-lead" macro event would be worse than the status quo.
_GLOBAL_CB = {
    "BOJ":  ("bank of japan", "boj"),
    "ECB":  ("european central bank", "ecb"),
    "BoE":  ("bank of england", "boe"),
    "PBoC": ("people's bank of china", "people’s bank of china", "pboc"),
    "RBA":  ("reserve bank of australia", "rba"),
    "BoC":  ("bank of canada",),
    "SNB":  ("swiss national bank", "snb"),
}
# A DECISIVE policy action — an actual decision, not speculation or a preview. Bare
# nouns ("rate hike needs", "rate-cut bets") and conditionals ("might ease", "to hike
# next week", "will raise") are deliberately NOT matched: only past/present-decisive
# verbs, a basis-point move WITH a direction, or a milestone ("highest since / N-year
# high") count. This is what kept the 2026-06-22 RBI commentary ("potentially easing
# rate hike needs") out — speculative, no decisive verb.
_CB_DECISIVE_RE = re.compile(
    r"\b(?:hiked|hikes|raised|raises|cut|cuts|lowered|lowers|trimmed|slashed|"
    r"held|holds|kept|stood\s+pat|left\s+(?:rates?|policy)[^.;]{0,20}unchanged|"
    r"raised?\s+its?\s+benchmark|deliver\w+\s+(?:a\s+)?\d+\s*bps?)\b"
    r"|\b\d+\s*bps?\b[^.;]{0,15}\b(?:hike|cut|increase|reduction|rise|move|decision)\b"
    r"|\b(?:hike|cut|increase|reduction)\s+of\s+\d+\s*bps?\b"
    r"|\bhighest\s+since\b|\b\d+-year\s+high\b",
    re.IGNORECASE)


def _harvest_global_macro_from_news(news_buckets) -> list[dict]:
    """Extract foreign central-bank DECISIONS from the news corpus.

    Accepts the merged bucket dict (cat -> list[str]) or a flat list of headline
    strings. Returns up to 5 rows shaped {"institution","headline"} deduped by
    institution (first material mention wins). Requires a US-material major AND a
    DECISIVE action token in the same headline — speculative/preview chatter and
    low-relevance foreign-domestic CBs (RBI etc.) are screened out by construction."""
    if isinstance(news_buckets, dict):
        headlines = [h for items in news_buckets.values() for h in (items or [])]
    else:
        headlines = list(news_buckets or [])
    rows: list[dict] = []
    seen: set[str] = set()
    for raw in headlines:
        text = str(raw or "").strip()
        if not text or len(text) < 8:
            continue
        if not _CB_DECISIVE_RE.search(text):
            continue
        low = text.lower()
        for inst, tokens in _GLOBAL_CB.items():
            if inst in seen:
                continue
            if any(tok in low for tok in tokens):
                rows.append({"institution": inst, "headline": text[:200]})
                seen.add(inst)
                break
        if len(rows) >= 5:
            break
    return rows


def _scrub_ungrounded_fed_attribution(data: dict, source_text: str) -> int:
    src = (source_text or "").lower()
    grounded = {n.lower() for n in _FED_SURNAMES if n.lower() in src}
    for sp in (data.get("fed_speakers") or []):
        who = str(sp.get("speaker", "")).lower() if isinstance(sp, dict) else ""
        grounded.update(n.lower() for n in _FED_SURNAMES if n.lower() in who)
    targets = [n for n in _FED_SURNAMES if n.lower() not in grounded]
    if not targets:
        return 0

    def _repl(possessive: bool):
        # "the Fed" (singular) keeps subject-verb agreement intact ("the Fed signals/signaled");
        # capitalize only at a sentence start so a mid-sentence replacement stays lowercase.
        def _r(m):
            prev = m.string[:m.start()].rstrip()
            at_start = (not prev) or prev[-1] in ".!?:"
            return ("The Fed" if at_start else "the Fed") + ("'s" if possessive else "")
        return _r

    subs = []
    for surname in targets:
        subs.append((re.compile(
            r"\b(?:" + _FED_TITLE + r")?(?:[A-Z][a-z]+\s+)?" + surname + r"(?:'s|’s)\b"),
            _repl(True)))
        subs.append((re.compile(
            r"\b(?:" + _FED_TITLE + r")?(?:[A-Z][a-z]+\s+)?" + surname + r"\b"),
            _repl(False)))

    def _fix(text: str) -> str:
        for rx, repl in subs:
            text = rx.sub(repl, text)
        return text

    return _map_all_prose(data, _fix)


# --- ungrounded Wall-Street-figure attribution scrub --------------------------
# Mirror of the Fed scrub for non-Fed Street figures: the report has no analyst-note feed, so
# attributing a market view to a NAMED bank/asset-manager person who never appears in the source
# headlines is fabrication (2026-06-23: source carried only "JPMorgan Executive"; the prose
# invented "JPMorgan CIO Bob Michael suggests every meeting is now live"). The firm + a generic
# role are preserved; only the fabricated NAME is removed. A name that IS grounded in the source
# corpus (e.g. a quoted CEO) is left intact.
_STREET_FIRMS = (
    "JPMorgan", "JP Morgan", "Goldman Sachs", "Goldman", "Morgan Stanley", "Citigroup",
    "Citi", "Bank of America", "BofA", "Wells Fargo", "Barclays", "UBS", "Deutsche Bank",
    "Nomura", "BlackRock", "Pimco", "PIMCO", "Vanguard", "Fidelity", "State Street",
)
_STREET_TITLE = (r"(?:CEO|CIO|CFO|COO|chief\s+\w+\s+officer|chief\s+economist|"
                 r"chief\s+strategist|head\s+of\s+[\w\s]{3,30}?|strategist|economist|"
                 r"analyst|portfolio\s+manager)")
_STREET_NAME = r"[A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+"   # First [M.] Last


def _scrub_ungrounded_analyst_attribution(data: dict, source_text: str) -> int:
    """De-name a Wall-Street-figure attribution whose person-name is absent from the source
    headline corpus. Keeps the firm + a generic role; removes only the fabricated name."""
    src = (source_text or "").lower()
    if not src:
        return 0
    firm_alt = "|".join(re.escape(f) for f in _STREET_FIRMS)
    pat1 = re.compile(rf"\b(?P<firm>{firm_alt})\s+{_STREET_TITLE}\s+(?P<name>{_STREET_NAME})\b")
    pat2 = re.compile(rf"\b(?P<firm>{firm_alt})(?:'s|’s)\s+(?P<name>{_STREET_NAME})\b")
    pat3 = re.compile(rf"\b{_STREET_TITLE}\s+(?P<name>{_STREET_NAME})\s+(?:of|at)\s+(?P<firm>{firm_alt})\b")

    def _repl(m):
        # A name present in the source headlines is a real quote — leave the whole match intact.
        if m.group("name").split()[-1].lower() in src:
            return m.group(0)
        prev = m.string[:m.start()].rstrip()
        art = "A" if ((not prev) or prev[-1] in ".!?:") else "a"
        return f"{art} {m.group('firm')} executive"

    def _fix(text: str) -> str:
        for rx in (pat1, pat2, pat3):
            text = rx.sub(_repl, text)
        return text

    return _map_all_prose(data, _fix)


# --- fabricated readings for not-yet-released econ events ----------------------
# economics_commentary must recap RELEASED prints. Asserting an actual number for an event the
# report itself flags as upcoming (the scenario event, or a calendar event dated today/later)
# is fabrication (2026-06-04: "Initial Jobless Claims at 215k vs 210k prior" and "Nonfarm
# Payrolls reading at 115k missed 185k" — claims was that morning's event, payrolls the next
# day). Drop only sentences that BOTH name an upcoming indicator AND assert a value; previews
# ("...claims print at 10:00 AM ET to gauge...") carry no value and are kept.
_ECON_INDICATOR_RES = {
    "jobless_claims":      re.compile(r"\b(?:initial\s+)?jobless\s+claims\b|\bweekly\s+claims\b", re.I),
    "nonfarm_payrolls":    re.compile(r"\b(?:non[\-\s]?farm\s+payrolls?|nonfarm\s+payrolls?|jobs\s+report|jobs\s+data|payrolls?\s+report|employment\s+(?:situation|report|data))\b|\bNFP\b", re.I),
    "cpi":                 re.compile(r"\b(?:cpi|consumer\s+price\s+index)\b", re.I),
    "ppi":                 re.compile(r"\b(?:ppi|producer\s+price\s+index)\b", re.I),
    "pce":                 re.compile(r"\b(?:core\s+)?pce\b", re.I),
    "gdp":                 re.compile(r"\bgdp\b", re.I),
    "retail_sales":        re.compile(r"\bretail\s+sales\b", re.I),
    "ism_services":        re.compile(r"\bism\s+services?\b|\bservices\s+pmi\b", re.I),
    "ism_manufacturing":   re.compile(r"\bism\s+manufacturing\b|\bmanufacturing\s+pmi\b", re.I),
    "productivity":        re.compile(r"\bproductivity\b|\bunit\s+labor\s+costs?\b", re.I),
    "consumer_credit":     re.compile(r"\bconsumer\s+credit\b", re.I),
    "existing_home_sales": re.compile(r"\bexisting\s+home\s+sales\b", re.I),
    "consumer_sentiment":  re.compile(r"\bconsumer\s+sentiment\b|\bmichigan\s+sentiment\b", re.I),
    "durable_goods":       re.compile(r"\bdurable\s+goods\b", re.I),
    "jolts":               re.compile(r"\bjolts\b|\bjob\s+openings\b", re.I),
    "adp":                 re.compile(r"\badp\b", re.I),
}
# A sentence asserts a value if it carries a magnitude-with-unit, a "vs/from N" compare, an
# "N prior", or a beat/miss tied to a number. Clock times ("10:00 AM ET") never match.
_ECON_VALUE_RE = re.compile(
    r"\b\d[\d,]*\.?\d*\s*(?:k|m|bn|%|bps?|basis\s+points)\b"
    r"|\bvs\.?\s+\$?\d"
    r"|\bfrom\s+\$?\d[\d,]*\.?\d*\b"
    r"|\b\d[\d,]*\.?\d*\s+prior\b"
    r"|\b(?:missed|beat|came\s+in\s+at|printed\s+at|reading\s+(?:at|of))\b[^.]*\d",
    re.I)


def _upcoming_econ_keys(data: dict) -> set:
    """Canonical indicator keys the report treats as upcoming: the scenario event (a forward
    catalyst by construction) plus economic-calendar events dated today or later. The calendar
    read is best-effort and silently degrades to scenario-event-only on any error."""
    keys: set = set()
    ev = str(data.get("scenario_event") or "")
    if ev:
        keys.update(k for k, rx in _ECON_INDICATOR_RES.items() if rx.search(ev))
    today_iso = (str(data.get("report_date") or "")
                 or datetime.now(timezone.utc).strftime("%Y-%m-%d"))[:10]
    try:
        cal_path = DATA_DIR / "economic_calendar.json"
        if cal_path.exists():
            with open(cal_path, "r", encoding="utf-8") as f:
                cal = json.load(f)
            for ev_obj in (cal.get("events") or []):
                d_iso = str(ev_obj.get("date", ""))[:10]
                if d_iso and d_iso >= today_iso:
                    name = str(ev_obj.get("event", ""))
                    keys.update(k for k, rx in _ECON_INDICATOR_RES.items() if rx.search(name))
    except Exception:
        pass
    return keys


def _scrub_unreleased_econ_prints(data: dict) -> int:
    text = data.get("economics_commentary")
    if not isinstance(text, str) or not text:
        return 0
    upcoming = _upcoming_econ_keys(data)
    if not upcoming:
        return 0
    kept, changed = [], False
    for sent in re.split(r"(?<=[.!?])\s+", text):
        named = {k for k, rx in _ECON_INDICATOR_RES.items() if rx.search(sent)}
        if (named & upcoming) and _ECON_VALUE_RE.search(sent):
            changed = True
            continue
        kept.append(sent)
    if changed:
        data["economics_commentary"] = " ".join(kept).strip()
        return 1
    return 0


# --- past-session attribution to an UNRELEASED econ print --------------------
# _scrub_unreleased_econ_prints only drops VALUE claims in economics_commentary. A
# value-LESS causal attribution slips it, and session_recap/pre_market_bullets are
# never scanned at all. Regression 2026-06-05 session_recap: "S&P 500 closed higher
# ... driven by robust May nonfarm payrolls data" and "10-year yield fell 2 bp ... as
# the strong jobs report lifted yields" — but NFP was THAT day's unreleased scenario
# event. Pinning a PAST move on a not-yet-released print is always false. Strip the
# trailing causal clause that carries the upcoming-event reference, keep the factual
# lead. Sweeps every prose field + recap/bullet list (mirrors the geopolitics scrub).
_EVENT_ATTR_CONNECTOR_RE = re.compile(
    r"\s+(?:driven|fueled|fuelled|powered|propelled|buoyed|boosted|lifted|spurred|"
    r"dragged|pressured|weighed|helped|hurt)\s+(?:higher\s+|lower\s+)?by\b"
    r"|\s+(?:as|after|on|amid|following|reflecting|thanks\s+to|in\s+response\s+to|"
    r"in\s+the\s+wake\s+of|on\s+the\s+back\s+of)\b",
    re.IGNORECASE)


def _scrub_unreleased_event_attribution(data: dict) -> int:
    """Strip clauses that attribute a PAST move to an upcoming/unreleased econ release.

    Keyed on the same upcoming-indicator set as _scrub_unreleased_econ_prints (the
    scenario event + calendar events dated today-or-later). For each sentence that
    names an upcoming indicator in a trailing causal clause whose head does NOT, cut at
    the causal connector. Previews ("await the jobs report", "...at 8:30 AM ET") carry
    no causal connector and are left intact. Idempotent."""
    upcoming = _upcoming_econ_keys(data)
    if not upcoming:
        return 0
    up_res = [rx for k, rx in _ECON_INDICATOR_RES.items() if k in upcoming]

    def _names(s: str) -> bool:
        return any(rx.search(s) for rx in up_res)

    def _clean_sentence(sent: str) -> str:
        if not _names(sent):
            return sent
        for m in _EVENT_ATTR_CONNECTOR_RE.finditer(sent):
            head, tail = sent[:m.start()], sent[m.start():]
            if _names(tail) and not _names(head) and len(head.strip()) > 15:
                h = head.rstrip(" ,;:")
                if h and h[-1] not in ".!?":
                    h += "."
                return h
        return sent

    def _fix(text: str) -> str:
        return " ".join(_clean_sentence(s) for s in re.split(r"(?<=[.!?])\s+", text))

    return _map_all_prose(data, _fix)


# --- fabricated kinetic-attack detail scrub (#1b) ----------------------------
# Regression 2026-06-05 pre_market_bullets: "Iran fired warning missiles and drones at
# US warships in the Gulf of Oman" — a concrete kinetic claim whose specifics (warships,
# drones, missiles) appear NOWHERE in the source corpus, and which contradicts the
# dominant ceasefire/de-escalation signal. The off-narrative scrub only catches conflict
# ENTITIES absent from the corpus (Iran IS present here, so it slipped); this catches the
# specific WEAPON/TARGET detail that is absent. Grounded framing ("Gulf hostilities
# flared") uses corpus vocabulary and survives. Drops the offending clause/sentence.
_KINETIC_VERB_RE = re.compile(
    r"\b(?:fired|launch\w*|strik\w*|struck|attack\w*|bombard\w*|shell\w*|sank|"
    r"downed|seiz\w*|torpedo\w*)\b", re.IGNORECASE)
_KINETIC_NOUN_RES = [
    re.compile(r"\bwarships?\b", re.I), re.compile(r"\bdrones?\b", re.I),
    re.compile(r"\bmissiles?\b", re.I), re.compile(r"\brockets?\b", re.I),
    re.compile(r"\b(?:naval\s+)?vessels?\b", re.I), re.compile(r"\btankers?\b", re.I),
    re.compile(r"\b(?:aircraft\s+)?carriers?\b", re.I), re.compile(r"\bgunboats?\b", re.I),
]


# Clause boundaries to cut a fabricated kinetic clause at, preserving the grounded lead.
_KINETIC_CLAUSE_BOUNDARY_RE = re.compile(
    r";|,?\s+and\s+|\s+as\s+|\s+while\s+|\s+after\s+|\s+amid\s+|\s+following\s+|\s+with\s+",
    re.IGNORECASE)


def _scrub_fabricated_kinetic_detail(data: dict, source_text: str) -> int:
    """Drop kinetic-attack claims whose specific weapon/target noun is ungrounded.

    A claim is fabricated when an attack verb (fired/launched/struck/attacked/...) sits within
    ~60 chars before a concrete weapon/target noun (warships/drones/missiles/...) that appears
    NOWHERE in the source corpus. We find the ungrounded noun, confirm a nearby preceding verb,
    then cut at the clause boundary just before that verb — keeping the grounded lead
    ("WTI fell as Gulf hostilities flared") and dropping the hallucinated clause ("and Iranian
    attacks on U.S. warships..."). Operating on the raw string (not pre-split sentences) makes
    it robust to abbreviation periods like "U.S." that fool a naive sentence splitter
    (regression 2026-06-05: the warships clause survived because "U.S." split the sentence).
    Skipped when source_text is empty. Returns the number of fields/items changed."""
    src = (source_text or "").lower()
    ungrounded = [rx for rx in _KINETIC_NOUN_RES if not rx.search(src)]
    if not ungrounded:
        return 0

    def _clean_once(text: str) -> str:
        noun_pos = None
        for rx in ungrounded:
            m = rx.search(text)
            if m:
                noun_pos = m.start() if noun_pos is None else min(noun_pos, m.start())
        if noun_pos is None:
            return text
        # require a kinetic verb in the ~60 chars before the noun (same clause)
        verbs = list(_KINETIC_VERB_RE.finditer(text, max(0, noun_pos - 60), noun_pos))
        if not verbs:
            return text
        verb_pos = verbs[-1].start()
        # cut at the last clause boundary at/before the verb; keep the grounded head
        cut = None
        for b in _KINETIC_CLAUSE_BOUNDARY_RE.finditer(text):
            if b.start() <= verb_pos:
                cut = b.start()
            else:
                break
        if cut is not None and len(text[:cut].strip()) > 15:
            head = text[:cut].rstrip(" ,;:")
            if head and head[-1] not in ".!?":
                head += "."
            return head
        return ""  # no usable grounded lead → drop the whole item

    def _clean(text: str) -> str:
        for _ in range(4):                       # handle multiple fabricated clauses, bounded
            nxt = _clean_once(text)
            if nxt == text or not nxt:
                text = nxt
                break
            text = nxt
        return text.strip()

    fixes = 0
    for field in _ALL_PROSE_FIELDS:
        v = data.get(field)
        if isinstance(v, str) and v:
            nv = _clean(v)
            if nv != v:
                data[field] = nv
                fixes += 1
    for field in _ALL_PROSE_LISTS:
        lst = data.get(field)
        if isinstance(lst, list):
            new, changed = [], False
            for it in lst:
                if isinstance(it, str):
                    ni = _clean(it)
                    if ni != it:
                        changed = True
                    if ni:                       # drop fully-fabricated items
                        new.append(ni)
                else:
                    new.append(it)
            if changed:
                data[field] = new
                fixes += 1
    aco = data.get("asset_class_outlooks")
    if isinstance(aco, dict):
        for av in aco.values():
            if isinstance(av, dict) and isinstance(av.get("rationale"), str) and av["rationale"]:
                nv = _clean(av["rationale"])
                if nv != av["rationale"]:
                    av["rationale"] = nv
                    fixes += 1
    return fixes


# --- inverted yield-causality guard (2026-07-06) ------------------------------
# A yield RISE attributed to a SOFT/DOVISH/MISS data print is economically backwards:
# a data miss or cooling print is disinflationary and should push yields DOWN, not up.
# 2026-07-06 shipped "the 10-year yield rose 4 bp to 4.49% driven by the ISM Manufacturing
# PMI miss" (3x), inverting the day's key macro insight — the Sevens' lead feature was
# precisely that yields rose DESPITE soft data (a structural-inflation / rate-hike-cycle
# signal). We can't assert the true driver deterministically, so we EXCISE the inverted
# causal clause and leave the factual move. A yield rise paired with a HAWKISH driver
# ("strong jobs", "sticky inflation", "higher-for-longer") is deliberately left untouched.
_YIELD_NOUN_RE = re.compile(
    r"\b(?:\d{1,2}[\s-]?(?:year|yr)\b[\w\s-]{0,18}?yield|treasury\s+yield|bond\s+yields?|yields?\b)",
    re.IGNORECASE)
_YIELD_UP_RE = re.compile(
    r"\b(rose|rise|rises|rising|risen|climb\w*|jump\w*|gain\w*|advanc\w*|"
    r"spik\w*|higher|upward|firmer|lurch\w*)\b", re.IGNORECASE)
# Soft/dovish/miss drivers that should LOWER yields — pairing them as the CAUSE of a rise
# is the inversion. Hawkish drivers (strong/hot/sticky/robust) are deliberately absent so
# a correctly-attributed rise survives.
_SOFT_DRIVER_RE = re.compile(
    r"\b(miss(?:ed|es)?|soft(?:er)?|weak(?:er)?|cool(?:ing|er|ed)?|disappoint\w*|"
    r"downside|below[\s-]?(?:consensus|expectations|forecast)|dovish|slow(?:down|ing|er)?|"
    r"contraction|contracting|easing\s+inflation|falling\s+inflation|receding\s+inflation)\b",
    re.IGNORECASE)
_YIELD_CAUSE_CONNECTOR_RE = re.compile(
    r"[,\s]*\b(?:driven\s+by|on\s+the\s+back\s+of|owing\s+to|due\s+to|because\s+of|"
    r"thanks\s+to|led\s+by|fuel\w+\s+by|powered\s+by|reflecting|amid|following|after|as|on)\b",
    re.IGNORECASE)


def _scrub_inverted_yield_causation(data: dict) -> int:
    """Excise an inverted causal clause that attributes a yield RISE to a soft/dovish/miss
    data print (2026-07-06). Cuts the connector-to-clause-end tail (these clauses are
    sentence-terminal in practice), leaving the factual move. Hawkish drivers untouched."""
    def _fix(text: str) -> str:
        if not isinstance(text, str) or not text:
            return text
        out = []
        for sent in re.split(r"(?<=[.!?])\s+", text):
            m_up = _YIELD_UP_RE.search(sent)
            if not (m_up and _YIELD_NOUN_RE.search(sent)):
                out.append(sent)
                continue
            cut = None
            for cm in _YIELD_CAUSE_CONNECTOR_RE.finditer(sent, m_up.end()):
                clause = re.split(r"[.;]", sent[cm.end():cm.end() + 90], 1)[0]
                if _SOFT_DRIVER_RE.search(clause):
                    cut = cm.start()
                    break
            if cut is None:
                out.append(sent)
                continue
            head = sent[:cut].rstrip(" ,")
            term = re.search(r"[.!?]+$", sent)
            if head and head[-1] not in ".!?":
                head += term.group(0) if term else "."
            out.append(head)
        return " ".join(out)
    return _map_all_prose(data, _fix)


# --- econ-print direction guard (2026-07-07) ----------------------------------
# An economic print whose directional VERB contradicts its own month-over-month numbers.
# 2026-07-07 shipped "Nonfarm Payrolls surged to 57k vs 129k prior" — 57k < 129k, so the
# series FELL; "surged" is inverted (the email had it right: "fell 72k to 57k"). Only
# past-tense verbs, only against an explicit prior/previous baseline, only when both numbers
# parse in matching units — so an actual-vs-expectation beat ("beat 50k vs 45k expected") and
# unit-mismatched phrases are left alone.
_ECON_UP_PAST = ("surged", "jumped", "soared", "climbed", "rose", "spiked", "gained",
                 "accelerated", "rebounded", "increased", "grew", "advanced", "rallied")
_ECON_DOWN_PAST = ("fell", "dropped", "plunged", "slumped", "tumbled", "declined", "slid",
                   "sank", "cooled", "eased", "decreased", "shrank", "contracted",
                   "slipped", "retreated")
_ECON_UNIT_SCALE = {"": 1.0, "k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6,
                    "bn": 1e9, "b": 1e9, "billion": 1e9, "%": 1.0, "pt": 1.0, "pts": 1.0}
_ECON_DIR_RE = re.compile(
    r"\b(?P<verb>" + "|".join(_ECON_UP_PAST + _ECON_DOWN_PAST) + r")\b"
    r"(?:\s+\w+){0,3}?\s+to\s+\$?(?P<a>\d+(?:\.\d+)?)\s*(?P<au>k|m|bn|b|%|thousand|million|billion|pts?)?"
    r"[^.;]{0,40}?\b(?:vs\.?|versus|from|against|compared\s+(?:with|to))\s+"
    r"\$?(?P<b>\d+(?:\.\d+)?)\s*(?P<bu>k|m|bn|b|%|thousand|million|billion|pts?)?"
    r"[^.;]{0,20}?\b(?:prior|previous|last\s+month|a\s+month\s+earlier|earlier|the\s+prior\s+reading)\b",
    re.IGNORECASE)


def _correct_econ_print_direction(data: dict) -> int:
    """Flip an econ print's directional verb when it contradicts its own MoM numbers
    (2026-07-07: "payrolls surged to 57k vs 129k prior"). Case-preserving; conservative."""
    def _scale(unit: str | None) -> float | None:
        return _ECON_UNIT_SCALE.get((unit or "").lower())

    def _fix(text: str) -> str:
        def _sub(m: "re.Match") -> str:
            au, bu = _scale(m.group("au")), _scale(m.group("bu"))
            if au is None or bu is None or au != bu:
                return m.group(0)  # unknown/mismatched units — don't touch
            try:
                a = float(m.group("a")) * au
                b = float(m.group("b")) * bu
            except ValueError:
                return m.group(0)
            if a == b:
                return m.group(0)
            verb = m.group("verb")
            is_up = verb.lower() in _ECON_UP_PAST
            wrong = (is_up and a < b) or ((not is_up) and a > b)
            if not wrong:
                return m.group(0)
            repl = "fell" if is_up else "rose"
            if verb[:1].isupper():
                repl = repl.capitalize()
            return m.group(0)[:m.start("verb") - m.start(0)] + repl + \
                m.group(0)[m.end("verb") - m.start(0):]
        return _ECON_DIR_RE.sub(_sub, text)

    return _map_all_prose(data, _fix)


def sanitize_commentary(data: dict, snapshot: dict | None = None, source_text: str = "") -> int:
    """Run the full deterministic corrector/scrubber pass over a commentary dict.

    Idempotent and non-failing (never discards the narrative — only mutates prose to match
    the data). Wired into validate_commentary at generation AND into the PDF/email renderers
    as defense-in-depth, so the rendered report is sanitized even if a generation-time guard
    was bypassed (e.g. an older latest_commentary.json or a future schema change). Returns
    the total number of field-level corrections applied. `source_text` (headline corpus) is
    only needed for the off-narrative geopolitics scrub; it is skipped when empty."""
    total = 0
    if snapshot:
        total += _correct_sign_mismatches(data, snapshot)
        total += _correct_magnitude_mismatches(data, snapshot)
        total += _correct_yield_pct_to_bp(data, snapshot)
        total += _correct_direction_words(data, snapshot)
        total += _correct_dollar_direction(data, snapshot)
        total += _scrub_false_weekly_claims(data, snapshot)
        total += _scrub_flat_tape_risk_regime(data, snapshot)  # force 'mixed' on a flat tape
    total += _correct_yield_bp_magnitude(data)   # force tenor bp moves + slope/direction to the arbitrated curve
    total += _scrub_inverted_yield_causation(data)  # drop 'yield rose driven by soft data' inversions
    total += _dedup_repeated_words(data)          # collapse "higher higher-for-longer" style repeats
    total += _correct_econ_print_direction(data)  # flip econ verb that contradicts its MoM numbers
    total += _scrub_ungrounded_geo_causation(data)  # drop Iran causal clauses when geo read is unclear/absent
    total += _scrub_degenerate_repetition(data)
    total += _correct_fed_hike_language(data)
    total += _scrub_fabricated_corporate_actions(data)
    total += _scrub_foreign_macro_lead(data)
    total += _scrub_safe_haven_inversion(data)
    total += _scrub_offuniverse_currency(data)
    total += _scrub_offtopic_em_bonds(data)
    total += _correct_event_day_slip(data)
    total += _correct_today_econ_event_weekday(data)
    total += _correct_future_econ_event_weekday(data)
    total += _reconcile_tactical_stance_with_outlook(data)
    total += _scrub_unreleased_econ_prints(data)
    total += _scrub_unreleased_event_attribution(data)
    total += _strip_unanchored_scenario_thresholds(data.get("scenarios"), data.get("scenario_consensus"))
    if source_text:
        total += _scrub_offnarrative_geopolitics(data, source_text)
        total += _scrub_fabricated_kinetic_detail(data, source_text)
        total += _scrub_ungrounded_fed_attribution(data, source_text)
        total += _scrub_ungrounded_analyst_attribution(data, source_text)
    return total


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically via a temp file + os.replace to avoid partial writes."""
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _build_deterministic_market_commentary(
    snapshot: dict,
    commodities_tbl: list,
    currencies_tbl: list,
    bonds_tbl: list,
) -> dict:
    """Build plain-text market narrative from snapshot data when LLM is unavailable.

    Output is numerically consistent with the snapshot and passes validate_commentary
    when called with snapshot=None. Called as fallback when Ollama fails or times out.
    """
    def _pct(val: Any) -> float:
        try:
            return float(val)
        except (TypeError, ValueError):
            return 0.0

    def _lvl(val: Any, fmt: str = ",.2f") -> str:
        try:
            return format(float(val), fmt)
        except Exception:
            return "N/A"

    def _dir(pct: float, style: str = "generic") -> str:
        if style == "yield":
            if pct > 0.05:  return "rose"
            if pct < -0.05: return "fell"
            return "was little changed"
        if pct > 0.5:    return "rose"
        if pct > 0.1:    return "edged higher"
        if pct < -0.5:   return "fell"
        if pct < -0.1:   return "edged lower"
        return "was little changed"

    sp  = snapshot.get("S&P 500", {})
    ndx = snapshot.get("Nasdaq 100", {})
    wti = snapshot.get("WTI Crude", {})
    gld = snapshot.get("Gold", {})
    dxy = snapshot.get("U.S. Dollar (DXY)", {})
    tyr = snapshot.get("10-Yr Yield", {})

    sp_pct  = _pct(sp.get("pct_change"));  sp_lvl  = _lvl(sp.get("level"))
    ndx_pct = _pct(ndx.get("pct_change")); ndx_lvl = _lvl(ndx.get("level"))
    wti_pct = _pct(wti.get("pct_change")); wti_lvl = _lvl(wti.get("level"))
    gld_pct = _pct(gld.get("pct_change")); gld_lvl = _lvl(gld.get("level"))
    dxy_pct = _pct(dxy.get("pct_change")); dxy_lvl = _lvl(dxy.get("level"))
    tyr_pct = _pct(tyr.get("pct_change")); tyr_lvl = _lvl(tyr.get("level"), ".3f")

    return {
        "pre_market_bullets": [
            f"S&P 500 {_dir(sp_pct)} {sp_pct:+.2f}% to {sp_lvl}; Nasdaq 100 {_dir(ndx_pct)} {ndx_pct:+.2f}%.",
            f"10-Yr yield at {tyr_lvl}%.",
            f"WTI crude {_dir(wti_pct)} {wti_pct:+.2f}% to ${wti_lvl}; gold {_dir(gld_pct)} {gld_pct:+.2f}%.",
            f"DXY {_dir(dxy_pct)} {dxy_pct:+.2f}% to {dxy_lvl}.",
        ],
        "equities_commentary": (
            f"The S&P 500 {_dir(sp_pct)} {sp_pct:+.2f}% to {sp_lvl}. "
            f"The Nasdaq 100 {_dir(ndx_pct)} {ndx_pct:+.2f}% to {ndx_lvl}."
        ),
        "fixed_income_commentary": (
            f"The 10-year Treasury yield {_dir(tyr_pct, 'yield')} to {tyr_lvl}, "
            f"reflecting prevailing market conditions."
        ),
        "commodities_commentary": (
            f"WTI crude {_dir(wti_pct)} {wti_pct:+.2f}% to ${wti_lvl}. "
            f"Gold {_dir(gld_pct)} {gld_pct:+.2f}% to ${gld_lvl}."
        ),
        "currencies_commentary": (
            f"The U.S. Dollar Index (DXY) {_dir(dxy_pct)} {dxy_pct:+.2f}% to {dxy_lvl}."
        ),
        "economics_commentary":      "Economic calendar data was unavailable for this session.",
        "market_outlook_label":      "Neutral",
        "market_outlook_rationale":  "Deterministic fallback — LLM commentary unavailable.",
        "tactical_outperforming":    "",
        "tactical_underperforming":  "",
        "asset_class_outlooks":      {},
        "portfolio_spotlight_winners": [],
        "portfolio_spotlight_watch":   [],
        "session_recap":             [],
        "watch_today":               [],
        "international_section":     "",
        "cross_asset_synthesis":     "",
    }


def _backfill_watch_panel(data: dict, watch_fallback: list | None,
                          known_tickers: set | None) -> int:
    """Fill portfolio_spotlight_watch from the authoritative input laggards when it is empty,
    so the panel never renders "No data available". Deterministic; returns entries added."""
    if data.get("portfolio_spotlight_watch") or not watch_fallback:
        return 0
    filled = []
    for entry in watch_fallback:
        if not isinstance(entry, dict) or not entry.get("ticker"):
            continue
        tk = str(entry["ticker"]).upper()
        if known_tickers and tk not in known_tickers:
            continue
        desc = str(entry.get("description") or "").strip().rstrip(".")
        metric = str(entry.get("metric_label") or "recent 1-month return").strip()
        note = (f"Lagging the portfolio on {metric}; monitor whether the "
                f"underperformance stabilizes or extends.")
        filled.append({
            "ticker": tk,
            "metric_label": entry.get("metric_label") or "",
            "commentary": (f"{desc}. {note}" if desc else note)[:400],
        })
    if filled:
        data["portfolio_spotlight_watch"] = filled
        print(f"[VALIDATE] Backfilled {len(filled)} watch entr(ies) from input laggards "
              f"(model omitted or off-universe).")
    return len(filled)


def _backfill_winners_panel(data: dict, winners_fallback: list | None,
                            known_tickers: set | None) -> int:
    """Fill portfolio_spotlight_winners from the authoritative input top performers when the
    model omits it, so the "Top Performers" panel never renders "No data available"
    (2026-07-06→08: empty 3 days running while JFNIX +12%, IXJ +6.8% sat in the fund metrics).
    Only positive 1M returns qualify. Mirror of _backfill_watch_panel. Deterministic."""
    if data.get("portfolio_spotlight_winners") or not winners_fallback:
        return 0
    filled = []
    for entry in winners_fallback:
        if not isinstance(entry, dict) or not entry.get("ticker"):
            continue
        try:
            if float(entry.get("return_1m") or 0) <= 0:
                continue  # "Top Performers" = positive 1M only
        except (TypeError, ValueError):
            continue
        tk = str(entry["ticker"]).upper()
        if known_tickers and tk not in known_tickers:
            continue
        desc = str(entry.get("description") or "").strip().rstrip(".")
        metric = str(entry.get("metric_label") or "recent 1-month return").strip()
        note = (f"Leading the portfolio on {metric}; monitor whether the "
                f"outperformance persists or fades.")
        filled.append({
            "ticker": tk,
            "metric_label": entry.get("metric_label") or "",
            "commentary": (f"{desc}. {note}" if desc else note)[:400],
        })
    if filled:
        data["portfolio_spotlight_winners"] = filled
        print(f"[VALIDATE] Backfilled {len(filled)} top-performer entr(ies) from input winners "
              f"(model omitted or off-universe).")
    return len(filled)


def validate_commentary(data: dict, known_tickers: set = None, snapshot: dict = None,
                        watch_fallback: list | None = None,
                        winners_fallback: list | None = None) -> bool:
    if not isinstance(data, dict):
        return False
    # commodities_commentary and economics_commentary are optional  model reliably omits them when
    # there is no relevant data; downstream renders gracefully without them
    required_narrative = {"pre_market_bullets", "equities_commentary", "fixed_income_commentary",
                          "currencies_commentary"}
    required_outlook   = {"market_outlook_label", "market_outlook_rationale",
                          "tactical_outperforming", "tactical_underperforming",
                          "asset_class_outlooks"}
    all_required = required_narrative | required_outlook
    missing = all_required - set(data.keys())
    if missing:
        print(f"[WARN] Commentary missing keys: {missing}")
        # Tolerate missing outlook keys if we have narrative
        if missing & required_narrative:
            return False
    # Check narrative sections are non-empty
    for key in required_narrative:
        val = data.get(key, "")
        if isinstance(val, list):
            if not val:
                print(f"[WARN] Empty list for '{key}'")
                return False
        elif not str(val).strip():
            print(f"[WARN] Empty string for '{key}'")
            return False
    # Numeric consistency gate — compare LLM prose directions/magnitudes to market snapshot
    if snapshot is not None:
        sign_fixes = _correct_sign_mismatches(data, snapshot)
        if sign_fixes:
            print(f"[CORRECT] Auto-corrected {sign_fixes} sign mismatch(es) in merged commentary.")
        mag_fixes = _correct_magnitude_mismatches(data, snapshot)
        if mag_fixes:
            print(f"[CORRECT] Auto-corrected {mag_fixes} magnitude mismatch(es) in merged commentary.")
        bp_fixes = _correct_yield_pct_to_bp(data, snapshot)
        if bp_fixes:
            print(f"[CORRECT] Auto-corrected {bp_fixes} yield-pct-to-bp citation(s) in merged commentary.")
        dir_fixes = _correct_direction_words(data, snapshot)
        if dir_fixes:
            print(f"[CORRECT] Auto-corrected {dir_fixes} direction-word/superlative contradiction(s) in merged commentary.")
        corp_scrubbed = _scrub_fabricated_corporate_actions(data)
        if corp_scrubbed:
            print(f"[CORRECT] Scrubbed {corp_scrubbed} fabricated corporate-action claim(s) in merged commentary.")
        weekly_scrubbed = _scrub_false_weekly_claims(data, snapshot)
        if weekly_scrubbed:
            print(f"[CORRECT] Scrubbed {weekly_scrubbed} false weekly/superlative claim(s) in merged commentary.")
        dollar_fixes = _correct_dollar_direction(data, snapshot)
        if dollar_fixes:
            print(f"[CORRECT] Auto-corrected {dollar_fixes} dollar direction/window claim(s) in merged commentary.")
        fed_fixes = _correct_fed_hike_language(data)
        if fed_fixes:
            print(f"[CORRECT] Reframed {fed_fixes} unsupported Fed rate-hike claim(s) to higher-for-longer.")
        foreign_scrubbed = _scrub_foreign_macro_lead(data)
        if foreign_scrubbed:
            print(f"[CORRECT] Dropped foreign-macro trivia from economics_commentary.")
        haven_scrubbed = _scrub_safe_haven_inversion(data)
        if haven_scrubbed:
            print(f"[CORRECT] Scrubbed {haven_scrubbed} safe-haven causal-inversion(s) in merged commentary.")
        violations = _check_numeric_consistency(data, snapshot)
        if violations:
            print(f"[VALIDATE] Numeric consistency violations vs market_snapshot: {violations}")
            return False
        causal_violations = _check_causal_logic(data, snapshot)
        if causal_violations:
            print(f"[VALIDATE] Causal logic inversions: {causal_violations}")
            return False
        direction_violations = _check_direction_words(data, snapshot)
        if direction_violations:
            print(f"[VALIDATE] Direction-word/superlative contradictions: {direction_violations}")
            return False
        corp_violations = _check_fabricated_corporate_actions(data)
        if corp_violations:
            print(f"[VALIDATE] Fabricated corporate-action claims: {corp_violations}")
            return False
    # Normalize market_outlook_label
    label = str(data.get("market_outlook_label", "")).strip()
    if label not in ("Bullish", "Cautious", "Neutral", "Bearish"):
        data["market_outlook_label"] = "Neutral"
    # Ensure portfolio lists exist
    data.setdefault("portfolio_spotlight_winners", [])
    data.setdefault("portfolio_spotlight_watch", [])
    data.setdefault("asset_class_outlooks", {})
    # New optional sections — graceful degradation if model omits them
    data.setdefault("session_recap", [])
    data.setdefault("watch_today", [])
    data.setdefault("international_section", "")
    data.setdefault("cross_asset_synthesis", "")

    # Strip spotlight entries whose tickers are outside the known universe
    if known_tickers:
        before_w = len(data["portfolio_spotlight_winners"])
        before_wt = len(data["portfolio_spotlight_watch"])
        data["portfolio_spotlight_winners"] = [
            e for e in data["portfolio_spotlight_winners"]
            if str(e.get("ticker", "")).upper() in known_tickers
        ]
        data["portfolio_spotlight_watch"] = [
            e for e in data["portfolio_spotlight_watch"]
            if str(e.get("ticker", "")).upper() in known_tickers
        ]
        removed_w = before_w - len(data["portfolio_spotlight_winners"])
        removed_wt = before_wt - len(data["portfolio_spotlight_watch"])
        if removed_w or removed_wt:
            print(f"[VALIDATE] Removed {removed_w} winner(s), {removed_wt} watch(es) outside known universe.")

    # Backfill the watch panel deterministically when the LLM omitted it or all of its
    # entries were stripped above (2026-07-01: "Names to Watch: No data available" while real
    # laggards — XLG -4.7%, RLY -6.0% — sat right there in the fund metrics). Runs AFTER the
    # strip so it also recovers the case where the model returned off-universe tickers.
    _backfill_watch_panel(data, watch_fallback, known_tickers)
    # Same for the "Top Performers" panel (2026-07-06→08: empty 3 days running while positive
    # -return funds — JFNIX +12%, IXJ +6.8% — sat in the metrics table). The bearish-ticker
    # strip below keys on MAG7 top_bullets, and the winners fallback holds portfolio FUNDS
    # (never MAG7 names) gated to positive 1M, so that strip cannot re-empty this panel.
    _backfill_winners_panel(data, winners_fallback, known_tickers)

    # Remove bearish tickers from spotlight winners (contradiction guard)
    bearish_tickers: set[str] = set()
    for bullet in data.get("top_bullets", []):
        if isinstance(bullet, str) and bullet.strip().lower().startswith("bearish"):
            parts = bullet.split("")
            if len(parts) >= 2:
                bearish_tickers.add(parts[1].split(":")[0].strip().upper())
    if bearish_tickers:
        before = len(data["portfolio_spotlight_winners"])
        data["portfolio_spotlight_winners"] = [
            e for e in data["portfolio_spotlight_winners"]
            if str(e.get("ticker", "")).upper() not in bearish_tickers
        ]
        removed = before - len(data["portfolio_spotlight_winners"])
        if removed:
            print(f"[VALIDATE] Removed {removed} winner(s) that contradicted bearish top_bullets: {bearish_tickers}")

    return True


# ---------------------------------------------------------------------------
# Historical return enrichment
# ---------------------------------------------------------------------------
_YIELD_NAMES: frozenset[str] = frozenset({
    "10-Yr Yield", "10-Year Yield", "30-Year Yield", "2-Year Yield",
})


def enrich_with_historical_returns(
    snapshots: list[tuple[dict, dict[str, str]]],
) -> None:
    """Add pct_change_1w / pct_change_ytd (bp_change_* for yields) to snapshot dicts in-place.

    snapshots: list of (data_dict, {display_name: yf_ticker})
    """
    if yf is None:
        return
    reverse: dict[str, list[tuple[dict, str]]] = {}
    for data_dict, ticker_map in snapshots:
        for name, ticker in ticker_map.items():
            if name in data_dict:
                reverse.setdefault(ticker, []).append((data_dict, name))
    if not reverse:
        return
    try:
        today = datetime.today()
        ytd_start = pd.Timestamp(today.year, 1, 1)
        dl_start  = ytd_start.strftime("%Y-%m-%d")
        dl_end    = today.strftime("%Y-%m-%d")
        raw = yf.download(
            list(reverse.keys()), start=dl_start, end=dl_end,
            progress=False, auto_adjust=True,
        )
        if raw.empty:
            return
        if isinstance(raw.columns, pd.MultiIndex):
            closes = raw["Close"]
        else:
            t = list(reverse.keys())[0]
            closes = pd.DataFrame({t: raw["Close"]})
        closes.index = pd.to_datetime(closes.index).tz_localize(None)
    except Exception as exc:
        print(f"[WARN] enrich_with_historical_returns: {exc}")
        return

    for ticker, targets in reverse.items():
        if ticker not in closes.columns:
            continue
        s = pd.to_numeric(closes[ticker], errors="coerce").dropna()
        if len(s) < 2:
            continue
        last = float(s.iloc[-1])
        base_1w = float(s.iloc[-6]) if len(s) > 5 else None
        s_ytd = s[s.index >= ytd_start]
        base_ytd = float(s_ytd.iloc[0]) if len(s_ytd) >= 1 else None
        for data_dict, name in targets:
            is_yield = name in _YIELD_NAMES
            if base_1w is not None:
                if is_yield:
                    data_dict[name]["bp_change_1w"] = round((last - base_1w) * 100, 1)
                elif base_1w != 0:
                    data_dict[name]["pct_change_1w"] = round((last / base_1w - 1) * 100, 2)
            if base_ytd is not None:
                if is_yield:
                    data_dict[name]["bp_change_ytd"] = round((last - base_ytd) * 100, 1)
                elif base_ytd != 0:
                    data_dict[name]["pct_change_ytd"] = round((last / base_ytd - 1) * 100, 2)


# ---------------------------------------------------------------------------
# Topic Spotlight helpers
# ---------------------------------------------------------------------------

def _topic_matches_text(keywords: list[str], text: str) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def _crawl_article_body(url: str, timeout: int = 8) -> str:
    """Fetch and extract plain text from a news article URL. Returns empty string on any failure."""
    if not url or not url.startswith("http"):
        return ""
    try:
        from bs4 import BeautifulSoup
        r = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=timeout,
        )
        if r.status_code != 200:
            return ""
        content = r.content[:204800]  # cap at 200KB
        soup = BeautifulSoup(content, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)[:8000]
    except Exception:
        return ""


def _extract_ticker_candidates(text: str) -> list[str]:
    """Extract potential fund/ETF tickers from article body text."""
    import re
    candidates: list[str] = []
    # Parenthetical groups: (XOVR), (BPTRX, BPTIX)
    for match in re.findall(r'\(([A-Z]{2,6}(?:,\s*[A-Z]{2,6})*)\)', text):
        for t in match.split(","):
            t = t.strip()
            if 2 <= len(t) <= 6:
                candidates.append(t)
    # Uppercase tokens immediately before "ETF", "Fund", or "Trust"
    for m in re.finditer(r'\b([A-Z]{2,6})\b\s+(?:ETF|Fund|Trust)', text):
        candidates.append(m.group(1))
    # Deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for t in candidates:
        if t not in seen and not t.isdigit():
            seen.add(t)
            result.append(t)
    return result


def _verify_spotlight_fund(ticker: str) -> dict | None:
    """Verify a ticker resolves to a real fund via OpenBBProvider. Returns None on failure."""
    try:
        from providers.openbb_provider import OpenBBProvider
        profile = OpenBBProvider().get_profile(ticker)
        if not profile:
            return None
        name = str(profile.get("name") or "").strip()
        if not name or name.upper() == ticker.upper():
            return None
        issue_type = str(profile.get("issue_type") or "").upper()
        long_desc  = str(profile.get("long_description") or profile.get("short_description") or "")
        # Reject plain equities that aren't fund-like
        if issue_type in {"EQUITY", "COMMONSTOCK", "STOCK"} and "fund" not in name.lower() and "trust" not in name.lower():
            return None
        return {
            "ticker":      ticker,
            "name":        name,
            "type":        issue_type or "Fund",
            "aum":         profile.get("market_cap"),
            "description": long_desc[:300],
        }
    except Exception:
        return None


def _scrub_spotlight_text(text: str) -> str:
    """Strip sensational escalation phrases from spotlight text (narrower than BANNED_PHRASES)
    and soften prescriptive 'buy this' directives into non-advice optioned phrasing
    (2026-06-12/15: "Investors should express this view by leaning into ARKK")."""
    import re
    for phrase in SPOTLIGHT_ESCALATION_PHRASES:
        text = re.sub(re.escape(phrase), "", text, flags=re.IGNORECASE)
    # Non-advice framing: convert the observed prescriptive vehicle lead-ins to options.
    text = re.sub(r"[Ii]nvestors should express this view by leaning into",
                  "One way to express this view is via", text)
    text = re.sub(r"\bexpress this view by leaning into\b",
                  "express this view via", text)
    text = re.sub(r"[Ii]nvestors should (?:buy|lean into|trim|sell)\b",
                  "One way to express this is via", text)
    text = re.sub(r"  +", " ", text).strip()
    return text


# Asset aliases + directional verbs for the spotlight directional guard.
_SPOTLIGHT_ASSET_ALIASES: dict[str, tuple[str, ...]] = {
    "S&P 500":            ("s&p 500", "s&p500", "s&p", "spx"),
    "Nasdaq 100":         ("nasdaq 100", "nasdaq", "ndx"),
    "Dow Jones":          ("dow jones", "the dow", "dow", "djia"),
    "Russell 2000":       ("russell 2000", "russell", "small caps", "small-caps"),
    "Gold":               ("gold", "bullion"),
    "WTI Crude":          ("wti crude", "wti", "crude oil", "crude", "oil prices", "oil"),
    "U.S. Dollar (DXY)":  ("dollar index", "the dollar", "greenback", "dxy"),
    "Nikkei 225":         ("nikkei",),
    "FTSE 100":           ("ftse",),
}
_SPOTLIGHT_UP_RE = re.compile(
    r'\b(surge\w*|soar\w*|jump\w*|rallie\w*|rally|rallied|climb\w*|rocket\w*|'
    r'spike[ds]?|gain\w*|rise[s]?|rose|rebound\w*|advanc\w*|popp?\w*)\b'
)
_SPOTLIGHT_DOWN_RE = re.compile(
    r'\b(crash\w*|plunge[ds]?|plunging|tumbl\w*|sink[s]?|sank|slump\w*|slid\w*|slide[s]?|'
    r'tank\w*|sell-?off|drop\w*|fell|fall[s]?|div\w*|sink\w*|slip\w*)\b'
)


def _spotlight_contradicts_market(text: str, market_dirs: dict[str, int]) -> list[str]:
    """Return descriptions of directional claims in `text` that contradict the close.

    market_dirs maps canonical asset name -> sign (+1 closed up, -1 closed down, 0 flat).
    Fires only when an asset alias is immediately followed (within ~22 chars) by an
    up/down verb whose direction is opposite the actual close. The tight window keeps a
    second clause (e.g. "...as oil crashes") from contaminating the prior asset's check.
    """
    low = (text or "").lower()
    if not low:
        return []
    violations: list[str] = []
    for asset, sign in market_dirs.items():
        if not sign:
            continue
        for alias in _SPOTLIGHT_ASSET_ALIASES.get(asset, ()):
            hit = False
            for m in re.finditer(r'\b' + re.escape(alias) + r'\b', low):
                seg = low[m.end(): m.end() + 22]
                up = _SPOTLIGHT_UP_RE.search(seg)
                dn = _SPOTLIGHT_DOWN_RE.search(seg)
                if not up and not dn:
                    continue
                said_up = bool(up) and (not dn or up.start() < dn.start())
                if said_up and sign < 0:
                    violations.append(f"{asset} described as rising but closed lower")
                    hit = True
                elif (not said_up) and dn and sign > 0:
                    violations.append(f"{asset} described as falling but closed higher")
                    hit = True
            if hit:
                break  # one alias hit per asset is enough
    return violations


def _spotlight_offtopic_mover(body: str, selected: dict | None) -> bool:
    """True when the spotlight is a single-name MOVER but the written body never references
    that name — i.e. the writer drifted to a different story while the teaser still advertises
    the mover (2026-06-23: a PRIM mover teaser over a Roblox body). Defense-in-depth behind the
    market_movers news gate: even if a name wins the slot, the deep-dive must actually be ABOUT
    it. A reference = the ticker OR a distinctive (non-generic) word of the company name."""
    if not selected or selected.get("kind") != "mover":
        return False
    tkr = str(selected.get("mover_ticker") or "").upper().strip()
    if not tkr:
        return False
    text = body or ""
    if re.search(r"\b" + re.escape(tkr) + r"\b", text, re.IGNORECASE):
        return False
    import market_movers
    for w in re.split(r"[^A-Za-z]+", str(selected.get("topic") or "")):
        if len(w) > 3 and w.lower() not in market_movers._GENERIC_NAME_WORDS:
            if re.search(r"\b" + re.escape(w) + r"\b", text, re.IGNORECASE):
                return False
    return True


# Evergreen personal-finance / society tropes that crawled EVERGREEN articles inject into an
# otherwise on-theme daily spotlight. Regression 2026-06-24: a tech-selloff deep-dive was padded
# with the "4% retirement rule … 2000s-style collapse" and "the top 20% of Americans now account
# for nearly 60% of spending" — timeless filler with no bearing on the session. The off-topic
# mover guard only catches whole-body drift; an on-theme body can still smuggle these in. Flag
# them as retry feedback (never scrub) so the writer rewrites without the tangent.
_SPOTLIGHT_EVERGREEN_RE = re.compile(
    r"(?:\b\d{1,2}%?\s*(?:percent\s+)?retirement\s+rule\b|\bretirement\s+rule\b|"
    r"\b4%\s+rule\b|\bfour[\-\s]?percent\s+rule\b|"
    r"\b(?:top|bottom)\s+\d{1,2}%\s+of\s+(?:americans|households|earners|the\s+population)\b|"
    r"\baccount\s+for\s+(?:nearly\s+)?\d{1,2}%\s+of\s+(?:all\s+)?(?:consumer\s+)?spending\b)",
    re.IGNORECASE)


def _spotlight_evergreen_drift(body: str) -> list[str]:
    """Return evergreen-trope phrases found in a spotlight body (empty when clean). Retry-feedback
    only — these are session-irrelevant tangents from stale crawled articles, not analysis."""
    hits: list[str] = []
    for m in _SPOTLIGHT_EVERGREEN_RE.finditer(body or ""):
        frag = m.group(0).strip()
        if frag not in hits:
            hits.append(frag)
        if len(hits) >= 3:
            break
    return hits


def _pick_fallback_theme(payload: dict) -> dict | None:
    """Pillar 1.5 — when no dominant NEWS topic exists, pick a market-data theme.

    The Sevens has its feature every day; the news-driven spotlight only fires when a
    single topic dominates the wire. On quieter days we need a flagship piece anyway, so
    we look at the day's data: the largest sector move (the most actionable observable),
    elevated to a deep-dive theme. Returns a scan_result-shaped dict, or None if no
    market-data theme is strong enough to anchor a feature.
    """
    sp = [s for s in (payload.get("sector_performance") or [])
          if s.get("ticker") and s.get("pct_change") is not None]
    if not sp:
        return None
    sp_sorted = sorted(sp, key=lambda s: abs(float(s["pct_change"])), reverse=True)
    top = sp_sorted[0]
    pct = float(top["pct_change"])
    # Only elevate to a feature if the move is meaningfully large.
    if abs(pct) < 1.5:
        return None
    name   = str(top["name"])
    ticker = str(top["ticker"]).upper()
    direction = "Leadership" if pct > 0 else "Sell-Off"
    name_lc = name.lower()
    base_kw = [name_lc, ticker.lower(), name_lc.replace(" ", "")]
    # Add some natural language keywords tied to the sector for headline matching.
    _SECTOR_KW = {
        "XLK":  ["technology", "tech", "semiconductor", "ai", "software", "chip"],
        "XLF":  ["bank", "financial", "lender", "insurance", "broker"],
        "XLE":  ["energy", "oil", "drilling", "refiner", "lng", "natural gas"],
        "XLV":  ["health", "pharma", "biotech", "medical"],
        "XLI":  ["industrial", "manufactur", "machinery", "defense", "aerospace"],
        "XLY":  ["consumer", "retail", "discretionary", "auto", "homebuilder"],
        "XLP":  ["staples", "consumer staples", "grocer", "beverage", "food"],
        "XLU":  ["utility", "utilities", "power"],
        "XLB":  ["material", "miner", "chemical", "metal"],
        "XLRE": ["real estate", "reit", "property"],
        "XLC":  ["communication", "media", "internet", "telecom"],
    }
    extras = _SECTOR_KW.get(ticker, [])
    return {
        "has_spotlight":   True,
        "topic":           f"{name} Sector {direction}",
        "topic_keywords":  list(dict.fromkeys(base_kw + extras))[:6],
        "category":        "sector_catalyst",
        "why_now":         (f"{name} ({ticker}) "
                            f"{'gained' if pct > 0 else 'fell'} {abs(pct):.1f}% in the prior session, "
                            f"the day's largest sector move — a setup the data alone makes worth explaining."),
        "candidate_funds": [ticker],   # sector ETF is the most direct vehicle
        "_is_fallback":    True,
    }


def generate_topic_spotlight(
    payload: dict,
    world_news: list[dict],
    enrich_news: dict,
    enrich_co_news: list[dict],
    market_dirs: dict[str, int] | None = None,
) -> dict | None:
    """Detect a trending financial topic and write a grounded spotlight story with verified fund tie-ins.

    Returns the topic_spotlight dict or None when the gate does not fire.
    """
    # ── Build headline corpus with source + URL ───────────────────────────────
    headline_corpus: list[dict] = []
    for a in (world_news or []):
        title = str(a.get("title") or "").strip()
        if title:
            headline_corpus.append({
                "text":   title + ("  " + str(a.get("summary") or ""))[:200],
                "source": str(a.get("source") or "world"),
                "url":    str(a.get("url") or ""),
            })
    for articles in (enrich_news if isinstance(enrich_news, dict) else {}).values():
        for a in (articles or []):
            hl = str(a.get("headline") or "").strip()
            if hl:
                headline_corpus.append({
                    "text":   hl + ("  " + str(a.get("summary") or ""))[:200],
                    "source": str(a.get("source") or "finnhub"),
                    "url":    str(a.get("url") or ""),
                })
    for a in (enrich_co_news if isinstance(enrich_co_news, list) else []):
        hl = str(a.get("headline") or "").strip()
        if hl:
            headline_corpus.append({
                "text":   hl,
                "source": str(a.get("source") or "finnhub"),
                "url":    str(a.get("url") or ""),
            })
    if not headline_corpus:
        return None

    # ── LLM topic scan ────────────────────────────────────────────────────────
    _scan_sectors = [
        {"name": s.get("name"), "pct_change": s.get("pct_change")}
        for s in (payload.get("sector_performance") or [])
        if s.get("name") and s.get("pct_change") is not None
    ]
    scan_payload = {
        "headlines": [{"index": i, "text": h["text"][:300]} for i, h in enumerate(headline_corpus[:40])],
        "date": payload.get("date", ""),
        "sector_leaders": (sorted(_scan_sectors, key=lambda s: s["pct_change"], reverse=True)[:3]
                           + sorted(_scan_sectors, key=lambda s: s["pct_change"])[:2]),
    }
    scan_result: dict = {}
    try:
        print("  [SPOTLIGHT] Scanning headlines for dominant topic...")
        scan_result = _call_ollama_raw(SYSTEM_PROMPT_TOPIC_SCAN, scan_payload)
    except Exception as exc:
        print(f"  [SPOTLIGHT] Scan failed: {exc}")
        return None

    # ── Fallback: if no dominant news theme, pick one from the day's market data ──
    # The Sevens runs its feature daily; the news-driven scanner only fires when a
    # single topic dominates the wire. On quieter days we fall back to the largest
    # sector move (or another data signal) so the flagship piece runs every day.
    is_fallback = False
    if not scan_result.get("has_spotlight"):
        print("  [SPOTLIGHT] No dominant news topic — trying data-driven fallback theme...")
        _fb = _pick_fallback_theme(payload)
        if _fb:
            scan_result = _fb
            is_fallback = True
            print(f"  [SPOTLIGHT] Fallback theme: '{_fb['topic']}' (why: {_fb['why_now']})")
        else:
            print("  [SPOTLIGHT] No fallback theme strong enough either — skipping.")
            return None

    topic          = str(scan_result.get("topic") or "").strip()
    topic_keywords = [str(k).lower().strip() for k in (scan_result.get("topic_keywords") or []) if k]
    why_now        = str(scan_result.get("why_now") or "").strip()
    category       = str(scan_result.get("category") or "").strip()
    scan_funds     = [str(t).upper().strip() for t in (scan_result.get("candidate_funds") or []) if t]

    if not topic or not topic_keywords:
        return None

    # ── Deterministic gate ────────────────────────────────────────────────────
    # News-driven theme: require strong headline corroboration. Data-driven fallback:
    # relaxed thresholds since the theme is grounded in actual market data, not news
    # consensus — incidental sector coverage in the wire is bonus colour, not the basis.
    matching       = [h for h in headline_corpus if _topic_matches_text(topic_keywords, h["text"])]
    distinct_src   = {h["source"] for h in matching}
    print(f"  [SPOTLIGHT] '{topic}': {len(matching)} matching headlines, {len(distinct_src)} sources"
          f"{' [fallback]' if is_fallback else ''}.")

    if is_fallback:
        _min_h, _min_s = 2, 1
    else:
        _min_h, _min_s = MIN_TOPIC_HEADLINES, MIN_TOPIC_SOURCES
    if len(matching) < _min_h or len(distinct_src) < _min_s:
        # Last-resort: even if zero matching headlines, a fallback theme can still
        # write a deep-dive grounded in the day's market data + tactical positioning.
        # We accept it but flag in logs so behaviour stays visible.
        if not is_fallback:
            print(f"  [SPOTLIGHT] News gate failed (need >={_min_h} headlines, >={_min_s} sources) — trying fallback.")
            _fb = _pick_fallback_theme(payload)
            if _fb:
                scan_result = _fb
                is_fallback = True
                topic          = scan_result["topic"]
                topic_keywords = scan_result["topic_keywords"]
                why_now        = scan_result["why_now"]
                category       = scan_result["category"]
                scan_funds     = list(scan_result.get("candidate_funds") or [])
                matching     = [h for h in headline_corpus if _topic_matches_text(topic_keywords, h["text"])]
                distinct_src = {h["source"] for h in matching}
                print(f"  [SPOTLIGHT] Fallback theme: '{topic}' — {len(matching)} corroborating headlines.")
            else:
                return None
        else:
            print(f"  [SPOTLIGHT] Fallback has only {len(matching)} matching headline(s) — proceeding anyway (data-driven theme).")

    # ── Single-name mover competes for the slot via unified prevalence score ──
    import market_movers
    from providers.openbb_provider import OpenBBProvider

    def _default_movers_fn():
        try:
            return OpenBBProvider().get_market_movers(limit=10)
        except Exception as _e:
            print(f"  [SPOTLIGHT] movers feed unavailable ({_e}).")
            return {"gainers": [], "losers": []}

    def _default_quote_fn(_t):
        try:
            return OpenBBProvider().get_quote(_t)
        except Exception:
            return {}

    def _default_mover_scan():
        try:
            res = _call_ollama_raw(SYSTEM_PROMPT_MOVER_SCAN,
                                   {"headlines": [h["text"][:300] for h in headline_corpus[:40]]})
            return res if isinstance(res, dict) and res.get("ticker") else None
        except Exception:
            return None

    _theme_cand = market_movers.theme_candidate(
        topic, topic_keywords, why_now, category, scan_funds, matching, headline_corpus, payload)
    _mover_cand = market_movers.detect_market_mover(
        headline_corpus, enrich_co_news, payload,
        movers_fn=_default_movers_fn, quote_fn=_default_quote_fn, scan_fn=_default_mover_scan)
    _selected = market_movers.select_spotlight_candidate(
        [c for c in (_mover_cand, _theme_cand) if c]) or _theme_cand

    # Earnings grounding for a single-name mover: if the mover reported its own
    # earnings today (or within the recent-actuals window), the move is an EARNINGS
    # reaction — not the day's macro/geopolitical theme. Without this, a dominant
    # wire theme hijacks the attribution (2026-06-18: Accenture's -17% earnings/
    # guidance drop was written up as caused by the "Iran war").
    earnings_grounding: dict | None = None
    if _selected and _selected.get("kind") == "mover":
        print(f"  [SPOTLIGHT] Mover wins slot: {_selected['mover_ticker']} "
              f"{_selected['mover_pct'] * 100:+.1f}% (share {_selected['headline_share']:.2f}).")
        topic          = _selected["topic"]
        topic_keywords = _selected["topic_keywords"]
        why_now        = _selected["why_now"]
        category       = _selected["category"]
        scan_funds     = list(_selected["candidate_funds"])
        matching       = [h for h in headline_corpus if _topic_matches_text(topic_keywords, h["text"])]

        _mv = str(_selected.get("mover_ticker") or "").upper().strip()
        _today_str = str(payload.get("date", ""))[:10]
        _earn_today = [e for e in (payload.get("earnings_calendar") or [])
                       if str(e.get("ticker", "")).upper().strip() == _mv
                       and str(e.get("date", ""))[:10] == _today_str]
        _earn_recent = [e for e in (payload.get("recent_earnings_actuals") or [])
                        if str(e.get("ticker", "")).upper().strip() == _mv]
        if _earn_today or _earn_recent:
            _rec = (_earn_recent or _earn_today)[0]
            earnings_grounding = {
                "ticker": _mv,
                "note": (f"{_mv} reported its own earnings "
                         f"{'today' if _earn_today else 'recently'} — this move is an "
                         f"earnings/guidance reaction, NOT the day's macro or geopolitical theme. "
                         f"Attribute it to the company's results, revenue/guidance, bookings, or "
                         f"segment performance."),
                "eps_actual":       _rec.get("eps_actual"),
                "eps_estimate":     _rec.get("eps_estimate"),
                "eps_surprise_pct": _rec.get("eps_surprise_pct"),
            }
            print(f"  [SPOTLIGHT] {_mv} reports earnings — grounding attribution in earnings, not theme.")

    # ── Fund grounding: crawl topic articles + verify tickers ─────────────────
    candidate_tickers = list(scan_funds)
    crawl_targets = [h["url"] for h in matching if h.get("url", "").startswith("http")]
    crawled = 0
    crawled_excerpts: list[dict] = []
    for url in crawl_targets[:MAX_CRAWL_ARTICLES]:
        print(f"  [SPOTLIGHT] Crawling {url[:80]}...")
        body = _crawl_article_body(url)
        if body:
            candidate_tickers.extend(_extract_ticker_candidates(body))
            crawled += 1
            # Keep a clean excerpt to GROUND the analysis in actual reporting rather than
            # headlines alone — this is what lifts the spotlight from a blurb to a genuine
            # deep-dive (the mechanism/sustainability paragraphs need real source material).
            _src = url.split("/")[2] if "//" in url else url
            crawled_excerpts.append({"source": _src, "text": body[:1400]})
    print(f"  [SPOTLIGHT] Crawled {crawled} articles; {len(set(candidate_tickers))} raw candidates.")

    seen_t: set[str] = set()
    deduped: list[str] = []
    for t in candidate_tickers:
        if t not in seen_t and len(t) >= 2:
            seen_t.add(t)
            deduped.append(t)

    verified_funds: list[dict] = []
    for ticker in deduped:
        if len(verified_funds) >= MAX_SPOTLIGHT_FUNDS:
            break
        result = _verify_spotlight_fund(ticker)
        if result:
            verified_funds.append(result)
            print(f"  [SPOTLIGHT] Verified: {ticker} ({result['name']})")
        else:
            print(f"  [SPOTLIGHT] Dropped: {ticker}")

    # ── LLM story writing (Call 6) ─────────────────────────────────────────────
    writer_payload = {
        "topic":               topic,
        "category":            category,
        "why_now":             why_now,
        "supporting_headlines": [
            {"headline": h["text"][:300], "source": h["source"]} for h in matching[:10]
        ],
        # Real article text the analysis MUST be grounded in (facts, figures, mechanism).
        "source_excerpts": crawled_excerpts[:5],
        # Market data grounding — always provided so the analysis can cite real numbers
        # for sector tilt, positioning, and tactical context. Essential when the theme is
        # data-driven (Pillar 1.5 fallback) and crawled excerpts are sparse; useful as
        # additional grounding for news-driven pieces too.
        "market_context": {
            "sector_top3": [
                {"name": s.get("name"), "ticker": s.get("ticker"), "pct_change": s.get("pct_change")}
                for s in (payload.get("sector_performance") or [])[:3]
            ],
            "sector_bottom3": [
                {"name": s.get("name"), "ticker": s.get("ticker"), "pct_change": s.get("pct_change")}
                for s in (payload.get("sector_performance") or [])[-3:][::-1]
            ],
            "tactical_positioning": payload.get("tactical_positioning") or {},
            "is_data_driven_theme": is_fallback,
        },
        "verified_funds": [
            {"ticker": f["ticker"], "name": f["name"], "type": f["type"], "description": f["description"]}
            for f in verified_funds
        ],
        "date": payload.get("date", ""),
    }
    # When the mover reported earnings, force attribution to the company's results
    # rather than the day's dominant wire theme (see earnings_grounding above).
    if earnings_grounding:
        writer_payload["earnings_grounding"] = earnings_grounding
    # Seed the writer with the actual closing directions so it is less likely to
    # invent a move that contradicts the tape on the first pass.
    if market_dirs:
        writer_payload["market_close_directions"] = {
            a: ("up" if s > 0 else "down" if s < 0 else "flat")
            for a, s in market_dirs.items() if s
        }

    print(f"  [LLM Call 6] Writing topic spotlight: '{topic}'...")
    # The writer loop now enforces BOTH completeness and the directional guard. A draft
    # that asserts a price move contradicting the close (e.g. "Dow Surges" on a down
    # day) is not discarded outright — we feed the specific error back and retry, so a
    # salvageable spotlight survives instead of vanishing. Only an exhausted loop drops.
    title = ""
    body  = ""
    story: dict = {}
    for attempt in range(4):
        try:
            story = _call_ollama_raw(SYSTEM_PROMPT_TOPIC_SPOTLIGHT, writer_payload, num_ctx=16384)
        except Exception as exc:
            print(f"  [SPOTLIGHT] Writer attempt {attempt + 1} failed: {exc}")
            story = {}
            continue
        # Depth gate: a flagship deep-dive must be substantive (>=3 paragraphs, >=600 chars).
        # A thin blurb triggers a retry; an exhausted loop drops it (quality over presence).
        _body_raw = str(story.get("body") or "").strip()
        _para_ct = len([p for p in _body_raw.split("\n\n") if p.strip()])
        if not (str(story.get("title") or "").strip() and len(_body_raw) >= 600 and _para_ct >= 3):
            print(f"  [SPOTLIGHT] Attempt {attempt + 1}: too thin "
                  f"({len(_body_raw)} chars, {_para_ct} paras) — retrying for depth.")
            story = {}
            continue
        # ── Scrub, then run the directional guard before accepting ─────────────
        title = _scrub_spotlight_text(str(story.get("title") or "").strip())
        body  = _scrub_spotlight_text(str(story.get("body") or "").strip())
        contradictions = (
            _spotlight_contradicts_market(title + ". " + body, market_dirs)
            if market_dirs else []
        )
        # Topic-coherence guard: a single-name mover spotlight whose body never mentions the
        # mover has drifted off-topic (the teaser still advertises it). Retry on-target; an
        # exhausted loop drops rather than ship a dangling teaser (2026-06-23 PRIM→Roblox).
        offtopic = _spotlight_offtopic_mover(body, _selected)
        evergreen = _spotlight_evergreen_drift(body)
        if not contradictions and not offtopic and not evergreen:
            break
        if evergreen:
            print(f"  [SPOTLIGHT] Attempt {attempt + 1}: evergreen filler not tied to the session "
                  f"{evergreen}; retrying without it.")
            writer_payload["factual_correction"] = (
                "Your previous draft was REJECTED for padding the analysis with evergreen, "
                "session-irrelevant filler: " + "; ".join(evergreen) + ". Rewrite the entire "
                "piece so EVERY paragraph is about today's theme and the current session — the "
                "catalyst, the mechanism, the data, and the read-through for the verified funds. "
                "Do NOT include timeless personal-finance rules (e.g. the '4% retirement rule'), "
                "long-horizon household wealth-distribution statistics, or other generic tangents "
                "that are not specific to today's move."
            )
            story, title, body = {}, "", ""
            continue
        if offtopic:
            _mv = str((_selected or {}).get("mover_ticker") or "").strip()
            print(f"  [SPOTLIGHT] Attempt {attempt + 1}: body never references the mover {_mv} "
                  f"— off-topic drift; retrying on-target.")
            writer_payload["factual_correction"] = (
                f"Your previous draft was REJECTED: this spotlight is about {_mv} "
                f"({topic}), but the draft never discussed {_mv}. Rewrite the entire piece so it "
                f"is specifically ABOUT {_mv} — its move today, the catalyst behind it, and the "
                f"read-through for related funds. Do NOT write about a different company or drift "
                f"to a generic market-rotation theme."
            )
            story, title, body = {}, "", ""
            continue
        print(f"  [SPOTLIGHT] Attempt {attempt + 1}: claim contradicts market close "
              f"{contradictions}; retrying with correction.")
        writer_payload["factual_correction"] = (
            "Your previous draft was REJECTED for stating a price move that contradicts "
            "the actual market close: " + "; ".join(contradictions) + ". Rewrite so EVERY "
            "directional claim matches these closing directions: "
            + ", ".join(f"{a} closed {d}"
                        for a, d in writer_payload.get("market_close_directions", {}).items())
            + ". When unsure, use a thematic headline with no index/asset move."
        )
        story, title, body = {}, "", ""

    if not title or not body:
        print("  [SPOTLIGHT] No usable, market-consistent story produced — skipping spotlight.")
        return None

    verified_tickers = {f["ticker"] for f in verified_funds}
    raw_funds = story.get("funds") or []
    clean_funds: list[dict] = []
    for f in (raw_funds if isinstance(raw_funds, list) else []):
        if not isinstance(f, dict):
            continue
        t = str(f.get("ticker") or "").upper().strip()
        if t in verified_tickers:
            clean_funds.append({
                "ticker":       t,
                "name":         str(f.get("name") or ""),
                "type":         str(f.get("type") or ""),
                "exposure_note": _scrub_spotlight_text(str(f.get("exposure_note") or "")),
            })

    result = {"title": title, "body": body, "funds": clean_funds, "category": category, "topic": topic}
    result["teaser"] = market_movers.build_spotlight_teaser(_selected)
    print(f"  [SPOTLIGHT] Done: '{title}' ({len(clean_funds)} verified funds).")
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    today = datetime.today().strftime("%Y-%m-%d")

    # Pre-warm the commentary model immediately so it loads concurrently with the
    # several-minute market-data gathering below and is resident before the first LLM
    # call. Without this, a cold/idle Ollama cold-loads on the narrative call
    # (num_ctx=16384); on this VRAM-tight server that load is slow enough to drop the
    # connection and force the deterministic fallback that blocks the email. Non-blocking.
    # The returned thread is handed to _preflight_gpu_check below, which joins it before
    # reading /api/ps so the GPU/CPU residency check sees a loaded model.
    _warmup_thread = _warmup_ollama_async()

    # Load yesterday's stored levels so each instrument's prev_close is the value
    # we actually reported last run.  GUARD: if the existing commentary file is from
    # TODAY (a same-day re-run), feeding its levels back would make daily pct_change
    # collapse to ~0 (today-vs-today).  In that case fall back to the most recent
    # prior-day archive file so contract-roll protection is still available.
    _prev: dict = {}
    if COMMENTARY_PATH.exists():
        try:
            with open(COMMENTARY_PATH, "r", encoding="utf-8") as _pf:
                _prev = json.load(_pf)
        except Exception:
            pass

    if _prev.get("report_date") == today:
        # Same-day re-run detected — source prev_close from prior archive instead.
        _archive_dir = COMMENTARY_PATH.parent / "commentary_archive"
        _archive_prev: dict = {}
        if _archive_dir.exists():
            _archive_files = sorted(
                (f for f in _archive_dir.glob("*.json") if f.stem < today),
                reverse=True,
            )
            if _archive_files:
                try:
                    with open(_archive_files[0], "r", encoding="utf-8") as _af:
                        _archive_prev = json.load(_af)
                    print(f"[DATA] Same-day re-run: using prior archive {_archive_files[0].name} for prev_close.")
                except Exception:
                    pass
        if _archive_prev:
            _prev = _archive_prev
        else:
            print("[DATA] Same-day re-run: no prior archive found — fetchers will use arr[-2] as prev_close.")
            _prev = {}

    print("[DATA] Fetching live market data...")
    snapshot         = fetch_market_snapshot(prev_data=_prev.get("market_snapshot"))
    print(f"  [OK] Core snapshot: {len(snapshot)} assets")

    global_markets   = fetch_global_markets(prev_data=_prev.get("global_markets"))
    print(f"  [OK] Global markets: {len(global_markets)} indices")

    commodities_tbl  = fetch_commodities_table(prev_data=_prev.get("commodities_table"))
    print(f"  [OK] Commodities: {len(commodities_tbl)} items")

    currencies_tbl   = fetch_currencies_table(prev_data=_prev.get("currencies_table"))
    print(f"  [OK] Currencies: {len(currencies_tbl)} pairs")

    # Gold: the snapshot and commodities table fetch gold independently through the
    # three-tier spot/proxy/futures fallback, so an intermittent XAUUSD=X 404 on one call
    # can split them across tiers (divergent level AND sign — 2026-06-18 cross-wire). Force
    # both onto the better-tier quote so the snapshot, prose, and table can never disagree.
    _gold_canon = _reconcile_gold(snapshot, commodities_tbl)
    if _gold_canon:
        print(f"  [OK] Gold reconciled across snapshot & commodities table: "
              f"${_gold_canon.get('level')} ({_gold_canon.get('pct_change')}%) "
              f"src={_gold_canon.get('_source')}")

    bonds_tbl        = fetch_bonds_table()
    print(f"  [OK] Bonds: {len(bonds_tbl)} instruments")

    # Cross-check Treasury.gov 2Y/10Y/30Y against the fresh arbitrated (YCharts) curve.
    # Treasury.gov's XML lags a session on some mornings and would otherwise invert the rates
    # narrative (2026-07-01: 10Y shown as -2 bp when it rose ~6 bp). See
    # _reconcile_bonds_with_arbitrated. Gated on the arbitration being TODAY's, so we only
    # override Treasury.gov when the alternative source is itself fresh.
    try:
        _arb = json.loads((DATA_DIR / "market_data_arbitrated.json").read_text(encoding="utf-8"))
        if str((_arb or {}).get("arbitrated_date", ""))[:10] == datetime.today().strftime("%Y-%m-%d"):
            _n = _reconcile_bonds_with_arbitrated(bonds_tbl, (_arb or {}).get("yield_curve") or {})
            if _n:
                print(f"  [OK] Reconciled {_n} Treasury tenor(s) to the fresh arbitrated curve "
                      f"(Treasury.gov row lagged a session).")
    except Exception as _rex:
        print(f"  [WARN] Bonds↔arbitrated reconciliation skipped: {_rex}")

    # Sync the 10-Yr Yield in the snapshot to the authoritative Treasury.gov value
    # so the market snapshot table and the yield table always agree on level/direction.
    _tsy_10y = bonds_tbl.get("10-Year Yield")
    if _tsy_10y and _tsy_10y.get("level") is not None:
        _tsy_chg = _tsy_10y.get("change")
        snapshot["10-Yr Yield"] = {
            "level":      _tsy_10y["level"],
            "change":     _tsy_chg,
            "pct_change": _tsy_10y.get("pct_change"),
            "bp_change":  round((_tsy_chg or 0) * 100, 1),
        }
        print(f"  [OK] Snapshot 10-Yr synced to Treasury.gov: {_tsy_10y['level']:.3f}%")

    print("[DATA] Enriching with 1W/YTD historical returns...")
    try:
        enrich_with_historical_returns([
            (snapshot,        MARKET_TICKERS),
            (global_markets,  GLOBAL_TICKERS),
            (commodities_tbl, COMMODITY_TICKERS),
            (currencies_tbl,  CURRENCY_TICKERS),
        ])
        print("  [OK] Historical enrichment complete")
    except Exception as _enrich_exc:
        print(f"  [WARN] Historical enrichment skipped: {_enrich_exc}")

    # Reconcile technical "current" with the canonical snapshot prices so the page-8
    # moving-average table never shows a different price than pages 1-3 (fixes the
    # 2026-06-01 split: snapshot Gold $4,560.50 / S&P 7,580.06 vs technicals 4,518.40 /
    # 7,612.37). 10-Yr is additionally pinned to Treasury.gov just below.
    _tech_current_overrides = {
        name: (snapshot.get(name) or {}).get("level")
        for name in ("S&P 500", "Nasdaq 100", "Gold", "WTI Crude", "10-Yr Yield")
        if (snapshot.get(name) or {}).get("level") is not None
    }
    tech_levels      = fetch_technical_levels(current_overrides=_tech_current_overrides)
    print(f"  [OK] Technical levels: {len(tech_levels)} assets (current reconciled to snapshot)")

    # Sync the technical-table 10-Yr "current" to the same authoritative Treasury.gov
    # value used for the snapshot, so the page-8 moving-average table can't disagree
    # with pages 1-2 (yfinance ^TNX often lags Treasury.gov by several bp).
    _tsy_10y_tech = bonds_tbl.get("10-Year Yield")
    if _tsy_10y_tech and _tsy_10y_tech.get("level") is not None and tech_levels.get("10-Yr Yield"):
        tech_levels["10-Yr Yield"]["current"] = round(float(_tsy_10y_tech["level"]), 2)
        print(f"  [OK] Technical 10-Yr synced to Treasury.gov: {_tsy_10y_tech['level']:.3f}%")

    sector_perf      = fetch_sector_performance()
    print(f"  [OK] Sectors: {len(sector_perf)} ETFs fetched")

    futures_tbl      = fetch_futures_table(prev_data=_prev.get("futures_table"))
    print(f"  [OK] Futures: {len(futures_tbl)} contracts")

    print("[DATA] Loading portfolio data...")
    df = load_portfolio_df()
    winners, watch     = build_portfolio_spotlight(df) if not df.empty else ([], [])
    mag7_consensus     = build_mag7_consensus(df)      if not df.empty else {}
    news_buckets       = load_news_headlines()

    print("[NET] Fetching world news...")
    world_news = fetch_world_news()

    print("[CAL] Fetching economic calendar...")
    econ_calendar = fetch_economic_calendar()
    # Slice the calendar for the prompt + scenario engine: keep the soonest events for
    # focus, but ALWAYS retain near-term HIGH-importance catalysts (e.g. FOMC) that can
    # sort behind same-week medium prints by date. A plain head-slice silently dropped the
    # 2026-06-17 FOMC decision (it sat at index 7) from both the scenario picker and the
    # LLM prompt, so the report led with Retail Sales instead of the rate decision.
    _econ_hi_cutoff = (datetime.today() + timedelta(days=10)).strftime("%Y-%m-%d")
    _soonest_econ = econ_calendar[:8]
    _soonest_ids = {id(e) for e in _soonest_econ}
    _hi_near_econ = [
        e for e in econ_calendar[8:]
        if e.get("importance") == "high"
        and id(e) not in _soonest_ids
        and str(e.get("date", ""))[:10] <= _econ_hi_cutoff
    ]
    upcoming_econ = _soonest_econ + _hi_near_econ

    print("[FED] Checking Fed speaker schedule...")
    fed_speakers = fetch_fed_speakers()

    print("[ENRICH] Loading enrichment data...")
    enrichment: dict = {}
    try:
        from fetch_enrichment import run_enrichment
        enrich_path = DATA_DIR / "enrichment.json"
        # Use cached file if updated today, otherwise re-fetch
        if enrich_path.exists():
            with open(enrich_path, "r", encoding="utf-8") as _ef:
                _cached = json.load(_ef)
            if _cached.get("updated") == today:
                enrichment = _cached
                print(f"  [OK] Enrichment loaded from cache ({today})")
            else:
                enrichment = run_enrichment()
        else:
            enrichment = run_enrichment()
        fg    = enrichment.get("fear_greed", {})
        wsb   = enrichment.get("wsb_sentiment", [])
        fred  = enrichment.get("fred_proxies", {})
        oecd_cli = enrichment.get("oecd_cli", {})
        enrich_news = enrichment.get("market_news", {})
        enrich_co_news = enrichment.get("company_news", [])
        earnings_cal = enrichment.get("earnings_calendar", [])
        sent_summary = enrichment.get("sentiment_summary", {})
        print(f"  [OK] Fear & Greed: {fg.get('score','N/A')} ({fg.get('rating','N/A')})")
        print(f"  [OK] WSB top: {wsb[0]['ticker'] if wsb else 'N/A'}")
        print(f"  [OK] FRED proxies: {sum(1 for v in fred.values() if v.get('value') is not None)}")
        print(f"  [OK] OECD CLI: {len(oecd_cli)} economies")
        print(f"  [OK] Finnhub articles: {sum(len(v) for v in enrich_news.values())}")
    except Exception as _exc:
        print(f"  [WARN] Enrichment failed: {_exc}")
        fg = wsb = {}; fred = {}; oecd_cli = {}; enrich_news = enrich_co_news = {}; earnings_cal = []; sent_summary = {}

    # Merge world news + Finnhub news into buckets for the LLM
    world_buckets: dict[str, list[str]] = {}
    for a in world_news:
        cat   = a.get("category", "other")
        entry = a["title"]
        if a.get("summary"):
            entry += f"  {a['summary'][:200]}"
        world_buckets.setdefault(cat, []).append(entry)

    # Add Finnhub scored news (pre-sorted by sentiment extremes for signal density)
    for cat, articles in (enrich_news if isinstance(enrich_news, dict) else {}).items():
        sorted_arts = sorted(articles, key=lambda x: abs(x.get("sentiment", 0)), reverse=True)
        for a in sorted_arts[:4]:
            headline = a.get("headline", "")
            if any(kw in headline.lower() for kw in _NOISE_KEYWORDS):
                continue
            entry = headline
            if a.get("summary"):
                entry += f"  {a['summary'][:150]}"
            world_buckets.setdefault(cat, []).append(entry)

    # Finnhub company-level news → equity/macro buckets
    for a in (enrich_co_news if isinstance(enrich_co_news, list) else [])[:15]:
        entry = a.get("headline", "")
        if not entry:
            continue
        lower = entry.lower()
        cat = "equities"
        for bname, kws in _NEWS_BUCKETS.items():
            if any(kw in lower for kw in kws):
                cat = bname
                break
        world_buckets.setdefault(cat, []).append(entry)

    merged_buckets = dict(news_buckets)
    for cat, items in world_buckets.items():
        merged_buckets.setdefault(cat, [])
        merged_buckets[cat] = merged_buckets[cat] + items

    # De-prioritize foreign-domestic headlines (India/RBI/SE-Asia) at the source so
    # US-relevant stories fill each bucket's LLM cut. sorted() is stable, so equal-score
    # items keep their existing sentiment/recency order.
    for cat in merged_buckets:
        merged_buckets[cat] = sorted(merged_buckets[cat], key=_us_relevance_score, reverse=True)

    LLM_PER_BUCKET = 6
    llm_buckets = {cat: items[:LLM_PER_BUCKET] for cat, items in merged_buckets.items()}

    # Foreign central-bank decisions — the econ calendar is US-only, so this is the only
    # path a BOJ/ECB/BoE decision reaches the LLM. Sevens leads its macro recap with
    # these; EPM missed the BOJ hike on 6/18 and 6/22. PRIMARY = official RSS decision
    # feeds (authoritative, timely); FALLBACK = the news wire for banks without a feed
    # (SNB/PBoC) or when a feed is down. RSS wins on overlap.
    try:
        _global_cb = fetch_global_cb_decisions()
        _have = {r["institution"] for r in _global_cb}
        _wire = _harvest_global_macro_from_news(merged_buckets)
        _global_cb = _global_cb + [w for w in _wire if w.get("institution") not in _have]
        if _global_cb:
            print(f"[MACRO] {len(_global_cb)} central-bank event(s) "
                  f"({len(_have)} RSS + {len(_global_cb) - len(_have)} wire): "
                  f"{', '.join(r['institution'] for r in _global_cb)}")
    except Exception as _me:
        print(f"[WARN] Global macro feed skipped: {_me}")
        _global_cb = []

    # Build international macro context block for LLM
    international_macro = {
        "eur_usd":    fred.get("eur_per_usd", {}) if isinstance(fred, dict) else {},
        "jpy_usd":    fred.get("jpy_per_usd", {}) if isinstance(fred, dict) else {},
        "eu_cpi":     fred.get("eu_cpi_hicp", {}) if isinstance(fred, dict) else {},
        "eu_stoxx":   global_markets.get("Euro Stoxx 50", {}),
        "nikkei":     global_markets.get("Nikkei 225", {}),
        "hang_seng":  global_markets.get("Hang Seng", {}),
        # OECD Composite Leading Indicators — monthly economic momentum by country
        # value >100 = above long-run trend (expansionary); trend = improving/deteriorating
        "oecd_cli":   oecd_cli,
        # Foreign central-bank decisions from the news wire (may be empty)
        "global_central_bank_events": _global_cb,
    }

    # Derive authoritative DXY direction so the LLM writes consistent currency commentary.
    # Individual pair tickers (EURUSD=X etc.) can have stale/misaligned timestamps vs DXY.
    # We tell the LLM explicitly what direction the dollar moved and what that implies.
    _dxy_pct = (snapshot.get("U.S. Dollar (DXY)") or {}).get("pct_change") or 0.0
    if _dxy_pct > 0.05:
        _dollar_direction = "strengthened"
        _major_pairs_direction = "EUR/USD, GBP/USD, AUD/USD fell (dollar strengthened)"
    elif _dxy_pct < -0.05:
        _dollar_direction = "weakened"
        _major_pairs_direction = "EUR/USD, GBP/USD, AUD/USD rose (dollar weakened)"
    else:
        _dollar_direction = "flat"
        _major_pairs_direction = "Major pairs were little changed"

    # Build a concise summary of key data for the LLM
    key_data_summary = {
        "us_equities": {k: snapshot[k] for k in ["S&P 500", "Nasdaq 100"] if k in snapshot},
        "rates":       {k: snapshot[k] for k in ["10-Yr Yield"] if k in snapshot},
        "commodities": {k: snapshot[k] for k in ["Gold", "WTI Crude"] if k in snapshot},
        "dollar":      {k: snapshot[k] for k in ["U.S. Dollar (DXY)"] if k in snapshot},
        "dollar_direction":      _dollar_direction,
        "major_pairs_direction": _major_pairs_direction,
        "global_equities_highlights": {
            k: v for k, v in list(global_markets.items())[:6]
        },
        "bonds_spread": bonds_tbl.get("10s-2s Spread"),
        "gold_level":   commodities_tbl.get("Gold", {}).get("level"),
        "wti_level":    commodities_tbl.get("WTI Crude", {}).get("level"),
        "vix":          tech_levels.get("VIX", {}).get("current"),
        "spx_ma200":    tech_levels.get("S&P 500", {}).get("ma200"),
        "spx_52w_high": tech_levels.get("S&P 500", {}).get("52w_high"),
    }

    # Top earnings by proximity — filter to known large-caps or $2B+ market cap.
    # Symbol-based set is the primary gate; market_cap is a fallback for unlisted names.
    # (The enrichment in fetch_enrichment.py populates market_cap for up to 40 symbols
    # per run, prioritising this set — but the set catches them even if enrichment fails.)
    _PRIORITY_EARNINGS_SYMBOLS = {
        "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA",
        "AMD","INTC","QCOM","AVGO","TXN","MU","AMAT","ADI",
        "JPM","BAC","GS","MS","V","MA","WFC","C","BLK",
        "JNJ","UNH","XOM","CVX","WMT","HD","TGT","COST",
        "LOW","TJX","INTU","CRM","ORCL","IBM","ADBE",
        "DIS","NFLX","CMCSA","NKE","SBUX","MCD","PEP","KO","PG",
        "ELF","ULTA",
    }
    _MIN_MKTCAP = 2_000_000_000
    _top_earnings = [
        {"date": e["date"], "symbol": e["symbol"],
         "eps_estimate": e.get("eps_estimate"),
         "hour": e.get("hour") or ""}
        for e in (earnings_cal if isinstance(earnings_cal, list) else [])
        if e.get("symbol") and (
            e["symbol"] in _PRIORITY_EARNINGS_SYMBOLS
            or (e.get("market_cap") or 0) >= _MIN_MKTCAP
        )
    ][:8]
    # Today's earnings — only entries for report_date, with non-null eps_estimate,
    # limited to known large-caps by filtering out empty tickers
    _today_earnings = [
        e for e in _top_earnings
        if str(e.get("date", ""))[:10] == today and e.get("symbol")
    ]

    payload = {
        "date":                      today,
        "market_levels":             snapshot,
        "global_markets":            global_markets,
        "commodities":               commodities_tbl,
        "currencies":                currencies_tbl,
        "bonds":                     bonds_tbl,
        "technical_levels":          tech_levels,
        "key_data_summary":          key_data_summary,
        "portfolio_top_performers":  winners,
        "portfolio_names_to_watch":  watch,
        "mag7_consensus_forecasts":  mag7_consensus,
        "news_by_section":           llm_buckets,
        "upcoming_economic_events":  upcoming_econ,
        # Enrichment additions
        "fear_greed":                fg,
        "wsb_top5":                  (wsb[:5] if isinstance(wsb, list) else []),
        "fred_proxies":              fred,
        "international_macro":       international_macro,
        "earnings_calendar":         _top_earnings,
        "news_sentiment_summary":    sent_summary,
        "recent_earnings_actuals":   load_recent_earnings_actuals(),
        "recent_macro_prints":       load_recent_macro_prints(recent_only=True),
        "sector_performance":        sector_perf,
        # item #8: prior-day continuity for outlook call
        "prior_day_label":           _prev.get("market_outlook_label"),
        "prior_day_synthesis":       _prev.get("cross_asset_synthesis"),
        # spec #3: the catalyst the prior session teased — recap its release if it printed
        "prior_scenario_event":      _prev.get("scenario_event"),
    }

    # Write market data first so snapshot/tables are always fresh.
    # Narrative keys are explicitly cleared here — if LLM and deterministic fallback
    # both fail, the file will have empty narrative fields that downstream freshness
    # gates will detect and block from reaching clients.
    existing: dict = {}
    if COMMENTARY_PATH.exists():
        try:
            with open(COMMENTARY_PATH, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    existing["market_snapshot"]    = snapshot
    existing["global_markets"]     = global_markets
    existing["commodities_table"]  = commodities_tbl
    existing["currencies_table"]   = currencies_tbl
    existing["bonds_table"]        = bonds_tbl
    existing["futures_table"]      = futures_tbl
    existing["fed_speakers"]       = fed_speakers
    existing["today_earnings"]     = _today_earnings
    existing["technical_levels"]   = tech_levels
    existing["sector_performance"] = sector_perf
    # Pillar 2: deterministic tactical-positioning snapshot from the 30-fund book +
    # sector tilt + VIX. EPM-unique synthesis the Sevens structurally cannot replicate.
    # Wrapped so a failure can never block the pipeline.
    try:
        _vix_lvl = (tech_levels.get("VIX") or {}).get("current")
        existing["tactical_positioning"] = build_tactical_positioning(df, sector_perf, _vix_lvl)
        # Quant Desk Read — fuse the sector stance, portfolio beta tilt, and MAG7 model
        # forecast into one interpretive line (EPM's edge: the Sevens has no model book).
        try:
            _dr = _build_quant_desk_read(existing["tactical_positioning"], mag7_consensus)
            if _dr:
                existing["tactical_positioning"]["desk_read"] = _dr
                print(f"[QUANT] Desk read: {_dr[:120]}...")
        except Exception as _dre:
            print(f"[WARN] quant desk read skipped: {_dre}")
    except Exception as _tp_exc:
        print(f"[WARN] tactical_positioning skipped: {_tp_exc}")
        existing["tactical_positioning"] = {}
    existing["report_date"]        = today
    existing["generated_at"]       = datetime.now(timezone.utc).isoformat()
    existing["data_source"]        = "yfinance:daily-bar"
    # Enrichment fields — available to email renderer even if LLM skipped.
    # Write a single structured fear_greed block; remove any stale fear_greed_index
    # that may have been written by a previous LLM output or older code path.
    existing.pop("fear_greed_index", None)
    if isinstance(fg, dict) and fg.get("score") is not None:
        existing["fear_greed_score"]  = fg.get("score")
        existing["fear_greed_rating"] = fg.get("rating", "")
        existing["fear_greed"]        = {
            "score":      fg.get("score"),
            "rating":     fg.get("rating", ""),
            "prev_score": fg.get("prev_score"),
        }
        ts = fg.get("timestamp")
        if ts:
            try:
                fg_dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                age_hours = (datetime.now(timezone.utc) - fg_dt).total_seconds() / 3600
                if age_hours > 24:
                    print(f"[WARN] Fear & Greed data is {age_hours:.0f}h old (timestamp: {ts}). CNN endpoint may be stale.")
            except Exception:
                pass

    # Clear all narrative keys so prior-run prose cannot survive a failed LLM call.
    for _k in [
        "pre_market_bullets", "pre_market_summary",
        "equities_commentary", "fixed_income_commentary",
        "commodities_commentary", "currencies_commentary",
        "economics_commentary", "cross_asset_synthesis",
        "market_outlook_label", "market_outlook_rationale",
        "tactical_outperforming", "tactical_underperforming", "asset_class_outlooks",
        "portfolio_spotlight_winners", "portfolio_spotlight_watch",
        "session_recap", "watch_today", "international_section",
        "narrative_generated_at", "narrative_source_date", "narrative_source",
        "scenarios", "levels_to_watch", "scenario_event", "scenario_consensus", "scenario_event_day",
        "topic_spotlight",
    ]:
        existing.pop(_k, None)

    DATA_DIR.mkdir(exist_ok=True)
    _guard_snapshot_drift(snapshot, COMMENTARY_PATH)
    _atomic_write_json(COMMENTARY_PATH, existing)
    print(f"[OK] Market data saved -> {COMMENTARY_PATH}")

    # Fail loudly NOW if Ollama isn't on the GPU. Without this, a dead GPU driver
    # silently routes the narrative to CPU where it grinds for ~1h and the run looks
    # hung (2026-06-03 incident). Returning 1 makes monitor.py skip the PDF and the
    # send_email freshness gate block the email — the same outcome, but in seconds.
    _gpu_err = _preflight_gpu_check(_warmup_thread)
    if _gpu_err:
        print(_gpu_err)
        return 1

    print(f"[LLM] Requesting commentary from Ollama ({OLLAMA_HOST}, model={OLLAMA_MODEL})...")
    commentary = None
    known_tickers: set[str] = set()
    llm_ok = False
    try:
        commentary, known_tickers = call_ollama(payload, snapshot)
        commentary = scrub_banned_phrases(commentary)
        if validate_commentary(commentary, known_tickers=known_tickers, snapshot=snapshot,
                               watch_fallback=watch, winners_fallback=winners):
            banned = find_banned_phrases(commentary)
            if banned:
                print(f"[WARN] Commentary still contains banned phrases after scrub: {banned}")
            llm_ok = True
        else:
            print("[WARN] Commentary response invalid — falling back to deterministic prose.")
    except requests.exceptions.ConnectionError:
        print("[WARN] Ollama unreachable — falling back to deterministic prose.")
    except requests.exceptions.Timeout:
        print("[WARN] Ollama timed out — falling back to deterministic prose.")
    except Exception as exc:
        print(f"[WARN] Ollama call failed ({exc}) — falling back to deterministic prose.")

    # Topic spotlight — detect dominant news theme (fires regardless of LLM commentary path)
    _spotlight: dict | None = None
    if TOPIC_SPOTLIGHT_ENABLED:
        # Build a directional map (asset -> +1/-1/0) so the spotlight guard can reject
        # any headline that claims a move contradicting the actual close.
        def _dir_sign(entry: dict | None) -> int:
            pc = (entry or {}).get("pct_change")
            if pc is None:
                pc = (entry or {}).get("change")
            try:
                pc = float(pc)
            except (TypeError, ValueError):
                return 0
            return 1 if pc > 0.05 else (-1 if pc < -0.05 else 0)
        _market_dirs = {
            name: _dir_sign(entry)
            for name, entry in {**(snapshot or {}), **(global_markets or {})}.items()
        }
        # Enrich the payload with the deterministic tactical_positioning so the spotlight
        # (and its Pillar 1.5 data-driven fallback) can ground a feature in real data
        # when news is quiet. tactical_positioning was just computed and stored in `existing`.
        try:
            payload["tactical_positioning"] = existing.get("tactical_positioning") or {}
        except Exception:
            pass
        try:
            _spotlight = generate_topic_spotlight(
                payload,
                world_news=world_news,
                enrich_news=enrich_news,
                enrich_co_news=enrich_co_news,
                market_dirs=_market_dirs,
            )
        except Exception as _exc:
            print(f"[WARN] Topic spotlight generation failed: {_exc}")

    # Persist a compact headline corpus so the PDF/email renderers' defense-in-depth
    # sanitize pass can re-verify off-narrative geopolitical claims at render time too.
    try:
        _hl = [str(a.get("title") or a.get("headline") or "") for a in (world_news or [])]
        for _arts in (merged_buckets or {}).values():
            for _a in (_arts or []):
                _hl.append(_a if isinstance(_a, str)
                           else str(_a.get("headline") or _a.get("title") or ""))
        existing["_source_headlines"] = " ".join(h for h in _hl if h)[:6000]
    except Exception:
        pass

    # Supplement the Governors-only Fed calendar feed with regional reserve-bank presidents
    # named in today's wire (Barkin/Richmond, Daly/SF, ...). The JSON feed structurally omits
    # them, so harvest from the same corpus the scrubbers use. Runs before the persist-time
    # sanitize so a harvested name correctly grounds any narrative attribution to it.
    try:
        _harvested_fed = _harvest_fed_speakers_from_news(_hl, existing.get("fed_speakers"))
        if _harvested_fed:
            existing["fed_speakers"] = (existing.get("fed_speakers") or []) + _harvested_fed
            print(f"[FED] +{len(_harvested_fed)} regional speaker(s) harvested from news: "
                  f"{', '.join(h['speaker'] for h in _harvested_fed)}")
    except Exception as _fe:
        print(f"[WARN] Fed speaker news-harvest skipped: {_fe}")

    if llm_ok and commentary:
        existing.update(commentary)
        if _spotlight:
            existing["topic_spotlight"] = _spotlight
            existing["spotlight_teaser"] = _spotlight.get("teaser", "")
        else:
            existing.pop("topic_spotlight", None)
            existing.pop("spotlight_teaser", None)
        existing["narrative_generated_at"] = datetime.now(timezone.utc).isoformat()
        existing["narrative_source_date"]  = today
        existing["narrative_source"]       = "llm"
        # Persist the SANITIZED narrative so the website (which reads this file directly), the
        # PDF, and the email all reflect the deterministic corrections — not just the render-time
        # defense-in-depth pass. Without this the scrubbers (fabricated future-event prints,
        # today/tomorrow event slip, ungrounded Fed attribution, etc.) never reached the live
        # site, which renders latest_commentary.json verbatim (2026-06-04).
        try:
            _ns = sanitize_commentary(
                existing, snapshot, source_text=str(existing.get("_source_headlines") or "")
            )
            if _ns:
                print(f"[SANITIZE] Applied {_ns} deterministic correction(s) before persisting commentary.")
        except Exception as _se:
            print(f"[WARN] Generation-time sanitize skipped: {_se}")
        _atomic_write_json(COMMENTARY_PATH, existing)
        print(f"[OK] Commentary saved -> {COMMENTARY_PATH}")
        return 0

    # LLM failed or produced invalid output — try deterministic fallback.
    print("[INFO] Building deterministic market commentary from snapshot data...")
    try:
        det = _build_deterministic_market_commentary(snapshot, commodities_tbl, currencies_tbl, bonds_tbl)
        if validate_commentary(det, snapshot=None):
            existing.update(det)
            if _spotlight:
                existing["topic_spotlight"] = _spotlight
                existing["spotlight_teaser"] = _spotlight.get("teaser", "")
            else:
                existing.pop("topic_spotlight", None)
                existing.pop("spotlight_teaser", None)
            existing["narrative_generated_at"] = datetime.now(timezone.utc).isoformat()
            existing["narrative_source_date"]  = today
            existing["narrative_source"]       = "deterministic"
            _atomic_write_json(COMMENTARY_PATH, existing)
            print(f"[OK] Deterministic commentary saved -> {COMMENTARY_PATH}")
            return 0
        else:
            print("[WARN] Deterministic commentary failed validation.")
    except Exception as exc:
        print(f"[WARN] Deterministic commentary build failed ({exc}).")

    # Both LLM and deterministic fallback failed — narrative keys are already cleared.
    # Non-zero exit signals monitor.py to skip PDF; send_email.py freshness gate blocks email.
    print("[ERROR] No valid commentary available — blocking PDF/email generation.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
