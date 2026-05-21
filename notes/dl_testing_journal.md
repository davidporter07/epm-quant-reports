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

## 2026-05-07 - Current Candidate Temporal Segment Check

Objective:

- Check whether the current top-3 rank-head candidate's validation edge is
  concentrated in one subperiod.
- Use production-like historical shadow logs and the same shadow scorer.

Commands:

```powershell
python dl_rank_head_shadow_backtest.py --results data\experiment\rank_head_current_immutable_5seed.json --device cpu --top-n 3 --start-date 2025-07-01 --end-date 2025-12-31 --output data\experiment\rank_head_current_immutable_shadow_backtest_h1.parquet --csv-output data\experiment\rank_head_current_immutable_shadow_backtest_h1.csv
python dl_rank_head_shadow_score.py --log-path data\experiment\rank_head_current_immutable_shadow_backtest_h1.parquet --output data\experiment\rank_head_current_immutable_shadow_backtest_h1_scores.json --detail-output data\experiment\rank_head_current_immutable_shadow_backtest_h1_scores.csv

python dl_rank_head_shadow_backtest.py --results data\experiment\rank_head_current_immutable_5seed.json --device cpu --top-n 3 --start-date 2026-01-01 --end-date 2026-04-07 --output data\experiment\rank_head_current_immutable_shadow_backtest_h2.parquet --csv-output data\experiment\rank_head_current_immutable_shadow_backtest_h2.csv
python dl_rank_head_shadow_score.py --log-path data\experiment\rank_head_current_immutable_shadow_backtest_h2.parquet --output data\experiment\rank_head_current_immutable_shadow_backtest_h2_scores.json --detail-output data\experiment\rank_head_current_immutable_shadow_backtest_h2_scores.csv
```

Segment results:

```text
Segment 1:
Rows scored: 483
AsOfDate range: 2025-09-24 -> 2025-12-31
IC_Spearman: +0.191969
Daily_IC_Mean: +0.196170
Long-short spread: +0.037177
Spread positive rate: 66.67%
Long candidate mean return: +0.008372
Short candidate mean return: -0.028806

Segment 2:
Rows scored: 42
AsOfDate range: 2026-03-30 -> 2026-04-07
IC_Spearman: +0.695000
Daily_IC_Mean: +0.761905
Long-short spread: +0.205832
Spread positive rate: 100.00%
Long candidate mean return: +0.287408
Short candidate mean return: +0.081575
```

Interpretation:

- The candidate remains positive in both available temporal segments.
- Segment 1 is the more useful stability check because it has 69 daily
  selection observations and a clean positive spread.
- Segment 2 is directionally favorable but too small to treat as strong
  independent evidence; it has only 6 daily selection observations.
- Production status remains shadow-only. The candidate now passes
  walk-forward, ensemble breadth, and segmented historical shadow checks, but
  it still needs matured live shadow scoring before promotion.

## 2026-05-07 - Live Shadow Forecast Recheck After Forecasting Page Fix

Objective:

- Recheck the current immutable rank-head candidate's live shadow forecast after
  fixing the forecasting page leaderboard.
- Confirm whether any live shadow rows have matured enough to score.

Commands:

```powershell
python dl_rank_head_shadow_score.py --log-path data\rank_head_current_immutable_shadow_log.parquet --output data\rank_head_current_immutable_shadow_scores.json --detail-output data\rank_head_current_immutable_shadow_scores.csv
python dl_rank_head_shadow_forecast.py --results data\experiment\rank_head_current_immutable_5seed.json --device cpu --top-n 3 --output data\rank_head_current_immutable_shadow_forecasts.csv --log-path data\rank_head_current_immutable_shadow_log.parquet
```

Live shadow status:

```text
Rows total/scored/pending: 7/0/7
Pending AsOfDate: 2026-05-06
Long candidate: META
Short candidate: MSFT
Log uniqueness: 7 rows, 7 unique AsOfDate/Ticker pairs
```

Interpretation:

- The live shadow forecast is running and deduplicated.
- The signal is still pending because the forward-return target for
  `2026-05-06` has not matured in the panel yet.
- Keep this as the active shadow candidate and score it again after the next
  data refresh/maturation cycle.

## 2026-05-07 - Rank-Head Paper-Trading Ledger

Objective:

- Continue DL testing before the `2026-05-06` live shadow signal matures.
- Convert historical rank-head shadow forecasts into a paper-trading ledger
  that can be compared against Quant Cup-style model runs.

Implementation:

- Added `dl_rank_head_paper_trade.py`.
- The script treats each historical `AsOfDate` as a paper signal date.
- It supports configurable long/short basket sizes and writes both a trade
  ledger CSV and a summary JSON.
- Important caveat: the returns are 21-trading-day forward returns issued on
  daily signal dates, so adjacent rows overlap. Mean spread and hit rate are
  the most useful diagnostics; compounded equity is directional only and should
  not be treated as a live, non-overlapping portfolio curve.

Commands:

```powershell
python dl_rank_head_paper_trade.py --log-path data\experiment\rank_head_current_immutable_shadow_backtest_252d.parquet --long-n 1 --short-n 1 --ledger-output data\experiment\rank_head_current_immutable_paper_trades_top1_bottom1.csv --summary-output data\experiment\rank_head_current_immutable_paper_trades_top1_bottom1.json
python dl_rank_head_paper_trade.py --log-path data\experiment\rank_head_current_immutable_shadow_backtest_252d.parquet --long-n 2 --short-n 2 --ledger-output data\experiment\rank_head_current_immutable_paper_trades_top2_bottom2.csv --summary-output data\experiment\rank_head_current_immutable_paper_trades_top2_bottom2.json
python dl_rank_head_paper_trade.py --log-path data\experiment\rank_head_current_immutable_shadow_backtest_252d.parquet --long-n 3 --short-n 3 --ledger-output data\experiment\rank_head_current_immutable_paper_trades_top3_bottom3.csv --summary-output data\experiment\rank_head_current_immutable_paper_trades_top3_bottom3.json
```

Results:

```text
Top-1 / Bottom-1:
Trade days: 193
AsOfDate range: 2025-07-01 -> 2026-04-07
Mean long return: +0.054870
Mean short return: +0.007837
Mean long-short return: +0.047033
Spread hit rate: 65.29%
Long hit rate: 59.59%
Short hit rate: 51.30%
Max drawdown: -93.80%

Top-2 / Bottom-2:
Trade days: 193
Mean long return: +0.040616
Mean short return: +0.001198
Mean long-short return: +0.039417
Spread hit rate: 74.61%
Long hit rate: 65.29%
Short hit rate: 50.78%
Max drawdown: -32.24%

Top-3 / Bottom-3:
Trade days: 193
Mean long return: +0.030821
Mean short return: +0.012586
Mean long-short return: +0.018236
Spread hit rate: 64.25%
Long hit rate: 62.18%
Short hit rate: 46.11%
Max drawdown: -80.40%
```

Interpretation:

- The paper-trading ledger confirms the rank-head signal is useful beyond the
  single-candidate shadow scorer.
- Top-1/bottom-1 preserves the strongest average spread, but top-2/bottom-2
  is more stable and has the best spread hit rate.
- Top-3/bottom-3 dilutes the edge too much for the current MAG7 universe.
- Recommended next paper-trading default: top-2/bottom-2 for Quant Cup-style
  stability testing, while preserving top-1/bottom-1 as the highest-conviction
  shadow signal.

## 2026-05-07 - Historical Blind Adaptive Loop Prototype

Objective:

- Move from static backtests toward a learning loop that experiences historical
  trading days as they would have appeared at the time.
- Prevent target leakage by training only on labels that would have matured
  before each historical decision date.
- Predict the historical decision date blind, then attach realized returns
  afterward only for scoring.

Implementation:

- Added `dl_rank_head_historical_blind_loop.py`.
- For each cycle:
  - choose a historical decision date with known 21D outcome;
  - set `TrainLabelThrough` to 21 trading sessions before that decision date;
  - train rank-head artifacts only on rows with `Date <= TrainLabelThrough`;
  - predict the decision date with target values replaced by dummy zeros in
    the prediction panel so the model cannot see the future label;
  - attach realized `Target_Forward_21D` after prediction for scoring.

Smoke command:

```powershell
python dl_rank_head_historical_blind_loop.py --cycles 2 --step-days 21 --epochs 1 --seeds 20260505 --val-days 126 --top-n 1 --paper-long-n 1 --paper-short-n 1 --device cpu --output data\experiment\historical_blind_rank_head\smoke_shadow_log.parquet --csv-output data\experiment\historical_blind_rank_head\smoke_shadow_log.csv --summary-output data\experiment\historical_blind_rank_head\smoke_summary.json --output-stem smoke_blind_loop
```

Smoke result:

```text
Cycles: 2
Rows: 14
Mean long-short return: -0.127338
Spread hit rate: 50.00%
```

The smoke test verified mechanics only; one epoch was intentionally too light
to judge model quality.

Prototype command:

```powershell
python dl_rank_head_historical_blind_loop.py --cycles 3 --step-days 21 --epochs 3 --seeds 20260505 --val-days 126 --top-n 1 --paper-long-n 2 --paper-short-n 2 --device cpu --date-grouped-batches --dates-per-batch 64 --output data\experiment\historical_blind_rank_head\rank_head_blind_loop_3c_3e_shadow_log.parquet --csv-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_3c_3e_shadow_log.csv --summary-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_3c_3e_summary.json --output-stem rank_head_blind_loop_3c_3e
```

Prototype result:

```text
Cycles: 3
Rows: 21
Decision dates: 2026-01-28, 2026-02-27, 2026-03-30
Train-label cutoffs: 2025-12-26, 2026-01-28, 2026-02-27
Paper basket: top-2 / bottom-2
Mean long return: +0.031671
Mean short return: +0.002810
Mean long-short return: +0.028860
Spread hit rate: 66.67%
Long hit rate: 33.33%
Short hit rate: 66.67%
Max drawdown: -0.40%
```

Cycle high-conviction signals:

```text
2026-01-28: long TSLA, short MSFT, long-short +0.115602
2026-02-27: long AMZN, short AAPL, long-short +0.023337
2026-03-30: long AMZN, short TSLA, long-short +0.259669
```

Interpretation:

- The prototype successfully creates a no-peeking historical learning loop.
- The 3-cycle/3-epoch run is positive, but the sample is too small for
  promotion decisions.
- This is now the right direction for making the neural system adaptive:
  expand cycle count, compare challengers to the current immutable champion,
  and promote only when a blind loop beats the champion across several
  historical regimes.

## 2026-05-07 - Expanded Historical Blind Loop Gate

Objective:

- Expand the historical blind loop from the 3-cycle prototype to a 12-cycle
  gate.
- Test whether the adaptive retraining loop is genuinely improving prediction
  quality across a broader historical path rather than only on the most recent
  favorable window.

Commands:

```powershell
python dl_rank_head_historical_blind_loop.py --cycles 12 --step-days 21 --epochs 3 --seeds 20260505 --val-days 126 --top-n 1 --paper-long-n 2 --paper-short-n 2 --device cpu --date-grouped-batches --dates-per-batch 64 --output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_3e_shadow_log.parquet --csv-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_3e_shadow_log.csv --summary-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_3e_summary.json --output-stem rank_head_blind_loop_12c_3e
python dl_rank_head_paper_trade.py --log-path data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_3e_shadow_log.parquet --long-n 1 --short-n 1 --ledger-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_3e_top1_bottom1.csv --summary-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_3e_top1_bottom1.json
python dl_rank_head_paper_trade.py --log-path data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_3e_shadow_log.parquet --long-n 3 --short-n 3 --ledger-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_3e_top3_bottom3.csv --summary-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_3e_top3_bottom3.json
```

12-cycle / 3-epoch result:

```text
Decision range: 2025-04-28 -> 2026-03-30
Top-1 / Bottom-1 mean spread: +0.012196
Top-1 / Bottom-1 spread hit rate: 41.67%

Top-2 / Bottom-2 mean spread: -0.016637
Top-2 / Bottom-2 spread hit rate: 50.00%

Top-3 / Bottom-3 mean spread: -0.015314
Top-3 / Bottom-3 spread hit rate: 33.33%
```

The 3-epoch adaptive challenger failed the expanded gate. It over-selected
TSLA early in the window and did not preserve the positive top-2/bottom-2
paper-trading behavior seen in the smaller prototype.

Follow-up command:

