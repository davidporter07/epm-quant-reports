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

## 2026-05-06: Shadow-Mode Rank-Head Forecast Runner

Purpose:

- Start the shadow-mode production candidate path without replacing the
  existing production DL forecast.
- Generate a daily rank-head ensemble selection log that can be compared
  against future realized returns before promotion.

Added:

```text
dl_rank_head_shadow_forecast.py
```

Smoke/default command:

```powershell
python dl_rank_head_shadow_forecast.py --device cpu --top-n 3
```

Resulting shadow snapshot:

```text
RunDate: 2026-05-06
AsOfDate used by latest fully valid rank-head window: 2025-12-30

Rank 1: TSLA long_candidate
Rank 2: AAPL neutral
Rank 3: GOOG neutral
Rank 4: AMZN neutral
Rank 5: MSFT neutral
Rank 6: NVDA neutral
Rank 7: META short_candidate
```

Artifacts written locally under ignored `data/` paths:

```text
data/rank_head_shadow_forecasts.csv
data/rank_head_shadow_log.parquet
```

Important finding:

- `data/experiment/directional_feature_panel_fmp.parquet` has base rows
  through `2026-05-05`.
- The six rank-head extra features required by the saved model
  (`atr_percentile`, `gap_5d_count`, `earnings_surprise_last`,
  `days_since_earnings`, `earnings_surprise_x_gap_count`,
  `post_earnings_negative_drift_window`) are non-null only through
  `2025-12-30`.
- The shadow runner therefore falls back to each ticker's latest fully finite
  sequence window instead of fabricating values.

Interpretation:

- Shadow infrastructure is working.
- The first shadow log is not yet a true current-date live signal because the
  research candidate feature cache is stale.
- Next quality step: refresh or rebuild the directional research feature panel
  so rank-head shadow forecasts can use the latest available market date,
  then rerun the shadow forecast and begin live outcome tracking.

## 2026-05-06: Current-Date Shadow Panel Refresh

Purpose:

- Repair the stale research candidate feature columns found during the first
  shadow-mode forecast run.
- Preserve the shared Quant Cup price cache instead of overwriting it with a
  MAG7-only forced refresh.

Added:

```text
refresh_quant_cup_price_cache.py
```

Price-cache command:

```powershell
python refresh_quant_cup_price_cache.py --tickers AAPL,MSFT,AMZN,NVDA,GOOG,META,TSLA --end 2026-05-07
```

Result:

```text
Close  updated rows=5117 max_date=2026-05-06
Open   updated rows=5117 max_date=2026-05-06
High   updated rows=5117 max_date=2026-05-06
Low    updated rows=5117 max_date=2026-05-06
Volume updated rows=5117 max_date=2026-05-06
```

Panel rebuild:

```powershell
python build_directional_feature_panel.py --merge-base --include-earnings --earnings-source fmp --end 2026-05-07 --output data\experiment\directional_feature_panel_fmp.parquet --csv-output data\experiment\directional_feature_panel_fmp_sample.csv
```

Verification:

```text
Panel max date: 2026-05-06
Required rank-head extra feature coverage through 2026-05-06:
atr_percentile: 100%
gap_5d_count: 100%
earnings_surprise_last: 100%
days_since_earnings: 100%
earnings_surprise_x_gap_count: 100%
post_earnings_negative_drift_window: 100%
```

Current-date shadow run:

```powershell
python dl_rank_head_shadow_forecast.py --device cpu --top-n 3
```

Current shadow snapshot:

```text
RunDate: 2026-05-06
AsOfDate: 2026-05-06

Rank 1: NVDA long_candidate
Rank 2: GOOG neutral
Rank 3: AAPL neutral
Rank 4: TSLA neutral
Rank 5: AMZN neutral
Rank 6: META neutral
Rank 7: MSFT short_candidate
```

Interpretation:

- Shadow-mode rank-head infrastructure now produces a current-date signal.
- The signal remains shadow-only and should be evaluated against realized
  forward returns before any promotion.
- Next quality step: add a scorer for `data/rank_head_shadow_log.parquet`
  once enough live rows accumulate, and optionally run daily shadow generation
  from `post_run.py` behind an explicit flag.

## 2026-05-06: Shadow Log Scorer

Purpose:

- Add the measurement layer for shadow-mode rank-head forecasts.
- Separate scoreable rows from pending rows so current forecasts can be logged
  immediately and scored only when their 21-trading-day outcomes mature.

