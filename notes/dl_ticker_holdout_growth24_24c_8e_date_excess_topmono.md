# DL Ticker Holdout Robustness Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_3c_3e_date_excess_topmono_shadow_log.parquet`
- Trade days: 24

## Summary

| Top N | Base Excess | Base Hit | Max Ticker | Worst Holdout Excess | Median Holdout Excess | Positive Holdout Rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.010190 | 41.67% | 58.33% | -0.003348 | 0.012712 | 80.00% |
| 2 | 0.033823 | 62.50% | 83.33% | 0.009053 | 0.038056 | 100.00% |
| 3 | 0.030063 | 66.67% | 91.67% | 0.016427 | 0.031169 | 100.00% |

## Top 1 Details

- Base ticker counts: `{'PLTR': 14, 'TSLA': 7, 'PANW': 1, 'MU': 1, 'INTC': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| PLTR | 14 | 58.33% | 0.056434 | 0.790081 | 50.00% |
| INTC | 1 | 4.17% | 0.033942 | 0.033942 | 100.00% |
| PANW | 1 | 4.17% | -0.020245 | -0.020245 | 0.00% |
| MU | 1 | 4.17% | -0.143027 | -0.143027 | 0.00% |
| TSLA | 7 | 29.17% | -0.059456 | -0.416190 | 28.57% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| PLTR | -0.003348 | 50.00% | 50.00% | 100.00% |
| INTC | 0.007510 | 41.67% | 58.33% | 100.00% |
| PANW | 0.012712 | 45.83% | 62.50% | 100.00% |
| MU | 0.015559 | 41.67% | 58.33% | 100.00% |
| TSLA | 0.070325 | 54.17% | 79.17% | 100.00% |

## Top 2 Details

- Base ticker counts: `{'PLTR': 20, 'TSLA': 12, 'AMD': 4, 'INTC': 3, 'NVDA': 3, 'MU': 2, 'PANW': 2, 'AVGO': 1, 'ORCL': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| PLTR | 20 | 83.33% | 0.042597 | 0.851936 | 60.00% |
| TSLA | 12 | 50.00% | 0.053535 | 0.642416 | 66.67% |
| AMD | 4 | 16.67% | 0.032443 | 0.129772 | 50.00% |
| NVDA | 3 | 12.50% | 0.034712 | 0.104135 | 66.67% |
| PANW | 2 | 8.33% | 0.013725 | 0.027451 | 100.00% |
| AVGO | 1 | 4.17% | 0.017588 | 0.017588 | 100.00% |
| INTC | 3 | 12.50% | -0.007442 | -0.022325 | 66.67% |
| ORCL | 1 | 4.17% | -0.044914 | -0.044914 | 0.00% |
| MU | 2 | 8.33% | -0.041286 | -0.082572 | 50.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| PLTR | 0.009053 | 58.33% | 50.00% | 100.00% |
| INTC | 0.026328 | 58.33% | 87.50% | 100.00% |
| PANW | 0.029745 | 58.33% | 83.33% | 100.00% |
| AVGO | 0.036276 | 62.50% | 83.33% | 100.00% |
| NVDA | 0.038056 | 62.50% | 87.50% | 100.00% |
| TSLA | 0.038591 | 66.67% | 87.50% | 100.00% |
| MU | 0.038962 | 62.50% | 87.50% | 100.00% |
| AMD | 0.039259 | 62.50% | 83.33% | 100.00% |
| ORCL | 0.044208 | 66.67% | 83.33% | 100.00% |

## Top 3 Details

- Base ticker counts: `{'PLTR': 22, 'TSLA': 12, 'NVDA': 8, 'AMD': 7, 'INTC': 7, 'AVGO': 4, 'ORCL': 3, 'MU': 3, 'PANW': 2, 'META': 2, 'NFLX': 1, 'CSCO': 1}`

### Selected Ticker Contribution

| Ticker | Days | Day Share | Mean Excess When Selected | Total Excess Contribution | Hit Rate |
|---|---:|---:|---:|---:|---:|
| PLTR | 22 | 91.67% | 0.035301 | 0.776623 | 68.18% |
| NVDA | 8 | 33.33% | 0.055670 | 0.445359 | 87.50% |
| TSLA | 12 | 50.00% | 0.034612 | 0.415346 | 66.67% |
| AMD | 7 | 29.17% | 0.040152 | 0.281064 | 71.43% |
| AVGO | 4 | 16.67% | 0.049003 | 0.196011 | 75.00% |
| NFLX | 1 | 4.17% | 0.157079 | 0.157079 | 100.00% |
| ORCL | 3 | 12.50% | 0.021683 | 0.065050 | 66.67% |
| MU | 3 | 12.50% | 0.007390 | 0.022169 | 66.67% |
| PANW | 2 | 8.33% | -0.006510 | -0.013020 | 50.00% |
| INTC | 7 | 29.17% | -0.002421 | -0.016950 | 57.14% |
| CSCO | 1 | 4.17% | -0.072173 | -0.072173 | 0.00% |
| META | 2 | 8.33% | -0.046003 | -0.092006 | 0.00% |

### Rerank Without Ticker

| Excluded | Mean Excess | Excess Hit | Max Ticker | Coverage |
|---|---:|---:|---:|---:|
| PLTR | 0.016427 | 58.33% | 54.17% | 100.00% |
| AMD | 0.023408 | 62.50% | 91.67% | 100.00% |
| NFLX | 0.027421 | 66.67% | 91.67% | 100.00% |
| CSCO | 0.028788 | 66.67% | 91.67% | 100.00% |
| META | 0.029575 | 66.67% | 91.67% | 100.00% |
| AVGO | 0.030660 | 62.50% | 91.67% | 100.00% |
| PANW | 0.031679 | 66.67% | 91.67% | 100.00% |
| ORCL | 0.032529 | 62.50% | 91.67% | 100.00% |
| MU | 0.033112 | 66.67% | 91.67% | 100.00% |
| NVDA | 0.034033 | 66.67% | 95.83% | 100.00% |
| TSLA | 0.036456 | 62.50% | 95.83% | 100.00% |
| INTC | 0.043175 | 70.83% | 95.83% | 100.00% |