```powershell
python dl_rank_head_historical_blind_loop.py --cycles 12 --step-days 21 --epochs 8 --seeds 20260505 --val-days 126 --top-n 1 --paper-long-n 2 --paper-short-n 2 --device cpu --date-grouped-batches --dates-per-batch 64 --output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_shadow_log.parquet --csv-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_shadow_log.csv --summary-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_summary.json --output-stem rank_head_blind_loop_12c_8e
python dl_rank_head_paper_trade.py --log-path data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_shadow_log.parquet --long-n 1 --short-n 1 --ledger-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_top1_bottom1.csv --summary-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_top1_bottom1.json
python dl_rank_head_paper_trade.py --log-path data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_shadow_log.parquet --long-n 3 --short-n 3 --ledger-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_top3_bottom3.csv --summary-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_top3_bottom3.json
```

12-cycle / 8-epoch result:

```text
Top-1 / Bottom-1:
Mean long return: +0.053725
Mean short return: +0.017477
Mean long-short return: +0.036248
Spread hit rate: 58.33%
Max drawdown: -24.79%

Top-2 / Bottom-2:
Mean long return: +0.035377
Mean short return: +0.038234
Mean long-short return: -0.002857
Spread hit rate: 58.33%
Max drawdown: -11.54%

Top-3 / Bottom-3:
Mean long return: +0.027490
Mean short return: +0.045347
Mean long-short return: -0.017857
Spread hit rate: 41.67%
Max drawdown: -19.45%
```

Interpretation:

- More training helped materially: top-1/bottom-1 became a positive
  high-conviction signal.
- The adaptive loop still fails the diversified top-2/bottom-2 gate, so it is
  not production-ready as a basket allocator.
- The short side is still weak in broad baskets; the model is better at finding
  one strong long than building a stable long/short book.
- Next improvement target: add a promotion gate that rejects adaptive
  challengers unless both high-conviction top-1 and diversified top-2 are
  positive across the 12-cycle blind loop, then test multi-seed ensembles or
  ticker exposure constraints to reduce single-name concentration.

## 2026-05-09 - Quant Cup Price Regime Gate Clean-Book Recheck

Objective:

- Verify whether the Quant Cup price rank-head historical regime pass survives
  a clean long/short book constraint.
- Reject abstention replay rows where the selected long and short baskets share
  any ticker. This matters for small historical universes where `top3_bottom3`
  can otherwise overlap.

Result:

```text
Raw price clean-book abstention:
Status: fail
Candidate configs: 5832
Passing configs: 0
Best: top1_bottom1, stress_spread=+0.212765, worst_dd=0.00%, coverage=1.39%

Excess-return clean-book abstention:
Status: fail
Candidate configs: 5832
Passing configs: 0
Best: top1_bottom1, stress_spread=+0.058357, worst_dd=0.00%, coverage=1.39%
```

Interpretation:

- The earlier raw-price abstention pass was invalidated by clean-book replay.
- Its apparent `top3_bottom3` pass relied on overlapping long/short baskets in
  small-universe stress regimes, especially `gfc_2008`.
- The remaining high-spread candidates trade too rarely, with only 1.39%
  average stress coverage versus the 10% gate.
- Do not promote this rank-head regime gate. Treat the Quant Cup price and
  excess-return historical regime branch as research-only until a future model
  passes with non-overlapping baskets and adequate stress coverage.

## 2026-05-09 - DL Shadow Diagnostic: Long Edge vs Short Leg

Objective:

- Diagnose the saved 12-cycle blind-loop rank-head runs without retraining.
- Separate top-N long-only behavior, bottom-N short-leg behavior, long/short
  spread behavior, ticker concentration, and rank-bucket monotonicity.

Command:

```powershell
python dl_shadow_diagnostic_report.py --log-path data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_shadow_log.parquet --output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_diagnostic.json --markdown-output notes\dl_shadow_diagnostic_12c_8e.md --max-n 3
python dl_shadow_diagnostic_report.py --log-path data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_3e_shadow_log.parquet --output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_3e_diagnostic.json --markdown-output notes\dl_shadow_diagnostic_12c_3e.md --max-n 3
```

Result:

```text
12-cycle / 8-epoch:
top1_bottom1: long=+0.053725, long_excess=+0.017239, short_alpha=-0.017477, spread=+0.036248
top2_bottom2: long=+0.035377, long_excess=-0.001109, short_alpha=-0.038234, spread=-0.002857
top3_bottom3: long=+0.027490, long_excess=-0.008996, short_alpha=-0.045347, spread=-0.017857

12-cycle / 3-epoch:
top1_bottom1: long=+0.031025, long_excess=-0.005461, short_alpha=-0.018830, spread=+0.012196
top2_bottom2: long=+0.015567, long_excess=-0.020919, short_alpha=-0.032204, spread=-0.016637
top3_bottom3: long=+0.028553, long_excess=-0.007933, short_alpha=-0.043867, spread=-0.015314
```

Interpretation:

- The 8-epoch training improvement is concentrated in the top-1 long leg:
  top-1 long excess improved from -0.005461 to +0.017239.
- The short leg is adverse in both runs. Bottom-ranked names still have
  positive realized forward returns, making short alpha negative.
- Broader baskets dilute the signal. Top-2 and top-3 long excess is not
  positive, and long/short spreads fail because the short side does not work.
- Rank ordering is not monotonic. In the 8-epoch run, rank 5 has the strongest
  average return, so this model should not be promoted as a full cross-sectional
  allocator.
- Next production-quality candidate should be long-only top-1 with abstention,
  ticker exposure caps, and benchmark/cash comparison, not a long/short book.

## 2026-05-09 - DL Long-Only Abstention Gate

Objective:

- Test whether the saved 12-cycle blind-loop runs can be promoted as selective
  long-only rank-head candidates after dropping the broken short leg.
- Gate against equal-weight universe excess return, excess hit rate, drawdown,
  minimum coverage, and single-ticker concentration.

Result:

```text
12-cycle / 8-epoch, no exposure cap:
Status: pass
Passing configs: 32 / 7290
Best: top1, long=+0.031999, excess=+0.005122, excess_hit=60.00%, coverage=41.67%

12-cycle / 3-epoch, no exposure cap:
Status: pass
Passing configs: 84 / 7290
Best: top1, long=+0.029767, excess=+0.012183, excess_hit=66.67%, coverage=25.00%

12-cycle / 8-epoch, max single-ticker share 50%:
Status: fail
Passing configs: 0 / 7290

12-cycle / 3-epoch, max single-ticker share 50%:
Status: fail
Passing configs: 0 / 7290

12-cycle / 8-epoch, max single-ticker share 67%:
Status: fail
Passing configs: 0 / 7290
Best: top1, long=+0.078200, excess=+0.013685, excess_hit=50.00%, coverage=16.67%

12-cycle / 3-epoch, max single-ticker share 67%:
Status: fail
Passing configs: 0 / 7290
Best: top1, long=+0.078200, excess=+0.013685, excess_hit=50.00%, coverage=16.67%
```

Interpretation:

- Long-only abstention can find positive top-1 slices, but not after applying a
  basic production concentration gate. This remains true with a looser 67%
  single-ticker cap.
- The 3-epoch strict-coverage pass selected TSLA on every kept date, so it is
  a single-name exposure result rather than a durable model edge.
- The 8-epoch pass has better full-sample top-1 behavior, but its gated variant
  is still too sparse or too concentrated once max ticker share is constrained.
- Do not promote the current rank-head model. The next model-improvement path is
  not another threshold sweep; it is to train for better rank monotonicity and
  reduced ticker concentration, then retest long-only top-1/top-2 under exposure
  caps.

## 2026-05-09 - Rank-Head Top-Excess/Rank-Quality Training Smoke

Objective:

- Add experimental differentiable training pressure toward top-ranked excess
  return and listwise rank quality.
- Verify the new training knobs execute before spending time on a larger
  historical blind loop.

Implementation:

- Added `--top-excess-weight`, `--top-excess-temperature`,
  `--monotonic-weight`, and `--monotonic-quantiles` to the rank-head experiment,
  walk-forward, and historical blind-loop CLIs.
- The top-excess helper uses a softmax-weighted exposure over predictions rather
  than hard `topk`, so it contributes gradient signal.
- The rank-quality helper uses a listwise target-return distribution rather than
  hard sorted buckets, so it also contributes gradient signal.

Smoke commands:

```powershell
python dl_rank_head_historical_blind_loop.py --cycles 1 --step-days 21 --epochs 1 --seeds 20260505 --val-days 126 --top-n 1 --paper-long-n 1 --paper-short-n 1 --device cpu --date-grouped-batches --dates-per-batch 64 --top-excess-weight 0.5 --top-excess-temperature 0.05 --monotonic-weight 0.05 --monotonic-quantiles 5 --output-stem smoke_topmono_1c_1e --output data\experiment\historical_blind_rank_head\smoke_topmono_1c_1e_shadow_log.parquet --csv-output data\experiment\historical_blind_rank_head\smoke_topmono_1c_1e_shadow_log.csv --summary-output data\experiment\historical_blind_rank_head\smoke_topmono_1c_1e_summary.json
python dl_rank_head_historical_blind_loop.py --cycles 3 --step-days 21 --epochs 3 --seeds 20260505 --val-days 126 --top-n 1 --paper-long-n 1 --paper-short-n 1 --device cpu --date-grouped-batches --dates-per-batch 64 --top-excess-weight 0.5 --top-excess-temperature 0.05 --monotonic-weight 0.05 --monotonic-quantiles 5 --output-stem rank_head_blind_loop_3c_3e_topmono --output data\experiment\historical_blind_rank_head\rank_head_blind_loop_3c_3e_topmono_shadow_log.parquet --csv-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_3c_3e_topmono_shadow_log.csv --summary-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_3c_3e_topmono_summary.json
```

Result:

```text
1-cycle / 1-epoch smoke:
Status: scored
Mean long-short return: +0.213536
Spread hit rate: 100.00%

3-cycle / 3-epoch topmono diagnostic:
top1_bottom1: long=+0.041515, long_excess=+0.031353, short_alpha=+0.051228, spread=+0.092744, hit=66.67%
top2_bottom2: long=+0.032532, long_excess=+0.022370, short_alpha=-0.010499, spread=+0.022033, hit=66.67%
top3_bottom3: long=+0.026560, long_excess=+0.016398, short_alpha=-0.014172, spread=+0.012388, hit=33.33%

3-cycle / 3-epoch long-only gate, no ticker cap:
Status: pass
Passing configs: 324 / 5832
Best: top1, long=-0.067098, excess=+0.009179, hit=100.00%, coverage=33.33%

3-cycle / 3-epoch long-only gate, max ticker share 67%:
Status: fail
Passing configs: 0 / 5832
Best: top1, long=-0.067098, excess=+0.009179, hit=100.00%, coverage=33.33%
```

Interpretation:

- The new training objective compiles and runs through historical blind-loop
  training.
- The tiny 3-cycle sample is too short for model selection, but it is useful as
  a sanity check: raw top-1/top-2 diagnostics improved, while production-style
  concentration gating still fails.
- Next step is a 12-cycle challenger run with the same top-excess/listwise
  settings, then rerun diagnostic and long-only gates with 67% and 50% ticker
  caps. Do not use the 3-cycle result for promotion decisions.

## 2026-05-09 - 12-Cycle Top-Excess/Rank-Quality Challenger

Objective:

- Test whether the differentiable top-excess/listwise training objective fixes
  the previous rank-head model's concentration and long-only gate failures.

Command:

```powershell
python dl_rank_head_historical_blind_loop.py --cycles 12 --step-days 21 --epochs 8 --seeds 20260505 --val-days 126 --top-n 1 --paper-long-n 1 --paper-short-n 1 --device cpu --date-grouped-batches --dates-per-batch 64 --top-excess-weight 0.5 --top-excess-temperature 0.05 --monotonic-weight 0.05 --monotonic-quantiles 5 --output-stem rank_head_blind_loop_12c_8e_topmono --output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_topmono_shadow_log.parquet --csv-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_topmono_shadow_log.csv --summary-output data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_topmono_summary.json
```

Result:

```text
Historical blind loop:
Status: scored
Cycles: 12
Rows: 84
Mean long-short return: +0.015543
Spread hit rate: 50.00%

Diagnostic:
top1_bottom1: long=+0.044331, long_excess=+0.007845, short_alpha=-0.028788, spread=+0.015543, hit=50.00%
top2_bottom2: long=+0.029965, long_excess=-0.006521, short_alpha=-0.042601, spread=-0.012636, hit=41.67%
top3_bottom3: long=+0.041828, long_excess=+0.005342, short_alpha=-0.044852, spread=-0.003024, hit=50.00%

Long-only gate, no ticker cap:
Status: pass
Passing configs: 138 / 5832
Best: top2, long=+0.057801, excess=+0.024829, hit=50.00%, coverage=16.67%

Long-only gate, max ticker share 67%:
Status: fail
Passing configs: 0 / 5832
Best: top2, long=+0.127770, excess=+0.056066, hit=100.00%, coverage=8.33%
Failures: coverage 8.33% < 10.00%, max ticker share 100.00% > 67.00%

Long-only gate, max ticker share 50%:
Status: fail
Passing configs: 0 / 5832
Best: top2, long=+0.127770, excess=+0.056066, hit=100.00%, coverage=8.33%
Failures: coverage 8.33% < 10.00%, max ticker share 100.00% > 50.00%
```

