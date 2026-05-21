# DL Regime Gate Report

- Results dir: `data\experiment\final4_growth24_price_regime_probe`
- Status: `fail`
- Stress regimes: current_2026, gfc_2008, q4_2018_drawdown, rate_bear_2022

## Basket Gates

### top1_bottom1

- Status: `fail`
- Mean spread all regimes: 0.034123
- Mean spread stress regimes: -0.023376
- Worst stress drawdown: -18.76%

Failures:
- gfc_2008 spread -0.050059 < 0.000000
- gfc_2008 hit 33.33% < 50.00%
- q4_2018_drawdown spread -0.078806 < 0.000000
- q4_2018_drawdown hit 33.33% < 50.00%
- rate_bear_2022 spread -0.042861 < 0.000000
- rate_bear_2022 hit 33.33% < 50.00%

### top2_bottom2

- Status: `fail`
- Mean spread all regimes: 0.051109
- Mean spread stress regimes: 0.040654
- Worst stress drawdown: -10.44%

Failures:
- gfc_2008 spread -0.004075 < 0.000000
- gfc_2008 hit 33.33% < 50.00%
- q4_2018_drawdown spread -0.029491 < 0.000000
- rate_bear_2022 spread -0.033927 < 0.000000
- rate_bear_2022 hit 33.33% < 50.00%

### top3_bottom3

- Status: `fail`
- Mean spread all regimes: 0.035690
- Mean spread stress regimes: 0.021502
- Worst stress drawdown: -6.00%

Failures:
- gfc_2008 spread -0.060393 < 0.000000
- gfc_2008 hit 33.33% < 50.00%
- q4_2018_drawdown spread -0.015169 < 0.000000
- rate_bear_2022 spread -0.012230 < 0.000000
- rate_bear_2022 hit 33.33% < 50.00%

## Results

| Regime | Basket | Days | Window | Spread | Hit | Max DD | Equity |
|---|---|---:|---|---:|---:|---:|---:|
| ai_mega_cap_2023_2025 | top1_bottom1 | 3 | 2025-10-08 -> 2025-12-08 | 0.068468 | 66.67% | -4.05% | 1.196929 |
| ai_mega_cap_2023_2025 | top2_bottom2 | 3 | 2025-10-08 -> 2025-12-08 | 0.058156 | 100.00% | 0.00% | 1.181838 |
| ai_mega_cap_2023_2025 | top3_bottom3 | 3 | 2025-10-08 -> 2025-12-08 | 0.042222 | 66.67% | 0.00% | 1.129382 |
| china_oil_2015 | top1_bottom1 | 3 | 2016-01-29 -> 2016-03-31 | 0.007457 | 66.67% | -8.58% | 1.015702 |
| china_oil_2015 | top2_bottom2 | 3 | 2016-01-29 -> 2016-03-31 | 0.031736 | 100.00% | 0.00% | 1.097183 |
| china_oil_2015 | top3_bottom3 | 3 | 2016-01-29 -> 2016-03-31 | 0.024240 | 66.67% | -0.59% | 1.073148 |
| covid_2020 | top1_bottom1 | 3 | 2020-10-20 -> 2020-12-18 | 0.214062 | 100.00% | 0.00% | 1.777082 |
| covid_2020 | top2_bottom2 | 3 | 2020-10-20 -> 2020-12-18 | 0.101789 | 66.67% | 0.00% | 1.324952 |
| covid_2020 | top3_bottom3 | 3 | 2020-10-20 -> 2020-12-18 | 0.094794 | 66.67% | 0.00% | 1.297798 |
| current_2026 | top1_bottom1 | 3 | 2026-02-03 -> 2026-04-06 | 0.078223 | 66.67% | 0.00% | 1.238593 |
| current_2026 | top2_bottom2 | 3 | 2026-02-03 -> 2026-04-06 | 0.230109 | 66.67% | 0.00% | 1.726501 |
| current_2026 | top3_bottom3 | 3 | 2026-02-03 -> 2026-04-06 | 0.173800 | 66.67% | 0.00% | 1.544428 |
| euro_debt_2011 | top1_bottom1 | 3 | 2012-05-01 -> 2012-06-29 | 0.035898 | 66.67% | -10.98% | 1.094139 |
| euro_debt_2011 | top2_bottom2 | 3 | 2012-05-01 -> 2012-06-29 | 0.026755 | 100.00% | 0.00% | 1.080990 |
| euro_debt_2011 | top3_bottom3 | 3 | 2012-05-01 -> 2012-06-29 | 0.025685 | 100.00% | 0.00% | 1.079044 |
| gfc_2008 | top1_bottom1 | 3 | 2009-04-02 -> 2009-06-03 | -0.050059 | 33.33% | -18.76% | 0.830752 |
| gfc_2008 | top2_bottom2 | 3 | 2009-04-02 -> 2009-06-03 | -0.004075 | 33.33% | -0.50% | 0.979488 |
| gfc_2008 | top3_bottom3 | 3 | 2009-04-02 -> 2009-06-03 | -0.060393 | 33.33% | -6.00% | 0.819389 |
| post_gfc_recovery | top1_bottom1 | 3 | 2011-01-31 -> 2011-03-31 | 0.074726 | 66.67% | 0.00% | 1.223540 |
| post_gfc_recovery | top2_bottom2 | 3 | 2011-01-31 -> 2011-03-31 | 0.078927 | 100.00% | 0.00% | 1.249544 |
| post_gfc_recovery | top3_bottom3 | 3 | 2011-01-31 -> 2011-03-31 | 0.048267 | 100.00% | 0.00% | 1.149101 |
| q4_2018_drawdown | top1_bottom1 | 3 | 2018-10-03 -> 2018-12-03 | -0.078806 | 33.33% | -6.20% | 0.744191 |
| q4_2018_drawdown | top2_bottom2 | 3 | 2018-10-03 -> 2018-12-03 | -0.029491 | 66.67% | 0.00% | 0.903924 |
| q4_2018_drawdown | top3_bottom3 | 3 | 2018-10-03 -> 2018-12-03 | -0.015169 | 66.67% | 0.00% | 0.949457 |
| rate_bear_2022 | top1_bottom1 | 3 | 2022-10-04 -> 2022-12-02 | -0.042861 | 33.33% | -1.96% | 0.871160 |
| rate_bear_2022 | top2_bottom2 | 3 | 2022-10-04 -> 2022-12-02 | -0.033927 | 33.33% | -10.44% | 0.897880 |
| rate_bear_2022 | top3_bottom3 | 3 | 2022-10-04 -> 2022-12-02 | -0.012230 | 33.33% | -5.80% | 0.962468 |
