# Handoff: DL Directional Testing and Feature Backfill

Date: 2026-05-05
Repo: `D:\fund_monitor`

## Current Goal

Improve the Deep Learning forecast so it learns stronger 21-day directional behavior without damaging price-error metrics. The recent experiments showed that changing the loss/architecture alone is not enough. The bottleneck is directional signal quality in the input features.

The next Codex session should continue from the FMP-backed research panel and use GitNexus MCP directly if available.

## GitNexus State

The user ran:

```powershell
npx.cmd gitnexus analyze --skip-git
npx.cmd gitnexus setup
```

`gitnexus setup` configured Codex MCP and installed Codex skills. Restarting Codex should make direct GitNexus MCP tools available. In this session only the CLI was available.

Important project rule from `AGENTS.md`:

- Run GitNexus impact analysis before editing any existing function/class/method.
- Warn before HIGH/CRITICAL edits.
- Run GitNexus change detection before committing if the MCP tool exists.

CLI note:

- `npx.cmd gitnexus impact ...` worked.
- `npx.cmd gitnexus detect_changes ...` did not exist in this installed CLI.
- After Codex restart, prefer MCP `gitnexus_detect_changes()` if available.

## Production/Integration Fixes Completed Earlier In This Thread

### Forecasting API/UI

Files changed:

- `app.py`
- `static/forecasting.html`
- `static/js/forecasting.js`

Purpose:

- Make the site forecasting page show the DL model consistently.
- Normalize `DeepLearning`, `Deep Learning`, and `DL` model names.
- Load `data/model_leaderboard_by_ticker.csv` when present.
- Bump forecasting JS cache key.
- Remove stale frontend language claiming the DL model used the older 11-feature/RSI description.

### Live Inference Freshness

Files changed:

- `build_training_dataset.py`
- `deep_learning_model.py`

Purpose:

- Preserve latest unlabeled rows for inference instead of dropping all rows without `Target_Forward_21D`.
- Filter non-null targets inside training/backtest only.

Result:

- Rebuilt training panel reached `2026-05-05`.
- Latest inference rows exist.

### Prediction Logging

File changed:

- `record_predictions.py`

Purpose:

- Normalize DL model names to `DeepLearning`.
- Include ARIMAX forecasts from `data/arimax_forecasts.csv`.

Observed result:

- `python record_predictions.py --debug` logged 49 rows:
  `7 models x 7 tickers`.

### Guarded DL Training

Files changed:

- `monitor.py`
- `deep_learning_model.py`

Purpose:

- Prevent daily warm-start training from accepting a worse DL checkpoint.
- Back up checkpoint/scaler/feature importance.
- Run pre/post `deep_learning_model.py backtest`.
- Restore the previous checkpoint if acceptance thresholds fail.

Acceptance guard:

- Reject if MAE worsens by more than 2%.
- Reject if directional accuracy drops by more than 3 percentage points.
- Reject if Spearman IC drops by more than 3 percentage points.

Current restored production checkpoint metrics:

```text
MAE: 0.082883
RMSE: 0.110585
Directional Accuracy: 50.85%
Correlation: -0.1347
IC_Spearman: -0.0586
```

Current restored DL forecasts after infer:

```text
AAPL  1.0343
MSFT -1.0220
AMZN -8.2140
NVDA -5.5394
GOOG -5.3847
META -2.1246
TSLA -2.2287
Date: 2026-05-05
```

Rejected candidate checkpoint was preserved as:

```text
models/dl_tcn.rejected_20260505.pt
```

## Loss/Architecture Experiments

### Directional Reward / Directional BCE

File changed:

- `deep_learning_model.py`

File added:

- `dl_directional_loss_experiment.py`

Implementation:

- Added optional `directional_bce(mu, y, temperature=0.02, neutral_threshold=0.0)`.
- Added optional training flags:
  - `--direction-weight`
  - `--direction-temperature`
  - `--direction-neutral-threshold`
- Production default remains `direction_weight=0.0`.

Why:

- User asked how the model can be rewarded for correct direction.
- The reward is an auxiliary differentiable loss: predictions with the correct sign receive lower loss, incorrect sign receives higher loss, and gradients update the network weights during backpropagation.

Tests:

- Unthresholded weights: `0`, `0.1`, `0.2`.
- Thresholded grid:
  - weights: `0`, `0.02`, `0.05`, `0.1`
  - thresholds: `0.005`, `0.01`, `0.02`
  - temperature: `0.02`
  - epochs: `2`

Best thresholded result:

```text
weight=0.1
threshold=0.02
Directional Accuracy: 48.93%
MAE: 0.083171
RMSE: 0.112070
IC: -0.0670
```

Decision:

- Do not enable directional loss in production.
- It worsened direction versus restored production baseline.

### Dual-Head Direction Model

File added:

- `dl_dual_head_experiment.py`

Why:

- Separate price head and direction head might allow the network to learn direction without distorting price magnitude.

GitNexus impact:

- `TCNForecaster` was CRITICAL risk.
- `PanelSequenceDataset` was HIGH risk.

Decision:

- Do not edit production model class.
- Implement isolated experiment model `DualHeadTCN` in a new script.

Tests:

- Unbalanced BCE grid:
  - weights: `0.1`, `0.25`, `0.5`
  - thresholds: `0.005`, `0.01`, `0.02`
  - epochs: `3`
- Balanced BCE grid:
  - weights: `0.25`, `0.5`, `1.0`
  - thresholds: `0.01`, `0.02`
  - epochs: `4`

Observed:

- Unbalanced head reached about `55.29%` directional accuracy but predicted bullish about `98.45%` of the time.
- That is class-collapse, not real learning.
- Balanced BCE best result was about `50.04%` direction with worse MAE/RMSE/IC.

Decision:

- Architecture/loss changes are not sufficient.
- Need stronger independent directional inputs.

## Directional Feature Backfill Work

File added:

- `build_directional_feature_panel.py`

Purpose:

- Build a research-only panel of directional feature candidates.
- Do not change production DL inputs yet.
- Merge candidate features with `data/training_panel.parquet`.
- Output to `data/experiment/`.

Current command:

```powershell
python build_directional_feature_panel.py --merge-base --download-earnings --earnings-source fmp --output data\experiment\directional_feature_panel_fmp.parquet --csv-output data\experiment\directional_feature_panel_fmp_sample.csv
```

Outputs:

```text
data\experiment\directional_feature_panel_fmp.parquet
data\experiment\directional_feature_panel_fmp_sample.csv
```

Final FMP-backed panel coverage:

```text
Rows: 10,913
Directional candidate features: 14
Price-derived feature coverage: 94.5%
FMP earnings feature coverage: 94.5%
FMP cached tickers: 7 / 7
```

Features included:

```text
momentum_12_1
momentum_6_1
momentum_3_1
overnight_return_5d
intraday_return_5d
overnight_return_20d
intraday_return_20d
atr_percentile
hv_percentile
vol_regime
gap_magnitude_5d
gap_5d_count
earnings_surprise_last
earnings_beat_rate_4q
```

Safety addition:

- `--force-refresh-prices` is blocked unless `--allow-shared-cache-overwrite` is also supplied.
- Reason: `quant_cup.data_loader.load_prices()` uses shared cache filenames. A forced refresh for only MAG7 could overwrite broader S&P 500 caches.

## Earnings Data Source Evaluation

### Alpha Vantage

Existing loader:

- `quant_cup/earnings_av.py`

Issue:

- AV rate-limited before missing MAG7 tickers downloaded.
- Original logging could expose API key through request exceptions and AV rate-limit messages.

Changes:

- Sanitized AV error/rate-limit logging.

Status:

```text
AV cached: 3 / 7
AV missing: 4 / 7
```

Decision:

- Do not rely on AV right now for DL earnings backtests.

