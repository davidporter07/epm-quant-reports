"""
deep_analysis.py — Seed document generator for the MiroFish deep analysis pipeline.

Seed doc is structured as labeled analytical perspective sections so MiroFish's
ontology extractor builds agents from the right entities (Technical Analysis,
Federal Reserve, Supply Chain Risk, etc.) rather than generic stakeholder roles.

Each section header IS the entity name — agents reason from the data in their section.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import yfinance as yf

from news_store import load_news_store
from universe_config import get_portfolio_tickers

KRONOS_URL = "http://192.168.1.145:8100"
DATA_DIR = Path("data")

_EPM_MODEL_FILES: Dict[str, Tuple[str, str]] = {
    "Linear Regression":  ("linear_forecasts.csv",       "Linear Model Forecast (%)"),
    "Fama-French":        ("fama_french_forecasts.csv",  "FF Forecast (%)"),
    "Machine Learning":   ("ml_forecasts.csv",            "ML Forecast (%)"),
    "ARIMAX":             ("arimax_forecasts.csv",         "ARIMAX Forecast (%)"),
    "Deep Learning":      ("dl_forecasts.csv",            "DL Forecast (%)"),
    "Institutional Flow": ("institutional_forecasts.csv", "Institutional Forecast (%)"),
}


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------

def _get_ohlcv(ticker: str, days: int = 252) -> List[dict]:
    df = yf.download(ticker, period=f"{days}d", interval="1d", progress=False, auto_adjust=True)
    if df.empty:
        return []
    candles = []
    for date, row in df.iterrows():
        def _f(col: str) -> float:
            v = row[col]
            return float(v.iloc[0]) if hasattr(v, "iloc") else float(v)
        candles.append({
            "date":   date.strftime("%Y-%m-%d"),
            "open":   round(_f("Open"),   2),
            "high":   round(_f("High"),   2),
            "low":    round(_f("Low"),    2),
            "close":  round(_f("Close"),  2),
            "volume": _f("Volume"),
        })
    return candles


def _get_kronos_scenarios(ticker: str, ohlcv: List[dict], pred_len: int = 5) -> List[List[dict]]:
    """
    Fetch Kronos OHLCV scenarios. Returns a list of forecast scenarios (each is a list of daily dicts).
    Handles both single-forecast and multi-sample response formats.
    """
    r = requests.post(
        f"{KRONOS_URL}/forecast",
        json={"ticker": ticker, "ohlcv": ohlcv, "pred_len": pred_len, "sample_count": 3},
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()

    # Multi-sample: {"forecasts": [[{day}, ...], [{day}, ...], ...]}
    if "forecasts" in data and isinstance(data["forecasts"], list):
        scenarios = [s for s in data["forecasts"] if isinstance(s, list) and s]
        if scenarios:
            return scenarios

    # Nested single: {"forecast": [[{day}, ...], ...]}
    if "forecast" in data:
        fc = data["forecast"]
        if isinstance(fc, list) and fc:
            if isinstance(fc[0], list):
                return [s for s in fc if s]
            if isinstance(fc[0], dict):
                return [fc]  # single scenario

    return []


def _get_epm_forecasts(ticker: str) -> Optional[Dict[str, float]]:
    """Raw model percentage outputs — no directional labels."""
    universe = [t.upper() for t in get_portfolio_tickers()]
    if ticker.upper() not in universe:
        return None

    forecasts: Dict[str, float] = {}
    for model_name, (filename, col) in _EPM_MODEL_FILES.items():
        path = DATA_DIR / filename
        if not path.exists():
            continue
        df = pd.read_csv(path)
        df["Ticker"] = df["Ticker"].astype(str).str.upper()
        row = df[df["Ticker"] == ticker.upper()]
        if row.empty or col not in row.columns:
            continue
        val = pd.to_numeric(row.iloc[-1][col], errors="coerce")
        if pd.notna(val):
            forecasts[model_name] = round(float(val), 2)

    return forecasts if forecasts else None


def _get_news_headlines(ticker: str, max_headlines: int = 10) -> List[str]:
    store = load_news_store()
    ticker_news = store[store["Ticker"] == ticker.upper()].copy()

    if not ticker_news.empty:
        ticker_news = ticker_news.sort_values("PublishedAt", ascending=False)
        return [h for h in ticker_news["Headline"].head(max_headlines).tolist() if h]

    try:
        raw = yf.Ticker(ticker).news or []
        return [n.get("content", {}).get("title", "") or n.get("title", "")
                for n in raw[:max_headlines]
                if (n.get("content", {}).get("title") or n.get("title"))]
    except Exception:
        return []


def _compute_technicals(ohlcv: List[dict]) -> Dict:
    """RSI(14), momentum, volume trend, 52-week range, MAs."""
    closes  = [c["close"]  for c in ohlcv]
    volumes = [c["volume"] for c in ohlcv]
    current = closes[-1]

    rsi = None
    if len(closes) >= 15:
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains  = [max(d, 0) for d in deltas]
        losses = [abs(min(d, 0)) for d in deltas]
        avg_gain = float(np.mean(gains[-14:]))
        avg_loss = float(np.mean(losses[-14:]))
        if avg_loss > 0:
            rs = avg_gain / avg_loss
            rsi = round(100 - (100 / (1 + rs)), 1)
        else:
            rsi = 100.0

    mom5  = round((current / closes[-6]  - 1) * 100, 2) if len(closes) >= 6  else None
    mom20 = round((current / closes[-21] - 1) * 100, 2) if len(closes) >= 21 else None

    vol_ratio = None
    if len(volumes) >= 20:
        avg20 = float(np.mean(volumes[-20:]))
        avg5  = float(np.mean(volumes[-5:]))
        if avg20 > 0:
            vol_ratio = round(avg5 / avg20, 2)

    high52 = round(max(c["high"] for c in ohlcv), 2)
    low52  = round(min(c["low"]  for c in ohlcv), 2)
    pct_from_high = round((current / high52 - 1) * 100, 1) if high52 else None
    pct_from_low  = round((current / low52  - 1) * 100, 1) if low52  else None
    ma50  = round(float(np.mean(closes[-50:])),  2) if len(closes) >= 50  else None
    ma200 = round(float(np.mean(closes[-200:])), 2) if len(closes) >= 200 else None

    return {
        "current": round(current, 2),
        "rsi": rsi, "mom5": mom5, "mom20": mom20, "vol_ratio": vol_ratio,
        "high52": high52, "low52": low52,
        "pct_from_high": pct_from_high, "pct_from_low": pct_from_low,
        "ma50": ma50, "ma200": ma200,
    }


def _get_company_info(ticker: str) -> Dict:
    try:
        info = yf.Ticker(ticker).info
        return {
            "name":     info.get("longName") or info.get("shortName") or ticker,
            "sector":   info.get("sector"),
            "industry": info.get("industry"),
            "country":  info.get("country"),
        }
    except Exception:
        return {"name": ticker, "sector": None, "industry": None, "country": None}


def _get_vix() -> Optional[float]:
    """Fetch current VIX level."""
    try:
        # Use Ticker.history() — avoids the MultiIndex column issues that yf.download causes
        # for indices when auto_adjust=True, which produces inflated values.
        hist = yf.Ticker("^VIX").history(period="5d", interval="1d")
        if not hist.empty:
            v = hist["Close"].iloc[-1]
            val = float(v.iloc[0]) if hasattr(v, "iloc") else float(v)
            # Sanity-check: VIX is always between 5 and 150
            if 5 <= val <= 150:
                return round(val, 1)
    except Exception:
        pass
    return None


def _get_spy_trend() -> Dict:
    """Fetch SPY recent returns for macro context."""
    result: Dict = {}
    try:
        df = yf.download("SPY", period="30d", interval="1d", progress=False, auto_adjust=True)
        if not df.empty:
            closes = [float(v.iloc[0]) if hasattr(v, "iloc") else float(v) for v in df["Close"]]
            current = closes[-1]
            if len(closes) >= 6:
                result["spy_5d"] = round((current / closes[-6] - 1) * 100, 2)
            if len(closes) >= 21:
                result["spy_20d"] = round((current / closes[-21] - 1) * 100, 2)
    except Exception:
        pass
    return result


def _get_earnings_info(ticker: str) -> Optional[Dict]:
    """Next earnings date from yfinance calendar."""
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is None:
            return None
        today = datetime.now().date()

        # calendar is a DataFrame (columns = dates, rows = metrics)
        if hasattr(cal, "columns"):
            for col in cal.columns:
                try:
                    d = pd.to_datetime(col).date()
                    if d >= today:
                        days_until = (d - today).days
                        return {"date": str(d), "days_until": days_until}
                except Exception:
                    continue

        # calendar is a dict
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date", [])
            if not isinstance(dates, (list, tuple)):
                dates = [dates]
            for raw in dates:
                try:
                    d = pd.to_datetime(raw).date()
                    if d >= today:
                        days_until = (d - today).days
                        return {"date": str(d), "days_until": days_until}
                except Exception:
                    continue
    except Exception:
        pass
    return None


def _vix_label(vix: float) -> str:
    if vix < 15:
        return "low — market complacent"
    if vix < 20:
        return "normal range"
    if vix < 25:
        return "elevated — market uncertainty"
    if vix < 30:
        return "high — significant fear"
    return "extreme — crisis-level fear"


def _scenario_label(implied_move: float, scenarios: List[List[dict]], idx: int) -> str:
    """Label a Kronos scenario based on its position among all scenarios."""
    if len(scenarios) == 1:
        return "Base Scenario"
    moves = sorted([(s[-1]["close"], i) for i, s in enumerate(scenarios)])
    rank = next(r for r, (_, i) in enumerate(moves) if i == idx)
    labels = {0: "Bearish Case", len(scenarios) - 1: "Bullish Case"}
    return labels.get(rank, "Base Case")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_seed_doc(ticker: str, pred_len: int = 5) -> str:
    """
    Build a MiroFish seed document structured as analytical perspective sections.

    Section headers act as entity names for MiroFish's ontology extractor, seeding
    agents that reason from technical data, macro context, supply chain risk, etc.
    """
    ticker = ticker.upper()
    today  = datetime.now().strftime("%Y-%m-%d")

    ohlcv    = _get_ohlcv(ticker, days=252)
    if not ohlcv:
        raise ValueError(f"No OHLCV data available for {ticker}")

    kronos_input = ohlcv[-60:]
    scenarios    = _get_kronos_scenarios(ticker, kronos_input, pred_len=pred_len)
    tech         = _compute_technicals(ohlcv)
    epm          = _get_epm_forecasts(ticker)
    headlines    = _get_news_headlines(ticker)
    co_info      = _get_company_info(ticker)
    vix          = _get_vix()
    spy          = _get_spy_trend()
    earnings     = _get_earnings_info(ticker)

    current = tech["current"]
    sector  = (co_info.get("sector") or "").lower()

    lines: List[str] = [
        f"{ticker} — {co_info['name']}",
        f"Sector: {co_info['sector'] or 'N/A'} | Industry: {co_info['industry'] or 'N/A'}",
        f"Market Intelligence Brief: {today}",
        "",
    ]

    # ── TECHNICAL ANALYSIS PERSPECTIVE ───────────────────────────────────────
    lines.append("── TECHNICAL ANALYSIS PERSPECTIVE ──────────────────────────────────────────")
    price_line = f"Current Price: ${current:.2f}"
    if tech["ma50"]:
        gap = (current / tech["ma50"] - 1) * 100
        price_line += f" | MA50: ${tech['ma50']:.2f} ({gap:+.1f}%)"
    if tech["ma200"]:
        gap = (current / tech["ma200"] - 1) * 100
        price_line += f" | MA200: ${tech['ma200']:.2f} ({gap:+.1f}%)"
    lines.append(price_line)

    if tech["high52"] and tech["low52"]:
        lines.append(
            f"52-Week Range: ${tech['low52']} – ${tech['high52']} | "
            f"Currently {tech['pct_from_high']:+.1f}% from 52w high, "
            f"{tech['pct_from_low']:+.1f}% from 52w low"
        )

    sig_parts = []
    if tech["rsi"] is not None:
        zone = "overbought" if tech["rsi"] > 70 else ("oversold" if tech["rsi"] < 30 else "neutral zone")
        sig_parts.append(f"RSI(14): {tech['rsi']:.1f} ({zone})")
    if tech["mom5"] is not None:
        sig_parts.append(f"5-day momentum: {tech['mom5']:+.2f}%")
    if tech["mom20"] is not None:
        sig_parts.append(f"20-day momentum: {tech['mom20']:+.2f}%")
    if tech["vol_ratio"] is not None:
        direction = "above" if tech["vol_ratio"] > 1 else "below"
        sig_parts.append(f"Volume: {tech['vol_ratio']:.2f}x 20-day avg ({direction}-average)")
    if sig_parts:
        lines.append(" | ".join(sig_parts))

    lines.append("")
    lines.append("Recent 10-Session Price Action:")
    lines.append("| Date | Open | High | Low | Close | Daily Change |")
    lines.append("|------|------|------|-----|-------|-------------|")
    recent = ohlcv[-10:]
    for i, c in enumerate(recent):
        prev_close = recent[i - 1]["close"] if i > 0 else c["open"]
        chg = (c["close"] / prev_close - 1) * 100 if prev_close else 0
        lines.append(
            f"| {c['date']} | ${c['open']:.2f} | ${c['high']:.2f} | "
            f"${c['low']:.2f} | ${c['close']:.2f} | {chg:+.2f}% |"
        )
    lines.append("")

    # ── KRONOS OHLCV FOUNDATION MODEL ────────────────────────────────────────
    lines.append(f"── KRONOS OHLCV FOUNDATION MODEL — Next {pred_len} Trading Days ────────────────────")
    if scenarios:
        for idx, scenario in enumerate(scenarios):
            label = _scenario_label(
                (scenario[-1]["close"] / current - 1) * 100, scenarios, idx
            )
            implied = (scenario[-1]["close"] / current - 1) * 100
            lines.append(f"{label} (Kronos implied: {implied:+.1f}% to ${scenario[-1]['close']:.2f}):")
            lines.append("| Date | Open | High | Low | Close | Volume |")
            lines.append("|------|------|------|-----|-------|--------|")
            for c in scenario:
                lines.append(
                    f"| {c['date']} | ${c['open']:.2f} | ${c['high']:.2f} | "
                    f"${c['low']:.2f} | ${c['close']:.2f} | {c['volume']/1e6:.1f}M |"
                )
            ranges = [c["high"] - c["low"] for c in scenario]
            lines.append(f"Avg daily range: ${float(np.mean(ranges)):.2f} | Max daily range: ${max(ranges):.2f}")
            lines.append("")
    else:
        lines.append("Kronos forecast unavailable.")
        lines.append("")

    # ── EPM QUANTITATIVE ENSEMBLE ─────────────────────────────────────────────
    if epm:
        lines.append("── EPM QUANTITATIVE ENSEMBLE — 5-Day Return Forecasts ──────────────────────────")
        for model_name, val in epm.items():
            lines.append(f"- {model_name}: {val:+.2f}%")
        vals = list(epm.values())
        spread = round(max(vals) - min(vals), 2)
        max_model = max(epm, key=lambda k: epm[k])
        min_model = min(epm, key=lambda k: epm[k])
        lines.append(
            f"Model spread: {spread:.2f}% | Most optimistic: {max_model} ({epm[max_model]:+.2f}%) | "
            f"Most pessimistic: {min_model} ({epm[min_model]:+.2f}%)"
        )
        lines.append("")

    # ── GROWTH INVESTOR PERSPECTIVE ───────────────────────────────────────────
    lines.append("── GROWTH INVESTOR PERSPECTIVE ─────────────────────────────────────────────────")
    lines.append(
        f"From a growth-oriented investment perspective on {co_info['name']}: Focus on revenue "
        f"trajectory, market share dynamics, and long-term secular tailwinds. Are current quantitative "
        f"models capturing the compounding effect of margin expansion and reinvestment at scale? "
        f"Does the near-term volatility represent an opportunity to build a position in a structural "
        f"winner, or does it signal a genuine breakdown in the growth thesis that demands reassessment?"
    )
    lines.append("")

    # ── VALUE INVESTOR PERSPECTIVE ────────────────────────────────────────────
    lines.append("── VALUE INVESTOR PERSPECTIVE ──────────────────────────────────────────────────")
    lines.append(
        f"From a fundamental valuation standpoint on {co_info['name']}: What does the current "
        f"price imply about normalized long-run earnings power and return on invested capital? "
        f"Is the stock pricing in a durable competitive moat or extrapolating unsustainable "
        f"near-term momentum? Does the short-term model spread diverge from the long-term "
        f"fundamental trajectory, and what is the margin of safety at current levels?"
    )
    lines.append("")

    # ── MARKET COMMENTATOR PERSPECTIVE ───────────────────────────────────────
    lines.append("── MARKET COMMENTATOR PERSPECTIVE ──────────────────────────────────────────────")
    lines.append(
        f"From a market commentary and sentiment perspective on {ticker}: How is the financial "
        f"media and retail investor narrative currently framing this stock — momentum play, "
        f"turnaround story, or value trap? What headline catalyst would most rapidly shift "
        f"sentiment in either direction? Are options markets pricing complacency or genuine "
        f"tail-risk hedging relative to the technical picture and model forecasts?"
    )
    lines.append("")

    # ── BEARISH ANALYST PERSPECTIVE ───────────────────────────────────────────
    lines.append("── BEARISH ANALYST PERSPECTIVE ─────────────────────────────────────────────────")
    lines.append(
        f"The bear case for {ticker}: What risk factors are bulls systematically underweighting? "
        f"Where is market consensus most likely wrong? If the most pessimistic quantitative model "
        f"proves correct, identify the specific catalyst that triggers it and the transmission "
        f"mechanism to price. What asymmetric downside scenario are the models failing to price in, "
        f"and what hedging approach would a short-focused analyst recommend given current technicals?"
    )
    lines.append("")

    # ── MACRO / FEDERAL RESERVE PERSPECTIVE ──────────────────────────────────
    lines.append("── MACRO / FEDERAL RESERVE PERSPECTIVE ─────────────────────────────────────────")
    if vix is not None:
        lines.append(f"VIX (Fear Index): {vix} — {_vix_label(vix)}")
    if spy.get("spy_5d") is not None:
        lines.append(f"S&P 500 5-day return: {spy['spy_5d']:+.2f}% | 20-day return: {spy.get('spy_20d', 'N/A'):+.2f}%"
                     if spy.get("spy_20d") is not None else f"S&P 500 5-day return: {spy['spy_5d']:+.2f}%")
    lines.append(
        "Interest Rate Environment: Federal Reserve maintaining elevated rates (Fed Funds Rate above 4%). "
        "Higher-for-longer policy increases discount rates on future earnings, creating headwinds for "
        "growth-oriented equities and affecting capital allocation across sectors."
    )
    lines.append("")

    # ── SUPPLY CHAIN & GEOPOLITICAL RISK PERSPECTIVE ─────────────────────────
    lines.append("── SUPPLY CHAIN & GEOPOLITICAL RISK PERSPECTIVE ────────────────────────────────")
    if "technology" in sector or "consumer electronics" in sector.lower():
        lines.append(
            f"{co_info['name']} operates with significant manufacturing concentration in China "
            f"(~85-90% of final assembly for key products). US-China trade policy, tariff regimes, "
            f"and export controls on semiconductors create structural cost and margin risk that "
            f"quantitative models do not capture. Potential retaliatory measures in the Chinese "
            f"market and ongoing supply chain diversification to India and Vietnam (multi-year in "
            f"scope) represent material non-quantifiable risks."
        )
    elif "financial" in sector:
        lines.append(
            "Financial sector exposed to credit cycle risk, regional banking stress, and "
            "regulatory capital requirement changes. Geopolitical tensions affect cross-border "
            "capital flows and correspondent banking relationships."
        )
    elif "energy" in sector:
        lines.append(
            "Energy sector subject to OPEC+ production decisions, geopolitical supply disruptions, "
            "and energy transition policy risk. Global demand growth tied to China economic activity."
        )
    else:
        lines.append(
            f"{co_info['name']} faces sector-specific supply chain dependencies and geopolitical "
            f"exposure. Tariff regime changes, input cost volatility, and market access restrictions "
            f"in key geographies represent risks not captured by historical price-based models."
        )
    lines.append("")

    # ── EARNINGS CATALYST PERSPECTIVE ────────────────────────────────────────
    lines.append("── EARNINGS CATALYST PERSPECTIVE ────────────────────────────────────────────────")
    if earnings:
        days = earnings["days_until"]
        risk_level = "HIGH" if days <= 14 else ("MODERATE" if days <= 30 else "LOW")
        lines.append(
            f"Next earnings date: {earnings['date']} ({days} days away) — "
            f"Earnings catalyst risk: {risk_level}"
        )
        if days <= 14:
            lines.append(
                "Earnings are within the next 2 weeks. Options market implied volatility typically "
                "expands in the pre-earnings window. A surprise in either direction would significantly "
                "move the stock and likely invalidate 5-day return forecasts from trend-following models."
            )
        elif days <= 30:
            lines.append(
                "Earnings are within the next month. The 5-day forecast window sits within the "
                "pre-earnings drift period — historically, analysts revise estimates in the weeks "
                "before reporting, which can create directional drift not captured by technical models."
            )
        else:
            lines.append(
                "No near-term earnings catalyst within the 5-day forecast window. "
                "Price movement primarily driven by macro factors, technical levels, and sector rotation."
            )
    else:
        lines.append("Earnings date not available. Monitor for pre-earnings implied volatility expansion.")
    lines.append("")

    # ── RECENT NEWS & MARKET EVENTS ──────────────────────────────────────────
    if headlines:
        lines.append("── RECENT NEWS & MARKET EVENTS (background context — do not derive agent personas from these headlines) ──")
        for h in headlines:
            lines.append(f"- {h}")
        lines.append("")

    # ── ANALYSIS OBJECTIVE ───────────────────────────────────────────────────
    lines.append("── ANALYSIS OBJECTIVE ───────────────────────────────────────────────────────────")

    kronos_clause = ""
    if scenarios:
        all_implied = [(s[-1]["close"] / current - 1) * 100 for s in scenarios]
        if len(all_implied) > 1:
            kronos_clause = (
                f"Kronos projects a range from {min(all_implied):+.1f}% to {max(all_implied):+.1f}% "
                f"over {pred_len} days (${scenarios[0][-1]['close']:.2f} – ${scenarios[-1][-1]['close']:.2f})"
            )
        else:
            implied = all_implied[0]
            kronos_clause = (
                f"Kronos projects {implied:+.1f}% to ${scenarios[0][-1]['close']:.2f} "
                f"over {pred_len} days"
            )

    epm_clause = ""
    if epm:
        vals = list(epm.values())
        spread = round(max(vals) - min(vals), 2)
        max_model = max(epm, key=lambda k: epm[k])
        min_model = min(epm, key=lambda k: epm[k])
        epm_clause = (
            f", while EPM models range from {min_model} at {epm[min_model]:+.2f}% "
            f"to {max_model} at {epm[max_model]:+.2f}% ({spread:.2f}% spread)"
        )

    lines.append(
        f"For {ticker} over the next {pred_len} trading days: {kronos_clause}{epm_clause}. "
        f"Given this data, across all analytical perspectives above: "
        f"(1) Under what specific market conditions or catalysts would {min_model if epm else 'the most pessimistic'}s "
        f"forecast prove correct — be specific about the trigger and mechanism. "
        f"(2) Where is the asymmetric risk — is the potential downside or upside more likely being underestimated, and why? "
        f"(3) What are the 2-3 most critical non-obvious risks that quantitative models cannot capture "
        f"(regulatory, geopolitical, supply chain, behavioral)? "
        f"(4) Does the model spread signal genuine directional uncertainty or do models simply weight different risk factors differently? "
        f"Prioritize specific insight and scenario analysis over directional summary."
    )

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(f"Building seed doc for {ticker}...")
    doc = build_seed_doc(ticker)
    print(doc)
    print(f"\n--- {len(doc)} chars, ~{len(doc.split())} words ---")
