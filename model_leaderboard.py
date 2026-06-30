# model_leaderboard.py
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

DATA_DIR = Path("data")
LOG_PATH = DATA_DIR / "prediction_log.parquet"

OUT_SUMMARY = DATA_DIR / "model_leaderboard_summary.csv"
OUT_BY_TICKER = DATA_DIR / "model_leaderboard_by_ticker.csv"
OUT_PENDING = DATA_DIR / "model_leaderboard_pending.csv"
OUT_HTML = DATA_DIR / "model_leaderboard.html"


MAG7_DEFAULT = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOG", "META", "TSLA"]


def _dt(s) -> pd.Timestamp:
    return pd.to_datetime(s, errors="coerce")


def _iso(d: pd.Timestamp) -> str:
    return d.date().isoformat()


def _load_log(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing prediction log: {path}")
    df = pd.read_parquet(path)
    # enforce expected columns
    for c in ["RunDate", "Ticker", "Model", "Horizon", "ForecastPct", "CI_Lower", "CI_Upper"]:
        if c not in df.columns:
            df[c] = np.nan
    df["RunDate"] = pd.to_datetime(df["RunDate"], errors="coerce")
    df["Ticker"] = df["Ticker"].astype(str).str.upper().str.strip()
    df["Model"] = df["Model"].astype(str).str.strip()
    df["Horizon"] = pd.to_numeric(df["Horizon"], errors="coerce").fillna(21).astype(int)
    for c in ["ForecastPct", "CI_Lower", "CI_Upper"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["RunDate", "Ticker", "Model", "ForecastPct"])
    return df


def _download_prices_yf(tickers: List[str], start: str, end: str) -> pd.DataFrame:
    """
    Uses yfinance if installed. Returns wide df: index=date, columns=tickers (Adj Close preferred else Close).
    """
    import yfinance as yf  # local import

    px = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        progress=False,
        group_by="ticker",
        auto_adjust=False,
        threads=True,
    )

    # Normalize to a wide 'close' table (date x ticker)
    if isinstance(px.columns, pd.MultiIndex):
        # Could be (Ticker, Field) or (Field, Ticker). Handle both.
        lvl0 = set(px.columns.get_level_values(0))
        lvl1 = set(px.columns.get_level_values(1))

        field_candidates = ["Adj Close", "Close"]
        # Case A: (Field, Ticker)
        if any(f in lvl0 for f in field_candidates):
            field = "Adj Close" if "Adj Close" in lvl0 else "Close"
            out = px[field].copy()
            out.columns = [str(c).upper() for c in out.columns]
            return out

        # Case B: (Ticker, Field)
        if any(f in lvl1 for f in field_candidates):
            field = "Adj Close" if "Adj Close" in lvl1 else "Close"
            out = pd.DataFrame(index=px.index)
            for t in tickers:
                tu = t.upper()
                if (tu, field) in px.columns:
                    out[tu] = px[(tu, field)]
                elif (t, field) in px.columns:
                    out[tu] = px[(t, field)]
            return out

        raise KeyError("Could not find Close/Adj Close in yfinance multiindex output.")

    # Single ticker case
    if "Adj Close" in px.columns:
        out = px[["Adj Close"]].rename(columns={"Adj Close": tickers[0].upper()})
    elif "Close" in px.columns:
        out = px[["Close"]].rename(columns={"Close": tickers[0].upper()})
    else:
        raise KeyError("Could not find Close/Adj Close columns in yfinance output.")
    return out


