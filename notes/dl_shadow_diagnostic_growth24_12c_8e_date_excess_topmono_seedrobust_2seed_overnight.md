# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_12c_8e_date_excess_topmono_seedrobust_2seed_overnight_shadow_log.parquet`
- Trade days: 12
- Window: 2025-04-15 -> 2026-03-18

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.090521 | 0.045537 | -0.024556 | 0.065965 | 66.67% | -11.51% | 12 | 0 |
| top2_bottom2 | 0.083894 | 0.038910 | -0.031507 | 0.052388 | 58.33% | -22.84% | 12 | 0 |
| top3_bottom3 | 0.079933 | 0.034949 | -0.021302 | 0.058630 | 75.00% | -14.54% | 12 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'PLTR': 7, 'MU': 3, 'ORCL': 1, 'INTC': 1}`
- Short counts: `{'MSFT': 3, 'CSCO': 2, 'NVDA': 2, 'AAPL': 2, 'AMZN': 1, 'GOOG': 1, 'ADBE': 1}`

### top2_bottom2

- Long counts: `{'PLTR': 8, 'MU': 4, 'TSLA': 4, 'INTC': 4, 'ORCL': 3, 'SNPS': 1}`
- Short counts: `{'CSCO': 7, 'MSFT': 6, 'GOOG': 3, 'AAPL': 3, 'NVDA': 2, 'CRM': 1, 'AMZN': 1, 'ADBE': 1}`

### top3_bottom3

- Long counts: `{'PLTR': 9, 'INTC': 8, 'MU': 6, 'TSLA': 5, 'ORCL': 3, 'LRCX': 2, 'NVDA': 1, 'AVGO': 1, 'SNPS': 1}`
- Short counts: `{'MSFT': 8, 'CSCO': 7, 'GOOG': 4, 'ADBE': 4, 'AAPL': 4, 'CRM': 3, 'NVDA': 3, 'AMZN': 2, 'NOW': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 12 | 0.090521 | 66.67% | `{'PLTR': 7, 'MU': 3, 'ORCL': 1, 'INTC': 1}` |
| 2 | 12 | 0.077268 | 50.00% | `{'TSLA': 4, 'INTC': 3, 'ORCL': 2, 'MU': 1, 'PLTR': 1}` |
| 3 | 12 | 0.072010 | 66.67% | `{'INTC': 4, 'MU': 2, 'LRCX': 2, 'NVDA': 1, 'AVGO': 1}` |
| 4 | 12 | 0.135436 | 75.00% | `{'MU': 4, 'AMD': 3, 'TSLA': 1, 'AVGO': 1, 'ORCL': 1}` |
| 5 | 12 | 0.095757 | 66.67% | `{'MU': 2, 'AMD': 2, 'INTC': 1, 'NVDA': 1, 'AVGO': 1}` |
| 6 | 12 | 0.024994 | 50.00% | `{'AVGO': 3, 'NVDA': 2, 'ORCL': 2, 'INTC': 1, 'SNPS': 1}` |
| 7 | 12 | 0.076083 | 66.67% | `{'AMD': 4, 'LRCX': 2, 'TSLA': 2, 'NVDA': 1, 'INTC': 1}` |
| 8 | 12 | 0.103571 | 75.00% | `{'LRCX': 5, 'TSLA': 2, 'ORCL': 1, 'NOW': 1, 'AMD': 1}` |
| 9 | 12 | 0.069245 | 75.00% | `{'AMAT': 5, 'ADBE': 1, 'NFLX': 1, 'NOW': 1, 'INTC': 1}` |
| 10 | 12 | 0.076087 | 66.67% | `{'AVGO': 3, 'ORCL': 2, 'SNPS': 2, 'LRCX': 1, 'AMD': 1}` |
| 11 | 12 | 0.010186 | 41.67% | `{'QCOM': 3, 'AMAT': 2, 'AVGO': 2, 'NFLX': 1, 'SNPS': 1}` |
| 12 | 12 | -0.012747 | 41.67% | `{'PANW': 3, 'NOW': 2, 'AAPL': 1, 'TXN': 1, 'GOOG': 1}` |
| 13 | 12 | 0.014696 | 50.00% | `{'TXN': 4, 'QCOM': 2, 'CRM': 2, 'NOW': 1, 'AAPL': 1}` |
| 14 | 12 | 0.046440 | 58.33% | `{'QCOM': 4, 'NFLX': 3, 'AMAT': 2, 'TXN': 2, 'ADBE': 1}` |
| 15 | 12 | 0.012809 | 50.00% | `{'PANW': 3, 'NFLX': 2, 'ADBE': 2, 'TXN': 1, 'ORCL': 1}` |
| 16 | 12 | -0.024562 | 41.67% | `{'NFLX': 3, 'PANW': 3, 'ADBE': 2, 'META': 2, 'AAPL': 1}` |
| 17 | 12 | 0.000333 | 41.67% | `{'AMZN': 3, 'SNPS': 2, 'AAPL': 2, 'META': 2, 'TXN': 1}` |
| 18 | 12 | 0.041697 | 91.67% | `{'AMZN': 3, 'META': 2, 'PANW': 1, 'MSFT': 1, 'SNPS': 1}` |
| 19 | 12 | 0.026017 | 66.67% | `{'AMZN': 3, 'GOOG': 2, 'PANW': 2, 'ADBE': 1, 'META': 1}` |
| 20 | 12 | 0.050733 | 66.67% | `{'META': 3, 'CSCO': 3, 'CRM': 2, 'NOW': 1, 'AMZN': 1}` |
| 21 | 12 | 0.029139 | 66.67% | `{'MSFT': 2, 'NOW': 2, 'GOOG': 2, 'CSCO': 2, 'CRM': 1}` |
| 22 | 12 | 0.000894 | 33.33% | `{'ADBE': 3, 'CRM': 2, 'MSFT': 2, 'AMZN': 1, 'GOOG': 1}` |
| 23 | 12 | 0.038458 | 83.33% | `{'CSCO': 5, 'MSFT': 3, 'GOOG': 2, 'CRM': 1, 'AAPL': 1}` |
| 24 | 12 | 0.024556 | 58.33% | `{'MSFT': 3, 'CSCO': 2, 'NVDA': 2, 'AAPL': 2, 'AMZN': 1}` |
