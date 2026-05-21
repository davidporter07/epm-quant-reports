# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\rank_head_blind_loop_3c_3e_topmono_ticker01_shadow_log.parquet`
- Trade days: 3
- Window: 2026-01-28 -> 2026-03-30

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.041515 | 0.031353 | -0.078753 | -0.037238 | 33.33% | -5.09% | 3 | 0 |
| top2_bottom2 | 0.031671 | 0.021509 | -0.010499 | 0.021172 | 66.67% | -0.40% | 3 | 0 |
| top3_bottom3 | 0.014432 | 0.004270 | 0.003367 | 0.017798 | 33.33% | -3.73% | 3 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'TSLA': 2, 'AMZN': 1}`
- Short counts: `{'AAPL': 2, 'GOOG': 1}`

### top2_bottom2

- Long counts: `{'TSLA': 2, 'AMZN': 2, 'GOOG': 1, 'MSFT': 1}`
- Short counts: `{'AAPL': 3, 'MSFT': 2, 'GOOG': 1}`

### top3_bottom3

- Long counts: `{'AMZN': 3, 'TSLA': 2, 'META': 2, 'GOOG': 1, 'MSFT': 1}`
- Short counts: `{'AAPL': 3, 'NVDA': 2, 'MSFT': 2, 'TSLA': 1, 'GOOG': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 3 | 0.041515 | 33.33% | `{'TSLA': 2, 'AMZN': 1}` |
| 2 | 3 | 0.021827 | 33.33% | `{'GOOG': 1, 'AMZN': 1, 'MSFT': 1}` |
| 3 | 3 | -0.020046 | 33.33% | `{'META': 2, 'AMZN': 1}` |
| 4 | 3 | 0.037939 | 33.33% | `{'META': 1, 'GOOG': 1, 'NVDA': 1}` |
| 5 | 3 | -0.031099 | 33.33% | `{'NVDA': 2, 'TSLA': 1}` |
| 6 | 3 | -0.057755 | 33.33% | `{'MSFT': 2, 'AAPL': 1}` |
| 7 | 3 | 0.078753 | 66.67% | `{'AAPL': 2, 'GOOG': 1}` |
