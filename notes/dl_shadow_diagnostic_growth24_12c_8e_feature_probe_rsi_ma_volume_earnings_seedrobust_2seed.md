# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_12c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_shadow_log.parquet`
- Trade days: 12
- Window: 2025-04-15 -> 2026-03-18

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.134181 | 0.090820 | 0.016366 | 0.150548 | 91.67% | -31.70% | 12 | 0 |
| top2_bottom2 | 0.092245 | 0.048883 | -0.019551 | 0.072694 | 75.00% | -15.26% | 12 | 0 |
| top3_bottom3 | 0.103539 | 0.060178 | -0.040840 | 0.062699 | 66.67% | -12.42% | 12 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'PLTR': 4, 'AMD': 4, 'INTC': 3, 'MU': 1}`
- Short counts: `{'META': 3, 'TSLA': 2, 'SNPS': 2, 'AVGO': 1, 'AMZN': 1, 'ADBE': 1, 'MSFT': 1, 'AAPL': 1}`

### top2_bottom2

- Long counts: `{'PLTR': 8, 'INTC': 7, 'AMD': 5, 'MU': 3, 'TSLA': 1}`
- Short counts: `{'META': 5, 'SNPS': 4, 'TSLA': 3, 'GOOG': 3, 'ADBE': 3, 'AVGO': 2, 'AMZN': 1, 'CRM': 1, 'MSFT': 1, 'AAPL': 1}`

### top3_bottom3

- Long counts: `{'PLTR': 8, 'INTC': 8, 'MU': 8, 'AMD': 6, 'ADBE': 3, 'LRCX': 2, 'TSLA': 1}`
- Short counts: `{'SNPS': 6, 'ADBE': 5, 'META': 5, 'TSLA': 3, 'GOOG': 3, 'MSFT': 3, 'AVGO': 2, 'AMZN': 2, 'CRM': 2, 'AAPL': 2, 'ORCL': 1, 'MU': 1, 'AMD': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 12 | 0.134181 | 66.67% | `{'PLTR': 4, 'AMD': 4, 'INTC': 3, 'MU': 1}` |
| 2 | 12 | 0.050309 | 58.33% | `{'INTC': 4, 'PLTR': 4, 'MU': 2, 'TSLA': 1, 'AMD': 1}` |
| 3 | 12 | 0.126127 | 75.00% | `{'MU': 5, 'ADBE': 3, 'LRCX': 2, 'INTC': 1, 'AMD': 1}` |
| 4 | 12 | 0.066710 | 75.00% | `{'NVDA': 3, 'AMD': 2, 'LRCX': 2, 'MU': 1, 'ORCL': 1}` |
| 5 | 12 | -0.016847 | 50.00% | `{'NVDA': 4, 'MSFT': 2, 'ORCL': 2, 'PLTR': 2, 'TXN': 1}` |
| 6 | 12 | 0.102914 | 66.67% | `{'LRCX': 2, 'AMAT': 2, 'NFLX': 2, 'QCOM': 1, 'SNPS': 1}` |
| 7 | 12 | 0.039046 | 50.00% | `{'ORCL': 3, 'MSFT': 1, 'AAPL': 1, 'MU': 1, 'AVGO': 1}` |
| 8 | 12 | 0.043915 | 75.00% | `{'CSCO': 2, 'TSLA': 2, 'PANW': 1, 'NOW': 1, 'AVGO': 1}` |
| 9 | 12 | 0.003771 | 50.00% | `{'NFLX': 4, 'CSCO': 2, 'AAPL': 1, 'QCOM': 1, 'ORCL': 1}` |
| 10 | 12 | 0.054784 | 75.00% | `{'QCOM': 2, 'AMAT': 2, 'NVDA': 1, 'ADBE': 1, 'NFLX': 1}` |
| 11 | 12 | 0.017928 | 58.33% | `{'QCOM': 2, 'LRCX': 1, 'GOOG': 1, 'NFLX': 1, 'AMAT': 1}` |
| 12 | 12 | 0.078513 | 75.00% | `{'QCOM': 2, 'SNPS': 1, 'ORCL': 1, 'AMD': 1, 'INTC': 1}` |
| 13 | 12 | -0.012390 | 25.00% | `{'PANW': 3, 'TXN': 3, 'NFLX': 1, 'CRM': 1, 'CSCO': 1}` |
| 14 | 12 | 0.033997 | 50.00% | `{'AVGO': 2, 'CSCO': 2, 'GOOG': 1, 'AMD': 1, 'META': 1}` |
| 15 | 12 | 0.046954 | 75.00% | `{'AVGO': 2, 'TXN': 2, 'AMZN': 2, 'PANW': 1, 'AMAT': 1}` |
| 16 | 12 | 0.013720 | 41.67% | `{'PANW': 3, 'AMZN': 2, 'AMAT': 1, 'TXN': 1, 'ORCL': 1}` |
| 17 | 12 | 0.044365 | 66.67% | `{'NOW': 2, 'PANW': 2, 'AAPL': 2, 'META': 1, 'TXN': 1}` |
| 18 | 12 | 0.034909 | 66.67% | `{'NOW': 3, 'AMZN': 2, 'AAPL': 2, 'NFLX': 1, 'AMAT': 1}` |
| 19 | 12 | 0.043712 | 58.33% | `{'MSFT': 3, 'AMZN': 2, 'CRM': 2, 'MU': 1, 'GOOG': 1}` |
| 20 | 12 | 0.004692 | 41.67% | `{'CRM': 3, 'META': 2, 'LRCX': 1, 'CSCO': 1, 'MSFT': 1}` |
| 21 | 12 | 0.017147 | 50.00% | `{'MSFT': 3, 'CRM': 2, 'ORCL': 1, 'NOW': 1, 'ADBE': 1}` |
| 22 | 12 | 0.081966 | 66.67% | `{'ADBE': 4, 'TSLA': 1, 'MU': 1, 'SNPS': 1, 'MSFT': 1}` |
| 23 | 12 | 0.042191 | 75.00% | `{'GOOG': 3, 'SNPS': 3, 'META': 3, 'AVGO': 2, 'ADBE': 1}` |
| 24 | 8 | -0.045820 | 37.50% | `{'TSLA': 2, 'META': 2, 'AMZN': 1, 'SNPS': 1, 'MSFT': 1}` |
