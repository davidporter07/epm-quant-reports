from __future__ import annotations

import os
from datetime import datetime

import numpy as np
import pandas as pd

DATA_DIR = "data"
PERFORMANCE_PATH = os.path.join(DATA_DIR, "model_performance.csv")
RANKINGS_PATH = os.path.join(DATA_DIR, "model_rankings.csv")
WINNERS_PATH = os.path.join(DATA_DIR, "model_winners.csv")
CONSENSUS_PATH = os.path.join(DATA_DIR, "consensus_forecasts.csv")
AGREEMENT_PATH = os.path.join(DATA_DIR, "model_agreement.csv")
CONFIDENCE_PATH = os.path.join(DATA_DIR, "forecast_confidence.csv")
REPORT_SUMMARY_PATH = os.path.join(DATA_DIR, "report_forecast_summary.csv")

MAG7 = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOG", "META", "TSLA"]

BACKTEST_FILES = {
    "Linear": os.path.join(DATA_DIR, "linear_backtest_results.csv"),
    "ML": os.path.join(DATA_DIR, "ml_backtest_results.csv"),
    "ARIMAX": os.path.join(DATA_DIR, "arimax_backtest_results.csv"),
}

CURRENT_FORECAST_FILES = {
    # Model names here MUST match the Model column in model_leaderboard_by_ticker.csv so the
    # walk-forward skill (RMSE/Corr/Directional) lines up per model.
    "DeepLearning": (os.path.join(DATA_DIR, "dl_forecasts.csv"), "DL Forecast (%)"),
    "Fama-French": (os.path.join(DATA_DIR, "fama_french_forecasts.csv"), "FF Forecast (%)"),
    "Institutional": (os.path.join(DATA_DIR, "institutional_forecasts.csv"), "Institutional Forecast (%)"),
    "QuantConnect": (os.path.join(DATA_DIR, "quantconnect_forecasts.csv"), "QuantConnect Forecast (%)"),
    "Linear": (os.path.join(DATA_DIR, "linear_forecasts.csv"), "Linear Model Forecast (%)"),
    "ML": (os.path.join(DATA_DIR, "ml_forecasts.csv"), "ML Forecast (%)"),
    "ARIMAX": (os.path.join(DATA_DIR, "arimax_forecasts.csv"), "ARIMAX Forecast (%)"),
}

# Single source of truth for model skill: the same walk-forward leaderboard the forecasting
# page shows (model_leaderboard.py -> model_leaderboard_by_ticker.csv). Using it here keeps the
# consensus, the page "winner", and the report summary from disagreeing about which model is best.
LEADERBOARD_PATH = os.path.join(DATA_DIR, "model_leaderboard_by_ticker.csv")

# A model with no directional edge (anti-correlated, or sub-coin-flip direction) over a
# meaningful sample is down-weighted to this fraction of its inverse-RMSE weight in the
# consensus — floored, never removed, so every model still contributes and stays in the suite.
SKILL_FLOOR = 0.15
# Require at least this many matured observations before we trust (and act on) a skill estimate.
MIN_SKILL_N = 8


def _safe_float(v):
    try:
        f = float(v)
        return None if (f != f) else f   # drop NaN
    except Exception:
        return None


def load_leaderboard_skill(path: str = LEADERBOARD_PATH) -> dict:
    """Per-(ticker, model) walk-forward skill from the page's leaderboard.

    Returns {(TICKER, Model): {rmse, corr, dir, dir_no, mae, n, rank}}; empty when the file is
    missing/unreadable so callers fall back to the legacy behaviour. Rank is recomputed by
    lowest MAE (RMSE tiebreak) to mirror the page exactly.
    """
    out: dict = {}
    if not os.path.exists(path):
        return out
    try:
        lb = pd.read_csv(path)
    except Exception:
        return out
    if lb.empty or "Ticker" not in lb.columns or "Model" not in lb.columns or "MAE" not in lb.columns:
        return out
    # The leaderboard writes "FamaFrench"; the consensus/current-forecast layer uses
    # "Fama-French". Normalize so skill keys line up with current["Model"] (every other
    # model name already matches exactly).
    lb_name_aliases = {"FamaFrench": "Fama-French"}
    lb = lb.sort_values(["Ticker", "MAE", "RMSE"]).copy()
    lb["__rank"] = lb.groupby("Ticker").cumcount() + 1
    for _, r in lb.iterrows():
        raw_model = str(r["Model"]).strip()
        key = (str(r["Ticker"]).upper().strip(), lb_name_aliases.get(raw_model, raw_model))
        out[key] = {
            "rmse": _safe_float(r.get("RMSE")),
            "corr": _safe_float(r.get("Corr")),
            "dir": _safe_float(r.get("Directional_Accuracy")),
            "dir_no": _safe_float(r.get("Directional_Accuracy_NO")),
            "mae": _safe_float(r.get("MAE")),
            "n": _safe_float(r.get("N")),
            "rank": int(r["__rank"]),
        }
    return out


