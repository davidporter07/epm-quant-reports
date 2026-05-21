# DL Ticker Holdout Robustness Report

- Log path: `data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_topmono_shadow_log.parquet`
- Trade days: 12

## Summary

| Top N | Base Excess | Base Hit | Max Ticker | Worst Holdout Excess | Median Holdout Excess | Positive Holdout Rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | -0.007788 | 33.33% | 33.33% | -0.041621 | -0.003893 | 33.33% |
| 2 | -0.006306 | 50.00% | 58.33% | -0.027027 | -0.010105 | 0.00% |
| 3 | -0.014109 | 25.00% | 75.00% | -0.018747 | -0.009674 | 0.00% |

## Top 1 Details

- Base ticker counts: `{'TSLA': 4, 'META': 3, 'NVDA': 2, 'AAPL': 1, 'GOOG': 1, 'MSFT': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| TSLA | 4 | 33.33% | 0.048969 | 0.195875 | 50.00% |
| GOOG | 1 | 8.33% | 0.002380 | 0.002380 | 100.00% |
| MSFT | 1 | 8.33% | -0.020687 | -0.020687 | 0.00% |
| AAPL | 1 | 8.33% | -0.057517 | -0.057517 | 0.00% |
| NVDA | 2 | 16.67% | -0.030442 | -0.060884 | 0.00% |
| META | 3 | 25.00% | -0.050874 | -0.152622 | 33.33% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| TSLA | -0.041621 | 25.00% | 41.67% | 100.00% |
| AAPL | -0.007824 | 33.33% | 33.33% | 100.00% |
| MSFT | -0.006356 | 33.33% | 33.33% | 100.00% |
| GOOG | -0.001430 | 25.00% | 41.67% | 100.00% |
| NVDA | 0.006139 | 50.00% | 33.33% | 100.00% |
| META | 0.007866 | 33.33% | 50.00% | 100.00% |

## Top 2 Details

- Base ticker counts: `{'TSLA': 7, 'META': 7, 'GOOG': 3, 'AAPL': 2, 'NVDA': 2, 'MSFT': 2, 'AMZN': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| NVDA | 2 | 16.67% | -0.001374 | -0.002748 | 50.00% |
| AMZN | 1 | 8.33% | -0.007504 | -0.007504 | 0.00% |
| TSLA | 7 | 58.33% | -0.001113 | -0.007794 | 57.14% |
| META | 7 | 58.33% | -0.001325 | -0.009278 | 57.14% |
| MSFT | 2 | 16.67% | -0.010342 | -0.020683 | 50.00% |
| GOOG | 3 | 25.00% | -0.008603 | -0.025808 | 66.67% |
| AAPL | 2 | 16.67% | -0.038761 | -0.077522 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| TSLA | -0.027027 | 33.33% | 58.33% | 100.00% |
| MSFT | -0.015222 | 25.00% | 66.67% | 100.00% |
| AMZN | -0.010379 | 33.33% | 66.67% | 100.00% |
| META | -0.010105 | 41.67% | 66.67% | 100.00% |
| GOOG | -0.003279 | 41.67% | 58.33% | 100.00% |
| NVDA | -0.001082 | 50.00% | 66.67% | 100.00% |
| AAPL | -0.000456 | 50.00% | 58.33% | 100.00% |

## Top 3 Details

- Base ticker counts: `{'TSLA': 9, 'META': 7, 'AMZN': 6, 'GOOG': 5, 'AAPL': 4, 'MSFT': 3, 'NVDA': 2}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| AMZN | 6 | 50.00% | -0.002197 | -0.013182 | 33.33% |
| NVDA | 2 | 16.67% | -0.007118 | -0.014236 | 50.00% |
| META | 7 | 58.33% | -0.009856 | -0.068995 | 28.57% |
| GOOG | 5 | 41.67% | -0.014143 | -0.070717 | 40.00% |
| MSFT | 3 | 25.00% | -0.026152 | -0.078455 | 0.00% |
| TSLA | 9 | 75.00% | -0.014132 | -0.127184 | 22.22% |
| AAPL | 4 | 33.33% | -0.033791 | -0.135165 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| TSLA | -0.018747 | 33.33% | 83.33% | 100.00% |
| MSFT | -0.015191 | 25.00% | 75.00% | 100.00% |
| NVDA | -0.010637 | 25.00% | 83.33% | 100.00% |
| AMZN | -0.009674 | 33.33% | 83.33% | 100.00% |
| GOOG | -0.004883 | 50.00% | 83.33% | 100.00% |
| META | -0.002960 | 33.33% | 83.33% | 100.00% |
| AAPL | -0.002254 | 58.33% | 75.00% | 100.00% |
