# DL Ticker Holdout Robustness Report

- Log path: `data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_date_excess_topmono_shadow_log.parquet`
- Trade days: 12

## Summary

| Top N | Base Excess | Base Hit | Max Ticker | Worst Holdout Excess | Median Holdout Excess | Positive Holdout Rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.006836 | 41.67% | 83.33% | 0.007310 | 0.010622 | 100.00% |
| 2 | 0.009071 | 66.67% | 91.67% | -0.009382 | 0.004587 | 60.00% |
| 3 | -0.004241 | 33.33% | 100.00% | -0.011557 | -0.006292 | 16.67% |

## Top 1 Details

- Base ticker counts: `{'TSLA': 10, 'NVDA': 2}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| NVDA | 2 | 16.67% | 0.025990 | 0.051980 | 50.00% |
| TSLA | 10 | 83.33% | 0.003005 | 0.030052 | 40.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| TSLA | 0.007310 | 58.33% | 41.67% | 100.00% |
| NVDA | 0.013933 | 50.00% | 91.67% | 100.00% |

## Top 2 Details

- Base ticker counts: `{'TSLA': 11, 'NVDA': 5, 'META': 4, 'GOOG': 3, 'AAPL': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| NVDA | 5 | 41.67% | 0.028222 | 0.141108 | 80.00% |
| META | 4 | 33.33% | 0.028827 | 0.115308 | 75.00% |
| TSLA | 11 | 91.67% | 0.004985 | 0.054839 | 63.64% |
| GOOG | 3 | 25.00% | 0.004076 | 0.012228 | 66.67% |
| AAPL | 1 | 8.33% | -0.105773 | -0.105773 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| NVDA | -0.009382 | 41.67% | 100.00% | 100.00% |
| TSLA | -0.004090 | 41.67% | 66.67% | 100.00% |
| META | 0.004587 | 58.33% | 100.00% | 100.00% |
| GOOG | 0.006239 | 50.00% | 91.67% | 100.00% |
| AAPL | 0.012586 | 66.67% | 91.67% | 100.00% |

## Top 3 Details

- Base ticker counts: `{'TSLA': 12, 'NVDA': 8, 'META': 8, 'GOOG': 3, 'AMZN': 3, 'AAPL': 2}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| NVDA | 8 | 66.67% | 0.003395 | 0.027160 | 50.00% |
| GOOG | 3 | 25.00% | -0.006828 | -0.020484 | 0.00% |
| META | 8 | 66.67% | -0.003167 | -0.025332 | 37.50% |
| AAPL | 2 | 16.67% | -0.015441 | -0.030881 | 50.00% |
| TSLA | 12 | 100.00% | -0.004241 | -0.050898 | 33.33% |
| AMZN | 3 | 25.00% | -0.017420 | -0.052259 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| NVDA | -0.011557 | 33.33% | 100.00% | 100.00% |
| TSLA | -0.008332 | 33.33% | 83.33% | 100.00% |
| AMZN | -0.007115 | 50.00% | 100.00% | 100.00% |
| META | -0.005470 | 41.67% | 100.00% | 100.00% |
| AAPL | -0.000902 | 41.67% | 100.00% | 100.00% |
| GOOG | 0.000474 | 50.00% | 100.00% | 100.00% |
