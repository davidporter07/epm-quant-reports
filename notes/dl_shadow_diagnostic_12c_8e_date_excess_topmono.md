# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_date_excess_topmono_shadow_log.parquet`
- Trade days: 12
- Window: 2025-04-28 -> 2026-03-30

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.043322 | 0.006836 | -0.024776 | 0.018546 | 50.00% | -21.22% | 12 | 0 |
| top2_bottom2 | 0.045558 | 0.009071 | -0.039675 | 0.005882 | 66.67% | -18.48% | 12 | 0 |
| top3_bottom3 | 0.032245 | -0.004241 | -0.045954 | -0.013710 | 33.33% | -18.74% | 12 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'TSLA': 10, 'NVDA': 2}`
- Short counts: `{'MSFT': 9, 'AAPL': 3}`

### top2_bottom2

- Long counts: `{'TSLA': 11, 'NVDA': 5, 'META': 4, 'GOOG': 3, 'AAPL': 1}`
- Short counts: `{'MSFT': 11, 'AAPL': 9, 'GOOG': 2, 'META': 1, 'NVDA': 1}`

### top3_bottom3

- Long counts: `{'TSLA': 12, 'NVDA': 8, 'META': 8, 'GOOG': 3, 'AMZN': 3, 'AAPL': 2}`
- Short counts: `{'MSFT': 11, 'AAPL': 9, 'GOOG': 7, 'AMZN': 4, 'NVDA': 3, 'META': 2}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 12 | 0.043322 | 50.00% | `{'TSLA': 10, 'NVDA': 2}` |
| 2 | 12 | 0.047793 | 66.67% | `{'META': 4, 'NVDA': 3, 'GOOG': 3, 'AAPL': 1, 'TSLA': 1}` |
| 3 | 12 | 0.005619 | 58.33% | `{'META': 4, 'NVDA': 3, 'AMZN': 3, 'AAPL': 1, 'TSLA': 1}` |
| 4 | 12 | 0.020807 | 66.67% | `{'AMZN': 5, 'GOOG': 2, 'META': 2, 'AAPL': 1, 'NVDA': 1}` |
| 5 | 12 | 0.058513 | 66.67% | `{'GOOG': 5, 'AMZN': 4, 'NVDA': 2, 'META': 1}` |
| 6 | 12 | 0.054574 | 66.67% | `{'AAPL': 6, 'GOOG': 2, 'MSFT': 2, 'META': 1, 'NVDA': 1}` |
| 7 | 12 | 0.024776 | 66.67% | `{'MSFT': 9, 'AAPL': 3}` |
