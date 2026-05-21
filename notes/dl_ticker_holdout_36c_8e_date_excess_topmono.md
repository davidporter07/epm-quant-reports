# DL Ticker Holdout Robustness Report

- Log path: `data\experiment\historical_blind_rank_head\rank_head_blind_loop_36c_8e_date_excess_topmono_shadow_log.parquet`
- Trade days: 36

## Summary

| Top N | Base Excess | Base Hit | Max Ticker | Worst Holdout Excess | Median Holdout Excess | Positive Holdout Rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.003270 | 50.00% | 72.22% | -0.001794 | 0.003223 | 80.00% |
| 2 | 0.005814 | 55.56% | 83.33% | -0.000645 | 0.004118 | 85.71% |
| 3 | 0.000580 | 50.00% | 88.89% | -0.004565 | -0.000549 | 42.86% |

## Top 1 Details

- Base ticker counts: `{'TSLA': 26, 'NVDA': 5, 'META': 3, 'GOOG': 1, 'AMZN': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| NVDA | 5 | 13.89% | 0.030445 | 0.152226 | 60.00% |
| META | 3 | 8.33% | 0.032173 | 0.096520 | 100.00% |
| GOOG | 1 | 2.78% | 0.035342 | 0.035342 | 100.00% |
| AMZN | 1 | 2.78% | -0.058030 | -0.058030 | 0.00% |
| TSLA | 26 | 72.22% | -0.004167 | -0.108351 | 42.31% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| META | -0.001794 | 44.44% | 77.78% | 100.00% |
| AMZN | 0.000112 | 44.44% | 72.22% | 100.00% |
| GOOG | 0.003223 | 47.22% | 72.22% | 100.00% |
| NVDA | 0.008214 | 50.00% | 77.78% | 100.00% |
| TSLA | 0.017851 | 55.56% | 44.44% | 100.00% |

## Top 2 Details

- Base ticker counts: `{'TSLA': 30, 'NVDA': 17, 'META': 16, 'GOOG': 6, 'MSFT': 1, 'AMZN': 1, 'AAPL': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| META | 16 | 44.44% | 0.015425 | 0.246797 | 56.25% |
| TSLA | 30 | 83.33% | 0.005844 | 0.175319 | 53.33% |
| NVDA | 17 | 47.22% | 0.005954 | 0.101213 | 58.82% |
| GOOG | 6 | 16.67% | 0.008690 | 0.052138 | 66.67% |
| MSFT | 1 | 2.78% | 0.047643 | 0.047643 | 100.00% |
| AMZN | 1 | 2.78% | -0.098743 | -0.098743 | 0.00% |
| AAPL | 1 | 2.78% | -0.105773 | -0.105773 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| NVDA | -0.000645 | 50.00% | 86.11% | 100.00% |
| META | 0.002872 | 50.00% | 88.89% | 100.00% |
| TSLA | 0.004042 | 44.44% | 80.56% | 100.00% |
| MSFT | 0.004118 | 52.78% | 83.33% | 100.00% |
| GOOG | 0.004305 | 52.78% | 83.33% | 100.00% |
| AAPL | 0.004742 | 55.56% | 83.33% | 100.00% |
| AMZN | 0.005562 | 58.33% | 86.11% | 100.00% |

## Top 3 Details

- Base ticker counts: `{'TSLA': 32, 'META': 31, 'NVDA': 23, 'GOOG': 9, 'AMZN': 8, 'MSFT': 3, 'AAPL': 2}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| NVDA | 23 | 63.89% | 0.010350 | 0.238057 | 60.87% |
| META | 31 | 86.11% | 0.002695 | 0.083551 | 54.84% |
| MSFT | 3 | 8.33% | 0.009509 | 0.028527 | 66.67% |
| GOOG | 9 | 25.00% | 0.000538 | 0.004846 | 44.44% |
| TSLA | 32 | 88.89% | -0.000382 | -0.012211 | 46.88% |
| AAPL | 2 | 5.56% | -0.015441 | -0.030881 | 50.00% |
| AMZN | 8 | 22.22% | -0.031151 | -0.249205 | 12.50% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| NVDA | -0.004565 | 41.67% | 88.89% | 100.00% |
| META | -0.003083 | 38.89% | 91.67% | 100.00% |
| MSFT | -0.002935 | 41.67% | 88.89% | 100.00% |
| AAPL | -0.000549 | 50.00% | 88.89% | 100.00% |
| AMZN | 0.001361 | 52.78% | 91.67% | 100.00% |
| TSLA | 0.001362 | 41.67% | 91.67% | 100.00% |
| GOOG | 0.002139 | 41.67% | 91.67% | 100.00% |
