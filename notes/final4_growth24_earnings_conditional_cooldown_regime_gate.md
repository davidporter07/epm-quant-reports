# DL Regime Gate Report

- Results dir: `data\experiment\final4_growth24_earnings_conditional_cooldown_probe`
- Status: `fail`
- Stress regimes: current_2026, gfc_2008, q4_2018_drawdown, rate_bear_2022

## Basket Gates

### top1_bottom1

- Status: `fail`
- Mean spread all regimes: 0.062784
- Mean spread stress regimes: 0.019977
- Worst stress drawdown: -35.64%

Failures:
- q4_2018_drawdown spread -0.022187 < 0.000000
- q4_2018_drawdown hit 33.33% < 50.00%
- rate_bear_2022 spread -0.093507 < 0.000000
- rate_bear_2022 hit 33.33% < 50.00%
- rate_bear_2022 drawdown -35.64% < -25.00%

### top2_bottom2

- Status: `fail`
- Mean spread all regimes: 0.000000
- Mean spread stress regimes: 0.000000
- Worst stress drawdown: 0.00%

### top3_bottom3

- Status: `fail`
- Mean spread all regimes: 0.000000
- Mean spread stress regimes: 0.000000
- Worst stress drawdown: 0.00%

## Results

| Regime | Basket | Days | Window | Spread | Hit | Max DD | Equity |
|---|---|---:|---|---:|---:|---:|---:|
| ai_mega_cap_2023_2025 | top1_bottom1 | 3 | 2025-10-08 -> 2025-12-08 | 0.098629 | 33.33% | -4.79% | 1.258340 |
| china_oil_2015 | top1_bottom1 | 3 | 2016-01-29 -> 2016-03-31 | 0.177608 | 100.00% | 0.00% | 1.624799 |
| covid_2020 | top1_bottom1 | 3 | 2020-10-20 -> 2020-12-18 | 0.050974 | 66.67% | -4.24% | 1.151294 |
| current_2026 | top1_bottom1 | 3 | 2026-02-03 -> 2026-04-06 | 0.149251 | 100.00% | 0.00% | 1.455820 |
| euro_debt_2011 | top1_bottom1 | 3 | 2012-05-01 -> 2012-06-29 | 0.116398 | 100.00% | 0.00% | 1.360530 |
| gfc_2008 | top1_bottom1 | 3 | 2009-04-02 -> 2009-06-03 | 0.046350 | 66.67% | 0.00% | 1.135143 |
| post_gfc_recovery | top1_bottom1 | 3 | 2011-01-31 -> 2011-03-31 | 0.041539 | 66.67% | -4.06% | 1.124441 |
| q4_2018_drawdown | top1_bottom1 | 3 | 2018-10-03 -> 2018-12-03 | -0.022187 | 33.33% | -0.08% | 0.907637 |
| rate_bear_2022 | top1_bottom1 | 3 | 2022-10-04 -> 2022-12-02 | -0.093507 | 33.33% | -35.64% | 0.706598 |