def _realized_forward_return_from_prices(
    prices: pd.DataFrame,
    run_date: pd.Timestamp,
    horizon: int,
) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp], Optional[float]]:
    """
    Uses trading days from the price index.
    start_date = first trading day >= run_date
    end_date   = trading day at start_idx + horizon
    return     = (end/start - 1) * 100
    """
    if prices.empty:
        return None, None, None

    idx = prices.index
    # ensure sorted and tz-naive
    idx = pd.DatetimeIndex(pd.to_datetime(idx)).tz_localize(None)
    run_date = run_date.tz_localize(None) if run_date.tzinfo else run_date

    # find first idx >= run_date
    pos = idx.searchsorted(run_date)
    if pos >= len(idx):
        return None, None, None
    start_dt = idx[pos]

    end_pos = pos + horizon
    if end_pos >= len(idx):
        return start_dt, None, None
    end_dt = idx[end_pos]

    start_px = prices.loc[start_dt]
    end_px = prices.loc[end_dt]
    if pd.isna(start_px) or pd.isna(end_px) or start_px == 0:
        return start_dt, end_dt, None

    realized = (float(end_px) / float(start_px) - 1.0) * 100.0
    return start_dt, end_dt, realized


def _greedy_nonoverlap(g: pd.DataFrame) -> pd.DataFrame:
    """Pick a chain of predictions whose forward [start, end] windows do not overlap.

    Daily forecasts of a 21-trading-day return overlap ~95% (consecutive windows share
    20 of 21 days), so a hit-rate computed over all of them is built on only a handful of
    INDEPENDENT outcomes and looks more impressive than it is. Greedily walk the windows in
    start-date order, keeping each one only when it begins on/after the previously kept
    window's end — yielding a maximal set of independent, non-overlapping observations.
    """
    gg = g.copy()
    gg["_s"] = pd.to_datetime(gg.get("StartTradingDay"), errors="coerce")
    gg["_e"] = pd.to_datetime(gg.get("EndTradingDay"), errors="coerce")
    gg = gg.dropna(subset=["_s", "_e"]).sort_values("_s")
    keep_idx: List = []
    last_end: Optional[pd.Timestamp] = None
    for idx, row in gg.iterrows():
        if last_end is None or row["_s"] >= last_end:
            keep_idx.append(idx)
            last_end = row["_e"]
    return gg.loc[keep_idx]


def _nonoverlap_pool(group: pd.DataFrame) -> pd.DataFrame:
    """Non-overlapping subset, computed PER TICKER then pooled — different tickers' windows
    are independent of each other, so overlap only has to be broken within a single ticker."""
    if "Ticker" in group.columns and group["Ticker"].nunique() > 1:
        parts = [_greedy_nonoverlap(g) for _, g in group.groupby("Ticker")]
        return pd.concat(parts) if parts else group.iloc[0:0]
    return _greedy_nonoverlap(group)