Ticker concentration:

```text
Long candidates: TSLA 9, MSFT 1, NVDA 1, AAPL 1
Short candidates: MSFT 9, GOOG 1, AAPL 1, NVDA 1
```

Interpretation:

- The top-excess/listwise objective improved the no-cap long-only gate, but it
  did not solve the production blocker.
- The model still mostly learns a single-name TSLA-long / MSFT-short preference.
- The short leg remains adverse: bottom-ranked names still do not reliably
  underperform.
- Do not promote this challenger. The next model-improvement step must target
  ticker concentration directly, not only return-ranking loss.

## 2026-05-09 - Ticker-Concentration Training Penalty Smoke

Objective:

- Add a direct ticker exposure concentration penalty to rank-head training.
- Penalize high softmax long exposure concentration by ticker across each
  date-grouped training batch.
- Verify whether the penalty changes the TSLA/MSFT collapse observed in the
  12-cycle topmono challenger.

Implementation:

- Added `--ticker-concentration-weight` and
  `--ticker-concentration-temperature` to the rank-head experiment,
  walk-forward, and historical blind-loop CLIs.
- The loss computes per-date softmax exposure from rank scores, aggregates
  exposure by ticker across the batch, and penalizes excess Herfindahl
  concentration above a uniform baseline.

Smoke results:

```text
1-cycle / 1-epoch smoke, ticker_concentration_weight=0.5:
Status: scored
Mean long-short return: +0.037437
Spread hit rate: 100.00%

3-cycle / 3-epoch, ticker_concentration_weight=0.5:
Status: scored
Mean long-short return: +0.051751
Long candidates: GOOG 1, META 1, AMZN 1
top1_bottom1: long=+0.021104, long_excess=+0.010942, short_alpha=+0.030647, spread=+0.051751
cap67 long-only gate: fail, 0 / 5832

3-cycle / 3-epoch, ticker_concentration_weight=0.1:
Status: scored
Mean long-short return: -0.037238
Long candidates: TSLA 2, AMZN 1
top1_bottom1: long=+0.041515, long_excess=+0.031353, short_alpha=-0.078753, spread=-0.037238
cap67 long-only gate: fail, 0 / 5832
```

Interpretation:

- The concentration penalty works mechanically: at weight 0.5, the 3-cycle
  probe no longer selects TSLA repeatedly.
- Weight 0.5 appears too strong on the small probe: it diversifies the picks but
  does not pass the long-only gate.
- Weight 0.1 is too weak: it still selected TSLA on two of three dates.
- Next full challenger should use a moderate value such as 0.25 with the same
  top-excess/listwise settings, then rerun the 12-cycle diagnostics and capped
  long-only gates.

## 2026-05-09 - 12-Cycle Ticker-Concentration 0.25 Challenger

Objective:

- Test whether a moderate ticker concentration penalty preserves the topmono
  long edge while reducing single-name exposure enough to satisfy production
  concentration gates.

Command note:

- The run used `--ticker-concentration-weight 0.25`, but reused the
  `rank_head_blind_loop_12c_8e_topmono` output stem, so it overwrote the prior
  no-concentration topmono artifact. Reports below were regenerated from the
  current overwritten parquet.

Result:

```text
Historical blind loop:
Status: scored
Cycles: 12
Rows: 84
Mean long-short return: +0.005116
Spread hit rate: 58.33%

Diagnostic:
top1_bottom1: long=+0.028698, long_excess=-0.007788, short_alpha=-0.023582, spread=+0.005116, hit=58.33%
top2_bottom2: long=+0.030181, long_excess=-0.006306, short_alpha=-0.052154, spread=-0.021973, hit=41.67%
top3_bottom3: long=+0.022377, long_excess=-0.014109, short_alpha=-0.043825, spread=-0.021448, hit=33.33%

Long-only gate, no ticker cap:
Status: fail
Passing configs: 0 / 5832
Best: top3, long=+0.001960, excess=-0.000314, hit=33.33%, coverage=25.00%

Long-only gate, max ticker share 67%:
Status: fail
Passing configs: 0 / 5832

Long-only gate, max ticker share 50%:
Status: fail
Passing configs: 0 / 5832
```

Ticker concentration:

```text
Long candidates: TSLA 4, META 3, NVDA 2, MSFT 1, GOOG 1, AAPL 1
Short candidates: MSFT 4, AAPL 3, NVDA 3, TSLA 1, GOOG 1
```

Interpretation:

- The 0.25 concentration penalty materially reduced concentration versus the
  prior TSLA 9/12 long selection.
- The diversification came at too high a cost: long excess turned negative and
  all long-only gates failed, even without ticker caps.
- This rejects the simple HHI penalty as a production candidate at the tested
  strength. It confirms that the current model's apparent edge is concentrated
  in a small subset of names rather than a broad cross-sectional signal.
- Next step should be a different approach: expand/evaluate the universe and
  use walk-forward out-of-sample ticker holdout or sector-neutral residual
  targets, rather than simply penalizing ticker exposure harder.

## 2026-05-09 - Ticker-Holdout Robustness Report

Objective:

- Add a report-only diagnostic that quantifies ticker dependence without
  retraining.
- Replay saved per-date rank-head rankings after excluding each selected ticker
  one at a time, then measure whether long-only excess return survives.

Implementation:

- Added `dl_ticker_holdout_report.py`.
- For each top-N basket, the report records:
  - base long-only excess return and ticker concentration,
  - selected ticker contribution,
  - reranked performance after excluding each selected ticker from every date,
  - worst/median holdout excess and positive holdout rate.

Result:

```text
12-cycle / 8-epoch baseline:
top1: base_excess=+0.017239, worst_holdout=-0.024157, positive_holdouts=60.00%
top2: base_excess=-0.001109, worst_holdout=-0.021271, positive_holdouts=42.86%
top3: base_excess=-0.008996, worst_holdout=-0.017015, positive_holdouts=14.29%

12-cycle / 3-epoch baseline:
top1: base_excess=-0.005461, worst_holdout=-0.024050, positive_holdouts=25.00%
top2: base_excess=-0.020919, worst_holdout=-0.030919, positive_holdouts=0.00%
top3: base_excess=-0.007933, worst_holdout=-0.013859, positive_holdouts=0.00%

12-cycle / 8-epoch topmono + ticker concentration 0.25:
top1: base_excess=-0.007788, worst_holdout=-0.041621, positive_holdouts=33.33%
top2: base_excess=-0.006306, worst_holdout=-0.027027, positive_holdouts=0.00%
top3: base_excess=-0.014109, worst_holdout=-0.018747, positive_holdouts=0.00%
```

Key details:

```text
8-epoch baseline top1:
- Base max ticker share: 50.00%
- Excluding TSLA and reranking: mean excess=-0.024157
- AMZN and TSLA are the primary positive contributors.

Ticker concentration 0.25 top1:
- Base max ticker share: 33.33%
- Base excess already negative.
- Excluding TSLA and reranking: mean excess=-0.041621
```

Interpretation:

- The only positive top-1 baseline is not ticker robust. Its worst leave-one
  selected-ticker rerank is meaningfully negative.
- The ticker-concentration penalty improves selection diversity, but the edge
  turns negative before holdout stress is applied.
- This confirms the current DL rank-head setup does not yet have production
  quality cross-sectional skill. The next work should move to target/data design:
  broader universe coverage and/or residualized targets, then retest with this
  holdout report as a required gate.

## 2026-05-09 - Date-Excess Target Mode Smoke

Objective:

- Add residualized target training to reduce raw single-name drift.
- Train the rank head on `Target_Forward_21D - date_mean(Target_Forward_21D)`
  while leaving realized-return shadow evaluation unchanged.

Implementation:

- Added `--target-mode raw|date_excess` to rank-head experiment,
  walk-forward, and historical blind-loop CLIs.
- Default is `raw`, preserving existing behavior.
- `date_excess` transforms labels inside `_train_one` after loading the panel
  and before train/validation splitting.

Smoke result:

```text
1-cycle / 1-epoch date_excess:
Status: scored
Mean long-short return: +0.171430
Spread hit rate: 100.00%

3-cycle / 3-epoch date_excess + topmono:
Status: scored
Mean long-short return: +0.007426
top1_bottom1: long=+0.027480, long_excess=+0.017318, short_alpha=-0.020054, spread=+0.007426
top2_bottom2: long=+0.024292, long_excess=+0.014130, short_alpha=-0.010499, spread=+0.013793
cap67 long-only gate: fail, 0 / 5832
top1 holdout: base_excess=+0.017318, worst_holdout=-0.012294, positive_holdouts=50.00%
top2 holdout: base_excess=+0.014130, worst_holdout=-0.023617, positive_holdouts=60.00%
Long candidates: TSLA 2, NVDA 1
```

Interpretation:

- Date-excess training is functional and improves the tiny 3-cycle long-excess
  diagnostic versus the ticker-concentration penalty run.
- It still fails the capped long-only gate and remains ticker sensitive on the
  small probe.
- A 12-cycle date-excess run is worth testing as a challenger, but it should be
  judged by the same long-only cap and ticker-holdout reports before any further
  promotion discussion.

## 2026-05-09 - Date-Excess Target Mode 12-Cycle Challenger

Objective:

- Run the full 12-cycle / 8-epoch date-excess target challenger with the same
  top-excess and monotonic rank losses used by the prior topmono variant.
- Evaluate it with diagnostic, long-only gate, capped long-only gates, and
  ticker-holdout reports.

Run:

```text
--cycles 12 --step-days 21 --epochs 8 --seeds 20260505
--val-days 126 --top-n 1 --paper-long-n 1 --paper-short-n 1
--target-mode date_excess
--top-excess-weight 0.5 --top-excess-temperature 0.05
--monotonic-weight 0.05 --monotonic-quantiles 5
```

Result:

```text
Blind loop:
Mean long-short return: +0.018546
Spread hit rate: 50.00%

Diagnostic:
top1_bottom1: long=+0.043322, long_excess=+0.006836, short_alpha=-0.024776, spread=+0.018546, hit=50.00%
top2_bottom2: long=+0.045558, long_excess=+0.009071, short_alpha=-0.039675, spread=+0.005882, hit=66.67%
top3_bottom3: long=+0.032245, long_excess=-0.004241, short_alpha=-0.045954, spread=-0.013710, hit=33.33%

Long-only abstention gate:
No ticker cap: pass, 156 / 5832 configs
Best: top2, long=+0.007594, excess=+0.004705, hit=66.67%, coverage=50.00%

Ticker-capped long-only gates:
cap67: fail, 0 / 5832 configs
cap50: fail, 0 / 5832 configs

Ticker holdout:
top1: base_excess=+0.006836, worst_holdout=+0.007310, positive_holdouts=100.00%
top2: base_excess=+0.009071, worst_holdout=-0.009382, positive_holdouts=60.00%
top3: base_excess=-0.004241, worst_holdout=-0.011557, positive_holdouts=16.67%

Candidate concentration:
Long candidates: TSLA 10, NVDA 2
Short candidates: MSFT 9, AAPL 3
```

Interpretation:

- This is the best challenger so far on ticker-holdout top1 robustness: the
  top1 long-only excess remains positive after removing either selected long
  ticker and reranking.
- The production blocker remains concentration. The 12-cycle top1 book is
  mostly TSLA long and MSFT short, and both cap50 and cap67 gates reject every
  abstention configuration.
- The short leg is still not usable: short alpha is negative across all basket
  sizes, so this remains a long-only research candidate rather than a
  market-neutral candidate.
- Next work should preserve the date-excess target but solve concentration at
  portfolio construction or universe design, not by the tested HHI training
  penalty, which diversified the book but destroyed the edge.

## 2026-05-09 - Cap-Aware Replay on Date-Excess Challenger

Objective:

- Test whether the date-excess model's saved rankings can support a
  concentration-aware long-only construction without retraining.
- Replay the 12-cycle shadow rankings sequentially, selecting fallback names
  when the highest-ranked ticker would breach an expanding ticker exposure cap.

Implementation:

- Added `dl_cap_aware_replay_report.py`.
- The report:
  - reads saved per-date rankings,
  - applies optional score/forecast/validation gates,
  - enforces max ticker share while walking dates in chronological order,
  - records selected average rank, excess return, drawdown, coverage, and
    realized ticker concentration.

