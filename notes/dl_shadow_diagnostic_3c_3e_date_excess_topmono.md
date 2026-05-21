# DL Shadow Diagnostic Report

- Log path: `data\experiment\historical_blind_rank_head\rank_head_blind_loop_3c_3e_date_excess_topmono_shadow_log.parquet`
- Trade days: 3
- Window: 2026-01-28 -> 2026-03-30

## Basket Diagnostics

| Basket | Long Mean | Long Excess | Short Alpha | Spread | Spread Hit | Max DD | Clean Days | Overlap Days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| top1_bottom1 | 0.027480 | 0.017318 | -0.020054 | 0.007426 | 33.33% | -5.09% | 3 | 0 |
| top2_bottom2 | 0.024292 | 0.014130 | -0.010499 | 0.013793 | 66.67% | -6.83% | 3 | 0 |
| top3_bottom3 | 0.001792 | -0.008370 | -0.005368 | -0.003576 | 33.33% | -1.91% | 3 | 0 |

## Ticker Concentration

### top1_bottom1

- Long counts: `{'TSLA': 2, 'NVDA': 1}`
- Short counts: `{'AAPL': 3}`

### top2_bottom2

- Long counts: `{'TSLA': 2, 'GOOG': 1, 'META': 1, 'NVDA': 1, 'AMZN': 1}`
- Short counts: `{'AAPL': 3, 'MSFT': 2, 'GOOG': 1}`

### top3_bottom3

- Long counts: `{'TSLA': 3, 'AMZN': 3, 'GOOG': 1, 'META': 1, 'NVDA': 1}`
- Short counts: `{'MSFT': 3, 'AAPL': 3, 'GOOG': 2, 'NVDA': 1}`

## Rank Buckets

| Rank | Observations | Mean Return | Hit Rate | Top Tickers |
|---:|---:|---:|---:|---|
| 1 | 3 | 0.027480 | 33.33% | `{'TSLA': 2, 'NVDA': 1}` |
| 2 | 3 | 0.021104 | 33.33% | `{'GOOG': 1, 'META': 1, 'AMZN': 1}` |
| 3 | 3 | -0.043207 | 33.33% | `{'AMZN': 2, 'TSLA': 1}` |
| 4 | 3 | 0.049653 | 33.33% | `{'META': 2, 'NVDA': 1}` |
| 5 | 3 | -0.004894 | 33.33% | `{'NVDA': 1, 'GOOG': 1, 'MSFT': 1}` |
| 6 | 3 | 0.000945 | 33.33% | `{'MSFT': 2, 'GOOG': 1}` |
| 7 | 3 | 0.020054 | 66.67% | `{'AAPL': 3}` |
