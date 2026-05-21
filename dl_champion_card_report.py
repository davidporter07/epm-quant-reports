"""Build a reusable champion card for the Growth24 DL research lane.

The card is a compact decision artifact for the champion/challenger loop. It
reads existing offline research outputs only; it does not train, score new
trades, or touch the live forecasting pipeline.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_STEM = "growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed"
DEFAULT_RESULTS_DIR = Path("data/experiment/historical_blind_rank_head")
DEFAULT_PAPER_DIR = Path("data/experiment/growth24_shadow_paper")
DEFAULT_REGIME_DIR = Path("data/experiment/final4_growth24_earnings_regime_probe")
DEFAULT_OUTPUT = DEFAULT_RESULTS_DIR / "growth24_dl_champion_card.json"
DEFAULT_MARKDOWN_OUTPUT = Path("notes/growth24_dl_champion_card.md")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"status": "invalid_json", "path": str(path), "error": str(exc)}


def _fmt_pct(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{number * 100:.{digits}f}%"


def _fmt_num(value: Any, digits: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{number:.{digits}f}"


def _first_passing_config(payload: dict[str, Any]) -> dict[str, Any] | None:
    configs = payload.get("passing_configs")
    if isinstance(configs, list) and configs:
        return configs[0]
    return None


def _summary_from_paper(payload: dict[str, Any]) -> dict[str, Any]:
    status = payload.get("status")
    if status == "missing":
        return {"status": "missing"}
    return {
        "status": status or "scored",
        "trade_rows": payload.get("trade_rows"),
        "matured_trades": payload.get("matured_trades"),
        "pending_trades": payload.get("pending_trades"),
        "matured_plans": payload.get("matured_plans"),
        "pending_plans": payload.get("pending_plans"),
        "mean_forward_21d": payload.get("mean_forward_21d"),
        "mean_excess_21d": payload.get("mean_excess_21d"),
        "hit_rate": payload.get("hit_rate"),
        "excess_hit_rate": payload.get("excess_hit_rate"),
    }


def build_card(
    stem: str,
    results_dir: Path,
    paper_dir: Path,
    regime_dir: Path,
) -> dict[str, Any]:
    summary = _load_json(results_dir / f"{stem}_summary.json")
    paper_summary = _load_json(results_dir / f"{stem}_shadow_log_paper_summary.json")
    cap_aware = _load_json(results_dir / f"{stem}_cap_aware_cov50_dd35.json")
    long_only = _load_json(results_dir / f"{stem}_long_only_gate_dd35.json")
    ticker_holdout = _load_json(results_dir / f"{stem}_ticker_holdout.json")
    diagnostic = _load_json(results_dir / f"{stem}_diagnostic.json")
    hmm_abstention = _load_json(results_dir / f"{stem}_hmm_abstention.json")
    failure_analysis = _load_json(results_dir / f"{stem}_failure_analysis.json")
    ticker_cooldown = _load_json(results_dir / f"{stem}_ticker_cooldown.json")
    live_paper = _load_json(paper_dir / "growth24_paper_outcome_summary.json")
    regime_gate = _load_json(regime_dir / "regime_gate_refresh.json")
    abstention_gate = _load_json(regime_dir / "abstention_gate_refresh_narrow.json")
    cooldown_regime_gate = _load_json(Path("data/experiment/final4_growth24_earnings_ticker_cooldown_probe/regime_gate.json"))

    cap_config = _first_passing_config(cap_aware)
    long_config = _first_passing_config(long_only)
    best_abstention = None
    if isinstance(abstention_gate.get("configs"), list) and abstention_gate["configs"]:
        best_abstention = abstention_gate["configs"][0]

    paper_metrics = paper_summary.get("paper_metrics") if isinstance(paper_summary.get("paper_metrics"), dict) else {}
    if not paper_metrics and paper_summary.get("status") == "scored":
        paper_metrics = paper_summary

    card = {
        "champion": {
            "name": "Growth24 rank-head RSI/MA/volume/earnings",
            "artifact_stem": stem,
            "status": "research_champion_shadow_only",
            "production_ready": False,
            "promotion_blocker": "Needs stress/abstention/paper validation before forecasting-page integration.",
        },
        "historical_blind": {
            "status": summary.get("status", "unknown"),
            "panel": summary.get("panel"),
            "cycles": summary.get("cycles"),
            "top_n": summary.get("top_n"),
            "paper_long_n": summary.get("paper_long_n"),
            "paper_short_n": summary.get("paper_short_n"),
        },
        "paper_replay": {
            "status": paper_metrics.get("status", paper_summary.get("status", "unknown")),
            "trade_days": paper_metrics.get("trade_days"),
            "mean_long_return": paper_metrics.get("mean_long_return"),
            "mean_short_return": paper_metrics.get("mean_short_return"),
            "mean_long_short_return": paper_metrics.get("mean_long_short_return"),
            "median_long_short_return": paper_metrics.get("median_long_short_return"),
            "spread_hit_rate": paper_metrics.get("spread_hit_rate"),
            "long_hit_rate": paper_metrics.get("long_hit_rate"),
            "short_hit_rate": paper_metrics.get("short_hit_rate"),
            "max_drawdown": paper_metrics.get("max_drawdown"),
        },
        "cap_aware_gate": {
            "status": cap_aware.get("status", "unknown"),
            "available_days": cap_aware.get("available_days"),
            "best_config": cap_config,
        },
        "long_only_gate": {
            "status": long_only.get("status", "unknown"),
            "best_config": long_config,
        },
        "ticker_holdout": {
            "status": ticker_holdout.get("status", "unknown"),
            "top_n_reports": ticker_holdout.get("reports") or ticker_holdout.get("baskets"),
        },
        "regime_stress_gate": {
            "status": regime_gate.get("status", "unknown"),
            "results_dir": regime_gate.get("results_dir"),
            "gate_config": regime_gate.get("gate_config"),
            "gates": regime_gate.get("gates"),
        },
        "abstention_gate": {
            "status": abstention_gate.get("status", "unknown"),
            "results_dir": abstention_gate.get("results_dir"),
            "gate_config": abstention_gate.get("gate_config"),
            "passing_config_count": len(abstention_gate.get("passing_configs") or []),
            "best_config": best_abstention,
        },
        "hmm_post_prediction_filter": {
            "status": hmm_abstention.get("status", "unknown"),
            "skipped_hmm_stress_days": hmm_abstention.get("skipped_hmm_stress_days"),
            "kept_non_hmm_stress_days": hmm_abstention.get("kept_non_hmm_stress_days"),
            "all": hmm_abstention.get("all"),
            "trade_only_non_hmm_stress": hmm_abstention.get("trade_only_non_hmm_stress"),
            "hmm_stress_only": hmm_abstention.get("hmm_stress_only"),
        },
        "failure_analysis": {
            "status": failure_analysis.get("status", "unknown"),
            "cycle_count": failure_analysis.get("cycle_count"),
            "loss_cycle_count": failure_analysis.get("loss_cycle_count"),
            "loss_cycle_rate": failure_analysis.get("loss_cycle_rate"),
            "mean_loss_spread": failure_analysis.get("mean_loss_spread"),
            "worst_cycles": failure_analysis.get("worst_cycles"),
            "loss_ticker_contribution": failure_analysis.get("loss_ticker_contribution"),
            "hmm_regime_loss_counts": failure_analysis.get("hmm_regime_loss_counts"),
        },
        "ticker_cooldown_replay": {
            "status": ticker_cooldown.get("status", "unknown"),
            "available_days": ticker_cooldown.get("available_days"),
            "best_config": (ticker_cooldown.get("configs") or [{}])[0],
            "regime_gate_status": cooldown_regime_gate.get("status", "unknown"),
            "regime_gate": cooldown_regime_gate,
        },
        "diagnostic": {
            "status": diagnostic.get("status", "unknown"),
            "path": str(results_dir / f"{stem}_diagnostic.json"),
        },
        "live_shadow_paper": _summary_from_paper(live_paper),
        "next_required_work": [
            "Do not run 36-cycle PEAD/HMM raw-feature replay; 12-cycle filter failed.",
            "Do not use simple HMM-stress skipping as the next abstention rule; it skipped too few dates and removed profitable stress decisions.",
            "Do not promote the ticker cooldown challenger yet; it improved 36-cycle average but failed the stress gate.",
            "Keep the champion fixed while testing one challenger at a time.",
            "Treat regime stress and abstention as the active blocker before forecasting-page integration.",
            "Continue Growth24 paper outcome scoring until more plans mature.",
            "Only consider forecasting-page integration after stress, abstention, and matured paper evidence pass.",
        ],
    }
    return card


def _markdown(card: dict[str, Any]) -> str:
    champion = card["champion"]
    paper = card["paper_replay"]
    cap_summary = ((card.get("cap_aware_gate") or {}).get("best_config") or {}).get("summary") or {}
    long_summary = ((card.get("long_only_gate") or {}).get("best_config") or {}).get("summary") or {}
    abstention_best = (card.get("abstention_gate") or {}).get("best_config") or {}
    abstention_gate = abstention_best.get("gate") or {}
    hmm_filter = card.get("hmm_post_prediction_filter") or {}
    hmm_non_stress = hmm_filter.get("trade_only_non_hmm_stress") or {}
    hmm_stress = hmm_filter.get("hmm_stress_only") or {}
    failure = card.get("failure_analysis") or {}
    worst_cycles = failure.get("worst_cycles") or []
    worst = worst_cycles[0] if worst_cycles else {}
    cooldown = ((card.get("ticker_cooldown_replay") or {}).get("best_config") or {})
    cooldown_summary = cooldown.get("summary") or {}
    cooldown_gate = card.get("ticker_cooldown_replay") or {}
    live = card.get("live_shadow_paper") or {}

    lines = [
        "# Growth24 DL Champion Card",
        "",
        f"- Champion: {champion['name']}",
        f"- Artifact stem: `{champion['artifact_stem']}`",
        f"- Status: `{champion['status']}`",
        f"- Production ready: {champion['production_ready']}",
        f"- Promotion blocker: {champion['promotion_blocker']}",
        "",
        "## Historical Blind Replay",
        "",
        f"- Cycles: {card['historical_blind'].get('cycles', 'n/a')}",
        f"- Mean long-short: {_fmt_pct(paper.get('mean_long_short_return'))}",
        f"- Spread hit rate: {_fmt_pct(paper.get('spread_hit_rate'))}",
        f"- Max drawdown: {_fmt_pct(paper.get('max_drawdown'))}",
        f"- Long hit rate: {_fmt_pct(paper.get('long_hit_rate'))}",
        "",
        "## Gates",
        "",
        f"- Cap-aware gate: `{card['cap_aware_gate'].get('status', 'unknown')}`",
        f"- Cap-aware mean excess: {_fmt_pct(cap_summary.get('mean_long_excess_return'))}",
        f"- Cap-aware coverage: {_fmt_pct(cap_summary.get('coverage'))}",
        f"- Cap-aware max ticker slot share: {_fmt_pct(cap_summary.get('max_ticker_slot_share'))}",
        f"- Long-only gate: `{card['long_only_gate'].get('status', 'unknown')}`",
        f"- Long-only mean excess: {_fmt_pct(long_summary.get('mean_long_excess_return'))}",
        f"- Long-only max ticker share: {_fmt_pct(long_summary.get('max_ticker_share'))}",
        f"- Regime stress gate: `{card['regime_stress_gate'].get('status', 'unknown')}`",
        f"- Abstention gate: `{card['abstention_gate'].get('status', 'unknown')}`",
        f"- Abstention passing configs: {card['abstention_gate'].get('passing_config_count', 'n/a')}",
        f"- Best abstention stress spread: {_fmt_pct(abstention_gate.get('mean_spread_stress'))}",
        f"- Best abstention stress coverage: {_fmt_pct(abstention_gate.get('mean_coverage_stress'))}",
        f"- Best abstention worst stress drawdown: {_fmt_pct(abstention_gate.get('worst_stress_drawdown'))}",
        f"- HMM skip-stress test: `{hmm_filter.get('status', 'unknown')}`",
        f"- HMM skipped stress days: {hmm_filter.get('skipped_hmm_stress_days', 'n/a')}",
        f"- HMM non-stress mean excess: {_fmt_pct(hmm_non_stress.get('mean_long_excess_return'))}",
        f"- HMM stress-only mean excess: {_fmt_pct(hmm_stress.get('mean_long_excess_return'))}",
        f"- Loss cycles: {failure.get('loss_cycle_count', 'n/a')} ({_fmt_pct(failure.get('loss_cycle_rate'))})",
        f"- Mean loss spread: {_fmt_pct(failure.get('mean_loss_spread'))}",
        f"- Worst cycle: {worst.get('AsOfDate', 'n/a')} {worst.get('LongTickers', '')} vs {worst.get('ShortTickers', '')} ({_fmt_pct(worst.get('LongShortReturn'))})",
        f"- Best cooldown challenger: top{cooldown.get('top_n', 'n/a')}, max_share={_fmt_pct(cooldown.get('max_ticker_share'))}, cooldown={cooldown.get('cooldown_cycles', 'n/a')}, max_consecutive={cooldown.get('max_consecutive', 'n/a')}",
        f"- Best cooldown mean excess: {_fmt_pct(cooldown_summary.get('mean_long_excess_return'))}",
        f"- Best cooldown excess hit rate: {_fmt_pct(cooldown_summary.get('excess_hit_rate'))}",
        f"- Best cooldown max slot share: {_fmt_pct(cooldown_summary.get('max_ticker_slot_share'))}",
        f"- Cooldown stress gate: `{cooldown_gate.get('regime_gate_status', 'unknown')}`",
        "",
        "## Live Shadow Paper",
        "",
        f"- Matured trades: {live.get('matured_trades', 'n/a')}",
        f"- Pending trades: {live.get('pending_trades', 'n/a')}",
        f"- Mean forward 21D: {_fmt_pct(live.get('mean_forward_21d'))}",
        f"- Mean excess 21D: {_fmt_pct(live.get('mean_excess_21d'))}",
        f"- Excess hit rate: {_fmt_pct(live.get('excess_hit_rate'))}",
        "",
        "## Next Required Work",
        "",
    ]
    lines.extend(f"- {item}" for item in card["next_required_work"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the Growth24 DL champion card.")
    parser.add_argument("--stem", default=DEFAULT_STEM)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--paper-dir", type=Path, default=DEFAULT_PAPER_DIR)
    parser.add_argument("--regime-dir", type=Path, default=DEFAULT_REGIME_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    args = parser.parse_args()

    card = build_card(args.stem, args.results_dir, args.paper_dir, args.regime_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(card, indent=2), encoding="utf-8")
    args.markdown_output.write_text(_markdown(card), encoding="utf-8")

    paper = card["paper_replay"]
    print("Status: champion-card-written")
    print(f"Champion: {card['champion']['artifact_stem']}")
    print(f"Cycles: {card['historical_blind'].get('cycles')}")
    print(f"Mean long-short: {_fmt_pct(paper.get('mean_long_short_return'))}")
    print(f"Spread hit rate: {_fmt_pct(paper.get('spread_hit_rate'))}")
    print(f"Saved JSON -> {args.output}")
    print(f"Saved Markdown -> {args.markdown_output}")


if __name__ == "__main__":
    main()
