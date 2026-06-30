# DL Walk-Forward Backtest — Verdict (2026-06-30)

Run: `dl_walkforward_backtest.py --cycles 0 --first-epochs 8 --warm-epochs 2`
(production TCN, warm-start chained, faithfully replaying the live daily-warm-start regime).

## Headline

Over **427 genuinely independent, look-ahead-free 21-day windows** (61 decision dates ×
7 MAG7, 2021-05 → 2026-05), the production DeepLearning model has **no out-of-sample
directional skill**:

| Metric | Pooled (ALL) |
|---|---|
| Independent N | **427** |
| Directional accuracy | **48.7%** |
| Wilson 95% CI | **[44.0%, 53.4%]** — straddles 50% |
| Significant? | **No** |
| Correlation (forecast vs realized) | **−0.005** (≈ zero) |

The CI is now *tight* (±~5pp on 427 obs, vs the live log's ±~37pp on 3), so this is a
statistically meaningful conclusion, not a small-sample shrug.

## Per ticker (61 independent windows each)

| Ticker | Dir | 95% CI | Corr | MAE |
|---|---|---|---|---|
| AAPL | 47.5% | [36%, 60%] | −0.089 | 7.12 |
| AMZN | 47.5% | [36%, 60%] | −0.124 | 8.39 |
| GOOG | 47.5% | [36%, 60%] | −0.110 | 7.02 |
| META | 49.2% | [37%, 61%] | −0.089 | 10.26 |
| MSFT | 50.8% | [39%, 63%] | −0.074 | 6.39 |
| NVDA | 49.2% | [37%, 61%] | +0.056 | 13.78 |
| TSLA | 49.2% | [37%, 61%] | +0.059 | 16.96 |

Every ticker is ~47–51% — indistinguishable from a coin flip, and most carry a slightly
*negative* correlation. None is significant.

## Why this differs from the live leaderboard (where DL "wins")

1. **MAE rewards shrinkage, not direction.** DL wins the live MAE ranking because it
   forecasts small, cautious numbers (mean forecast +1.46% vs mean realized +2.32%) —
   on noisy returns, low-magnitude forecasts minimize MAE without any directional edge.
2. **Tiny live sample.** The live GOOG/DL 92% / 67% headline rested on ~3 overlapping
   windows. Over 61 independent windows GOOG/DL is 47.5%.
3. **In-sample contamination of the live model.** The live checkpoint is warm-started on
   *all* history including the eval period; the walk-forward only ever knows the past.

## Sanity (not a harness artifact)

- Forecasts are varied: std 5.21, range −18.8% … +20.9% (the model discriminates).
- Realized returns sensible: range −34% … +71%, mean +2.3%.
- DL forecasts positive 70.5% of the time; realized positive 58.5% — over-bullish but
  still only ~49% correct on direction.

## Implication (decision for the user — NOT yet acted on)

The page's "Best Recent Fit = DL" is a low-MAE/shrinkage + small-sample artifact, not
genuine directional skill. Lever 3's ✓/~ markers already flag the live small sample as
not-significant; this walk-forward is the definitive confirmation. Open options:
(a) leave as-is (markers already honest); (b) surface the walk-forward verdict on the
page next to DL; (c) feed walk-forward Corr/Dir into the consensus skill-gate so a model
with no real edge is floored regardless of a lucky 3-window live Corr. All three respect
"don't remove models" — DL stays in the suite either way.

Reproduce: `python dl_walkforward_backtest.py --cycles 0 --first-epochs 8 --warm-epochs 2`
→ `data/dl_walkforward_results.csv` + `data/dl_walkforward_summary.{csv,json}`.
