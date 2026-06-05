# Growth24 Paper-Policy Threshold Sensitivity

- Paper only: True
- Live policy changed: False
- Paper plan changed: False
- Shadow log: `data\experiment\historical_blind_rank_head\growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet`
- Score start dates: 2024-10-11, 2025-04-15
- Configs tested: 18
- Passing configs: 17
- Overall status: `pass`

## Best Robust Config

- Config: `universe_score_std_max=0.08; forecast_gap_max=3; max_consecutive=0`
- Full-sample allowed cycles: 13 / 36
- Full-sample overlay mean LS: 14.73%
- Full-sample filter uplift: 6.47%
- Full-sample selection uplift: 0.00%
- Full-sample replacement cycles: 0
- Minimum holdout allowed cycles: 5
- Minimum holdout filter uplift: 3.34%
- Minimum holdout overlay mean LS: 13.28%
- Worst holdout max drawdown: 0.00%

## Top Configs

| Status | Config | Holdout Passes | Min Holdout Allowed | Min Holdout Uplift | Min Holdout LS | Worst Holdout DD | All Allowed | All Mean LS | All Replacements |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| pass | universe_score_std_max=0.08; forecast_gap_max=3; max_consecutive=0 | 2 / 2 | 5 | 3.34% | 13.28% | 0.00% | 13 / 36 | 14.73% | 0 |
| pass | universe_score_std_max=0.085; forecast_gap_max=3; max_consecutive=0 | 2 / 2 | 5 | 3.34% | 13.28% | 0.00% | 13 / 36 | 14.73% | 0 |
| pass | universe_score_std_max=0.08; forecast_gap_max=4; max_consecutive=0 | 2 / 2 | 5 | 3.34% | 13.28% | 0.00% | 17 / 36 | 13.56% | 0 |
| pass | universe_score_std_max=0.085; forecast_gap_max=4; max_consecutive=0 | 2 / 2 | 5 | 3.34% | 13.28% | 0.00% | 17 / 36 | 13.56% | 0 |
| pass | universe_score_std_max=0.08; forecast_gap_max=5; max_consecutive=0 | 2 / 2 | 5 | 3.34% | 13.28% | 0.00% | 19 / 36 | 12.71% | 0 |
| pass | universe_score_std_max=0.085; forecast_gap_max=5; max_consecutive=0 | 2 / 2 | 5 | 3.34% | 13.28% | 0.00% | 19 / 36 | 12.71% | 0 |
| pass | universe_score_std_max=0.08; forecast_gap_max=3; max_consecutive=3 | 2 / 2 | 5 | 3.34% | 13.28% | 0.00% | 13 / 36 | 15.73% | 1 |
| pass | universe_score_std_max=0.085; forecast_gap_max=3; max_consecutive=3 | 2 / 2 | 5 | 3.34% | 13.28% | 0.00% | 13 / 36 | 15.73% | 1 |
| pass | universe_score_std_max=0.08; forecast_gap_max=4; max_consecutive=3 | 2 / 2 | 5 | 3.34% | 13.28% | 0.00% | 17 / 36 | 14.32% | 1 |
| pass | universe_score_std_max=0.085; forecast_gap_max=4; max_consecutive=3 | 2 / 2 | 5 | 3.34% | 13.28% | 0.00% | 17 / 36 | 14.32% | 1 |
| pass | universe_score_std_max=0.08; forecast_gap_max=5; max_consecutive=3 | 2 / 2 | 5 | 3.34% | 13.28% | 0.00% | 19 / 36 | 11.89% | 3 |
| pass | universe_score_std_max=0.085; forecast_gap_max=5; max_consecutive=3 | 2 / 2 | 5 | 3.34% | 13.28% | 0.00% | 19 / 36 | 11.89% | 3 |
| pass | universe_score_std_max=0.09; forecast_gap_max=3; max_consecutive=0 | 2 / 2 | 5 | 3.34% | 13.28% | -2.95% | 14 / 36 | 13.47% | 0 |
| pass | universe_score_std_max=0.09; forecast_gap_max=4; max_consecutive=0 | 2 / 2 | 5 | 3.34% | 13.28% | -2.95% | 18 / 36 | 12.64% | 0 |
| pass | universe_score_std_max=0.09; forecast_gap_max=5; max_consecutive=0 | 2 / 2 | 5 | 3.34% | 13.28% | -2.95% | 20 / 36 | 11.93% | 0 |
| pass | universe_score_std_max=0.09; forecast_gap_max=3; max_consecutive=3 | 2 / 2 | 5 | 3.34% | 13.28% | -2.95% | 14 / 36 | 14.40% | 1 |
| pass | universe_score_std_max=0.09; forecast_gap_max=4; max_consecutive=3 | 2 / 2 | 5 | 3.34% | 13.28% | -2.95% | 18 / 36 | 13.36% | 1 |
| fail | universe_score_std_max=0.09; forecast_gap_max=5; max_consecutive=3 | 1 / 2 | 5 | -0.67% | 10.01% | -11.30% | 20 / 36 | 9.24% | 4 |

