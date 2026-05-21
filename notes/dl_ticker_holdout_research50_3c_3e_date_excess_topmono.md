# DL Ticker Holdout Robustness Report

- Log path: `data\experiment\historical_blind_rank_head\research50_3c_3e_date_excess_topmono_shadow_log.parquet`
- Trade days: 3

## Summary

| Top N | Base Excess | Base Hit | Max Ticker | Worst Holdout Excess | Median Holdout Excess | Positive Holdout Rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | -0.028323 | 0.00% | 33.33% | -0.053150 | -0.032356 | 0.00% |
| 2 | -0.032396 | 0.00% | 100.00% | -0.019762 | -0.018733 | 25.00% |
| 3 | -0.003218 | 33.33% | 100.00% | -0.016333 | -0.007009 | 16.67% |

## Top 1 Details

- Base ticker counts: `{'GOOG': 1, 'TSLA': 1, 'MSFT': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| MSFT | 1 | 33.33% | -0.023523 | -0.023523 | 0.00% |
| TSLA | 1 | 33.33% | -0.027466 | -0.027466 | 0.00% |
| GOOG | 1 | 33.33% | -0.033979 | -0.033979 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| MSFT | -0.053150 | 0.00% | 66.67% | 100.00% |
| TSLA | -0.032356 | 0.00% | 33.33% | 100.00% |
| GOOG | -0.019222 | 0.00% | 66.67% | 100.00% |

## Top 2 Details

- Base ticker counts: `{'TSLA': 3, 'GOOG': 1, 'META': 1, 'MSFT': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| GOOG | 1 | 33.33% | -0.020299 | -0.020299 | 0.00% |
| META | 1 | 33.33% | -0.023785 | -0.023785 | 0.00% |
| MSFT | 1 | 33.33% | -0.053105 | -0.053105 | 0.00% |
| TSLA | 3 | 100.00% | -0.032396 | -0.097189 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| META | -0.019762 | 0.00% | 100.00% | 100.00% |
| GOOG | -0.019091 | 33.33% | 100.00% | 100.00% |
| MSFT | -0.018376 | 33.33% | 100.00% | 100.00% |
| TSLA | 0.008147 | 66.67% | 66.67% | 100.00% |

## Top 3 Details

- Base ticker counts: `{'TSLA': 3, 'GOOG': 2, 'NVDA': 1, 'META': 1, 'MSFT': 1, 'AMZN': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| NVDA | 1 | 33.33% | 0.001790 | 0.001790 | 100.00% |
| GOOG | 2 | 66.67% | -0.002332 | -0.004664 | 50.00% |
| AMZN | 1 | 33.33% | -0.004991 | -0.004991 | 0.00% |
| MSFT | 1 | 33.33% | -0.004991 | -0.004991 | 0.00% |
| META | 1 | 33.33% | -0.006454 | -0.006454 | 0.00% |
| TSLA | 3 | 100.00% | -0.003218 | -0.009655 | 33.33% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| NVDA | -0.016333 | 0.00% | 100.00% | 100.00% |
| GOOG | -0.012919 | 0.00% | 100.00% | 100.00% |
| AMZN | -0.008710 | 33.33% | 100.00% | 100.00% |
| TSLA | -0.005308 | 33.33% | 66.67% | 100.00% |
| MSFT | -0.003965 | 33.33% | 100.00% | 100.00% |
| META | 0.004207 | 33.33% | 100.00% | 100.00% |
