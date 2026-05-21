# DL Ticker Holdout Robustness Report

- Log path: `data\experiment\historical_blind_rank_head\rank_head_blind_loop_3c_3e_date_excess_topmono_shadow_log.parquet`
- Trade days: 3

## Summary

| Top N | Base Excess | Base Hit | Max Ticker | Worst Holdout Excess | Median Holdout Excess | Positive Holdout Rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.017318 | 66.67% | 66.67% | -0.012294 | 0.012135 | 50.00% |
| 2 | 0.014130 | 66.67% | 66.67% | -0.023617 | 0.005847 | 60.00% |
| 3 | -0.008370 | 33.33% | 100.00% | -0.005315 | -0.000737 | 40.00% |

## Top 1 Details

- Base ticker counts: `{'TSLA': 2, 'NVDA': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| NVDA | 1 | 33.33% | 0.063718 | 0.063718 | 100.00% |
| TSLA | 2 | 66.67% | -0.005882 | -0.011764 | 50.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| TSLA | -0.012294 | 66.67% | 33.33% | 100.00% |
| NVDA | 0.036563 | 66.67% | 66.67% | 100.00% |

## Top 2 Details

- Base ticker counts: `{'TSLA': 2, 'GOOG': 1, 'META': 1, 'NVDA': 1, 'AMZN': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| AMZN | 1 | 33.33% | 0.084771 | 0.084771 | 100.00% |
| NVDA | 1 | 33.33% | 0.084771 | 0.084771 | 100.00% |
| GOOG | 1 | 33.33% | 0.005780 | 0.005780 | 100.00% |
| TSLA | 2 | 66.67% | -0.021191 | -0.042381 | 50.00% |
| META | 1 | 33.33% | -0.048161 | -0.048161 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| AMZN | -0.023617 | 0.00% | 100.00% | 100.00% |
| NVDA | -0.016921 | 33.33% | 100.00% | 100.00% |
| TSLA | 0.005847 | 33.33% | 100.00% | 100.00% |
| GOOG | 0.006297 | 33.33% | 66.67% | 100.00% |
| META | 0.036381 | 100.00% | 66.67% | 100.00% |

## Top 3 Details

- Base ticker counts: `{'TSLA': 3, 'AMZN': 3, 'GOOG': 1, 'META': 1, 'NVDA': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| NVDA | 1 | 33.33% | 0.005232 | 0.005232 | 100.00% |
| META | 1 | 33.33% | -0.014341 | -0.014341 | 0.00% |
| GOOG | 1 | 33.33% | -0.016001 | -0.016001 | 0.00% |
| AMZN | 3 | 100.00% | -0.008370 | -0.025109 | 33.33% |
| TSLA | 3 | 100.00% | -0.008370 | -0.025109 | 33.33% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| NVDA | -0.005315 | 33.33% | 100.00% | 100.00% |
| GOOG | -0.001083 | 33.33% | 100.00% | 100.00% |
| AMZN | -0.000737 | 66.67% | 100.00% | 100.00% |
| META | 0.003989 | 66.67% | 100.00% | 100.00% |
| TSLA | 0.013994 | 33.33% | 100.00% | 100.00% |
