# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_36c_8e_date_excess_topmono_seedrobust_2seed_overnight_shadow_log.parquet`
- Trade days: 36
- Window: 2023-04-12 -> 2026-03-18

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.049125 | 0.016404 | -0.019545 | 0.029579 | 55.56% | -52.21% | 36 | 0 |
| top2_bottom2 | 0.059936 | 0.027215 | -0.023283 | 0.036652 | 55.56% | -30.47% | 36 | 0 |
| top3_bottom3 | 0.069430 | 0.036709 | -0.014883 | 0.054547 | 69.44% | -18.61% | 36 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'PLTR': 23, 'TSLA': 4, 'MU': 4, 'NVDA': 2, 'NFLX': 1, 'ORCL': 1, 'INTC': 1}`
- Short counts: `{'TXN': 7, 'CSCO': 5, 'MSFT': 4, 'AAPL': 4, 'SNPS': 3, 'LRCX': 3, 'CRM': 2, 'AMAT': 2, 'NVDA': 2, 'AVGO': 1, 'AMZN': 1, 'GOOG': 1, 'ADBE': 1}`

### top2_bottom2

- Long counts: `{'PLTR': 29, 'TSLA': 14, 'NVDA': 7, 'MU': 6, 'INTC': 5, 'AMD': 3, 'ORCL': 3, 'META': 2, 'NFLX': 1, 'PANW': 1, 'SNPS': 1}`
- Short counts: `{'CSCO': 13, 'TXN': 12, 'AAPL': 10, 'MSFT': 8, 'AMAT': 5, 'SNPS': 4, 'LRCX': 4, 'GOOG': 4, 'CRM': 3, 'PANW': 2, 'NVDA': 2, 'ORCL': 1, 'AVGO': 1, 'META': 1, 'AMZN': 1, 'ADBE': 1}`

### top3_bottom3

- Long counts: `{'PLTR': 32, 'NVDA': 19, 'TSLA': 18, 'INTC': 10, 'MU': 9, 'AMD': 7, 'META': 3, 'ORCL': 3, 'PANW': 2, 'LRCX': 2, 'NFLX': 1, 'AVGO': 1, 'SNPS': 1}`
- Short counts: `{'CSCO': 18, 'AAPL': 15, 'TXN': 14, 'MSFT': 10, 'CRM': 6, 'LRCX': 6, 'GOOG': 6, 'AMAT': 5, 'AMZN': 5, 'SNPS': 4, 'ADBE': 4, 'NOW': 3, 'NVDA': 3, 'AVGO': 2, 'PANW': 2, 'ORCL': 1, 'QCOM': 1, 'AMD': 1, 'META': 1, 'MU': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 36 | 0.049125 | 52.78% | `{'PLTR': 23, 'TSLA': 4, 'MU': 4, 'NVDA': 2, 'NFLX': 1}` |
| 2 | 36 | 0.070747 | 61.11% | `{'TSLA': 10, 'PLTR': 6, 'NVDA': 5, 'INTC': 4, 'AMD': 3}` |
| 3 | 36 | 0.088418 | 66.67% | `{'NVDA': 12, 'INTC': 5, 'AMD': 4, 'TSLA': 4, 'PLTR': 3}` |
| 4 | 36 | 0.085192 | 66.67% | `{'TSLA': 5, 'AMD': 5, 'MU': 5, 'PANW': 3, 'NFLX': 3}` |
| 5 | 36 | 0.048348 | 58.33% | `{'AMD': 7, 'INTC': 5, 'AVGO': 5, 'PANW': 4, 'NVDA': 4}` |
| 6 | 36 | 0.028748 | 63.89% | `{'AVGO': 7, 'AMD': 5, 'NVDA': 4, 'NFLX': 3, 'META': 3}` |
| 7 | 36 | 0.024852 | 55.56% | `{'INTC': 6, 'AMD': 5, 'LRCX': 4, 'META': 3, 'NFLX': 3}` |
| 8 | 36 | 0.043627 | 61.11% | `{'LRCX': 6, 'AVGO': 3, 'TSLA': 3, 'AMD': 3, 'PANW': 2}` |
| 9 | 36 | 0.045303 | 77.78% | `{'AMAT': 5, 'AMZN': 4, 'NFLX': 4, 'AVGO': 3, 'META': 3}` |
| 10 | 36 | 0.049722 | 61.11% | `{'AVGO': 4, 'PANW': 3, 'ADBE': 3, 'LRCX': 3, 'CRM': 3}` |
| 11 | 36 | 0.008982 | 50.00% | `{'NFLX': 5, 'NOW': 3, 'LRCX': 3, 'AMAT': 3, 'QCOM': 3}` |
| 12 | 36 | 0.023317 | 63.89% | `{'GOOG': 6, 'NOW': 5, 'ADBE': 4, 'PANW': 4, 'CRM': 2}` |
| 13 | 36 | 0.024707 | 63.89% | `{'AVGO': 4, 'AMAT': 4, 'QCOM': 4, 'TXN': 4, 'AMZN': 3}` |
| 14 | 36 | 0.035770 | 58.33% | `{'AMZN': 5, 'NFLX': 4, 'QCOM': 4, 'AMAT': 3, 'TXN': 3}` |
| 15 | 36 | 0.029462 | 61.11% | `{'QCOM': 5, 'PANW': 5, 'ADBE': 4, 'MU': 4, 'ORCL': 3}` |
| 16 | 36 | -0.000973 | 58.33% | `{'MU': 4, 'PANW': 4, 'NOW': 3, 'ORCL': 3, 'ADBE': 3}` |
| 17 | 36 | 0.003802 | 47.22% | `{'SNPS': 6, 'AAPL': 4, 'META': 3, 'AMZN': 3, 'QCOM': 2}` |
| 18 | 36 | 0.042029 | 75.00% | `{'QCOM': 7, 'AAPL': 4, 'AMAT': 4, 'MSFT': 3, 'AMZN': 3}` |
| 19 | 36 | 0.013133 | 61.11% | `{'SNPS': 5, 'GOOG': 5, 'CRM': 4, 'NOW': 3, 'AMZN': 3}` |
| 20 | 36 | 0.017698 | 63.89% | `{'MSFT': 7, 'ORCL': 4, 'CRM': 4, 'CSCO': 4, 'META': 4}` |
| 21 | 36 | 0.008645 | 52.78% | `{'MSFT': 6, 'TXN': 4, 'AAPL': 4, 'GOOG': 4, 'CSCO': 3}` |
| 22 | 36 | -0.001917 | 50.00% | `{'CSCO': 5, 'AAPL': 5, 'AMZN': 4, 'CRM': 3, 'NOW': 3}` |
| 23 | 36 | 0.027022 | 66.67% | `{'CSCO': 8, 'AAPL': 6, 'TXN': 5, 'MSFT': 4, 'AMAT': 3}` |
| 24 | 36 | 0.019545 | 55.56% | `{'TXN': 7, 'CSCO': 5, 'MSFT': 4, 'AAPL': 4, 'SNPS': 3}` |
