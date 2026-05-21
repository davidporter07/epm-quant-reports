# DL Ticker Holdout Robustness Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_12c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_shadow_log.parquet`
- Trade days: 12

## Summary

| Top N | Base Excess | Base Hit | Max Ticker | Worst Holdout Excess | Median Holdout Excess | Positive Holdout Rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.090820 | 66.67% | 33.33% | 0.052015 | 0.076942 | 100.00% |
| 2 | 0.048883 | 66.67% | 66.67% | 0.042214 | 0.054435 | 100.00% |
| 3 | 0.060178 | 66.67% | 66.67% | 0.031406 | 0.062602 | 100.00% |

## Top 1 Details

- Base ticker counts: `{'PLTR': 4, 'AMD': 4, 'INTC': 3, 'MU': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| AMD | 4 | 33.33% | 0.090208 | 0.360830 | 75.00% |
| INTC | 3 | 25.00% | 0.098859 | 0.296576 | 33.33% |
| MU | 1 | 8.33% | 0.249671 | 0.249671 | 100.00% |
| PLTR | 4 | 33.33% | 0.045690 | 0.182758 | 75.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| PLTR | 0.052015 | 50.00% | 41.67% | 100.00% |
| INTC | 0.076469 | 75.00% | 41.67% | 100.00% |
| MU | 0.077416 | 66.67% | 33.33% | 100.00% |
| AMD | 0.085755 | 66.67% | 58.33% | 100.00% |

## Top 2 Details

- Base ticker counts: `{'PLTR': 8, 'INTC': 7, 'AMD': 5, 'MU': 3, 'TSLA': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| INTC | 7 | 58.33% | 0.083952 | 0.587664 | 85.71% |
| MU | 3 | 25.00% | 0.113111 | 0.339332 | 100.00% |
| AMD | 5 | 41.67% | 0.039034 | 0.195170 | 60.00% |
| PLTR | 8 | 66.67% | 0.010383 | 0.083065 | 50.00% |
| TSLA | 1 | 8.33% | -0.032029 | -0.032029 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| MU | 0.042214 | 50.00% | 66.67% | 100.00% |
| INTC | 0.043777 | 58.33% | 66.67% | 100.00% |
| TSLA | 0.054435 | 66.67% | 66.67% | 100.00% |
| PLTR | 0.064895 | 66.67% | 66.67% | 100.00% |
| AMD | 0.085410 | 83.33% | 66.67% | 100.00% |

## Top 3 Details

- Base ticker counts: `{'PLTR': 8, 'INTC': 8, 'MU': 8, 'AMD': 6, 'ADBE': 3, 'LRCX': 2, 'TSLA': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| MU | 8 | 66.67% | 0.073790 | 0.590319 | 87.50% |
| AMD | 6 | 50.00% | 0.090712 | 0.544270 | 83.33% |
| INTC | 8 | 66.67% | 0.061317 | 0.490539 | 62.50% |
| LRCX | 2 | 16.67% | 0.153115 | 0.306230 | 100.00% |
| PLTR | 8 | 66.67% | 0.033116 | 0.264930 | 50.00% |
| TSLA | 1 | 8.33% | -0.008826 | -0.008826 | 0.00% |
| ADBE | 3 | 25.00% | -0.007024 | -0.021072 | 33.33% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| MU | 0.031406 | 50.00% | 75.00% | 100.00% |
| INTC | 0.050518 | 83.33% | 75.00% | 100.00% |
| LRCX | 0.052909 | 66.67% | 75.00% | 100.00% |
| ADBE | 0.062602 | 75.00% | 66.67% | 100.00% |
| AMD | 0.065892 | 75.00% | 75.00% | 100.00% |
| PLTR | 0.065896 | 75.00% | 75.00% | 100.00% |
| TSLA | 0.066616 | 75.00% | 66.67% | 100.00% |
