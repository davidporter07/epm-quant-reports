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

from build_directional_feature_panel import EARNINGS_TICKER_ALIASES
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
from dl_growth24_current_control_gate import (
    DEFAULT_FORECAST as DEFAULT_CONTROL_GATE_FORECAST,
    DEFAULT_MARKDOWN_OUTPUT as DEFAULT_CONTROL_GATE_MARKDOWN_OUTPUT,
    DEFAULT_OUTPUT as DEFAULT_CONTROL_GATE_OUTPUT,
    DEFAULT_PAPER_PLAN as DEFAULT_CONTROL_GATE_PAPER_PLAN,
    DEFAULT_PANEL_DIAGNOSTICS as DEFAULT_CONTROL_GATE_PANEL_DIAGNOSTICS,
    DEFAULT_PLAN_OVERLAY_OUTPUT as DEFAULT_CONTROL_GATE_PLAN_OVERLAY_OUTPUT,
    DEFAULT_SUMMARY as DEFAULT_CONTROL_GATE_SUMMARY,
    DEFAULT_UNIVERSE_SCORE_STD_MAX,
    _json_safe as _control_gate_json_safe,
    _markdown as _control_gate_markdown,
    build_gate as build_control_gate,
    write_plan_overlay as write_control_gate_plan_overlay,
)
from dl_rank_head_shadow_forecast import HORIZON
from refresh_growth24_price_cache import _download_ohlcv, _load_tickers, _merge_cache, FIELD_TO_CACHE
from quant_cup.earnings_av import download_earnings


DEFAULT_STATUS_OUTPUT = Path("data/experiment/growth24_shadow_paper/growth24_paper_maturity_status.json")
DEFAULT_ALERT_OUTPUT = Path("data/experiment/growth24_shadow_paper/growth24_paper_maturity_alert.txt")
DEFAULT_CONTROL_OVERLAY_OUTCOME_LEDGER = Path(
    "data/experiment/growth24_shadow_paper/growth24_control_overlay_outcome_ledger.csv"
)
DEFAULT_CONTROL_OVERLAY_OUTCOME_SUMMARY = Path(
    "data/experiment/growth24_shadow_paper/growth24_control_overlay_outcome_summary.json"
)
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


def _clean_str(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value)


def _numeric(value: object) -> float | None:
    out = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(out) if pd.notna(out) else None


