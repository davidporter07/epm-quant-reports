# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\research50_3c_3e_date_excess_topmono_shadow_log.parquet`
- Trade days: 3
- Window: 2026-01-15 -> 2026-03-18

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | -0.018471 | -0.028323 | -0.017089 | -0.035560 | 33.33% | -0.21% | 3 | 0 |
| top2_bottom2 | -0.022545 | -0.032396 | -0.000621 | -0.023166 | 0.00% | -4.61% | 3 | 0 |
| top3_bottom3 | 0.006633 | -0.003218 | -0.021647 | -0.015014 | 0.00% | -1.58% | 3 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'GOOG': 1, 'TSLA': 1, 'MSFT': 1}`
- Short counts: `{'AAPL': 3}`

### top2_bottom2

- Long counts: `{'TSLA': 3, 'GOOG': 1, 'META': 1, 'MSFT': 1}`
- Short counts: `{'AAPL': 3, 'MSFT': 1, 'NVDA': 1, 'GOOG': 1}`

### top3_bottom3

- Long counts: `{'TSLA': 3, 'GOOG': 2, 'NVDA': 1, 'META': 1, 'MSFT': 1, 'AMZN': 1}`
- Short counts: `{'AAPL': 3, 'NVDA': 2, 'META': 1, 'MSFT': 1, 'AMZN': 1, 'GOOG': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 3 | -0.018471 | 33.33% | `{'GOOG': 1, 'TSLA': 1, 'MSFT': 1}` |
| 2 | 3 | -0.026618 | 33.33% | `{'TSLA': 2, 'META': 1}` |
| 3 | 3 | 0.064989 | 66.67% | `{'NVDA': 1, 'GOOG': 1, 'AMZN': 1}` |
| 4 | 3 | -0.015879 | 33.33% | `{'AMZN': 1, 'MSFT': 1, 'META': 1}` |
| 5 | 3 | 0.063698 | 100.00% | `{'META': 1, 'AMZN': 1, 'NVDA': 1}` |
| 6 | 3 | -0.015847 | 33.33% | `{'MSFT': 1, 'NVDA': 1, 'GOOG': 1}` |
| 7 | 3 | 0.017089 | 66.67% | `{'AAPL': 3}` |
