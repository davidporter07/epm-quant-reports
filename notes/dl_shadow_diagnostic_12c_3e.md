# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_3e_shadow_log.parquet`
- Trade days: 12
- Window: 2025-04-28 -> 2026-03-30

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.031025 | -0.005461 | -0.018830 | 0.012196 | 41.67% | -35.28% | 12 | 0 |
| top2_bottom2 | 0.015567 | -0.020919 | -0.032204 | -0.016637 | 50.00% | -30.90% | 12 | 0 |
| top3_bottom3 | 0.028553 | -0.007933 | -0.043867 | -0.015314 | 33.33% | -24.45% | 12 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'TSLA': 8, 'AMZN': 2, 'NVDA': 1, 'META': 1}`
- Short counts: `{'NVDA': 3, 'AAPL': 3, 'MSFT': 3, 'AMZN': 1, 'GOOG': 1, 'TSLA': 1}`

### top2_bottom2

- Long counts: `{'TSLA': 10, 'META': 4, 'AMZN': 3, 'AAPL': 2, 'NVDA': 2, 'GOOG': 2, 'MSFT': 1}`
- Short counts: `{'MSFT': 7, 'AAPL': 6, 'NVDA': 4, 'AMZN': 3, 'GOOG': 3, 'TSLA': 1}`

### top3_bottom3

- Long counts: `{'TSLA': 11, 'META': 11, 'AMZN': 6, 'AAPL': 2, 'MSFT': 2, 'NVDA': 2, 'GOOG': 2}`
- Short counts: `{'GOOG': 9, 'NVDA': 8, 'MSFT': 8, 'AAPL': 7, 'AMZN': 3, 'TSLA': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 12 | 0.031025 | 41.67% | `{'TSLA': 8, 'AMZN': 2, 'NVDA': 1, 'META': 1}` |
| 2 | 12 | 0.000108 | 50.00% | `{'META': 3, 'AAPL': 2, 'TSLA': 2, 'GOOG': 2, 'NVDA': 1}` |
| 3 | 12 | 0.054526 | 83.33% | `{'META': 7, 'AMZN': 3, 'MSFT': 1, 'TSLA': 1}` |
| 4 | 12 | 0.038142 | 66.67% | `{'AAPL': 3, 'AMZN': 3, 'MSFT': 2, 'NVDA': 2, 'GOOG': 1}` |
| 5 | 12 | 0.067194 | 83.33% | `{'GOOG': 6, 'NVDA': 4, 'AAPL': 1, 'MSFT': 1}` |
| 6 | 12 | 0.045578 | 58.33% | `{'MSFT': 4, 'AAPL': 3, 'AMZN': 2, 'GOOG': 2, 'NVDA': 1}` |
| 7 | 12 | 0.018830 | 58.33% | `{'NVDA': 3, 'AAPL': 3, 'MSFT': 3, 'AMZN': 1, 'GOOG': 1}` |
