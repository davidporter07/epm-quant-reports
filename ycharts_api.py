"""
ycharts_api.py

YCharts REST API v4 client — drop-in replacement for scrape_ycharts.py.

WHY THIS EXISTS
  The playwright scraper (scrape_ycharts.py) is now hard-blocked by a YCharts
  "Human Verification" CAPTCHA wall on login (2026-06-24): it silently produced an
  EMPTY ycharts_live.json that still passed the date-only freshness gate. See
  memory incident_ycharts_scrape_stale. The REST API v4 (api-key auth) has no
  browser login and no bot wall — it authenticated cleanly in the 6/24 smoke test —
  and is far faster (a handful of batched HTTP calls vs ~29 sequential page loads).

WHAT IT DOES
  Reads config/ycharts_indicator_map.json (the verified slug->I:code / field->metric
  map) and emits data/ycharts_live.json in the EXACT shape data_arbiter.py expects:
    { scrape_date, scrape_ts, yield_curve{label:{value,date,prev_value,prev_date}},
      economic{...}, funds{TICKER:{ticker,url,price,alpha_3y,...,updown_ratio}} }

SAFETY (fixes the three defects that made the scraper fail silently)
  1. CONTENT-AWARE: a run that yields no indicators AND no funds is a FAILURE — it
     preserves the last-good ycharts_live.json and exits non-zero (never the
     scraper's partial-save-then-clobber bug).
  2. Exits 1 on failure so monitor.py / the scheduler can DETECT it.
  3. Prints a per-field summary so failures are visible in captured stdout.

OPEN ITEMS to confirm on first live run (marked TODO below) — needs the commercial
  API key + the v4 docs (ycharts://api-reference/v4-api-docs):
    - exact api-key auth header name
    - securities points endpoint path + response shape
  The indicators path mirrors the endpoints already observed via the MCP
  (api.ycharts.com/v4/indicators/<codes>/points).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=False)

OUT_FILE       = ROOT / "data" / "ycharts_live.json"
MAP_FILE       = ROOT / "config" / "ycharts_indicator_map.json"
PORTFOLIO_FILE = ROOT / "config" / "portfolio_funds.json"
TODAY_STR      = datetime.today().strftime("%Y-%m-%d")

API_BASE = "https://api.ycharts.com/v4"
API_KEY  = os.environ.get("YCHARTS_API_KEY", "")
# CONFIRMED via the v4 OpenAPI spec (ycharts://api-reference/v4-api-docs):
#   "Requests must be authenticated using an API key for a user with the API V4
#    Add-On Feature. API keys can be found and regenerated at https://ycharts.com/api_v4.
#    Provide in the request header as:  x-ychartsauthorization: <ACCESS_TOKEN>"
AUTH_HEADER = os.environ.get("YCHARTS_AUTH_HEADER", "x-ychartsauthorization")


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def _request(method: str, path: str, params: dict | None = None,
             body: dict | None = None, retries: int = 3) -> dict:
    """{method} {API_BASE}/{path} with the api-key header; retry on transient errors."""
    url = f"{API_BASE}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {AUTH_HEADER: API_KEY, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # 4xx (bad key / not entitled) won't fix on retry — fail fast.
            if 400 <= e.code < 500 and e.code != 429:
                raise RuntimeError(f"YCharts API {e.code} for {method} {path}: {e.read()[:200]!r}") from e
            last_exc = e
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_exc = e
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"YCharts API {method} failed after {retries} tries: {path}") from last_exc


def _get(path: str, params: dict | None = None, retries: int = 3) -> dict:
    return _request("GET", path, params=params, retries=retries)


def _clean_value(raw: Any) -> Any:
    """Convert a YCharts comp-table display string to a Python number (or None).
    Mirrors scrape_ycharts._clean_value so the emitted funds match the old format:
    percentages -> decimal fraction (4.2% -> 0.042); B/M/T suffixes -> scientific."""
    if raw is None:
        return None
    s = str(raw).strip()
    if s in ("", "--", "N/A", "n/a", "NM", "NA"):
        return None
    is_pct = s.endswith("%")
    s = (s.replace("%", "").replace(",", "").replace("$", "")
           .replace("B", "e9").replace("M", "e6").replace("T", "e12").strip())
    try:
        v = float(s)
        return v / 100.0 if is_pct else v
    except ValueError:
        return str(raw).strip()


def _point(node: dict) -> tuple[Any, Any]:
    """Pull [date, value] out of a v4 points node (.results.data_point.data)."""
    try:
        data = node["results"]["data_point"]["data"]
        return data[0], data[1]
    except (KeyError, TypeError, IndexError):
        return None, None


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def _load_map() -> dict:
    with open(MAP_FILE, encoding="utf-8") as f:
        return json.load(f)


def _codes(section: dict) -> dict[str, str]:
    """field/label -> code for a config section, skipping _meta keys."""
    return {k: v["code"] for k, v in section.items() if not k.startswith("_") and isinstance(v, dict)}


# ---------------------------------------------------------------------------
# Indicators (yield curve + economic) — 2 batched calls (latest + prev period)
# ---------------------------------------------------------------------------
def fetch_indicators(cfg: dict) -> dict[str, dict]:
    out: dict[str, dict] = {"yield_curve": {}, "economic": {}}
    for section_key in ("yield_curve", "economic"):
        label_to_code = _codes(cfg[section_key])
        codes = list(dict.fromkeys(label_to_code.values()))  # de-dupe (Fed_Funds is shared)
        if not codes:
            continue
        joined = ",".join(codes)
        latest = _get(f"indicators/{joined}/points")["response"]["data"]
        prev   = _get(f"indicators/{joined}/points", params={"date": "-1"})["response"]["data"]

        for label, code in label_to_code.items():
            d, v   = _point(latest.get(code, {}))
            pd, pv = _point(prev.get(code, {}))
            entry: dict[str, Any] = {}
            if v is not None:
                entry["value"], entry["date"] = v, d
            if pv is not None:
                entry["prev_value"], entry["prev_date"] = pv, pd
            out[section_key][label] = entry
            status = f"{v} ({d})" if v is not None else "[EMPTY]"
            print(f"  {section_key[:5]:5s} {label:18s} {status}")
    return out


# ---------------------------------------------------------------------------
# Fund metrics — via the persistent comp table backed by a watchlist
# (v4 has NO per-security points endpoint; comp_tables/{id} is the only way to
#  pull per-security metrics. Object IDs live in config _ycharts_objects.)
# ---------------------------------------------------------------------------
def sync_watchlist(cfg: dict, tickers: list[str]) -> None:
    """Best-effort: keep the backing watchlist == portfolio_funds.json. If the
    REST PUT shape is off it warns and continues (the comp table still computes
    over whatever the watchlist currently holds)."""
    obj = cfg.get("_ycharts_objects", {})
    wl_id = obj.get("watchlist_id")
    if not wl_id:
        return
    try:
        cur = _get(f"watchlists/{wl_id}", params={"page_size": 500})["response"]["watchlist_items"]
        cur_syms = {it.get("security_id", "").upper() for it in cur}
        want_syms = {t.upper().strip() for t in tickers}
        if cur_syms == want_syms:
            return
        print(f"  [sync] watchlist drift (have {len(cur_syms)}, want {len(want_syms)}) — updating")
        _request("PUT", f"watchlists/{wl_id}", body={"security_ids": sorted(want_syms)})
    except Exception as e:
        print(f"  [sync][WARN] could not sync watchlist {wl_id}: {e} "
              "(continuing with its current contents)")


def fetch_funds(cfg: dict, tickers: list[str]) -> dict[str, dict]:
    obj = cfg.get("_ycharts_objects", {})
    ct_id = obj.get("comp_table_id")
    if not ct_id:
        print("  [funds][ERROR] no comp_table_id in config _ycharts_objects")
        return {}

    field_to_code = _codes(cfg["fund_metrics"])          # field -> calc-name code
    code_to_field = {c: f for f, c in field_to_code.items()}

    # GET recomputes the table fresh; page through all rows.
    rows: list[dict] = []
    page = 1
    while True:
        resp = _get(f"comp_tables/{ct_id}", params={"page": page, "page_size": 100})["response"]
        rows.extend(resp["data"]["rows"])
        nxt = resp["pagination"].get("next_page")
        if not nxt:
            break
        page = nxt

    out: dict[str, dict] = {}
    for row in rows:
        ticker = (row.get("display_security_id") or "").upper().strip()
        if not ticker:
            continue
        base = "mutual_funds" if row.get("security_type") == "mutual_fund" else "companies"
        fund: dict[str, Any] = {
            "ticker": ticker,
            "url": "https://ycharts.com" + (row.get("ycharts_url") or f"/{base}/{ticker}"),
        }
        got = False
        for code, field in code_to_field.items():
            if code in row:
                v = _clean_value(row[code])
                if v is not None:
                    fund[field] = v
                    got = True
        # updown_ratio = up_capture / down_capture (the YCharts "Capture Ratio" row).
        up, down = fund.get("up_capture_3y"), fund.get("down_capture_3y")
        if isinstance(up, (int, float)) and isinstance(down, (int, float)) and down != 0:
            fund["updown_ratio"] = up / down
        if not got:
            fund["error"] = "no metrics returned"
        out[ticker] = fund
        print(f"  fund  {ticker:8s} sharpe={fund.get('sharpe_3y','?')} "
              f"1m={fund.get('return_1m','?')} [{'ok' if got else 'EMPTY'}]")
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run() -> dict:
    if not API_KEY:
        print("[YChartsAPI][ERROR] YCHARTS_API_KEY not set — cannot call the REST API. "
              "Preserving last-good cache. Get the key (requires the 'API V4 Add-On "
              "Feature') at https://ycharts.com/api_v4 and add YCHARTS_API_KEY=<key> to .env.")
        return {}

    cfg = _load_map()
    with open(PORTFOLIO_FILE, encoding="utf-8") as f:
        tickers = json.load(f).get("portfolio_ycharts_symbols", [])

    results: dict[str, Any] = {
        "scrape_date": TODAY_STR,
        "scrape_ts":   datetime.now().isoformat(),
        "yield_curve": {},
        "economic":    {},
        "funds":       {},
    }

    print("[YChartsAPI] Indicators (yield curve + economic)...")
    try:
        results.update(fetch_indicators(cfg))
    except Exception as e:
        print(f"[YChartsAPI][WARN] indicator fetch failed: {e}")

    print("[YChartsAPI] Fund metrics (watchlist-backed comp table)...")
    try:
        sync_watchlist(cfg, tickers)
        results["funds"] = fetch_funds(cfg, tickers)
    except Exception as e:
        print(f"[YChartsAPI][WARN] fund fetch failed: {e}")

    # ---- CONTENT-AWARE guard (the scraper's missing safety) --------------------
    good_funds = {k: v for k, v in results["funds"].items() if not v.get("error")}
    have_indicators = any(e.get("value") is not None
                          for sec in ("yield_curve", "economic")
                          for e in results[sec].values())
    if not good_funds and not have_indicators:
        print("[YChartsAPI][ERROR] No funds AND no indicators returned — preserving "
              f"last-good {OUT_FILE.name}, NOT overwriting. Run FAILED.")
        return {}

    OUT_FILE.parent.mkdir(exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n[YChartsAPI] Saved -> {OUT_FILE}")
    print(f"  Yield curve: {sum(1 for e in results['yield_curve'].values() if e.get('value') is not None)}/"
          f"{len(results['yield_curve'])}")
    print(f"  Economic:    {sum(1 for e in results['economic'].values() if e.get('value') is not None)}/"
          f"{len(results['economic'])}")
    print(f"  Funds:       {len(good_funds)}/{len(results['funds'])} OK")
    return results


if __name__ == "__main__":
    _res = run()
    # Non-zero exit on failure so monitor.py / schedulers DETECT it (never silently
    # reuse a stale/empty ycharts_live.json — the 2026-05-08 freeze + 2026-06-24 CAPTCHA).
    ok = bool(_res) and (
        any(e.get("value") is not None for e in _res.get("yield_curve", {}).values())
        or any(not v.get("error") for v in _res.get("funds", {}).values())
    )
    sys.exit(0 if ok else 1)
