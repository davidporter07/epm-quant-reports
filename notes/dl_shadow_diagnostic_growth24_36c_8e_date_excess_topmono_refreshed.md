# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_36c_8e_date_excess_topmono_refreshed_shadow_log.parquet`
- Trade days: 36
- Window: 2023-04-12 -> 2026-03-18

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.066692 | 0.033971 | -0.014540 | 0.052152 | 63.89% | -29.16% | 36 | 0 |
| top2_bottom2 | 0.083598 | 0.050877 | -0.027392 | 0.056206 | 66.67% | -22.66% | 36 | 0 |
| top3_bottom3 | 0.088882 | 0.056161 | -0.019751 | 0.069131 | 80.56% | -17.32% | 36 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'PLTR': 23, 'TSLA': 5, 'NVDA': 3, 'MU': 3, 'INTC': 2}`
- Short counts: `{'AMAT': 6, 'MSFT': 5, 'TXN': 5, 'CRM': 3, 'AAPL': 3, 'GOOG': 3, 'SNPS': 3, 'NVDA': 3, 'LRCX': 1, 'INTC': 1, 'META': 1, 'AMZN': 1, 'CSCO': 1}`

### top2_bottom2

- Long counts: `{'PLTR': 25, 'TSLA': 12, 'NVDA': 8, 'MU': 8, 'INTC': 7, 'AMD': 4, 'LRCX': 3, 'ORCL': 2, 'META': 1, 'PANW': 1, 'AVGO': 1}`
- Short counts: `{'AMAT': 8, 'TXN': 7, 'AMZN': 7, 'MSFT': 6, 'CRM': 5, 'GOOG': 5, 'CSCO': 5, 'NVDA': 5, 'AAPL': 4, 'LRCX': 3, 'MU': 3, 'SNPS': 3, 'NOW': 3, 'AVGO': 2, 'INTC': 2, 'QCOM': 1, 'PANW': 1, 'ORCL': 1, 'META': 1}`

### top3_bottom3

- Long counts: `{'PLTR': 32, 'TSLA': 18, 'NVDA': 13, 'INTC': 12, 'AMD': 8, 'MU': 8, 'META': 4, 'AVGO': 3, 'ORCL': 3, 'LRCX': 3, 'PANW': 2, 'NFLX': 2}`
- Short counts: `{'MSFT': 11, 'AMAT': 10, 'AMZN': 9, 'CSCO': 8, 'TXN': 8, 'CRM': 7, 'GOOG': 7, 'LRCX': 6, 'AAPL': 6, 'NVDA': 6, 'NOW': 5, 'MU': 4, 'SNPS': 4, 'INTC': 3, 'META': 3, 'AVGO': 2, 'QCOM': 2, 'ORCL': 2, 'PANW': 2, 'AMD': 1, 'ADBE': 1, 'NFLX': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 36 | 0.066692 | 58.33% | `{'PLTR': 23, 'TSLA': 5, 'NVDA': 3, 'MU': 3, 'INTC': 2}` |
| 2 | 36 | 0.100504 | 69.44% | `{'TSLA': 7, 'NVDA': 5, 'MU': 5, 'INTC': 5, 'AMD': 4}` |
| 3 | 36 | 0.099451 | 66.67% | `{'PLTR': 7, 'TSLA': 6, 'NVDA': 5, 'INTC': 5, 'AMD': 4}` |
| 4 | 36 | 0.039719 | 58.33% | `{'NVDA': 7, 'INTC': 6, 'MU': 5, 'AMD': 4, 'TSLA': 3}` |
| 5 | 36 | 0.013903 | 50.00% | `{'AVGO': 6, 'AMD': 4, 'MU': 4, 'PANW': 3, 'ADBE': 3}` |
| 6 | 36 | 0.031030 | 61.11% | `{'AMD': 7, 'AVGO': 4, 'LRCX': 4, 'PANW': 4, 'ADBE': 2}` |
| 7 | 36 | 0.047487 | 69.44% | `{'NFLX': 4, 'NVDA': 4, 'TSLA': 4, 'AVGO': 3, 'SNPS': 3}` |
| 8 | 36 | 0.055117 | 63.89% | `{'NOW': 4, 'AVGO': 4, 'META': 3, 'MU': 3, 'NFLX': 3}` |
| 9 | 36 | 0.049554 | 66.67% | `{'AMAT': 6, 'NFLX': 4, 'ORCL': 4, 'LRCX': 3, 'AVGO': 3}` |
| 10 | 36 | 0.004430 | 63.89% | `{'CRM': 5, 'CSCO': 4, 'ORCL': 4, 'GOOG': 3, 'AMD': 3}` |
| 11 | 36 | 0.011240 | 55.56% | `{'AAPL': 4, 'AVGO': 3, 'PANW': 3, 'LRCX': 3, 'ADBE': 2}` |
| 12 | 36 | 0.029443 | 55.56% | `{'ORCL': 4, 'PANW': 4, 'QCOM': 4, 'AMZN': 3, 'ADBE': 3}` |
| 13 | 36 | 0.004298 | 55.56% | `{'GOOG': 5, 'CRM': 3, 'CSCO': 3, 'QCOM': 3, 'MSFT': 3}` |
| 14 | 36 | 0.041621 | 63.89% | `{'LRCX': 4, 'QCOM': 3, 'CSCO': 3, 'META': 3, 'AMAT': 3}` |
| 15 | 36 | 0.028801 | 63.89% | `{'QCOM': 6, 'AAPL': 3, 'AMZN': 3, 'META': 3, 'INTC': 2}` |
| 16 | 36 | 0.000165 | 52.78% | `{'MSFT': 4, 'TXN': 4, 'ADBE': 4, 'AAPL': 3, 'AMZN': 3}` |
| 17 | 36 | 0.009905 | 52.78% | `{'ADBE': 5, 'AMZN': 4, 'SNPS': 3, 'NOW': 3, 'INTC': 3}` |
| 18 | 36 | 0.028371 | 66.67% | `{'SNPS': 7, 'ORCL': 4, 'TXN': 2, 'ADBE': 2, 'MSFT': 2}` |
| 19 | 36 | 0.008963 | 55.56% | `{'CSCO': 6, 'NOW': 4, 'TXN': 4, 'MSFT': 4, 'SNPS': 2}` |
| 20 | 36 | 0.019187 | 52.78% | `{'SNPS': 4, 'TXN': 4, 'MU': 3, 'NFLX': 3, 'GOOG': 3}` |
| 21 | 36 | 0.036168 | 69.44% | `{'AAPL': 5, 'MSFT': 4, 'AMZN': 4, 'LRCX': 3, 'NOW': 3}` |
| 22 | 36 | 0.004470 | 55.56% | `{'MSFT': 5, 'CSCO': 3, 'LRCX': 3, 'AMAT': 2, 'AAPL': 2}` |
| 23 | 36 | 0.040244 | 63.89% | `{'AMZN': 6, 'CSCO': 4, 'MU': 3, 'NOW': 3, 'AVGO': 2}` |
| 24 | 36 | 0.014540 | 61.11% | `{'AMAT': 6, 'MSFT': 5, 'TXN': 5, 'CRM': 3, 'AAPL': 3}` |
