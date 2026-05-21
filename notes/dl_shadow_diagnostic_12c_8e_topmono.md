# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_topmono_shadow_log.parquet`
- Trade days: 12
- Window: 2025-04-28 -> 2026-03-30

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.044331 | 0.007845 | -0.028788 | 0.015543 | 50.00% | -20.11% | 12 | 0 |
| top2_bottom2 | 0.029965 | -0.006521 | -0.042601 | -0.012636 | 41.67% | -18.48% | 12 | 0 |
| top3_bottom3 | 0.041828 | 0.005342 | -0.044852 | -0.003024 | 50.00% | -12.92% | 12 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'TSLA': 9, 'AAPL': 1, 'NVDA': 1, 'MSFT': 1}`
- Short counts: `{'MSFT': 9, 'NVDA': 1, 'AAPL': 1, 'GOOG': 1}`

### top2_bottom2

- Long counts: `{'TSLA': 11, 'NVDA': 4, 'META': 3, 'GOOG': 3, 'AAPL': 2, 'MSFT': 1}`
- Short counts: `{'MSFT': 11, 'AAPL': 8, 'META': 2, 'GOOG': 2, 'NVDA': 1}`

### top3_bottom3

- Long counts: `{'TSLA': 11, 'NVDA': 9, 'META': 7, 'GOOG': 5, 'AAPL': 2, 'AMZN': 1, 'MSFT': 1}`
- Short counts: `{'MSFT': 11, 'AAPL': 9, 'GOOG': 6, 'AMZN': 5, 'NVDA': 3, 'META': 2}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 12 | 0.044331 | 58.33% | `{'TSLA': 9, 'AAPL': 1, 'NVDA': 1, 'MSFT': 1}` |
| 2 | 12 | 0.015599 | 50.00% | `{'NVDA': 3, 'META': 3, 'GOOG': 3, 'TSLA': 2, 'AAPL': 1}` |
| 3 | 12 | 0.065554 | 66.67% | `{'NVDA': 5, 'META': 4, 'GOOG': 2, 'AMZN': 1}` |
| 4 | 12 | -0.004635 | 58.33% | `{'AMZN': 6, 'META': 3, 'GOOG': 1, 'AAPL': 1, 'TSLA': 1}` |
| 5 | 12 | 0.049352 | 66.67% | `{'AMZN': 5, 'GOOG': 4, 'NVDA': 2, 'AAPL': 1}` |
| 6 | 12 | 0.056414 | 83.33% | `{'AAPL': 7, 'META': 2, 'MSFT': 2, 'GOOG': 1}` |
| 7 | 12 | 0.028788 | 58.33% | `{'MSFT': 9, 'NVDA': 1, 'AAPL': 1, 'GOOG': 1}` |