def _is_unskilled(sk: dict) -> bool:
    """True when a model shows no directional edge over a trustworthy sample: anti-correlated
    (Corr <= 0) OR sub-coin-flip directional accuracy. Gated on MIN_SKILL_N so an unproven model
    is treated as neutral, not punished."""
    if not sk or not sk.get("n") or sk["n"] < MIN_SKILL_N:
        return False
    corr, d = sk.get("corr"), sk.get("dir")
    return (corr is not None and corr <= 0) or (d is not None and d < 0.5)


def load_backtests() -> pd.DataFrame:
    frames = []
    for model, path in BACKTEST_FILES.items():
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        if df.empty:
            continue
        df["Model"] = model
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["Date", "Ticker", "Model", "Predicted_Return", "Actual_Return", "Error", "Absolute_Error", "Squared_Error", "Direction_Correct"])
    perf = pd.concat(frames, ignore_index=True)
    for col in ["Predicted_Return", "Actual_Return", "Error", "Absolute_Error", "Squared_Error"]:
        perf[col] = pd.to_numeric(perf[col], errors="coerce")
    perf["Date"] = pd.to_datetime(perf["Date"], errors="coerce")
    perf["Ticker"] = perf["Ticker"].astype(str).str.upper().str.strip()
    perf["Direction_Correct"] = pd.to_numeric(perf["Direction_Correct"], errors="coerce")
    perf = perf.dropna(subset=["Date", "Ticker", "Model", "Predicted_Return", "Actual_Return"])
    return perf