## Holdout Detail

| Config | Score Start | Status | Allowed | Baseline Mean LS | Overlay Mean LS | Filter Uplift | Hit | Max DD | Failures |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| universe_score_std_max=0.08; forecast_gap_max=3; max_consecutive=0 | 2024-10-11 | pass | 7 / 18 | 10.68% | 21.24% | 10.57% | 100.00% | 0.00% |  |
| universe_score_std_max=0.08; forecast_gap_max=3; max_consecutive=0 | 2025-04-15 | pass | 5 / 12 | 9.94% | 13.28% | 3.34% | 100.00% | 0.00% |  |
| universe_score_std_max=0.085; forecast_gap_max=3; max_consecutive=0 | 2024-10-11 | pass | 7 / 18 | 10.68% | 21.24% | 10.57% | 100.00% | 0.00% |  |
| universe_score_std_max=0.085; forecast_gap_max=3; max_consecutive=0 | 2025-04-15 | pass | 5 / 12 | 9.94% | 13.28% | 3.34% | 100.00% | 0.00% |  |
| universe_score_std_max=0.08; forecast_gap_max=4; max_consecutive=0 | 2024-10-11 | pass | 7 / 18 | 10.68% | 21.24% | 10.57% | 100.00% | 0.00% |  |
| universe_score_std_max=0.08; forecast_gap_max=4; max_consecutive=0 | 2025-04-15 | pass | 5 / 12 | 9.94% | 13.28% | 3.34% | 100.00% | 0.00% |  |
| universe_score_std_max=0.085; forecast_gap_max=4; max_consecutive=0 | 2024-10-11 | pass | 7 / 18 | 10.68% | 21.24% | 10.57% | 100.00% | 0.00% |  |
| universe_score_std_max=0.085; forecast_gap_max=4; max_consecutive=0 | 2025-04-15 | pass | 5 / 12 | 9.94% | 13.28% | 3.34% | 100.00% | 0.00% |  |
| universe_score_std_max=0.08; forecast_gap_max=5; max_consecutive=0 | 2024-10-11 | pass | 8 / 18 | 10.68% | 19.79% | 9.11% | 100.00% | 0.00% |  |
| universe_score_std_max=0.08; forecast_gap_max=5; max_consecutive=0 | 2025-04-15 | pass | 5 / 12 | 9.94% | 13.28% | 3.34% | 100.00% | 0.00% |  |
| universe_score_std_max=0.085; forecast_gap_max=5; max_consecutive=0 | 2024-10-11 | pass | 8 / 18 | 10.68% | 19.79% | 9.11% | 100.00% | 0.00% |  |
| universe_score_std_max=0.085; forecast_gap_max=5; max_consecutive=0 | 2025-04-15 | pass | 5 / 12 | 9.94% | 13.28% | 3.34% | 100.00% | 0.00% |  |
| universe_score_std_max=0.08; forecast_gap_max=3; max_consecutive=3 | 2024-10-11 | pass | 7 / 18 | 10.68% | 21.24% | 10.57% | 100.00% | 0.00% |  |
| universe_score_std_max=0.08; forecast_gap_max=3; max_consecutive=3 | 2025-04-15 | pass | 5 / 12 | 9.94% | 13.28% | 3.34% | 100.00% | 0.00% |  |
| universe_score_std_max=0.085; forecast_gap_max=3; max_consecutive=3 | 2024-10-11 | pass | 7 / 18 | 10.68% | 21.24% | 10.57% | 100.00% | 0.00% |  |
| universe_score_std_max=0.085; forecast_gap_max=3; max_consecutive=3 | 2025-04-15 | pass | 5 / 12 | 9.94% | 13.28% | 3.34% | 100.00% | 0.00% |  |
| universe_score_std_max=0.08; forecast_gap_max=4; max_consecutive=3 | 2024-10-11 | pass | 7 / 18 | 10.68% | 21.24% | 10.57% | 100.00% | 0.00% |  |
| universe_score_std_max=0.08; forecast_gap_max=4; max_consecutive=3 | 2025-04-15 | pass | 5 / 12 | 9.94% | 13.28% | 3.34% | 100.00% | 0.00% |  |
| universe_score_std_max=0.085; forecast_gap_max=4; max_consecutive=3 | 2024-10-11 | pass | 7 / 18 | 10.68% | 21.24% | 10.57% | 100.00% | 0.00% |  |
| universe_score_std_max=0.085; forecast_gap_max=4; max_consecutive=3 | 2025-04-15 | pass | 5 / 12 | 9.94% | 13.28% | 3.34% | 100.00% | 0.00% |  |
