"""Check and score Growth24 DL shadow-paper plan maturity.

This is the local reminder/automation hook for the Growth24 paper lane. It can
refresh the price cache/panel, rerun the paper outcome scorer, and write a
compact maturity status file that makes due/overdue plans explicit.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
from pandas.tseries.offsets import CustomBusinessDay

from build_quantcup_price_dl_panel import build_panel
from deep_learning_model import _ensure_panel_schema, read_panel
from dl_growth24_paper_outcome import (
    DEFAULT_FORECAST_LOG,
    DEFAULT_PANEL,
    DEFAULT_PLAN_LOG,
    DEFAULT_SUMMARY_OUTPUT,
    DEFAULT_TRADE_OUTPUT,
    _build_trade_rows,
    _forecast_lookup,
    _summary,
    _write_json,
)
from dl_rank_head_shadow_forecast import HORIZON
from refresh_growth24_price_cache import _download_ohlcv, _load_tickers, _merge_cache, FIELD_TO_CACHE
from quant_cup.earnings_av import download_earnings


DEFAULT_STATUS_OUTPUT = Path("data/experiment/growth24_shadow_paper/growth24_paper_maturity_status.json")
DEFAULT_ALERT_OUTPUT = Path("data/experiment/growth24_shadow_paper/growth24_paper_maturity_alert.txt")
DEFAULT_TICKER_CONFIG = Path("config/research_growth_universe.json")


def _parse_today(raw: str | None) -> date:
    if raw:
        return pd.Timestamp(raw).date()
    return date.today()


def _business_due_date(asof: pd.Timestamp, horizon: int) -> date:
    us_bday = CustomBusinessDay(calendar=USFederalHolidayCalendar())
    return (pd.Timestamp(asof).normalize() + (int(horizon) * us_bday)).date()


def _panel_exit_dates(panel: pd.DataFrame) -> dict[tuple[str, str], date]:
    out: dict[tuple[str, str], date] = {}
    if panel.empty:
        return out
    rows = panel[["Date", "Ticker"]].copy()
    rows["Date"] = pd.to_datetime(rows["Date"])
    rows["Ticker"] = rows["Ticker"].astype(str).str.upper()
    for ticker, group in rows.groupby("Ticker"):
        dates = group.sort_values("Date")["Date"].reset_index(drop=True)
        for pos, asof in enumerate(dates):
            exit_pos = pos + HORIZON
            if exit_pos < len(dates):
                out[(ticker, asof.date().isoformat())] = pd.Timestamp(dates.iloc[exit_pos]).date()
    return out


def _selected_plan_rows(plan_log: pd.DataFrame) -> pd.DataFrame:
    if plan_log.empty or "Status" not in plan_log.columns:
        return plan_log.iloc[0:0].copy()
    selected = plan_log[plan_log["Status"].astype(str).str.lower().eq("selected")].copy()
    if selected.empty:
        return selected
    selected["AsOfDate"] = pd.to_datetime(selected["AsOfDate"]).dt.date.astype(str)
    return selected.sort_values(["AsOfDate", "RunDate"])


def _split_tickers(value: object) -> list[str]:
    if pd.isna(value):
        return []
    return [part.strip().upper() for part in str(value).split(",") if part.strip()]


def _refresh_price_cache(ticker_config: Path, start: date, end: date) -> None:
    tickers = _load_tickers(ticker_config)
    downloaded = _download_ohlcv(tickers, start.isoformat(), end.isoformat())
    print(f"Downloaded {len(tickers)} tickers for {start.isoformat()} -> {end.isoformat()}")
    for field, cache_file in FIELD_TO_CACHE.items():
        values, min_date, max_date = _merge_cache(cache_file, downloaded[field], tickers)
        print(f"Patched {field:<6} values={values:,} cache_range={min_date.date()} -> {max_date.date()}")


def _load_env_key(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    env_path = Path(".env")
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        if key.strip() == name:
            return raw.strip().strip('"').strip("'")
    return ""


def _refresh_earnings_cache(ticker_config: Path, force_refresh: bool) -> None:
    tickers = _load_tickers(ticker_config)
    api_key = _load_env_key("AV_API_KEY")
    if not api_key:
        raise RuntimeError("AV_API_KEY is required to refresh Growth24 AV earnings cache.")
    print(f"Refreshing AV earnings cache for {len(tickers)} Growth24 tickers.")
    download_earnings(tickers, api_key, force_refresh=bool(force_refresh))


def _refresh_panel(ticker_config: Path, panel_output: Path, end: date) -> None:
    tickers = _load_tickers(ticker_config)
    panel = build_panel(
        tickers=tickers,
        start="2006-01-03",
        end=end.isoformat(),
        include_earnings=True,
        earnings_source="av",
        target_mode="raw",
    )
    panel_output.parent.mkdir(parents=True, exist_ok=True)
    panel.to_parquet(panel_output, index=False)
    labeled = panel[pd.to_numeric(panel["Raw_Target_Forward_21D"], errors="coerce").notna()]
    print(f"Saved {len(panel):,} rows -> {panel_output}")
    print(f"Panel range: {panel['Date'].min().date()} -> {panel['Date'].max().date()}")
    print(f"Labeled range: {labeled['Date'].min().date()} -> {labeled['Date'].max().date()}")


def _score(
    panel_path: Path,
    plan_log_path: Path,
    forecast_log_path: Path,
    trade_output: Path,
    summary_output: Path,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    if not plan_log_path.exists():
        raise FileNotFoundError(f"Missing paper plan log: {plan_log_path}")
    plan_log = pd.read_csv(plan_log_path)
    panel = _ensure_panel_schema(read_panel(panel_path))
    forecasts = _forecast_lookup(forecast_log_path)
    trades = _build_trade_rows(plan_log, panel, forecasts)
    summary = _summary(trades)
    trade_output.parent.mkdir(parents=True, exist_ok=True)
    trades.to_csv(trade_output, index=False)
    _write_json(summary_output, summary)
    return trades, summary, panel


def _plan_status(
    plan_log: pd.DataFrame,
    trades: pd.DataFrame,
    panel: pd.DataFrame,
    today: date,
) -> dict[str, Any]:
    selected = _selected_plan_rows(plan_log)
    exit_dates = _panel_exit_dates(panel)
    trade_status: dict[tuple[str, str], str] = {}
    if not trades.empty:
        for _, row in trades.iterrows():
            trade_status[(str(row.get("Ticker", "")).upper(), str(row.get("AsOfDate", "")))] = str(row.get("Status", ""))

    plan_rows: list[dict[str, Any]] = []
    due_today = 0
    overdue_pending = 0
    pending_dates: list[date] = []
    for _, plan in selected.iterrows():
        asof_key = str(plan.get("AsOfDate", ""))
        asof = pd.Timestamp(asof_key)
        tickers = _split_tickers(plan.get("LongTickers"))
        est_due = _business_due_date(asof, HORIZON)
        known_exit_dates = [
            exit_dates[(ticker, asof_key)]
            for ticker in tickers
            if (ticker, asof_key) in exit_dates
        ]
        panel_exit = max(known_exit_dates).isoformat() if known_exit_dates else ""
        statuses = [trade_status.get((ticker, asof_key), "pending") for ticker in tickers]
        matured = bool(statuses) and all(status == "matured" for status in statuses)
        if matured:
            status = "matured"
        elif today == est_due:
            status = "due_today"
            due_today += 1
        elif today > est_due:
            status = "overdue_pending"
            overdue_pending += 1
        else:
            status = "pending"
        if not matured and today <= est_due:
            pending_dates.append(est_due)
        plan_rows.append(
            {
                "RunDate": str(plan.get("RunDate", "")),
                "AsOfDate": asof_key,
                "Model": str(plan.get("Model", "")),
                "LongTickers": ",".join(tickers),
                "Status": status,
                "EstimatedDueDate": est_due.isoformat(),
                "PanelExitDate": panel_exit,
                "DaysUntilDue": int((est_due - today).days),
            }
        )

    next_due = min(pending_dates).isoformat() if pending_dates else None
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "today": today.isoformat(),
        "horizon_trading_days": HORIZON,
        "selected_plan_count": int(len(selected)),
        "due_today_count": int(due_today),
        "overdue_pending_count": int(overdue_pending),
        "next_due_date": next_due,
        "plans": plan_rows,
    }


def _write_alert(path: Path, status: dict[str, Any], summary: dict[str, Any]) -> None:
    lines = [
        "Growth24 paper maturity check",
        f"Generated: {status['generated_at']}",
        f"Today: {status['today']}",
        f"Trade rows: {summary.get('trade_rows')}",
        f"Matured trades: {summary.get('matured_trades')}",
        f"Pending trades: {summary.get('pending_trades')}",
        f"Due today: {status['due_today_count']}",
        f"Overdue pending: {status['overdue_pending_count']}",
        f"Next due date: {status.get('next_due_date')}",
        "",
    ]
    for plan in status["plans"]:
        if plan["Status"] in {"due_today", "overdue_pending", "pending"}:
            lines.append(
                f"{plan['Status']}: AsOf {plan['AsOfDate']} "
                f"({plan['LongTickers']}) due {plan['EstimatedDueDate']}"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Check Growth24 paper-trade maturity and score available outcomes.")
    ap.add_argument("--panel", type=Path, default=DEFAULT_PANEL)
    ap.add_argument("--paper-plan-log", type=Path, default=DEFAULT_PLAN_LOG)
    ap.add_argument("--forecast-log", type=Path, default=DEFAULT_FORECAST_LOG)
    ap.add_argument("--trade-output", type=Path, default=DEFAULT_TRADE_OUTPUT)
    ap.add_argument("--summary-output", type=Path, default=DEFAULT_SUMMARY_OUTPUT)
    ap.add_argument("--status-output", type=Path, default=DEFAULT_STATUS_OUTPUT)
    ap.add_argument("--alert-output", type=Path, default=DEFAULT_ALERT_OUTPUT)
    ap.add_argument("--ticker-config", type=Path, default=DEFAULT_TICKER_CONFIG)
    ap.add_argument("--refresh-data", action="store_true", help="Refresh yfinance cache and rebuild the AV earnings panel first.")
    ap.add_argument("--refresh-earnings", action="store_true", help="Refresh stale/missing Growth24 Alpha Vantage earnings cache before panel rebuild.")
    ap.add_argument("--force-refresh-earnings", action="store_true", help="Force-download Growth24 earnings even when cache files are still fresh.")
    ap.add_argument("--refresh-start", default=None, help="Override price refresh start date.")
    ap.add_argument("--today", default=None, help="Override today's date for checks/tests.")
    ap.add_argument("--strict", action="store_true", help="Exit non-zero when a plan is due/overdue and still pending.")
    args = ap.parse_args()

    today = _parse_today(args.today)
    if args.refresh_earnings:
        _refresh_earnings_cache(args.ticker_config, bool(args.force_refresh_earnings))
    if args.refresh_data:
        refresh_start = pd.Timestamp(args.refresh_start).date() if args.refresh_start else today
        _refresh_price_cache(args.ticker_config, refresh_start, today)
        _refresh_panel(args.ticker_config, args.panel, today)

    plan_log = pd.read_csv(args.paper_plan_log)
    trades, summary, panel = _score(
        args.panel,
        args.paper_plan_log,
        args.forecast_log,
        args.trade_output,
        args.summary_output,
    )
    status = _plan_status(plan_log, trades, panel, today)
    _write_json(args.status_output, {"maturity": status, "outcome_summary": summary})
    _write_alert(args.alert_output, status, summary)

    print("Status: checked")
    print(f"Today: {status['today']}")
    print(f"Selected plans: {status['selected_plan_count']}")
    print(f"Due today: {status['due_today_count']}")
    print(f"Overdue pending: {status['overdue_pending_count']}")
    print(f"Next due date: {status.get('next_due_date')}")
    print(f"Matured trades: {summary.get('matured_trades')}")
    print(f"Pending trades: {summary.get('pending_trades')}")
    print(f"Saved status -> {args.status_output}")
    print(f"Saved alert -> {args.alert_output}")
    if args.strict and (status["due_today_count"] or status["overdue_pending_count"]):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