def _mean_or_none(rows: pd.DataFrame, column: str) -> float | None:
    if rows.empty or column not in rows.columns:
        return None
    values = pd.to_numeric(rows[column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def _rate_or_none(rows: pd.DataFrame, column: str) -> float | None:
    if rows.empty or column not in rows.columns:
        return None
    values = rows[column].dropna()
    return float(values.astype(bool).mean()) if not values.empty else None


def _normalize_forecast_log(forecasts: pd.DataFrame) -> pd.DataFrame:
    if forecasts.empty:
        return forecasts.copy()
    rows = forecasts.copy()
    for column in ["RunDate", "Model", "SourceResults", "Rank", "ShadowRankScore", "Ticker"]:
        if column not in rows.columns:
            rows[column] = ""
    rows["AsOfDate"] = pd.to_datetime(rows["AsOfDate"], errors="coerce").dt.date.astype(str)
    rows["RunDate"] = rows["RunDate"].astype(str)
    rows["Model"] = rows["Model"].astype(str)
    rows["SourceResults"] = rows["SourceResults"].astype(str)
    rows["Rank"] = pd.to_numeric(rows["Rank"], errors="coerce")
    rows["ShadowRankScore"] = pd.to_numeric(rows["ShadowRankScore"], errors="coerce")
    rows["Ticker"] = rows["Ticker"].astype(str).str.upper().str.strip()
    return rows


def _plan_forecast_rows(forecasts: pd.DataFrame, plan: pd.Series) -> pd.DataFrame:
    if forecasts.empty:
        return forecasts.copy()
    asof_key = pd.Timestamp(plan.get("AsOfDate")).date().isoformat()
    model = _clean_str(plan.get("Model"))
    source = _clean_str(plan.get("SourceResults"))
    run_date = _clean_str(plan.get("RunDate"))

    rows = forecasts[
        forecasts["AsOfDate"].astype(str).eq(asof_key)
        & forecasts["Model"].astype(str).eq(model)
        & forecasts["SourceResults"].astype(str).eq(source)
    ].copy()
    if rows.empty:
        rows = forecasts[
            forecasts["AsOfDate"].astype(str).eq(asof_key)
            & forecasts["Model"].astype(str).eq(model)
            & forecasts["RunDate"].astype(str).eq(run_date)
        ].copy()
    if rows.empty:
        rows = forecasts[
            forecasts["AsOfDate"].astype(str).eq(asof_key)
            & forecasts["Model"].astype(str).eq(model)
        ].copy()
    return rows


def _plan_trade_rows(trades: pd.DataFrame, plan: pd.Series) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    asof_key = pd.Timestamp(plan.get("AsOfDate")).date().isoformat()
    model = _clean_str(plan.get("Model"))
    source = _clean_str(plan.get("SourceResults"))
    run_date = _clean_str(plan.get("RunDate"))
    rows = trades[
        trades["AsOfDate"].astype(str).eq(asof_key)
        & trades["Model"].astype(str).eq(model)
        & trades["SourceResults"].astype(str).eq(source)
        & trades["RunDate"].astype(str).eq(run_date)
    ].copy()
    if rows.empty:
        rows = trades[
            trades["AsOfDate"].astype(str).eq(asof_key)
            & trades["Model"].astype(str).eq(model)
            & trades["RunDate"].astype(str).eq(run_date)
        ].copy()
    return rows


def _control_overlay_decision(
    plan: pd.Series,
    forecasts: pd.DataFrame,
    max_universe_score_std: float,
    expected_universe_count: int,
) -> dict[str, Any]:
    plan_longs = _split_tickers(plan.get("LongTickers"))
    top_n = int(_numeric(plan.get("PaperTopN")) or len(plan_longs) or 2)
    if forecasts.empty:
        return {
            "gate_status": "paper_control_unavailable",
            "overlay_status": "paper_overlay_unavailable",
            "universe_count": 0,
            "universe_score_std": None,
            "gate_long_tickers": [],
            "gate_failures": ["forecast rows unavailable"],
        }

    scores = pd.to_numeric(forecasts["ShadowRankScore"], errors="coerce").dropna()
    universe_score_std = float(scores.std(ddof=0)) if not scores.empty else None
    ordered = forecasts.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False])
    gate_longs = [str(t).upper().strip() for t in ordered.head(top_n)["Ticker"].tolist()]
    failures: list[str] = []
    if len(forecasts) < int(expected_universe_count):
        failures.append(f"universe count {len(forecasts)} < {int(expected_universe_count)}")
    if universe_score_std is None:
        failures.append("universe score std missing")
    elif universe_score_std > float(max_universe_score_std):
        failures.append(f"universe score std {universe_score_std:.6f} > {float(max_universe_score_std):.6f}")

    gate_status = "paper_control_abstain" if failures else "paper_control_allowed"
    overlay_status = "paper_overlay_abstain" if failures else "paper_overlay_allowed"
    return {
        "gate_status": gate_status,
        "overlay_status": overlay_status,
        "universe_count": int(len(forecasts)),
        "universe_score_std": universe_score_std,
        "gate_long_tickers": gate_longs,
        "gate_failures": failures,
    }


def _base_plan_outcome(trade_rows: pd.DataFrame) -> dict[str, Any]:
    if trade_rows.empty:
        return {
            "base_outcome_status": "unavailable",
            "base_ticker_count": 0,
            "base_mean_forward_21d": None,
            "base_mean_excess_21d": None,
            "base_hit_rate": None,
            "base_excess_hit_rate": None,
        }
    statuses = trade_rows["Status"].astype(str).str.lower()
    matured = bool(len(statuses)) and statuses.eq("matured").all()
    return {
        "base_outcome_status": "matured" if matured else "pending",
        "base_ticker_count": int(len(trade_rows)),
        "base_mean_forward_21d": _mean_or_none(trade_rows, "RealizedForward21D") if matured else None,
        "base_mean_excess_21d": _mean_or_none(trade_rows, "RealizedExcess21D") if matured else None,
        "base_hit_rate": _rate_or_none(trade_rows, "Hit") if matured else None,
        "base_excess_hit_rate": _rate_or_none(trade_rows, "ExcessHit") if matured else None,
    }