def compute_rankings(perf: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if perf.empty:
        return pd.DataFrame(columns=[
            "Ticker", "Model", "Observations", "MAE", "RMSE", "Directional_Accuracy", "Correlation",
            "Mean_Predicted_Return", "Mean_Actual_Return", "Recent_MAE", "Recent_Directional_Accuracy",
            "Composite_Score", "Rank"
        ])

    for (ticker, model), g in perf.groupby(["Ticker", "Model"]):
        g = g.sort_values("Date")
        recent = g.tail(min(5, len(g)))
        if len(g) >= 2 and g["Predicted_Return"].nunique() > 1 and g["Actual_Return"].nunique() > 1:
            corr = g["Predicted_Return"].corr(g["Actual_Return"])
        else:
            corr = np.nan
        rows.append({
            "Ticker": ticker,
            "Model": model,
            "Observations": len(g),
            "MAE": float(g["Absolute_Error"].mean()),
            "RMSE": float(np.sqrt(g["Squared_Error"].mean())),
            "Directional_Accuracy": float(g["Direction_Correct"].mean()),
            "Correlation": float(corr) if pd.notna(corr) else np.nan,
            "Mean_Predicted_Return": float(g["Predicted_Return"].mean()),
            "Mean_Actual_Return": float(g["Actual_Return"].mean()),
            "Recent_MAE": float(recent["Absolute_Error"].mean()),
            "Recent_Directional_Accuracy": float(recent["Direction_Correct"].mean()),
        })
    ranks = pd.DataFrame(rows)
    if ranks.empty:
        return ranks

    out_parts = []
    for ticker, grp in ranks.groupby("Ticker"):
        grp = grp.copy()
        grp["RMSE_rank"] = grp["RMSE"].rank(method="min", ascending=True)
        grp["MAE_rank"] = grp["MAE"].rank(method="min", ascending=True)
        grp["Directional_rank"] = grp["Directional_Accuracy"].rank(method="min", ascending=False)
        grp["Correlation_rank"] = grp["Correlation"].rank(method="min", ascending=False, na_option="bottom")
        grp["Recent_rank"] = (0.5 * grp["Recent_MAE"].rank(method="min", ascending=True) +
                              0.5 * grp["Recent_Directional_Accuracy"].rank(method="min", ascending=False))
        grp["Composite_Score"] = (
            0.30 * grp["RMSE_rank"]
            + 0.25 * grp["MAE_rank"]
            + 0.25 * grp["Directional_rank"]
            + 0.10 * grp["Correlation_rank"]
            + 0.10 * grp["Recent_rank"]
        )
        grp["Rank"] = grp["Composite_Score"].rank(method="min", ascending=True)
        out_parts.append(grp)
    return pd.concat(out_parts, ignore_index=True)


def load_current_forecasts() -> pd.DataFrame:
    rows = []
    run_date = datetime.today().date().isoformat()
    for model, (path, value_col) in CURRENT_FORECAST_FILES.items():
        if not os.path.exists(path):
            continue
        df = pd.read_csv(path)
        if df.empty or value_col not in df.columns:
            continue
        for _, row in df.iterrows():
            ticker = str(row.get("Ticker", "")).upper().strip()
            if ticker not in MAG7:
                continue
            val = pd.to_numeric(row[value_col], errors="coerce")
            if pd.isna(val):
                continue
            as_decimal = float(val) / 100.0
            rows.append({
                "Date": str(row.get("Date", run_date)) if pd.notna(row.get("Date", run_date)) else run_date,
                "Ticker": ticker,
                "Model": model,
                "Forecast_Return": as_decimal,
            })
    return pd.DataFrame(rows)


def pick_winners(rankings: pd.DataFrame, current: pd.DataFrame, skill: dict | None = None) -> pd.DataFrame:
    """Winning model per ticker = the leaderboard's rank-1 model that has a current forecast
    (identical to the page), with its skill metrics. Falls back to the legacy composite ranking
    only when the leaderboard is unavailable, so the report and the page never crown different
    models."""
    if skill is None:
        skill = load_leaderboard_skill()
    rows = []
    for ticker in MAG7:
        cur_t = current[current["Ticker"] == ticker]
        lb_ranked = sorted(
            ((m, sk) for (tk, m), sk in skill.items() if tk == ticker and sk.get("rank")),
            key=lambda kv: kv[1]["rank"],
        )
        chosen = next(((m, sk) for m, sk in lb_ranked if not cur_t[cur_t["Model"] == m].empty), None)
        if chosen is not None:
            m, sk = chosen
            sub = cur_t[cur_t["Model"] == m]
            rows.append({
                "Date": datetime.today().date().isoformat(),
                "Ticker": ticker,
                "Winning_Model": m,
                "Winning_Forecast": sub["Forecast_Return"].iloc[-1] if not sub.empty else np.nan,
                "Composite_Score": np.nan,
                "MAE": sk.get("mae"),
                "RMSE": sk.get("rmse"),
                "Directional_Accuracy": sk.get("dir"),
                "Correlation": sk.get("corr"),
            })
            continue
        # Fallback: legacy composite ranking (leaderboard absent / model not matured yet)
        rk = rankings[rankings["Ticker"] == ticker].sort_values(["Rank", "Composite_Score"])
        if rk.empty:
            continue
        top = rk.iloc[0]
        cur = current[(current["Ticker"] == ticker) & (current["Model"] == top["Model"])]
        forecast = cur["Forecast_Return"].iloc[-1] if not cur.empty else np.nan
        rows.append({
            "Date": datetime.today().date().isoformat(),
            "Ticker": ticker,
            "Winning_Model": top["Model"],
            "Winning_Forecast": forecast,
            "Composite_Score": top["Composite_Score"],
            "MAE": top["MAE"],
            "RMSE": top["RMSE"],
            "Directional_Accuracy": top["Directional_Accuracy"],
            "Correlation": top["Correlation"],
        })
    return pd.DataFrame(rows)


def build_consensus(current: pd.DataFrame, rankings: pd.DataFrame, skill: dict | None = None) -> pd.DataFrame:
    """Skill-gated inverse-RMSE consensus.

    Each model is weighted by 1/RMSE from the walk-forward leaderboard, then a directional-skill
    gate floors (does NOT remove) any model with no edge — anti-correlated or sub-coin-flip — to
    SKILL_FLOOR of its weight, so a reliably wrong-signed model can no longer steer the consensus
    while every model still contributes. Models without a trustworthy leaderboard entry keep a
    neutral fallback weight (unproven, not penalised). Top_Model is the leaderboard's rank-1 for
    the ticker, so the consensus, the page, and the report all name the same best model.
    """
    if skill is None:
        skill = load_leaderboard_skill()
    rows = []
    for ticker in MAG7:
        cur = current[current["Ticker"] == ticker].copy()
        if cur.empty:
            continue
        simple = cur["Forecast_Return"].mean()

        # Legacy backtest RMSE (Linear/ML/ARIMAX) as a fallback base weight when a model has no
        # leaderboard entry yet; the leaderboard is the primary source below.
        ranked = rankings[rankings["Ticker"] == ticker].copy()
        legacy_rmse = {}
        if not ranked.empty:
            ranked = ranked[ranked["Observations"] >= 5].copy()
            for _, rr in ranked.iterrows():
                legacy_rmse[rr["Model"]] = _safe_float(rr["RMSE"])
        lb_weights = [1.0 / sk["rmse"] for (tk, _m), sk in skill.items()
                      if tk == ticker and sk.get("rmse") and sk["rmse"] > 0]
        median_lb_weight = float(np.median(lb_weights)) if lb_weights else np.nan
        fallback_weight = median_lb_weight * 0.5 if pd.notna(median_lb_weight) and median_lb_weight > 0 else 1.0

        def _weight_for(model: str) -> float:
            sk = skill.get((ticker, model))
            rmse = sk.get("rmse") if sk else None
            if rmse is None or rmse <= 0:
                rmse = legacy_rmse.get(model)
            if rmse is None or rmse <= 0:
                return fallback_weight                      # unproven model — neutral weight
            w = 1.0 / rmse
            if _is_unskilled(sk):
                w *= SKILL_FLOOR                            # no directional edge — floored, not dropped
            return w

        cur["Weight"] = cur["Model"].map(_weight_for)
        weighted = np.average(cur["Forecast_Return"], weights=cur["Weight"]) if cur["Weight"].sum() > 0 else simple

        # Top model = leaderboard rank-1 (same as the page); fall back to the composite ranking.
        top_model, top_forecast = None, np.nan
        lb_ranked = sorted(
            ((m, sk) for (tk, m), sk in skill.items() if tk == ticker and sk.get("rank")),
            key=lambda kv: kv[1]["rank"],
        )
        for m, _sk in lb_ranked:
            sub = cur[cur["Model"] == m]
            if not sub.empty:
                top_model, top_forecast = m, sub["Forecast_Return"].iloc[-1]
                break
        if top_model is None and not ranked.empty:
            rtop = ranked.sort_values(["Composite_Score", "RMSE"]).iloc[0]
            top_model = rtop["Model"]
            sub = cur[cur["Model"] == top_model]
            if not sub.empty:
                top_forecast = sub["Forecast_Return"].iloc[-1]

        rows.append({
            "Date": datetime.today().date().isoformat(),
            "Ticker": ticker,
            "Consensus_Forecast_Simple": simple,
            "Consensus_Forecast": weighted,
            "Consensus_Method": "SkillGatedInverseRMSE",
            "Model_Count": int(len(cur)),
            "Top_Model": top_model,
            "Top_Model_Forecast": top_forecast,
        })
    return pd.DataFrame(rows)


def compute_agreement(current: pd.DataFrame, consensus: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ticker in MAG7:
        cur = current[current["Ticker"] == ticker].copy()
        if cur.empty:
            continue
        cons = consensus[consensus["Ticker"] == ticker]
        cval = cons["Consensus_Forecast"].iloc[0] if not cons.empty else cur["Forecast_Return"].mean()
        signs = np.sign(cur["Forecast_Return"])
        consensus_sign = np.sign(cval)
        agreement_ratio = float((signs == consensus_sign).mean()) if len(signs) else np.nan
        rows.append({
            "Date": datetime.today().date().isoformat(),
            "Ticker": ticker,
            "Bullish_Model_Count": int((cur["Forecast_Return"] > 0).sum()),
            "Bearish_Model_Count": int((cur["Forecast_Return"] < 0).sum()),
            "Neutral_Model_Count": int((cur["Forecast_Return"] == 0).sum()),
            "Agreement_Ratio": agreement_ratio,
            "Forecast_StdDev": float(cur["Forecast_Return"].std(ddof=0)),
            "Forecast_Range": float(cur["Forecast_Return"].max() - cur["Forecast_Return"].min()),
        })
    return pd.DataFrame(rows)


def assign_confidence(winners: pd.DataFrame, consensus: pd.DataFrame, agreement: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ticker in MAG7:
        w = winners[winners["Ticker"] == ticker]
        c = consensus[consensus["Ticker"] == ticker]
        a = agreement[agreement["Ticker"] == ticker]
        if w.empty or c.empty or a.empty:
            continue
        w = w.iloc[0]
        c = c.iloc[0]
        a = a.iloc[0]
        sign_match = int(np.sign(w["Winning_Forecast"]) == np.sign(c["Consensus_Forecast"])) if pd.notna(w["Winning_Forecast"]) else 0
        high = (
            pd.notna(w["Composite_Score"]) and w["Composite_Score"] <= 1.75
            and a["Agreement_Ratio"] >= 0.66
            and a["Forecast_StdDev"] <= 0.05
            and sign_match == 1
        )
        medium = (
            a["Agreement_Ratio"] >= 0.50 and a["Forecast_StdDev"] <= 0.10
        )
        label = "High" if high else "Medium" if medium else "Low"
        rows.append({
            "Date": datetime.today().date().isoformat(),
            "Ticker": ticker,
            "Winning_Model": w["Winning_Model"],
            "Consensus_Forecast": c["Consensus_Forecast"],
            "Confidence_Label": label,
            "Agreement_Ratio": a["Agreement_Ratio"],
            "Forecast_StdDev": a["Forecast_StdDev"],
            "Winner_vs_Consensus_Sign_Match": sign_match,
        })
    return pd.DataFrame(rows)


def build_report_summary(winners: pd.DataFrame, consensus: pd.DataFrame, confidence: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ticker in MAG7:
        w = winners[winners["Ticker"] == ticker]
        c = consensus[consensus["Ticker"] == ticker]
        cf = confidence[confidence["Ticker"] == ticker]
        if w.empty or c.empty:
            continue
        w = w.iloc[0]
        c = c.iloc[0]
        cf_row = cf.iloc[0] if not cf.empty else {}
        rows.append({
            "Date": datetime.today().date().isoformat(),
            "Ticker": ticker,
            "Winning_Model": w["Winning_Model"],
            "Winning_Forecast": w["Winning_Forecast"],
            "Consensus_Forecast": c["Consensus_Forecast"],
            "Confidence_Label": cf_row.get("Confidence_Label", "Medium") if isinstance(cf_row, pd.Series) else "Medium",
            "Agreement_Ratio": cf_row.get("Agreement_Ratio", np.nan) if isinstance(cf_row, pd.Series) else np.nan,
            "Forecast_StdDev": cf_row.get("Forecast_StdDev", np.nan) if isinstance(cf_row, pd.Series) else np.nan,
            "Best_Model_Rank_Score": w["Composite_Score"],
        })
    return pd.DataFrame(rows)


def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    perf = load_backtests()
    perf.to_csv(PERFORMANCE_PATH, index=False)

    rankings = compute_rankings(perf)
    rankings.to_csv(RANKINGS_PATH, index=False)

    current = load_current_forecasts()
    skill = load_leaderboard_skill()   # one read, shared by winners + consensus for consistency
    winners = pick_winners(rankings, current, skill)
    winners.to_csv(WINNERS_PATH, index=False)

    consensus = build_consensus(current, rankings, skill)
    consensus.to_csv(CONSENSUS_PATH, index=False)

    agreement = compute_agreement(current, consensus)
    agreement.to_csv(AGREEMENT_PATH, index=False)

    confidence = assign_confidence(winners, consensus, agreement)
    confidence.to_csv(CONFIDENCE_PATH, index=False)

    report = build_report_summary(winners, consensus, confidence)
    report.to_csv(REPORT_SUMMARY_PATH, index=False)

    print(f" Wrote {PERFORMANCE_PATH}")
    print(f" Wrote {RANKINGS_PATH}")
    print(f" Wrote {WINNERS_PATH}")
    print(f" Wrote {CONSENSUS_PATH}")
    print(f" Wrote {AGREEMENT_PATH}")
    print(f" Wrote {CONFIDENCE_PATH}")
    print(f" Wrote {REPORT_SUMMARY_PATH}")
    if not report.empty:
        print(report)


if __name__ == "__main__":
    main()
