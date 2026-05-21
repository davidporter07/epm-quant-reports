# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_36c_8e_date_excess_topmono_shadow_log.parquet`
- Trade days: 36
- Window: 2022-12-08 -> 2025-11-13

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.062246 | 0.026787 | -0.011747 | 0.050499 | 66.67% | -39.92% | 36 | 0 |
| top2_bottom2 | 0.078816 | 0.043357 | -0.016748 | 0.062067 | 75.00% | -17.11% | 36 | 0 |
| top3_bottom3 | 0.068010 | 0.032551 | -0.026529 | 0.041481 | 66.67% | -27.91% | 36 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'PLTR': 22, 'TSLA': 7, 'NFLX': 2, 'NVDA': 1, 'META': 1, 'PANW': 1, 'MU': 1, 'INTC': 1}`
- Short counts: `{'TXN': 7, 'LRCX': 4, 'CRM': 4, 'AMAT': 3, 'SNPS': 3, 'MSFT': 3, 'META': 2, 'QCOM': 1, 'AVGO': 1, 'AAPL': 1, 'AMZN': 1, 'CSCO': 1, 'TSLA': 1, 'AMD': 1, 'ORCL': 1, 'INTC': 1, 'GOOG': 1}`

### top2_bottom2

- Long counts: `{'PLTR': 28, 'TSLA': 14, 'NVDA': 10, 'META': 5, 'AMD': 4, 'INTC': 3, 'NFLX': 2, 'PANW': 2, 'MU': 2, 'AVGO': 1, 'ORCL': 1}`
- Short counts: `{'TXN': 9, 'LRCX': 7, 'AMAT': 6, 'SNPS': 5, 'CRM': 5, 'MSFT': 4, 'CSCO': 4, 'AMZN': 4, 'NOW': 4, 'AMD': 3, 'AAPL': 3, 'GOOG': 3, 'QCOM': 2, 'PANW': 2, 'TSLA': 2, 'INTC': 2, 'ORCL': 2, 'META': 2, 'AVGO': 1, 'NFLX': 1, 'NVDA': 1}`

### top3_bottom3

- Long counts: `{'PLTR': 30, 'TSLA': 20, 'NVDA': 16, 'META': 8, 'AMD': 8, 'INTC': 7, 'NFLX': 5, 'AVGO': 4, 'PANW': 3, 'MU': 3, 'ORCL': 3, 'CSCO': 1}`
- Short counts: `{'TXN': 14, 'AMAT': 9, 'AMZN': 9, 'MSFT': 8, 'CSCO': 8, 'LRCX': 7, 'SNPS': 6, 'CRM': 6, 'NOW': 6, 'AMD': 4, 'QCOM': 4, 'AAPL': 4, 'GOOG': 4, 'PANW': 3, 'NFLX': 3, 'TSLA': 3, 'MU': 2, 'INTC': 2, 'ORCL': 2, 'META': 2, 'AVGO': 1, 'NVDA': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 36 | 0.062246 | 61.11% | `{'PLTR': 22, 'TSLA': 7, 'NFLX': 2, 'NVDA': 1, 'META': 1}` |
| 2 | 36 | 0.095386 | 72.22% | `{'NVDA': 9, 'TSLA': 7, 'PLTR': 6, 'META': 4, 'AMD': 4}` |
| 3 | 36 | 0.046399 | 61.11% | `{'TSLA': 6, 'NVDA': 6, 'AMD': 4, 'INTC': 4, 'NFLX': 3}` |
| 4 | 36 | 0.050587 | 55.56% | `{'INTC': 5, 'MU': 5, 'NVDA': 4, 'AMD': 4, 'NFLX': 3}` |
| 5 | 36 | 0.059764 | 66.67% | `{'AVGO': 8, 'AMD': 5, 'NVDA': 5, 'ADBE': 4, 'META': 3}` |
| 6 | 36 | 0.036266 | 58.33% | `{'NFLX': 6, 'NVDA': 4, 'GOOG': 3, 'AMD': 3, 'MU': 3}` |
| 7 | 36 | 0.049703 | 66.67% | `{'CRM': 4, 'ADBE': 4, 'AVGO': 4, 'LRCX': 3, 'NOW': 3}` |
| 8 | 36 | 0.026889 | 58.33% | `{'LRCX': 5, 'AVGO': 4, 'NFLX': 3, 'PANW': 3, 'MSFT': 2}` |
| 9 | 36 | 0.072297 | 72.22% | `{'ORCL': 5, 'AMZN': 4, 'NFLX': 4, 'NOW': 3, 'PANW': 3}` |
| 10 | 36 | 0.034966 | 69.44% | `{'ADBE': 4, 'AAPL': 4, 'MSFT': 3, 'CSCO': 3, 'CRM': 2}` |
| 11 | 36 | -0.005385 | 50.00% | `{'QCOM': 4, 'INTC': 3, 'MU': 3, 'AMAT': 3, 'AMZN': 2}` |
| 12 | 36 | 0.033012 | 63.89% | `{'ADBE': 4, 'QCOM': 4, 'NOW': 3, 'AMAT': 3, 'PANW': 3}` |
| 13 | 36 | 0.008310 | 58.33% | `{'MSFT': 3, 'AMZN': 3, 'NOW': 3, 'GOOG': 3, 'AAPL': 2}` |
| 14 | 36 | 0.022484 | 55.56% | `{'TXN': 4, 'META': 4, 'AAPL': 3, 'AMZN': 3, 'PANW': 2}` |
| 15 | 36 | 0.017113 | 61.11% | `{'QCOM': 5, 'CRM': 4, 'CSCO': 3, 'META': 3, 'PANW': 3}` |
| 16 | 36 | 0.005230 | 52.78% | `{'ORCL': 5, 'QCOM': 4, 'MU': 3, 'MSFT': 3, 'AAPL': 3}` |
| 17 | 36 | 0.034104 | 63.89% | `{'INTC': 4, 'GOOG': 4, 'AMZN': 4, 'CRM': 3, 'MU': 3}` |
| 18 | 36 | 0.042659 | 72.22% | `{'GOOG': 6, 'TXN': 5, 'AMZN': 3, 'MSFT': 3, 'AMAT': 3}` |
| 19 | 36 | 0.015149 | 55.56% | `{'SNPS': 6, 'NOW': 5, 'PANW': 3, 'MSFT': 3, 'ADBE': 3}` |
| 20 | 36 | 0.026954 | 55.56% | `{'SNPS': 6, 'QCOM': 4, 'GOOG': 3, 'AAPL': 3, 'CSCO': 2}` |
| 21 | 36 | 0.037287 | 69.44% | `{'AMAT': 4, 'MU': 4, 'NOW': 3, 'AAPL': 3, 'ADBE': 3}` |
| 22 | 36 | 0.046092 | 69.44% | `{'AMZN': 5, 'TXN': 5, 'MSFT': 4, 'CSCO': 4, 'AMAT': 3}` |
| 23 | 36 | 0.021750 | 69.44% | `{'NOW': 4, 'AMAT': 3, 'LRCX': 3, 'CSCO': 3, 'AMZN': 3}` |
| 24 | 36 | 0.011747 | 52.78% | `{'TXN': 7, 'LRCX': 4, 'CRM': 4, 'AMAT': 3, 'SNPS': 3}` |
