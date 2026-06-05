# Growth24 Post-Prediction Gate Walk-Forward

- Shadow log: `data\experiment\historical_blind_rank_head\growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet`
- Long/short book: top 2 / bottom 2
- Available cycles: 36
- Evaluated configs: 1
- Valid splits: [18, 24]
- Overall status: `pass`
- Passing splits: 2 / 2

## All-Sample Reference

| Config | Days | Coverage | Mean LS | Hit | Max DD | Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| forecast_gap_max=4; universe_score_std_max=0.085 | 19 | 52.78% | 12.66% | 89.47% | -4.02% | 13.777 |

## Walk-Forward Splits

| Split | Train Window | Test Window | Selected Config | Train Mean LS | Train Hit | Train DD | Test Mean LS | Test Hit | Test DD | Test Coverage | Test Status | Baseline Test Mean LS | Test Uplift | Accepted |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|
| 18 | 2023-04-12 -> 2024-09-12 | 2024-10-11 -> 2026-03-18 | forecast_gap_max=4; universe_score_std_max=0.085 | 8.18% | 80.00% | -4.02% | 17.65% | 100.00% | 0.00% | 50.00% | pass | 10.68% | 6.97% | yes |
| 24 | 2023-04-12 -> 2025-03-17 | 2025-04-15 -> 2026-03-18 | forecast_gap_max=4; universe_score_std_max=0.085 | 12.86% | 84.62% | -4.02% | 12.22% | 100.00% | 0.00% | 50.00% | pass | 9.94% | 2.28% | yes |
