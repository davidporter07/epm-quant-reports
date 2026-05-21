# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\rank_head_blind_loop_3c_3e_topmono_shadow_log.parquet`
- Trade days: 3
- Window: 2026-01-28 -> 2026-03-30

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.041515 | 0.031353 | 0.051228 | 0.092744 | 66.67% | -5.09% | 3 | 0 |
| top2_bottom2 | 0.032532 | 0.022370 | -0.010499 | 0.022033 | 66.67% | -4.36% | 3 | 0 |
| top3_bottom3 | 0.026560 | 0.016398 | -0.014172 | 0.012388 | 33.33% | -3.73% | 3 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'TSLA': 2, 'AMZN': 1}`
- Short counts: `{'AAPL': 2, 'MSFT': 1}`

### top2_bottom2

- Long counts: `{'TSLA': 2, 'GOOG': 2, 'AMZN': 1, 'NVDA': 1}`
- Short counts: `{'AAPL': 3, 'MSFT': 2, 'GOOG': 1}`

### top3_bottom3

- Long counts: `{'TSLA': 2, 'GOOG': 2, 'AMZN': 2, 'NVDA': 2, 'META': 1}`
- Short counts: `{'AAPL': 3, 'MSFT': 3, 'NVDA': 1, 'AMZN': 1, 'GOOG': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 3 | 0.041515 | 33.33% | `{'TSLA': 2, 'AMZN': 1}` |
| 2 | 3 | 0.023550 | 33.33% | `{'GOOG': 2, 'NVDA': 1}` |
| 3 | 3 | 0.014616 | 33.33% | `{'AMZN': 1, 'NVDA': 1, 'META': 1}` |
| 4 | 3 | -0.051064 | 33.33% | `{'META': 2, 'TSLA': 1}` |
| 5 | 3 | 0.021518 | 33.33% | `{'NVDA': 1, 'AMZN': 1, 'MSFT': 1}` |
| 6 | 3 | 0.072227 | 66.67% | `{'AAPL': 1, 'MSFT': 1, 'GOOG': 1}` |
| 7 | 3 | -0.051228 | 33.33% | `{'AAPL': 2, 'MSFT': 1}` |
