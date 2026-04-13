"""feature_dashboard_gen.py

Generate a self-contained internal HTML dashboard from feature pipeline JSON outputs.
Reads feature_store/ outputs and writes charts/feature_dashboard.html.

Usage
-----
python feature_dashboard_gen.py
"""

from __future__ import annotations

import glob
import json
from datetime import datetime
from pathlib import Path

BASE  = Path(__file__).parent
STORE = BASE / "feature_store"
OUT   = STORE / "dashboard" / "feature_dashboard.html"  # local-only: not in SYNC_DIRS

# DL experiment result files (data/experiment/)  never synced to server
DL_EXP_DIR = BASE / "data" / "experiment"
DL_EXPS = [
    {
        "key":      "exp1_rsi14_removal",
        "title":    "Exp 1  RSI_14 Removal (from scratch)",
        "protocol": "From-scratch training, fixed seed 20260401, 10 epochs, MAG7 panel. Tests whether removing RSI_14 improves calibration.",
        "file":     DL_EXP_DIR / "rsi14_removal_comparison.json",
        "schema":   "results_list",   # {"test_cutoff":, "results":[{variant, mae, correlation, ic_spearman, directional_accuracy}]}
        "finding":  "11-feat model is degenerate: 96.8% positive predictions (always-bullish). RSI_14 removal fixes calibration  10-feat predicts negative 37% of the time (actual 42%). IC improves from 0.091 to 0.006.",
        "verdict":  "REMOVE",
    },
    {
        "key":      "exp2_logvol_addition",
        "title":    "Exp 2  log_volume Addition (from scratch)",
        "protocol": "From-scratch training, same config. Tests log_volume on top of the 11-feat baseline.",
        "file":     DL_EXP_DIR / "log_volume_addition_comparison.json",
        "schema":   "flat_dict",      # {"11feat":{label, mae, corr, ic, pred_std, pct_neg_pred}, "12feat_log_volume":{}}
        "finding":  "IC sign flip: 0.091  +0.023. Pearson: +0.009  +0.120 (13). MAE/RMSE both improve. All 7 tickers gain in per-ticker correlation.",
        "verdict":  "ADD",
    },
    {
        "key":      "exp3_warmstart",
        "title":    "Exp 3  Warm-start: 11-feat vs 12-feat+log_volume",
        "protocol": "Partial weight transfer from production checkpoint (24/26 layers). 5 epochs, LR0.2. Tests whether log_volume benefit persists when the backbone starts from production weights.",
        "file":     DL_EXP_DIR / "warmstart_comparison.json",
        "schema":   "results_list",
        "finding":  "IC sign flip holds: 0.143  +0.030. Pearson: 0.084  +0.160. BUT calibration problem is inherited  12-feat WS predicts positive 99.9% of the time. RSI_14 bullish bias in backbone pollutes the test. AMZN/GOOG worsen (2/7 tickers). IC p=0.27 (not significant).",
        "verdict":  "CONDITIONAL",
    },
    {
        "key":      "exp4_combined",
        "title":    "Exp 4  Combined Clean-Baseline: 10-feat vs 10-feat+log_volume (warm-start)",
        "protocol": "Partial weight transfer from production checkpoint. 10-feat (no RSI_14) vs 11-feat (no RSI_14 + log_volume). Input stage force-re-initialized on both to prevent feature-substitution contamination. 5 epochs, LR0.2.",
        "file":     DL_EXP_DIR / "combined_cleanbaseline_comparison.json",
        "schema":   "results_list",
        "finding":  (
            "10-feat (no RSI_14) is the BEST model across all 4 experiments: Corr=+0.237, IC=+0.173 (p0), DirAcc=64.8%. "
            "Adding log_volume to the clean baseline reduces aggregate performance (IC: 0.1730.116), though both remain "
            "statistically significant. Per-ticker is split: AMZN (+0.53), TSLA (+0.16), NVDA (+0.10) gain; "
            "MSFT (0.79), AAPL (0.41), GOOG (0.34) worsen. "
            "Limitation: 5-epoch warm-start with LR0.2 is insufficient for proper feature-substitution evaluation. "
            "Verdict: RSI_14 removal is strongly supported. log_volume on clean baseline is inconclusive  needs full fresh training."
        ),
        "verdict":  "REMOVE",
    },
]

# Stage that each promoter recommendation targets
_REC_TARGET_STAGE = {
    "PROMOTE_TO_DL_APPROVED": "dl_approved",
    "PROMOTE_TO_SANDBOX":     "sandbox_approved",
}


#  helpers 

def load(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def flag_badge(flag: str, small: bool = False) -> str:
    colors = {
        "PASS": ("#1a7f37", "#dcfce7"),
        "WARN": ("#854d0e", "#fef9c3"),
        "FAIL": ("#9b1c1c", "#fee2e2"),
        "INFO": ("#1e3a5f", "#dbeafe"),
    }
    fg, bg = colors.get(flag, ("#374151", "#f3f4f6"))
    size = "0.75em" if small else "0.78em"
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 8px;border-radius:4px;'
        f'font-size:{size};font-weight:600;letter-spacing:0.03em">{flag}</span>'
    )