Result:

```text
Broad cap-aware grid, min coverage 25%:
Status: pass
Candidate configs: 14580
Passing configs: 1392
Best: top1 cap=67%, long=+0.039155, excess=+0.025747, hit=50.00%, coverage=33.33%, max_slot=50.00%
Ticker counts: TSLA 2, NVDA 1, GOOG 1
Average selected rank: 1.50
Long max drawdown: -7.14%

Stricter coverage check, min coverage 50%:
Status: pass
Candidate configs: 432
Passing configs: 27
Best: top1 cap=50%, long=-0.003574, excess=+0.007721, hit=57.14%, coverage=58.33%, max_slot=42.86%
Ticker counts: TSLA 3, GOOG 2, NVDA 1, META 1
Average selected rank: 1.57
Long max drawdown: -22.73%
```

Interpretation:

- Cap-aware construction fixes the immediate concentration failure on the saved
  12-cycle challenger and can preserve positive excess return.
- The high-return best case trades only 4 of 12 dates. The 7-trade stricter
  coverage case is positive versus the local universe but slightly negative in
  absolute long return.
- This is progress, but not production approval. The next required test is a
  longer historical blind run using the same date-excess model configuration,
  then replaying the same cap-aware construction. The 12-cycle window is too
  small to promote from.

## 2026-05-10 - 36-Cycle Date-Excess Challenger

Objective:

- Expand the date-excess + topmono blind loop from 12 cycles to 36 cycles.
- Re-test the same diagnostic, holdout, long-only, and cap-aware construction
  gates on the longer window.

Result:

```text
Blind loop:
Cycles: 36
Rows: 252
Mean long-short return: +0.011561
Spread hit rate: 50.00%

Diagnostic:
top1_bottom1: long=+0.037167, long_excess=+0.003270, short_alpha=-0.025606, spread=+0.011561, hit=50.00%
top2_bottom2: long=+0.039711, long_excess=+0.005814, short_alpha=-0.035645, spread=+0.004066, hit=55.56%
top3_bottom3: long=+0.034478, long_excess=+0.000580, short_alpha=-0.036568, spread=-0.002090, hit=44.44%

Ticker holdout:
top1: base_excess=+0.003270, worst_holdout=-0.001794, positive_holdouts=80.00%
top2: base_excess=+0.005814, worst_holdout=-0.000645, positive_holdouts=85.71%
top3: base_excess=+0.000580, worst_holdout=-0.004565, positive_holdouts=42.86%

No-cap long-only gate:
Status: pass
Passing configs: 168 / 7290
Best: top2, long=+0.065438, excess=+0.024058, hit=75.00%, coverage=33.33%

Raw long-candidate concentration:
TSLA 26, NVDA 5, META 3, AMZN 1, GOOG 1
```

Cap-aware replay:

```text
Top1 only, min coverage 50%:
Status: fail
Passing configs: 0 / 432
Best: cap=67%, long=+0.106714, excess=+0.051304, hit=50.00%, coverage=16.67%, max_slot=66.67%

Top1 only, min coverage 25%:
Status: fail
Passing configs: 0 / 432
Best: cap=67%, long=+0.106714, excess=+0.051304, hit=50.00%, coverage=16.67%, max_slot=66.67%

Top1/2/3, min coverage 25%:
Status: pass
Passing configs: 96 / 1296
Best: top2 cap=50%, long=+0.057192, excess=+0.037774, hit=77.78%, coverage=25.00%, max_slot=44.44%
Ticker counts: TSLA 8, NVDA 4, META 3, GOOG 3
Average selected rank: 1.61
Long max drawdown: -8.18%

Top1/2/3, min coverage 50%:
Status: fail
Passing configs: 0 / 1296
Best: top1 cap=67%, long=+0.106714, excess=+0.051304, hit=50.00%, coverage=16.67%, max_slot=66.67%
```

Interpretation:

- The 36-cycle result confirms there is a real but sparse long-only signal in
  the date-excess model.
- Top2 is better than top1 on the longer window. It has higher no-cap excess,
  better ticker-holdout stability, and the only cap-aware pass.
- The production blocker is now coverage, not just concentration. Cap-aware
  construction can produce strong positive excess, but only on 25% to 33% of
  dates. It cannot pass the 50% coverage gate.
- This should not be promoted to production yet. The next engineering step is
  to improve signal availability: either broaden the investable universe or add
  a second independent long-only candidate model/gate that can fill the dates
  rejected by the date-excess rank head.

## 2026-05-10 - DL-Only 50-Name Research Universe Setup

Objective:

- Broaden the DL research universe without changing the published forecasting
  page or production MAG7 forecast pipeline.
- Build a separate 50-name large-cap panel that can test whether the
  date-excess rank-head signal has enough diversified alternatives to improve
  cap-aware coverage.

Implementation:

- Added `--ticker-config` support to `build_quantcup_price_dl_panel.py`.
- Used existing `config/research_universe.json`, which contains 50 large-cap
  US equities across technology, healthcare, financials, consumer, energy, and
  industrials.
- Confirmed all 50 configured tickers are already present in the local Quant
  Cup OHLCV cache through 2026-05-06, so no new price download was required.

Panel build:

```text
Output: data/experiment/dl_research_panels/research_universe_50_price_panel.parquet
Rows: 255,850
Tickers: 50
Panel range: 2006-01-03 -> 2026-05-06
Labeled range: 2006-01-03 -> 2026-04-07
```

Smoke test:

```text
1-cycle / 1-epoch default-feature run:
Failed as expected because the price-only panel does not include earnings
features required by the default rank-head extra feature list.

1-cycle / 1-epoch price/market-only feature run:
No schema failure, but exceeded the 5-minute internal CPU timeout.
```

Interpretation:

- The broadened panel is ready for long-run testing, but CPU training on 50
  names is materially slower than the MAG7 research loop.
- Initial broader-universe tests should explicitly pass the price/market feature
  list and should be run as monitored long jobs, not short internal checks.
- The forecasting page remains untouched. This panel is DL research-only.

## 2026-05-11 - Research50 3-Cycle Price-Only Probe

Objective:

- Run the first small blind-loop probe on the 50-name DL-only research panel.
- Use only price/market features because the panel does not include the
  earnings features required by the default rank-head extra feature set.

Result:

```text
Blind loop:
Cycles: 3
Rows: 21
Mean long-short return: -0.035560
Spread hit rate: 33.33%

Diagnostic:
top1_bottom1: long=-0.018471, long_excess=-0.028323, short_alpha=-0.017089, spread=-0.035560, hit=33.33%
top2_bottom2: long=-0.022545, long_excess=-0.032396, short_alpha=-0.000621, spread=-0.023166, hit=0.00%
top3_bottom3: long=+0.006633, long_excess=-0.003218, short_alpha=-0.021647, spread=-0.015014, hit=0.00%

Ticker holdout:
top1: base_excess=-0.028323, worst_holdout=-0.053150, positive_holdouts=0.00%
top2: base_excess=-0.032396, worst_holdout=-0.019762, positive_holdouts=25.00%
top3: base_excess=-0.003218, worst_holdout=-0.016333, positive_holdouts=16.67%

Candidate concentration:
Long candidates: MSFT 1, TSLA 1, GOOG 1
Short candidates: AAPL 3
```

Interpretation:

- The 50-name pipeline is functional, but this 3-cycle / 3-epoch price-only
  probe is not promising.
- Broadening the universe alone did not improve signal availability on the
  tiny probe; it diluted the rank-head edge and the short side concentrated in
  AAPL.
- Do not run a long 36-cycle version of this exact setup yet. The next test
  should either add the cached earnings/event features to the research50 panel
  or reduce the broadened universe to a cleaner liquid tech/large-growth set
  before spending more CPU on long blind loops.

## 2026-05-11 - Growth24 Research Universe Setup

Objective:

- Test the recommended narrower universe path after the 50-name cross-sector
  probe diluted the rank-head signal.
- Build a DL-only universe focused on large-growth, AI, semiconductors,
  infrastructure, and software names while keeping the production forecasting
  page unchanged.

Implementation:

- Added `config/research_growth_universe.json` with 24 tickers.
- Built two panels:
  - `research_growth_24_price_panel.parquet` through 2026-05-06.
  - `research_growth_24_price_panel_20251230.parquet` through 2025-12-30.
- The 2026-05-06 panel was rejected for testing because most non-MAG7 cached
  price series currently stop at 2025-12-30, which leaves incomplete recent
  feature windows and collapses prediction output back to 7 names.
- The 2025-12-30 panel is the correct research panel for now.

Corrected panel:

```text
Output: data/experiment/dl_research_panels/research_growth_24_price_panel_20251230.parquet
Rows: 120,720
Tickers: 24
Panel range: 2006-01-03 -> 2025-12-30
Labeled range: 2006-01-03 -> 2025-11-28
```

Smoke result:

```text
1-cycle / 1-epoch growth24 date_excess:
Decision date: 2025-11-13
Rows emitted: 24
Mean long-short return: +0.099358
Spread hit rate: 100.00%

Diagnostic:
top1_bottom1: long=+0.044556, long_excess=+0.033942, short_alpha=+0.054802, spread=+0.099358, hit=100.00%
top2_bottom2: long=+0.023438, long_excess=+0.012825, short_alpha=+0.055658, spread=+0.079096, hit=100.00%
top3_bottom3: long=+0.037139, long_excess=+0.026525, short_alpha=+0.058207, spread=+0.095346, hit=100.00%
```

Interpretation:

- The corrected growth24 panel restores true cross-sectional breadth and is
  materially more promising than the 50-name cross-sector smoke.
- The one-cycle result is not enough evidence, but it is strong enough to
  justify the planned 3-cycle / 3-epoch probe on this corrected panel.

## 2026-05-11 - Growth24 3-Cycle Probe

Objective:

- Run the first non-smoke blind probe on the corrected 24-name growth panel.
- Keep the model configuration aligned with the current best MAG7 variant:
  `date_excess` target, top-excess loss, monotonic regularization, 3 cycles,
  3 epochs, and explicit price/market/relative features.

Result:

```text
Cycles: 3
Rows: 72
Mean long-short return: +0.041272
Spread hit rate: 66.67%
```

Diagnostic:

```text
top1_bottom1: long=+0.019296, long_excess=-0.006462, short_alpha=+0.021976, spread=+0.041272, hit=66.67%
top2_bottom2: long=+0.003111, long_excess=-0.022647, short_alpha=+0.035434, spread=+0.038545, hit=100.00%
top3_bottom3: long=+0.031863, long_excess=+0.006105, short_alpha=+0.013097, spread=+0.044961, hit=66.67%
```

Gate / concentration checks:

```text
Long-only gate: pass, 3510 / 7290 configs.
Best long-only: top1, long=+0.044556, excess=+0.033942, hit=100.00%, coverage=33.33%.
Cap-aware replay: pass, 216 / 1296 configs.
Best capped replay: top3 cap=50%, long=+0.031863, excess=+0.006105, hit=66.67%, coverage=100.00%, max_slot=33.33%.
```

Candidate concentration:

```text
Long candidates: PLTR 3, MU 2, INTC 2, ORCL 2, LRCX 1, AMD 1, AVGO 1
Short candidates: MSFT 3, ADBE 2, NOW 2, CSCO 2, NVDA 1, AMZN 1, META 1
```

Interpretation:

- Growth24 is clearly better than the 50-name cross-sector price-only probe.
- The long-short spread is positive and the cap-aware top3 replay passes at
  full coverage with no ticker over one-third of long slots.
- The top1 long-only signal is too sparse to trust yet: the holdout report has
  negative base excess for top1 and 0% positive holdouts.
- Next step is a longer 12-cycle / 8-epoch growth24 blind run. If that preserves
  capped top2/top3 excess and coverage, move to 24-36 cycles; if not, revisit
  features or universe composition before production integration.

## 2026-05-11 - Growth24 12-Cycle Probe

Objective:

- Extend the corrected growth24 test from 3 cycles to 12 cycles using the same
  `date_excess` + top-excess + monotonic setup.
- Check whether the broader top2/top3 signal survives more dates and whether
  cap-aware replay can still pass with useful coverage.

Note:

- The run used `--cycles 12 --epochs 8`, but reused the old
  `growth24_3c_3e_date_excess_topmono` output stem. The parquet/csv/summary
  files with that stem now contain the 12-cycle result, not the prior 3-cycle
  probe. Follow-up diagnostics were saved with `growth24_12c_8e...` names.

Result:

```text
Cycles: 12
Rows: 288
Mean long-short return: +0.020203
Spread hit rate: 58.33%
```

Diagnostic:

