# Growth24 Candidate Contract Evaluation

- Shadow log: `data\experiment\growth24_research_candidates\20260601_203313\g24_20260601_203313_12c_3e_stressw3_shadow_log.parquet`
- Status: `provisional`
- Failures: none
- Skipped checks: walk_forward, threshold_sensitivity
- Cycles: 12
- Window: 2025-05-15 -> 2026-04-17
- Paper only: True
- Live policy changed: False
- Paper plan changed: False

## Practical Replay

- Allowed cycles: 7 / 12
- Overlay mean LS: 12.72%
- Overlay hit rate: 71.43%
- Overlay max drawdown: -5.37%
- Baseline all-cycle mean LS: 10.92%
- Abstained baseline mean LS: 8.41%

## Gate Grid

- Status: `pass`
- Passing configs: 96
- Best config: `forecast_gap_max=3; universe_score_std_max=0.08`
- Best mean LS: 15.13%
- Best hit rate: 87.50%
- Best max drawdown: -0.31%

## Walk Forward

- Status: `skipped`
- Passing splits: n/a / 0

## Threshold Sensitivity

- Status: `skipped`
- Passing configs: n/a
- Best config: `n/a`
- Minimum holdout uplift: n/a
- Minimum holdout LS: n/a

## Holdouts

| Score Start | Status | Allowed | Baseline Mean LS | Overlay Mean LS | Hit | Max DD |
|---|---|---:|---:|---:|---:|---:|
| 2024-10-11 | skipped | None / None | n/a | n/a | n/a | n/a |
| 2025-04-15 | skipped | None / None | n/a | n/a | n/a | n/a |
