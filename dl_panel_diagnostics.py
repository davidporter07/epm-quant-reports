"""Decision-date panel diagnostics for DL shadow and paper runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _date_key(value: object) -> str:
    return pd.Timestamp(value).date().isoformat()


def _feature_gap_columns(window: pd.DataFrame, feature_cols: list[str]) -> list[str]:
    gaps: list[str] = []
    for col in feature_cols:
        if col not in window.columns:
            gaps.append(col)
            continue
        values = pd.to_numeric(window[col], errors="coerce").to_numpy(dtype=np.float64)
        if not np.isfinite(values).all():
            gaps.append(col)
    return gaps


def decision_date_sequence_diagnostics(
    panel: pd.DataFrame,
    decision_date: pd.Timestamp,
    feature_cols: list[str],
    seq_len: int,
    expected_universe_count: int | None = None,
    expected_tickers: list[str] | None = None,
) -> dict[str, Any]:
    """Return sequence-readiness diagnostics for one decision date.

    The check mirrors the condition that matters for rank-head prediction: every
    expected ticker must have a row on the decision date and a fully finite
    feature window ending on that date.
    """
    if panel.empty:
        raise ValueError("Cannot diagnose an empty panel.")
    rows = panel.copy()
    rows["Date"] = pd.to_datetime(rows["Date"], errors="coerce")
    rows["Ticker"] = rows["Ticker"].astype(str).str.upper().str.strip()
    rows = rows.dropna(subset=["Date", "Ticker"])
    decision = pd.Timestamp(decision_date)
    decision_key = _date_key(decision)
    tickers = (
        [str(t).upper().strip() for t in expected_tickers if str(t).strip()]
        if expected_tickers is not None
        else sorted(rows["Ticker"].dropna().unique().tolist())
    )
    expected_count = int(expected_universe_count or len(tickers))

    per_ticker: list[dict[str, Any]] = []
    eligible: list[str] = []
    for ticker in tickers:
        g = rows[(rows["Ticker"].eq(ticker)) & (rows["Date"] <= decision)].sort_values("Date")
        if g.empty:
            per_ticker.append({"ticker": ticker, "status": "missing_history", "gap_columns": []})
            continue
        latest = pd.Timestamp(g["Date"].iloc[-1])
        if _date_key(latest) != decision_key:
            per_ticker.append(
                {
                    "ticker": ticker,
                    "status": "missing_decision_row",
                    "latest_date": _date_key(latest),
                    "gap_columns": [],
                }
            )
            continue
        if len(g) < int(seq_len):
            per_ticker.append(
                {
                    "ticker": ticker,
                    "status": "insufficient_history",
                    "rows": int(len(g)),
                    "required_rows": int(seq_len),
                    "gap_columns": [],
                }
            )
            continue
        window = g.tail(int(seq_len))
        gap_cols = _feature_gap_columns(window, feature_cols)
        if gap_cols:
            per_ticker.append(
                {
                    "ticker": ticker,
                    "status": "feature_gaps",
                    "gap_columns": gap_cols,
                    "gap_count": int(len(gap_cols)),
                }
            )
            continue
        eligible.append(ticker)
        per_ticker.append({"ticker": ticker, "status": "ok", "gap_columns": []})

    status_counts = pd.Series([row["status"] for row in per_ticker]).value_counts().to_dict()
    failed = [row for row in per_ticker if row["status"] != "ok"]
    passed = int(len(eligible)) >= expected_count and not failed
    return {
        "decision_date": decision_key,
        "seq_len": int(seq_len),
        "feature_count": int(len(feature_cols)),
        "expected_universe_count": expected_count,
        "observed_decision_rows": int(rows[rows["Date"].eq(decision)]["Ticker"].nunique()),
        "eligible_universe_count": int(len(eligible)),
        "eligible_tickers": eligible,
        "missing_tickers": [row["ticker"] for row in failed],
        "status_counts": {str(k): int(v) for k, v in status_counts.items()},
        "passed": bool(passed),
        "failures": failed,
    }


def write_panel_diagnostics(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def format_panel_gate_failure(diagnostics: dict[str, Any]) -> str:
    failures = diagnostics.get("failures") or []
    sample = []
    for row in failures[:8]:
        gaps = row.get("gap_columns") or []
        suffix = f" ({', '.join(gaps[:5])})" if gaps else ""
        sample.append(f"{row.get('ticker')}:{row.get('status')}{suffix}")
    return (
        "Decision-date panel gate failed: "
        f"{diagnostics.get('eligible_universe_count')}/"
        f"{diagnostics.get('expected_universe_count')} eligible on "
        f"{diagnostics.get('decision_date')}; "
        f"sample failures: {', '.join(sample)}"
    )


def assert_decision_date_panel(
    panel: pd.DataFrame,
    decision_date: pd.Timestamp,
    feature_cols: list[str],
    seq_len: int,
    expected_universe_count: int | None,
    output_path: Path | None = None,
    allow_gaps: bool = False,
) -> dict[str, Any]:
    diagnostics = decision_date_sequence_diagnostics(
        panel=panel,
        decision_date=decision_date,
        feature_cols=feature_cols,
        seq_len=seq_len,
        expected_universe_count=expected_universe_count,
    )
    if output_path is not None:
        write_panel_diagnostics(output_path, diagnostics)
    if not allow_gaps and not diagnostics["passed"]:
        raise RuntimeError(format_panel_gate_failure(diagnostics))
    return diagnostics
