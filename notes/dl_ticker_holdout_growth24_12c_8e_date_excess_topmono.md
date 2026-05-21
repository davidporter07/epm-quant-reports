# DL Ticker Holdout Robustness Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_3c_3e_date_excess_topmono_shadow_log.parquet`
- Trade days: 12

## Summary

| Top N | Base Excess | Base Hit | Max Ticker | Worst Holdout Excess | Median Holdout Excess | Positive Holdout Rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | -0.005681 | 50.00% | 58.33% | -0.016525 | -0.007449 | 33.33% |
| 2 | 0.026992 | 50.00% | 91.67% | 0.000162 | 0.031742 | 100.00% |
| 3 | 0.024192 | 58.33% | 100.00% | 0.005568 | 0.026659 | 100.00% |

## Top 1 Details

- Base ticker counts: `{'PLTR': 7, 'TSLA': 4, 'INTC': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| PLTR | 7 | 58.33% | 0.026033 | 0.182231 | 57.14% |
| INTC | 1 | 8.33% | 0.033942 | 0.033942 | 100.00% |
| TSLA | 4 | 33.33% | -0.071085 | -0.284342 | 25.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| PLTR | -0.016525 | 41.67% | 66.67% | 100.00% |
| INTC | -0.007449 | 50.00% | 58.33% | 100.00% |
| TSLA | 0.077454 | 58.33% | 91.67% | 100.00% |

## Top 2 Details

- Base ticker counts: `{'PLTR': 11, 'TSLA': 8, 'INTC': 2, 'AVGO': 1, 'ORCL': 1, 'MU': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| TSLA | 8 | 66.67% | 0.046782 | 0.374254 | 50.00% |
| PLTR | 11 | 91.67% | 0.028280 | 0.311077 | 45.45% |
| AVGO | 1 | 8.33% | 0.017588 | 0.017588 | 100.00% |
| MU | 1 | 8.33% | 0.012825 | 0.012825 | 100.00% |
| INTC | 2 | 16.67% | -0.011513 | -0.023026 | 50.00% |
| ORCL | 1 | 8.33% | -0.044914 | -0.044914 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| PLTR | 0.000162 | 50.00% | 66.67% | 100.00% |
| INTC | 0.019158 | 50.00% | 100.00% | 100.00% |
| AVGO | 0.031080 | 50.00% | 91.67% | 100.00% |
| MU | 0.032403 | 50.00% | 100.00% | 100.00% |
| TSLA | 0.032714 | 58.33% | 91.67% | 100.00% |
| ORCL | 0.047389 | 58.33% | 91.67% | 100.00% |

## Top 3 Details

- Base ticker counts: `{'PLTR': 12, 'TSLA': 8, 'AVGO': 4, 'INTC': 4, 'ORCL': 3, 'AMD': 2, 'MU': 2, 'NVDA': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| PLTR | 12 | 100.00% | 0.024192 | 0.290304 | 58.33% |
| TSLA | 8 | 66.67% | 0.024841 | 0.198728 | 50.00% |
| AVGO | 4 | 33.33% | 0.049003 | 0.196011 | 75.00% |
| MU | 2 | 16.67% | 0.047171 | 0.094342 | 100.00% |
| NVDA | 1 | 8.33% | 0.091330 | 0.091330 | 100.00% |
| AMD | 2 | 16.67% | 0.037822 | 0.075644 | 50.00% |
| ORCL | 3 | 25.00% | 0.021683 | 0.065050 | 66.67% |
| INTC | 4 | 33.33% | -0.035125 | -0.140498 | 25.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| PLTR | 0.005568 | 58.33% | 66.67% | 100.00% |
| AMD | 0.011106 | 58.33% | 100.00% | 100.00% |
| NVDA | 0.020928 | 58.33% | 100.00% | 100.00% |
| AVGO | 0.024567 | 50.00% | 100.00% | 100.00% |
| ORCL | 0.028750 | 58.33% | 100.00% | 100.00% |
| MU | 0.029047 | 58.33% | 100.00% | 100.00% |
| TSLA | 0.034833 | 58.33% | 100.00% | 100.00% |
| INTC | 0.038068 | 66.67% | 100.00% | 100.00% |
