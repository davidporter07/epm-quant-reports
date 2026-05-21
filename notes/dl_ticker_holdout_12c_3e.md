# DL Ticker Holdout Robustness Report

- Log path: `data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_3e_shadow_log.parquet`
- Trade days: 12

## Summary

| Top N | Base Excess | Base Hit | Max Ticker | Worst Holdout Excess | Median Holdout Excess | Positive Holdout Rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | -0.005461 | 41.67% | 66.67% | -0.024050 | -0.015778 | 25.00% |
| 2 | -0.020919 | 50.00% | 83.33% | -0.030919 | -0.017884 | 0.00% |
| 3 | -0.007933 | 33.33% | 91.67% | -0.013859 | -0.005499 | 0.00% |

## Top 1 Details

- Base ticker counts: `{'TSLA': 8, 'AMZN': 2, 'NVDA': 1, 'META': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| AMZN | 2 | 16.67% | 0.079562 | 0.159124 | 100.00% |
| NVDA | 1 | 8.33% | -0.011738 | -0.011738 | 0.00% |
| META | 1 | 8.33% | -0.075890 | -0.075890 | 0.00% |
| TSLA | 8 | 66.67% | -0.017128 | -0.137026 | 37.50% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| TSLA | -0.024050 | 50.00% | 33.33% | 100.00% |
| AMZN | -0.022727 | 16.67% | 75.00% | 100.00% |
| META | -0.008828 | 41.67% | 66.67% | 100.00% |
| NVDA | 0.003253 | 50.00% | 75.00% | 100.00% |

## Top 2 Details

- Base ticker counts: `{'TSLA': 10, 'META': 4, 'AMZN': 3, 'AAPL': 2, 'NVDA': 2, 'GOOG': 2, 'MSFT': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| MSFT | 1 | 8.33% | 0.042568 | 0.042568 | 100.00% |
| AMZN | 3 | 25.00% | 0.013684 | 0.041051 | 66.67% |
| GOOG | 2 | 16.67% | 0.009318 | 0.018635 | 100.00% |
| NVDA | 2 | 16.67% | -0.034018 | -0.068036 | 50.00% |
| AAPL | 2 | 16.67% | -0.069426 | -0.138851 | 0.00% |
| META | 4 | 33.33% | -0.046748 | -0.186990 | 25.00% |
| TSLA | 10 | 83.33% | -0.021044 | -0.210443 | 50.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| AMZN | -0.030919 | 33.33% | 83.33% | 100.00% |
| MSFT | -0.022196 | 41.67% | 83.33% | 100.00% |
| GOOG | -0.021148 | 33.33% | 83.33% | 100.00% |
| TSLA | -0.017884 | 41.67% | 83.33% | 100.00% |
| AAPL | -0.008417 | 58.33% | 83.33% | 100.00% |
| NVDA | -0.003706 | 58.33% | 91.67% | 100.00% |
| META | -0.003208 | 58.33% | 91.67% | 100.00% |

## Top 3 Details

- Base ticker counts: `{'TSLA': 11, 'META': 11, 'AMZN': 6, 'AAPL': 2, 'MSFT': 2, 'NVDA': 2, 'GOOG': 2}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| NVDA | 2 | 16.67% | 0.012200 | 0.024400 | 100.00% |
| MSFT | 2 | 16.67% | -0.001716 | -0.003432 | 50.00% |
| AMZN | 6 | 50.00% | -0.002536 | -0.015213 | 33.33% |
| GOOG | 2 | 16.67% | -0.009932 | -0.019865 | 0.00% |
| AAPL | 2 | 16.67% | -0.026968 | -0.053935 | 0.00% |
| META | 11 | 91.67% | -0.007200 | -0.079195 | 36.36% |
| TSLA | 11 | 91.67% | -0.012577 | -0.138346 | 27.27% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| MSFT | -0.013859 | 25.00% | 91.67% | 100.00% |
| AMZN | -0.009357 | 33.33% | 100.00% | 100.00% |
| TSLA | -0.007526 | 25.00% | 100.00% | 100.00% |
| NVDA | -0.005499 | 41.67% | 91.67% | 100.00% |
| META | -0.005225 | 25.00% | 91.67% | 100.00% |
| GOOG | -0.002590 | 41.67% | 100.00% | 100.00% |
| AAPL | -0.001885 | 50.00% | 91.67% | 100.00% |
