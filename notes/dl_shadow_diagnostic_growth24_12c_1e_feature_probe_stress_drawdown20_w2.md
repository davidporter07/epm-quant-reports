# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_12c_1e_feature_probe_stress_drawdown20_w2_shadow_log.parquet`
- Trade days: 12
- Window: 2025-04-15 -> 2026-03-18

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.109244 | 0.065883 | -0.017106 | 0.092139 | 75.00% | -10.80% | 12 | 0 |
| top2_bottom2 | 0.108536 | 0.065174 | 0.008799 | 0.117334 | 66.67% | -2.91% | 12 | 0 |
| top3_bottom3 | 0.104518 | 0.061157 | -0.001280 | 0.103239 | 91.67% | -4.73% | 12 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'INTC': 6, 'PLTR': 3, 'AMD': 2, 'MU': 1}`
- Short counts: `{'MSFT': 5, 'GOOG': 4, 'CSCO': 2, 'AVGO': 1}`

### top2_bottom2

- Long counts: `{'INTC': 9, 'PLTR': 6, 'MU': 5, 'AMD': 3, 'TSLA': 1}`
- Short counts: `{'MSFT': 8, 'GOOG': 4, 'META': 3, 'AMZN': 2, 'CSCO': 2, 'AAPL': 2, 'SNPS': 1, 'NOW': 1, 'AVGO': 1}`

### top3_bottom3

- Long counts: `{'INTC': 12, 'PLTR': 6, 'AMD': 6, 'MU': 6, 'TSLA': 4, 'ORCL': 1, 'NOW': 1}`
- Short counts: `{'MSFT': 8, 'META': 6, 'GOOG': 5, 'AMZN': 3, 'CSCO': 3, 'AVGO': 3, 'CRM': 2, 'SNPS': 2, 'AAPL': 2, 'NOW': 1, 'NVDA': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 12 | 0.109244 | 75.00% | `{'INTC': 6, 'PLTR': 3, 'AMD': 2, 'MU': 1}` |
| 2 | 12 | 0.107827 | 58.33% | `{'MU': 4, 'INTC': 3, 'PLTR': 3, 'TSLA': 1, 'AMD': 1}` |
| 3 | 12 | 0.096483 | 66.67% | `{'AMD': 3, 'TSLA': 3, 'INTC': 3, 'MU': 1, 'ORCL': 1}` |
| 4 | 12 | 0.040315 | 58.33% | `{'MU': 4, 'AMD': 2, 'ORCL': 2, 'LRCX': 2, 'NVDA': 1}` |
| 5 | 12 | 0.117523 | 83.33% | `{'NVDA': 3, 'PLTR': 3, 'ORCL': 2, 'AMD': 1, 'MU': 1}` |
| 6 | 12 | 0.107631 | 58.33% | `{'TSLA': 3, 'LRCX': 3, 'AMD': 2, 'ORCL': 1, 'SNPS': 1}` |
| 7 | 12 | 0.065215 | 66.67% | `{'ORCL': 3, 'NFLX': 3, 'MU': 1, 'LRCX': 1, 'AMD': 1}` |
| 8 | 12 | 0.058778 | 58.33% | `{'AVGO': 3, 'ORCL': 2, 'NVDA': 1, 'TXN': 1, 'AMAT': 1}` |
| 9 | 12 | 0.079819 | 66.67% | `{'PANW': 2, 'AMAT': 2, 'TSLA': 2, 'LRCX': 1, 'AVGO': 1}` |
| 10 | 12 | 0.080572 | 58.33% | `{'NOW': 2, 'AVGO': 2, 'QCOM': 2, 'TXN': 2, 'LRCX': 1}` |
| 11 | 12 | -0.009304 | 41.67% | `{'TXN': 3, 'AMAT': 2, 'PANW': 2, 'NFLX': 2, 'NVDA': 1}` |
| 12 | 12 | -0.022757 | 41.67% | `{'PANW': 3, 'NOW': 2, 'CSCO': 2, 'SNPS': 2, 'QCOM': 1}` |
| 13 | 12 | -0.002951 | 58.33% | `{'CRM': 3, 'AAPL': 2, 'AMAT': 2, 'NOW': 1, 'TXN': 1}` |
| 14 | 12 | 0.031361 | 75.00% | `{'QCOM': 5, 'CRM': 2, 'AMAT': 1, 'AAPL': 1, 'ADBE': 1}` |
| 15 | 12 | 0.026293 | 58.33% | `{'NFLX': 2, 'AMZN': 2, 'CSCO': 2, 'ADBE': 1, 'TXN': 1}` |
| 16 | 12 | 0.016210 | 58.33% | `{'PANW': 3, 'TXN': 2, 'AAPL': 2, 'QCOM': 1, 'NOW': 1}` |
| 17 | 12 | 0.019440 | 58.33% | `{'ADBE': 4, 'CSCO': 2, 'NFLX': 1, 'AAPL': 1, 'PANW': 1}` |
| 18 | 12 | 0.021863 | 58.33% | `{'CSCO': 3, 'SNPS': 2, 'CRM': 2, 'AMZN': 1, 'AAPL': 1}` |
| 19 | 12 | 0.010575 | 58.33% | `{'AMZN': 4, 'GOOG': 2, 'SNPS': 1, 'AAPL': 1, 'NOW': 1}` |
| 20 | 12 | 0.054988 | 75.00% | `{'MSFT': 3, 'ADBE': 2, 'AAPL': 2, 'AMZN': 1, 'SNPS': 1}` |
| 21 | 12 | 0.023943 | 41.67% | `{'CRM': 2, 'META': 2, 'ADBE': 2, 'AVGO': 2, 'AMZN': 2}` |
| 22 | 12 | -0.005507 | 41.67% | `{'META': 4, 'AMZN': 1, 'CSCO': 1, 'CRM': 1, 'SNPS': 1}` |
| 23 | 12 | -0.017575 | 50.00% | `{'MSFT': 4, 'META': 2, 'AAPL': 2, 'CSCO': 1, 'SNPS': 1}` |
| 24 | 8 | 0.018127 | 75.00% | `{'GOOG': 4, 'MSFT': 3, 'CSCO': 1}` |
