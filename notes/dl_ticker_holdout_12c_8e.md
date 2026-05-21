# DL Ticker Holdout Robustness Report

- Log path: `data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_shadow_log.parquet`
- Trade days: 12

## Summary

| Top N | Base Excess | Base Hit | Max Ticker | Worst Holdout Excess | Median Holdout Excess | Positive Holdout Rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.017239 | 50.00% | 50.00% | -0.024157 | 0.012500 | 60.00% |
| 2 | -0.001109 | 50.00% | 66.67% | -0.021271 | -0.000502 | 42.86% |
| 3 | -0.008996 | 33.33% | 83.33% | -0.017015 | -0.005013 | 14.29% |

## Top 1 Details

- Base ticker counts: `{'TSLA': 6, 'NVDA': 2, 'AMZN': 2, 'AAPL': 1, 'META': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| AMZN | 2 | 16.67% | 0.079562 | 0.159124 | 100.00% |
| TSLA | 6 | 50.00% | 0.026261 | 0.157569 | 50.00% |
| META | 1 | 8.33% | 0.008575 | 0.008575 | 100.00% |
| AAPL | 1 | 8.33% | -0.057517 | -0.057517 | 0.00% |
| NVDA | 2 | 16.67% | -0.030442 | -0.060884 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| TSLA | -0.024157 | 41.67% | 33.33% | 100.00% |
| AMZN | -0.000027 | 25.00% | 58.33% | 100.00% |
| META | 0.012500 | 41.67% | 50.00% | 100.00% |
| AAPL | 0.026483 | 58.33% | 50.00% | 100.00% |
| NVDA | 0.032893 | 66.67% | 58.33% | 100.00% |

## Top 2 Details

- Base ticker counts: `{'TSLA': 8, 'META': 5, 'AMZN': 5, 'AAPL': 2, 'NVDA': 2, 'GOOG': 1, 'MSFT': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| MSFT | 1 | 8.33% | 0.042568 | 0.042568 | 100.00% |
| AMZN | 5 | 41.67% | 0.005325 | 0.026627 | 40.00% |
| NVDA | 2 | 16.67% | 0.003809 | 0.007618 | 50.00% |
| GOOG | 1 | 8.33% | 0.005780 | 0.005780 | 100.00% |
| AAPL | 2 | 16.67% | -0.010921 | -0.021843 | 50.00% |
| META | 5 | 41.67% | -0.006936 | -0.034681 | 40.00% |
| TSLA | 8 | 66.67% | -0.006586 | -0.052690 | 50.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| TSLA | -0.021271 | 33.33% | 66.67% | 100.00% |
| AMZN | -0.012938 | 41.67% | 75.00% | 100.00% |
| MSFT | -0.002386 | 41.67% | 66.67% | 100.00% |
| META | -0.000502 | 50.00% | 75.00% | 100.00% |
| NVDA | 0.001117 | 50.00% | 66.67% | 100.00% |
| GOOG | 0.002101 | 50.00% | 66.67% | 100.00% |
| AAPL | 0.002452 | 58.33% | 66.67% | 100.00% |

## Top 3 Details

- Base ticker counts: `{'META': 10, 'TSLA': 9, 'AMZN': 7, 'NVDA': 3, 'GOOG': 3, 'AAPL': 2, 'MSFT': 2}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| MSFT | 2 | 16.67% | -0.001716 | -0.003432 | 50.00% |
| NVDA | 3 | 25.00% | -0.008022 | -0.024067 | 66.67% |
| AMZN | 7 | 58.33% | -0.005474 | -0.038319 | 28.57% |
| AAPL | 2 | 16.67% | -0.023728 | -0.047455 | 0.00% |
| META | 10 | 83.33% | -0.004747 | -0.047468 | 40.00% |
| GOOG | 3 | 25.00% | -0.021152 | -0.063456 | 0.00% |
| TSLA | 9 | 75.00% | -0.011075 | -0.099675 | 33.33% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| TSLA | -0.017015 | 25.00% | 91.67% | 100.00% |
| MSFT | -0.014923 | 33.33% | 83.33% | 100.00% |
| AMZN | -0.008773 | 41.67% | 91.67% | 100.00% |
| AAPL | -0.005013 | 50.00% | 83.33% | 100.00% |
| META | -0.004482 | 25.00% | 83.33% | 100.00% |
| NVDA | -0.003709 | 33.33% | 83.33% | 100.00% |
| GOOG | 0.000342 | 50.00% | 91.67% | 100.00% |
