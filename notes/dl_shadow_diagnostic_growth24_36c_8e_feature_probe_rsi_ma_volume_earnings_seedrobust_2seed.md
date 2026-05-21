# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_shadow_log.parquet`
- Trade days: 36
- Window: 2023-04-12 -> 2026-03-18

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.127720 | 0.095395 | -0.012040 | 0.115680 | 72.22% | -31.70% | 36 | 0 |
| top2_bottom2 | 0.087644 | 0.055320 | -0.017376 | 0.070268 | 69.44% | -22.27% | 36 | 0 |
| top3_bottom3 | 0.075650 | 0.043325 | -0.020872 | 0.054778 | 63.89% | -29.61% | 36 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'PLTR': 27, 'AMD': 4, 'INTC': 3, 'NFLX': 1, 'MU': 1}`
- Short counts: `{'SNPS': 8, 'META': 5, 'TSLA': 4, 'MSFT': 3, 'AMAT': 2, 'AAPL': 2, 'INTC': 2, 'ADBE': 2, 'AMZN': 2, 'MU': 2, 'AVGO': 2, 'LRCX': 1, 'TXN': 1}`

### top2_bottom2

- Long counts: `{'PLTR': 32, 'NVDA': 9, 'INTC': 9, 'TSLA': 7, 'AMD': 5, 'NFLX': 4, 'MU': 3, 'PANW': 1, 'CSCO': 1, 'ADBE': 1}`
- Short counts: `{'SNPS': 13, 'META': 8, 'ADBE': 7, 'TSLA': 7, 'MSFT': 6, 'AMAT': 5, 'TXN': 3, 'CRM': 3, 'AVGO': 3, 'GOOG': 3, 'ORCL': 2, 'AAPL': 2, 'INTC': 2, 'CSCO': 2, 'AMZN': 2, 'MU': 2, 'LRCX': 1, 'QCOM': 1}`

### top3_bottom3

- Long counts: `{'PLTR': 32, 'INTC': 15, 'NVDA': 12, 'MU': 11, 'NFLX': 10, 'AMD': 9, 'TSLA': 7, 'ADBE': 4, 'CSCO': 3, 'LRCX': 2, 'META': 1, 'PANW': 1, 'QCOM': 1}`
- Short counts: `{'SNPS': 15, 'ADBE': 13, 'MSFT': 11, 'META': 9, 'CRM': 7, 'AMAT': 7, 'TSLA': 7, 'GOOG': 6, 'LRCX': 4, 'TXN': 4, 'AAPL': 4, 'ORCL': 3, 'CSCO': 3, 'AMZN': 3, 'MU': 3, 'AVGO': 3, 'INTC': 2, 'QCOM': 2, 'NOW': 1, 'AMD': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 36 | 0.127720 | 66.67% | `{'PLTR': 27, 'AMD': 4, 'INTC': 3, 'NFLX': 1, 'MU': 1}` |
| 2 | 36 | 0.047568 | 55.56% | `{'NVDA': 9, 'TSLA': 7, 'INTC': 6, 'PLTR': 5, 'NFLX': 3}` |
| 3 | 36 | 0.051661 | 58.33% | `{'MU': 8, 'NFLX': 6, 'INTC': 6, 'AMD': 4, 'NVDA': 3}` |
| 4 | 36 | 0.018676 | 55.56% | `{'NVDA': 6, 'AMD': 6, 'MU': 5, 'NFLX': 4, 'CRM': 3}` |
| 5 | 36 | 0.014531 | 61.11% | `{'NVDA': 6, 'INTC': 4, 'AMD': 3, 'TXN': 3, 'MSFT': 3}` |
| 6 | 36 | 0.031413 | 58.33% | `{'TSLA': 5, 'LRCX': 5, 'INTC': 4, 'CSCO': 3, 'NFLX': 3}` |
| 7 | 36 | 0.035724 | 61.11% | `{'MU': 4, 'ORCL': 4, 'NFLX': 4, 'AVGO': 3, 'PANW': 3}` |
| 8 | 36 | 0.044277 | 69.44% | `{'CSCO': 4, 'NOW': 3, 'TSLA': 3, 'SNPS': 3, 'INTC': 2}` |
| 9 | 36 | 0.011933 | 52.78% | `{'NFLX': 4, 'AAPL': 3, 'LRCX': 3, 'QCOM': 3, 'ORCL': 3}` |
| 10 | 36 | 0.036084 | 61.11% | `{'QCOM': 5, 'AVGO': 5, 'AMAT': 4, 'PANW': 3, 'TXN': 2}` |
| 11 | 36 | 0.034843 | 63.89% | `{'PANW': 4, 'QCOM': 4, 'ORCL': 4, 'LRCX': 3, 'AVGO': 3}` |
| 12 | 36 | 0.054922 | 77.78% | `{'AMD': 5, 'QCOM': 5, 'AVGO': 3, 'TXN': 3, 'ADBE': 3}` |
| 13 | 36 | 0.013667 | 52.78% | `{'NOW': 6, 'AMZN': 4, 'PANW': 4, 'CSCO': 3, 'ORCL': 3}` |
| 14 | 36 | 0.018221 | 63.89% | `{'GOOG': 5, 'ORCL': 3, 'CSCO': 3, 'AVGO': 3, 'LRCX': 2}` |
| 15 | 36 | 0.030453 | 69.44% | `{'AMAT': 4, 'PANW': 4, 'AMZN': 4, 'GOOG': 3, 'AVGO': 3}` |
| 16 | 36 | 0.021833 | 52.78% | `{'AMZN': 7, 'GOOG': 5, 'PANW': 4, 'NOW': 4, 'QCOM': 4}` |
| 17 | 36 | 0.031331 | 55.56% | `{'META': 4, 'AMZN': 4, 'AMAT': 4, 'AAPL': 4, 'ADBE': 3}` |
| 18 | 36 | 0.026787 | 63.89% | `{'AAPL': 7, 'NOW': 4, 'QCOM': 3, 'META': 3, 'NFLX': 2}` |
| 19 | 36 | 0.029055 | 55.56% | `{'CRM': 6, 'MSFT': 4, 'AMZN': 3, 'NOW': 3, 'TXN': 3}` |
| 20 | 36 | 0.022222 | 55.56% | `{'CRM': 6, 'TXN': 3, 'MSFT': 3, 'META': 3, 'LRCX': 3}` |
| 21 | 36 | 0.016286 | 55.56% | `{'MSFT': 5, 'AAPL': 3, 'CRM': 3, 'MU': 2, 'AVGO': 2}` |
| 22 | 36 | 0.022168 | 61.11% | `{'ADBE': 8, 'CRM': 5, 'MSFT': 4, 'GOOG': 3, 'AMAT': 2}` |
| 23 | 36 | 0.022969 | 69.44% | `{'SNPS': 6, 'META': 4, 'ADBE': 4, 'MSFT': 3, 'TSLA': 3}` |
| 24 | 30 | 0.012360 | 53.33% | `{'SNPS': 7, 'META': 4, 'MSFT': 3, 'TSLA': 3, 'AMAT': 2}` |
