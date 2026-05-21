# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_3c_3e_date_excess_topmono_shadow_log.parquet`
- Trade days: 3
- Window: 2025-09-16 -> 2025-11-13

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.019296 | -0.006462 | 0.021976 | 0.041272 | 66.67% | -2.19% | 3 | 0 |
| top2_bottom2 | 0.003111 | -0.022647 | 0.035434 | 0.038545 | 100.00% | 0.00% | 3 | 0 |
| top3_bottom3 | 0.031863 | 0.006105 | 0.013097 | 0.044961 | 66.67% | -13.09% | 3 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'PLTR': 2, 'INTC': 1}`
- Short counts: `{'MSFT': 3}`

### top2_bottom2

- Long counts: `{'PLTR': 2, 'INTC': 2, 'ORCL': 1, 'MU': 1}`
- Short counts: `{'MSFT': 3, 'NOW': 2, 'NVDA': 1}`

### top3_bottom3

- Long counts: `{'PLTR': 3, 'ORCL': 2, 'INTC': 2, 'AMD': 1, 'MU': 1}`
- Short counts: `{'MSFT': 3, 'CSCO': 2, 'NOW': 2, 'AMZN': 1, 'NVDA': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 3 | 0.019296 | 66.67% | `{'PLTR': 2, 'INTC': 1}` |
| 2 | 3 | -0.013073 | 33.33% | `{'ORCL': 1, 'INTC': 1, 'MU': 1}` |
| 3 | 3 | 0.089367 | 66.67% | `{'AMD': 1, 'ORCL': 1, 'PLTR': 1}` |
| 4 | 3 | 0.095156 | 66.67% | `{'AVGO': 1, 'MU': 1, 'LRCX': 1}` |
| 5 | 3 | -0.030510 | 66.67% | `{'AMD': 2, 'TSLA': 1}` |
| 6 | 3 | -0.005659 | 33.33% | `{'MU': 1, 'TSLA': 1, 'ORCL': 1}` |
| 7 | 3 | 0.028737 | 66.67% | `{'SNPS': 2, 'NVDA': 1}` |
| 8 | 3 | 0.148515 | 100.00% | `{'LRCX': 2, 'TSLA': 1}` |
| 9 | 3 | 0.250573 | 100.00% | `{'INTC': 1, 'GOOG': 1, 'AMAT': 1}` |
| 10 | 3 | 0.033309 | 66.67% | `{'SNPS': 1, 'AVGO': 1, 'GOOG': 1}` |
| 11 | 3 | -0.010967 | 0.00% | `{'TXN': 1, 'AMAT': 1, 'AVGO': 1}` |
| 12 | 3 | 0.138225 | 100.00% | `{'QCOM': 2, 'AMAT': 1}` |
| 13 | 3 | 0.029613 | 66.67% | `{'GOOG': 1, 'PANW': 1, 'TXN': 1}` |
| 14 | 3 | -0.024920 | 33.33% | `{'META': 1, 'AAPL': 1, 'PANW': 1}` |
| 15 | 3 | 0.022666 | 66.67% | `{'CRM': 2, 'QCOM': 1}` |
| 16 | 3 | -0.110897 | 0.00% | `{'AMZN': 1, 'TXN': 1, 'NFLX': 1}` |
| 17 | 3 | 0.023321 | 100.00% | `{'PANW': 1, 'NVDA': 1, 'AAPL': 1}` |
| 18 | 3 | 0.052342 | 100.00% | `{'NFLX': 1, 'AMZN': 1, 'ADBE': 1}` |
| 19 | 3 | -0.049494 | 33.33% | `{'CRM': 1, 'META': 1, 'CSCO': 1}` |
| 20 | 3 | -0.031074 | 33.33% | `{'AAPL': 1, 'NFLX': 1, 'NOW': 1}` |
| 21 | 3 | 0.002959 | 66.67% | `{'ADBE': 2, 'META': 1}` |
| 22 | 3 | 0.031575 | 66.67% | `{'CSCO': 2, 'AMZN': 1}` |
| 23 | 3 | -0.048892 | 0.00% | `{'NOW': 2, 'NVDA': 1}` |
| 24 | 3 | -0.021976 | 33.33% | `{'MSFT': 3}` |
