# DL Ticker Holdout Robustness Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_3c_3e_date_excess_topmono_shadow_log.parquet`
- Trade days: 3

## Summary

| Top N | Base Excess | Base Hit | Max Ticker | Worst Holdout Excess | Median Holdout Excess | Positive Holdout Rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | -0.006462 | 33.33% | 66.67% | -0.024744 | -0.019715 | 0.00% |
| 2 | -0.022647 | 33.33% | 66.67% | -0.055133 | 0.001068 | 50.00% |
| 3 | 0.006105 | 66.67% | 100.00% | -0.046347 | 0.029180 | 80.00% |

## Top 1 Details

- Base ticker counts: `{'PLTR': 2, 'INTC': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| INTC | 1 | 33.33% | 0.033942 | 0.033942 | 100.00% |
| PLTR | 2 | 66.67% | -0.026664 | -0.053329 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| PLTR | -0.024744 | 33.33% | 66.67% | 100.00% |
| INTC | -0.014685 | 33.33% | 66.67% | 100.00% |

## Top 2 Details

- Base ticker counts: `{'PLTR': 2, 'INTC': 2, 'ORCL': 1, 'MU': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| MU | 1 | 33.33% | 0.012825 | 0.012825 | 100.00% |
| INTC | 2 | 66.67% | -0.011513 | -0.023026 | 50.00% |
| ORCL | 1 | 33.33% | -0.044914 | -0.044914 | 0.00% |
| PLTR | 2 | 66.67% | -0.040383 | -0.080765 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| INTC | -0.055133 | 33.33% | 100.00% | 100.00% |
| MU | -0.006931 | 33.33% | 100.00% | 100.00% |
| PLTR | 0.009067 | 66.67% | 66.67% | 100.00% |
| ORCL | 0.052356 | 66.67% | 66.67% | 100.00% |

## Top 3 Details

- Base ticker counts: `{'PLTR': 3, 'ORCL': 2, 'INTC': 2, 'AMD': 1, 'MU': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| AMD | 1 | 33.33% | 0.109609 | 0.109609 | 100.00% |
| MU | 1 | 33.33% | 0.026525 | 0.026525 | 100.00% |
| PLTR | 3 | 100.00% | 0.006105 | 0.018316 | 66.67% |
| ORCL | 2 | 66.67% | -0.004105 | -0.008210 | 50.00% |
| INTC | 2 | 66.67% | -0.045646 | -0.091293 | 50.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| AMD | -0.046347 | 33.33% | 100.00% | 100.00% |
| MU | 0.019346 | 66.67% | 100.00% | 100.00% |
| PLTR | 0.029180 | 66.67% | 66.67% | 100.00% |
| INTC | 0.044928 | 66.67% | 100.00% | 100.00% |
| ORCL | 0.054547 | 100.00% | 100.00% | 100.00% |
