# DL Abstention Gate Evaluation

- Results dir: `data\experiment\final4_growth24_earnings_regime_probe`
- Status: `pass`
- Candidate configs: 100
- Passing configs: 50

## Best Configs

| Status | Basket | Score Gap | Forecast Gap | Val Score | Val Daily IC | Val Spread | Val Spread Hit | Stress Spread | Stress DD | Stress Coverage |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | -0.2000 | -0.1000 | 50.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | -0.2000 | -0.1000 | 55.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | -0.2000 | -0.0200 | 50.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | -0.2000 | -0.0200 | 55.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | -0.2000 | 0.0000 | 50.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | -0.2000 | 0.0000 | 55.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | -0.0500 | -0.1000 | 50.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | -0.0500 | -0.1000 | 55.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | -0.0500 | -0.0200 | 50.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | -0.0500 | -0.0200 | 55.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | -0.0500 | 0.0000 | 50.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | -0.0500 | 0.0000 | 55.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | 0.0000 | -0.1000 | 50.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | 0.0000 | -0.1000 | 55.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | 0.0000 | -0.0200 | 50.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | 0.0000 | -0.0200 | 55.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | 0.0000 | 0.0000 | 50.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | 0.0000 | 0.0000 | 55.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | 0.0500 | -0.1000 | 0.00% | 0.099825 | 0.00% | 8.33% |
| pass | top2_bottom2 | 0.0000 | 2.0000 | -10.0000 | 0.0500 | -0.1000 | 45.00% | 0.099825 | 0.00% | 8.33% |

## Passing Configs

- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=-0.2000, val_spread>=-0.1000, val_spread_hit>=50.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=-0.2000, val_spread>=-0.1000, val_spread_hit>=55.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=-0.2000, val_spread>=-0.0200, val_spread_hit>=50.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=-0.2000, val_spread>=-0.0200, val_spread_hit>=55.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=-0.2000, val_spread>=0.0000, val_spread_hit>=50.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=-0.2000, val_spread>=0.0000, val_spread_hit>=55.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=-0.0500, val_spread>=-0.1000, val_spread_hit>=50.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=-0.0500, val_spread>=-0.1000, val_spread_hit>=55.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=-0.0500, val_spread>=-0.0200, val_spread_hit>=50.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=-0.0500, val_spread>=-0.0200, val_spread_hit>=55.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=-0.0500, val_spread>=0.0000, val_spread_hit>=50.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=-0.0500, val_spread>=0.0000, val_spread_hit>=55.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=0.0000, val_spread>=-0.1000, val_spread_hit>=50.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=0.0000, val_spread>=-0.1000, val_spread_hit>=55.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=0.0000, val_spread>=-0.0200, val_spread_hit>=50.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=0.0000, val_spread>=-0.0200, val_spread_hit>=55.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=0.0000, val_spread>=0.0000, val_spread_hit>=50.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=0.0000, val_spread>=0.0000, val_spread_hit>=55.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=0.0500, val_spread>=-0.1000, val_spread_hit>=0.00%
- top2_bottom2: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=-10.0000, val_daily_ic>=0.0500, val_spread>=-0.1000, val_spread_hit>=45.00%