def stage_badge(stage: str) -> str:
    colors = {
        "dl_approved":      ("#065f46", "#d1fae5"),
        "sandbox_approved": ("#1e3a8a", "#dbeafe"),
        "experimental":     ("#374151", "#f3f4f6"),
        "deprecated":       ("#6b7280", "#e5e7eb"),
    }
    fg, bg = colors.get(stage, ("#374151", "#f3f4f6"))
    label = stage.replace("_", " ").upper()
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 8px;border-radius:4px;'
        f'font-size:0.75em;font-weight:700;letter-spacing:0.05em">{label}</span>'
    )


def decision_badge(decision: str) -> str:
    """Badge for the human decision outcome."""
    cfg = {
        "HELD":      ("#7c3aed", "#ede9fe", "HUMAN HOLD"),
        "PROMOTED":  ("#065f46", "#d1fae5", "PROMOTED"),
        "DEMOTED":   ("#9b1c1c", "#fee2e2", "DEMOTED"),
        "FOLLOWED":  ("#374151", "#f3f4f6", "ACCEPTED"),
        "PENDING":   ("#64748b", "#f1f5f9", "PENDING"),
    }
    fg, bg, label = cfg.get(decision, ("#374151", "#f3f4f6", decision))
    return (
        f'<span style="background:{bg};color:{fg};padding:3px 10px;border-radius:4px;'
        f'font-size:0.78em;font-weight:700;letter-spacing:0.06em;border:1px solid {bg}">'
        f'{label}</span>'
    )


def infer_decision(sc: dict | None, registry_features: dict) -> str:
    """Compare promoter recommendation vs current registry stage."""
    if not sc:
        return "PENDING"
    fname   = sc.get("feature_name", "")
    rec     = sc.get("recommendation", "")
    current = registry_features.get(fname, {}).get("stage", sc.get("current_stage", ""))
    target  = _REC_TARGET_STAGE.get(rec)

    if target is None:
        # HOLD or DEMOTE recommendation  if stage is lower, DEMOTED; else FOLLOWED
        if rec == "DEMOTE":
            return "DEMOTED" if current != sc.get("current_stage", current) else "FOLLOWED"
        return "FOLLOWED"

    if current == target:
        return "PROMOTED"
    # Promoter said promote but stage hasn't moved
    return "HELD"


def score_bar(score: int, max_score: int = 100) -> str:
    pct   = int(score / max_score * 100)
    color = "#1a7f37" if pct >= 75 else "#854d0e" if pct >= 60 else "#9b1c1c"
    return (
        f'<div style="display:flex;align-items:center;gap:8px">'
        f'<div style="flex:1;background:#e5e7eb;border-radius:4px;height:8px">'
        f'<div style="width:{pct}%;background:{color};border-radius:4px;height:8px"></div></div>'
        f'<span style="font-weight:700;color:{color};min-width:54px">{score}/{max_score}</span>'
        f'</div>'
    )


def th(text: str, right: bool = False) -> str:
    align = "right" if right else "left"
    return (
        f'<th style="text-align:{align};padding:8px 12px;background:#f8fafc;'
        f'border-bottom:2px solid #e2e8f0;font-size:0.78em;color:#64748b;'
        f'text-transform:uppercase;letter-spacing:0.05em;white-space:nowrap">{text}</th>'
    )


def td(content: str, mono: bool = False, right: bool = False, bg: str = "") -> str:
    align = "right" if right else "left"
    font  = "font-family:monospace;font-size:0.85em;" if mono else ""
    style_bg = f"background:{bg};" if bg else ""
    return (
        f'<td style="padding:8px 12px;border-bottom:1px solid #f1f5f9;'
        f'vertical-align:top;text-align:{align};{font}{style_bg}">{content}</td>'
    )


def section(title: str, subtitle: str = "") -> str:
    sub = f'<p style="margin:4px 0 0;font-size:0.85em;color:#64748b">{subtitle}</p>' if subtitle else ""
    return (
        f'<div style="margin:32px 0 12px">'
        f'<h2 style="margin:0;font-size:1.1em;color:#0f172a;font-weight:700;'
        f'border-left:4px solid #3b82f6;padding-left:10px">{title}</h2>{sub}</div>'
    )


def card(body: str, border_color: str = "#e2e8f0") -> str:
    return (
        f'<div style="background:#fff;border:1px solid {border_color};border-radius:8px;'
        f'padding:20px 24px;margin-bottom:16px">{body}</div>'
    )


def key_metric(label: str, value: str, flag: str = "") -> str:
    flag_colors = {"PASS": "#1a7f37", "WARN": "#854d0e", "FAIL": "#9b1c1c"}
    color = flag_colors.get(flag, "#0f172a")
    return (
        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;'
        f'padding:8px 12px;min-width:120px">'
        f'<div style="font-size:0.72em;color:#94a3b8;text-transform:uppercase;'
        f'letter-spacing:0.06em;margin-bottom:2px">{label}</div>'
        f'<div style="font-size:1em;font-weight:700;color:{color};font-family:monospace">{value}</div>'
        f'</div>'
    )


#  sections 

