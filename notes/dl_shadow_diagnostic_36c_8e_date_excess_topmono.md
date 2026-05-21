# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\rank_head_blind_loop_36c_8e_date_excess_topmono_shadow_log.parquet`
- Trade days: 36
- Window: 2023-04-24 -> 2026-03-30

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.037167 | 0.003270 | -0.025606 | 0.011561 | 50.00% | -42.58% | 36 | 0 |
| top2_bottom2 | 0.039711 | 0.005814 | -0.035645 | 0.004066 | 55.56% | -30.16% | 36 | 0 |
| top3_bottom3 | 0.034478 | 0.000580 | -0.036568 | -0.002090 | 44.44% | -26.72% | 36 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'TSLA': 26, 'NVDA': 5, 'META': 3, 'GOOG': 1, 'AMZN': 1}`
- Short counts: `{'MSFT': 15, 'AAPL': 13, 'TSLA': 3, 'GOOG': 2, 'NVDA': 2, 'AMZN': 1}`

### top2_bottom2

- Long counts: `{'TSLA': 30, 'NVDA': 17, 'META': 16, 'GOOG': 6, 'MSFT': 1, 'AMZN': 1, 'AAPL': 1}`
- Short counts: `{'AAPL': 28, 'MSFT': 27, 'GOOG': 5, 'AMZN': 4, 'NVDA': 4, 'TSLA': 3, 'META': 1}`

### top3_bottom3

- Long counts: `{'TSLA': 32, 'META': 31, 'NVDA': 23, 'GOOG': 9, 'AMZN': 8, 'MSFT': 3, 'AAPL': 2}`
- Short counts: `{'MSFT': 31, 'AAPL': 31, 'GOOG': 19, 'AMZN': 11, 'NVDA': 10, 'TSLA': 3, 'META': 3}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 36 | 0.037167 | 55.56% | `{'TSLA': 26, 'NVDA': 5, 'META': 3, 'GOOG': 1, 'AMZN': 1}` |
| 2 | 36 | 0.042255 | 61.11% | `{'META': 13, 'NVDA': 12, 'GOOG': 5, 'TSLA': 4, 'MSFT': 1}` |
| 3 | 36 | 0.024011 | 61.11% | `{'META': 15, 'AMZN': 7, 'NVDA': 6, 'GOOG': 3, 'MSFT': 2}` |
| 4 | 36 | 0.024145 | 66.67% | `{'AMZN': 17, 'GOOG': 8, 'AAPL': 3, 'NVDA': 3, 'MSFT': 2}` |
| 5 | 36 | 0.038413 | 58.33% | `{'GOOG': 14, 'AMZN': 7, 'NVDA': 6, 'MSFT': 4, 'AAPL': 3}` |
| 6 | 36 | 0.045684 | 72.22% | `{'AAPL': 15, 'MSFT': 12, 'AMZN': 3, 'GOOG': 3, 'NVDA': 2}` |
| 7 | 36 | 0.025606 | 50.00% | `{'MSFT': 15, 'AAPL': 13, 'TSLA': 3, 'GOOG': 2, 'NVDA': 2}` |
