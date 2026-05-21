# DL Ticker Holdout Robustness Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_shadow_log.parquet`
- Trade days: 36

## Summary

| Top N | Base Excess | Base Hit | Max Ticker | Worst Holdout Excess | Median Holdout Excess | Positive Holdout Rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.095395 | 63.89% | 75.00% | 0.029258 | 0.090573 | 100.00% |
| 2 | 0.055320 | 66.67% | 88.89% | 0.024970 | 0.053725 | 100.00% |
| 3 | 0.043325 | 69.44% | 88.89% | 0.018050 | 0.040679 | 100.00% |

## Top 1 Details

- Base ticker counts: `{'PLTR': 27, 'AMD': 4, 'INTC': 3, 'NFLX': 1, 'MU': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| PLTR | 27 | 75.00% | 0.092882 | 2.507801 | 62.96% |
| AMD | 4 | 11.11% | 0.090208 | 0.360830 | 75.00% |
| INTC | 3 | 8.33% | 0.098859 | 0.296576 | 33.33% |
| MU | 1 | 2.78% | 0.249671 | 0.249671 | 100.00% |
| NFLX | 1 | 2.78% | 0.019358 | 0.019358 | 100.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| PLTR | 0.029258 | 47.22% | 25.00% | 100.00% |
| INTC | 0.089648 | 66.67% | 77.78% | 100.00% |
| MU | 0.090573 | 63.89% | 75.00% | 100.00% |
| AMD | 0.093196 | 63.89% | 83.33% | 100.00% |
| NFLX | 0.099557 | 63.89% | 77.78% | 100.00% |

## Top 2 Details

- Base ticker counts: `{'PLTR': 32, 'NVDA': 9, 'INTC': 9, 'TSLA': 7, 'AMD': 5, 'NFLX': 4, 'MU': 3, 'PANW': 1, 'ADBE': 1, 'CSCO': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| PLTR | 32 | 88.89% | 0.046499 | 1.487968 | 62.50% |
| INTC | 9 | 25.00% | 0.073977 | 0.665794 | 77.78% |
| TSLA | 7 | 19.44% | 0.086892 | 0.608241 | 71.43% |
| MU | 3 | 8.33% | 0.113111 | 0.339332 | 100.00% |
| NVDA | 9 | 25.00% | 0.025011 | 0.225096 | 55.56% |
| AMD | 5 | 13.89% | 0.039034 | 0.195170 | 60.00% |
| PANW | 1 | 2.78% | 0.163615 | 0.163615 | 100.00% |
| NFLX | 4 | 11.11% | 0.034974 | 0.139898 | 50.00% |
| CSCO | 1 | 2.78% | 0.079494 | 0.079494 | 100.00% |
| ADBE | 1 | 2.78% | 0.078400 | 0.078400 | 100.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| PLTR | 0.024970 | 52.78% | 41.67% | 100.00% |
| NVDA | 0.047174 | 63.89% | 88.89% | 100.00% |
| MU | 0.052742 | 61.11% | 88.89% | 100.00% |
| CSCO | 0.053132 | 63.89% | 88.89% | 100.00% |
| ADBE | 0.053700 | 66.67% | 88.89% | 100.00% |
| PANW | 0.053750 | 63.89% | 88.89% | 100.00% |
| INTC | 0.055960 | 63.89% | 88.89% | 100.00% |
| NFLX | 0.056147 | 69.44% | 88.89% | 100.00% |
| TSLA | 0.057016 | 66.67% | 88.89% | 100.00% |
| AMD | 0.066984 | 72.22% | 88.89% | 100.00% |

## Top 3 Details

- Base ticker counts: `{'PLTR': 32, 'INTC': 15, 'NVDA': 12, 'MU': 11, 'NFLX': 10, 'AMD': 9, 'TSLA': 7, 'ADBE': 4, 'CSCO': 3, 'LRCX': 2, 'META': 1, 'PANW': 1, 'QCOM': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| PLTR | 32 | 88.89% | 0.034453 | 1.102511 | 65.62% |
| INTC | 15 | 41.67% | 0.069911 | 1.048658 | 80.00% |
| MU | 11 | 30.56% | 0.076689 | 0.843583 | 81.82% |
| AMD | 9 | 25.00% | 0.056701 | 0.510311 | 77.78% |
| TSLA | 7 | 19.44% | 0.057511 | 0.402578 | 71.43% |
| LRCX | 2 | 5.56% | 0.153115 | 0.306230 | 100.00% |
| NFLX | 10 | 27.78% | 0.018888 | 0.188878 | 60.00% |
| NVDA | 12 | 33.33% | 0.008893 | 0.106714 | 50.00% |
| META | 1 | 2.78% | 0.087672 | 0.087672 | 100.00% |
| PANW | 1 | 2.78% | 0.068811 | 0.068811 | 100.00% |
| QCOM | 1 | 2.78% | 0.036915 | 0.036915 | 100.00% |
| ADBE | 4 | 11.11% | 0.003961 | 0.015843 | 50.00% |
| CSCO | 3 | 8.33% | -0.013190 | -0.039569 | 66.67% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| PLTR | 0.018050 | 50.00% | 50.00% | 100.00% |
| MU | 0.033690 | 66.67% | 91.67% | 100.00% |
| NVDA | 0.034155 | 58.33% | 88.89% | 100.00% |
| INTC | 0.036908 | 66.67% | 91.67% | 100.00% |
| NFLX | 0.039391 | 66.67% | 88.89% | 100.00% |
| QCOM | 0.040566 | 66.67% | 88.89% | 100.00% |
| LRCX | 0.040679 | 69.44% | 88.89% | 100.00% |
| TSLA | 0.041511 | 69.44% | 88.89% | 100.00% |
| ADBE | 0.041796 | 69.44% | 88.89% | 100.00% |
| META | 0.043461 | 69.44% | 88.89% | 100.00% |
| PANW | 0.045458 | 69.44% | 88.89% | 100.00% |
| AMD | 0.045945 | 69.44% | 91.67% | 100.00% |
| CSCO | 0.048795 | 69.44% | 88.89% | 100.00% |