### Yahoo Finance

Command tested:

```powershell
python build_directional_feature_panel.py --merge-base --include-earnings --earnings-source yahoo --output data\experiment\directional_feature_panel_yahoo.parquet --csv-output data\experiment\directional_feature_panel_yahoo_sample.csv
```

Result:

```text
Yahoo earnings feature coverage: 12.0%
```

Decision:

- Yahoo is useful for OHLCV.
- Yahoo is too sparse for historical earnings-surprise DL backtesting.

### Financial Modeling Prep

Existing loader:

- `quant_cup/earnings_fmp.py`

Issue found:

- Loader used stale endpoint:
  `stable/earnings-surprises?symbol=...`
- It returned HTTP 404.

Fix:

- Updated endpoint to:
  `stable/earnings?symbol=...`
- Added empty-cache rejection for `[]` files.
- Sanitized request error logging.
- Added `GOOG -> GOOGL` earnings alias handling in the research panel builder.

Result:

```text
FMP earnings loaded: 209 records, 7 tickers, 2019-01-29 to 2026-04-30
FMP earnings feature coverage: 94.5%
```

Decision:

- Use FMP as the current earnings source for research backtests.

FMP docs checked:

- `https://site.financialmodelingprep.com/developer/docs/stable`

## Formal Feature Tests Run

All tests used:

```powershell
python feature_tester.py --feature <feature> --panel data\experiment\directional_feature_panel_fmp.parquet --tickers AAPL,MSFT,AMZN,NVDA,GOOG,META,TSLA --min-obs 50
```

Result files:

```text
feature_store\testing\results\momentum_12_1_20260505.json
feature_store\testing\results\gap_magnitude_5d_20260505.json
feature_store\testing\results\atr_percentile_20260505.json
feature_store\testing\results\intraday_return_20d_20260505.json
feature_store\testing\results\gap_5d_count_20260505.json
feature_store\testing\results\hv_percentile_20260505.json
feature_store\testing\results\earnings_surprise_last_20260505.json
feature_store\testing\results\earnings_beat_rate_4q_20260505.json
```

### Quick Signal Screen Before Formal Gate

Notable rank/quantile behavior:

```text
atr_percentile       Spearman IC about -0.066, sign_match about 61.5%
hv_percentile        Spearman IC about -0.064, sign_match about 61.5%
gap_magnitude_5d     Spearman IC about  0.052
intraday_return_20d  Spearman IC about  0.046
gap_5d_count         Spearman IC about  0.039
momentum_12_1        Spearman IC about  0.036
```

Interpretation:

- Volatility percentiles are directionally informative, but the relationship is negative and regime-sensitive.
- Gap features are informative but partly redundant with existing volatility/return features.

### Formal Test Summary

`atr_percentile`:

```text
Availability: PASS
Leakage: PASS
IC Walkforward: PASS
Drift: FAIL
Regime: WARN
Robustness: PASS
Ablation: PASS
Redundancy: PASS
Overall: FAIL
```

Why it matters:

- Best single candidate so far.
- Clear incremental lift and low redundancy.
- Needs regime handling before promotion.

`gap_5d_count`:

```text
Availability: PASS
Leakage: PASS
IC Walkforward: PASS
Drift: FAIL
Regime: PASS
Robustness: PASS
Ablation: WARN
Redundancy: PASS
Overall: FAIL
```

Why it matters:

- Useful directional signal.
- Incremental lift was small, so best tested as part of a bundle.

`gap_magnitude_5d`:

```text
Availability: PASS
Leakage: PASS
IC Walkforward: PASS
Drift: FAIL
Regime: PASS
Robustness: PASS
Ablation: FAIL
Redundancy: WARN
Overall: FAIL
```

Decision:

- Do not promote raw.

`momentum_12_1`:

```text
Availability: PASS
Leakage: PASS
IC Walkforward: WARN
Drift: FAIL
Regime: PASS
Robustness: PASS
Ablation: WARN
Redundancy: FAIL
Overall: FAIL
```

Decision:

- Mostly duplicates `Ret_252D`.

`earnings_surprise_last` with FMP:

```text
Availability: PASS
Leakage: PASS
IC Walkforward: FAIL
Drift: FAIL
Regime: PASS
Robustness: WARN
Ablation: FAIL
Redundancy: PASS
Overall: FAIL
```

Decision:

- Raw value is not enough by itself.
- Should derive event/window/regime interaction features.

`earnings_beat_rate_4q` with FMP:

```text
Availability: PASS
Leakage: PASS
IC Walkforward: FAIL
Drift: FAIL
Regime: FAIL
Robustness: PASS
Ablation: FAIL
Redundancy: PASS
Overall: FAIL
```

Decision:

- Do not use raw beat-rate directly.

## Why We Moved From One Test To The Next

1. The site forecast page was missing/underreporting DL.
   - Fixed name normalization, leaderboard loading, and frontend cache/description.

2. DL was not reliably producing current forecasts.
   - Found latest rows were being dropped due to null future target.
   - Moved target-null filtering into training/backtesting only.

3. Daily learning could make the model worse.
   - Added guarded training and checkpoint restore.
   - A candidate warm-start improved MAE but hurt direction, so it was rejected/restored.

4. User asked for a reward that encourages correct direction.
   - Added optional directional BCE.
   - Tests did not improve direction, so production default remains off.

5. User asked to test without waiting 21 days.
   - Added isolated historical experiments.
   - Directional loss and dual-head models were backtested against existing historical targets.

6. Dual-head direction looked promising but collapsed into near-all-bullish predictions.
   - Balanced BCE fixed collapse but lost the directional improvement.
   - Conclusion: architecture/loss is not the bottleneck.

7. Needed stronger directional inputs.
   - Built research feature panel using OHLCV, earnings, gap, volatility, momentum, overnight/intraday decomposition.

8. AV earnings was rate-limited and sparse.
   - Tested Yahoo: too sparse.
   - Fixed FMP loader: now sufficient coverage.

9. Raw earnings features failed as standalone features.
   - Next step is not to promote raw earnings.
   - Next step is derived event/regime interactions.

## Recommended Next Step

Create derived earnings/regime features in the research panel, then run DL backtests.

Recommended derived features:

```text
days_since_earnings
post_earnings_window_active
earnings_surprise_direction
earnings_abs_surprise
earnings_surprise_x_atr_regime
earnings_surprise_x_gap_count
post_earnings_positive_drift_window
post_earnings_negative_drift_window
```

Recommended candidate bundle for first DL test:

```text
atr_percentile
gap_5d_count
earnings_surprise_last
days_since_earnings
post_earnings_window_active
earnings_surprise_x_atr_regime
```

Do not promote these to production yet.

## Suggested Implementation Plan For Next Codex

1. Verify GitNexus MCP is available.

2. Run GitNexus impact before editing:

```text
build_directional_feature_panel
pead_features
train_model if touched
PanelSequenceDataset if touched
```

3. Prefer adding derived features inside `build_directional_feature_panel.py` first.
   - This is research-only and lower-risk than touching production training.

4. Add a new helper in the research builder to create event-derived earnings features from the FMP earnings DataFrame.

5. Rebuild:

```powershell
python build_directional_feature_panel.py --merge-base --download-earnings --earnings-source fmp --output data\experiment\directional_feature_panel_fmp.parquet --csv-output data\experiment\directional_feature_panel_fmp_sample.csv
```

6. Run `feature_tester.py` on the derived features.

7. Add `--panel` support to `dl_dual_head_experiment.py` and/or `dl_directional_loss_experiment.py` if not already present.

8. Run an isolated DL experiment using:

```text
data\experiment\directional_feature_panel_fmp.parquet
```

9. Compare to restored production baseline:

