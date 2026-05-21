# DL Regime Gate Report

- Results dir: `data\experiment\historical_regime_tests_quantcup_price`
- Status: `fail`
- Stress regimes: current_2026, gfc_2008, q4_2018_drawdown, rate_bear_2022

## Basket Gates

### top1_bottom1

- Status: `fail`
- Mean spread all regimes: 0.025289
- Mean spread stress regimes: -0.009649
- Worst stress drawdown: -57.01%

Failures:
- current_2026 spread -0.001720 < 0.000000
- gfc_2008 spread -0.031291 < 0.000000
- gfc_2008 hit 27.78% < 50.00%
- gfc_2008 drawdown -57.01% < -25.00%
- q4_2018_drawdown spread -0.007673 < 0.000000
- rate_bear_2022 drawdown -29.20% < -25.00%

### top2_bottom2

- Status: `fail`
- Mean spread all regimes: -0.000790
- Mean spread stress regimes: -0.028492
- Worst stress drawdown: -46.72%

Failures:
- current_2026 spread -0.026371 < 0.000000
- gfc_2008 spread -0.027731 < 0.000000
- gfc_2008 hit 44.44% < 50.00%
- gfc_2008 drawdown -46.72% < -25.00%
- q4_2018_drawdown spread -0.048932 < 0.000000
- q4_2018_drawdown hit 25.00% < 50.00%
- q4_2018_drawdown drawdown -25.34% < -25.00%
- rate_bear_2022 spread -0.010935 < 0.000000
- rate_bear_2022 hit 41.67% < 50.00%
- rate_bear_2022 drawdown -39.08% < -25.00%

### top3_bottom3

- Status: `fail`
- Mean spread all regimes: 0.001875
- Mean spread stress regimes: -0.016260
- Worst stress drawdown: -33.18%

Failures:
- current_2026 spread -0.026495 < 0.000000
- current_2026 hit 0.00% < 50.00%
- gfc_2008 spread -0.018487 < 0.000000
- gfc_2008 hit 44.44% < 50.00%
- gfc_2008 drawdown -33.18% < -25.00%
- q4_2018_drawdown spread -0.013743 < 0.000000
- rate_bear_2022 spread -0.006313 < 0.000000
- rate_bear_2022 hit 41.67% < 50.00%
- rate_bear_2022 drawdown -29.58% < -25.00%

## Results

| Regime | Basket | Days | Window | Spread | Hit | Max DD | Equity |
|---|---|---:|---|---:|---:|---:|---:|
| ai_mega_cap_2023_2025 | top1_bottom1 | 24 | 2024-01-04 -> 2025-12-08 | 0.019619 | 45.83% | -53.36% | 1.178479 |
| ai_mega_cap_2023_2025 | top2_bottom2 | 24 | 2024-01-04 -> 2025-12-08 | 0.025016 | 54.17% | -34.60% | 1.510540 |
| ai_mega_cap_2023_2025 | top3_bottom3 | 24 | 2024-01-04 -> 2025-12-08 | 0.017983 | 58.33% | -24.84% | 1.345510 |
| china_oil_2015 | top1_bottom1 | 11 | 2015-06-01 -> 2016-03-31 | 0.022225 | 63.64% | -4.40% | 1.263496 |
| china_oil_2015 | top2_bottom2 | 11 | 2015-06-01 -> 2016-03-31 | 0.006823 | 54.55% | -14.91% | 1.041462 |
| china_oil_2015 | top3_bottom3 | 11 | 2015-06-01 -> 2016-03-31 | -0.000477 | 36.36% | -15.37% | 0.973524 |
| covid_2020 | top1_bottom1 | 11 | 2020-02-21 -> 2020-12-18 | 0.155855 | 72.73% | -14.83% | 4.092645 |
| covid_2020 | top2_bottom2 | 11 | 2020-02-21 -> 2020-12-18 | 0.061884 | 72.73% | -6.82% | 1.775958 |
| covid_2020 | top3_bottom3 | 11 | 2020-02-21 -> 2020-12-18 | 0.055512 | 72.73% | -4.29% | 1.732078 |
| current_2026 | top1_bottom1 | 4 | 2026-01-02 -> 2026-04-06 | -0.001720 | 50.00% | -11.79% | 0.983172 |
| current_2026 | top2_bottom2 | 4 | 2026-01-02 -> 2026-04-06 | -0.026371 | 50.00% | -11.47% | 0.893431 |
| current_2026 | top3_bottom3 | 4 | 2026-01-02 -> 2026-04-06 | -0.026495 | 0.00% | -4.12% | 0.897199 |
| euro_debt_2011 | top1_bottom1 | 15 | 2011-05-02 -> 2012-06-29 | 0.050003 | 66.67% | -30.11% | 1.854621 |
| euro_debt_2011 | top2_bottom2 | 15 | 2011-05-02 -> 2012-06-29 | 0.017211 | 66.67% | -16.35% | 1.249492 |
| euro_debt_2011 | top3_bottom3 | 15 | 2011-05-02 -> 2012-06-29 | 0.011612 | 66.67% | -19.57% | 1.157745 |
| gfc_2008 | top1_bottom1 | 18 | 2008-01-02 -> 2009-06-03 | -0.031291 | 27.78% | -57.01% | 0.503996 |
| gfc_2008 | top2_bottom2 | 18 | 2008-01-02 -> 2009-06-03 | -0.027731 | 44.44% | -46.72% | 0.559219 |
| gfc_2008 | top3_bottom3 | 18 | 2008-01-02 -> 2009-06-03 | -0.018487 | 44.44% | -33.18% | 0.692440 |
| post_gfc_recovery | top1_bottom1 | 22 | 2009-07-01 -> 2011-03-31 | 0.018499 | 63.64% | -56.50% | 1.195826 |
| post_gfc_recovery | top2_bottom2 | 22 | 2009-07-01 -> 2011-03-31 | -0.004077 | 63.64% | -38.28% | 0.796011 |
| post_gfc_recovery | top3_bottom3 | 22 | 2009-07-01 -> 2011-03-31 | -0.002718 | 63.64% | -26.40% | 0.888389 |
| q4_2018_drawdown | top1_bottom1 | 4 | 2018-09-04 -> 2018-12-03 | -0.007673 | 50.00% | -17.36% | 0.937930 |
| q4_2018_drawdown | top2_bottom2 | 4 | 2018-09-04 -> 2018-12-03 | -0.048932 | 25.00% | -25.34% | 0.789970 |
| q4_2018_drawdown | top3_bottom3 | 4 | 2018-09-04 -> 2018-12-03 | -0.013743 | 50.00% | -15.28% | 0.927134 |
| rate_bear_2022 | top1_bottom1 | 12 | 2022-01-03 -> 2022-12-02 | 0.002089 | 58.33% | -29.20% | 0.941947 |
| rate_bear_2022 | top2_bottom2 | 12 | 2022-01-03 -> 2022-12-02 | -0.010935 | 41.67% | -39.08% | 0.809288 |
| rate_bear_2022 | top3_bottom3 | 12 | 2022-01-03 -> 2022-12-02 | -0.006313 | 41.67% | -29.58% | 0.885881 |
