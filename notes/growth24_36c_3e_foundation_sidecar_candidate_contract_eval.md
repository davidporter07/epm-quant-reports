# Growth24 Candidate Contract Evaluation

- Shadow log: `data\experiment\growth24_research_candidates\20260602_102740\g24_20260602_102740_36c_3e_foundation_sidecar_shadow_log.parquet`
- Status: `fail`
- Failures: walk_forward, threshold_sensitivity
- Skipped checks: none
- Cycles: 36
- Window: 2023-05-11 -> 2026-04-17
- Paper only: True
- Live policy changed: False
- Paper plan changed: False

## Practical Replay

- Allowed cycles: 11 / 36
- Overlay mean LS: 9.01%
- Overlay hit rate: 90.91%
- Overlay max drawdown: -3.80%
- Baseline all-cycle mean LS: 7.62%
- Abstained baseline mean LS: 7.01%

## Gate Grid

- Status: `pass`
- Passing configs: 74
- Best config: `score_gap_max=0.36; forecast_gap_max=3; max_consecutive=3`
- Best mean LS: 8.80%
- Best hit rate: 81.82%
- Best max drawdown: -9.20%

## Walk Forward

- Status: `fail`
- Passing splits: 0 / 2

## Threshold Sensitivity

- Status: `fail`
- Passing configs: 0
- Best config: `universe_score_std_max=0.09; forecast_gap_max=4; max_consecutive=0`
- Minimum holdout uplift: -1.15%
- Minimum holdout LS: 8.48%

## Holdouts

| Score Start | Status | Allowed | Baseline Mean LS | Overlay Mean LS | Hit | Max DD |
|---|---|---:|---:|---:|---:|---:|
| 2024-10-11 | scored | 6 / 19 | 9.61% | 8.00% | 100.00% | 0.00% |
| 2025-04-15 | scored | 4 / 13 | 12.33% | 11.14% | 100.00% | 0.00% |
