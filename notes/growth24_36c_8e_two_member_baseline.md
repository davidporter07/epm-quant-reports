# Growth24 36-Cycle 8-Epoch Two-Member Baseline

## Command

```text
scripts/run_growth24_research_ladder.ps1
  -Device cuda -Amp
  -Seeds "20260506,20260507"
  -SpreadWeights "0.0"
  -HistoricalCycles 36
  -HistoricalEpochs 8
  -HistoricalTopN 2
  -SkipCurrent
```

## Two-Member Result

```text
asof_start: 2023-05-11
asof_end: 2026-04-17
mean_long_return: 0.094231
mean_short_return: 0.013312
mean_long_short_return: 0.080919
median_long_short_return: 0.025446
std_long_short_return: 0.160462
spread_hit_rate: 0.611111
long_hit_rate: 0.666667
short_hit_rate: 0.472222
max_drawdown: -0.155361
naive_sharpe: 8.005337
```

## Prior Validated Single-Member Policy

```text
asof_start: 2023-04-12
asof_end: 2026-03-18
mean_long_return: 0.093732
mean_short_return: 0.011143
mean_long_short_return: 0.082589
median_long_short_return: 0.054513
std_long_short_return: 0.145669
spread_hit_rate: 0.750000
long_hit_rate: 0.694444
short_hit_rate: 0.500000
max_drawdown: -0.198607
naive_sharpe: 9.000265
```

## Interpretation

- The two-member ensemble does not beat the validated single-member policy.
  Mean spread is slightly lower, spread hit rate is materially lower, and
  naive Sharpe is lower.
- The two-member run improves max drawdown, but the weaker hit rate and median
  spread argue against policy promotion.
- Keep the live paper rules unchanged. Further model work should focus on
  regime, abstention, and concentration controls instead of adding ensemble
  members or epochs.
