# Growth24 Post-Prediction Gate Grid

- Shadow log: `data\experiment\growth24_research_candidates\20260602_102740\g24_20260602_102740_36c_3e_foundation_sidecar_shadow_log.parquet`
- Long/short book: top 2 / bottom 2
- Available cycles: 36
- Overall status: `pass`
- Passing configs: 138

## Baseline

| Days | Coverage | Mean LS | Median LS | Hit | Max DD | Sharpe | Max Long Share |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 36 | 100.00% | 7.62% | 3.75% | 77.78% | -27.58% | 8.891 | 38.89% |

## Best Configs

| Status | Config | Days | Coverage | Mean LS | Median LS | Hit | Max DD | Sharpe | Max Long Share |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| pass | forecast_gap_max=4; long_share<=0.5; cooldown=2 | 28 | 77.78% | 10.62% | 7.79% | 85.71% | -11.25% | 11.212 | 16.07% |
| pass | forecast_gap_max=4; long_share<=0.5; cooldown=2; max_consecutive=3 | 28 | 77.78% | 10.62% | 7.79% | 85.71% | -11.25% | 11.212 | 16.07% |
| pass | score_gap_max=0.36; forecast_gap_max=4; long_share<=0.5; max_consecutive=3 | 24 | 66.67% | 9.76% | 5.58% | 87.50% | -9.20% | 12.474 | 33.33% |
| pass | forecast_gap_max=4; long_share<=0.5; max_consecutive=3 | 28 | 77.78% | 9.56% | 5.58% | 82.14% | -13.29% | 11.503 | 30.36% |
| pass | score_gap_max=0.36; forecast_gap_max=4; cooldown=2 | 24 | 66.67% | 9.21% | 6.95% | 87.50% | -7.23% | 14.128 | 18.75% |
| pass | score_gap_max=0.36; forecast_gap_max=4; cooldown=2; max_consecutive=3 | 24 | 66.67% | 9.21% | 6.95% | 87.50% | -7.23% | 14.128 | 18.75% |
| pass | forecast_gap_max=4; cooldown=2 | 28 | 77.78% | 8.64% | 5.15% | 71.43% | -21.18% | 10.095 | 17.86% |
| pass | forecast_gap_max=4; cooldown=2; max_consecutive=3 | 28 | 77.78% | 8.64% | 5.15% | 71.43% | -21.18% | 10.095 | 17.86% |
| pass | forecast_gap_max=4; universe_score_std_max=0.085; long_share<=0.5 | 12 | 33.33% | 8.58% | 6.12% | 83.33% | -9.20% | 11.888 | 33.33% |
| pass | forecast_gap_max=4; universe_score_std_max=0.085; long_share<=0.5; max_consecutive=3 | 12 | 33.33% | 8.58% | 6.12% | 83.33% | -9.20% | 11.888 | 33.33% |
| pass | score_gap_max=0.36; forecast_gap_max=4; universe_score_std_max=0.085; long_share<=0.5 | 12 | 33.33% | 8.58% | 6.12% | 83.33% | -9.20% | 11.888 | 33.33% |
| pass | score_gap_max=0.36; forecast_gap_max=4; universe_score_std_max=0.085; long_share<=0.5; max_consecutive=3 | 12 | 33.33% | 8.58% | 6.12% | 83.33% | -9.20% | 11.888 | 33.33% |
| pass | score_gap_max=0.32; forecast_gap_max=4; universe_score_std_max=0.085; long_share<=0.5 | 12 | 33.33% | 8.58% | 6.12% | 83.33% | -9.20% | 11.888 | 33.33% |
| pass | score_gap_max=0.32; forecast_gap_max=4; universe_score_std_max=0.085; long_share<=0.5; max_consecutive=3 | 12 | 33.33% | 8.58% | 6.12% | 83.33% | -9.20% | 11.888 | 33.33% |
| pass | forecast_gap_max=4; universe_score_std_max=0.085; long_share<=0.5; cooldown=2 | 12 | 33.33% | 8.38% | 6.88% | 83.33% | -12.99% | 10.987 | 25.00% |
| pass | forecast_gap_max=4; universe_score_std_max=0.085; long_share<=0.5; cooldown=2; max_consecutive=3 | 12 | 33.33% | 8.38% | 6.88% | 83.33% | -12.99% | 10.987 | 25.00% |
| pass | score_gap_max=0.36; forecast_gap_max=4; universe_score_std_max=0.085; long_share<=0.5; cooldown=2 | 12 | 33.33% | 8.38% | 6.88% | 83.33% | -12.99% | 10.987 | 25.00% |
| pass | score_gap_max=0.36; forecast_gap_max=4; universe_score_std_max=0.085; long_share<=0.5; cooldown=2; max_consecutive=3 | 12 | 33.33% | 8.38% | 6.88% | 83.33% | -12.99% | 10.987 | 25.00% |
| pass | score_gap_max=0.32; forecast_gap_max=4; universe_score_std_max=0.085; long_share<=0.5; cooldown=2 | 12 | 33.33% | 8.38% | 6.88% | 83.33% | -12.99% | 10.987 | 25.00% |
| pass | score_gap_max=0.32; forecast_gap_max=4; universe_score_std_max=0.085; long_share<=0.5; cooldown=2; max_consecutive=3 | 12 | 33.33% | 8.38% | 6.88% | 83.33% | -12.99% | 10.987 | 25.00% |
| pass | score_gap_max=0.36; cooldown=2 | 26 | 72.22% | 8.25% | 4.97% | 80.77% | -9.05% | 12.468 | 17.31% |
| pass | score_gap_max=0.36; cooldown=2; max_consecutive=3 | 26 | 72.22% | 8.25% | 4.97% | 80.77% | -9.05% | 12.468 | 17.31% |
| pass | score_gap_max=0.36; long_share<=0.5; cooldown=2 | 26 | 72.22% | 8.25% | 4.97% | 80.77% | -9.05% | 12.468 | 17.31% |
| pass | score_gap_max=0.36; long_share<=0.5; cooldown=2; max_consecutive=3 | 26 | 72.22% | 8.25% | 4.97% | 80.77% | -9.05% | 12.468 | 17.31% |
| pass | score_gap_max=0.36; forecast_gap_max=4; long_share<=0.5; cooldown=2 | 24 | 66.67% | 8.23% | 5.98% | 91.67% | -9.93% | 14.611 | 18.75% |

## Best Ticker Counts

`{'PLTR': 9, 'NVDA': 6, 'TSLA': 6, 'AMD': 6, 'INTC': 6, 'MU': 5, 'NFLX': 4, 'ORCL': 3, 'AVGO': 2, 'PANW': 2, 'CSCO': 2, 'SNPS': 2, 'META': 1, 'QCOM': 1, 'LRCX': 1}`