```text
top1_bottom1: long=+0.019300, long_excess=-0.005681, short_alpha=+0.000903, spread=+0.020203, hit=58.33%
top2_bottom2: long=+0.051973, long_excess=+0.026992, short_alpha=+0.010253, spread=+0.062226, hit=83.33%
top3_bottom3: long=+0.049173, long_excess=+0.024192, short_alpha=-0.000364, spread=+0.048809, hit=66.67%
```

Holdout:

```text
top1: base_excess=-0.005681, worst_holdout=-0.016525, positive_holdouts=33.33%
top2: base_excess=+0.026992, worst_holdout=+0.000162, positive_holdouts=100.00%
top3: base_excess=+0.024192, worst_holdout=+0.005568, positive_holdouts=100.00%
```

Gate / concentration checks:

```text
Long-only gate: fail, 0 / 7290 configs.
Best uncapped long-only: top2, long=+0.025587, excess=+0.024202, hit=66.67%, coverage=50.00%.
Cap-aware replay: pass, 216 / 1296 configs.
Best capped replay: top1 cap=50%, long=+0.125076, excess=+0.124125, hit=57.14%, coverage=58.33%, max_slot=42.86%.
```

Candidate concentration:

```text
Long candidates: PLTR 12, TSLA 8, MU 7, INTC 6, AVGO 6, ORCL 3, AMD 3, LRCX 1, NFLX 1, NVDA 1
Short candidates: CSCO 5, AMZN 5, NOW 4, CRM 4, LRCX 4, AMAT 4, META 3, TXN 3, MSFT 3, ADBE 2, GOOG 2, ORCL 2, QCOM 2, NVDA 1, PANW 1, NFLX 1, INTC 1, AAPL 1
```

Interpretation:

- The 12-cycle result is a meaningful improvement over the MAG7-only production
  candidate because top2/top3 long excess is positive and survives ticker
  holdout with 100% positive holdouts.
- The best capped replay is very strong but still only 7 selected trades out of
  12 dates. That is useful as a research result, but not enough for production.
- The next test should be a 24-cycle / 8-epoch growth24 run with a correctly
  named output stem. If top2/top3 excess remains positive and cap-aware coverage
  stays near or above 50%, then run the final 36-cycle stress window.

## 2026-05-11 - Growth24 24-Cycle Probe

Objective:

- Extend the corrected growth24 test from 12 cycles to 24 cycles.
- Validate whether top2/top3 long excess and cap-aware replay remain viable over
  a broader 2023-12 to 2025-11 blind window.

Note:

- The run again used `growth24_3c_3e_date_excess_topmono` output filenames.
  Those files now contain the 24-cycle result. Diagnostics were saved under
  `growth24_24c_8e...` names.

Result:

```text
Cycles: 24
Rows: 576
Mean long-short return: +0.033617
Spread hit rate: 58.33%
```

Diagnostic:

```text
top1_bottom1: long=+0.039730, long_excess=+0.010190, short_alpha=-0.006113, spread=+0.033617, hit=58.33%
top2_bottom2: long=+0.063363, long_excess=+0.033823, short_alpha=-0.003450, spread=+0.059913, hit=79.17%
top3_bottom3: long=+0.059604, long_excess=+0.030063, short_alpha=-0.016032, spread=+0.043572, hit=70.83%
```

Holdout:

```text
top1: base_excess=+0.010190, worst_holdout=-0.003348, positive_holdouts=80.00%
top2: base_excess=+0.033823, worst_holdout=+0.009053, positive_holdouts=100.00%
top3: base_excess=+0.030063, worst_holdout=+0.016427, positive_holdouts=100.00%
```

Gate / concentration checks:

```text
Default long-only gate: fail, 0 / 7290 configs.
Default cap-aware replay: fail, 0 / 1296 configs.
Best default capped replay: top2 cap=67%, long=+0.048313, excess=+0.028484, hit=71.43%, coverage=58.33%, max_slot=39.29%.
Default failure reason: long drawdown -29.53% < -25.00%.

Drawdown sensitivity at -35%:
Long-only gate: pass, 4860 / 7290 configs.
Cap-aware replay: pass, 864 / 1296 configs.
Best capped replay: top2 cap=67%, long=+0.048313, excess=+0.028484, hit=71.43%, coverage=58.33%, max_slot=39.29%.
```

Candidate concentration:

```text
Long candidates: PLTR 23, TSLA 13, INTC 12, NVDA 10, AMD 9, MU 8, AVGO 7, META 3, NFLX 3, ORCL 3, PANW 2, LRCX 1, CRM 1, CSCO 1
Short candidates: TXN 10, AMZN 9, LRCX 7, NOW 7, AMAT 7, CSCO 7, MSFT 5, SNPS 5, CRM 4, GOOG 4, MU 4, META 4, ADBE 3, QCOM 3, TSLA 3, AAPL 3, ORCL 2, NFLX 2, INTC 2, PANW 2, AMD 2, NVDA 1
```

Interpretation:

- The signal strengthened at 24 cycles. Top2/top3 long excess is positive,
  hit rates are high, and ticker holdout robustness is materially better than
  the earlier MAG7-only candidate.
- The default production-style gate fails only because long drawdown reaches
  -29.53%, just beyond the current -25% threshold. Excess drawdown is -18.70%,
  which is more acceptable for the intended date-excess target.
- Do not loosen production gates yet. Use this as evidence to run the 36-cycle
  stress window with correct filenames, then decide whether growth24 needs a
  separate high-vol growth gate or additional risk controls.

## 2026-05-12 - Growth24 36-Cycle Stress Window

Objective:

- Run the final growth24 stress window using correct `growth24_36c_8e...`
  artifact names.
- Decide whether the 24-name growth universe is a credible successor candidate
  to the MAG7-only rank-head path.

Result:

```text
Cycles: 36
Rows: 864
Mean long-short return: +0.050499
Spread hit rate: 66.67%
```

Diagnostic:

```text
top1_bottom1: long=+0.062246, long_excess=+0.026787, short_alpha=-0.011747, spread=+0.050499, hit=66.67%
top2_bottom2: long=+0.078816, long_excess=+0.043357, short_alpha=-0.016748, spread=+0.062067, hit=75.00%
top3_bottom3: long=+0.068010, long_excess=+0.032551, short_alpha=-0.026529, spread=+0.041481, hit=66.67%
```

Holdout:

```text
top1: base_excess=+0.026787, worst_holdout=+0.012032, positive_holdouts=100.00%
top2: base_excess=+0.043357, worst_holdout=+0.015524, positive_holdouts=100.00%
top3: base_excess=+0.032551, worst_holdout=+0.016631, positive_holdouts=100.00%
```

Gate / concentration checks:

```text
Default long-only gate: fail, 0 / 7290 configs.
Default cap-aware replay: fail, 0 / 1296 configs.
Default failure reason: long drawdown -29.53% < -25.00%.

Best default capped replay:
top2 cap=50%, long=+0.089333, excess=+0.055655, hit=71.43%, coverage=77.78%, max_slot=37.50%, long_dd=-29.53%, excess_dd=-22.66%.

Drawdown sensitivity at -35%:
Long-only gate: pass, 4860 / 7290 configs.
Cap-aware replay: pass, 864 / 1296 configs.
Cap50-only replay: pass, 432 / 648 configs.
Best capped replay: top2 cap=50%, long=+0.089333, excess=+0.055655, hit=71.43%, coverage=77.78%, max_slot=37.50%.
```

Candidate concentration:

```text
Long candidates: PLTR 32, TSLA 22, NVDA 20, AMD 12, INTC 12, META 10, NFLX 8, MU 8, AVGO 7, PANW 5, ORCL 4, CSCO 2, LRCX 1, CRM 1
Short candidates: TXN 14, AMAT 13, AMZN 11, CSCO 10, LRCX 10, MSFT 10, NOW 9, CRM 8, SNPS 7, AAPL 7, QCOM 6, MU 6, GOOG 5, AMD 4, META 4, ADBE 3, TSLA 3, NFLX 3, ORCL 3, PANW 3, AVGO 2, INTC 2, NVDA 1
```

Interpretation:

- This is the strongest DL rank-head research result so far. Top1/top2/top3
  all have positive long excess, positive worst ticker holdouts, and 100%
  positive holdout rates.
- The cap-aware top2 replay is attractive: 28 selected trades over 36 cycles,
  77.78% coverage, 71.43% excess hit rate, 37.50% max slot concentration, and
  +5.57% mean excess return.
- The blocker is risk policy rather than raw alpha: the default -25% long
  drawdown threshold fails by 4.53 percentage points. A -35% drawdown threshold
  passes cleanly, including cap50-only replay.
- Next step: do not merge this directly into production yet. Freeze the
  growth24 candidate configuration and run a current-date shadow forecast /
  paper ledger path with explicit cap-aware selection and a high-vol growth
  risk gate.

## 2026-05-12 - Growth24 Shadow/Paper Path

Objective:

- Create a separate current-date growth24 DL shadow/paper path without touching
  the main forecast page.
- Freeze the candidate policy from the 36-cycle stress window:
  `date_excess`, top-excess weight 0.5, monotonic weight 0.05, top2 paper
  selection, cap-aware max ticker share 50%, and a high-vol growth risk gate
  using -35% max drawdown research tolerance.

Implementation:

- Added `dl_growth24_shadow_paper.py`.
- The script trains on matured labels only, forecasts the latest available
  panel date, writes a current shadow forecast, appends a shadow forecast log,
  applies cap-aware top2 paper selection, and appends a paper plan log.
- Artifacts are kept separate under:
  - `data/experiment/growth24_shadow_paper/`
  - `models/experiment/growth24_shadow_paper/`

Smoke test:

```text
Command: 1 epoch CPU smoke
Status: selected
AsOfDate: 2025-12-30
Train labels through: 2025-11-28
Selected long tickers: MU, INTC
```

Interpretation:

- The new path is wired and can produce a current shadow forecast plus paper
  plan.
- The smoke output should not be treated as the official candidate because it
  used only one training epoch. The next run should use the full frozen 8-epoch
  configuration.

Full 8-epoch shadow run:

```text
Status: selected
AsOfDate: 2025-12-30
Train labels through: 2025-11-28
Selected long tickers: MU, INTC
Universe count: 24
Paper top N: 2
Max ticker share: 50.00%
Validation selection score: 0.513904
Validation daily IC: 0.219351
Validation spread: 0.064067
Validation spread positive rate: 76.12%
```

Top forecast ranks:

```text
1. MU
2. INTC
3. AMD
4. LRCX
5. PLTR
6. AMAT
7. TSLA
8. SNPS
```

## 2026-05-12 - Growth24 Panel Refresh

Objective:

- Update the growth24 price-first DL panel to the current local date without
  collapsing the live universe breadth.

Issue found:

- A direct rebuild of `research_growth_24_price_panel.parquet` extended the
  panel to 2026-05-06, but the underlying Quant Cup OHLCV cache only had valid
  latest closes for 7 of 24 growth tickers.
- The affected missing latest closes were the non-MAG7 names, which caused the
  current shadow smoke to emit only 7 forecast rows and block paper selection.

Fix:

- Added `refresh_growth24_price_cache.py` to patch the existing Quant Cup OHLCV
  parquet caches for the configured growth24 tickers while preserving other
  cached columns.
- Refreshed growth24 OHLCV values for 2025-12-01 through 2026-05-12.
- Rebuilt `data/experiment/dl_research_panels/research_growth_24_price_panel.parquet`.

Updated panel:

```text
Rows: 122,904
Panel range: 2006-01-03 -> 2026-05-12
Labeled range: 2006-01-03 -> 2026-04-13
Latest date valid closes: 24/24
```

Current-date smoke after refresh:

```text
Command: dl_growth24_shadow_paper.py --epochs 1 --device cpu --asof-date 2026-05-12
Status: blocked
AsOfDate: 2026-05-12
Train labels through: 2026-04-13
Gate failure: validation score 0.103832 < 0.250000
Top ranks: INTC, MU, AMD, LRCX, AMAT, QCOM, AVGO, TXN
```

Interpretation:

- The data breadth problem is fixed: the live shadow path now forecasts all 24
  growth names on the refreshed panel.
- The one-epoch smoke is intentionally not a candidate selection run. Use the
  full frozen 8-epoch shadow/paper run before recording a live paper plan.

Full 8-epoch current shadow/paper run:

```text
Command: dl_growth24_shadow_paper.py --device cpu
Status: selected
AsOfDate: 2026-05-12
Train labels through: 2026-04-13
Validation daily IC: 0.2064
Validation spread: 0.1490
Validation spread positive rate: 80.60%
Raw top candidates: MU, INTC
Selected paper longs: LRCX, NOW
```

Top forecast ranks:

```text
1. MU
2. INTC
3. LRCX
4. NOW
5. AMD
6. AMAT
7. NFLX
8. PLTR
```

Interpretation:

- The refreshed 24-name panel produced a gate-clean full run.
- The cap-aware paper ledger selected `LRCX,NOW` instead of the raw top two
  `MU,INTC` because `MU,INTC` already occupied the prior paper slots and the
  current policy caps ticker share at 50%.

## 2026-05-12 - Growth24 Paper Outcome Ledger

Objective:

- Add the next feedback loop for the DL shadow/paper path: automatically score
  selected paper plans once their 21-trading-day labels mature.

Implementation:

- Added `dl_growth24_paper_outcome.py`.
- The script reads the paper plan log, joins selected tickers to the refreshed
  growth24 panel, attaches forecast rank/score details from the forecast log,
  and writes:
  - `data/experiment/growth24_shadow_paper/growth24_paper_outcome_trades.csv`
  - `data/experiment/growth24_shadow_paper/growth24_paper_outcome_summary.json`

Current score:

```text
Command: dl_growth24_paper_outcome.py
Trade rows: 4
Matured trades: 2
Pending trades: 2
Matured plan: 2025-12-30 -> MU, INTC
Pending plan: 2026-05-12 -> LRCX, NOW
Mean matured forward 21D: +33.18%
Mean matured excess 21D: +28.26%
Hit rate: 100.00%
Excess hit rate: 100.00%
```

Interpretation:

- The first growth24 paper selection matured cleanly and beat the market proxy.
- The current selected plan remains pending until the 21-trading-day forward
  label becomes available in the panel.

## 2026-05-14 - Refreshed Growth24 36-Cycle Gate Reports

Objective:

- Finish the refreshed Growth24 36-cycle stress rerun after the overnight
  laptop reset interrupted the first attempt.
- Re-run the diagnostic, ticker-holdout, long-only gate, and cap-aware replay
  reports against the refreshed 24-name panel artifact.

Completed refreshed run:

```text
Command family: dl_rank_head_historical_blind_loop.py
Output stem: growth24_36c_8e_date_excess_topmono_refreshed
Status: scored
Cycles: 36
Rows: 864
Date range: 2023-04-12 -> 2026-03-18
Tickers per cycle: 24 / 24
Mean long return: +8.36%
Mean short return: +2.74%
Mean long-short return: +5.62%
Spread hit rate: 66.67%
Max drawdown: -22.66%
```

Diagnostic:

```text
top1_bottom1: long=+0.066692, long_excess=+0.033971, short_alpha=-0.014540, spread=+0.052152, hit=63.89%
top2_bottom2: long=+0.083598, long_excess=+0.050877, short_alpha=-0.027392, spread=+0.056206, hit=66.67%
top3_bottom3: long=+0.088882, long_excess=+0.056161, short_alpha=-0.019751, spread=+0.069131, hit=80.56%
```

Ticker holdout:

```text
top1: base_excess=+0.033971, worst_holdout=+0.032678, positive_holdouts=100.00%
top2: base_excess=+0.050877, worst_holdout=+0.042931, positive_holdouts=100.00%
top3: base_excess=+0.056161, worst_holdout=+0.038583, positive_holdouts=100.00%
```

Gate / concentration checks:

```text
Default long-only gate: fail, 0 / 7290 configs.
Best default long-only: top3, long=+0.089302, excess=+0.060585, hit=70.97%, coverage=86.11%.

High-vol growth long-only gate at -35% drawdown: pass, 4860 / 7290 configs.
Best high-vol growth long-only: top3, long=+0.089302, excess=+0.060585, hit=70.97%, coverage=86.11%.

Default cap-aware replay, max ticker share 50%: fail, 0 / 7290 configs.
Best default cap-aware: top3 cap=50%, long=+0.089302, excess=+0.060585, hit=70.97%, coverage=86.11%, max_slot=29.03%.

High-vol growth cap-aware replay at -35% drawdown, max ticker share 50%: pass, 4860 / 7290 configs.
Best high-vol growth cap-aware: top3 cap=50%, long=+0.089302, excess=+0.060585, hit=70.97%, coverage=86.11%, max_slot=29.03%.
```

Artifacts:

```text
data/experiment/historical_blind_rank_head/growth24_36c_8e_date_excess_topmono_refreshed_shadow_log.parquet
data/experiment/historical_blind_rank_head/growth24_36c_8e_date_excess_topmono_refreshed_summary.json
notes/dl_shadow_diagnostic_growth24_36c_8e_date_excess_topmono_refreshed.md
notes/dl_ticker_holdout_growth24_36c_8e_date_excess_topmono_refreshed.md
notes/dl_long_only_gate_growth24_36c_8e_date_excess_topmono_refreshed.md
notes/dl_long_only_gate_growth24_36c_8e_date_excess_topmono_refreshed_dd35.md
notes/dl_cap_aware_replay_growth24_36c_8e_date_excess_topmono_refreshed_cov50.md
notes/dl_cap_aware_replay_growth24_36c_8e_date_excess_topmono_refreshed_cov50_dd35.md
```

Interpretation:

- The refreshed 36-cycle result strengthens the Growth24 candidate. Top1,
  top2, and top3 long excess are all positive, and all ticker-holdout tests
  remain positive with 100% positive holdout rates.
- The default production gate still rejects the strategy because the drawdown
  policy is too tight for this high-vol growth universe.
- The explicit high-vol growth gate at -35% drawdown passes cleanly, including
  the cap-aware 50% max ticker-share replay.
- Promotion should use the separate Growth24 shadow/paper path and high-vol
  growth risk gate rather than merging this directly into the default
  production DL forecast gate.

## 2026-05-14 - Growth24 Top3 Shadow/Paper Promotion

Objective:

- Promote Growth24 only inside the separate shadow/paper lane using the
  refreshed 36-cycle policy: top3 longs, 50% max ticker-share cap, and the
  high-vol growth drawdown gate at -35%.

Implementation:

- Updated `dl_growth24_shadow_paper.py` defaults to
  `Growth24RankHeadShadowTop3` and `--paper-top-n 3`.
- Added explicit policy metadata to the shadow summary and paper plan:
  `growth24_36c_8e_date_excess_topmono_refreshed`, diagnostic top3 excess
  `+5.62%` / hit `80.56%`, and cap-aware top3 cap50 excess `+6.06%` /
  coverage `86.11%` / max slot `29.03%`.

Current top3 shadow/paper run:

```text
Command: dl_growth24_shadow_paper.py --device cpu
Status: selected
AsOfDate: 2026-05-12
Train labels through: 2026-04-13
Model: Growth24RankHeadShadowTop3
PaperTopN: 3
Max ticker share: 50.00%
Risk gate max drawdown: -35.00%
Selected paper longs: MU, INTC, LRCX
Post-selection max ticker share: 28.57%
Validation daily IC: 0.2321
Validation spread: 0.1622
Validation spread positive rate: 85.07%
```

Paper outcome refresh:

```text
Command: dl_growth24_paper_outcome.py
Trade rows: 7
Matured trades: 2
Pending trades: 5
Matured plan: 2025-12-30 -> MU, INTC
Pending plan set: 2026-05-12
Mean matured forward 21D: +33.18%
Mean matured excess 21D: +28.26%
Hit rate: 100.00%
Excess hit rate: 100.00%
```

Interpretation:

- The new top3 policy stays isolated to the Growth24 shadow/paper lane.
- Existing top2 paper rows remain in the audit ledger.
- The new top3 `2026-05-12` trades remain pending until the 21-trading-day
  outcome label matures.

## 2026-05-14 - AV / Quant Cup Refresh and Earnings-Feature DL Probe

Objective:

- Continue validation without promoting the DL model to production.
- Trigger the next Alpha Vantage earnings cache download.
- Refresh Quant Cup prices through the current local market date and test
  whether AV/Quant Cup earnings features can feed the Growth24 DL lane.

AV cache:

```text
Before download: 407 / 503 cached, 96 missing.
After download: 431 / 503 cached, 72 missing.
Status: daily Alpha Vantage limit reached after 24 additional cached tickers.
Growth24 AV coverage: 22 / 24 cached; TSLA and TXN remain missing.
```

Quant Cup price cache:

```text
Refresh: full current S&P 500 ticker set from 2026-05-13 through 2026-05-14.
Close/Open/High/Low/Volume max date: 2026-05-14.
Current S&P 500 valid closes on 2026-05-14: 502 / 503.
Missing latest close: CTRA.
```

Current-date Quant Cup dev tournament:

```text
Command: quant_cup/tournament.py --dev --end 2026-05-14 --output round1_dev_20260514.json
Earnings source: AlphaVantage cache, partial 431-ticker coverage.
SPY baseline CAGR: 14.97%

1. PEAD: CAGR=24.30%, Sharpe=1.28, MaxDD=-18.13%, beats SPY=yes
2. OVERNIGHT: CAGR=21.14%, Sharpe=1.30, MaxDD=-27.51%, beats SPY=yes
3. MOMENTUM: CAGR=13.07%, Sharpe=0.58, MaxDD=-29.19%, beats SPY=no
```

Earnings-enhanced Growth24 DL panel:

```text
Output: data/experiment/dl_research_panels/research_growth_24_price_earnings_av_panel.parquet
Rows: 122,952
Panel range: 2006-01-03 -> 2026-05-14
Labeled range: 2006-01-03 -> 2026-04-15
Earnings feature availability: roughly 81-84% for non-indicator earnings fields.
```

Earnings-enhanced DL 8-epoch current shadow probe:

```text
Command: dl_growth24_shadow_paper.py with AV earnings features, isolated outputs
Status: selected
AsOfDate: 2026-05-14
Train labels through: 2026-04-15
Universe count: 22
Selected paper longs: INTC, MU, AMD
Validation selection score: 0.5114
Validation daily IC: 0.1082
Validation spread: 0.1277
Validation spread positive rate: 79.10%
Outcome rows: 3 pending, 0 matured
```

Interpretation:

- Quant Cup price data is current enough for current-date testing, with one
  current S&P 500 latest-close miss.
- AV is still not complete. Continue the AV download loop until the remaining
  72 tickers are cached.
- PEAD is currently the strongest Quant Cup dev result, but the result uses a
  partial AV cache and should be rerun after AV completion.
- The AV earnings feature path works mechanically for DL, but it is not yet a
  production candidate because two Growth24 names are missing earnings cache and
  the run only has pending paper outcomes.
- Treat the existing price-only Growth24 top3 shadow lane as the primary paper
  candidate; treat the earnings-enhanced lane as a challenger that needs a full
  historical blind-loop replay after AV completion.

## 2026-05-14 - Growth24 Alternate-Seed Robustness Pilot

Objective:

- Continue DL-only model validation while waiting for the Alpha Vantage cache to
  complete.
- Test whether the Growth24 price-only topmono setup still looks constructive
  under alternate seeds before spending overnight time on a larger multi-seed
  blind loop.

Attempted larger run:

```text
Command: 12 cycles, 8 epochs, seeds 20260506 and 20260507
Status: stopped by interactive timeout during cycle 3 before the combined
shadow log was written.
Note: this size should be treated as an overnight job.
```

Completed scored pilot:

```text
Command: dl_rank_head_historical_blind_loop.py
Panel: research_growth_24_price_panel.parquet
Cycles: 3
Epochs: 3
Seeds: 20260506,20260507
Target mode: date_excess
Top-excess weight: 0.5
Monotonic weight: 0.05
Rows: 72
Mean long-short return: +12.10%
Spread hit rate: 66.67%
```

Diagnostic:

```text
top1_bottom1: long=+10.95%, long_excess=+9.25%, short_alpha=+1.15%, spread=+12.10%, hit=66.67%
top2_bottom2: long=+9.60%, long_excess=+7.90%, short_alpha=+0.32%, spread=+9.92%, hit=100.00%
top3_bottom3: long=+7.53%, long_excess=+5.83%, short_alpha=-0.66%, spread=+6.87%, hit=66.67%
```

Ticker holdout:

```text
top1: base_excess=+9.25%, worst_holdout=+6.96%, positive_holdouts=100.00%
top2: base_excess=+7.90%, worst_holdout=+2.64%, positive_holdouts=100.00%
top3: base_excess=+5.83%, worst_holdout=+0.51%, positive_holdouts=100.00%
```

High-vol growth gate:

```text
Long-only gate at -35% drawdown: pass, 6480 / 7290 configs.
Best long-only: top2, long=+25.36%, excess=+14.68%, hit=100.00%, coverage=33.33%.

Cap-aware replay at -35% drawdown, max ticker share 50%: pass, 6480 / 7290 configs.
Best cap-aware: top2 cap=50%, long=+25.36%, excess=+14.68%, hit=100.00%, coverage=33.33%, max_slot=50.00%.
```

