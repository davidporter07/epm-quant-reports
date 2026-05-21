# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\growth24_smoke_1c_1e_date_excess_topmono_shadow_log.parquet`
- Trade days: 1
- Window: 2026-03-18 -> 2026-03-18

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.079124 | -0.023523 | -0.108064 | -0.028940 | 0.00% | 0.00% | 1 | 0 |
| top2_bottom2 | 0.098740 | -0.003906 | -0.094622 | 0.004119 | 100.00% | 0.00% | 1 | 0 |
| top3_bottom3 | 0.130454 | 0.027808 | -0.102401 | 0.028053 | 100.00% | 0.00% | 1 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'MSFT': 1}`
- Short counts: `{'GOOG': 1}`

### top2_bottom2

- Long counts: `{'MSFT': 1, 'META': 1}`
- Short counts: `{'AAPL': 1, 'GOOG': 1}`

### top3_bottom3

- Long counts: `{'MSFT': 1, 'META': 1, 'AMZN': 1}`
- Short counts: `{'NVDA': 1, 'AAPL': 1, 'GOOG': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 1 | 0.079124 | 100.00% | `{'MSFT': 1}` |
| 2 | 1 | 0.118357 | 100.00% | `{'META': 1}` |
| 3 | 1 | 0.193882 | 100.00% | `{'AMZN': 1}` |
| 4 | 1 | 0.019960 | 100.00% | `{'TSLA': 1}` |
| 5 | 1 | 0.117960 | 100.00% | `{'NVDA': 1}` |
| 6 | 1 | 0.081180 | 100.00% | `{'AAPL': 1}` |
| 7 | 1 | 0.108064 | 100.00% | `{'GOOG': 1}` |
