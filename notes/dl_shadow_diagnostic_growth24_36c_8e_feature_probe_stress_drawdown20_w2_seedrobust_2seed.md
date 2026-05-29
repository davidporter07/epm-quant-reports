# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet`
- Trade days: 36
- Window: 2023-04-12 -> 2026-03-18

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.125531 | 0.093206 | -0.017860 | 0.107671 | 72.22% | -31.70% | 36 | 0 |
| top2_bottom2 | 0.093732 | 0.061407 | -0.011143 | 0.082589 | 75.00% | -19.86% | 36 | 0 |
| top3_bottom3 | 0.075365 | 0.043040 | -0.018483 | 0.056882 | 66.67% | -29.66% | 36 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'PLTR': 25, 'INTC': 4, 'TSLA': 3, 'AMD': 3, 'MU': 1}`
- Short counts: `{'SNPS': 9, 'META': 5, 'AMAT': 3, 'LRCX': 3, 'ADBE': 3, 'CRM': 2, 'TXN': 2, 'TSLA': 2, 'GOOG': 2, 'CSCO': 1, 'MU': 1, 'ORCL': 1, 'AVGO': 1, 'MSFT': 1}`

### top2_bottom2

- Long counts: `{'PLTR': 32, 'NVDA': 10, 'INTC': 9, 'TSLA': 8, 'AMD': 4, 'MU': 4, 'NFLX': 3, 'ADBE': 2}`
- Short counts: `{'SNPS': 12, 'META': 11, 'MSFT': 8, 'CRM': 5, 'ADBE': 5, 'GOOG': 5, 'AMAT': 4, 'ORCL': 3, 'LRCX': 3, 'AAPL': 3, 'TXN': 3, 'AMZN': 2, 'MU': 2, 'TSLA': 2, 'AVGO': 2, 'CSCO': 1, 'QCOM': 1}`

### top3_bottom3

- Long counts: `{'PLTR': 32, 'NVDA': 17, 'MU': 14, 'INTC': 13, 'TSLA': 9, 'NFLX': 7, 'AMD': 7, 'ADBE': 3, 'PANW': 1, 'CSCO': 1, 'AVGO': 1, 'MSFT': 1, 'ORCL': 1, 'NOW': 1}`
- Short counts: `{'SNPS': 14, 'META': 12, 'MSFT': 12, 'ADBE': 11, 'CRM': 7, 'GOOG': 7, 'AMAT': 6, 'AAPL': 6, 'TXN': 5, 'MU': 5, 'ORCL': 4, 'LRCX': 4, 'AMZN': 4, 'AVGO': 3, 'NOW': 2, 'TSLA': 2, 'NVDA': 2, 'CSCO': 1, 'QCOM': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 36 | 0.125531 | 63.89% | `{'PLTR': 25, 'INTC': 4, 'TSLA': 3, 'AMD': 3, 'MU': 1}` |
| 2 | 36 | 0.061933 | 55.56% | `{'NVDA': 10, 'PLTR': 7, 'TSLA': 5, 'INTC': 5, 'NFLX': 3}` |
| 3 | 36 | 0.038630 | 58.33% | `{'MU': 10, 'NVDA': 7, 'NFLX': 4, 'INTC': 4, 'AMD': 3}` |
| 4 | 36 | 0.032998 | 63.89% | `{'AMD': 8, 'LRCX': 6, 'NFLX': 6, 'PANW': 2, 'QCOM': 2}` |
| 5 | 36 | 0.025587 | 61.11% | `{'NVDA': 8, 'MU': 4, 'AMD': 3, 'INTC': 3, 'ADBE': 3}` |
| 6 | 36 | 0.009555 | 52.78% | `{'INTC': 7, 'AMD': 5, 'LRCX': 5, 'AMAT': 3, 'PANW': 3}` |
| 7 | 36 | 0.032522 | 63.89% | `{'ORCL': 5, 'CSCO': 4, 'LRCX': 4, 'GOOG': 3, 'NFLX': 3}` |
| 8 | 36 | 0.071528 | 77.78% | `{'AVGO': 6, 'CSCO': 4, 'PANW': 3, 'ORCL': 3, 'TXN': 2}` |
| 9 | 36 | 0.026876 | 61.11% | `{'QCOM': 4, 'AVGO': 4, 'NFLX': 3, 'TSLA': 3, 'INTC': 2}` |
| 10 | 36 | 0.023832 | 58.33% | `{'CSCO': 6, 'AMAT': 5, 'QCOM': 4, 'SNPS': 3, 'TXN': 3}` |
| 11 | 36 | 0.035920 | 69.44% | `{'PANW': 4, 'NOW': 3, 'AMAT': 3, 'TSLA': 2, 'MU': 2}` |
| 12 | 36 | 0.027445 | 58.33% | `{'TXN': 4, 'QCOM': 4, 'META': 3, 'AVGO': 3, 'GOOG': 3}` |
| 13 | 36 | 0.037550 | 66.67% | `{'ORCL': 4, 'CRM': 4, 'QCOM': 4, 'TSLA': 3, 'AMZN': 3}` |
| 14 | 36 | 0.014029 | 55.56% | `{'TSLA': 4, 'AMZN': 3, 'NOW': 2, 'TXN': 2, 'ORCL': 2}` |
| 15 | 36 | 0.026304 | 58.33% | `{'NOW': 4, 'AMZN': 4, 'META': 4, 'MSFT': 3, 'CSCO': 3}` |
| 16 | 36 | 0.027797 | 55.56% | `{'GOOG': 5, 'NOW': 5, 'ORCL': 4, 'AAPL': 4, 'TXN': 3}` |
| 17 | 36 | 0.027285 | 58.33% | `{'ORCL': 3, 'AMZN': 3, 'QCOM': 3, 'NOW': 3, 'META': 3}` |
| 18 | 36 | 0.024740 | 66.67% | `{'AAPL': 6, 'CSCO': 5, 'META': 4, 'NOW': 3, 'SNPS': 3}` |
| 19 | 36 | 0.014710 | 50.00% | `{'GOOG': 5, 'AMZN': 4, 'AAPL': 3, 'CRM': 3, 'NVDA': 2}` |
| 20 | 36 | 0.022939 | 52.78% | `{'CRM': 6, 'MSFT': 4, 'NOW': 4, 'AAPL': 3, 'TXN': 3}` |
| 21 | 36 | 0.012229 | 52.78% | `{'ADBE': 7, 'TSLA': 3, 'CRM': 3, 'AMZN': 3, 'MSFT': 3}` |
| 22 | 36 | 0.030698 | 63.89% | `{'ADBE': 5, 'MSFT': 5, 'MU': 4, 'CRM': 3, 'AAPL': 3}` |
| 23 | 36 | 0.016567 | 66.67% | `{'MSFT': 6, 'META': 5, 'SNPS': 4, 'GOOG': 3, 'ADBE': 3}` |
| 24 | 30 | 0.008924 | 60.00% | `{'SNPS': 8, 'META': 5, 'AMAT': 3, 'LRCX': 2, 'CRM': 2}` |
