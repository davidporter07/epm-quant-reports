# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_20251230_smoke_1c_1e_date_excess_topmono_shadow_log.parquet`
- Trade days: 1
- Window: 2025-11-13 -> 2025-11-13

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.044556 | 0.033942 | 0.054802 | 0.099358 | 100.00% | 0.00% | 1 | 0 |
| top2_bottom2 | 0.023438 | 0.012825 | 0.055658 | 0.079096 | 100.00% | 0.00% | 1 | 0 |
| top3_bottom3 | 0.037139 | 0.026525 | 0.058207 | 0.095346 | 100.00% | 0.00% | 1 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'INTC': 1}`
- Short counts: `{'MSFT': 1}`

### top2_bottom2

- Long counts: `{'INTC': 1, 'MU': 1}`
- Short counts: `{'NVDA': 1, 'MSFT': 1}`

### top3_bottom3

- Long counts: `{'INTC': 1, 'MU': 1, 'PLTR': 1}`
- Short counts: `{'AMZN': 1, 'NVDA': 1, 'MSFT': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 1 | 0.044556 | 100.00% | `{'INTC': 1}` |
| 2 | 1 | 0.002321 | 100.00% | `{'MU': 1}` |
| 3 | 1 | 0.064540 | 100.00% | `{'PLTR': 1}` |
| 4 | 1 | 0.073379 | 100.00% | `{'LRCX': 1}` |
| 5 | 1 | -0.162849 | 0.00% | `{'AMD': 1}` |
| 6 | 1 | -0.150067 | 0.00% | `{'ORCL': 1}` |
| 7 | 1 | 0.154190 | 100.00% | `{'SNPS': 1}` |
| 8 | 1 | 0.182393 | 100.00% | `{'TSLA': 1}` |
| 9 | 1 | 0.172701 | 100.00% | `{'AMAT': 1}` |
| 10 | 1 | 0.108920 | 100.00% | `{'GOOG': 1}` |
| 11 | 1 | -0.000500 | 0.00% | `{'AVGO': 1}` |
| 12 | 1 | 0.032527 | 100.00% | `{'QCOM': 1}` |
| 13 | 1 | 0.097023 | 100.00% | `{'TXN': 1}` |
| 14 | 1 | -0.092250 | 0.00% | `{'PANW': 1}` |
| 15 | 1 | 0.058853 | 100.00% | `{'CRM': 1}` |
| 16 | 1 | -0.187597 | 0.00% | `{'NFLX': 1}` |
| 17 | 1 | 0.004250 | 100.00% | `{'AAPL': 1}` |
| 18 | 1 | 0.052608 | 100.00% | `{'ADBE': 1}` |
| 19 | 1 | 0.011243 | 100.00% | `{'CSCO': 1}` |
| 20 | 1 | -0.099436 | 0.00% | `{'NOW': 1}` |
| 21 | 1 | 0.062549 | 100.00% | `{'META': 1}` |
| 22 | 1 | -0.063305 | 0.00% | `{'AMZN': 1}` |
| 23 | 1 | -0.056514 | 0.00% | `{'NVDA': 1}` |
| 24 | 1 | -0.054802 | 0.00% | `{'MSFT': 1}` |
