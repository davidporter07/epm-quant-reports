# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_shadow_log.parquet`
- Trade days: 12
- Window: 2025-04-28 -> 2026-03-30

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.053725 | 0.017239 | -0.017477 | 0.036248 | 58.33% | -24.79% | 12 | 0 |
| top2_bottom2 | 0.035377 | -0.001109 | -0.038234 | -0.002857 | 58.33% | -11.54% | 12 | 0 |
| top3_bottom3 | 0.027490 | -0.008996 | -0.045347 | -0.017857 | 41.67% | -19.45% | 12 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'TSLA': 6, 'NVDA': 2, 'AMZN': 2, 'AAPL': 1, 'META': 1}`
- Short counts: `{'AAPL': 4, 'MSFT': 4, 'NVDA': 2, 'AMZN': 1, 'TSLA': 1}`

### top2_bottom2

- Long counts: `{'TSLA': 8, 'META': 5, 'AMZN': 5, 'AAPL': 2, 'NVDA': 2, 'GOOG': 1, 'MSFT': 1}`
- Short counts: `{'MSFT': 8, 'AAPL': 7, 'GOOG': 4, 'NVDA': 2, 'TSLA': 2, 'AMZN': 1}`

### top3_bottom3

- Long counts: `{'META': 10, 'TSLA': 9, 'AMZN': 7, 'GOOG': 3, 'NVDA': 3, 'AAPL': 2, 'MSFT': 2}`
- Short counts: `{'MSFT': 10, 'NVDA': 7, 'GOOG': 7, 'AAPL': 7, 'TSLA': 3, 'META': 1, 'AMZN': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 12 | 0.053725 | 58.33% | `{'TSLA': 6, 'NVDA': 2, 'AMZN': 2, 'AAPL': 1, 'META': 1}` |
| 2 | 12 | 0.017029 | 58.33% | `{'META': 4, 'AMZN': 3, 'TSLA': 2, 'AAPL': 1, 'GOOG': 1}` |
| 3 | 12 | 0.011715 | 66.67% | `{'META': 5, 'GOOG': 2, 'AMZN': 2, 'MSFT': 1, 'NVDA': 1}` |
| 4 | 12 | 0.036893 | 66.67% | `{'AMZN': 4, 'AAPL': 3, 'GOOG': 2, 'NVDA': 2, 'META': 1}` |
| 5 | 12 | 0.059573 | 75.00% | `{'NVDA': 5, 'GOOG': 3, 'MSFT': 2, 'META': 1, 'TSLA': 1}` |
| 6 | 12 | 0.058991 | 58.33% | `{'MSFT': 4, 'GOOG': 4, 'AAPL': 3, 'TSLA': 1}` |
| 7 | 12 | 0.017477 | 58.33% | `{'AAPL': 4, 'MSFT': 4, 'NVDA': 2, 'AMZN': 1, 'TSLA': 1}` |