Artifacts:

```text
data/experiment/historical_blind_rank_head/growth24_3c_3e_date_excess_topmono_seedrobust_2seed_shadow_log.parquet
data/experiment/historical_blind_rank_head/growth24_3c_3e_date_excess_topmono_seedrobust_2seed_summary.json
notes/dl_shadow_diagnostic_growth24_3c_3e_date_excess_topmono_seedrobust_2seed.md
notes/dl_ticker_holdout_growth24_3c_3e_date_excess_topmono_seedrobust_2seed.md
notes/dl_long_only_gate_growth24_3c_3e_date_excess_topmono_seedrobust_2seed_dd35.md
notes/dl_cap_aware_replay_growth24_3c_3e_date_excess_topmono_seedrobust_2seed_cov50_dd35.md
```

Interpretation:

- The alternate-seed pilot supports the Growth24 signal: top1/top2/top3 excess
  remain positive and ticker holdouts stay positive.
- The sample is intentionally small, so this is not a promotion result.
- The next DL-only validation step should be an overnight 12-cycle or 36-cycle
  alternate-seed replay with full 8-epoch training, then the same diagnostic,
  holdout, long-only, and cap-aware reports.

## 2026-05-16 - Growth24 12-Cycle Alternate-Seed Overnight Replay

Objective:

- Run the full 12-cycle alternate-seed robustness replay while holding the full
  Quant Cup rerun until the Alpha Vantage cache completes.
- Keep the test on the price-only Growth24 panel and the validated topmono /
  date-excess setup.

Completed replay:

```text
Command: scripts/run_growth24_12c_seedrobust_overnight.ps1
Panel: research_growth_24_price_panel.parquet
Cycles: 12
Epochs: 8
Seeds: 20260506,20260507
Target mode: date_excess
Top-excess weight: 0.5
Monotonic weight: 0.05
Rows: 288
Mean long-short return: +6.60%
Spread hit rate: 66.67%
```

Diagnostic:

```text
top1_bottom1: long=+9.05%, long_excess=+4.55%, short_alpha=-2.46%, spread=+6.60%, hit=66.67%
top2_bottom2: long=+8.39%, long_excess=+3.89%, short_alpha=-3.15%, spread=+5.24%, hit=58.33%
top3_bottom3: long=+7.99%, long_excess=+3.49%, short_alpha=-2.13%, spread=+5.86%, hit=75.00%
```

Ticker holdout:

```text
top1: base_excess=+4.55%, worst_holdout=+1.82%, positive_holdouts=100.00%
top2: base_excess=+3.89%, worst_holdout=+2.07%, positive_holdouts=100.00%
top3: base_excess=+3.49%, worst_holdout=+2.14%, positive_holdouts=100.00%
```

High-vol growth gate:

```text
Long-only gate at -35% drawdown: pass, 6470 / 7290 configs.
Best long-only: top1, long=+10.09%, excess=+7.51%, hit=71.43%, coverage=58.33%.

Cap-aware replay at -35% drawdown, max ticker share 50%: pass, 5930 / 7290 configs.
Best cap-aware: top1 cap=50%, long=+9.57%, excess=+6.68%, hit=75.00%, coverage=66.67%, max_slot=37.50%.
```

Artifacts:

```text
data/experiment/historical_blind_rank_head/growth24_12c_8e_date_excess_topmono_seedrobust_2seed_overnight_shadow_log.parquet
data/experiment/historical_blind_rank_head/growth24_12c_8e_date_excess_topmono_seedrobust_2seed_overnight_summary.json
notes/dl_shadow_diagnostic_growth24_12c_8e_date_excess_topmono_seedrobust_2seed_overnight.md
notes/dl_ticker_holdout_growth24_12c_8e_date_excess_topmono_seedrobust_2seed_overnight.md
notes/dl_long_only_gate_growth24_12c_8e_date_excess_topmono_seedrobust_2seed_overnight_dd35.md
notes/dl_cap_aware_replay_growth24_12c_8e_date_excess_topmono_seedrobust_2seed_overnight_cov50_dd35.md
```

Interpretation:

- The 12-cycle alternate-seed replay supports the Growth24 signal. Long excess
  is positive for top1/top2/top3, ticker holdouts are all positive, and the
  high-vol growth cap-aware gate passes.
- The best capped replay is top1 rather than top3 on this shorter alternate-seed
  window, so the current live top3 paper lane should not be changed from this
  result alone.
- Next serious validation step: run a 36-cycle alternate-seed replay before any
  production promotion discussion.

## 2026-05-17 - Growth24 36-Cycle Alternate-Seed Replay

Objective:

- Validate the Growth24 price-only topmono setup over the full 36-cycle stress
  window with alternate seeds `20260506,20260507`.
- Compare against the refreshed single-seed 36-cycle result before making any
  production-readiness decision.

Completed replay:

```text
Command: scripts/run_growth24_36c_seedrobust_overnight.ps1
Panel: research_growth_24_price_panel.parquet
Cycles: 36
Epochs: 8
Seeds: 20260506,20260507
Target mode: date_excess
Top-excess weight: 0.5
Monotonic weight: 0.05
Rows: 864
Mean long-short return: +2.96%
Spread hit rate: 55.56%
```

Diagnostic:

```text
top1_bottom1: long=+4.91%, long_excess=+1.64%, short_alpha=-1.95%, spread=+2.96%, hit=55.56%
top2_bottom2: long=+5.99%, long_excess=+2.72%, short_alpha=-2.33%, spread=+3.67%, hit=55.56%
top3_bottom3: long=+6.94%, long_excess=+3.67%, short_alpha=-1.49%, spread=+5.45%, hit=69.44%
```

Ticker holdout:

```text
top1: base_excess=+1.64%, worst_holdout=-2.21%, positive_holdouts=85.71%
top2: base_excess=+2.72%, worst_holdout=+1.40%, positive_holdouts=100.00%
top3: base_excess=+3.67%, worst_holdout=+3.30%, positive_holdouts=100.00%
```

High-vol growth gate:

```text
Long-only gate at -35% drawdown: pass, 3690 / 7290 configs.
Best long-only: top3, long=+8.41%, excess=+5.66%, hit=64.71%, coverage=47.22%.

Cap-aware replay at -35% drawdown, max ticker share 50%: pass, 3690 / 7290 configs.
Best cap-aware: top3 cap=50%, long=+8.41%, excess=+5.66%, hit=64.71%, coverage=47.22%, max_slot=29.41%.
```

Artifacts:

```text
data/experiment/historical_blind_rank_head/growth24_36c_8e_date_excess_topmono_seedrobust_2seed_overnight_shadow_log.parquet
data/experiment/historical_blind_rank_head/growth24_36c_8e_date_excess_topmono_seedrobust_2seed_overnight_summary.json
notes/dl_shadow_diagnostic_growth24_36c_8e_date_excess_topmono_seedrobust_2seed_overnight.md
notes/dl_ticker_holdout_growth24_36c_8e_date_excess_topmono_seedrobust_2seed_overnight.md
notes/dl_long_only_gate_growth24_36c_8e_date_excess_topmono_seedrobust_2seed_overnight_dd35.md
notes/dl_cap_aware_replay_growth24_36c_8e_date_excess_topmono_seedrobust_2seed_overnight_cov50_dd35.md
```

Interpretation:

- The alternate-seed 36-cycle replay is weaker than the refreshed single-seed
  replay on headline long-short spread and hit rate, but it still supports the
  separate Growth24 top3 shadow lane.
- Top3 is the robust basket under this replay: positive long excess, positive
  worst ticker holdout, 100% positive holdouts, and a passing cap-aware 50%
  ticker-share gate under the -35% high-vol growth drawdown policy.
- Top1 is not robust enough on this replay because its ticker holdout turns
  negative.
- This result strengthens the case for continuing top3 paper trading, but it is
  still not enough by itself to promote to production capital. Wait for the live
  top3 paper outcome cycle to mature and compare it with the historical gate.

## 2026-05-17 - Quant Cup AV-Complete Baseline

Objective:

- Run the full Quant Cup after the Alpha Vantage earnings cache was refreshed,
  using the point-in-time S&P 500 universe through `2026-05-14`.
- Use the result to decide which external signals should be tested in the
  Growth24 DL feature set.

Completed run:

```text
Command: python quant_cup/tournament.py --end 2026-05-14 --output round1_av_complete_20260514.json
Universe: point-in-time S&P 500 composition, 849 historical tickers
Earnings source: Alpha Vantage cache
Saved result: quant_cup/results/round1_av_complete_20260514.json
```

Leaderboard:

```text
1. PEAD              CAGR=+31.60%, Sharpe=1.69, MaxDD=-20.33%, Beats SPY=YES
2. OVERNIGHT         CAGR=+21.05%, Sharpe=1.51, MaxDD=-27.64%, Beats SPY=YES
3. PAIRS_DIVERGE     CAGR= +6.58%, Sharpe=0.65, MaxDD=-28.28%, Beats SPY=no
4. MEAN_REVERT       CAGR= +3.67%, Sharpe=0.27, MaxDD=-42.87%, Beats SPY=no
5. PAIRS_Z           CAGR= +2.85%, Sharpe=0.31, MaxDD=-47.98%, Beats SPY=no
6. MOMENTUM          CAGR= -1.57%, Sharpe=0.08, MaxDD=-87.34%, Beats SPY=no
7. VOL_COMPRESSION   CAGR=-11.72%, Sharpe=-0.13, MaxDD=-96.87%, Beats SPY=no
8. GAP_CONTINUATION  CAGR=-63.98%, Sharpe=-0.84, MaxDD=-100.00%, Beats SPY=no
```

Interpretation:

- PEAD is the strongest Quant Cup baseline by a wide margin and is the cleanest
  evidence that earnings/post-earnings behavior should be tested as DL input.
- OVERNIGHT is also strong, but PEAD has the better return, Sharpe, drawdown,
  and year-by-year consistency in this run.
- This does not make the DL model production-ready. It identifies the highest
  value feature family to validate inside the existing blind Growth24 replay
  loop.
- Next DL step: run a 12-cycle feature replay with RSI/MA/Volume plus AV
  earnings features, then only promote to a 36-cycle replay if the 12-cycle
  result holds up under cap-aware and ticker-holdout checks.

## 2026-05-18 - Growth24 12-Cycle Earnings Feature Replay

Objective:

- Test whether the RSI/MA/Volume plus Alpha Vantage earnings feature set still
  holds up beyond the 3-cycle smoke test.
- Use the same seed-robust replay controls as the prior serious Growth24
  overnight tests.

Completed replay:

```text
Command: scripts/run_growth24_feature_probe_12c.ps1
Panel: research_growth_24_price_earnings_av_panel.parquet
Features: existing Growth24 extras + RSI_14, MA_20, MA_50, MA_200, Volume, AV earnings features
Cycles: 12
Epochs: 8
Seeds: 20260506,20260507
Target mode: date_excess
Rows: 284
Mean long-short return: +15.05%
Spread hit rate: 91.67%
```

Diagnostic:

```text
top1_bottom1: long=+13.42%, long_excess=+9.08%, short_alpha=+1.64%, spread=+15.05%, hit=91.67%
top2_bottom2: long= +9.22%, long_excess=+4.89%, short_alpha=-1.96%, spread= +7.27%, hit=75.00%
top3_bottom3: long=+10.35%, long_excess=+6.02%, short_alpha=-4.08%, spread= +6.27%, hit=66.67%
```

Ticker holdout:

```text
top1: base_excess=+9.08%, worst_holdout=+5.20%, positive_holdouts=100.00%
top2: base_excess=+4.89%, worst_holdout=+4.22%, positive_holdouts=100.00%
top3: base_excess=+6.02%, worst_holdout=+3.14%, positive_holdouts=100.00%
```

High-vol growth gate:

```text
Long-only gate at -35% drawdown: pass, 4320 / 7290 configs.
Best long-only: top1, long=+21.64%, excess=+15.82%, hit=60.00%, coverage=41.67%, max_ticker=40.00%, DD=-3.90%.

Cap-aware replay at -35% drawdown, max ticker share 50%: pass, 4815 / 7290 configs.
Best cap-aware: top1 cap=50%, long=+20.50%, excess=+14.68%, hit=60.00%, coverage=41.67%, max_slot=40.00%, DD=-9.61%.
```

Artifacts:

```text
data/experiment/historical_blind_rank_head/growth24_12c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_shadow_log.parquet
data/experiment/historical_blind_rank_head/growth24_12c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_summary.json
notes/dl_shadow_diagnostic_growth24_12c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed.md
notes/dl_ticker_holdout_growth24_12c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed.md
notes/dl_long_only_gate_growth24_12c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_dd35.md
notes/dl_cap_aware_replay_growth24_12c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_cov50_dd35.md
```

