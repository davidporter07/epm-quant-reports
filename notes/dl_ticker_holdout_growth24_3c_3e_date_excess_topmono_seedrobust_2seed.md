# DL Ticker Holdout Robustness Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_3c_3e_date_excess_topmono_seedrobust_2seed_shadow_log.parquet`
- Trade days: 3

## Summary

| Top N | Base Excess | Base Hit | Max Ticker | Worst Holdout Excess | Median Holdout Excess | Positive Holdout Rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.092532 | 66.67% | 100.00% | 0.069551 | 0.069551 | 100.00% |
| 2 | 0.079030 | 100.00% | 100.00% | 0.026437 | 0.045226 | 100.00% |
| 3 | 0.058312 | 100.00% | 100.00% | 0.005141 | 0.036998 | 100.00% |

## Top 1 Details

- Base ticker counts: `{'MU': 3}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| MU | 3 | 100.00% | 0.092532 | 0.277595 | 66.67% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| MU | 0.069551 | 33.33% | 66.67% | 100.00% |

## Top 2 Details

- Base ticker counts: `{'MU': 3, 'INTC': 2, 'PLTR': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| MU | 3 | 100.00% | 0.079030 | 0.237090 | 100.00% |
| INTC | 2 | 66.67% | 0.102801 | 0.205602 | 100.00% |
| PLTR | 1 | 33.33% | 0.031488 | 0.031488 | 100.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| INTC | 0.026437 | 66.67% | 100.00% | 100.00% |
| MU | 0.045226 | 33.33% | 100.00% | 100.00% |
| PLTR | 0.110313 | 100.00% | 100.00% | 100.00% |

## Top 3 Details

- Base ticker counts: `{'MU': 3, 'INTC': 3, 'LRCX': 2, 'PLTR': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| INTC | 3 | 100.00% | 0.058312 | 0.174937 | 100.00% |
| MU | 3 | 100.00% | 0.058312 | 0.174937 | 100.00% |
| LRCX | 2 | 66.67% | 0.074008 | 0.148016 | 100.00% |
| PLTR | 1 | 33.33% | 0.026922 | 0.026922 | 100.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| INTC | 0.005141 | 66.67% | 100.00% | 100.00% |
| MU | 0.017070 | 33.33% | 100.00% | 100.00% |
| LRCX | 0.056926 | 100.00% | 100.00% | 100.00% |
| PLTR | 0.062157 | 100.00% | 100.00% | 100.00% |
