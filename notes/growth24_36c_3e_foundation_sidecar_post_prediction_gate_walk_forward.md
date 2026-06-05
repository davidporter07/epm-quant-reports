# Growth24 Post-Prediction Gate Walk-Forward

- Shadow log: `data\experiment\growth24_research_candidates\20260602_102740\g24_20260602_102740_36c_3e_foundation_sidecar_shadow_log.parquet`
- Long/short book: top 2 / bottom 2
- Available cycles: 36
- Evaluated configs: 144
- Valid splits: [18, 24]
- Overall status: `fail`
- Passing splits: 0 / 2

## All-Sample Reference

| Config | Days | Coverage | Mean LS | Hit | Max DD | Sharpe |
|---|---:|---:|---:|---:|---:|---:|
| forecast_gap_max=4; long_share<=0.5; cooldown=2 | 28 | 77.78% | 10.62% | 85.71% | -11.25% | 11.212 |

## Walk-Forward Splits

| Split | Train Window | Test Window | Selected Config | Train Mean LS | Train Hit | Train DD | Test Mean LS | Test Hit | Test DD | Test Coverage | Test Status | Baseline Test Mean LS | Test Uplift | Accepted |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|
| 18 | 2023-05-11 -> 2024-10-11 | 2024-11-11 -> 2026-04-17 | forecast_gap_max=4; universe_score_std_max=0.085; long_share<=0.5 | 12.82% | 80.00% | -3.80% | 5.72% | 85.71% | -9.20% | 38.89% | pass | 8.42% | -2.69% | no |
| 24 | 2023-05-11 -> 2025-04-15 | 2025-05-15 -> 2026-04-17 | forecast_gap_max=4; universe_score_std_max=0.085; long_share<=0.5 | 9.65% | 85.71% | -3.80% | 6.84% | 80.00% | -9.20% | 41.67% | pass | 11.82% | -4.98% | no |