```text
MAE: 0.082883
RMSE: 0.110585
Directional Accuracy: 50.85%
IC_Spearman: -0.0586
```

10. Only consider production promotion if:

```text
Directional Accuracy improves materially
IC improves materially
MAE/RMSE do not regress beyond guard thresholds
No all-bullish/all-bearish collapse
```

## Commands To Reproduce Current Research Panel

```powershell
cd D:\fund_monitor
python build_directional_feature_panel.py --merge-base --download-earnings --earnings-source fmp --output data\experiment\directional_feature_panel_fmp.parquet --csv-output data\experiment\directional_feature_panel_fmp_sample.csv
```

Feature tests:

```powershell
python feature_tester.py --feature atr_percentile --panel data\experiment\directional_feature_panel_fmp.parquet --tickers AAPL,MSFT,AMZN,NVDA,GOOG,META,TSLA --min-obs 50
python feature_tester.py --feature gap_5d_count --panel data\experiment\directional_feature_panel_fmp.parquet --tickers AAPL,MSFT,AMZN,NVDA,GOOG,META,TSLA --min-obs 50
python feature_tester.py --feature earnings_surprise_last --panel data\experiment\directional_feature_panel_fmp.parquet --tickers AAPL,MSFT,AMZN,NVDA,GOOG,META,TSLA --min-obs 50
python feature_tester.py --feature earnings_beat_rate_4q --panel data\experiment\directional_feature_panel_fmp.parquet --tickers AAPL,MSFT,AMZN,NVDA,GOOG,META,TSLA --min-obs 50
```

## Files Added In This Workstream

```text
build_directional_feature_panel.py
dl_directional_loss_experiment.py
dl_dual_head_experiment.py
HANDOFF_dl_directional_testing_20260505.md
```

## Files Modified In This Workstream

Known files touched by this DL/directional workstream:

```text
app.py
build_training_dataset.py
deep_learning_model.py
monitor.py
record_predictions.py
static/forecasting.html
static/js/forecasting.js
quant_cup/earnings_av.py
quant_cup/earnings_fmp.py
```

There are many unrelated pre-existing working tree changes. Do not revert user work.

## Cautions

- Do not run `git reset --hard`.
- Do not force-refresh price caches for a ticker subset.
- Do not promote raw earnings features just because FMP coverage is now good.
- Do not enable directional loss in production based on current results.
- Do not edit `TCNForecaster` or `PanelSequenceDataset` without fresh GitNexus impact analysis.
- Be careful with API key logging; AV/FMP request exceptions can include keys in URLs/messages.

## Continuation Update: Derived Earnings Features

This follow-up session had GitNexus MCP access. Impact analysis for
`pead_features` returned LOW risk:

```text
Direct callers: 1 (`quant_cup/feature_candidates.py::compute_features`)
Affected processes: 1 (`compute_features`)
Risk: LOW
```

`build_directional_feature_panel.py` was untracked and not in the graph, so
GitNexus could not resolve `build_directional_feature_panel` for impact.

Added research-only derived earnings/event features:

```text
days_since_earnings
post_earnings_window_active
earnings_surprise_direction
earnings_abs_surprise
earnings_surprise_x_atr_regime
earnings_surprise_x_gap_count
post_earnings_positive_drift_window
post_earnings_negative_drift_window
```

Rebuilt:

```powershell
python build_directional_feature_panel.py --merge-base --download-earnings --earnings-source fmp --output data\experiment\directional_feature_panel_fmp.parquet --csv-output data\experiment\directional_feature_panel_fmp_sample.csv
```

Result:

```text
Rows: 10,913
Directional candidate features: 22
All derived earnings/event features: 94.5% non-null
FMP download: 0 tickers to fetch, 7 already cached
FMP earnings loaded: 209 records, 7 tickers, 2019-01-29 to 2026-04-30
```

Formal tests showed no derived feature passed overall. Notable signals:

```text
earnings_surprise_x_gap_count:
  IC Walkforward PASS, Mean IC 0.0648, hit rate 68%, regime PASS
  Overall FAIL due to drift and robustness

earnings_surprise_direction:
  Ablation PASS, delta R +0.00609
  Overall FAIL due to IC, drift, and robustness

post_earnings_negative_drift_window:
  Ablation PASS, delta R +0.01927
  Overall FAIL due to IC/regime failures
```

Added research-panel support to:

```text
dl_directional_loss_experiment.py
dl_dual_head_experiment.py
```

New flags:

```text
--panel
--extra-features
```

First isolated DL tests with bundle:

```text
atr_percentile
gap_5d_count
earnings_surprise_last
days_since_earnings
earnings_surprise_x_gap_count
post_earnings_negative_drift_window
```

Dual-head, balanced BCE:

```powershell
python dl_dual_head_experiment.py --panel data\experiment\directional_feature_panel_fmp.parquet --extra-features atr_percentile,gap_5d_count,earnings_surprise_last,days_since_earnings,earnings_surprise_x_gap_count,post_earnings_negative_drift_window --weights 0.25 --thresholds 0.01 --epochs 3 --balanced
```

Result:

```text
MAE: 0.067271
RMSE: 0.087475
Return directional accuracy: 54.13%
Head directional accuracy: 47.43%
IC_Spearman: -0.0724
Bullish head: 28.01%
```

Single-head TCN with the same extra features, no directional auxiliary loss:

```powershell
python dl_directional_loss_experiment.py --panel data\experiment\directional_feature_panel_fmp.parquet --extra-features atr_percentile,gap_5d_count,earnings_surprise_last,days_since_earnings,earnings_surprise_x_gap_count,post_earnings_negative_drift_window --weights 0 --epochs 3 --batch-size 256 --val-days 252
```

Result:

```text
Warm-start failed because feature count changed from 10 to 16, so this trained from scratch.
MAE: 0.064076
RMSE: 0.083599
Directional Accuracy: 63.28%
Correlation: 0.0772
IC_Spearman: 0.0223
N: 896
Top features: gap_5d_count, Ret_21D, Ret_5D, Gap_MA20, days_since_earnings
```

Interpretation:

- The feature bundle is promising enough for deeper research.
- The single-head result is not directly comparable to restored production
  because it trained from scratch after feature-count mismatch.
- Do not promote yet. Next step should be repeated seeds and longer epochs,
  plus a production-compatible warm-start strategy for expanded feature inputs.

## Continuation Update: Expanded-Feature DL Growth Tests

Added a compatible warm-start loader inside `deep_learning_model.py::train_model`
that can expand an existing checkpoint when feature count increases:

```text
feature_gate.log_weights: copies old feature weights into the prefix
in_proj.weight: copies old input channels into the prefix
other same-shape tensors: loaded normally
new feature channels: initialized normally and trained
```

GitNexus impact before editing:

```text
train_model: LOW risk, 3 direct callers, 1 affected process
load_model_and_scaler: CRITICAL risk
TCNForecaster: CRITICAL risk
```

Because `load_model_and_scaler` and `TCNForecaster` were CRITICAL, they were
not edited. The production model class and inference loader remain unchanged.

Added research controls to `dl_directional_loss_experiment.py`:

```text
--lr
--from-scratch
--seed
--selection-metric {loss,directional,composite}
```

### Compatible Production Warm-Start Results

Same six-feature research bundle:

```text
atr_percentile
gap_5d_count
earnings_surprise_last
days_since_earnings
earnings_surprise_x_gap_count
post_earnings_negative_drift_window
```

Compatible warm-start now loads correctly:

```text
Warm-start: loaded 26 tensors
```

But metrics were weaker than scratch:

```text
3 epochs, lr 0.001:
MAE: 0.070671
RMSE: 0.097958
Directional Accuracy: 53.68%
IC_Spearman: -0.0441

5 epochs, lr 0.005:
MAE: 0.075639
RMSE: 0.104649
Directional Accuracy: 43.97%
IC_Spearman: -0.0735
```