Interpretation:

- The earnings feature replay passes the 12-cycle qualifier and is materially
  stronger than the prior price-only 12-cycle replay.
- Top1 is strongest in this 12-cycle run, including ticker holdout and
  cap-aware gates, but it is concentrated in high-vol growth names. It should
  not replace the current top3 paper lane from this result alone.
- Advance this candidate to a 36-cycle replay. If the 36-cycle result holds,
  move it into a Final 4 stress-test bracket against the current Growth24 top3
  lane and the strongest Quant Cup baselines.

## 2026-05-19 - Growth24 36-Cycle Earnings Feature Replay

Objective:

- Test the RSI/MA/Volume plus Alpha Vantage earnings feature candidate across
  the full 36-cycle blind replay window.
- Decide whether it advances from qualifier validation into Final 4 stress
  testing.

Completed replay:

```text
Command: scripts/run_growth24_feature_probe_36c.ps1
Panel: research_growth_24_price_earnings_av_panel.parquet
Features: existing Growth24 extras + RSI_14, MA_20, MA_50, MA_200, Volume, AV earnings features
Cycles: 36
Epochs: 8
Seeds: 20260506,20260507
Target mode: date_excess
Rows: 858
Mean long-short return: +11.57%
Spread hit rate: 72.22%
```

Diagnostic:

```text
top1_bottom1: long=+12.77%, long_excess=+9.54%, short_alpha=-1.20%, spread=+11.57%, hit=72.22%, DD=-31.70%
top2_bottom2: long= +8.76%, long_excess=+5.53%, short_alpha=-1.74%, spread= +7.03%, hit=69.44%, DD=-22.27%
top3_bottom3: long= +7.57%, long_excess=+4.33%, short_alpha=-2.09%, spread= +5.48%, hit=63.89%, DD=-29.61%
```

Ticker holdout:

```text
top1: base_excess=+9.54%, worst_holdout=+2.93%, positive_holdouts=100.00%, max_ticker=75.00%
top2: base_excess=+5.53%, worst_holdout=+2.50%, positive_holdouts=100.00%, max_ticker=88.89%
top3: base_excess=+4.33%, worst_holdout=+1.81%, positive_holdouts=100.00%, max_ticker=88.89%
```

High-vol growth gate:

```text
Long-only gate at -35% drawdown: pass, 6885 / 7290 configs.
Best long-only: top1, long=+16.18%, excess=+12.42%, hit=67.86%, coverage=77.78%, max_ticker=85.71%, DD=-25.92%.

Cap-aware replay at -35% drawdown, max ticker share 50%: pass, 6015 / 7290 configs.
Best cap-aware: top1 cap=50%, long=+16.70%, excess=+12.83%, hit=76.00%, coverage=69.44%, max_slot=44.00%, DD=-33.13%.
```

Artifacts:

```text
data/experiment/historical_blind_rank_head/growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_shadow_log.parquet
data/experiment/historical_blind_rank_head/growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_summary.json
notes/dl_shadow_diagnostic_growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed.md
notes/dl_ticker_holdout_growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed.md
notes/dl_long_only_gate_growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_dd35.md
notes/dl_cap_aware_replay_growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_cov50_dd35.md
```

Interpretation:

- The earnings feature candidate passes the full 36-cycle validation and is
  materially stronger than the prior price-only seed-robust 36-cycle replay.
- Top1 is the strongest basket in this run, but it is highly concentrated in
  PLTR. The ticker holdout remains positive when PLTR is excluded, which is
  encouraging, but concentration must be treated as the main stress risk.
- This candidate should advance to the Final 4 stress-test bracket. It should
  still remain out of production capital until it survives the harder bracket
  tests and a live/paper outcome cycle.

## 2026-05-19 - Final 4 Stress Bracket Results

Objective:

- Compare the strongest DL candidate against the existing price-only Growth24
  lane under harder regime-stress windows.
- Refresh the Quant Cup PEAD vs OVERNIGHT semifinal.

DL semifinal:

```text
Earnings-feature DL regime gate: fail
  top1: stress_spread=+2.00%, worst_dd=-35.64%
  top2: stress_spread=+0.17%, worst_dd=-9.16%
  top3: stress_spread=-1.43%, worst_dd=-7.39%

Price-only DL regime gate: fail
  top1: stress_spread=-2.34%, worst_dd=-18.76%
  top2: stress_spread=+4.07%, worst_dd=-10.44%
  top3: stress_spread=+2.15%, worst_dd=-6.00%
```

DL failure details:

```text
Earnings top1 failed Q4 2018 and 2022 rate-bear stress.
Earnings top2 failed Q4 2018.
Earnings top3 failed GFC, Q4 2018, and 2022 rate-bear stress.

Price top1 failed GFC, Q4 2018, and 2022 rate-bear stress.
Price top2 failed GFC, Q4 2018, and 2022 rate-bear stress.
Price top3 failed GFC, Q4 2018, and 2022 rate-bear stress.
```

Quant Cup semifinal:

```text
PEAD:      CAGR=+31.22%, Sharpe=1.67, MaxDD=-20.33%, Beats SPY=YES
OVERNIGHT: CAGR=+21.05%, Sharpe=1.51, MaxDD=-27.64%, Beats SPY=YES
```

Interpretation:

- No DL candidate survives the strict Final 4 stress gate.
- The earnings-feature DL remains the stronger research candidate from the
  36-cycle replay, but it is not production-ready because it breaks in Q4 2018
  and 2022 rate-bear stress.
- PEAD wins the Quant Cup semifinal and is the only finalist-level strategy
  after this bracket pass.
- Next DL work should focus on a stress-aware version of the earnings-feature
  model: regime conditioning, stronger concentration limits, or abstention
  gates that stand down in Q4-2018/rate-bear-like conditions.

## 2026-05-20 - Earnings DL Abstention Gate Probe

Objective:

- Test whether existing DL confidence/validation fields can stand down during
  the stress windows that failed the Final 4 bracket.

Strict gate:

```text
Command: python dl_abstention_gate_eval.py --results-dir data/experiment/final4_growth24_earnings_regime_probe --output data/experiment/final4_growth24_earnings_regime_probe/abstention_gate.json --markdown-output notes/final4_growth24_earnings_abstention_gate.md --gate-max-drawdown -0.25 --gate-min-hit 0.5 --gate-min-spread 0.0 --gate-min-stress-coverage 0.10
Status: fail
Candidate configs: 56250
Passing configs: 0
Best: top2_bottom2, stress_spread=+9.98%, worst_dd=0.00%, coverage=8.33%
```

Relaxed diagnostic gate:

```text
Command: python dl_abstention_gate_eval.py --results-dir data/experiment/final4_growth24_earnings_regime_probe --output data/experiment/final4_growth24_earnings_regime_probe/abstention_gate_relaxed_probe.json --markdown-output notes/final4_growth24_earnings_abstention_gate_relaxed_probe.md --gate-max-drawdown -0.25 --gate-min-hit 0.5 --gate-min-spread 0.0 --gate-min-stress-coverage 0.08 --gate-min-trade-days 1
Status: pass
Candidate configs: 56250
Passing configs: 1404
Best: top2_bottom2, stress_spread=+9.98%, worst_dd=0.00%, coverage=8.33%
```

Interpretation:

- The strict gate failed because the best stress-safe abstention config only
  traded one stress decision date in the 3-cycle-per-regime bracket: 8.33%
  coverage versus the required 10.00%, and one trade day in rate-bear 2022
  versus the default two-day minimum.
- The relaxed diagnostic pass shows the existing confidence fields do contain
  some useful stress-avoidance signal.
- This is not enough for production. The next test should deepen the stress
  windows to more cycles so coverage is not decided by one of twelve possible
  stress decisions.

## 2026-05-20 - DL Distillation and HMM Regime Honesty Prep

Objective:

- Evaluate the deferred Claude suggestions after Quant Cup completion and wire
  the safe offline research pieces into the current DL testing framework.

Completed:

```text
dl_rank_head_distill_train.py
- Removed silent zero-imputation for missing teacher targets.
- Added [Distill] Teacher coverage reporting.
- Added --min-teacher-coverage, default 0.99.
- Distillation loss now skips uncovered rows instead of treating missing
  teacher ranks as 0.0.

run_distill_sweep.bat
- Added distill_weight sweep for 0.0, 0.3, 0.5, 0.7.
- Writes artifacts under artifacts/distill_sweep/w*/.

summarize_distill_sweep.py
- Summarizes each sweep metrics.json into a markdown table.
- Appends the table to this journal.

regime_detector.py
- Replaced HMM predict() calls with Viterbi decode().
- Added get_regime_series(start, end).
- Added --bic-sweep / run_bic_sweep().
- Added cached Quant Cup OHLCV fallback for SPY so offline regime checks do
  not depend on yfinance cache behavior.

dl_abstention_gate_eval.py
- Added HMM regime stress diagnostics alongside existing named stress buckets.
- Existing STRESS_REGIMES gate logic remains unchanged.
```

Verification:

```text
python -m py_compile dl_rank_head_distill_train.py regime_detector.py dl_abstention_gate_eval.py summarize_distill_sweep.py
.venv/Scripts/python.exe dl_rank_head_distill_train.py ... --epochs 0
  -> printed [Distill] Teacher coverage: 8218/8218 (100.0%).
.venv/Scripts/python.exe dl_rank_head_distill_train.py ... --min-teacher-coverage 1.01
  -> raised RuntimeError before training with exact coverage counts.
.venv/Scripts/python.exe regime_detector.py --bic-sweep
  -> minimum-BIC n_states: 4.
.venv/Scripts/python.exe -c "from regime_detector import get_regime_series..."
  -> 2022 regime series returned non-empty stress labels.
.venv/Scripts/python.exe dl_abstention_gate_eval.py ... narrowed smoke
  -> report included [HMM regime] diagnostics.
```

BIC sweep:

```text
n_states  log_likelihood       bic
2         21716.664147    -43275.389800
3         21581.256739    -42901.914963
4         23538.238673    -46697.424963  <- minimum BIC
5         23115.750446    -45718.200790
6         23172.523795    -45681.705919
```

Interpretation:

- These are usable opportunities. The distillation path can now be tested
  without hidden teacher-target contamination.
- The current 4-state HMM setting has empirical support from BIC, so it is
  reasonable to keep it unchanged while using HMM stress labels as an additional
  abstention diagnostic.
- Next run: execute `run_distill_sweep.bat`, then use
  `summarize_distill_sweep.py` output to decide whether distillation improves
  over the 0.0 baseline.

## 2026-05-17: Smoke-test — regime_detector.py + dl_rank_head_distill_train.py

Two new research scripts created by a prior session were smoke-tested end-to-end.
Neither is wired into monitor.py; both are orphaned research tools pending post-Quant Cup integration.

### regime_detector.py

```
python regime_detector.py fit
python regime_detector.py status
```

Result: PASS
- HMM fit converged (log-likelihood=24329.4757, 4 states, 2785 SPY trading days)
- State distribution: bull_quiet 45.9%, bear_quiet 28.9%, bull_volatile 21.5%, bear_stress 3.7%
  All states within 5–60% bounds — no degenerate state
- Current regime as of 2026-05-15: bull_quiet (state 2), self-persistence 97.9%
  Matches intuition for post-tariff-pause rally environment
- Bug fixed: yfinance now returns MultiIndex columns; added `df.columns = df.columns.get_level_values(0)` flatten in both _fetch_ohlcv and get_current_regime

### dl_rank_head_distill_train.py (1 epoch, 1 seed, CPU)

```
python dl_rank_head_distill_train.py --results data\experiment\rank_head_walkforward_3w_5seed.json
  --top-n 3 --epochs 1 --seeds 20260601 --device cpu
```

Result: PASS
- Teacher ensemble loaded (3 members, 8218 training samples, 7 tickers)
- One epoch completed without exceptions
- Output files written: data/experiment/rank_head_distilled.json, .csv
- IC=-0.186 on 1-epoch CPU run is expected (not converged); not a quality signal
- Bugs fixed:
  - `_load_window_rows` looked for key "windows" (an int=3 in this JSON); changed to "window_rows" (the actual list key)
  - `DEFAULT_EXTRA_FEATURES` is a comma-separated string; `list()` on a string iterates characters; fixed to `.split(",")`

### Deferred backlog
All deeper improvements (vectorize teacher lookup, assert coverage, distill_weight sweep,
get_regime_series, label vocab reconciliation, BIC sweep) are parked until after Quant Cup ships.
See plan file: C:\Users\david\.claude\plans\here-is-what-was-lexical-turtle.md