def _overlay_outcome_status(overlay_status: str, base_status: str) -> str:
    if overlay_status == "paper_overlay_allowed":
        return base_status
    if overlay_status == "paper_overlay_abstain":
        return "abstained_matured" if base_status == "matured" else "abstained_pending"
    return "unavailable"


def _abstention_classification(overlay_trade_status: str, base_mean_forward: float | None) -> str:
    if overlay_trade_status != "abstained_matured" or base_mean_forward is None:
        return ""
    if base_mean_forward < 0.0:
        return "avoided_loss"
    if base_mean_forward > 0.0:
        return "skipped_gain"
    return "neutral_skip"


def _build_control_overlay_outcomes(
    plan_log: pd.DataFrame,
    forecasts: pd.DataFrame,
    trades: pd.DataFrame,
    max_universe_score_std: float,
    expected_universe_count: int,
) -> pd.DataFrame:
    selected = _selected_plan_rows(plan_log)
    forecast_rows = _normalize_forecast_log(forecasts)
    rows: list[dict[str, Any]] = []
    for _, plan in selected.iterrows():
        asof_key = pd.Timestamp(plan.get("AsOfDate")).date().isoformat()
        plan_longs = _split_tickers(plan.get("LongTickers"))
        decision = _control_overlay_decision(
            plan,
            _plan_forecast_rows(forecast_rows, plan),
            max_universe_score_std,
            expected_universe_count,
        )
        base = _base_plan_outcome(_plan_trade_rows(trades, plan))
        overlay_trade_status = _overlay_outcome_status(decision["overlay_status"], base["base_outcome_status"])
        overlay_longs = plan_longs if decision["overlay_status"] == "paper_overlay_allowed" else []
        rows.append(
            {
                "RunDate": _clean_str(plan.get("RunDate")),
                "AsOfDate": asof_key,
                "EstimatedDueDate": _business_due_date(pd.Timestamp(asof_key), HORIZON).isoformat(),
                "Model": _clean_str(plan.get("Model")),
                "PlanStatus": _clean_str(plan.get("Status")),
                "PlanLongTickers": ",".join(plan_longs),
                "BaseOutcomeStatus": base["base_outcome_status"],
                "BaseTickerCount": base["base_ticker_count"],
                "BaseMeanForward21D": base["base_mean_forward_21d"],
                "BaseMeanExcess21D": base["base_mean_excess_21d"],
                "BaseHitRate": base["base_hit_rate"],
                "BaseExcessHitRate": base["base_excess_hit_rate"],
                "GateStatus": decision["gate_status"],
                "OverlayStatus": decision["overlay_status"],
                "OverlayTradeStatus": overlay_trade_status,
                "OverlayTraded": bool(overlay_trade_status in {"matured", "pending"}),
                "OverlayLongTickers": ",".join(overlay_longs),
                "UniverseCount": decision["universe_count"],
                "ExpectedUniverseCount": int(expected_universe_count),
                "UniverseScoreStd": decision["universe_score_std"],
                "MaxUniverseScoreStd": float(max_universe_score_std),
                "GateLongTickers": ",".join(decision["gate_long_tickers"]),
                "GateFailures": "; ".join(decision["gate_failures"]),
                "AbstentionClassification": _abstention_classification(
                    overlay_trade_status,
                    base["base_mean_forward_21d"],
                ),
                "SourceResults": _clean_str(plan.get("SourceResults")),
            }
        )
    return pd.DataFrame(rows)