def build_header(registry: dict, drift: dict, n_tested: int, n_held: int) -> str:
    total    = registry.get("total_features", 0)
    approved = registry.get("dl_approved_count", 0)
    d_pass   = drift.get("drift_pass", 0)
    d_warn   = drift.get("drift_warn", 0)
    d_fail   = drift.get("drift_fail", 0)
    gen_date = registry.get("generated_date", "unknown")

    def stat(value: str, label: str, color: str = "#f8fafc") -> str:
        return (
            f'<div style="text-align:center;padding:14px 20px;flex:1">'
            f'<div style="font-size:1.8em;font-weight:700;color:{color}">{value}</div>'
            f'<div style="font-size:0.78em;color:#94a3b8;margin-top:2px;'
            f'text-transform:uppercase;letter-spacing:0.05em">{label}</div>'
            f'</div>'
        )

    def divider() -> str:
        return '<div style="width:1px;background:#334155;align-self:stretch;margin:10px 0"></div>'

    drift_color = "#fca5a5" if d_fail else "#fde68a" if d_warn else "#86efac"
    drift_val   = f"{d_pass}P&nbsp;/&nbsp;{d_warn}W&nbsp;/&nbsp;{d_fail}F"

    held_color  = "#c4b5fd" if n_held else "#94a3b8"

    return (
        f'<div style="background:#0f172a;color:#f8fafc;padding:20px 28px 0;'
        f'border-radius:8px 8px 0 0;">'
        f'<h1 style="margin:0 0 2px;font-size:1.3em;font-weight:700">'
        f'EPM Feature Pipeline</h1>'
        f'<p style="margin:0 0 16px;font-size:0.8em;color:#94a3b8">'
        f'Internal testing dashboard &nbsp;&nbsp; Generated {gen_date}</p>'
        f'<div style="display:flex;border-top:1px solid #1e293b">'
        + stat(str(total),    "Total Features")
        + divider()
        + stat(str(approved), "DL Approved", "#86efac")
        + divider()
        + stat(str(n_tested), "Tested")
        + divider()
        + stat(str(n_held),   "Human Holds", held_color)
        + divider()
        + stat(drift_val,     "Drift Pass/Warn/Fail", drift_color)
        + f'</div></div>'
        f'<div style="background:#1e293b;border-radius:0 0 8px 8px;padding:7px 28px;'
        f'font-size:0.78em;color:#94a3b8;margin-bottom:8px">'
        f'DL baseline: 11 features (production unchanged) &nbsp;&nbsp; '
        f'RSI_14 removal: promotion path prepared, pending human approval &nbsp;&nbsp; '
        f'log_volume: deferred pending cleaner baseline re-test &nbsp;&nbsp; '
        f'Validator: fully operational (statsmodels {_statsmodels_version()})'
        f'</div>'
    )


def _statsmodels_version() -> str:
    try:
        import statsmodels
        return statsmodels.__version__
    except ImportError:
        return "not installed"


def build_registry(registry: dict, scorecards: dict[str, dict]) -> str:
    by_stage    = registry.get("by_stage", {})
    stage_order = ["dl_approved", "sandbox_approved", "experimental", "deprecated"]

    # Build flat lookup: feature_name -> stage
    registry_features: dict[str, dict] = {}
    for stage, features in by_stage.items():
        for f in features:
            registry_features[f["name"]] = {"stage": stage, **f}

    rows = ""
    for stage in stage_order:
        features = by_stage.get(stage, [])
        if not features:
            continue
        for f in features:
            fname = f["name"]
            sc    = scorecards.get(fname)

            # Decision column
            decision = infer_decision(sc, registry_features)
            dec_html = decision_badge(decision) if sc else '<span style="color:#d1d5db;font-size:0.8em"></span>'

            # Score column
            if sc:
                score_html = f'<span style="font-weight:700;font-family:monospace">{sc["total_score"]}/100</span>'
            else:
                score_html = '<span style="color:#d1d5db"></span>'

            pit = (
                '<span style="color:#1a7f37">&#10003;</span>' if f.get("point_in_time")
                else '<span style="color:#f59e0b" title="PIT not confirmed">&#9888;</span>'
            )
            rows += (
                f'<tr class="reg-row" data-name="{fname.lower()}" '
                f'data-stage="{stage}" data-type="{f.get("feature_type","").lower()}">'
                + td(f'<strong style="font-family:monospace">{fname}</strong>')
                + td(stage_badge(stage))
                + td(dec_html)
                + td(score_html, mono=False)
                + td(f.get("feature_type", ""), mono=False)
                + td(str(f.get("lag_days", "")), mono=True, right=True)
                + td(pit)
                + td(f'<span style="font-size:0.78em;color:#64748b">{f.get("notes","")[:90]}</span>')
                + '</tr>'
            )

    filter_js = """
<script>
function filterReg(val) {
  val = val.toLowerCase();
  document.querySelectorAll('.reg-row').forEach(function(r) {
    var match = r.dataset.name.includes(val)
             || r.dataset.stage.includes(val)
             || r.dataset.type.includes(val)
             || r.innerText.toLowerCase().includes(val);
    r.style.display = match ? '' : 'none';
  });
}
</script>
"""
    search_box = (
        f'<div style="margin-bottom:10px">'
        f'<input type="text" placeholder="Filter by name, stage, type" '
        f'oninput="filterReg(this.value)" '
        f'style="padding:6px 12px;border:1px solid #e2e8f0;border-radius:6px;'
        f'font-size:0.88em;width:280px;outline:none;background:#f8fafc">'
        f'</div>'
    )
    table = (
        f'<table style="width:100%;border-collapse:collapse">'
        f'<thead><tr>'
        + th("Feature") + th("Stage") + th("Decision") + th("Score")
        + th("Type") + th("Lag", right=True) + th("PIT") + th("Notes")
        + '</tr></thead>'
        f'<tbody>{rows}</tbody></table>'
        + filter_js
    )
    return (
        section("Registry", f"{registry.get('total_features',0)} features  filter by name, stage, or type")
        + card(search_box + table)
    )