Interpretation:

- The compatibility loader works.
- The current production checkpoint does not adapt cleanly to the expanded
  feature set under simple fine-tuning.
- Do not promote expanded production warm-start yet.

### Scratch Expanded-Feature Results

Six-feature bundle, from scratch, no directional auxiliary loss:

```text
5 epochs, seed 20260505:
MAE: 0.065234
RMSE: 0.084023
Directional Accuracy: 63.06%
IC_Spearman: 0.0058
Top features: Vol_63D, days_since_earnings, Gap_MA20, Ret_5D, earnings_surprise_x_gap_count
```

Directional-loss grid on the six-feature scratch model:

```text
weight 0.00:
  MAE 0.065234, RMSE 0.084023, Direction 63.06%, IC 0.0058

weight 0.02, threshold 0.01:
  MAE 0.067819, RMSE 0.088786, Direction 47.54%, IC -0.1975

weight 0.05, threshold 0.01:
  MAE 0.065673, RMSE 0.085853, Direction 57.81%, IC -0.1049
```

Conclusion:

- Directional auxiliary loss still hurts this setup.
- Keep `direction_weight=0` for the expanded-feature candidate.

Tighter three-feature bundle:

```text
gap_5d_count
days_since_earnings
earnings_surprise_x_gap_count
```

Result:

```text
MAE: 0.066527
RMSE: 0.085796
Directional Accuracy: 60.04%
IC_Spearman: -0.2284
```

Conclusion:

- The full six-feature bundle is better than the tighter bundle.

### Seed Stability

Six-feature scratch, 3 epochs, loss-selected:

```text
seed 20260505:
MAE 0.064076, RMSE 0.083599, Direction 63.28%, IC 0.0223

seed 20260506:
MAE 0.069186, RMSE 0.087815, Direction 57.70%, IC -0.1368

seed 20260507:
MAE 0.068026, RMSE 0.087140, Direction 49.44%, IC -0.1472
```

Directional checkpoint selection for weak seed 20260507:

```text
MAE: 0.074972
RMSE: 0.092797
Directional Accuracy: 62.95%
IC_Spearman: -0.1330
```

Composite selection selected the same checkpoint and had the same result.

Interpretation:

- The expanded feature set is promising, but seed stability is not yet good.
- Directional checkpoint selection can rescue direction, but at the cost of
  MAE/IC.
- A promotion path should require repeated-seed stability or use an ensemble/
  selection strategy, not a single lucky scratch checkpoint.

Recommended next step:

```text
1. Build a seed-grid runner for expanded DL candidates.
2. Evaluate mean/std of MAE, RMSE, direction, IC, and bullish prediction rate.
3. Test a small ensemble of the top 3 scratch seeds.
4. Only promote if the ensemble beats production guardrails and avoids sign collapse.
```

## Continuation Update: Stability Verification Run

Added:

```text
dl_expanded_feature_seed_grid.py
dl_expanded_feature_ensemble_eval.py
```

Seed-grid command:

```powershell
python dl_expanded_feature_seed_grid.py --epochs 3 --seeds 20260505,20260506,20260507,20260508,20260509 --selection-metric loss
```

Outputs:

```text
data/experiment/expanded_feature_seed_grid.json
data/experiment/expanded_feature_seed_grid.csv
```

Five-seed aggregate:

```text
MAE mean: 0.068385, std: 0.001681, min: 0.065261, max: 0.069748
RMSE mean: 0.087131, std: 0.001579, min: 0.084104, max: 0.088533
Directional Accuracy mean: 56.99%, std: 4.06 pp, min: 49.44%, max: 61.61%
Correlation mean: 0.0049, std: 0.0425
IC_Spearman mean: -0.1047, std: 0.0586, min: -0.1560, max: 0.0017
Predicted bullish rate mean: 87.21%, std: 10.33 pp, min: 67.08%, max: 96.43%
```

Interpretation:

- The expanded feature set improves average directional accuracy versus the
  restored production baseline, but not enough for promotion.
- IC is negative on average.
- The model has a strong bullish prediction bias/sign imbalance.
- The single best seed is not enough evidence; the stability profile is weak.

Ensemble checks:

```powershell
python dl_expanded_feature_ensemble_eval.py --sort-by Directional_Accuracy --top-k 2,3,5
python dl_expanded_feature_ensemble_eval.py --sort-by MAE --top-k 2,3,5 --output data\experiment\expanded_feature_ensemble_eval_by_mae.json
```

Best direction-sorted ensemble:

```text
top 2 by Directional Accuracy:
MAE: 0.067148
RMSE: 0.085679
Directional Accuracy: 61.16%
IC_Spearman: -0.0886
Predicted bullish rate: 95.54%
```

Best MAE-sorted ensemble:

```text
top 2 by MAE:
MAE: 0.065682
RMSE: 0.084481
Directional Accuracy: 57.81%
IC_Spearman: -0.0790
Predicted bullish rate: 91.96%
```

Conclusion:

- Simple seed averaging does not fix sign bias.
- Do not promote this expanded-feature candidate as-is.
- Next research should target sign calibration and balanced directional
  validation, not more raw features or larger seed ensembles.

Recommended next step:

```text
1. Add validation reporting for bullish prediction rate in train/backtest.
2. Add an experiment-only calibration layer or threshold search on validation predictions.
3. Evaluate calibrated predictions on the 252-day holdout.
4. Gate promotion on:
   - Directional Accuracy > production baseline by a material margin
   - IC_Spearman >= production baseline
   - Predicted bullish rate not collapsed, e.g. 35%-75%
   - MAE/RMSE within guard thresholds
```

## Continuation Update: Sign Calibration Tests

Added:

```text
dl_sign_calibration_eval.py
dl_rolling_sign_calibration_eval.py
```

Static sign calibration command:

```powershell
python dl_sign_calibration_eval.py
```

Outputs:

```text
data/experiment/sign_calibration_eval.json
data/experiment/sign_calibration_eval.csv
```

Important holdout regime split:

```text
Full 252-day holdout bullish rate: 63.66%
First half calibration bullish rate: 79.98%
Second half evaluation bullish rate: 47.09%
```

Static thresholds failed to generalize across that regime shift. Best rows on
the second half only reached about 53.5% directional accuracy and still had
negative IC.

Rolling calibration command:

```powershell
python dl_rolling_sign_calibration_eval.py
```

Outputs:

```text
data/experiment/rolling_sign_calibration_eval.json
data/experiment/rolling_sign_calibration_eval.csv
```

Best rolling result:

```text
Model: seed 20260505
Method: max_balanced_score
Lookback: 84 trading days
Label lag: 21 trading days
Directional accuracy: 62.73%
Bullish signal rate: 59.63%
MAE: 0.050938
RMSE: 0.063459
IC_Spearman: -0.1124
Coverage: 161 samples / 23 evaluated dates
```

Broader rolling windows:

```text
Top 3 ensemble, 42-day lookback:
Directional accuracy: 59.56%
Bullish signal rate: 82.20%
IC_Spearman: -0.1087
Coverage: 455 samples / 65 evaluated dates

Seed 20260505, 42-day lookback:
Directional accuracy: 57.80%
Bullish signal rate: 76.48%
IC_Spearman: -0.0845
Coverage: 455 samples / 65 evaluated dates
```

Conclusion:

- Calibration can reduce sign collapse in narrow windows.
- It does not yet produce a robust promotion candidate because IC remains
  negative and the strongest result has limited date coverage.
- The model score itself is still poorly ranked cross-sectionally in the
  regime-shift period.

Recommended next step:

