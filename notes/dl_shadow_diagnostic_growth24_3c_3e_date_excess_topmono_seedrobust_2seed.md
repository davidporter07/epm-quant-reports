# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_3c_3e_date_excess_topmono_seedrobust_2seed_shadow_log.parquet`
- Trade days: 3
- Window: 2026-01-15 -> 2026-03-18

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.109515 | 0.092532 | 0.011514 | 0.121029 | 66.67% | -9.52% | 3 | 0 |
| top2_bottom2 | 0.096013 | 0.079030 | 0.003228 | 0.099241 | 100.00% | 0.00% | 3 | 0 |
| top3_bottom3 | 0.075296 | 0.058312 | -0.006630 | 0.068665 | 66.67% | 0.00% | 3 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'MU': 3}`
- Short counts: `{'GOOG': 1, 'NVDA': 1, 'AAPL': 1}`

### top2_bottom2

- Long counts: `{'MU': 3, 'INTC': 2, 'PLTR': 1}`
- Short counts: `{'NVDA': 2, 'AAPL': 2, 'GOOG': 1, 'MSFT': 1}`

### top3_bottom3

- Long counts: `{'MU': 3, 'INTC': 3, 'LRCX': 2, 'PLTR': 1}`
- Short counts: `{'AAPL': 3, 'NVDA': 2, 'GOOG': 2, 'QCOM': 1, 'MSFT': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 3 | 0.109515 | 66.67% | `{'MU': 3}` |
| 2 | 3 | 0.082511 | 33.33% | `{'INTC': 2, 'PLTR': 1}` |
| 3 | 3 | 0.033861 | 33.33% | `{'LRCX': 2, 'INTC': 1}` |
| 4 | 3 | -0.026281 | 33.33% | `{'AMAT': 2, 'ORCL': 1}` |
| 5 | 3 | 0.073023 | 33.33% | `{'SNPS': 1, 'ORCL': 1, 'AMD': 1}` |
| 6 | 3 | 0.081374 | 66.67% | `{'AMD': 1, 'PLTR': 1, 'TXN': 1}` |
| 7 | 3 | -0.073783 | 33.33% | `{'LRCX': 1, 'TXN': 1, 'NOW': 1}` |
| 8 | 3 | -0.041098 | 0.00% | `{'TSLA': 1, 'AMD': 1, 'PLTR': 1}` |
| 9 | 3 | -0.020264 | 66.67% | `{'SNPS': 2, 'NFLX': 1}` |
| 10 | 3 | 0.076993 | 66.67% | `{'AMAT': 1, 'TSLA': 1, 'ORCL': 1}` |
| 11 | 3 | 0.021019 | 66.67% | `{'AVGO': 1, 'NOW': 1, 'TSLA': 1}` |
| 12 | 3 | 0.115031 | 66.67% | `{'TXN': 1, 'AVGO': 1, 'AMZN': 1}` |
| 13 | 3 | 0.042361 | 66.67% | `{'CRM': 1, 'NFLX': 1, 'GOOG': 1}` |
| 14 | 3 | -0.102829 | 0.00% | `{'NOW': 1, 'ADBE': 1, 'CRM': 1}` |
| 15 | 3 | 0.067270 | 100.00% | `{'META': 1, 'CRM': 1, 'CSCO': 1}` |
| 16 | 3 | 0.036629 | 33.33% | `{'ADBE': 1, 'META': 1, 'AVGO': 1}` |
| 17 | 3 | 0.003959 | 66.67% | `{'QCOM': 1, 'CSCO': 1, 'META': 1}` |
| 18 | 3 | -0.069097 | 33.33% | `{'AMZN': 1, 'QCOM': 1, 'NFLX': 1}` |
| 19 | 3 | -0.030664 | 33.33% | `{'PANW': 2, 'AMZN': 1}` |
| 20 | 3 | -0.049258 | 0.00% | `{'MSFT': 2, 'ADBE': 1}` |
| 21 | 3 | 0.057437 | 100.00% | `{'CSCO': 1, 'PANW': 1, 'NVDA': 1}` |
| 22 | 3 | 0.026346 | 100.00% | `{'AAPL': 1, 'GOOG': 1, 'QCOM': 1}` |
| 23 | 3 | 0.005059 | 33.33% | `{'NVDA': 1, 'AAPL': 1, 'MSFT': 1}` |
| 24 | 3 | -0.011514 | 33.33% | `{'GOOG': 1, 'NVDA': 1, 'AAPL': 1}` |
