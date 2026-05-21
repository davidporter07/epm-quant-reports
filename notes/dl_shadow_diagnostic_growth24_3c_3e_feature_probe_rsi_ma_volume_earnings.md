# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_3c_3e_feature_probe_rsi_ma_volume_earnings_shadow_log.parquet`
- Trade days: 3
- Window: 2026-01-15 -> 2026-03-18

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.189061 | 0.172078 | 0.031604 | 0.220665 | 100.00% | 0.00% | 3 | 0 |
| top2_bottom2 | 0.075479 | 0.058496 | 0.011154 | 0.086634 | 66.67% | 0.00% | 3 | 0 |
| top3_bottom3 | 0.093455 | 0.076472 | 0.017646 | 0.111101 | 100.00% | 0.00% | 3 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'AMD': 1, 'MU': 1, 'INTC': 1}`
- Short counts: `{'SNPS': 1, 'TSLA': 1, 'META': 1}`

### top2_bottom2

- Long counts: `{'PLTR': 2, 'MU': 2, 'AMD': 1, 'INTC': 1}`
- Short counts: `{'INTC': 1, 'SNPS': 1, 'ORCL': 1, 'TSLA': 1, 'MSFT': 1, 'META': 1}`

### top3_bottom3

- Long counts: `{'MU': 3, 'PLTR': 2, 'AMD': 1, 'CSCO': 1, 'INTC': 1, 'LRCX': 1}`
- Short counts: `{'ORCL': 2, 'SNPS': 2, 'INTC': 1, 'TSLA': 1, 'AAPL': 1, 'MSFT': 1, 'META': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 3 | 0.189061 | 66.67% | `{'AMD': 1, 'MU': 1, 'INTC': 1}` |
| 2 | 3 | -0.038103 | 33.33% | `{'PLTR': 2, 'MU': 1}` |
| 3 | 3 | 0.129407 | 100.00% | `{'MU': 1, 'CSCO': 1, 'LRCX': 1}` |
| 4 | 3 | 0.081773 | 33.33% | `{'NFLX': 1, 'INTC': 1, 'AMD': 1}` |
| 5 | 3 | 0.007896 | 33.33% | `{'LRCX': 1, 'AMD': 1, 'PLTR': 1}` |
| 6 | 3 | 0.039122 | 66.67% | `{'CSCO': 1, 'AAPL': 1, 'ORCL': 1}` |
| 7 | 3 | 0.104113 | 66.67% | `{'TXN': 1, 'NVDA': 1, 'AMAT': 1}` |
| 8 | 3 | -0.165733 | 0.00% | `{'NOW': 2, 'TXN': 1}` |
| 9 | 3 | 0.042755 | 33.33% | `{'QCOM': 1, 'LRCX': 1, 'AVGO': 1}` |
| 10 | 3 | -0.052330 | 33.33% | `{'PANW': 1, 'ADBE': 1, 'NFLX': 1}` |
| 11 | 3 | 0.123582 | 100.00% | `{'AAPL': 1, 'NFLX': 1, 'NVDA': 1}` |
| 12 | 3 | 0.022032 | 66.67% | `{'AMAT': 1, 'QCOM': 1, 'TSLA': 1}` |
| 13 | 3 | 0.044924 | 66.67% | `{'ADBE': 1, 'NOW': 1, 'TXN': 1}` |
| 14 | 3 | -0.061346 | 33.33% | `{'PANW': 2, 'CRM': 1}` |
| 15 | 3 | 0.029111 | 66.67% | `{'NVDA': 1, 'CRM': 1, 'QCOM': 1}` |
| 16 | 3 | -0.067302 | 0.00% | `{'MSFT': 2, 'CRM': 1}` |
| 17 | 3 | 0.009367 | 33.33% | `{'TSLA': 1, 'AMAT': 1, 'CSCO': 1}` |
| 18 | 3 | 0.027254 | 66.67% | `{'AMZN': 3}` |
| 19 | 3 | -0.028934 | 0.00% | `{'AVGO': 2, 'ADBE': 1}` |
| 20 | 3 | 0.014152 | 66.67% | `{'META': 2, 'SNPS': 1}` |
| 21 | 3 | 0.009734 | 66.67% | `{'GOOG': 3}` |
| 22 | 3 | -0.030629 | 66.67% | `{'ORCL': 1, 'SNPS': 1, 'AAPL': 1}` |
| 23 | 3 | 0.009295 | 33.33% | `{'INTC': 1, 'ORCL': 1, 'MSFT': 1}` |
| 24 | 3 | -0.031604 | 33.33% | `{'SNPS': 1, 'TSLA': 1, 'META': 1}` |