```text
1. Stop trying to repair this candidate with output thresholds alone.
2. Add explicit sign-balance diagnostics to training/backtest.
3. Try training objective changes that penalize sign collapse directly:
   - batch-level bullish-rate regularization
   - correlation/IC auxiliary objective
   - validation selection requiring direction + IC + bullish-rate bounds
4. Keep all of this research-only until repeated-seed IC is non-negative.
```

## Continuation Update: Anti-Collapse Objective Tests

Added:

```text
dl_sign_regularized_experiment.py
```

This is research-only and does not modify production inference. It trains the
same TCN architecture with optional:

```text
batch sign-balance loss
Pearson correlation auxiliary loss
pairwise ranking auxiliary loss
balanced sign sampler
validation selection score including direction, IC, MAE, and bullish-rate penalty
```

Initial objective grid:

```powershell
python dl_sign_regularized_experiment.py --seeds 20260505,20260506,20260507 --corr-weights 0,0.05 --balance-weights 0,0.1,0.5 --epochs 3
```

Result:

```text
Best direction: 65.07%, but bullish rate 93.19%, IC -0.0419
Best in-bounds bullish-rate rows: direction around 48%-54%, IC negative
Conclusion: Pearson + simple sign-balance did not fix rank quality.
```

Pairwise ranking grid:

```powershell
python dl_sign_regularized_experiment.py --seeds 20260505,20260506,20260507 --corr-weights 0 --balance-weights 0.1,0.5 --rank-weights 0.01,0.05 --epochs 3 --output data\experiment\sign_regularized_rank_comparison.json --csv-output data\experiment\sign_regularized_rank_comparison.csv
```

Result:

```text
Best IC: +0.0355, direction 63.39%, but bullish rate 100%
Only in-bounds bullish-rate row: direction 49.22%, IC -0.0573
Conclusion: pairwise rank loss can improve IC, but still collapses sign.
```

Smoother/stronger balance grid:

```powershell
python dl_sign_regularized_experiment.py --seeds 20260505,20260506,20260507 --corr-weights 0 --balance-weights 1.0,2.0 --rank-weights 0.01,0.05 --balance-temperature 0.05 --rank-temperature 0.02 --epochs 3 --output data\experiment\sign_regularized_smooth_balance_comparison.json --csv-output data\experiment\sign_regularized_smooth_balance_comparison.csv
```

Result:

```text
Best IC: +0.0185, direction 63.17%, but bullish rate 97.99%
Best in-bounds row: direction 56.58%, IC -0.0305, bullish rate 72.66%
Conclusion: smoother sign-balance helps, but does not stabilize IC.
```

Balanced sampler grid:

```powershell
python dl_sign_regularized_experiment.py --seeds 20260505,20260506,20260507 --corr-weights 0 --balance-weights 0,0.5,1.0 --rank-weights 0,0.01 --balance-temperature 0.05 --balanced-sampler --epochs 3 --output data\experiment\sign_regularized_balanced_sampler_comparison.json --csv-output data\experiment\sign_regularized_balanced_sampler_comparison.csv
```

Notable result:

```text
seed 20260505, balance 0.5, rank 0, balanced sampler:
MAE: 0.064269
RMSE: 0.083220
Directional Accuracy: 64.17%
IC_Spearman: +0.0213
Bullish raw signal rate: 87.83%
```

Post-hoc threshold check on that model:

```text
Raw threshold 0.000000:
Direction 64.17%, bullish 87.83%, IC +0.0213

Threshold 0.005022, bullish capped at 75%:
Direction 59.15%, bullish 75.00%, IC +0.0213
```

This is the first candidate with positive IC and materially better direction
while price-error metrics are also improved. However, it is still one seed.

Additional seeds for same setup:

```powershell
python dl_sign_regularized_experiment.py --seeds 20260508,20260509 --corr-weights 0 --balance-weights 0.5 --rank-weights 0 --balance-temperature 0.05 --balanced-sampler --epochs 3 --output data\experiment\sign_regularized_balanced_sampler_more_seeds.json --csv-output data\experiment\sign_regularized_balanced_sampler_more_seeds.csv
```

Result:

```text
seed 20260508: direction 55.02%, IC -0.0836, bullish 71.76%
seed 20260509: direction 53.57%, IC -0.1338, bullish 78.57%
```

Conclusion:

- Balanced sign sampling is the most promising lever so far.
- It produced one genuinely promising seed, especially after thresholding.
- It is not stable enough across seeds for promotion.
- The next step should be a longer training run and/or architecture change that
  explicitly separates magnitude and rank/sign learning while enforcing a
  validation gate.

Recommended next experiment:

```text
1. Continue with balanced sampler enabled.
2. Train the best setup for longer (8-12 epochs) across 5 seeds.
3. Add stricter validation gate:
   - bullish rate inside 35%-75%
   - IC non-negative
   - direction above production baseline
   - MAE/RMSE within guardrails
4. If stability remains poor, revisit dual-head with balanced sampler and
   validation gate, not raw BCE direction loss.
```

## Continuation Update: 10-Epoch Balanced Sampler Run

Command:

```powershell
python dl_sign_regularized_experiment.py --seeds 20260505,20260506,20260507,20260508,20260509 --corr-weights 0 --balance-weights 0.5 --rank-weights 0 --balance-temperature 0.05 --balanced-sampler --epochs 10 --output data\experiment\sign_regularized_balanced_sampler_10epoch.json --csv-output data\experiment\sign_regularized_balanced_sampler_10epoch.csv
```

Results:

```text
seed 20260505:
MAE 0.064269, RMSE 0.083220, Direction 64.17%, IC +0.0213, bullish 87.83%

seed 20260509:
MAE 0.069212, RMSE 0.088686, Direction 65.96%, IC -0.0201, bullish 92.97%

seed 20260508:
MAE 0.073788, RMSE 0.093562, Direction 54.80%, IC -0.1012, bullish 71.76%

seed 20260506:
MAE 0.073121, RMSE 0.091763, Direction 49.22%, IC -0.1783, bullish 74.89%

seed 20260507:
MAE 0.072126, RMSE 0.092300, Direction 45.76%, IC -0.1630, bullish 55.36%
```

Interpretation:

- Longer training did not stabilize the candidate.
- The validation selector still favored early checkpoints for the best seeds.
- Only seed 20260505 retained positive IC.
- In-bounds bullish-rate rows had negative IC.

Conclusion:

- Balanced sampling remains the best lever, but this exact single-head setup is
  not stable enough.
- Next step should be a research-only balanced-sampler dual-head experiment with
  validation gating on direction + IC + bullish-rate bounds.
- Do not promote the 10-epoch single-head candidate.

## Continuation Update: Balanced-Sampler Dual-Head Gate Run

Updated:

```text
dl_dual_head_experiment.py
```

Added research-only controls:

```text
--seeds
--lr
--balanced-sampler
--from-scratch
--selection-metric {loss,gate}
--bullish-min / --bullish-max
--default-extra-features
--output / --csv-output
```

The dual-head experiment now reports both return-head and direction-head
direction accuracy, bullish rates, actual bullish rate, IC, and prediction
distribution. Gate selection prioritizes return-head direction, head direction,
IC, MAE, and a bullish-rate bound.

First run, balanced sampler plus balanced BCE:

```powershell
python dl_dual_head_experiment.py --panel data\experiment\directional_feature_panel_fmp.parquet --default-extra-features --weights 0.1,0.25 --thresholds 0.01 --epochs 5 --batch-size 256 --val-days 252 --balanced --balanced-sampler --from-scratch --seeds 20260505,20260506,20260507 --lr 0.001 --selection-metric gate --output data\experiment\dual_head_balanced_sampler_comparison.json --csv-output data\experiment\dual_head_balanced_sampler_comparison.csv
```

Loose gate result:

```text
Mean MAE: 0.067120
Mean RMSE: 0.085576
Mean return direction: 60.94%
Mean head direction: 37.46%
Mean IC_Spearman: -0.0627
Mean return bullish rate: 89.36%
Mean head bullish rate: 3.46%
```

Interpretation:

- Return direction looked good but was still bullish-heavy.
- Direction head collapsed mostly bearish.
- This is not stable directional learning.

Strict gate rerun with out-of-bound bullish rates heavily penalized:

```text
Mean MAE: 0.069957
Mean RMSE: 0.088732
Mean return direction: 48.70%
Mean head direction: 38.71%
Mean IC_Spearman: -0.0759
Mean return bullish rate: 60.38%
Mean head bullish rate: 13.08%
```

Interpretation:

- Strict gating fixed return-head bullish collapse.
- It exposed the underlying weakness: direction and IC were not good enough.

Sampler-only rerun without balanced BCE `pos_weight`:

```powershell
python dl_dual_head_experiment.py --panel data\experiment\directional_feature_panel_fmp.parquet --default-extra-features --weights 0.1,0.25 --thresholds 0.01 --epochs 5 --batch-size 256 --val-days 252 --balanced-sampler --from-scratch --seeds 20260505,20260506,20260507 --lr 0.001 --selection-metric gate --output data\experiment\dual_head_sampler_only_strict_gate.json --csv-output data\experiment\dual_head_sampler_only_strict_gate.csv
```

Result:

```text
Mean MAE: 0.069570
Mean RMSE: 0.088332
Mean return direction: 50.84%
Mean head direction: 54.54%
Mean IC_Spearman: -0.0896
Mean return bullish rate: 63.30%
Mean head bullish rate: 84.19%
```

Interpretation:

- Removing `pos_weight` improved the direction head versus the all-bearish
  failure mode.
- It did not improve the return head enough, and IC stayed negative.
- The direction head shifted toward bullish-heavy predictions.

Conclusion:

- Balanced-sampler dual-head with the current BCE setup is not a promotion
  path.
- The gate is useful and should remain in the research script.
- The next objective should stop trying to rely on BCE direction classification
  alone. Better options are:
  - train the return head with an explicit cross-sectional/ranking objective,
  - select by non-negative IC and bounded bullish rate as hard constraints,
  - or test a small multi-task objective where the direction head influences
    representation learning but final sign/rank comes from the return head.

## Continuation Update: Return-Head Rank/IC Hard-Gate Run

Updated:

```text
dl_sign_regularized_experiment.py
```

Added research-only diagnostics and controls:

```text
Daily_IC_Mean
Daily_IC_Positive_Rate
Daily_Directional_Accuracy
--nll-weights
--hard-gate
--ic-min
--direction-min
```

The selector can now heavily penalize checkpoints that miss:

```text
IC_Spearman >= --ic-min
Directional_Accuracy >= --direction-min
--bullish-min <= pct_bullish_pred <= --bullish-max
```

Focused rank/IC grid:

```powershell
python dl_sign_regularized_experiment.py --seeds 20260505,20260506,20260507 --corr-weights 0.05 --balance-weights 0.5,1.0 --rank-weights 0.01,0.05 --nll-weights 1.0,0.5 --balance-temperature 0.05 --rank-temperature 0.02 --balanced-sampler --hard-gate --ic-min 0 --direction-min 0.5085 --epochs 5 --batch-size 256 --val-days 252 --lr 0.001 --output data\experiment\sign_regularized_hard_gate_rank_ic.json --csv-output data\experiment\sign_regularized_hard_gate_rank_ic.csv
```

Aggregate:

```text
Mean MAE: 0.070473
Mean RMSE: 0.090142
Mean Direction: 46.56%
Mean IC_Spearman: -0.0853
Mean Daily_IC_Mean: -0.0811
Mean Daily_IC_Positive_Rate: 40.76%
Mean bullish rate: 53.19%
```

Best pooled-IC row:

```text
seed 20260505, corr 0.05, balance 1.0, rank 0.01, nll 1.0:
MAE 0.064108, RMSE 0.083279, Direction 58.15%, IC +0.0403,
Daily_IC_Mean -0.0232, bullish 75.56%
```

With the strict 75% bullish cap, no row satisfied all hard gates:

```text
IC >= 0
Direction >= 50.85%
35% <= bullish <= 75%
```

Sanity check with a slightly wider 80% bullish cap on the best setup across
five seeds:

```powershell
python dl_sign_regularized_experiment.py --seeds 20260505,20260506,20260507,20260508,20260509 --corr-weights 0.05 --balance-weights 1.0 --rank-weights 0.01 --nll-weights 1.0 --balance-temperature 0.05 --rank-temperature 0.02 --balanced-sampler --hard-gate --ic-min 0 --direction-min 0.5085 --bullish-max 0.80 --epochs 5 --batch-size 256 --val-days 252 --lr 0.001 --output data\experiment\sign_regularized_best_rank_ic_5seed.json --csv-output data\experiment\sign_regularized_best_rank_ic_5seed.csv
```

Five-seed aggregate:

```text
Mean MAE: 0.069628
Mean RMSE: 0.089292
Mean Direction: 48.10%
Mean IC_Spearman: -0.0764
Mean Daily_IC_Mean: -0.0900
Mean Daily_IC_Positive_Rate: 41.41%
Mean bullish rate: 56.76%
```

Interpretation:

- The rank/IC objective can create an attractive single checkpoint, but the
  signal did not repeat across seeds.
- Daily cross-sectional IC remained negative even for the best pooled-IC row.
- Widening the bullish cap to 80% only preserved the seed-20260505 result; the
  five-seed mean still failed direction and IC requirements.

Conclusion:

- This objective family is still not stable enough for promotion.
- Hard-gated validation is useful and should stay.
- The next useful research direction is to change the sampling/evaluation unit
  from random pooled windows to date-grouped batches, because the target
  business problem is cross-sectional ranking by date. Batch-level rank loss on
  randomly mixed dates is not matching the validation objective tightly enough.

## Continuation Update: Date-Grouped Cross-Sectional Rank Training

Updated:

```text
dl_sign_regularized_experiment.py
```

Added research-only date-grouped training controls:

```text
--date-grouped-batches
--min-date-batch-size
--dates-per-batch
```

Implementation detail:

- Training batches can now preserve date groups so rank/correlation/balance
  losses are computed within each prediction date.
- `--dates-per-batch` packs multiple date groups into one optimizer batch for
  speed while keeping auxiliary losses grouped by date internally.
- `--balanced-sampler` and `--date-grouped-batches` are mutually exclusive.

Smoke test:

```powershell
python dl_sign_regularized_experiment.py --seeds 20260505 --corr-weights 0.05 --balance-weights 0.5 --rank-weights 0.01 --nll-weights 1.0 --date-grouped-batches --dates-per-batch 32 --hard-gate --ic-min 0 --direction-min 0.5085 --epochs 1 --output data\experiment\date_grouped_smoke.json --csv-output data\experiment\date_grouped_smoke.csv
```

Result:

```text
date_count: 1175
optimizer batches per epoch with dates_per_batch=32: 37
```

Focused date-grouped grid:

```powershell
python dl_sign_regularized_experiment.py --seeds 20260505,20260506,20260507 --corr-weights 0.05 --balance-weights 0.1,0.5 --rank-weights 0.01,0.05 --nll-weights 1.0,0.5 --balance-temperature 0.05 --rank-temperature 0.02 --date-grouped-batches --dates-per-batch 32 --hard-gate --ic-min 0 --direction-min 0.5085 --bullish-min 0.35 --bullish-max 0.75 --epochs 5 --batch-size 256 --val-days 252 --lr 0.001 --output data\experiment\sign_regularized_date_grouped_rank_ic.json --csv-output data\experiment\sign_regularized_date_grouped_rank_ic.csv
```

Aggregate:

```text
Mean MAE: 0.068795
Mean RMSE: 0.088063
Mean Direction: 49.78%
Mean IC_Spearman: -0.0636
Mean Daily_IC_Mean: -0.0783
Mean Daily_IC_Positive_Rate: 42.25%
Mean bullish rate: 60.40%
Strict gate passing rows: 2 / 24
```

Best strict-gate row:

```text
seed 20260505, corr 0.05, balance 0.5, rank 0.01, nll 0.5:
MAE 0.068350, RMSE 0.087126, Direction 51.79%, IC +0.0479,
Daily_IC_Mean -0.0254, bullish 61.38%
```

Five-seed repeat of that best setup:

```powershell
python dl_sign_regularized_experiment.py --seeds 20260505,20260506,20260507,20260508,20260509 --corr-weights 0.05 --balance-weights 0.5 --rank-weights 0.01 --nll-weights 0.5 --balance-temperature 0.05 --rank-temperature 0.02 --date-grouped-batches --dates-per-batch 32 --hard-gate --ic-min 0 --direction-min 0.5085 --bullish-min 0.35 --bullish-max 0.75 --epochs 5 --batch-size 256 --val-days 252 --lr 0.001 --output data\experiment\sign_regularized_date_grouped_best_5seed.json --csv-output data\experiment\sign_regularized_date_grouped_best_5seed.csv
```

Five-seed aggregate:

```text
Mean MAE: 0.071762
Mean RMSE: 0.090984
Mean Direction: 49.33%
Mean IC_Spearman: -0.0806
Mean Daily_IC_Mean: -0.0935
Mean Daily_IC_Positive_Rate: 41.56%
Mean bullish rate: 62.37%
Strict gate passing rows: 1 / 5
```

Interpretation:

- Date-grouped rank training is directionally more aligned with the business
  objective and produced the cleanest single checkpoint so far:
  bounded bullish rate, positive pooled IC, and direction above production.
- It still failed seed stability. Only seed `20260505` passed the strict gate
  in the five-seed repeat.
- Daily IC stayed negative even in the best row, which means the pooled IC gain
  is not yet a robust per-date cross-sectional ranking signal.

Conclusion:

- Keep the date-grouped training infrastructure; it is the correct shape for
  future cross-sectional objectives.
- Do not promote this candidate.
- Next useful work should focus on stabilizing date-grouped training:
  lower learning rate, longer training, stronger early stopping based on
  Daily_IC_Mean, and possibly target demeaning/standardization within each date
  so the model learns relative returns instead of mixed market-regime drift.

## Continuation Update: PyTorch Training-Speed Controls

Updated:

```text
dl_sign_regularized_experiment.py
```

Added research-only PyTorch training controls inspired by the 1Cycle/AMP/DataLoader
optimization notes:

```text
--device {auto,cpu,cuda}
--amp
--pin-memory
--num-workers
--cudnn-benchmark
--scheduler {cosine,onecycle,none}
--max-lr
--onecycle-pct-start
--onecycle-div-factor
--onecycle-final-div-factor
```

Implementation details:

- CUDA is available on this machine:

```text
NVIDIA GeForce GTX 1650 Ti
torch 2.5.1+cu121
```

- AMP is enabled only on CUDA.
- Loss calculations are forced back to FP32 after the autocast forward pass to
  avoid FP16 instability in `gaussian_nll` and the rank/correlation losses.
- The previous `zero_grad(set_to_none=True)`, gradient clipping, AdamW, and
  `torch.no_grad()` validation patterns were already in place.
- `OneCycleLR` steps per optimizer batch. `CosineAnnealingLR` remains the
  default for backward compatibility.

Smoke test:

```powershell
python dl_sign_regularized_experiment.py --seeds 20260505 --corr-weights 0.05 --balance-weights 0.5 --rank-weights 0.01 --nll-weights 0.5 --date-grouped-batches --dates-per-batch 32 --hard-gate --ic-min 0 --direction-min 0.5085 --epochs 1 --scheduler onecycle --lr 0.001 --max-lr 0.003 --device auto --amp --pin-memory --num-workers 0 --cudnn-benchmark --output data\experiment\onecycle_amp_smoke.json --csv-output data\experiment\onecycle_amp_smoke.csv
```

Result:

```text
CUDA/AMP/OneCycle path completed successfully.
```

Focused 5-seed OneCycle/AMP run:

```powershell
python dl_sign_regularized_experiment.py --seeds 20260505,20260506,20260507,20260508,20260509 --corr-weights 0.05 --balance-weights 0.5 --rank-weights 0.01 --nll-weights 0.5 --balance-temperature 0.05 --rank-temperature 0.02 --date-grouped-batches --dates-per-batch 64 --hard-gate --ic-min 0 --direction-min 0.5085 --bullish-min 0.35 --bullish-max 0.75 --epochs 8 --scheduler onecycle --lr 0.001 --max-lr 0.001 --onecycle-pct-start 0.45 --onecycle-div-factor 10 --onecycle-final-div-factor 1000 --device auto --amp --pin-memory --num-workers 0 --cudnn-benchmark --output data\experiment\sign_regularized_date_grouped_onecycle_amp_5seed.json --csv-output data\experiment\sign_regularized_date_grouped_onecycle_amp_5seed.csv
```

Aggregate:

```text
Mean MAE: 0.073124
Mean RMSE: 0.092814
Mean Direction: 50.27%
Mean IC_Spearman: -0.0630
Mean Daily_IC_Mean: -0.0792
Mean Daily_IC_Positive_Rate: 42.19%
Mean bullish rate: 59.73%
Strict gate passing rows: 0 / 5
```

Interpretation:

- The speed/accelerator controls work and should remain available for research
  sweeps.
- This specific OneCycle schedule did not improve stability or IC versus the
  previous date-grouped cosine run.
- Do not promote any OneCycle/AMP result from this run.
- Next model-quality step remains date-level target demeaning/standardization
  and Daily_IC-based selection, not more scheduler-only tuning.

## Continuation Update: Date-Level Target Normalization

Updated:

```text
dl_sign_regularized_experiment.py
```

Added research-only quality controls:

```text
--aux-target-transform {raw,demean,zscore}
--daily-ic-min
--daily-ic-weight
```

Implementation detail:

- Raw-return NLL is still trained against the original target.
- Cross-sectional auxiliary losses can now use transformed targets:
  - `raw`: original target
  - `demean`: target minus same-date mean
  - `zscore`: same-date demeaned and scaled target
- Date-grouped rank/correlation/balance losses apply this transform within
  each date group.
- Hard-gated checkpoint selection can now include `Daily_IC_Mean`.

Smoke test:

```powershell
python dl_sign_regularized_experiment.py --seeds 20260505 --corr-weights 0.05 --balance-weights 0.5 --rank-weights 0.01 --nll-weights 0.5 --aux-target-transform demean --date-grouped-batches --dates-per-batch 64 --hard-gate --ic-min 0 --daily-ic-min 0 --direction-min 0.5085 --epochs 1 --scheduler cosine --device auto --output data\experiment\target_transform_smoke.json --csv-output data\experiment\target_transform_smoke.csv
```

Focused three-seed comparisons:

