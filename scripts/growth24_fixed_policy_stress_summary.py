"""Summarize Growth24 fixed-policy stress replay ledgers.

This is research-only. It consumes ledgers produced by
dl_growth24_shadow_policy_replay.py and applies the pre-registered stress gates
from the Growth24 research plan.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dl_growth24_post_prediction_gate_grid import _fmt_pct, _max_drawdown


DEFAULT_EXPECTED_REGIMES = "current_2026,gfc_2008,q4_2018_drawdown,rate_bear_2022"


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _safe_mean(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.mean()) if not numeric.empty else None


def _safe_hit(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float((numeric > 0.0).mean()) if not numeric.empty else None


def _safe_drawdown(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    if numeric.empty:
        return None
    out = _max_drawdown(numeric)
    return float(out) if np.isfinite(out) else None


def _parse_ledger_name(path: Path, policy_prefix: str) -> tuple[str, str]:
    stem = path.stem
    if not stem.startswith(policy_prefix):
        raise ValueError(f"Ledger {path} does not start with prefix {policy_prefix!r}")
    remainder = stem[len(policy_prefix) :]
    if "_" not in remainder:
        raise ValueError(f"Ledger {path} does not end with a policy suffix")
    regime, policy = remainder.rsplit("_", 1)
    if not regime or not policy:
        raise ValueError(f"Ledger {path} has invalid regime/policy tokens")
    return regime, policy


def _load_ledgers(input_dir: Path, policy_prefix: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted(input_dir.glob(f"{policy_prefix}*.csv")):
        regime, policy = _parse_ledger_name(path, policy_prefix)
        rows = pd.read_csv(path)
        rows["Regime"] = regime
        rows["Policy"] = policy
        rows["SourcePath"] = str(path)
        frames.append(rows)
    if not frames:
        raise FileNotFoundError(f"No stress replay ledgers matched {policy_prefix!r} in {input_dir}")
    out = pd.concat(frames, ignore_index=True)
    required = {"AsOfDate", "OverlayStatus", "BaselineLongShortReturn", "OverlayLongShortReturn", "Regime", "Policy"}
    missing = required.difference(out.columns)
    if missing:
        raise ValueError(f"Stress replay ledger missing required columns: {sorted(missing)}")
    out["AsOfDate"] = pd.to_datetime(out["AsOfDate"], errors="raise")
    return out.sort_values(["Policy", "AsOfDate", "Regime"]).reset_index(drop=True)


def _metric_block(rows: pd.DataFrame, return_col: str) -> dict[str, Any]:
    values = pd.to_numeric(rows[return_col], errors="coerce") if not rows.empty else pd.Series(dtype=float)
    return {
        "cycles": int(len(rows)),
        "mean_long_short": _safe_mean(values),
        "hit_rate": _safe_hit(values),
        "max_drawdown": _safe_drawdown(values),
    }


def _policy_report(
    rows: pd.DataFrame,
    *,
    min_allowed_decisions: int,
    min_mean_long_short: float,
    min_hit_rate: float,
    max_drawdown: float,
    min_window_mean_long_short: float,
    max_drawdown_worsening: float,
) -> dict[str, Any]:
    policy = str(rows["Policy"].iloc[0])
    baseline = _metric_block(rows.sort_values("AsOfDate"), "BaselineLongShortReturn")
    allowed = rows[rows["OverlayStatus"].eq("paper_overlay_allowed")].copy().sort_values("AsOfDate")
    allowed_metrics = _metric_block(allowed, "OverlayLongShortReturn")
    failures: list[str] = []

    if allowed_metrics["cycles"] < int(min_allowed_decisions):
        failures.append(f"allowed decisions {allowed_metrics['cycles']} < {int(min_allowed_decisions)}")
    if allowed_metrics["mean_long_short"] is None or allowed_metrics["mean_long_short"] <= float(min_mean_long_short):
        failures.append(
            "allowed mean long-short is missing"
            if allowed_metrics["mean_long_short"] is None
            else f"allowed mean long-short {allowed_metrics['mean_long_short']:.6f} <= {float(min_mean_long_short):.6f}"
        )
    if allowed_metrics["hit_rate"] is None or allowed_metrics["hit_rate"] < float(min_hit_rate):
        failures.append(
            "allowed hit rate is missing"
            if allowed_metrics["hit_rate"] is None
            else f"allowed hit rate {allowed_metrics['hit_rate']:.2%} < {float(min_hit_rate):.2%}"
        )
    if allowed_metrics["max_drawdown"] is None or allowed_metrics["max_drawdown"] < float(max_drawdown):
        failures.append(
            "allowed max drawdown is missing"
            if allowed_metrics["max_drawdown"] is None
            else f"allowed max drawdown {allowed_metrics['max_drawdown']:.2%} < {float(max_drawdown):.2%}"
        )
    baseline_dd = baseline["max_drawdown"]
    allowed_dd = allowed_metrics["max_drawdown"]
    if baseline_dd is None or allowed_dd is None:
        failures.append("drawdown comparison is missing")
    elif allowed_dd < baseline_dd - float(max_drawdown_worsening):
        failures.append(
            f"allowed drawdown {allowed_dd:.2%} worsens baseline {baseline_dd:.2%} by more than "
            f"{float(max_drawdown_worsening):.2%}"
        )

    regimes = []
    for regime, regime_rows in rows.groupby("Regime", sort=True):
        regime_allowed = regime_rows[regime_rows["OverlayStatus"].eq("paper_overlay_allowed")].copy().sort_values("AsOfDate")
        regime_allowed_metrics = _metric_block(regime_allowed, "OverlayLongShortReturn")
        regime_baseline_metrics = _metric_block(regime_rows.sort_values("AsOfDate"), "BaselineLongShortReturn")
        if (
            regime_allowed_metrics["cycles"] > 0
            and regime_allowed_metrics["mean_long_short"] is not None
            and regime_allowed_metrics["mean_long_short"] < float(min_window_mean_long_short)
        ):
            failures.append(
                f"{regime} allowed mean long-short {regime_allowed_metrics['mean_long_short']:.6f} < "
                f"{float(min_window_mean_long_short):.6f}"
            )
        regimes.append(
            {
                "regime": str(regime),
                "baseline": regime_baseline_metrics,
                "allowed": regime_allowed_metrics,
                "abstained_cycles": int(regime_rows["OverlayStatus"].eq("paper_overlay_abstain").sum()),
            }
        )

    return {
        "policy": policy,
        "status": "pass" if not failures else "fail",
        "failures": failures,
        "cycles": int(len(rows)),
        "coverage": float(allowed_metrics["cycles"] / len(rows)) if len(rows) else None,
        "baseline": baseline,
        "allowed": allowed_metrics,
        "drawdown_delta_vs_baseline": (
            float(allowed_metrics["max_drawdown"] - baseline["max_drawdown"])
            if allowed_metrics["max_drawdown"] is not None and baseline["max_drawdown"] is not None
            else None
        ),
        "regimes": regimes,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    rows = _load_ledgers(args.input_dir, args.policy_prefix)
    expected_regimes = [part.strip() for part in str(args.expected_regimes).split(",") if part.strip()]
    policies = []
    for policy, policy_rows in rows.groupby("Policy", sort=True):
        seen_regimes = set(policy_rows["Regime"].astype(str))
        missing = sorted(set(expected_regimes).difference(seen_regimes))
        policy_report = _policy_report(
            policy_rows,
            min_allowed_decisions=args.min_allowed_decisions,
            min_mean_long_short=args.min_mean_long_short,
            min_hit_rate=args.min_hit_rate,
            max_drawdown=args.max_drawdown,
            min_window_mean_long_short=args.min_window_mean_long_short,
            max_drawdown_worsening=args.max_drawdown_worsening,
        )
        if missing:
            policy_report["status"] = "fail"
            policy_report["failures"].append(f"missing regimes: {', '.join(missing)}")
        policies.append(policy_report)

    primary = next((policy for policy in policies if policy["policy"] == args.primary_policy), None)
    if primary is None:
        overall_status = "fail"
        failures = [f"primary policy {args.primary_policy!r} was not found"]
    else:
        overall_status = primary["status"]
        failures = [f"primary {args.primary_policy}: {failure}" for failure in primary["failures"]]

    return {
        "status": overall_status,
        "failures": failures,
        "input_dir": str(args.input_dir),
        "policy_prefix": args.policy_prefix,
        "baseline_note": str(args.baseline_note) if args.baseline_note else None,
        "primary_policy": args.primary_policy,
        "gate_config": {
            "expected_regimes": expected_regimes,
            "min_allowed_decisions": int(args.min_allowed_decisions),
            "min_mean_long_short": float(args.min_mean_long_short),
            "min_hit_rate": float(args.min_hit_rate),
            "max_drawdown": float(args.max_drawdown),
            "min_window_mean_long_short": float(args.min_window_mean_long_short),
            "max_drawdown_worsening": float(args.max_drawdown_worsening),
        },
        "policies": policies,
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Growth24 Fixed-Policy Stress Summary",
        "",
        f"- Status: `{report['status']}`",
        f"- Input dir: `{report['input_dir']}`",
        f"- Baseline note: `{report['baseline_note']}`",
        f"- Primary policy: `{report['primary_policy']}`",
        "",
        "## Policy Summary",
        "",
        "| Policy | Status | Allowed | Coverage | Allowed Mean LS | Allowed Hit | Allowed DD | Baseline DD | Failures |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for policy in report["policies"]:
        failure_text = "; ".join(policy["failures"])
        lines.append(
            f"| {policy['policy']} | {policy['status']} | {policy['allowed']['cycles']} / {policy['cycles']} | "
            f"{_fmt_pct(policy['coverage'])} | {_fmt_pct(policy['allowed']['mean_long_short'])} | "
            f"{_fmt_pct(policy['allowed']['hit_rate'])} | {_fmt_pct(policy['allowed']['max_drawdown'])} | "
            f"{_fmt_pct(policy['baseline']['max_drawdown'])} | {failure_text} |"
        )

    lines.extend(
        [
            "",
            "## Regime Detail",
            "",
            "| Policy | Regime | Allowed | Abstained | Allowed Mean LS | Allowed Hit | Allowed DD | Baseline Mean LS |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for policy in report["policies"]:
        for regime in policy["regimes"]:
            lines.append(
                f"| {policy['policy']} | {regime['regime']} | {regime['allowed']['cycles']} | "
                f"{regime['abstained_cycles']} | {_fmt_pct(regime['allowed']['mean_long_short'])} | "
                f"{_fmt_pct(regime['allowed']['hit_rate'])} | {_fmt_pct(regime['allowed']['max_drawdown'])} | "
                f"{_fmt_pct(regime['baseline']['mean_long_short'])} |"
            )

    if report["failures"]:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in report["failures"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize Growth24 fixed-policy stress replay ledgers.")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--policy-prefix", default="stress_")
    parser.add_argument("--baseline-note", type=Path, default=None)
    parser.add_argument("--primary-policy", default="p0")
    parser.add_argument("--expected-regimes", default=DEFAULT_EXPECTED_REGIMES)
    parser.add_argument("--min-allowed-decisions", type=int, default=4)
    parser.add_argument("--min-mean-long-short", type=float, default=0.0)
    parser.add_argument("--min-hit-rate", type=float, default=0.50)
    parser.add_argument("--max-drawdown", type=float, default=-0.25)
    parser.add_argument("--min-window-mean-long-short", type=float, default=-0.05)
    parser.add_argument("--max-drawdown-worsening", type=float, default=0.05)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, default=None)
    args = parser.parse_args()

    report = build_report(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_json_safe(report), indent=2), encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(_markdown(report), encoding="utf-8")
    print(f"Status: {report['status']}")
    for policy in report["policies"]:
        print(
            f"{policy['policy']}: {policy['status']} allowed={policy['allowed']['cycles']}/{policy['cycles']} "
            f"mean={_fmt_pct(policy['allowed']['mean_long_short'])} dd={_fmt_pct(policy['allowed']['max_drawdown'])}"
        )
    print(f"Saved -> {args.output}")


if __name__ == "__main__":
    main()
