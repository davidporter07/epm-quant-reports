# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_3c_3e_date_excess_topmono_shadow_log.parquet`
- Trade days: 24
- Window: 2023-12-11 -> 2025-11-13

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.039730 | 0.010190 | -0.006113 | 0.033617 | 58.33% | -39.92% | 24 | 0 |
| top2_bottom2 | 0.063363 | 0.033823 | -0.003450 | 0.059913 | 79.17% | -17.11% | 24 | 0 |
| top3_bottom3 | 0.059604 | 0.030063 | -0.016032 | 0.043572 | 70.83% | -27.91% | 24 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'PLTR': 14, 'TSLA': 7, 'PANW': 1, 'MU': 1, 'INTC': 1}`
- Short counts: `{'TXN': 4, 'SNPS': 3, 'LRCX': 3, 'MSFT': 3, 'CRM': 2, 'META': 2, 'CSCO': 1, 'AMAT': 1, 'TSLA': 1, 'AMD': 1, 'ORCL': 1, 'INTC': 1, 'GOOG': 1}`

### top2_bottom2

- Long counts: `{'PLTR': 20, 'TSLA': 12, 'AMD': 4, 'NVDA': 3, 'INTC': 3, 'PANW': 2, 'MU': 2, 'AVGO': 1, 'ORCL': 1}`
- Short counts: `{'TXN': 6, 'SNPS': 4, 'LRCX': 4, 'NOW': 4, 'AMAT': 3, 'AMZN': 3, 'MSFT': 3, 'CSCO': 2, 'TSLA': 2, 'INTC': 2, 'AMD': 2, 'GOOG': 2, 'ORCL': 2, 'CRM': 2, 'META': 2, 'AAPL': 1, 'QCOM': 1, 'PANW': 1, 'NFLX': 1, 'NVDA': 1}`

### top3_bottom3

- Long counts: `{'PLTR': 22, 'TSLA': 12, 'NVDA': 8, 'AMD': 7, 'INTC': 7, 'AVGO': 4, 'MU': 3, 'ORCL': 3, 'META': 2, 'PANW': 2, 'NFLX': 1, 'CSCO': 1}`
- Short counts: `{'TXN': 10, 'AMZN': 7, 'CSCO': 6, 'AMAT': 5, 'SNPS': 5, 'NOW': 5, 'LRCX': 4, 'MSFT': 4, 'TSLA': 3, 'GOOG': 3, 'CRM': 3, 'QCOM': 2, 'INTC': 2, 'PANW': 2, 'AMD': 2, 'NFLX': 2, 'ORCL': 2, 'META': 2, 'MU': 1, 'AAPL': 1, 'NVDA': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 24 | 0.039730 | 50.00% | `{'PLTR': 14, 'TSLA': 7, 'PANW': 1, 'MU': 1, 'INTC': 1}` |
| 2 | 24 | 0.086996 | 70.83% | `{'PLTR': 6, 'TSLA': 5, 'AMD': 4, 'NVDA': 3, 'INTC': 2}` |
| 3 | 24 | 0.052085 | 66.67% | `{'NVDA': 5, 'INTC': 4, 'AMD': 3, 'AVGO': 3, 'META': 2}` |
| 4 | 24 | 0.058534 | 54.17% | `{'INTC': 5, 'MU': 5, 'AVGO': 3, 'NFLX': 2, 'NVDA': 2}` |
| 5 | 24 | 0.064417 | 66.67% | `{'AVGO': 7, 'NVDA': 4, 'PANW': 2, 'META': 2, 'ADBE': 2}` |
| 6 | 24 | 0.025775 | 50.00% | `{'NVDA': 4, 'NFLX': 4, 'MU': 3, 'ORCL': 2, 'ADBE': 2}` |
| 7 | 24 | 0.044180 | 58.33% | `{'AVGO': 3, 'CRM': 3, 'TSLA': 2, 'NOW': 2, 'ADBE': 2}` |
| 8 | 24 | 0.033975 | 58.33% | `{'AVGO': 3, 'PANW': 3, 'LRCX': 3, 'NFLX': 2, 'ORCL': 2}` |
| 9 | 24 | 0.085590 | 75.00% | `{'META': 3, 'NFLX': 3, 'ORCL': 3, 'CSCO': 2, 'NOW': 2}` |
| 10 | 24 | 0.018117 | 66.67% | `{'CSCO': 3, 'AAPL': 3, 'ORCL': 2, 'ADBE': 2, 'MSFT': 2}` |
| 11 | 24 | -0.014700 | 45.83% | `{'AMAT': 3, 'CRM': 2, 'LRCX': 2, 'MU': 2, 'CSCO': 2}` |
| 12 | 24 | 0.027869 | 58.33% | `{'QCOM': 4, 'PANW': 3, 'NOW': 2, 'LRCX': 2, 'CRM': 2}` |
| 13 | 24 | -0.003055 | 50.00% | `{'NOW': 3, 'GOOG': 3, 'QCOM': 2, 'CSCO': 2, 'AMZN': 2}` |
| 14 | 24 | 0.002579 | 41.67% | `{'META': 4, 'AMZN': 3, 'CSCO': 2, 'TXN': 2, 'LRCX': 2}` |
| 15 | 24 | 0.017069 | 62.50% | `{'CRM': 4, 'PANW': 3, 'QCOM': 3, 'CSCO': 2, 'TXN': 1}` |
| 16 | 24 | -0.015836 | 45.83% | `{'QCOM': 4, 'LRCX': 2, 'MSFT': 2, 'ORCL': 2, 'AMZN': 2}` |
| 17 | 24 | 0.024446 | 58.33% | `{'GOOG': 3, 'AMZN': 3, 'SNPS': 2, 'CRM': 2, 'ORCL': 2}` |
| 18 | 24 | 0.048242 | 70.83% | `{'GOOG': 5, 'MSFT': 3, 'TXN': 3, 'AMAT': 3, 'AMZN': 2}` |
| 19 | 24 | 0.007751 | 54.17% | `{'SNPS': 4, 'AAPL': 2, 'MSFT': 2, 'AMAT': 2, 'NOW': 2}` |
| 20 | 24 | 0.023299 | 54.17% | `{'AAPL': 3, 'SNPS': 3, 'QCOM': 2, 'AMAT': 2, 'PANW': 2}` |
| 21 | 24 | 0.033810 | 66.67% | `{'MU': 3, 'ADBE': 3, 'LRCX': 3, 'NOW': 2, 'AMZN': 2}` |
| 22 | 24 | 0.041194 | 70.83% | `{'TXN': 4, 'AMZN': 4, 'CSCO': 4, 'AMAT': 2, 'MU': 1}` |
| 23 | 24 | 0.000788 | 62.50% | `{'NOW': 4, 'AMZN': 3, 'TXN': 2, 'AMAT': 2, 'SNPS': 1}` |
| 24 | 24 | 0.006113 | 50.00% | `{'TXN': 4, 'SNPS': 3, 'LRCX': 3, 'MSFT': 3, 'CRM': 2}` |
