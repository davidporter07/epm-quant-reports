# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\rank_head_blind_loop_12c_8e_topmono_shadow_log.parquet`
- Trade days: 12
- Window: 2025-04-28 -> 2026-03-30

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.028698 | -0.007788 | -0.023582 | 0.005116 | 58.33% | -29.00% | 12 | 0 |
| top2_bottom2 | 0.030181 | -0.006306 | -0.052154 | -0.021973 | 41.67% | -21.48% | 12 | 0 |
| top3_bottom3 | 0.022377 | -0.014109 | -0.043825 | -0.021448 | 33.33% | -15.23% | 12 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'TSLA': 4, 'META': 3, 'NVDA': 2, 'AAPL': 1, 'GOOG': 1, 'MSFT': 1}`
- Short counts: `{'MSFT': 4, 'NVDA': 3, 'AAPL': 3, 'GOOG': 1, 'TSLA': 1}`

### top2_bottom2

- Long counts: `{'TSLA': 7, 'META': 7, 'GOOG': 3, 'AAPL': 2, 'NVDA': 2, 'MSFT': 2, 'AMZN': 1}`
- Short counts: `{'AAPL': 7, 'MSFT': 5, 'GOOG': 4, 'NVDA': 3, 'AMZN': 3, 'META': 1, 'TSLA': 1}`

### top3_bottom3

- Long counts: `{'TSLA': 9, 'META': 7, 'AMZN': 6, 'GOOG': 5, 'AAPL': 4, 'MSFT': 3, 'NVDA': 2}`
- Short counts: `{'MSFT': 8, 'NVDA': 8, 'AAPL': 8, 'AMZN': 5, 'GOOG': 4, 'TSLA': 2, 'META': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 12 | 0.028698 | 58.33% | `{'TSLA': 4, 'META': 3, 'NVDA': 2, 'AAPL': 1, 'GOOG': 1}` |
| 2 | 12 | 0.031663 | 58.33% | `{'META': 4, 'TSLA': 3, 'GOOG': 2, 'AAPL': 1, 'AMZN': 1}` |
| 3 | 12 | 0.006770 | 66.67% | `{'AMZN': 5, 'GOOG': 2, 'AAPL': 2, 'TSLA': 2, 'MSFT': 1}` |
| 4 | 12 | 0.056796 | 75.00% | `{'META': 4, 'GOOG': 3, 'NVDA': 2, 'AMZN': 1, 'TSLA': 1}` |
| 5 | 12 | 0.027168 | 58.33% | `{'NVDA': 5, 'MSFT': 3, 'AMZN': 2, 'TSLA': 1, 'AAPL': 1}` |
| 6 | 12 | 0.080726 | 75.00% | `{'AAPL': 4, 'AMZN': 3, 'GOOG': 3, 'META': 1, 'MSFT': 1}` |
| 7 | 12 | 0.023582 | 50.00% | `{'MSFT': 4, 'NVDA': 3, 'AAPL': 3, 'GOOG': 1, 'TSLA': 1}` |
