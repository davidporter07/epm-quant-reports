# Growth24 Post-Prediction Gate Grid

- Shadow log: `data\experiment\historical_blind_rank_head\growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet`
- Long/short book: top 2 / bottom 2
- Available cycles: 36
- Overall status: `pass`
- Passing configs: 1

## Baseline

| Days | Coverage | Mean LS | Median LS | Hit | Max DD | Sharpe | Max Long Share |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 36 | 100.00% | 8.26% | 5.45% | 75.00% | -19.86% | 9.000 | 44.44% |

## Best Configs

| Status | Config | Days | Coverage | Mean LS | Median LS | Hit | Max DD | Sharpe | Max Long Share |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| pass | forecast_gap_max=4; universe_score_std_max=0.085 | 19 | 52.78% | 12.66% | 8.53% | 89.47% | -4.02% | 13.777 | 44.74% |

## Best Ticker Counts

`{'PLTR': 17, 'TSLA': 6, 'NVDA': 4, 'INTC': 4, 'AMD': 3, 'MU': 2, 'ADBE': 1, 'NFLX': 1}`
