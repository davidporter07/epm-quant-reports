# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_3c_3e_feature_probe_sector_earnings_shadow_log.parquet`
- Trade days: 3
- Window: 2026-01-15 -> 2026-03-18

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.150672 | 0.133689 | 0.012862 | 0.163535 | 100.00% | 0.00% | 3 | 0 |
| top2_bottom2 | 0.093807 | 0.076823 | -0.003894 | 0.089913 | 66.67% | 0.00% | 3 | 0 |
| top3_bottom3 | 0.062285 | 0.045302 | -0.003315 | 0.058970 | 66.67% | 0.00% | 3 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'INTC': 3}`
- Short counts: `{'MSFT': 1, 'TSLA': 1, 'AMAT': 1}`

### top2_bottom2

- Long counts: `{'INTC': 3, 'PLTR': 1, 'MU': 1, 'TXN': 1}`
- Short counts: `{'TSLA': 2, 'META': 1, 'MSFT': 1, 'GOOG': 1, 'AMAT': 1}`

### top3_bottom3

- Long counts: `{'INTC': 3, 'PLTR': 3, 'AMD': 1, 'MU': 1, 'TXN': 1}`
- Short counts: `{'GOOG': 3, 'MSFT': 2, 'TSLA': 2, 'META': 1, 'AMAT': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 3 | 0.150672 | 33.33% | `{'INTC': 3}` |
| 2 | 3 | 0.036941 | 66.67% | `{'PLTR': 1, 'MU': 1, 'TXN': 1}` |
| 3 | 3 | -0.000758 | 33.33% | `{'PLTR': 2, 'AMD': 1}` |
| 4 | 3 | 0.010234 | 33.33% | `{'MU': 1, 'ORCL': 1, 'NOW': 1}` |
| 5 | 3 | -0.054229 | 33.33% | `{'NFLX': 1, 'TXN': 1, 'CSCO': 1}` |
| 6 | 3 | -0.068810 | 33.33% | `{'ORCL': 1, 'LRCX': 1, 'NFLX': 1}` |
| 7 | 3 | 0.017147 | 33.33% | `{'LRCX': 1, 'AMD': 1, 'MU': 1}` |
| 8 | 3 | 0.089502 | 66.67% | `{'TXN': 1, 'NOW': 1, 'ADBE': 1}` |
| 9 | 3 | 0.059497 | 33.33% | `{'NOW': 1, 'NVDA': 1, 'AMD': 1}` |
| 10 | 3 | 0.064251 | 66.67% | `{'QCOM': 1, 'NFLX': 1, 'MSFT': 1}` |
| 11 | 3 | -0.025130 | 66.67% | `{'PANW': 1, 'CSCO': 1, 'QCOM': 1}` |
| 12 | 3 | 0.014785 | 66.67% | `{'CSCO': 1, 'AMAT': 1, 'SNPS': 1}` |
| 13 | 3 | 0.096791 | 100.00% | `{'AMAT': 1, 'SNPS': 1, 'ORCL': 1}` |
| 14 | 3 | 0.034460 | 33.33% | `{'NVDA': 1, 'QCOM': 1, 'AMZN': 1}` |
| 15 | 3 | -0.072250 | 33.33% | `{'CRM': 3}` |
| 16 | 3 | -0.037427 | 33.33% | `{'ADBE': 1, 'AVGO': 1, 'AAPL': 1}` |
| 17 | 3 | 0.052768 | 66.67% | `{'AAPL': 1, 'ADBE': 1, 'LRCX': 1}` |
| 18 | 3 | -0.047629 | 33.33% | `{'PANW': 2, 'SNPS': 1}` |
| 19 | 3 | 0.000475 | 33.33% | `{'TSLA': 1, 'AAPL': 1, 'NVDA': 1}` |
| 20 | 3 | 0.043719 | 66.67% | `{'AVGO': 1, 'AMZN': 1, 'META': 1}` |
| 21 | 3 | 0.032642 | 33.33% | `{'AMZN': 1, 'META': 1, 'AVGO': 1}` |
| 22 | 3 | 0.002158 | 33.33% | `{'GOOG': 2, 'MSFT': 1}` |
| 23 | 3 | 0.020650 | 100.00% | `{'META': 1, 'GOOG': 1, 'TSLA': 1}` |
| 24 | 3 | -0.012862 | 33.33% | `{'MSFT': 1, 'TSLA': 1, 'AMAT': 1}` |
