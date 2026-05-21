# DL Regime Gate Report

- Results dir: `data\experiment\historical_regime_tests_quantcup_price_excess`
- Status: `fail`
- Stress regimes: current_2026, gfc_2008, q4_2018_drawdown, rate_bear_2022

## Basket Gates

### top1_bottom1

- Status: `fail`
- Mean spread all regimes: -0.006847
- Mean spread stress regimes: -0.052737
- Worst stress drawdown: -81.06%

Failures:
- current_2026 spread -0.096887 < 0.000000
- current_2026 hit 25.00% < 50.00%
- current_2026 drawdown -34.83% < -25.00%
- gfc_2008 spread -0.038901 < 0.000000
- gfc_2008 hit 38.89% < 50.00%
- gfc_2008 drawdown -81.06% < -25.00%
- q4_2018_drawdown spread -0.044821 < 0.000000
- q4_2018_drawdown drawdown -31.49% < -25.00%
- rate_bear_2022 spread -0.030340 < 0.000000
- rate_bear_2022 hit 41.67% < 50.00%
- rate_bear_2022 drawdown -55.84% < -25.00%

### top2_bottom2

- Status: `fail`
- Mean spread all regimes: -0.000424
- Mean spread stress regimes: -0.017213
- Worst stress drawdown: -38.73%

Failures:
- current_2026 spread -0.053580 < 0.000000
- current_2026 hit 25.00% < 50.00%
- gfc_2008 hit 44.44% < 50.00%
- gfc_2008 drawdown -38.73% < -25.00%
- q4_2018_drawdown spread -0.006274 < 0.000000
- rate_bear_2022 spread -0.012778 < 0.000000
- rate_bear_2022 drawdown -34.45% < -25.00%

### top3_bottom3

- Status: `fail`
- Mean spread all regimes: 0.000094
- Mean spread stress regimes: -0.011065
- Worst stress drawdown: -33.19%

Failures:
- current_2026 spread -0.035714 < 0.000000
- current_2026 hit 25.00% < 50.00%
- gfc_2008 hit 44.44% < 50.00%
- gfc_2008 drawdown -27.28% < -25.00%
- rate_bear_2022 spread -0.031448 < 0.000000
- rate_bear_2022 hit 25.00% < 50.00%
- rate_bear_2022 drawdown -33.19% < -25.00%

## Results

| Regime | Basket | Days | Window | Spread | Hit | Max DD | Equity |
|---|---|---:|---|---:|---:|---:|---:|
| ai_mega_cap_2023_2025 | top1_bottom1 | 24 | 2024-01-04 -> 2025-12-08 | 0.006954 | 41.67% | -66.86% | 0.785239 |
| ai_mega_cap_2023_2025 | top2_bottom2 | 24 | 2024-01-04 -> 2025-12-08 | 0.017363 | 54.17% | -40.55% | 1.238296 |
| ai_mega_cap_2023_2025 | top3_bottom3 | 24 | 2024-01-04 -> 2025-12-08 | 0.001255 | 58.33% | -37.12% | 0.915445 |
| china_oil_2015 | top1_bottom1 | 11 | 2015-06-01 -> 2016-03-31 | 0.013910 | 54.55% | -31.72% | 1.106394 |
| china_oil_2015 | top2_bottom2 | 11 | 2015-06-01 -> 2016-03-31 | -0.031710 | 36.36% | -44.60% | 0.679457 |
| china_oil_2015 | top3_bottom3 | 11 | 2015-06-01 -> 2016-03-31 | -0.014857 | 45.45% | -37.69% | 0.819386 |
| covid_2020 | top1_bottom1 | 11 | 2020-02-21 -> 2020-12-18 | 0.079997 | 54.55% | -26.03% | 1.873290 |
| covid_2020 | top2_bottom2 | 11 | 2020-02-21 -> 2020-12-18 | 0.037176 | 63.64% | -28.49% | 1.326043 |
| covid_2020 | top3_bottom3 | 11 | 2020-02-21 -> 2020-12-18 | 0.027761 | 63.64% | -21.68% | 1.253840 |
| current_2026 | top1_bottom1 | 4 | 2026-01-02 -> 2026-04-06 | -0.096887 | 25.00% | -34.83% | 0.657087 |
| current_2026 | top2_bottom2 | 4 | 2026-01-02 -> 2026-04-06 | -0.053580 | 25.00% | -20.90% | 0.798232 |
| current_2026 | top3_bottom3 | 4 | 2026-01-02 -> 2026-04-06 | -0.035714 | 25.00% | -20.37% | 0.857117 |
| euro_debt_2011 | top1_bottom1 | 15 | 2011-05-02 -> 2012-06-29 | 0.040914 | 66.67% | -24.12% | 1.660984 |
| euro_debt_2011 | top2_bottom2 | 15 | 2011-05-02 -> 2012-06-29 | 0.027923 | 66.67% | -16.98% | 1.435726 |
| euro_debt_2011 | top3_bottom3 | 15 | 2011-05-02 -> 2012-06-29 | 0.021423 | 60.00% | -7.41% | 1.342485 |
| gfc_2008 | top1_bottom1 | 18 | 2008-01-02 -> 2009-06-03 | -0.038901 | 38.89% | -81.06% | 0.360579 |
| gfc_2008 | top2_bottom2 | 18 | 2008-01-02 -> 2009-06-03 | 0.003778 | 44.44% | -38.73% | 1.003695 |
| gfc_2008 | top3_bottom3 | 18 | 2008-01-02 -> 2009-06-03 | 0.002518 | 44.44% | -27.28% | 1.016946 |
| post_gfc_recovery | top1_bottom1 | 22 | 2009-07-01 -> 2011-03-31 | 0.007552 | 40.91% | -35.65% | 1.059865 |
| post_gfc_recovery | top2_bottom2 | 22 | 2009-07-01 -> 2011-03-31 | 0.014290 | 54.55% | -15.33% | 1.315979 |
| post_gfc_recovery | top3_bottom3 | 22 | 2009-07-01 -> 2011-03-31 | 0.009527 | 54.55% | -10.37% | 1.211228 |
| q4_2018_drawdown | top1_bottom1 | 4 | 2018-09-04 -> 2018-12-03 | -0.044821 | 50.00% | -31.49% | 0.772038 |
| q4_2018_drawdown | top2_bottom2 | 4 | 2018-09-04 -> 2018-12-03 | -0.006274 | 50.00% | -16.91% | 0.951221 |
| q4_2018_drawdown | top3_bottom3 | 4 | 2018-09-04 -> 2018-12-03 | 0.020382 | 75.00% | -15.57% | 1.054893 |
| rate_bear_2022 | top1_bottom1 | 12 | 2022-01-03 -> 2022-12-02 | -0.030340 | 41.67% | -55.84% | 0.590884 |
| rate_bear_2022 | top2_bottom2 | 12 | 2022-01-03 -> 2022-12-02 | -0.012778 | 50.00% | -34.45% | 0.822011 |
| rate_bear_2022 | top3_bottom3 | 12 | 2022-01-03 -> 2022-12-02 | -0.031448 | 25.00% | -33.19% | 0.669753 |