def _summarize_control_overlay_outcomes(ledger: pd.DataFrame) -> dict[str, Any]:
    if ledger.empty:
        return {
            "ledger_rows": 0,
            "base_matured_plans": 0,
            "base_pending_plans": 0,
            "overlay_allowed_plans": 0,
            "overlay_abstained_plans": 0,
            "overlay_matured_plans": 0,
            "overlay_pending_plans": 0,
            "abstained_matured_plans": 0,
            "avoided_loss_plans": 0,
            "skipped_gain_plans": 0,
        }

    base_matured = ledger[ledger["BaseOutcomeStatus"].eq("matured")].copy()
    overlay_matured = ledger[ledger["OverlayTradeStatus"].eq("matured")].copy()
    abstained_matured = ledger[ledger["OverlayTradeStatus"].eq("abstained_matured")].copy()
    return {
        "ledger_rows": int(len(ledger)),
        "base_matured_plans": int(len(base_matured)),
        "base_pending_plans": int(ledger["BaseOutcomeStatus"].eq("pending").sum()),
        "overlay_allowed_plans": int(ledger["OverlayStatus"].eq("paper_overlay_allowed").sum()),
        "overlay_abstained_plans": int(ledger["OverlayStatus"].eq("paper_overlay_abstain").sum()),
        "overlay_matured_plans": int(len(overlay_matured)),
        "overlay_pending_plans": int(ledger["OverlayTradeStatus"].eq("pending").sum()),
        "abstained_matured_plans": int(len(abstained_matured)),
        "avoided_loss_plans": int(ledger["AbstentionClassification"].eq("avoided_loss").sum()),
        "skipped_gain_plans": int(ledger["AbstentionClassification"].eq("skipped_gain").sum()),
        "base_matured_mean_forward_21d": _mean_or_none(base_matured, "BaseMeanForward21D"),
        "base_matured_mean_excess_21d": _mean_or_none(base_matured, "BaseMeanExcess21D"),
        "overlay_matured_mean_forward_21d": _mean_or_none(overlay_matured, "BaseMeanForward21D"),
        "overlay_matured_mean_excess_21d": _mean_or_none(overlay_matured, "BaseMeanExcess21D"),
        "abstained_matured_mean_forward_21d": _mean_or_none(abstained_matured, "BaseMeanForward21D"),
        "abstained_matured_mean_excess_21d": _mean_or_none(abstained_matured, "BaseMeanExcess21D"),
    }


def _write_control_overlay_outcomes(
    ledger_output: Path,
    summary_output: Path,
    ledger: pd.DataFrame,
    summary: dict[str, Any],
) -> None:
    ledger_output.parent.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(ledger_output, index=False)
    _write_json(summary_output, summary)


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
    earnings_tickers = list(dict.fromkeys(EARNINGS_TICKER_ALIASES.get(ticker, ticker) for ticker in tickers))
    api_key = _load_env_key("AV_API_KEY")
    if not api_key:
        raise RuntimeError("AV_API_KEY is required to refresh Growth24 AV earnings cache.")
    print(f"Refreshing AV earnings cache for {len(earnings_tickers)} Growth24 earnings tickers.")
    download_earnings(earnings_tickers, api_key, force_refresh=bool(force_refresh))


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


def _control_gate_status(args: argparse.Namespace) -> dict[str, Any]:
    if bool(args.skip_control_gate):
        return {
            "status": "skipped",
            "paper_only": True,
            "live_policy_changed": False,
            "reason": "disabled by --skip-control-gate",
        }
    gate_args = argparse.Namespace(
        forecast=args.control_gate_forecast,
        summary=args.control_gate_summary,
        panel_diagnostics=args.control_gate_panel_diagnostics,
        paper_plan=args.control_gate_paper_plan,
        output=args.control_gate_output,
        plan_overlay_output=args.control_gate_plan_overlay_output,
        markdown_output=args.control_gate_markdown_output,
        long_n=int(args.control_gate_long_n),
        short_n=int(args.control_gate_short_n),
        expected_universe_count=int(args.control_gate_expected_universe_count),
        max_universe_score_std=float(args.control_gate_max_universe_score_std),
        max_score_gap=args.control_gate_max_score_gap,
    )
    try:
        report = build_control_gate(gate_args)
        args.control_gate_output.parent.mkdir(parents=True, exist_ok=True)
        args.control_gate_markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.control_gate_output.write_text(
            json.dumps(_control_gate_json_safe(report), indent=2),
            encoding="utf-8",
        )
        write_control_gate_plan_overlay(args.control_gate_plan_overlay_output, report)
        args.control_gate_markdown_output.write_text(_control_gate_markdown(report), encoding="utf-8")
        return report
    except Exception as exc:
        return {
            "status": "unavailable",
            "paper_only": True,
            "live_policy_changed": False,
            "error": str(exc),
            "forecast": str(args.control_gate_forecast),
            "paper_plan": str(args.control_gate_paper_plan),
            "thresholds": {
                "expected_universe_count": int(args.control_gate_expected_universe_count),
                "long_n": int(args.control_gate_long_n),
                "short_n": int(args.control_gate_short_n),
                "max_universe_score_std": float(args.control_gate_max_universe_score_std),
                "max_score_gap": args.control_gate_max_score_gap,
            },
        }


