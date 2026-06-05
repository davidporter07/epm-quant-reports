# Growth24 Post-Prediction Gate Walk-Forward

- Shadow log: `data\experiment\historical_blind_rank_head\growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet`
- Long/short book: top 2 / bottom 2
- Available cycles: 36
- Evaluated configs: 144
- Valid splits: [18, 24]
- Overall status: `pass`
- Passing splits: 2 / 2

## All-Sample Reference

| Config | Days | Coverage | Mean LS | Hit | Max DD | Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| forecast_gap_max=4; universe_score_std_max=0.085; max_consecutive=3 | 19 | 52.78% | 14.07% | 89.47% | -4.02% | 15.377 |

## Walk-Forward Splits

| Split | Train Window | Test Window | Selected Config | Train Mean LS | Train Hit | Train DD | Test Mean LS | Test Hit | Test DD | Test Coverage | Test Status | Baseline Test Mean LS | Test Uplift | Accepted |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|
| 18 | 2023-04-12 -> 2024-09-12 | 2024-10-11 -> 2026-03-18 | forecast_gap_max=4; universe_score_std_max=0.09; max_consecutive=3 | 9.48% | 80.00% | -4.02% | 15.08% | 81.82% | -3.83% | 61.11% | pass | 10.68% | 4.40% | yes |
| 24 | 2023-04-12 -> 2025-03-17 | 2025-04-15 -> 2026-03-18 | forecast_gap_max=4; universe_score_std_max=0.085; max_consecutive=3 | 13.87% | 84.62% | -4.02% | 14.52% | 100.00% | 0.00% | 50.00% | pass | 9.94% | 4.59% | yes |