Added:

```text
dl_rank_head_shadow_score.py
```

Command:

```powershell
python dl_rank_head_shadow_score.py
```

Current result:

```text
Rows total: 7
Rows scored: 0
Rows pending: 7
Status: no_scoreable_rows
Pending AsOfDate values: 2026-05-06
```

Artifacts written locally under ignored `data/` paths:

```text
data/rank_head_shadow_scores.json
data/rank_head_shadow_scores.csv
```

Interpretation:

- The scorer is ready, but the current shadow run cannot be evaluated yet
  because `Target_Forward_21D` is not known for `2026-05-06`.
- Once enough future market data exists, rerun the scorer to compute pooled IC,
  Daily IC, selection spread, candidate long/short hit rates, and pending-row
  counts from the same shadow log.

## 2026-05-06: Historical Shadow Backtest Harness

Purpose:

- Test the production-like shadow workflow on historical rows with known
  21-trading-day forward outcomes instead of waiting for live rows to mature.
- Emit historical rows in the same shape as the live shadow log so
  `dl_rank_head_shadow_score.py` can score them directly.

Added:

```text
dl_rank_head_shadow_backtest.py
```

Also updated:

```text
dl_rank_head_shadow_score.py
```

The scorer now uses an existing `RealizedForwardReturn` column when present in
a historical shadow log, and falls back to joining `Target_Forward_21D` from the
panel for live logs.

Current-panel command:

```powershell
python dl_rank_head_shadow_backtest.py --device cpu --top-n 3 --val-days 252 --output data\experiment\rank_head_shadow_backtest_252d.parquet --csv-output data\experiment\rank_head_shadow_backtest_252d.csv

python dl_rank_head_shadow_score.py --log-path data\experiment\rank_head_shadow_backtest_252d.parquet --output data\experiment\rank_head_shadow_backtest_252d_scores.json --detail-output data\experiment\rank_head_shadow_backtest_252d_scores.csv
```

Current-panel result:

```text
Rows: 1,351
AsOfDate range: 2025-07-01 -> 2026-04-07
Rows scored: 1,351
Rows pending: 0
IC_Spearman: -0.090123
Daily_IC_Mean: -0.137861
Selection_Long_Short_Spread_Mean: -0.026865
Selection_Spread_Positive_Rate: 29.53%
LongCandidateMeanReturn: +0.004296
ShortCandidateMeanReturn: +0.031161
```

Cross-check:

```powershell
python dl_rank_head_ensemble_eval.py --results data\experiment\rank_head_selection_objective_scaler_5seed.json --device cpu --top-n 3 --output data\experiment\rank_head_selection_objective_ensemble_top3_currentpanel_check.json --csv-output data\experiment\rank_head_selection_objective_ensemble_members_top3_currentpanel_check.csv
```

The existing ensemble evaluator matched the new shadow backtest result on the
refreshed current panel:

```text
IC_Spearman: -0.090123
Daily_IC_Mean: -0.137861
Selection_Long_Short_Spread_Mean: -0.026865
Selection_Spread_Positive_Rate: 29.53%
```

Artifact-management finding:

- The earlier walk-forward JSON still records positive historical metrics.
- However, the checkpoint filenames under `models/experiment/` are reused by
  later rank-head runs/windows.
- Re-evaluating the saved generic checkpoint paths now does not reproduce the
  earlier positive window metrics.
- This means the historical metrics are useful as recorded evidence, but the
  model artifacts are not sufficiently immutable for promotion-quality
  reproducibility.

Interpretation:

- The shadow backtest/scorer workflow is working.
- The current reusable top-3 checkpoint artifacts are not production-ready.
- Before promotion, the next engineering fix is to make rank-head/walk-forward
  checkpoint paths immutable by run/window id, then rerun the walk-forward
  experiment and preserve the exact artifacts that produced each metric.

## 2026-05-07: Immutable Walk-Forward Checkpoints

Purpose:

- Fix the artifact reproducibility problem found by the historical shadow
  backtest.
- Prevent later rank-head runs/windows from overwriting checkpoints that
  produced earlier validation metrics.

Updated:

```text
dl_rank_head_experiment.py
dl_rank_head_walkforward.py
```

Implementation:

- `_train_one(...)` now accepts an optional `artifact_dir`.
- Plain rank-head experiment runs keep their existing default location.
- Walk-forward runs now save each window's models/scalers under:

```text
models/experiment/rank_head_walkforward/<output-stem>/<window>/
```

Rerun command:

```powershell
python dl_rank_head_walkforward.py --windows 3 --val-days 252 --top-n 3 --seeds 20260505,20260506,20260507,20260508,20260509 --epochs 8 --lr 0.0005 --scheduler cosine --device auto --amp --pin-memory --date-grouped-batches --dates-per-batch 64 --aux-target-transform zscore --corr-weight 0.05 --rank-weight 0.005 --nll-weight 0.5 --output data\experiment\rank_head_walkforward_immutable_3w_5seed.json --csv-output data\experiment\rank_head_walkforward_immutable_3w_5seed.csv
```

Immutable walk-forward result:

```text
Window 1: 2025-04-04..2026-04-07
IC_Spearman: +0.090408
Daily_IC_Mean: +0.176268
Long-short spread: +0.047445
Spread positive rate: 65.29%
Bullish rate: 39.75%
Directional accuracy: 49.37%

Window 2: 2024-04-03..2025-04-03
IC_Spearman: +0.108409
Daily_IC_Mean: +0.121503
Long-short spread: +0.049987
Spread positive rate: 61.66%
Bullish rate: 54.32%
Directional accuracy: 52.46%

Window 3: 2023-03-31..2024-04-02
IC_Spearman: +0.182456
Daily_IC_Mean: +0.169319
Long-short spread: +0.043678
Spread positive rate: 61.14%
Bullish rate: 59.44%
Directional accuracy: 57.59%
```

Aggregate:

```text
Mean IC_Spearman: +0.127091
Mean Daily_IC_Mean: +0.155696
Mean long-short spread: +0.047037
Minimum long-short spread: +0.043678
Mean spread positive rate: 62.70%
```

Verification:

- The JSON result rows now point to window-specific checkpoint paths, for
  example:

```text
models\experiment\rank_head_walkforward\rank_head_walkforward_immutable_3w_5seed\w1_20260407\dl_rankhead_seed20260508_cw0p05_rw0p005_nw0p5_dgb.pt
```

Interpretation:

- The rank-head top-3 ensemble again passes the core walk-forward quality gate.
- The evidence is now reproducible because each metric points to preserved,
  window-specific artifacts.
- This restores the shadow-mode candidate path, but it still should remain
  shadow-only until live scoring or a current-date retrained immutable candidate
  confirms behavior.

## 2026-05-07 - Current Immutable Rank-Head Candidate

Objective:

- Train a current-date rank-head candidate using immutable artifact storage.
- Verify the same artifacts can drive live shadow forecasts and historical
  shadow scoring without reusing overwritten checkpoints.

Code change:

- `dl_rank_head_experiment.py` now accepts `--artifact-dir`.
- The default behavior remains unchanged when the flag is omitted.

Training command:

```powershell
python dl_rank_head_experiment.py --seeds 20260505,20260506,20260507,20260508,20260509 --epochs 8 --lr 0.0005 --scheduler cosine --device auto --amp --pin-memory --date-grouped-batches --dates-per-batch 64 --aux-target-transform zscore --nll-weights 0.5 --corr-weights 0.05 --rank-weights 0.005 --daily-ic-min -0.02 --spread-min 0.0 --spread-positive-rate-min 0.55 --hard-gate --selection-score-mode selection --output data\experiment\rank_head_current_immutable_5seed.json --csv-output data\experiment\rank_head_current_immutable_5seed.csv --artifact-dir models\experiment\rank_head_current\rank_head_current_immutable_5seed
```

Top-3 ensemble evaluation:

```powershell
python dl_rank_head_ensemble_eval.py --results data\experiment\rank_head_current_immutable_5seed.json --device cpu --top-n 3 --output data\experiment\rank_head_current_immutable_ensemble_top3.json --csv-output data\experiment\rank_head_current_immutable_ensemble_members_top3.csv
```

Selected members:

```text
rankhead_seed20260508_cw0p05_rw0p005_nw0p5_dgb
rankhead_seed20260507_cw0p05_rw0p005_nw0p5_dgb
rankhead_seed20260505_cw0p05_rw0p005_nw0p5_dgb
```

Rank-centered ensemble metrics:

```text
IC_Spearman: +0.090393
Daily_IC_Mean: +0.174685
Long-short spread: +0.047033
Spread positive rate: 65.29%
Directional accuracy: 49.37%
Bullish prediction rate: 39.75%
```

Live shadow forecast command:

```powershell
python dl_rank_head_shadow_forecast.py --results data\experiment\rank_head_current_immutable_5seed.json --device cpu --top-n 3 --output data\rank_head_current_immutable_shadow_forecasts.csv --log-path data\rank_head_current_immutable_shadow_log.parquet
```

Live shadow forecast for `2026-05-06`:

```text
Long candidate: META
Short candidate: MSFT
Rows total/scored/pending: 7/0/7
Status: no_scoreable_rows
```

Historical shadow backtest commands:

```powershell
python dl_rank_head_shadow_backtest.py --results data\experiment\rank_head_current_immutable_5seed.json --device cpu --top-n 3 --val-days 252 --output data\experiment\rank_head_current_immutable_shadow_backtest_252d.parquet --csv-output data\experiment\rank_head_current_immutable_shadow_backtest_252d.csv
python dl_rank_head_shadow_score.py --log-path data\experiment\rank_head_current_immutable_shadow_backtest_252d.parquet --output data\experiment\rank_head_current_immutable_shadow_backtest_252d_scores.json --detail-output data\experiment\rank_head_current_immutable_shadow_backtest_252d_scores.csv
```

Historical shadow score:

```text
Rows scored: 1,351
AsOfDate range: 2025-07-01 -> 2026-04-07
IC_Spearman: +0.090393
Daily_IC_Mean: +0.174685
Long-short spread: +0.047033
Spread positive rate: 65.29%
Long candidate mean return: +0.054870
Short candidate mean return: +0.007837
Long hit rate: 59.59%
Short hit rate: 51.30%
```

Interpretation:

- The current immutable candidate preserves the positive long/short selection
  evidence seen in walk-forward testing.
- The historical shadow scorer matches the ensemble evaluator, confirming that
  the shadow-mode scoring path is aligned with the validation path.
- The current live forecast is pending because the forward-return target for
  `2026-05-06` is not yet available.
- Next quality step: keep this candidate in shadow mode, score it when forward
  returns mature, and compare it against the older live shadow candidate before
  promoting any rank-head signal into production commentary.

## 2026-05-07 - Current Candidate Ensemble Breadth Robustness

Objective:

- Test whether the current immutable candidate depends too heavily on the
  selected top-3 ensemble size.
- A production candidate should keep positive rank and selection behavior when
  evaluated as a single best model and as a wider ensemble.

Commands:

```powershell
python dl_rank_head_ensemble_eval.py --results data\experiment\rank_head_current_immutable_5seed.json --device cpu --top-n 1 --output data\experiment\rank_head_current_immutable_ensemble_top1.json --csv-output data\experiment\rank_head_current_immutable_ensemble_members_top1.csv
python dl_rank_head_ensemble_eval.py --results data\experiment\rank_head_current_immutable_5seed.json --device cpu --top-n 5 --output data\experiment\rank_head_current_immutable_ensemble_top5.json --csv-output data\experiment\rank_head_current_immutable_ensemble_members_top5.csv
```

Rank-centered results:

```text
Top-1:
IC_Spearman: +0.094572
Daily_IC_Mean: +0.110474
Long-short spread: +0.042900
Spread positive rate: 68.39%
Directional accuracy: 50.11%
Bullish prediction rate: 47.89%

Top-3:
IC_Spearman: +0.090393
Daily_IC_Mean: +0.174685
Long-short spread: +0.047033
Spread positive rate: 65.29%
Directional accuracy: 49.37%
Bullish prediction rate: 39.75%

Top-5:
IC_Spearman: +0.048657
Daily_IC_Mean: +0.144152
Long-short spread: +0.050710
Spread positive rate: 62.18%
Directional accuracy: 48.63%
Bullish prediction rate: 45.67%
```

Interpretation:

- The candidate is not a fragile top-3-only result. All three ensemble breadths
  keep positive rank IC and positive long/short selection spread.
- Top-5 has the strongest spread but weaker overall IC; top-3 remains the best
  balance of daily IC, spread, and prediction-rate discipline.
- Keep top-3 as the shadow default. Promotion should still wait for matured
  live shadow scores and at least one more clean refresh/backtest cycle.
