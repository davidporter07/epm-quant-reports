"""Score matured growth24 DL shadow paper plans against realized 21D outcomes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from deep_learning_model import TARGET_COL, _ensure_panel_schema, read_panel
from dl_rank_head_shadow_forecast import HORIZON


DEFAULT_PANEL = Path("data/experiment/dl_research_panels/research_growth_24_price_panel.parquet")
DEFAULT_OUT_DIR = Path("data/experiment/growth24_shadow_paper")
DEFAULT_PLAN_LOG = DEFAULT_OUT_DIR / "growth24_paper_plan_log.csv"
DEFAULT_FORECAST_LOG = DEFAULT_OUT_DIR / "growth24_shadow_forecast_log.parquet"
DEFAULT_TRADE_OUTPUT = DEFAULT_OUT_DIR / "growth24_paper_outcome_trades.csv"
DEFAULT_SUMMARY_OUTPUT = DEFAULT_OUT_DIR / "growth24_paper_outcome_summary.json"


def _split_tickers(value: object) -> list[str]:
    if pd.isna(value):
        return []
    return [part.strip().upper() for part in str(value).split(",") if part.strip()]


def _exit_date(group: pd.DataFrame, asof_date: pd.Timestamp) -> pd.Timestamp | None:
    dates = pd.to_datetime(group["Date"]).sort_values().reset_index(drop=True)
    matches = dates[dates == asof_date]
    if matches.empty:
        return None
    pos = int(matches.index[0]) + HORIZON
    if pos >= len(dates):
        return None
    return pd.Timestamp(dates.iloc[pos])


def _forecast_lookup(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    rows = pd.read_parquet(path)
    if rows.empty:
        return rows
    rows = rows.copy()
    rows["AsOfDate"] = pd.to_datetime(rows["AsOfDate"]).dt.date.astype(str)
    rows["Ticker"] = rows["Ticker"].astype(str).str.upper()
    return rows


def _build_trade_rows(plan_log: pd.DataFrame, panel: pd.DataFrame, forecasts: pd.DataFrame) -> pd.DataFrame:
    panel = panel.copy()
    panel["Date"] = pd.to_datetime(panel["Date"])
    panel["Ticker"] = panel["Ticker"].astype(str).str.upper()
    by_ticker = {ticker: group.sort_values("Date") for ticker, group in panel.groupby("Ticker")}

    rows: list[dict[str, Any]] = []
    selected_plans = plan_log[plan_log["Status"].astype(str).str.lower().eq("selected")].copy()
    for _, plan in selected_plans.iterrows():
        asof = pd.Timestamp(plan["AsOfDate"])
        asof_key = asof.date().isoformat()
        tickers = _split_tickers(plan.get("LongTickers"))
        for ticker in tickers:
            group = by_ticker.get(ticker)
            if group is None:
                outcome = None
                entry = None
                exit_dt = None
                market = None
            else:
                matched = group[group["Date"].eq(asof)]
                if matched.empty:
                    outcome = None
                    entry = None
                    market = None
                else:
                    row = matched.iloc[0]
                    outcome = pd.to_numeric(pd.Series([row.get("Raw_Target_Forward_21D")]), errors="coerce").iloc[0]
                    market = pd.to_numeric(pd.Series([row.get("Market_Forward_21D")]), errors="coerce").iloc[0]
                    entry = pd.to_numeric(pd.Series([row.get("Close")]), errors="coerce").iloc[0]
                exit_dt = _exit_date(group, asof)

            forecast_row = forecasts[
                forecasts.get("AsOfDate", pd.Series(dtype=str)).astype(str).eq(asof_key)
                & forecasts.get("Ticker", pd.Series(dtype=str)).astype(str).str.upper().eq(ticker)
            ]
            if forecast_row.empty:
                rank = np.nan
                rank_score = np.nan
                raw_forecast = np.nan
            else:
                first = forecast_row.iloc[-1]
                rank = first.get("Rank", np.nan)
                rank_score = first.get("ShadowRankScore", np.nan)
                raw_forecast = first.get("RawForecastPct", np.nan)

            matured = pd.notna(outcome)
            market_value = float(market) if pd.notna(market) else np.nan
            realized = float(outcome) if matured else np.nan
            rows.append(
                {
                    "RunDate": plan.get("RunDate"),
                    "AsOfDate": asof_key,
                    "ExitDate": exit_dt.date().isoformat() if exit_dt is not None else "",
                    "Status": "matured" if matured else "pending",
                    "Model": plan.get("Model"),
                    "Ticker": ticker,
                    "Rank": rank,
                    "ShadowRankScore": rank_score,
                    "RawForecastPct": raw_forecast,
                    "EntryClose": float(entry) if pd.notna(entry) else np.nan,
                    "RealizedForward21D": realized,
                    "MarketForward21D": market_value,
                    "RealizedExcess21D": realized - market_value if matured and pd.notna(market) else np.nan,
                    "Hit": bool(realized > 0.0) if matured else np.nan,
                    "ExcessHit": bool(realized - market_value > 0.0) if matured and pd.notna(market) else np.nan,
                    "PlanLongTickers": plan.get("LongTickers"),
                    "PlanCandidateTickers": plan.get("CandidateTickers"),
                    "SourceResults": plan.get("SourceResults"),
                }
            )
    return pd.DataFrame(rows)


def _summary(trades: pd.DataFrame) -> dict[str, Any]:
    matured = trades[trades["Status"].eq("matured")].copy()
    pending = trades[trades["Status"].eq("pending")].copy()
    plan_summary = []
    if not matured.empty:
        for asof, group in matured.groupby("AsOfDate"):
            plan_summary.append(
                {
                    "AsOfDate": asof,
                    "Tickers": ",".join(group["Ticker"].astype(str).tolist()),
                    "MeanForward21D": float(group["RealizedForward21D"].mean()),
                    "MeanExcess21D": float(group["RealizedExcess21D"].mean()),
                    "HitRate": float(group["Hit"].mean()),
                    "ExcessHitRate": float(group["ExcessHit"].mean()),
                }
            )
    return {
        "trade_rows": int(len(trades)),
        "matured_trades": int(len(matured)),
        "pending_trades": int(len(pending)),
        "matured_plans": int(matured["AsOfDate"].nunique()) if not matured.empty else 0,
        "pending_plans": int(pending["AsOfDate"].nunique()) if not pending.empty else 0,
        "mean_forward_21d": float(matured["RealizedForward21D"].mean()) if not matured.empty else None,
        "mean_excess_21d": float(matured["RealizedExcess21D"].mean()) if not matured.empty else None,
        "hit_rate": float(matured["Hit"].mean()) if not matured.empty else None,
        "excess_hit_rate": float(matured["ExcessHit"].mean()) if not matured.empty else None,
        "plans": plan_summary,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def main() -> None:
    ap = argparse.ArgumentParser(description="Score growth24 DL paper outcomes.")
    ap.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    ap.add_argument("--paper-plan-log", type=Path, default=DEFAULT_PLAN_LOG)
    ap.add_argument("--forecast-log", type=Path, default=DEFAULT_FORECAST_LOG)
    ap.add_argument("--trade-output", type=Path, default=DEFAULT_TRADE_OUTPUT)
    ap.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    args = ap.parse_args()

    if not args.paper_plan_log.exists():
        raise FileNotFoundError(f"Missing paper plan log: {args.paper_plan_log}")
    plan_log = pd.read_csv(args.paper_plan_log)
    panel = _ensure_panel_schema(read_panel(args.panel))
    forecasts = _forecast_lookup(args.forecast_log)

    trades = _build_trade_rows(plan_log, panel, forecasts)
    summary = _summary(trades)

    args.trade_output.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(args.trade_output, index=False)
    _write_json(args.summary_output, summary)

    print("Status: scored")
    print(f"Trade rows: {summary['trade_rows']}")
    print(f"Matured trades: {summary['matured_trades']}")
    print(f"Pending trades: {summary['pending_trades']}")
    print(f"Mean forward 21D: {summary['mean_forward_21d']}")
    print(f"Mean excess 21D: {summary['mean_excess_21d']}")
    print(f"Saved trades -> {args.trade_output}")
    print(f"Saved summary -> {args.summary_output}")


if __name__ == "__main__":
    main()
