"""Paper-only Growth24 current-date control gate.

This applies the strongest offline control-overlay threshold to the current
Growth24 shadow forecast. It writes a research gate verdict for shadow
tracking only; it does not alter paper-plan files or live policy.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_OUT_DIR = Path("data/experiment/growth24_shadow_paper")
DEFAULT_FORECAST = DEFAULT_OUT_DIR / "growth24_current_shadow_forecast.csv"
DEFAULT_SUMMARY = DEFAULT_OUT_DIR / "growth24_current_shadow_summary.json"
DEFAULT_PANEL_DIAGNOSTICS = DEFAULT_OUT_DIR / "growth24_current_panel_diagnostics.json"
DEFAULT_PAPER_PLAN = DEFAULT_OUT_DIR / "growth24_current_paper_plan.csv"
DEFAULT_OUTPUT = DEFAULT_OUT_DIR / "growth24_current_control_overlay_gate.json"
DEFAULT_PLAN_OVERLAY_OUTPUT = DEFAULT_OUT_DIR / "growth24_current_paper_plan_control_overlay.csv"
DEFAULT_MARKDOWN_OUTPUT = Path("notes/growth24_current_control_overlay_gate.md")
DEFAULT_UNIVERSE_SCORE_STD_MAX = 0.085
DEFAULT_FORECAST_GAP_MAX = 4.0


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not Path(path).exists():
        return {}
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def _finite_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, tuple):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _fmt_num(value: Any, digits: int = 6) -> str:
    number = _finite_float(value)
    if number is None:
        return "n/a"
    return f"{number:.{digits}f}"


def _load_forecast(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Forecast not found: {path}")
    rows = pd.read_csv(path).copy()
    required = {"AsOfDate", "Ticker", "Rank", "ShadowRankScore", "RawForecastPct"}
    missing = required.difference(rows.columns)
    if missing:
        raise ValueError(f"{path} missing required columns: {sorted(missing)}")
    rows["AsOfDate"] = pd.to_datetime(rows["AsOfDate"], errors="coerce")
    rows["Ticker"] = rows["Ticker"].astype(str).str.upper().str.strip()
    rows["Rank"] = pd.to_numeric(rows["Rank"], errors="coerce")
    rows["ShadowRankScore"] = pd.to_numeric(rows["ShadowRankScore"], errors="coerce")
    rows["RawForecastPct"] = pd.to_numeric(rows["RawForecastPct"], errors="coerce")
    rows["MemberCount"] = pd.to_numeric(rows.get("MemberCount"), errors="coerce")
    rows = rows.dropna(subset=["AsOfDate", "Ticker", "Rank", "ShadowRankScore", "RawForecastPct"]).copy()
    if rows.empty:
        raise RuntimeError(f"No usable forecast rows found in {path}")
    return rows.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False])


def _split_tickers(value: Any) -> list[str]:
    if value is None or pd.isna(value):
        return []
    return [part.strip().upper() for part in str(value).split(",") if part.strip()]


def _clean_scalar(value: Any) -> Any:
    if isinstance(value, np.generic):
        return _clean_scalar(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if pd.isna(value):
        return None
    return value


def _load_paper_plan(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"available": False, "path": None, "reason": "paper plan path disabled"}
    if not Path(path).exists():
        return {"available": False, "path": str(path), "reason": "paper plan not found"}
    rows = pd.read_csv(path).copy()
    if rows.empty:
        return {"available": False, "path": str(path), "reason": "paper plan is empty"}
    row = rows.tail(1).iloc[0].to_dict()
    return {
        "available": True,
        "path": str(path),
        "run_date": str(_clean_scalar(row.get("RunDate")) or ""),
        "asof_date": str(_clean_scalar(row.get("AsOfDate")) or ""),
        "model": str(_clean_scalar(row.get("Model")) or ""),
        "status": str(_clean_scalar(row.get("Status")) or ""),
        "long_tickers": _split_tickers(row.get("LongTickers")),
        "candidate_tickers": _split_tickers(row.get("CandidateTickers")),
        "source_results": str(_clean_scalar(row.get("SourceResults")) or ""),
        "raw_row": {str(k): _json_safe(_clean_scalar(v)) for k, v in row.items()},
    }


def _forecast_metrics(forecasts: pd.DataFrame, long_n: int, short_n: int) -> dict[str, Any]:
    ordered = forecasts.sort_values(["Rank", "ShadowRankScore"], ascending=[True, False]).copy()
    longs = ordered.head(int(long_n))
    shorts = ordered.tail(int(short_n))
    if longs.empty or shorts.empty:
        raise RuntimeError("Forecast does not contain enough rows to build the requested long/short book.")
    return {
        "asof_date": str(ordered["AsOfDate"].iloc[0].date()),
        "model": str(ordered["Model"].iloc[0]) if "Model" in ordered.columns else "",
        "source_results": str(ordered["SourceResults"].iloc[0]) if "SourceResults" in ordered.columns else "",
        "universe_count": int(len(ordered)),
        "long_n": int(long_n),
        "short_n": int(short_n),
        "long_tickers": [str(ticker).upper().strip() for ticker in longs["Ticker"].tolist()],
        "short_tickers": [str(ticker).upper().strip() for ticker in shorts["Ticker"].tolist()],
        "universe_score_std": float(ordered["ShadowRankScore"].std(ddof=0)),
        "long_short_score_gap": float(longs["ShadowRankScore"].mean() - shorts["ShadowRankScore"].mean()),
        "long_vs_universe_score_gap": float(longs["ShadowRankScore"].mean() - ordered["ShadowRankScore"].mean()),
        "long_short_forecast_gap_pct": float(longs["RawForecastPct"].mean() - shorts["RawForecastPct"].mean()),
        "long_vs_universe_forecast_gap_pct": float(longs["RawForecastPct"].mean() - ordered["RawForecastPct"].mean()),
        "long_avg_score": float(longs["ShadowRankScore"].mean()),
        "short_avg_score": float(shorts["ShadowRankScore"].mean()),
        "long_avg_forecast_pct": float(longs["RawForecastPct"].mean()),
        "short_avg_forecast_pct": float(shorts["RawForecastPct"].mean()),
        "min_member_count_long": int(longs["MemberCount"].min()) if "MemberCount" in longs.columns else None,
    }


def _gate_failures(
    metrics: dict[str, Any],
    panel_diagnostics: dict[str, Any],
    args: argparse.Namespace,
) -> list[str]:
    failures: list[str] = []
    universe_count = _finite_float(metrics.get("universe_count"))
    if universe_count is None or universe_count < int(args.expected_universe_count):
        failures.append(f"universe count {universe_count} < {int(args.expected_universe_count)}")

    if panel_diagnostics:
        passed = bool(panel_diagnostics.get("passed", panel_diagnostics.get("status") == "passed"))
        if not passed:
            failures.append("panel diagnostics did not pass")

    universe_score_std = _finite_float(metrics.get("universe_score_std"))
    if universe_score_std is None or universe_score_std > float(args.max_universe_score_std):
        failures.append(
            f"universe score std {universe_score_std:.6f} > {float(args.max_universe_score_std):.6f}"
            if universe_score_std is not None
            else "universe score std missing"
        )

    max_score_gap = getattr(args, "max_score_gap", None)
    if max_score_gap is not None:
        score_gap = _finite_float(metrics.get("long_short_score_gap"))
        if score_gap is None or score_gap > float(max_score_gap):
            failures.append(
                f"long-short score gap {score_gap:.6f} > {float(max_score_gap):.6f}"
                if score_gap is not None
                else "long-short score gap missing"
            )
    max_forecast_gap = getattr(args, "max_forecast_gap", DEFAULT_FORECAST_GAP_MAX)
    if max_forecast_gap is not None:
        forecast_gap = _finite_float(metrics.get("long_short_forecast_gap_pct"))
        if forecast_gap is None or forecast_gap > float(max_forecast_gap):
            failures.append(
                f"long-short forecast gap {forecast_gap:.6f} > {float(max_forecast_gap):.6f}"
                if forecast_gap is not None
                else "long-short forecast gap missing"
            )
    return failures


def _paper_plan_overlay(report: dict[str, Any]) -> dict[str, Any]:
    plan = report.get("paper_plan", {})
    metrics = report.get("forecast_metrics", {})
    gate_status = str(report.get("status", ""))
    plan_status = str(plan.get("status", "")).lower()
    warnings: list[str] = []
    plan_longs = [str(ticker).upper().strip() for ticker in plan.get("long_tickers", [])]
    gate_longs = [str(ticker).upper().strip() for ticker in metrics.get("long_tickers", [])]
    if plan_longs and gate_longs and set(plan_longs) != set(gate_longs):
        warnings.append("paper plan long tickers differ from current gate long tickers")

    if not plan.get("available"):
        overlay_status = "paper_overlay_unavailable"
        action = "No current paper plan was available to compare against the control gate."
    elif gate_status == "paper_control_allowed":
        overlay_status = "paper_overlay_allowed"
        action = "Control gate allows the current paper plan for paper-only tracking."
    elif plan_status == "selected":
        overlay_status = "paper_overlay_abstain"
        action = (
            "Control gate would abstain from the selected paper plan; keep the base "
            "paper plan unchanged and score both paths at maturity."
        )
    else:
        overlay_status = "paper_overlay_no_action"
        action = "Standing paper policy did not select a plan, so the control gate adds no action."

    return {
        "status": overlay_status,
        "action": action,
        "paper_only": True,
        "live_policy_changed": False,
        "paper_plan_changed": False,
        "plan_path": plan.get("path"),
        "plan_status": plan.get("status"),
        "plan_long_tickers": plan_longs,
        "plan_candidate_tickers": plan.get("candidate_tickers", []),
        "gate_status": gate_status,
        "gate_long_tickers": gate_longs,
        "gate_failures": list(report.get("gate_failures", [])),
        "warnings": warnings,
    }


def build_gate(args: argparse.Namespace) -> dict[str, Any]:
    forecasts = _load_forecast(args.forecast)
    summary = _load_json(args.summary)
    panel_diagnostics = _load_json(args.panel_diagnostics)
    paper_plan = _load_paper_plan(getattr(args, "paper_plan", DEFAULT_PAPER_PLAN))
    metrics = _forecast_metrics(forecasts, int(args.long_n), int(args.short_n))
    failures = _gate_failures(metrics, panel_diagnostics, args)
    status = "paper_control_abstain" if failures else "paper_control_allowed"
    report = {
        "status": status,
        "paper_only": True,
        "live_policy_changed": False,
        "paper_plan_changed": False,
        "forecast": str(args.forecast),
        "summary": str(args.summary) if args.summary is not None else None,
        "panel_diagnostics": str(args.panel_diagnostics) if args.panel_diagnostics is not None else None,
        "paper_plan": paper_plan,
        "forecast_metrics": metrics,
        "current_summary_status": summary.get("status"),
        "current_summary_selected_tickers": summary.get("selected_tickers"),
        "thresholds": {
            "expected_universe_count": int(args.expected_universe_count),
            "long_n": int(args.long_n),
            "short_n": int(args.short_n),
            "max_universe_score_std": float(args.max_universe_score_std),
            "max_score_gap": _finite_float(getattr(args, "max_score_gap", None))
            if getattr(args, "max_score_gap", None) is not None
            else None,
            "max_forecast_gap": _finite_float(getattr(args, "max_forecast_gap", DEFAULT_FORECAST_GAP_MAX))
            if getattr(args, "max_forecast_gap", DEFAULT_FORECAST_GAP_MAX) is not None
            else None,
            "research_source": "Growth24 36-cycle 8-epoch post-prediction walk-forward overlay",
        },
        "gate_failures": failures,
        "recommendation": (
            "Track as paper-control abstain only; keep existing paper plan unchanged."
            if failures
            else "Track as paper-control allowed; keep existing paper plan unchanged."
        ),
    }
    report["paper_plan_overlay"] = _paper_plan_overlay(report)
    return report


def _overlay_row(report: dict[str, Any]) -> dict[str, Any]:
    overlay = report.get("paper_plan_overlay", {})
    plan = report.get("paper_plan", {})
    metrics = report.get("forecast_metrics", {})
    return {
        "RunDate": plan.get("run_date", ""),
        "AsOfDate": plan.get("asof_date", metrics.get("asof_date", "")),
        "Model": plan.get("model", metrics.get("model", "")),
        "PlanStatus": overlay.get("plan_status", ""),
        "PlanLongTickers": ",".join(overlay.get("plan_long_tickers", [])),
        "GateStatus": overlay.get("gate_status", ""),
        "OverlayStatus": overlay.get("status", ""),
        "OverlayAction": overlay.get("action", ""),
        "PaperOnly": bool(overlay.get("paper_only", True)),
        "LivePolicyChanged": bool(overlay.get("live_policy_changed", False)),
        "PaperPlanChanged": bool(overlay.get("paper_plan_changed", False)),
        "UniverseScoreStd": metrics.get("universe_score_std"),
        "MaxUniverseScoreStd": report.get("thresholds", {}).get("max_universe_score_std"),
        "LongShortForecastGapPct": metrics.get("long_short_forecast_gap_pct"),
        "MaxForecastGapPct": report.get("thresholds", {}).get("max_forecast_gap"),
        "GateLongTickers": ",".join(overlay.get("gate_long_tickers", [])),
        "GateFailures": "; ".join(overlay.get("gate_failures", [])),
        "Warnings": "; ".join(overlay.get("warnings", [])),
        "PlanPath": overlay.get("plan_path", ""),
    }


def write_plan_overlay(path: Path | None, report: dict[str, Any]) -> None:
    if path is None:
        return
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([_overlay_row(report)]).to_csv(path, index=False)


def _markdown(report: dict[str, Any]) -> str:
    metrics = report["forecast_metrics"]
    failures = report["gate_failures"]
    plan = report.get("paper_plan", {})
    overlay = report.get("paper_plan_overlay", {})
    lines = [
        "# Growth24 Current Control Overlay Gate",
        "",
        f"- Status: `{report['status']}`",
        f"- Paper only: {report['paper_only']}",
        f"- Live policy changed: {report['live_policy_changed']}",
        f"- Paper plan changed: {report.get('paper_plan_changed', False)}",
        f"- Forecast: `{report['forecast']}`",
        f"- Paper plan: `{plan.get('path')}`",
        f"- AsOfDate: {metrics['asof_date']}",
        f"- Current paper selection: `{report.get('current_summary_selected_tickers')}`",
        f"- Gate longs: `{','.join(metrics['long_tickers'])}`",
        f"- Gate shorts: `{','.join(metrics['short_tickers'])}`",
        "",
        "## Paper Plan Overlay",
        "",
        f"- Overlay status: `{overlay.get('status')}`",
        f"- Plan status: `{overlay.get('plan_status')}`",
        f"- Plan longs: `{','.join(overlay.get('plan_long_tickers', []))}`",
        f"- Gate status: `{overlay.get('gate_status')}`",
        f"- Paper plan changed: {overlay.get('paper_plan_changed', False)}",
        f"- Action: {overlay.get('action')}",
        "",
        "## Metrics",
        "",
        "| Metric | Value | Threshold |",
        "|---|---:|---:|",
        (
            f"| Universe count | {metrics['universe_count']} | "
            f"{report['thresholds']['expected_universe_count']} |"
        ),
        (
            f"| Universe score std | {_fmt_num(metrics['universe_score_std'])} | "
            f"{_fmt_num(report['thresholds']['max_universe_score_std'])} max |"
        ),
        f"| Long-short score gap | {_fmt_num(metrics['long_short_score_gap'])} | n/a |",
        (
            f"| Long-short forecast gap | {_fmt_num(metrics['long_short_forecast_gap_pct'])} | "
            f"{_fmt_num(report['thresholds']['max_forecast_gap'])} max |"
        ),
        "",
        "## Failures",
        "",
    ]
    if failures:
        lines.extend(f"- {failure}" for failure in failures)
    else:
        lines.append("- none")
    warnings = overlay.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    lines.extend(["", "## Recommendation", "", report["recommendation"], ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply the paper-only Growth24 current control gate.")
    parser.add_argument("--forecast", type=Path, default=DEFAULT_FORECAST)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--panel-diagnostics", type=Path, default=DEFAULT_PANEL_DIAGNOSTICS)
    parser.add_argument("--paper-plan", type=Path, default=DEFAULT_PAPER_PLAN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--plan-overlay-output", type=Path, default=DEFAULT_PLAN_OVERLAY_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--long-n", type=int, default=2)
    parser.add_argument("--short-n", type=int, default=2)
    parser.add_argument("--expected-universe-count", type=int, default=24)
    parser.add_argument("--max-universe-score-std", type=float, default=DEFAULT_UNIVERSE_SCORE_STD_MAX)
    parser.add_argument("--max-score-gap", type=float, default=None)
    args = parser.parse_args()

    report = build_gate(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_json_safe(report), indent=2), encoding="utf-8")
    write_plan_overlay(args.plan_overlay_output, report)
    args.markdown_output.write_text(_markdown(report), encoding="utf-8")

    print(f"Status: {report['status']}")
    print(f"Overlay: {report['paper_plan_overlay']['status']}")
    print(f"AsOfDate: {report['forecast_metrics']['asof_date']}")
    print(f"Longs: {', '.join(report['forecast_metrics']['long_tickers'])}")
    print(f"Universe score std: {report['forecast_metrics']['universe_score_std']:.6f}")
    if report["gate_failures"]:
        print("Gate failures:")
        for failure in report["gate_failures"]:
            print(f" - {failure}")
    print(f"Saved -> {args.output}")
    print(f"Saved -> {args.plan_overlay_output}")
    print(f"Saved -> {args.markdown_output}")


if __name__ == "__main__":
    main()
