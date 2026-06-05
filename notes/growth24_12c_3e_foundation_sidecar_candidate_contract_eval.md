# Growth24 Candidate Contract Evaluation

- Shadow log: `data\experiment\growth24_research_candidates\20260602_073702\g24_20260602_073702_12c_3e_foundation_sidecar_shadow_log.parquet`
- Status: `provisional`
- Failures: none
- Skipped checks: walk_forward, threshold_sensitivity
- Cycles: 12
- Window: 2025-05-15 -> 2026-04-17
- Paper only: True
- Live policy changed: False
- Paper plan changed: False

## Practical Replay

- Allowed cycles: 4 / 12
- Overlay mean LS: 11.14%
- Overlay hit rate: 100.00%
- Overlay max drawdown: 0.00%
- Baseline all-cycle mean LS: 11.82%
- Abstained baseline mean LS: 12.17%

## Gate Grid

- Status: `pass`
- Passing configs: 74
- Best config: `max_consecutive=3`
- Best mean LS: 13.47%
- Best hit rate: 91.67%
- Best max drawdown: -9.20%

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