def _wilson_interval(successes: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score interval for a binomial proportion — the honest CI for a
    hit-rate on a SMALL sample (unlike the normal approximation it stays inside
    [0,1] and is well-behaved at n=2..3). Returns (lo, hi); (nan, nan) if n==0."""
    if n <= 0:
        return float("nan"), float("nan")
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, center - half), min(1.0, center + half)


def _metrics(group: pd.DataFrame) -> Dict[str, float]:
    err = group["RealizedPct"] - group["ForecastPct"]
    mae = float(np.nanmean(np.abs(err)))
    rmse = float(np.sqrt(np.nanmean(err**2)))
    dir_acc = float(np.nanmean(np.sign(group["RealizedPct"]) == np.sign(group["ForecastPct"])))
    corr = float(group[["RealizedPct", "ForecastPct"]].corr().iloc[0, 1]) if len(group) > 2 else float("nan")

    # Non-overlapping directional accuracy — the statistically honest hit-rate. Same sign
    # test as dir_acc, but only over independent (non-overlapping) forward windows, so a
    # short, heavily-overlapping daily log can't inflate it.
    no = _nonoverlap_pool(group)
    n_no = int(len(no))
    dir_acc_no = (float(np.nanmean(np.sign(no["RealizedPct"]) == np.sign(no["ForecastPct"])))
                  if n_no else float("nan"))

    # Wilson 95% CI on the INDEPENDENT hit-rate, so a 2/3 that is really a coin
    # flip reads as such. "Significant" = the CI excludes 0.5 (genuine directional
    # edge either way); with the current tiny n it almost never will, which is the
    # honest message until the independent sample grows.
    if n_no:
        successes_no = int(round(dir_acc_no * n_no))
        ci_lo_no, ci_hi_no = _wilson_interval(successes_no, n_no)
        dir_no_significant = float((ci_lo_no > 0.5) or (ci_hi_no < 0.5))
    else:
        ci_lo_no = ci_hi_no = float("nan")
        dir_no_significant = float("nan")

    # CI coverage (only where CI exists)
    has_ci = group["CI_Lower"].notna() & group["CI_Upper"].notna()
    if has_ci.any():
        cov = float(np.mean((group.loc[has_ci, "RealizedPct"] >= group.loc[has_ci, "CI_Lower"]) &
                            (group.loc[has_ci, "RealizedPct"] <= group.loc[has_ci, "CI_Upper"])))
    else:
        cov = float("nan")

    return {
        "N": float(len(group)),
        "MAE": mae,
        "RMSE": rmse,
        "Directional_Accuracy": dir_acc,
        "Directional_Accuracy_NO": dir_acc_no,
        "N_NonOverlap": float(n_no),
        "Dir_NO_CI_Lower": ci_lo_no,
        "Dir_NO_CI_Upper": ci_hi_no,
        "Dir_NO_Significant": dir_no_significant,
        "Corr": corr,
        "CI_Coverage": cov,
        "Avg_Forecast": float(np.nanmean(group["ForecastPct"])),
        "Avg_Realized": float(np.nanmean(group["RealizedPct"])),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", type=str, default=",".join(MAG7_DEFAULT))
    ap.add_argument("--horizon", type=int, default=21)
    ap.add_argument("--lookback_days", type=int, default=365, help="Only evaluate predictions made in last N days")
    ap.add_argument("--windows", type=str, default="30,90,180,365", help="Rolling windows (days) for summary")
    args = ap.parse_args()

    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    horizon = int(args.horizon)

    log = _load_log(LOG_PATH)
    log = log[log["Ticker"].isin(tickers)].copy()
    log = log[log["Horizon"] == horizon].copy()

    if log.empty:
        print(" No predictions found for requested tickers/horizon.")
        return

    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=int(args.lookback_days))
    log = log[log["RunDate"] >= cutoff].copy()

    # Early exit: if nothing can possibly be matured yet, just write pending list and HTML
    min_date = log["RunDate"].min()
    max_date = log["RunDate"].max()
    start_dl = (min_date - pd.Timedelta(days=10)).date().isoformat()
    end_dl = (pd.Timestamp.today().normalize() + pd.Timedelta(days=2)).date().isoformat()

    # Download prices for all tickers once
    px_all = _download_prices_yf(tickers, start=start_dl, end=end_dl)

    rows = []
    pending_rows = []

    for _, r in log.iterrows():
        t = r["Ticker"]
        rd = r["RunDate"]
        model = r["Model"]

        if t not in px_all.columns:
            pending_rows.append({**r.to_dict(), "Reason": "No price series"})
            continue

        px = px_all[t].dropna()
        start_dt, end_dt, realized = _realized_forward_return_from_prices(px, rd, horizon)

        if realized is None or end_dt is None:
            pending_rows.append({
                "RunDate": _iso(rd),
                "Ticker": t,
                "Model": model,
                "ForecastPct": float(r["ForecastPct"]),
                "Horizon": horizon,
                "StartTradingDay": _iso(start_dt) if start_dt is not None else None,
                "EndTradingDay": _iso(end_dt) if end_dt is not None else None,
                "Reason": "Not matured yet",
            })
            continue

        rows.append({
            "RunDate": _iso(rd),
            "Ticker": t,
            "Model": model,
            "Horizon": horizon,
            "ForecastPct": float(r["ForecastPct"]),
            "CI_Lower": float(r["CI_Lower"]) if pd.notna(r["CI_Lower"]) else np.nan,
            "CI_Upper": float(r["CI_Upper"]) if pd.notna(r["CI_Upper"]) else np.nan,
            "StartTradingDay": _iso(start_dt),
            "EndTradingDay": _iso(end_dt),
            "RealizedPct": float(realized),
            "ErrorPct": float(realized - float(r["ForecastPct"])),
            "AbsErrorPct": float(abs(realized - float(r["ForecastPct"]))),
        })

    scored = pd.DataFrame(rows)
    pending = pd.DataFrame(pending_rows)

    if not pending.empty:
        pending.to_csv(OUT_PENDING, index=False)

    if scored.empty:
        print(" No matured predictions to score yet. Wrote pending file.")
        # still write a simple HTML status block
        status_html = f"""
        <div class='section-title'><h2>Model Leaderboard</h2></div>
        <p><strong>Status:</strong> No matured predictions yet for horizon={horizon}.</p>
        <p>Pending predictions: {len(pending):,}</p>
        """
        OUT_HTML.write_text(status_html, encoding="utf-8")
        return

    # Overall metrics by model
    by_model = scored.groupby("Model", as_index=False).apply(lambda g: pd.Series(_metrics(g))).reset_index(drop=True)
    by_model = by_model.sort_values(["MAE", "RMSE"], ascending=True)

    # By ticker+model
    by_ticker = (
        scored.groupby(["Ticker", "Model"], as_index=False)
        .apply(lambda g: pd.Series(_metrics(g)))
        .reset_index(drop=True)
        .sort_values(["Ticker", "MAE"], ascending=[True, True])
    )

    by_model.to_csv(OUT_SUMMARY, index=False)
    by_ticker.to_csv(OUT_BY_TICKER, index=False)

    # Rolling windows (days)
    win_days = [int(x) for x in args.windows.split(",") if x.strip().isdigit()]
    scored["RunDate_dt"] = pd.to_datetime(scored["RunDate"])
    roll_blocks = []
    today = pd.Timestamp.today().normalize()
    for w in win_days:
        wcut = today - pd.Timedelta(days=w)
        sub = scored[scored["RunDate_dt"] >= wcut].copy()
        if sub.empty:
            continue
        bm = sub.groupby("Model", as_index=False).apply(lambda g: pd.Series(_metrics(g))).reset_index(drop=True)
        bm["WindowDays"] = w
        roll_blocks.append(bm)

    roll = pd.concat(roll_blocks, ignore_index=True) if roll_blocks else pd.DataFrame()

    # HTML snippet for report embedding
    def _df_to_html(df: pd.DataFrame, title: str) -> str:
        if df is None or df.empty:
            return f"<h3>{title}</h3><p>No data.</p>"
        return f"<h3>{title}</h3>" + df.to_html(index=False, float_format=lambda x: f"{x:.4f}")

    html = "<div class='section-title'><h2>Model Leaderboard</h2></div>"
    html += f"<p>Horizon: {horizon} trading days. Matured rows: {len(scored):,}. Pending: {len(pending):,}.</p>"
    html += _df_to_html(by_model, "Overall (all tickers)")
    # show top 3 per ticker (most useful)
    top3 = by_ticker.sort_values(["Ticker", "MAE"]).groupby("Ticker").head(3).reset_index(drop=True)
    html += _df_to_html(top3, "Top 3 Models per Ticker (by MAE)")
    if not roll.empty:
        # best model per window (overall)
        best_roll = roll.sort_values(["WindowDays", "MAE"]).groupby("WindowDays").head(6)
        html += _df_to_html(best_roll.reset_index(drop=True), "Rolling Window Summary (best models)")
    OUT_HTML.write_text(html, encoding="utf-8")

    print(f" Leaderboard saved: {OUT_SUMMARY}, {OUT_BY_TICKER}, {OUT_HTML}")
    if not pending.empty:
        print(f" Pending saved: {OUT_PENDING}")


if __name__ == "__main__":
    main()