# DL Regime Gate Report

- Results dir: `data\experiment\final4_growth24_earnings_stress_weight_8e2seed_probe`
- Status: `pass`
- Stress regimes: current_2026, gfc_2008, q4_2018_drawdown, rate_bear_2022

## Basket Gates

### top1_bottom1

- Status: `fail`
- Mean spread all regimes: 0.139392
- Mean spread stress regimes: 0.139392
- Worst stress drawdown: -26.59%

Failures:
- q4_2018_drawdown spread -0.011048 < 0.000000
- q4_2018_drawdown hit 33.33% < 50.00%
- q4_2018_drawdown drawdown -26.59% < -25.00%

### top2_bottom2

- Status: `pass`
- Mean spread all regimes: 0.099037
- Mean spread stress regimes: 0.099037
- Worst stress drawdown: -4.54%

### top3_bottom3

- Status: `fail`
- Mean spread all regimes: 0.062412
- Mean spread stress regimes: 0.062412
- Worst stress drawdown: -8.07%

Failures:
- q4_2018_drawdown spread -0.006145 < 0.000000
- q4_2018_drawdown hit 33.33% < 50.00%

## Results

| Regime | Basket | Days | Window | Spread | Hit | Max DD | Equity |
|---|---|---:|---|---:|---:|---:|---:|
| current_2026 | top1_bottom1 | 3 | 2026-02-03 -> 2026-04-06 | 0.363933 | 66.67% | 0.00% | 2.149891 |
| current_2026 | top2_bottom2 | 3 | 2026-02-03 -> 2026-04-06 | 0.237472 | 66.67% | 0.00% | 1.701790 |
| current_2026 | top3_bottom3 | 3 | 2026-02-03 -> 2026-04-06 | 0.168562 | 66.67% | 0.00% | 1.480468 |
| gfc_2008 | top1_bottom1 | 3 | 2009-04-02 -> 2009-06-03 | 0.100977 | 100.00% | 0.00% | 1.329940 |
| gfc_2008 | top2_bottom2 | 3 | 2009-04-02 -> 2009-06-03 | 0.055001 | 66.67% | -2.73% | 1.167810 |
| gfc_2008 | top3_bottom3 | 3 | 2009-04-02 -> 2009-06-03 | 0.002970 | 66.67% | -8.07% | 1.003232 |
| q4_2018_drawdown | top1_bottom1 | 3 | 2018-10-03 -> 2018-12-03 | -0.011048 | 33.33% | -26.59% | 0.914874 |
| q4_2018_drawdown | top2_bottom2 | 3 | 2018-10-03 -> 2018-12-03 | 0.021019 | 66.67% | -4.54% | 1.060837 |
| q4_2018_drawdown | top3_bottom3 | 3 | 2018-10-03 -> 2018-12-03 | -0.006145 | 33.33% | -2.15% | 0.981470 |
| rate_bear_2022 | top1_bottom1 | 3 | 2022-10-04 -> 2022-12-02 | 0.103705 | 100.00% | 0.00% | 1.326163 |
| rate_bear_2022 | top2_bottom2 | 3 | 2022-10-04 -> 2022-12-02 | 0.082657 | 100.00% | 0.00% | 1.265962 |
| rate_bear_2022 | top3_bottom3 | 3 | 2022-10-04 -> 2022-12-02 | 0.084262 | 100.00% | 0.00% | 1.271657 |
