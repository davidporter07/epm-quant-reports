# Growth24 Candidate Contract Evaluation

- Shadow log: `data\experiment\historical_blind_rank_head\growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet`
- Status: `pass`
- Failures: none
- Skipped checks: none
- Cycles: 36
- Window: 2023-04-12 -> 2026-03-18
- Paper only: True
- Live policy changed: False
- Paper plan changed: False

## Practical Replay

- Allowed cycles: 17 / 36
- Overlay mean LS: 13.56%
- Overlay hit rate: 88.24%
- Overlay max drawdown: -4.02%
- Baseline all-cycle mean LS: 8.26%
- Abstained baseline mean LS: 3.52%

## Gate Grid

- Status: `pass`
- Passing configs: 93
- Best config: `forecast_gap_max=3; universe_score_std_max=0.08; max_consecutive=3`
- Best mean LS: 16.09%
- Best hit rate: 92.86%
- Best max drawdown: 0.00%

## Walk Forward

- Status: `pass`
- Passing splits: 2 / 2

## Threshold Sensitivity

- Status: `pass`
- Passing configs: 17
- Best config: `universe_score_std_max=0.08; forecast_gap_max=3; max_consecutive=0`
- Minimum holdout uplift: 3.34%
- Minimum holdout LS: 13.28%

## Holdouts

| Score Start | Status | Allowed | Baseline Mean LS | Overlay Mean LS | Hit | Max DD |
|---|---|---:|---:|---:|---:|---:|
| 2024-10-11 | scored | 7 / 18 | 10.68% | 21.24% | 100.00% | 0.00% |
| 2025-04-15 | scored | 5 / 12 | 9.94% | 13.28% | 100.00% | 0.00% |
