# DL Regime Gate Report

- Results dir: `data\experiment\final4_growth24_earnings_stress_weight_probe`
- Status: `fail`
- Stress regimes: current_2026, gfc_2008, q4_2018_drawdown, rate_bear_2022

## Basket Gates

### top1_bottom1

- Status: `fail`
- Mean spread all regimes: 0.081010
- Mean spread stress regimes: 0.081010
- Worst stress drawdown: -37.13%

Failures:
- q4_2018_drawdown spread -0.079998 < 0.000000
- q4_2018_drawdown hit 33.33% < 50.00%
- rate_bear_2022 spread -0.100693 < 0.000000
- rate_bear_2022 hit 33.33% < 50.00%
- rate_bear_2022 drawdown -37.13% < -25.00%

### top2_bottom2

- Status: `fail`
- Mean spread all regimes: 0.064223
- Mean spread stress regimes: 0.064223
- Worst stress drawdown: -17.07%

Failures:
- rate_bear_2022 spread -0.037028 < 0.000000
- rate_bear_2022 hit 33.33% < 50.00%

### top3_bottom3

- Status: `fail`
- Mean spread all regimes: 0.051158
- Mean spread stress regimes: 0.051158
- Worst stress drawdown: -9.76%

Failures:
- gfc_2008 spread -0.002611 < 0.000000
- q4_2018_drawdown spread -0.030731 < 0.000000
- q4_2018_drawdown hit 33.33% < 50.00%

## Results

| Regime | Basket | Days | Window | Spread | Hit | Max DD | Equity |
|---|---|---:|---|---:|---:|---:|---:|
| current_2026 | top1_bottom1 | 3 | 2026-02-03 -> 2026-04-06 | 0.401993 | 100.00% | 0.00% | 2.399808 |
| current_2026 | top2_bottom2 | 3 | 2026-02-03 -> 2026-04-06 | 0.256308 | 100.00% | 0.00% | 1.806505 |
| current_2026 | top3_bottom3 | 3 | 2026-02-03 -> 2026-04-06 | 0.215681 | 100.00% | 0.00% | 1.706552 |
| gfc_2008 | top1_bottom1 | 3 | 2009-04-02 -> 2009-06-03 | 0.102737 | 100.00% | 0.00% | 1.340943 |
| gfc_2008 | top2_bottom2 | 3 | 2009-04-02 -> 2009-06-03 | 0.027752 | 66.67% | -4.42% | 1.081496 |
| gfc_2008 | top3_bottom3 | 3 | 2009-04-02 -> 2009-06-03 | -0.002611 | 66.67% | -8.07% | 0.986880 |
| q4_2018_drawdown | top1_bottom1 | 3 | 2018-10-03 -> 2018-12-03 | -0.079998 | 33.33% | -17.64% | 0.749984 |
| q4_2018_drawdown | top2_bottom2 | 3 | 2018-10-03 -> 2018-12-03 | 0.009860 | 66.67% | -8.82% | 1.022240 |
| q4_2018_drawdown | top3_bottom3 | 3 | 2018-10-03 -> 2018-12-03 | -0.030731 | 33.33% | -9.76% | 0.907534 |
| rate_bear_2022 | top1_bottom1 | 3 | 2022-10-04 -> 2022-12-02 | -0.100693 | 33.33% | -37.13% | 0.690189 |
| rate_bear_2022 | top2_bottom2 | 3 | 2022-10-04 -> 2022-12-02 | -0.037028 | 33.33% | -17.07% | 0.885042 |
| rate_bear_2022 | top3_bottom3 | 3 | 2022-10-04 -> 2022-12-02 | 0.022295 | 66.67% | -2.47% | 1.065362 |