def _write_alert(
    path: Path,
    status: dict[str, Any],
    summary: dict[str, Any],
    control_gate: dict[str, Any] | None = None,
    control_overlay_summary: dict[str, Any] | None = None,
) -> None:
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
    if control_gate:
        gate_metrics = control_gate.get("forecast_metrics", {})
        gate_failures = control_gate.get("gate_failures", [])
        overlay = control_gate.get("paper_plan_overlay", {})
        lines.extend(
            [
                f"Control gate status: {control_gate.get('status')}",
                f"Control gate paper-only: {control_gate.get('paper_only')}",
                f"Control gate live policy changed: {control_gate.get('live_policy_changed')}",
                f"Control gate paper plan changed: {control_gate.get('paper_plan_changed')}",
                f"Control gate AsOfDate: {gate_metrics.get('asof_date', '')}",
                f"Control gate selected longs: {','.join(gate_metrics.get('long_tickers', []))}",
                f"Control gate universe score std: {gate_metrics.get('universe_score_std', '')}",
                f"Control gate failures: {'; '.join(gate_failures) if gate_failures else control_gate.get('error', 'none')}",
                f"Paper overlay status: {overlay.get('status', '')}",
                f"Paper overlay action: {overlay.get('action', '')}",
                f"Paper overlay plan status: {overlay.get('plan_status', '')}",
                f"Paper overlay plan longs: {','.join(overlay.get('plan_long_tickers', []))}",
                "",
            ]
        )
    if control_overlay_summary:
        lines.extend(
            [
                f"Overlay ledger rows: {control_overlay_summary.get('ledger_rows')}",
                f"Overlay allowed plans: {control_overlay_summary.get('overlay_allowed_plans')}",
                f"Overlay abstained plans: {control_overlay_summary.get('overlay_abstained_plans')}",
                f"Overlay matured plans: {control_overlay_summary.get('overlay_matured_plans')}",
                f"Abstained matured plans: {control_overlay_summary.get('abstained_matured_plans')}",
                f"Avoided-loss plans: {control_overlay_summary.get('avoided_loss_plans')}",
                f"Skipped-gain plans: {control_overlay_summary.get('skipped_gain_plans')}",
                f"Base matured mean forward 21D: {control_overlay_summary.get('base_matured_mean_forward_21d')}",
                f"Overlay matured mean forward 21D: {control_overlay_summary.get('overlay_matured_mean_forward_21d')}",
                f"Abstained matured mean forward 21D: {control_overlay_summary.get('abstained_matured_mean_forward_21d')}",
                "",
            ]
        )
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
    ap.add_argument("--control-overlay-ledger-output", type=Path, default=DEFAULT_CONTROL_OVERLAY_OUTCOME_LEDGER)
    ap.add_argument("--control-overlay-summary-output", type=Path, default=DEFAULT_CONTROL_OVERLAY_OUTCOME_SUMMARY)
    ap.add_argument("--ticker-config", type=Path, default=DEFAULT_TICKER_CONFIG)
    ap.add_argument("--refresh-data", action="store_true", help="Refresh yfinance cache and rebuild the AV earnings panel first.")
    ap.add_argument("--refresh-earnings", action="store_true", help="Refresh stale/missing Growth24 Alpha Vantage earnings cache before panel rebuild.")
    ap.add_argument("--force-refresh-earnings", action="store_true", help="Force-download Growth24 earnings even when cache files are still fresh.")
    ap.add_argument("--refresh-start", default=None, help="Override price refresh start date.")
    ap.add_argument("--today", default=None, help="Override today's date for checks/tests.")
    ap.add_argument("--strict", action="store_true", help="Exit non-zero when a plan is due/overdue and still pending.")
    ap.add_argument("--skip-control-gate", action="store_true", help="Skip the report-only Growth24 current control gate.")
    ap.add_argument("--control-gate-forecast", type=Path, default=DEFAULT_CONTROL_GATE_FORECAST)
    ap.add_argument("--control-gate-summary", type=Path, default=DEFAULT_CONTROL_GATE_SUMMARY)
    ap.add_argument("--control-gate-panel-diagnostics", type=Path, default=DEFAULT_CONTROL_GATE_PANEL_DIAGNOSTICS)
    ap.add_argument("--control-gate-paper-plan", type=Path, default=DEFAULT_CONTROL_GATE_PAPER_PLAN)
    ap.add_argument("--control-gate-output", type=Path, default=DEFAULT_CONTROL_GATE_OUTPUT)
    ap.add_argument("--control-gate-plan-overlay-output", type=Path, default=DEFAULT_CONTROL_GATE_PLAN_OVERLAY_OUTPUT)
    ap.add_argument("--control-gate-markdown-output", type=Path, default=DEFAULT_CONTROL_GATE_MARKDOWN_OUTPUT)
    ap.add_argument("--control-gate-long-n", type=int, default=2)
    ap.add_argument("--control-gate-short-n", type=int, default=2)
    ap.add_argument("--control-gate-expected-universe-count", type=int, default=24)
    ap.add_argument("--control-gate-max-universe-score-std", type=float, default=DEFAULT_UNIVERSE_SCORE_STD_MAX)
    ap.add_argument("--control-gate-max-score-gap", type=float, default=None)
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
    control_gate = _control_gate_status(args)
    forecasts = _forecast_lookup(args.forecast_log)
    control_overlay_ledger = _build_control_overlay_outcomes(
        plan_log=plan_log,
        forecasts=forecasts,
        trades=trades,
        max_universe_score_std=float(args.control_gate_max_universe_score_std),
        expected_universe_count=int(args.control_gate_expected_universe_count),
    )
    control_overlay_summary = _summarize_control_overlay_outcomes(control_overlay_ledger)
    _write_control_overlay_outcomes(
        args.control_overlay_ledger_output,
        args.control_overlay_summary_output,
        control_overlay_ledger,
        control_overlay_summary,
    )
    _write_json(
        args.status_output,
        {
            "maturity": status,
            "outcome_summary": summary,
            "control_gate": control_gate,
            "control_overlay_outcomes": control_overlay_summary,
        },
    )
    _write_alert(args.alert_output, status, summary, control_gate, control_overlay_summary)

    print("Status: checked")
    print(f"Today: {status['today']}")
    print(f"Selected plans: {status['selected_plan_count']}")
    print(f"Due today: {status['due_today_count']}")
    print(f"Overdue pending: {status['overdue_pending_count']}")
    print(f"Next due date: {status.get('next_due_date')}")
    print(f"Matured trades: {summary.get('matured_trades')}")
    print(f"Pending trades: {summary.get('pending_trades')}")
    print(f"Control gate: {control_gate.get('status')}")
    overlay = control_gate.get("paper_plan_overlay", {})
    if overlay:
        print(f"Paper overlay: {overlay.get('status')}")
    print(f"Overlay ledger rows: {control_overlay_summary.get('ledger_rows')}")
    print(f"Overlay allowed plans: {control_overlay_summary.get('overlay_allowed_plans')}")
    print(f"Overlay abstained plans: {control_overlay_summary.get('overlay_abstained_plans')}")
    print(f"Overlay matured plans: {control_overlay_summary.get('overlay_matured_plans')}")
    print(f"Abstained matured plans: {control_overlay_summary.get('abstained_matured_plans')}")
    if control_gate.get("gate_failures"):
        print("Control gate failures:")
        for failure in control_gate["gate_failures"]:
            print(f" - {failure}")
    if control_gate.get("error"):
        print(f"Control gate error: {control_gate['error']}")
    print(f"Saved status -> {args.status_output}")
    print(f"Saved alert -> {args.alert_output}")
    print(f"Saved overlay ledger -> {args.control_overlay_ledger_output}")
    print(f"Saved overlay summary -> {args.control_overlay_summary_output}")
    if args.strict and (status["due_today_count"] or status["overdue_pending_count"]):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
