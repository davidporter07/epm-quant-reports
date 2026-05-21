# DL Abstention Gate Evaluation

- Results dir: `data\experiment\final4_growth24_earnings_regime_probe`
- Status: `pass`
- Candidate configs: 1
- Passing configs: 1

## Best Configs

| Status | Basket | Score Gap | Forecast Gap | Val Score | Val Daily IC | Val Spread | Val Spread Hit | Stress Spread | Stress DD | Stress Coverage |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | -0.2000 | -0.1000 | 50.00% | 0.099825 | 0.00% | 8.33% |

## Passing Configs

- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=-0.2000, val_spread>=-0.1000, val_spread_hit>=50.00%

## HMM Regime Stress

[HMM regime] Rows add decision-date stress diagnostics using `regime_detector.get_regime_series()` and `STRESS_LABELS`.

- [HMM regime] top2_bottom2: decisions=1, pass_rate=100.00%, mean_spread=0.089534