```powershell
python dl_sign_regularized_experiment.py --seeds 20260505,20260506,20260507 --corr-weights 0.05 --balance-weights 0.5 --rank-weights 0.01 --nll-weights 0.5 --aux-target-transform demean --balance-temperature 0.05 --rank-temperature 0.02 --date-grouped-batches --dates-per-batch 64 --hard-gate --ic-min 0 --daily-ic-min 0 --direction-min 0.5085 --daily-ic-weight 0.75 --bullish-min 0.35 --bullish-max 0.75 --epochs 8 --scheduler cosine --lr 0.001 --device auto --output data\experiment\date_grouped_demean_dailyic_3seed.json --csv-output data\experiment\date_grouped_demean_dailyic_3seed.csv

python dl_sign_regularized_experiment.py --seeds 20260505,20260506,20260507 --corr-weights 0.05 --balance-weights 0.5 --rank-weights 0.01 --nll-weights 0.5 --aux-target-transform zscore --balance-temperature 0.05 --rank-temperature 0.02 --date-grouped-batches --dates-per-batch 64 --hard-gate --ic-min 0 --daily-ic-min 0 --direction-min 0.5085 --daily-ic-weight 0.75 --bullish-min 0.35 --bullish-max 0.75 --epochs 8 --scheduler cosine --lr 0.001 --device auto --output data\experiment\date_grouped_zscore_dailyic_3seed.json --csv-output data\experiment\date_grouped_zscore_dailyic_3seed.csv
```

Demean aggregate:

```text
Mean MAE: 0.068238
Mean RMSE: 0.087530
Mean Direction: 50.71%
Mean IC_Spearman: -0.0280
Mean Daily_IC_Mean: -0.0398
Mean Daily_IC_Positive_Rate: 43.23%
Mean bullish rate: 56.14%
Strict daily gate passing rows: 0 / 3
```

Z-score aggregate:

```text
Mean MAE: 0.068234
Mean RMSE: 0.087429
Mean Direction: 51.00%
Mean IC_Spearman: -0.0234
Mean Daily_IC_Mean: -0.0379
Mean Daily_IC_Positive_Rate: 43.23%
Mean bullish rate: 56.51%
Strict daily gate passing rows: 0 / 3
```

Lower learning-rate, longer z-score run:

```powershell
python dl_sign_regularized_experiment.py --seeds 20260505,20260506,20260507,20260508,20260509 --corr-weights 0.05 --balance-weights 0.5 --rank-weights 0.01 --nll-weights 0.5 --aux-target-transform zscore --balance-temperature 0.05 --rank-temperature 0.02 --date-grouped-batches --dates-per-batch 64 --hard-gate --ic-min 0 --daily-ic-min -0.02 --direction-min 0.5085 --daily-ic-weight 0.75 --bullish-min 0.35 --bullish-max 0.75 --epochs 12 --scheduler cosine --lr 0.0005 --device auto --output data\experiment\date_grouped_zscore_low_lr_5seed.json --csv-output data\experiment\date_grouped_zscore_low_lr_5seed.csv
```

Five-seed aggregate:

```text
Mean MAE: 0.068097
Mean RMSE: 0.087377
Mean Direction: 49.69%
Mean IC_Spearman: -0.0395
Mean Daily_IC_Mean: -0.0664
Mean Daily_IC_Positive_Rate: 40.63%
Mean bullish rate: 56.34%
Relaxed daily gate passing rows: 0 / 5
```

Best row from the lower-LR z-score run:

```text
seed 20260505:
MAE 0.065488, RMSE 0.084996, Direction 52.68%, IC +0.0634,
Daily_IC_Mean -0.0421, bullish 57.59%
```

Interpretation:

- Date-level target normalization improved pooled IC in some rows and kept
  bullish rate better bounded.
- It did not solve Daily IC. Even the best row still had negative
  `Daily_IC_Mean`.
- Lower LR and longer training improved price-error metrics but did not produce
  repeated-seed cross-sectional stability.

Conclusion:

- Keep `--aux-target-transform` and Daily IC gates in the harness.
- Do not promote any normalized-target candidate yet.
- The next quality lever should be model output decomposition:
  train one head for raw return magnitude and a separate date-relative/rank
  head for cross-sectional signal, then evaluate whether the rank head can
  drive selection without forcing raw return signs to carry both jobs.

## Continuation Update: Rank-Head Selection Objective and Ensemble Testing

Updated:

```text
dl_rank_head_experiment.py
dl_rank_head_ensemble_eval.py
```

Rationale:

- Prior tests showed raw sign accuracy is not the cleanest signal.
- The rank head is better judged as a date-relative selection model:
  top-ranked names should outperform bottom-ranked names on the same date.
- Checkpoint selection was changed from the legacy sign/IC score to a
  selection objective using:
  - centered long-short spread
  - spread positive rate
  - Daily_IC_Mean
  - pooled IC
  - bounded bullish rate

Key implementation details:

- Rank-head checkpoints now save their matching scaler JSON so they are
  reloadable outside the original training process.
- `dl_rank_head_ensemble_eval.py` reloads saved rank-head checkpoints,
  centers each model's rank score by date, averages the centered rank scores,
  and reports the same IC/selection metrics.
- Production `deep_learning_model.py` was not modified.

Best single-setting validation so far:

```powershell
python dl_rank_head_experiment.py --seeds 20260505,20260506,20260507,20260508,20260509 --epochs 8 --lr 0.0005 --scheduler cosine --device auto --amp --pin-memory --date-grouped-batches --dates-per-batch 64 --aux-target-transform zscore --nll-weights 0.5 --corr-weights 0.05 --rank-weights 0.005 --daily-ic-min -0.02 --spread-min 0.0 --spread-positive-rate-min 0.55 --hard-gate --selection-score-mode selection --output data\experiment\rank_head_selection_objective_scaler_5seed.json --csv-output data\experiment\rank_head_selection_objective_scaler_5seed.csv
```

Five-seed centered rank aggregate:

```text
Mean IC_Spearman: +0.0488
Mean Daily_IC_Mean: +0.0935
Mean long-short spread: +0.0512
Minimum long-short spread: +0.0120
Mean spread positive rate: 67.66%
Mean bullish rate: 44.33%
Mean directional accuracy: 46.61%
```

Top-member ensemble checks from that run:

```powershell
python dl_rank_head_ensemble_eval.py --results data\experiment\rank_head_selection_objective_scaler_5seed.json --device auto --amp --top-n 3 --output data\experiment\rank_head_selection_objective_ensemble_top3.json --csv-output data\experiment\rank_head_selection_objective_ensemble_members_top3.csv
```

Top-3 ensemble:

```text
IC_Spearman: +0.088653
Daily_IC_Mean: +0.106585
Long-short spread: +0.078004
Spread positive rate: 75.00%
Bullish rate: 45.65%
Directional accuracy: 49.22%
```

Top-2 ensemble:

```text
IC_Spearman: +0.121458
Daily_IC_Mean: +0.121094
Long-short spread: +0.073797
Spread positive rate: 72.66%
Bullish rate: 50.33%
Directional accuracy: 52.79%
```

Interpretation:

- The ensemble path is the strongest result so far for selection/ranking.
- Top-3 gives the best long-short spread and hit rate.
- Top-2 gives stronger pooled IC and directional accuracy but less model
  diversity.
- This supports an ensemble rank signal as the next production candidate,
  not a single-seed raw sign forecaster.

Robustness checks:

Short holdout (`--val-days 126`):

```text
Result: rejected as a production gate.
Reason: validation sample count was too small/discrete for this panel and
sequence length. Top-3 ensemble long-short spread was -0.020117 despite
positive IC, so it is not a reliable promotion window.
```

Long holdout (`--val-days 504`):

```text
Top-3 ensemble IC_Spearman: +0.025612
Top-3 ensemble Daily_IC_Mean: +0.023158
Top-3 ensemble long-short spread: +0.039360
Top-3 ensemble spread positive rate: 56.84%
Top-3 ensemble bullish rate: 50.06%
```

Interpretation:

- The 504-day holdout is positive but materially weaker than the 252-day
  holdout.
- This is not enough to call the rank-head ensemble production-ready yet.
- The next objective should be walk-forward validation with several
  non-overlapping 252-day windows, then only consider promotion if the ensemble
  keeps positive long-short spread and positive Daily_IC_Mean across windows.
