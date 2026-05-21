# Growth24 HMM Abstention Filter Report

- Shadow log: `data\experiment\historical_blind_rank_head\growth24_36c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_shadow_log.parquet`
- Top N: 1
- HMM stress labels: bear_stress, bull_volatile

## Summary

| Book | Trade Days | Coverage | Mean Excess | Excess Hit | Excess Max DD |
|---|---:|---:|---:|---:|---:|
| All decisions | 36 | 100.00% | 9.54% | 63.89% | -19.70% |
| Skip HMM stress | 33 | 91.67% | 9.08% | 60.61% | -22.70% |
| HMM stress only | 3 | 8.33% | 14.61% | 100.00% | 0.00% |

## Regime Counts

- bear_quiet: 13
- bear_stress: 1
- bull_quiet: 17
- bull_volatile: 2
- missing: 3
