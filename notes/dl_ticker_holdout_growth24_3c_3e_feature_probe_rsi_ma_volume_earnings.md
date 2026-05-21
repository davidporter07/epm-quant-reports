# DL Ticker Holdout Robustness Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_3c_3e_feature_probe_rsi_ma_volume_earnings_shadow_log.parquet`
- Trade days: 3

## Summary

| Top N | Base Excess | Base Hit | Max Ticker | Worst Holdout Excess | Median Holdout Excess | Positive Holdout Rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.172078 | 66.67% | 33.33% | -0.000516 | 0.128641 | 66.67% |
| 2 | 0.058496 | 66.67% | 66.67% | 0.009252 | 0.088886 | 100.00% |
| 3 | 0.076472 | 100.00% | 100.00% | 0.068108 | 0.072641 | 100.00% |

## Top 1 Details

- Base ticker counts: `{'AMD': 1, 'MU': 1, 'INTC': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| INTC | 1 | 33.33% | 0.414364 | 0.414364 | 100.00% |
| MU | 1 | 33.33% | 0.148778 | 0.148778 | 100.00% |
| AMD | 1 | 33.33% | -0.046909 | -0.046909 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| INTC | -0.000516 | 33.33% | 66.67% | 100.00% |
| AMD | 0.128641 | 66.67% | 33.33% | 100.00% |
| MU | 0.173939 | 66.67% | 33.33% | 100.00% |

## Top 2 Details

- Base ticker counts: `{'PLTR': 2, 'MU': 2, 'AMD': 1, 'INTC': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| MU | 2 | 66.67% | 0.146145 | 0.292290 | 100.00% |
| INTC | 1 | 33.33% | 0.146755 | 0.146755 | 100.00% |
| PLTR | 2 | 66.67% | 0.014366 | 0.028733 | 50.00% |
| AMD | 1 | 33.33% | -0.116802 | -0.116802 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| INTC | 0.009252 | 33.33% | 66.67% | 100.00% |
| MU | 0.072465 | 66.67% | 66.67% | 100.00% |
| PLTR | 0.105307 | 100.00% | 100.00% | 100.00% |
| AMD | 0.111085 | 100.00% | 100.00% | 100.00% |

## Top 3 Details

- Base ticker counts: `{'MU': 3, 'PLTR': 2, 'AMD': 1, 'CSCO': 1, 'INTC': 1, 'LRCX': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| MU | 3 | 100.00% | 0.076472 | 0.229416 | 100.00% |
| INTC | 1 | 33.33% | 0.125845 | 0.125845 | 100.00% |
| LRCX | 1 | 33.33% | 0.125845 | 0.125845 | 100.00% |
| PLTR | 2 | 66.67% | 0.051785 | 0.103571 | 100.00% |
| CSCO | 1 | 33.33% | 0.098215 | 0.098215 | 100.00% |
| AMD | 1 | 33.33% | 0.005356 | 0.005356 | 100.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| PLTR | 0.068108 | 100.00% | 100.00% | 100.00% |
| INTC | 0.068341 | 100.00% | 100.00% | 100.00% |
| MU | 0.071248 | 66.67% | 66.67% | 100.00% |
| CSCO | 0.074035 | 100.00% | 100.00% | 100.00% |
| AMD | 0.077796 | 66.67% | 100.00% | 100.00% |
| LRCX | 0.101816 | 100.00% | 100.00% | 100.00% |
