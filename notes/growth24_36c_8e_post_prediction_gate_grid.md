# Growth24 Post-Prediction Gate Grid

- Shadow log: `data\experiment\historical_blind_rank_head\growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet`
- Long/short book: top 2 / bottom 2
- Available cycles: 36
- Overall status: `pass`
- Passing configs: 104

## Baseline

| Days | Coverage | Mean LS | Median LS | Hit | Max DD | Sharpe | Max Long Share |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 36 | 100.00% | 8.26% | 5.45% | 75.00% | -19.86% | 9.000 | 44.44% |

## Best Configs

| Status | Config | Days | Coverage | Mean LS | Median LS | Hit | Max DD | Sharpe | Max Long Share |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| pass | forecast_gap_max=4; universe_score_std_max=0.085; max_consecutive=3 | 19 | 52.78% | 14.07% | 9.18% | 89.47% | -4.02% | 15.377 | 39.47% |
| pass | score_gap_max=0.36; forecast_gap_max=4; universe_score_std_max=0.085; max_consecutive=3 | 19 | 52.78% | 14.07% | 9.18% | 89.47% | -4.02% | 15.377 | 39.47% |
| pass | score_gap_max=0.32; forecast_gap_max=4; universe_score_std_max=0.085; max_consecutive=3 | 19 | 52.78% | 14.07% | 9.18% | 89.47% | -4.02% | 15.377 | 39.47% |
| pass | universe_score_std_max=0.085 | 22 | 61.11% | 13.10% | 8.82% | 90.91% | -4.02% | 14.149 | 43.18% |
| pass | score_gap_max=0.36; universe_score_std_max=0.085 | 22 | 61.11% | 13.10% | 8.82% | 90.91% | -4.02% | 14.149 | 43.18% |
| pass | score_gap_max=0.32; universe_score_std_max=0.085 | 22 | 61.11% | 13.10% | 8.82% | 90.91% | -4.02% | 14.149 | 43.18% |
| pass | universe_score_std_max=0.085; max_consecutive=3 | 22 | 61.11% | 13.02% | 9.40% | 86.36% | -4.02% | 16.907 | 36.36% |
| pass | score_gap_max=0.36; universe_score_std_max=0.085; max_consecutive=3 | 22 | 61.11% | 13.02% | 9.40% | 86.36% | -4.02% | 16.907 | 36.36% |
| pass | score_gap_max=0.32; universe_score_std_max=0.085; max_consecutive=3 | 22 | 61.11% | 13.02% | 9.40% | 86.36% | -4.02% | 16.907 | 36.36% |
| pass | forecast_gap_max=4; universe_score_std_max=0.085 | 19 | 52.78% | 12.66% | 8.53% | 89.47% | -4.02% | 13.777 | 44.74% |
| pass | score_gap_max=0.36; forecast_gap_max=4; universe_score_std_max=0.085 | 19 | 52.78% | 12.66% | 8.53% | 89.47% | -4.02% | 13.777 | 44.74% |
| pass | score_gap_max=0.32; forecast_gap_max=4; universe_score_std_max=0.085 | 19 | 52.78% | 12.66% | 8.53% | 89.47% | -4.02% | 13.777 | 44.74% |
| pass | forecast_gap_max=4; universe_score_std_max=0.09; max_consecutive=3 | 21 | 58.33% | 12.41% | 9.10% | 80.95% | -4.02% | 13.356 | 40.48% |
| pass | score_gap_max=0.36; forecast_gap_max=4; universe_score_std_max=0.09; max_consecutive=3 | 21 | 58.33% | 12.41% | 9.10% | 80.95% | -4.02% | 13.356 | 40.48% |
| pass | score_gap_max=0.32; forecast_gap_max=4; universe_score_std_max=0.09; max_consecutive=3 | 21 | 58.33% | 12.41% | 9.10% | 80.95% | -4.02% | 13.356 | 40.48% |
| pass | forecast_gap_max=4; universe_score_std_max=0.085; long_share<=0.5; max_consecutive=3 | 19 | 52.78% | 11.93% | 9.10% | 84.21% | -9.68% | 13.245 | 36.84% |
| pass | score_gap_max=0.36; forecast_gap_max=4; universe_score_std_max=0.085; long_share<=0.5; max_consecutive=3 | 19 | 52.78% | 11.93% | 9.10% | 84.21% | -9.68% | 13.245 | 36.84% |
| pass | score_gap_max=0.32; forecast_gap_max=4; universe_score_std_max=0.085; long_share<=0.5; max_consecutive=3 | 19 | 52.78% | 11.93% | 9.10% | 84.21% | -9.68% | 13.245 | 36.84% |
| pass | score_gap_max=0.32; universe_score_std_max=0.09 | 24 | 66.67% | 11.73% | 7.73% | 83.33% | -4.02% | 12.581 | 43.75% |
| pass | score_gap_max=0.32; forecast_gap_max=4; max_consecutive=3 | 22 | 61.11% | 11.51% | 8.82% | 77.27% | -7.31% | 12.188 | 40.91% |
| pass | score_gap_max=0.36; forecast_gap_max=4; max_consecutive=3 | 24 | 66.67% | 11.45% | 7.73% | 79.17% | -7.31% | 12.169 | 39.58% |
| pass | universe_score_std_max=0.09 | 25 | 69.44% | 11.30% | 6.93% | 84.00% | -4.02% | 12.256 | 44.00% |
| pass | score_gap_max=0.36; universe_score_std_max=0.09 | 25 | 69.44% | 11.30% | 6.93% | 84.00% | -4.02% | 12.256 | 44.00% |
| pass | universe_score_std_max=0.085; long_share<=0.5 | 22 | 61.11% | 11.25% | 7.73% | 86.36% | -9.68% | 12.408 | 40.91% |
| pass | score_gap_max=0.36; universe_score_std_max=0.085; long_share<=0.5 | 22 | 61.11% | 11.25% | 7.73% | 86.36% | -9.68% | 12.408 | 40.91% |

## Best Ticker Counts

`{'PLTR': 15, 'TSLA': 6, 'NVDA': 5, 'INTC': 4, 'MU': 3, 'AMD': 3, 'ADBE': 1, 'NFLX': 1}`
