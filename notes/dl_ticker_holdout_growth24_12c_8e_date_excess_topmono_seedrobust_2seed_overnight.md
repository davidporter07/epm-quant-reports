# DL Ticker Holdout Robustness Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_12c_8e_date_excess_topmono_seedrobust_2seed_overnight_shadow_log.parquet`
- Trade days: 12

## Summary

| Top N | Base Excess | Base Hit | Max Ticker | Worst Holdout Excess | Median Holdout Excess | Positive Holdout Rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.045537 | 58.33% | 58.33% | 0.018203 | 0.048133 | 100.00% |
| 2 | 0.038910 | 58.33% | 66.67% | 0.020742 | 0.037399 | 100.00% |
| 3 | 0.034949 | 58.33% | 75.00% | 0.021435 | 0.038036 | 100.00% |

## Top 1 Details

- Base ticker counts: `{'PLTR': 7, 'MU': 3, 'ORCL': 1, 'INTC': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| MU | 3 | 25.00% | 0.092532 | 0.277595 | 66.67% |
| INTC | 1 | 8.33% | 0.247026 | 0.247026 | 100.00% |
| PLTR | 7 | 58.33% | 0.026033 | 0.182231 | 57.14% |
| ORCL | 1 | 8.33% | -0.160411 | -0.160411 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| PLTR | 0.018203 | 50.00% | 33.33% | 100.00% |
| INTC | 0.034719 | 66.67% | 58.33% | 100.00% |
| MU | 0.061547 | 58.33% | 58.33% | 100.00% |
| ORCL | 0.063165 | 66.67% | 66.67% | 100.00% |

## Top 2 Details

- Base ticker counts: `{'PLTR': 8, 'MU': 4, 'TSLA': 4, 'INTC': 4, 'ORCL': 3, 'SNPS': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| INTC | 4 | 33.33% | 0.125280 | 0.501118 | 100.00% |
| MU | 4 | 33.33% | 0.117302 | 0.469207 | 100.00% |
| SNPS | 1 | 8.33% | 0.161786 | 0.161786 | 100.00% |
| TSLA | 4 | 33.33% | 0.023705 | 0.094821 | 50.00% |
| PLTR | 8 | 66.67% | -0.004274 | -0.034194 | 37.50% |
| ORCL | 3 | 25.00% | -0.086297 | -0.258890 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| MU | 0.020742 | 41.67% | 75.00% | 100.00% |
| INTC | 0.024584 | 50.00% | 75.00% | 100.00% |
| PLTR | 0.033168 | 58.33% | 66.67% | 100.00% |
| TSLA | 0.041630 | 66.67% | 66.67% | 100.00% |
| SNPS | 0.050195 | 58.33% | 66.67% | 100.00% |
| ORCL | 0.058859 | 66.67% | 66.67% | 100.00% |

## Top 3 Details

- Base ticker counts: `{'PLTR': 9, 'INTC': 8, 'MU': 6, 'TSLA': 5, 'ORCL': 3, 'LRCX': 2, 'NVDA': 1, 'AVGO': 1, 'SNPS': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| MU | 6 | 50.00% | 0.094285 | 0.565711 | 100.00% |
| SNPS | 1 | 8.33% | 0.233457 | 0.233457 | 100.00% |
| INTC | 8 | 66.67% | 0.027171 | 0.217369 | 50.00% |
| LRCX | 2 | 16.67% | 0.074008 | 0.148016 | 100.00% |
| NVDA | 1 | 8.33% | 0.089499 | 0.089499 | 100.00% |
| AVGO | 1 | 8.33% | 0.086718 | 0.086718 | 100.00% |
| TSLA | 5 | 41.67% | 0.012662 | 0.063310 | 40.00% |
| PLTR | 9 | 75.00% | 0.004212 | 0.037912 | 44.44% |
| ORCL | 3 | 25.00% | -0.061280 | -0.183839 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| MU | 0.021435 | 41.67% | 75.00% | 100.00% |
| INTC | 0.029212 | 58.33% | 83.33% | 100.00% |
| SNPS | 0.033175 | 58.33% | 75.00% | 100.00% |
| LRCX | 0.037688 | 58.33% | 75.00% | 100.00% |
| AVGO | 0.038036 | 58.33% | 75.00% | 100.00% |
| NVDA | 0.039395 | 58.33% | 75.00% | 100.00% |
| TSLA | 0.055036 | 75.00% | 75.00% | 100.00% |
| PLTR | 0.061887 | 75.00% | 83.33% | 100.00% |
| ORCL | 0.067066 | 83.33% | 75.00% | 100.00% |
