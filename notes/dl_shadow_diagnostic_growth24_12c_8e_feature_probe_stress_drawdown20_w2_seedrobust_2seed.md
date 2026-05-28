# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_12c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet`
- Trade days: 12
- Window: 2025-04-15 -> 2026-03-18

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.158337 | 0.114975 | -0.012100 | 0.146237 | 91.67% | -31.70% | 12 | 0 |
| top2_bottom2 | 0.113836 | 0.070475 | -0.014447 | 0.099390 | 83.33% | -15.57% | 12 | 0 |
| top3_bottom3 | 0.097417 | 0.054056 | -0.029393 | 0.068025 | 66.67% | -12.96% | 12 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'PLTR': 4, 'INTC': 4, 'AMD': 3, 'MU': 1}`
- Short counts: `{'SNPS': 3, 'META': 2, 'GOOG': 2, 'ORCL': 1, 'TSLA': 1, 'ADBE': 1, 'AVGO': 1, 'MSFT': 1}`

### top2_bottom2

- Long counts: `{'PLTR': 8, 'INTC': 7, 'AMD': 4, 'MU': 4, 'ADBE': 1}`
- Short counts: `{'META': 5, 'SNPS': 4, 'MSFT': 3, 'AVGO': 2, 'AAPL': 2, 'GOOG': 2, 'MU': 1, 'ORCL': 1, 'TSLA': 1, 'ADBE': 1, 'CRM': 1, 'AMZN': 1}`

### top3_bottom3

- Long counts: `{'MU': 10, 'PLTR': 8, 'INTC': 7, 'AMD': 6, 'ADBE': 2, 'MSFT': 1, 'ORCL': 1, 'NOW': 1}`
- Short counts: `{'META': 6, 'SNPS': 5, 'MSFT': 4, 'ADBE': 4, 'GOOG': 3, 'NVDA': 2, 'MU': 2, 'AVGO': 2, 'AMZN': 2, 'AAPL': 2, 'ORCL': 1, 'TSLA': 1, 'NOW': 1, 'CRM': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 12 | 0.158337 | 75.00% | `{'PLTR': 4, 'INTC': 4, 'AMD': 3, 'MU': 1}` |
| 2 | 12 | 0.069336 | 58.33% | `{'PLTR': 4, 'INTC': 3, 'MU': 3, 'ADBE': 1, 'AMD': 1}` |
| 3 | 12 | 0.064579 | 58.33% | `{'MU': 6, 'AMD': 2, 'MSFT': 1, 'ADBE': 1, 'ORCL': 1}` |
| 4 | 12 | 0.071601 | 75.00% | `{'LRCX': 4, 'AMD': 3, 'ORCL': 2, 'QCOM': 1, 'PANW': 1}` |
| 5 | 12 | 0.054442 | 75.00% | `{'NVDA': 6, 'ORCL': 2, 'AAPL': 1, 'MSFT': 1, 'AMAT': 1}` |
| 6 | 12 | 0.071735 | 50.00% | `{'LRCX': 3, 'AMD': 2, 'AMAT': 2, 'SNPS': 1, 'TSLA': 1}` |
| 7 | 12 | 0.067255 | 66.67% | `{'NFLX': 3, 'ORCL': 3, 'TXN': 1, 'AAPL': 1, 'TSLA': 1}` |
| 8 | 12 | 0.069140 | 75.00% | `{'AVGO': 2, 'SNPS': 1, 'NVDA': 1, 'QCOM': 1, 'CSCO': 1}` |
| 9 | 12 | 0.016558 | 50.00% | `{'TSLA': 3, 'CSCO': 2, 'NFLX': 2, 'AVGO': 1, 'INTC': 1}` |
| 10 | 12 | 0.024658 | 58.33% | `{'QCOM': 4, 'TXN': 3, 'GOOG': 1, 'CSCO': 1, 'ORCL': 1}` |
| 11 | 12 | 0.021854 | 66.67% | `{'AMAT': 2, 'CSCO': 2, 'INTC': 1, 'ORCL': 1, 'NFLX': 1}` |
| 12 | 12 | 0.007113 | 50.00% | `{'AMAT': 2, 'PANW': 2, 'TXN': 2, 'GOOG': 1, 'QCOM': 1}` |
| 13 | 12 | 0.023048 | 50.00% | `{'CRM': 3, 'QCOM': 2, 'TSLA': 2, 'NFLX': 1, 'ORCL': 1}` |
| 14 | 12 | 0.041342 | 50.00% | `{'PANW': 2, 'LRCX': 1, 'AMD': 1, 'TSLA': 1, 'AMZN': 1}` |
| 15 | 12 | 0.040756 | 58.33% | `{'TXN': 2, 'AMZN': 2, 'AVGO': 2, 'CSCO': 2, 'NOW': 1}` |
| 16 | 12 | 0.011358 | 50.00% | `{'PANW': 3, 'AMZN': 2, 'GOOG': 2, 'TXN': 1, 'NOW': 1}` |
| 17 | 12 | 0.037209 | 83.33% | `{'AAPL': 3, 'AMZN': 2, 'ADBE': 2, 'META': 1, 'NOW': 1}` |
| 18 | 12 | 0.019529 | 66.67% | `{'AAPL': 3, 'NOW': 2, 'CSCO': 2, 'CRM': 1, 'NFLX': 1}` |
| 19 | 12 | 0.038148 | 50.00% | `{'AMZN': 2, 'GOOG': 2, 'MSFT': 2, 'TSLA': 1, 'INTC': 1}` |
| 20 | 12 | 0.023910 | 41.67% | `{'CRM': 4, 'NOW': 2, 'MSFT': 2, 'AVGO': 1, 'NVDA': 1}` |
| 21 | 12 | 0.024109 | 58.33% | `{'ADBE': 3, 'AMZN': 2, 'NVDA': 1, 'LRCX': 1, 'MSFT': 1}` |
| 22 | 12 | 0.055008 | 50.00% | `{'MU': 2, 'ADBE': 2, 'MSFT': 2, 'META': 2, 'SNPS': 1}` |
| 23 | 12 | 0.029333 | 66.67% | `{'AVGO': 2, 'SNPS': 2, 'META': 2, 'AAPL': 2, 'ORCL': 1}` |
| 24 | 8 | -0.027430 | 50.00% | `{'META': 2, 'SNPS': 2, 'GOOG': 2, 'TSLA': 1, 'MSFT': 1}` |
