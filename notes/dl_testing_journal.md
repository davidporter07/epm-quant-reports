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
