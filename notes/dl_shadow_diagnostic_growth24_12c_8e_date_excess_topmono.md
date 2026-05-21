# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_3c_3e_date_excess_topmono_shadow_log.parquet`
- Trade days: 12
- Window: 2024-12-11 -> 2025-11-13

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.019300 | -0.005681 | 0.000903 | 0.020203 | 58.33% | -38.29% | 12 | 0 |
| top2_bottom2 | 0.051973 | 0.026992 | 0.010253 | 0.062226 | 83.33% | -16.10% | 12 | 0 |
| top3_bottom3 | 0.049173 | 0.024192 | -0.000364 | 0.048809 | 66.67% | -13.78% | 12 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'PLTR': 7, 'TSLA': 4, 'INTC': 1}`
- Short counts: `{'MSFT': 3, 'LRCX': 2, 'CRM': 2, 'META': 2, 'ORCL': 1, 'INTC': 1, 'GOOG': 1}`

### top2_bottom2

- Long counts: `{'PLTR': 11, 'TSLA': 8, 'INTC': 2, 'AVGO': 1, 'ORCL': 1, 'MU': 1}`
- Short counts: `{'NOW': 4, 'MSFT': 3, 'AMAT': 2, 'LRCX': 2, 'ORCL': 2, 'CRM': 2, 'META': 2, 'AMZN': 2, 'TXN': 1, 'INTC': 1, 'CSCO': 1, 'GOOG': 1, 'NVDA': 1}`

### top3_bottom3

- Long counts: `{'PLTR': 12, 'TSLA': 8, 'AVGO': 4, 'INTC': 4, 'ORCL': 3, 'AMD': 2, 'MU': 2, 'NVDA': 1}`
- Short counts: `{'CSCO': 5, 'AMZN': 4, 'NOW': 4, 'TXN': 3, 'CRM': 3, 'MSFT': 3, 'AMAT': 2, 'LRCX': 2, 'ORCL': 2, 'META': 2, 'QCOM': 1, 'PANW': 1, 'INTC': 1, 'NFLX': 1, 'GOOG': 1, 'NVDA': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 12 | 0.019300 | 58.33% | `{'PLTR': 7, 'TSLA': 4, 'INTC': 1}` |
| 2 | 12 | 0.084645 | 50.00% | `{'PLTR': 4, 'TSLA': 4, 'AVGO': 1, 'ORCL': 1, 'INTC': 1}` |
| 3 | 12 | 0.043573 | 58.33% | `{'AVGO': 3, 'AMD': 2, 'INTC': 2, 'ORCL': 2, 'NVDA': 1}` |
| 4 | 12 | 0.037920 | 58.33% | `{'MU': 5, 'INTC': 2, 'AVGO': 2, 'NFLX': 1, 'AMD': 1}` |
| 5 | 12 | 0.070408 | 66.67% | `{'NVDA': 2, 'ADBE': 2, 'AVGO': 2, 'AMD': 2, 'NFLX': 1}` |
| 6 | 12 | 0.050971 | 50.00% | `{'NVDA': 3, 'NFLX': 2, 'MU': 2, 'AVGO': 1, 'AAPL': 1}` |
| 7 | 12 | 0.046602 | 58.33% | `{'ADBE': 2, 'SNPS': 2, 'META': 1, 'MU': 1, 'MSFT': 1}` |
| 8 | 12 | 0.043484 | 58.33% | `{'LRCX': 3, 'ORCL': 1, 'MSFT': 1, 'META': 1, 'QCOM': 1}` |
| 9 | 12 | 0.073853 | 66.67% | `{'AAPL': 2, 'NFLX': 2, 'AMAT': 2, 'NOW': 1, 'CSCO': 1}` |
| 10 | 12 | 0.041158 | 66.67% | `{'MSFT': 2, 'CSCO': 1, 'CRM': 1, 'NVDA': 1, 'TXN': 1}` |
| 11 | 12 | -0.033565 | 33.33% | `{'MSFT': 2, 'AMAT': 2, 'CRM': 1, 'AAPL': 1, 'NVDA': 1}` |
| 12 | 12 | 0.037235 | 50.00% | `{'QCOM': 3, 'PANW': 2, 'AMD': 2, 'ORCL': 2, 'SNPS': 1}` |
| 13 | 12 | -0.012917 | 41.67% | `{'GOOG': 3, 'NOW': 2, 'TXN': 2, 'MSFT': 1, 'AMZN': 1}` |
| 14 | 12 | 0.015513 | 41.67% | `{'META': 2, 'AAPL': 2, 'AMZN': 1, 'CSCO': 1, 'TXN': 1}` |
| 15 | 12 | 0.020068 | 66.67% | `{'PANW': 2, 'QCOM': 2, 'CRM': 2, 'AAPL': 1, 'SNPS': 1}` |
| 16 | 12 | -0.037466 | 25.00% | `{'NFLX': 2, 'QCOM': 2, 'TXN': 2, 'INTC': 1, 'NOW': 1}` |
| 17 | 12 | 0.034060 | 66.67% | `{'ORCL': 2, 'AMZN': 2, 'MU': 1, 'AMD': 1, 'NOW': 1}` |
| 18 | 12 | 0.067225 | 75.00% | `{'GOOG': 2, 'ADBE': 2, 'TXN': 2, 'AMAT': 2, 'LRCX': 1}` |
| 19 | 12 | -0.031192 | 25.00% | `{'ADBE': 2, 'CRM': 2, 'SNPS': 2, 'GOOG': 1, 'NOW': 1}` |
| 20 | 12 | 0.015991 | 41.67% | `{'PANW': 2, 'NOW': 2, 'META': 2, 'SNPS': 1, 'CSCO': 1}` |
| 21 | 12 | 0.011582 | 58.33% | `{'AMAT': 2, 'LRCX': 2, 'ADBE': 2, 'QCOM': 1, 'AMZN': 1}` |
| 22 | 12 | 0.021599 | 66.67% | `{'CSCO': 4, 'TXN': 2, 'AMZN': 2, 'QCOM': 1, 'PANW': 1}` |
| 23 | 12 | -0.019604 | 41.67% | `{'NOW': 4, 'AMAT': 2, 'AMZN': 2, 'TXN': 1, 'ORCL': 1}` |
| 24 | 12 | -0.000903 | 41.67% | `{'MSFT': 3, 'LRCX': 2, 'CRM': 2, 'META': 2, 'ORCL': 1}` |
