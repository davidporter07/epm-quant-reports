# DL Testing Journal

This journal is the durable project record for deep-learning forecast testing.
The longer `notes/handoffs/HANDOFF_dl_directional_testing_20260505.md` remains
the detailed handoff; this file is the running chronology of test decisions,
commands, results, and promotion status.

## 2026-05-06: Rank-Head Selection Direction

Decision:

- Continue with the rank-head model as a selection/ranking signal, not as a
  pure absolute sign forecaster.
- Keep production `deep_learning_model.py` untouched until repeated-window
  validation supports promotion.

Best 252-day holdout result so far:

```text
Top-3 rank-head ensemble
IC_Spearman: +0.088653
Daily_IC_Mean: +0.106585
Long-short spread: +0.078004
Spread positive rate: 75.00%
Bullish rate: 45.65%
Directional accuracy: 49.22%
```

Top-2 ensemble result:

```text
IC_Spearman: +0.121458
Daily_IC_Mean: +0.121094
Long-short spread: +0.073797
Spread positive rate: 72.66%
Bullish rate: 50.33%
Directional accuracy: 52.79%
```

Robustness checks:

```text
126-day holdout: rejected as a gate because sample count was too small and
selection spread was negative.

504-day holdout top-3 ensemble:
IC_Spearman: +0.025612
Daily_IC_Mean: +0.023158
Long-short spread: +0.039360
Spread positive rate: 56.84%
Bullish rate: 50.06%
```

Current production-readiness status:

```text
Not production-ready.
Reason: 252-day ensemble is strong, but 504-day robustness is weaker.
Next gate: walk-forward validation over non-overlapping 252-day windows.
```

Artifacts:

```text
dl_rank_head_experiment.py
dl_rank_head_ensemble_eval.py
data/experiment/rank_head_selection_objective_scaler_5seed.json
data/experiment/rank_head_selection_objective_ensemble_top3.json
data/experiment/rank_head_selection_objective_ensemble_top2.json
data/experiment/rank_head_selection_objective_ensemble_top3_val504.json
```

## 2026-05-06: Walk-Forward Rank-Head Ensemble Gate

Purpose:

- Test whether the rank-head ensemble survives multiple non-overlapping
  252-trading-day validation windows.
- Use the same top-3 selection ensemble objective, with five available seeds.

Command:

```powershell
python dl_rank_head_walkforward.py --windows 3 --val-days 252 --top-n 3 --seeds 20260505,20260506,20260507,20260508,20260509 --epochs 8 --lr 0.0005 --scheduler cosine --device auto --amp --pin-memory --date-grouped-batches --dates-per-batch 64 --aux-target-transform zscore --corr-weight 0.05 --rank-weight 0.005 --nll-weight 0.5 --output data\experiment\rank_head_walkforward_3w_5seed.json --csv-output data\experiment\rank_head_walkforward_3w_5seed.csv
```

Results:

```text
Window 1: 2025-04-03..2026-04-06
IC_Spearman: +0.088653
Daily_IC_Mean: +0.106585
Long-short spread: +0.078004
Spread positive rate: 75.00%
Bullish rate: 45.65%
Directional accuracy: 49.22%

Window 2: 2024-04-02..2025-04-02
IC_Spearman: +0.099221
Daily_IC_Mean: +0.136491
Long-short spread: +0.052151
Spread positive rate: 62.18%
Bullish rate: 59.15%
Directional accuracy: 50.00%

Window 3: 2023-03-30..2024-04-01
IC_Spearman: +0.191058
Daily_IC_Mean: +0.166058
Long-short spread: +0.044445
Spread positive rate: 60.62%
Bullish rate: 59.96%
Directional accuracy: 57.51%
```

Interpretation:

- This is the strongest production-readiness evidence so far.
- All three windows have positive pooled IC, positive Daily_IC_Mean, positive
  long-short spread, and spread positive rate above 60%.
- The model is still better framed as a cross-sectional rank/selection signal
  than a raw sign forecaster.

Current status:

```text
Eligible for shadow-mode production candidate work.
Not yet eligible to replace the existing DL forecast in production.
Next step: generate daily shadow rank-head ensemble forecasts alongside the
current production DL output, then compare live logged outcomes before promotion.
```

Artifacts:

```text
dl_rank_head_walkforward.py
data/experiment/rank_head_walkforward_3w_5seed.json
data/experiment/rank_head_walkforward_3w_5seed.csv
```
