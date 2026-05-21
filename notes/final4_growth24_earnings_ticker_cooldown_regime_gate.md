# DL Regime Gate Report

- Results dir: `data\experiment\final4_growth24_earnings_ticker_cooldown_probe`
- Status: `fail`
- Stress regimes: current_2026, gfc_2008, q4_2018_drawdown, rate_bear_2022

## Basket Gates

### top1_bottom1

- Status: `fail`
- Mean spread all regimes: 0.037111
- Mean spread stress regimes: -0.037788
- Worst stress drawdown: -34.68%

Failures:
- current_2026 spread -0.084079 < 0.000000
- current_2026 drawdown -34.68% < -25.00%
- q4_2018_drawdown spread -0.124646 < 0.000000
- q4_2018_drawdown hit 33.33% < 50.00%
- q4_2018_drawdown drawdown -26.09% < -25.00%

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
| current_2026 | top1_bottom1 | 3 | 2026-02-03 -> 2026-04-06 | -0.084079 | 66.67% | -34.68% | 0.715690 |
| euro_debt_2011 | top1_bottom1 | 3 | 2012-05-01 -> 2012-06-29 | 0.116398 | 100.00% | 0.00% | 1.360530 |
| gfc_2008 | top1_bottom1 | 3 | 2009-04-02 -> 2009-06-03 | 0.041879 | 66.67% | 0.00% | 1.121388 |
| post_gfc_recovery | top1_bottom1 | 3 | 2011-01-31 -> 2011-03-31 | 0.041539 | 66.67% | -4.06% | 1.124441 |
| q4_2018_drawdown | top1_bottom1 | 3 | 2018-10-03 -> 2018-12-03 | -0.124646 | 33.33% | -26.09% | 0.643322 |
| rate_bear_2022 | top1_bottom1 | 3 | 2022-10-04 -> 2022-12-02 | 0.015693 | 66.67% | -15.15% | 1.025358 |
