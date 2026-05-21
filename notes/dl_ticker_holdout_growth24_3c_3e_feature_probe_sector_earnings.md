# DL Ticker Holdout Robustness Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_3c_3e_feature_probe_sector_earnings_shadow_log.parquet`
- Trade days: 3

## Summary

| Top N | Base Excess | Base Hit | Max Ticker | Worst Holdout Excess | Median Holdout Excess | Positive Holdout Rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.133689 | 66.67% | 100.00% | 0.025770 | 0.025770 | 100.00% |
| 2 | 0.076823 | 66.67% | 100.00% | 0.006921 | 0.059212 | 100.00% |
| 3 | 0.045302 | 66.67% | 100.00% | 0.004302 | 0.031335 | 100.00% |

## Top 1 Details

- Base ticker counts: `{'INTC': 3}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| INTC | 3 | 100.00% | 0.133689 | 0.401068 | 66.67% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| INTC | 0.025770 | 66.67% | 33.33% | 100.00% |

## Top 2 Details

- Base ticker counts: `{'INTC': 3, 'PLTR': 1, 'MU': 1, 'TXN': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| TXN | 1 | 33.33% | 0.256077 | 0.256077 | 100.00% |
| INTC | 3 | 100.00% | 0.076823 | 0.230470 | 66.67% |
| MU | 1 | 33.33% | 0.058846 | 0.058846 | 100.00% |
| PLTR | 1 | 33.33% | -0.084453 | -0.084453 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| INTC | 0.006921 | 33.33% | 100.00% | 100.00% |
| TXN | 0.038658 | 66.67% | 100.00% | 100.00% |
| MU | 0.079765 | 66.67% | 100.00% | 100.00% |
| PLTR | 0.097324 | 66.67% | 100.00% | 100.00% |

## Top 3 Details

- Base ticker counts: `{'INTC': 3, 'PLTR': 3, 'AMD': 1, 'MU': 1, 'TXN': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| INTC | 3 | 100.00% | 0.045302 | 0.135906 | 66.67% |
| PLTR | 3 | 100.00% | 0.045302 | 0.135906 | 66.67% |
| TXN | 1 | 33.33% | 0.121183 | 0.121183 | 100.00% |
| MU | 1 | 33.33% | 0.086661 | 0.086661 | 100.00% |
| AMD | 1 | 33.33% | -0.071939 | -0.071939 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| INTC | 0.004302 | 66.67% | 100.00% | 100.00% |
| TXN | 0.008805 | 66.67% | 100.00% | 100.00% |
| MU | 0.031335 | 66.67% | 100.00% | 100.00% |
| PLTR | 0.061700 | 100.00% | 100.00% | 100.00% |
| AMD | 0.081414 | 100.00% | 100.00% | 100.00% |
