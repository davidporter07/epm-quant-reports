# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\rank_head_blind_loop_3c_3e_topmono_ticker_shadow_log.parquet`
- Trade days: 3
- Window: 2026-01-28 -> 2026-03-30

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.021104 | 0.010942 | 0.030647 | 0.051751 | 66.67% | -10.53% | 3 | 0 |
| top2_bottom2 | 0.003989 | -0.006173 | -0.023827 | -0.019838 | 33.33% | -6.18% | 3 | 0 |
| top3_bottom3 | 0.009109 | -0.001053 | -0.029086 | -0.019977 | 33.33% | -4.29% | 3 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'GOOG': 1, 'META': 1, 'AMZN': 1}`
- Short counts: `{'NVDA': 1, 'AAPL': 1, 'TSLA': 1}`

### top2_bottom2

- Long counts: `{'AMZN': 2, 'MSFT': 2, 'GOOG': 1, 'META': 1}`
- Short counts: `{'AAPL': 2, 'NVDA': 2, 'GOOG': 1, 'TSLA': 1}`

### top3_bottom3

- Long counts: `{'GOOG': 2, 'AMZN': 2, 'META': 2, 'MSFT': 2, 'TSLA': 1}`
- Short counts: `{'NVDA': 3, 'AAPL': 2, 'TSLA': 2, 'META': 1, 'GOOG': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 3 | 0.021104 | 33.33% | `{'GOOG': 1, 'META': 1, 'AMZN': 1}` |
| 2 | 3 | -0.013126 | 33.33% | `{'MSFT': 2, 'AMZN': 1}` |
| 3 | 3 | 0.019348 | 33.33% | `{'TSLA': 1, 'GOOG': 1, 'META': 1}` |
| 4 | 3 | -0.043449 | 33.33% | `{'MSFT': 1, 'AMZN': 1, 'AAPL': 1}` |
| 5 | 3 | 0.039603 | 33.33% | `{'META': 1, 'TSLA': 1, 'NVDA': 1}` |
| 6 | 3 | 0.078302 | 66.67% | `{'AAPL': 1, 'NVDA': 1, 'GOOG': 1}` |
| 7 | 3 | -0.030647 | 33.33% | `{'NVDA': 1, 'AAPL': 1, 'TSLA': 1}` |