def build_drift(drift: dict) -> str:
    features = drift.get("features", [])
    warnings = drift.get("demotion_warnings", [])

    warn_html = ""
    if warnings:
        warn_html = (
            f'<div style="background:#fef9c3;border:1px solid #fde68a;border-radius:6px;'
            f'padding:10px 16px;margin-bottom:12px;font-size:0.85em;color:#854d0e">'
            f'<strong>Demotion warnings:</strong> {", ".join(warnings)}</div>'
        )

    # Check whether any rolling window data exists
    has_current = any(f.get("current_n", 0) > 0 for f in features)
    no_current_note = "" if has_current else (
        f'<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;'
        f'padding:8px 14px;margin-bottom:12px;font-size:0.82em;color:#64748b">'
        f'Current window columns are empty  drift monitor compares rolling 90-day window against '
        f'historical baseline. These will populate once the pipeline accumulates a full window of '
        f'post-baseline data.</div>'
    )

    rows = ""
    for f in features:
        flag   = f.get("drift_flag", "?")
        h_mean = f.get("historical_mean")
        h_std  = f.get("historical_std")
        c_mean = f.get("current_mean")
        shift  = f.get("mean_shift_z")
        notes  = "; ".join(f.get("drift_notes", [])) if f.get("drift_notes") else ""

        row_bg = ""
        if flag == "FAIL":
            row_bg = "#fff5f5"
        elif flag == "WARN":
            row_bg = "#fffbeb"

        rows += (
            f'<tr>'
            + td(f'<strong style="font-family:monospace">{f["feature"]}</strong>', bg=row_bg)
            + td(stage_badge(f.get("stage", "")), bg=row_bg)
            + td(flag_badge(flag), bg=row_bg)
            + td(f'{h_mean:.4f}' if h_mean is not None else "", mono=True, right=True, bg=row_bg)
            + td(f'{h_std:.4f}'  if h_std  is not None else "", mono=True, right=True, bg=row_bg)
            + td(f'{c_mean:.4f}' if c_mean is not None else '<span style="color:#cbd5e1"></span>', mono=True, right=True, bg=row_bg)
            + td(f'{shift:.2f}'  if shift  is not None else '<span style="color:#cbd5e1"></span>', mono=True, right=True, bg=row_bg)
            + td(f'<span style="font-size:0.8em;color:#64748b">{notes}</span>', bg=row_bg)
            + '</tr>'
        )

    table = (
        f'<table style="width:100%;border-collapse:collapse">'
        f'<thead><tr>'
        + th("Feature") + th("Stage") + th("Drift")
        + th("Hist Mean", right=True) + th("Hist Std", right=True)
        + th("Curr Mean", right=True) + th("Shift (z)", right=True)
        + th("Notes")
        + '</tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )
    return (
        section("Drift Monitor", f"Daily check  {drift.get('generated_date','?')}  {len(features)} approved features")
        + warn_html + no_current_note + card(table)
    )


def _extract_key_metrics(tests: dict) -> list[tuple[str, str, str]]:
    """Pull the most decision-relevant numbers from each test for the summary strip."""
    metrics = []
    if "ic_walkforward" in tests:
        t = tests["ic_walkforward"]
        metrics.append(("Mean IC", f'{t.get("mean_ic",0):.4f}', t.get("flag","?")))
        metrics.append(("IC Hit Rate", f'{t.get("ic_hit_rate",0):.0%}', t.get("flag","?")))
        metrics.append(("t-stat", f'{t.get("t_stat",0):.2f}', t.get("flag","?")))
    if "ablation" in tests:
        t = tests["ablation"]
        dR2 = t.get("delta_r2", 0)
        metrics.append(("R", f'{dR2:+.5f}', t.get("flag","?")))
    if "drift" in tests:
        t = tests["drift"]
        metrics.append(("KS p-val", f'{t.get("ks_pvalue",0):.4f}', t.get("flag","?")))
    if "regime_breakdown" in tests:
        t = tests["regime_breakdown"]
        metrics.append(("High-vol IC", f'{t.get("high_vol_ic",0):.4f}', t.get("flag","?")))
        metrics.append(("Low-vol IC",  f'{t.get("low_vol_ic",0):.4f}',  t.get("flag","?")))
    if "redundancy" in tests:
        t = tests["redundancy"]
        metrics.append(("Max Corr", f'{t.get("max_abs_corr",0):.3f}', t.get("flag","?")))
    return metrics


def build_test_cards(results_dir: Path, scores_dir: Path, registry_features: dict) -> str:
    result_files = sorted(glob.glob(str(results_dir / "*.json")))
    if not result_files:
        return section("Test Results", "No test results yet.")

    # Deduplicate: keep only latest file per feature
    latest: dict[str, Path] = {}
    for rf in result_files:
        tr = load(Path(rf))
        if not tr:
            continue
        fname = tr.get("feature_name", "")
        if fname not in latest or tr.get("test_date", "") > load(latest[fname]).get("test_date", ""):
            latest[fname] = Path(rf)

    html = section("Test Results", f"{len(latest)} feature(s) tested  most recent result per feature")

    for fname, rf in sorted(latest.items()):
        tr = load(rf)
        if not tr:
            continue

        test_date = tr.get("test_date", "?")
        overall   = tr.get("overall_flag", "?")
        lag       = tr.get("lag_days_applied", "?")
        tickers   = ", ".join(tr.get("ticker_list", []))
        rows_used = tr.get("panel_rows", 0)
        tests     = tr.get("tests", {})

        # Load scorecard
        sc_files = sorted(glob.glob(str(scores_dir / f"{fname}_*_scorecard.json")))
        sc       = load(Path(sc_files[-1])) if sc_files else None

        # Decision
        decision  = infer_decision(sc, registry_features)
        curr_stage = registry_features.get(fname, {}).get("stage", sc.get("current_stage", "?") if sc else "?")

        # Card border color by overall flag
        border = {"PASS": "#bbf7d0", "WARN": "#fde68a", "FAIL": "#fecaca"}.get(overall, "#e2e8f0")

        #  Decision banner 
        if sc:
            rec        = sc.get("recommendation", "?")
            rec_color  = {
                "PROMOTE_TO_DL_APPROVED": "#065f46",
                "PROMOTE_TO_SANDBOX":     "#1e3a8a",
                "HOLD":                   "#854d0e",
                "DEMOTE":                 "#9b1c1c",
            }.get(rec, "#374151")
            rec_label  = rec.replace("_", " ")
            banner_bg  = {"HELD": "#faf5ff", "PROMOTED": "#f0fdf4"}.get(decision, "#f8fafc")
            banner_bdr = {"HELD": "#ddd6fe", "PROMOTED": "#bbf7d0"}.get(decision, "#e2e8f0")

            if decision == "HELD":
                banner_text = (
                    f'Promoter recommended <strong style="color:{rec_color}">{rec_label}</strong>'
                    f' &nbsp;&nbsp; '
                    f'<strong style="color:#7c3aed">Human decision: HELD</strong>'
                    f' &nbsp;&nbsp; Current stage: {stage_badge(curr_stage)}'
                )
            elif decision == "PROMOTED":
                banner_text = (
                    f'Promoter recommended <strong style="color:{rec_color}">{rec_label}</strong>'
                    f' &nbsp;&nbsp; '
                    f'<strong style="color:#065f46">Promotion accepted</strong>'
                    f' &nbsp;&nbsp; Current stage: {stage_badge(curr_stage)}'
                )
            else:
                banner_text = (
                    f'Promoter: <strong style="color:{rec_color}">{rec_label}</strong>'
                    f' &nbsp;&nbsp; Current stage: {stage_badge(curr_stage)}'
                )

            decision_banner = (
                f'<div style="background:{banner_bg};border:1px solid {banner_bdr};'
                f'border-radius:6px;padding:9px 14px;margin-bottom:14px;font-size:0.85em;'
                f'display:flex;align-items:center;gap:10px">'
                + decision_badge(decision)
                + f'<span>{banner_text}</span></div>'
            )
        else:
            decision_banner = ""

        #  Key metrics strip 
        metrics      = _extract_key_metrics(tests)
        metrics_html = (
            f'<div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:16px">'
            + "".join(key_metric(lbl, val, flg) for lbl, val, flg in metrics)
            + "</div>"
        )

        #  Test dimension table 
        test_rows = ""
        for test_name, result in tests.items():
            flag     = result.get("flag", "?")
            note     = result.get("note", "")
            row_bg   = ""
            if flag == "FAIL":
                row_bg = "#fff5f5"
            elif flag == "WARN":
                row_bg = "#fffbeb"
            test_rows += (
                f'<tr>'
                + td(test_name.replace("_", " ").title(), bg=row_bg)
                + td(flag_badge(flag), bg=row_bg)
                + td(f'<span style="font-size:0.82em;color:#475569">{note}</span>', bg=row_bg)
                + '</tr>'
            )

        dim_table = (
            f'<table style="width:100%;border-collapse:collapse">'
            f'<thead><tr>' + th("Test") + th("Flag") + th("Detail")
            + '</tr></thead>'
            f'<tbody>{test_rows}</tbody></table>'
        )

        #  Scorecard 
        sc_html = ""
        if sc:
            total_score = sc.get("total_score", 0)
            dim_rows    = ""
            for dim, info in sc.get("dimensions", {}).items():
                dscore  = info.get("score", 0)
                dmax    = _DIM_MAX.get(dim, "?")
                dflag   = info.get("test_flag", "?")
                row_bg  = ""
                if dflag == "FAIL":
                    row_bg = "#fff5f5"
                elif dflag == "WARN":
                    row_bg = "#fffbeb"
                dim_rows += (
                    f'<tr>'
                    + td(dim.replace("_", " ").title(), bg=row_bg)
                    + td(flag_badge(dflag, small=True), bg=row_bg)
                    + td(f'<strong>{dscore}</strong>/{dmax} pts', mono=True, bg=row_bg)
                    + td(f'<span style="font-size:0.82em;color:#475569">{info.get("explanation","")}</span>', bg=row_bg)
                    + '</tr>'
                )

            sc_html = (
                f'<div style="margin-top:18px;padding-top:14px;border-top:1px solid #f1f5f9">'
                f'<div style="display:flex;align-items:center;gap:16px;margin-bottom:10px">'
                f'<span style="font-weight:700;color:#0f172a;font-size:0.9em">Scorecard</span>'
                f'<div style="flex:1">{score_bar(total_score)}</div>'
                f'</div>'
                f'<table style="width:100%;border-collapse:collapse">'
                f'<thead><tr>'
                + th("Dimension") + th("Flag") + th("Points") + th("Explanation")
                + '</tr></thead>'
                f'<tbody>{dim_rows}</tbody></table>'
                f'</div>'
            )

        card_content = (
            f'<div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:10px">'
            f'<div>'
            f'<span style="font-size:1.05em;font-weight:700;color:#0f172a;font-family:monospace">{fname}</span>'
            f'<span style="font-size:0.8em;color:#94a3b8;margin-left:10px">tested {test_date}</span>'
            f'</div>'
            + flag_badge(overall) +
            f'</div>'
            f'<div style="font-size:0.8em;color:#64748b;margin-bottom:12px">'
            f'lag={lag}d &nbsp;&nbsp; {rows_used:,} rows &nbsp;&nbsp; {tickers}'
            f'</div>'
            + decision_banner
            + metrics_html
            + dim_table + sc_html
        )
        html += card(card_content, border_color=border)

    return html


# Scorecard max points per dimension  used in display
_DIM_MAX = {
    "availability":      5,
    "predictive_lift":  20,
    "ic_stability":     10,
    "incremental_value": 20,
    "leakage_free":     15,
    "drift_resistance": 15,
    "robustness":       10,
    "non_redundant":    10,
}


def build_queue(queue: dict) -> str:
    items = queue.get("queue", [])
    count = queue.get("features_pending_review", 0)

    if not items:
        body = (
            f'<p style="margin:0;color:#64748b;font-size:0.9em">'
            f'No features pending review. Run '
            f'<code style="background:#f1f5f9;padding:1px 5px;border-radius:3px">'
            f'feature_promoter.py --feature NAME</code> after testing to populate this queue.</p>'
        )
        return section("Promotion Queue", "0 pending") + card(body)

    rows = ""
    for item in items:
        rows += (
            f'<tr>'
            + td(f'<strong style="font-family:monospace">{item.get("feature","?")}</strong>')
            + td(stage_badge(item.get("current_stage", "")))
            + td(score_bar(item.get("score", 0)))
            + td(decision_badge("PENDING"))
            + td(f'<span style="font-size:0.82em;color:#475569">{item.get("reason","")}</span>')
            + '</tr>'
        )
    table = (
        f'<table style="width:100%;border-collapse:collapse">'
        f'<thead><tr>'
        + th("Feature") + th("Stage") + th("Score") + th("Status") + th("Reason")
        + '</tr></thead>'
        f'<tbody>{rows}</tbody></table>'
    )
    return section("Promotion Queue", f"{count} pending decision") + card(table)


#  DL experiments 

def _dl_metric_row(label: str, val_a, val_b, higher_better: bool | None = True) -> str:
    """Single metric comparison row  green/red delta colouring."""
    def fmt(v) -> str:
        if v is None:
            return '<span style="color:#cbd5e1"></span>'
        if isinstance(v, float):
            return f'{v:.5f}'
        return str(v)

    delta_html = ""
    if isinstance(val_a, float) and isinstance(val_b, float):
        delta = val_b - val_a
        if higher_better is True:
            color = "#1a7f37" if delta > 0 else "#9b1c1c"
            sign  = "+" if delta > 0 else ""
        elif higher_better is False:
            color = "#1a7f37" if delta < 0 else "#9b1c1c"
            sign  = "+" if delta > 0 else ""
        else:
            color = "#374151"
            sign  = "+" if delta > 0 else ""
        delta_html = (
            f'<span style="font-family:monospace;font-weight:700;color:{color}">'
            f'{sign}{delta:+.5f}</span>'
        )

    return (
        f'<tr>'
        + td(label)
        + td(fmt(val_a), mono=True, right=True)
        + td(fmt(val_b), mono=True, right=True)
        + td(delta_html, right=True)
        + '</tr>'
    )


def _parse_dl_exp(exp_cfg: dict) -> tuple[list[dict], str]:
    """Parse a DL experiment file into a list of variant dicts and a test_cutoff string.

    Returns (variants, cutoff_str).  Each variant dict has normalised keys:
      label, mae, rmse, correlation, ic_spearman, directional_accuracy,
      pred_std, pct_neg_predictions
    """
    path = exp_cfg["file"]
    schema = exp_cfg["schema"]
    if not path.exists():
        return [], "file missing"

    raw = load(path)
    if not raw:
        return [], "empty"

    cutoff = raw.get("test_cutoff", "?") if isinstance(raw, dict) else "?"

    if schema == "results_list":
        results = raw.get("results", [])
        variants = []
        for r in results:
            variants.append({
                "label":                r.get("label", r.get("variant", "?")),
                "n_features":           r.get("n_features"),
                "mae":                  r.get("mae"),
                "rmse":                 r.get("rmse"),
                "correlation":          r.get("correlation"),
                "ic_spearman":          r.get("ic_spearman"),
                "ic_pvalue":            r.get("ic_pvalue"),
                "directional_accuracy": r.get("directional_accuracy"),
                "pred_std":             r.get("pred_std"),
                "pct_neg_predictions":  r.get("pct_neg_predictions"),
                "per_ticker":           r.get("per_ticker", {}),
            })
        return variants, cutoff

    if schema == "flat_dict":
        variants = []
        for k, v in raw.items():
            if not isinstance(v, dict):
                continue
            variants.append({
                "label":                v.get("label", k),
                "n_features":           v.get("n_features"),
                "mae":                  v.get("mae"),
                "rmse":                 v.get("rmse"),
                "correlation":          v.get("corr") or v.get("correlation"),
                "ic_spearman":          v.get("ic") or v.get("ic_spearman"),
                "ic_pvalue":            v.get("ic_pvalue"),
                "directional_accuracy": v.get("dir_acc") or v.get("directional_accuracy"),
                "pred_std":             v.get("pred_std"),
                "pct_neg_predictions":  v.get("pct_neg_pred") or v.get("pct_neg_predictions"),
                "per_ticker":           v.get("per_ticker", {}),
            })
        return variants, cutoff

    return [], "unknown schema"


def build_dl_experiments() -> str:
    """Render the DL Experiment Results section for all four experiments."""
    verdict_cfg = {
        "REMOVE":      ("#9b1c1c", "#fee2e2", "REMOVE"),
        "ADD":         ("#065f46", "#d1fae5", "ADD"),
        "CONDITIONAL": ("#854d0e", "#fef9c3", "CONDITIONAL"),
        "PENDING":     ("#64748b", "#f1f5f9", "PENDING"),
        "PASS":        ("#065f46", "#d1fae5", "PASS"),
        "FAIL":        ("#9b1c1c", "#fee2e2", "FAIL"),
    }

    def verdict_badge(v: str) -> str:
        fg, bg, label = verdict_cfg.get(v, ("#374151", "#f8fafc", v))
        return (
            f'<span style="background:{bg};color:{fg};padding:3px 10px;border-radius:4px;'
            f'font-size:0.78em;font-weight:700;letter-spacing:0.06em">{label}</span>'
        )

    html = section(
        "DL Experiment Results",
        "Bounded experiments  production checkpoint never modified. Results inform promotion decisions only."
    )

    for exp in DL_EXPS:
        variants, cutoff = _parse_dl_exp(exp)
        has_data = len(variants) >= 2

        verdict  = exp["verdict"]
        finding  = exp["finding"]
        protocol = exp["protocol"]

        vfg, vbg, _ = verdict_cfg.get(verdict, ("#374151", "#f8fafc", verdict))
        border = {"REMOVE": "#fecaca", "ADD": "#bbf7d0", "CONDITIONAL": "#fde68a",
                  "PENDING": "#e2e8f0"}.get(verdict, "#e2e8f0")

        #  header row 
        cutoff_note = f'test cutoff: {cutoff}' if has_data else 'not yet run'
        card_header = (
            f'<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">'
            f'<span style="font-size:1.0em;font-weight:700;color:#0f172a">{exp["title"]}</span>'
            + verdict_badge(verdict) +
            f'</div>'
            f'<div style="font-size:0.78em;color:#64748b;margin-bottom:10px">'
            f'{protocol} &nbsp;&nbsp; {cutoff_note}</div>'
        )

        #  finding callout 
        if finding:
            callout_bg  = vbg
            callout_bdr = border
            finding_html = (
                f'<div style="background:{callout_bg};border-left:3px solid {vfg};'
                f'border-radius:0 6px 6px 0;padding:8px 14px;margin-bottom:12px;'
                f'font-size:0.83em;color:{vfg}">'
                f'<strong>Finding:</strong> {finding}</div>'
            )
        elif verdict == "PENDING":
            finding_html = (
                f'<div style="background:#f8fafc;border:1px dashed #cbd5e1;border-radius:6px;'
                f'padding:8px 14px;margin-bottom:12px;font-size:0.83em;color:#94a3b8">'
                f'Experiment not yet run  results will appear here after training completes.</div>'
            )
        else:
            finding_html = ""

        #  comparison table 
        if has_data:
            a, b = variants[0], variants[1]
            metric_rows = (
                _dl_metric_row("MAE",                   a["mae"],                  b["mae"],                  higher_better=False)
                + _dl_metric_row("RMSE",                a["rmse"],                 b["rmse"],                 higher_better=False)
                + _dl_metric_row("Pearson Correlation",  a["correlation"],          b["correlation"],          higher_better=True)
                + _dl_metric_row("IC (Spearman)",        a["ic_spearman"],          b["ic_spearman"],          higher_better=True)
                + _dl_metric_row("IC p-value",           a["ic_pvalue"],            b["ic_pvalue"],            higher_better=False)
                + _dl_metric_row("Pred StdDev",          a["pred_std"],             b["pred_std"],             higher_better=None)
                + _dl_metric_row("Pct Neg Predictions",  a["pct_neg_predictions"],  b["pct_neg_predictions"],  higher_better=None)
                + _dl_metric_row("Directional Accuracy", a["directional_accuracy"], b["directional_accuracy"], higher_better=None)
            )
            lbl_a = a["label"][:32]
            lbl_b = b["label"][:32]
            comp_table = (
                f'<table style="width:100%;border-collapse:collapse">'
                f'<thead><tr>'
                + th("Metric") + th(lbl_a, right=True) + th(lbl_b, right=True) + th("Delta (BA)", right=True)
                + '</tr></thead>'
                f'<tbody>{metric_rows}</tbody></table>'
            )

            # per-ticker correlation if available
            pt_a = a.get("per_ticker", {})
            pt_b = b.get("per_ticker", {})
            if pt_a and pt_b:
                tickers = sorted(set(list(pt_a.keys()) + list(pt_b.keys())))
                pt_rows = ""
                for tkr in tickers:
                    ca = pt_a.get(tkr, {}).get("corr")
                    cb = pt_b.get(tkr, {}).get("corr")
                    if ca is None:
                        ca = pt_a.get(tkr, {}).get("correlation")
                    if cb is None:
                        cb = pt_b.get(tkr, {}).get("correlation")
                    pt_rows += _dl_metric_row(tkr, ca, cb, higher_better=True)
                comp_table += (
                    f'<div style="margin-top:14px;padding-top:10px;border-top:1px solid #f1f5f9">'
                    f'<div style="font-size:0.78em;font-weight:700;color:#64748b;'
                    f'text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px">'
                    f'Per-ticker Pearson Correlation</div>'
                    f'<table style="width:100%;border-collapse:collapse">'
                    f'<thead><tr>'
                    + th("Ticker") + th(lbl_a, right=True) + th(lbl_b, right=True) + th("Delta", right=True)
                    + '</tr></thead>'
                    f'<tbody>{pt_rows}</tbody></table>'
                    f'</div>'
                )
        else:
            comp_table = ""

        card_body = card_header + finding_html + comp_table
        html += card(card_body, border_color=border)

    return html


#  main 

def main() -> None:
    registry = load(STORE / "dashboard" / "registry_status.json") or {}
    drift    = load(STORE / "dashboard" / "drift_status.json") or {}
    queue    = load(STORE / "dashboard" / "promotion_queue.json") or {}

    # Build feature name  stage lookup from registry
    registry_features: dict[str, dict] = {}
    for stage, features in registry.get("by_stage", {}).items():
        for f in features:
            registry_features[f["name"]] = {"stage": stage, **f}

    # Load all scorecards  keep latest per feature
    scorecards: dict[str, dict] = {}
    for sc_file in sorted(glob.glob(str(STORE / "scoring" / "results" / "*_scorecard.json"))):
        sc = load(Path(sc_file))
        if sc:
            fname = sc.get("feature_name", "")
            if fname not in scorecards or sc.get("scorecard_date","") >= scorecards[fname].get("scorecard_date",""):
                scorecards[fname] = sc

    # Count tested / held
    result_files = list((STORE / "testing" / "results").glob("*.json"))
    tested_names: set[str] = set()
    for rf in result_files:
        tr = load(rf)
        if tr:
            tested_names.add(tr.get("feature_name", ""))
    n_tested = len(tested_names)
    n_held   = sum(
        1 for fname, sc in scorecards.items()
        if infer_decision(sc, registry_features) == "HELD"
    )

    body = (
        build_header(registry, drift, n_tested, n_held)
        + build_dl_experiments()
        + build_registry(registry, scorecards)
        + build_drift(drift)
        + build_queue(queue)
        + build_test_cards(
            STORE / "testing" / "results",
            STORE / "scoring" / "results",
            registry_features,
        )
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EPM Feature Dashboard  Internal</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #f1f5f9;
    color: #1e293b;
    margin: 0;
    padding: 24px;
    font-size: 14px;
    line-height: 1.5;
  }}
  .container {{ max-width: 1140px; margin: 0 auto; }}
  table {{ font-size: 0.9em; width: 100%; }}
  tr:last-child td {{ border-bottom: none !important; }}
  tr:hover td {{ background: #f8fafc !important; }}
  input[type=text]:focus {{
    border-color: #93c5fd !important;
    background: #fff !important;
    box-shadow: 0 0 0 3px #dbeafe;
  }}
</style>
</head>
<body>
<div class="container">
{body}
<p style="margin-top:40px;font-size:0.75em;color:#94a3b8;text-align:center">
  Internal use only &nbsp;&nbsp; EPM Market Intelligence &nbsp;&nbsp;
  Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}
</p>
</div>
</body>
</html>"""

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"[feature_dashboard_gen] Written: {OUT}")
    print(f"  Registry : {registry.get('total_features', 0)} features")
    print(f"  Tested   : {n_tested} / Held: {n_held}")
    print(f"  Drift    : {drift.get('drift_pass', 0)}P / {drift.get('drift_warn', 0)}W / {drift.get('drift_fail', 0)}F")
    print(f"  statsmodels: {_statsmodels_version()}")


if __name__ == "__main__":
    main()
