# Growth24 Policy Concentration Audit

- Status: `fail`
- Paper only: True
- Live policy changed: False
- Paper plan changed: False
- Shadow log: `data\experiment\historical_blind_rank_head\growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed_shadow_log.parquet`
- Policy: `p0`
- Allowed cycles: 17 / 36
- Overlay allowed mean LS: 13.56%
- Baseline all-cycle mean LS: 8.26%
- Max slot share: 44.12% (PLTR)
- Max contribution share: 59.36% (PLTR)
- Minimum leave-one-cycle-out uplift: 4.12% excluding 2024-10-11

## Failures

- max contribution share 59.36% > 50.00% for PLTR

## Slot Concentration

| Ticker | Slots | Slot Share |
|---|---:|---:|
| PLTR | 15 | 44.12% |
| TSLA | 6 | 17.65% |
| INTC | 4 | 11.76% |
| NVDA | 4 | 11.76% |
| AMD | 2 | 5.88% |
| MU | 2 | 5.88% |
| NFLX | 1 | 2.94% |

## Contribution Concentration

| Ticker | Contribution | Absolute Share | Signed Share |
|---|---:|---:|---:|
| PLTR | 136.82% | 59.36% | 59.36% |
| TSLA | 38.46% | 16.69% | 16.69% |
| AMD | 28.88% | 12.53% | 12.53% |
| INTC | 11.57% | 5.02% | 5.02% |
| NVDA | 6.49% | 2.82% | 2.82% |
| NFLX | 4.93% | 2.14% | 2.14% |
| MU | 3.33% | 1.45% | 1.45% |

## Leave-One-Cycle-Out Uplift

| Excluded AsOfDate | Allowed Cycles | Filter Uplift vs Baseline All |
|---|---:|---:|
| 2023-04-12 | 16 | 5.77% |
| 2023-05-11 | 16 | 4.73% |
| 2023-06-12 | 17 | 5.32% |
| 2023-07-13 | 17 | 5.05% |
| 2023-08-11 | 17 | 5.13% |
| 2023-09-12 | 17 | 4.87% |
| 2023-10-11 | 17 | 5.23% |
| 2023-11-09 | 16 | 6.05% |
| 2023-12-11 | 16 | 5.60% |
| 2024-01-11 | 16 | 5.56% |
| 2024-02-12 | 16 | 5.74% |
| 2024-03-13 | 16 | 5.81% |
| 2024-04-12 | 17 | 4.96% |
| 2024-05-13 | 17 | 5.51% |
| 2024-06-12 | 16 | 5.98% |
| 2024-07-15 | 16 | 5.84% |
| 2024-08-13 | 16 | 5.25% |
| 2024-09-12 | 17 | 5.10% |
| 2024-10-11 | 16 | 4.12% |
| 2024-11-11 | 17 | 5.34% |
| 2024-12-11 | 17 | 4.98% |
| 2025-01-14 | 16 | 4.91% |
| 2025-02-13 | 17 | 4.51% |
| 2025-03-17 | 17 | 5.15% |
| 2025-04-15 | 17 | 4.95% |
| 2025-05-15 | 17 | 5.09% |
| 2025-06-16 | 17 | 5.24% |
| 2025-07-17 | 16 | 5.81% |
| 2025-08-15 | 16 | 5.60% |
| 2025-09-16 | 16 | 4.90% |
| 2025-10-15 | 17 | 5.26% |
| 2025-11-13 | 17 | 4.62% |
| 2025-12-15 | 17 | 6.11% |
| 2026-01-15 | 17 | 5.68% |
| 2026-02-17 | 16 | 5.62% |
| 2026-03-18 | 16 | 5.37% |
