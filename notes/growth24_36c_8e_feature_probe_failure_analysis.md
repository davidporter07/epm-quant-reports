# Growth24 Champion Failure Analysis

- Shadow log: `data\experiment\historical_blind_rank_head\growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_shadow_log.parquet`
- Cycles: 36
- Loss cycles: 10 (27.78%)
- Mean loss spread: -8.86%

## Worst Cycles

| AsOf | Regime | Longs | Shorts | Spread | Long Ret | Short Ret | Best Actual | Worst Actual |
|---|---|---|---|---:|---:|---:|---|---|
| 2025-11-13 | bear_quiet | AMD | SNPS | -31.70% | -16.28% | 15.42% | TSLA (18.24%) | NFLX (-18.76%) |
| 2023-11-09 | bear_quiet | PLTR | INTC | -20.57% | -2.74% | 17.83% | PANW (23.62%) | CSCO (-5.02%) |
| 2024-03-13 | bull_quiet | PLTR | SNPS | -8.60% | -9.32% | -0.72% | MU (30.24%) | INTC (-17.44%) |
| 2025-02-13 | bull_quiet | PLTR | AVGO | -8.40% | -25.92% | -17.51% | MU (7.79%) | TSLA (-33.13%) |
| 2024-04-12 | bear_quiet | PLTR | SNPS | -7.67% | -7.63% | 0.04% | TXN (13.73%) | INTC (-14.17%) |
| 2024-12-11 | bull_quiet | PLTR | INTC | -4.53% | -9.10% | -4.57% | AVGO (22.98%) | ADBE (-24.95%) |
| 2023-07-13 | bull_quiet | PLTR | SNPS | -3.40% | -7.95% | -4.54% | CSCO (4.39%) | TSLA (-12.68%) |
| 2024-06-12 | bull_quiet | PLTR | ADBE | -2.40% | 20.61% | 23.02% | TSLA (42.50%) | MU (-6.94%) |

## Loss Ticker Contribution

- PLTR: loss_cycles=9, mean_spread=-6.32%, total_spread=-56.92%
- AMD: loss_cycles=1, mean_spread=-31.70%, total_spread=-31.70%

## HMM Regime Loss Counts

- bear_quiet: 4
- bull_quiet: 6
