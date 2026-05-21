# DL Abstention Gate Evaluation

- Results dir: `data\experiment\historical_regime_tests_quantcup_price`
- Status: `pass`
- Candidate configs: 100
- Passing configs: 12

## Best Configs

| Status | Basket | Score Gap | Forecast Gap | Val Score | Val Daily IC | Val Spread | Val Spread Hit | Stress Spread | Stress DD | Stress Coverage |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pass | top3_bottom3 | 0.0000 | 1.5000 | 0.0000 | -0.0500 | 0.0000 | 45.00% | 0.015962 | -5.76% | 11.11% |
| pass | top3_bottom3 | 0.0000 | 1.5000 | 0.0000 | -0.0500 | 0.0200 | 45.00% | 0.015962 | -5.76% | 11.11% |
| pass | top3_bottom3 | 0.0000 | 1.5000 | 0.0000 | 0.0000 | 0.0000 | 45.00% | 0.015962 | -5.76% | 11.11% |
| pass | top3_bottom3 | 0.0000 | 1.5000 | 0.0000 | 0.0000 | 0.0200 | 45.00% | 0.015962 | -5.76% | 11.11% |
| pass | top3_bottom3 | 0.0000 | 1.5000 | 0.0000 | 0.0500 | 0.0000 | 45.00% | 0.015962 | -5.76% | 11.11% |
| pass | top3_bottom3 | 0.0000 | 1.5000 | 0.0000 | 0.0500 | 0.0200 | 45.00% | 0.015962 | -5.76% | 11.11% |
| pass | top3_bottom3 | 0.0000 | 2.0000 | 0.0000 | -0.0500 | 0.0000 | 45.00% | 0.015962 | -5.76% | 11.11% |
| pass | top3_bottom3 | 0.0000 | 2.0000 | 0.0000 | -0.0500 | 0.0200 | 45.00% | 0.015962 | -5.76% | 11.11% |
| pass | top3_bottom3 | 0.0000 | 2.0000 | 0.0000 | 0.0000 | 0.0000 | 45.00% | 0.015962 | -5.76% | 11.11% |
| pass | top3_bottom3 | 0.0000 | 2.0000 | 0.0000 | 0.0000 | 0.0200 | 45.00% | 0.015962 | -5.76% | 11.11% |
| pass | top3_bottom3 | 0.0000 | 2.0000 | 0.0000 | 0.0500 | 0.0000 | 45.00% | 0.015962 | -5.76% | 11.11% |
| pass | top3_bottom3 | 0.0000 | 2.0000 | 0.0000 | 0.0500 | 0.0200 | 45.00% | 0.015962 | -5.76% | 11.11% |
| fail | top1_bottom1 | 0.0800 | 1.0000 | 0.5000 | -0.0500 | 0.0500 | 45.00% | 0.212765 | 0.00% | 1.39% |
| fail | top1_bottom1 | 0.0800 | 1.0000 | 0.5000 | -0.0500 | 0.0500 | 50.00% | 0.212765 | 0.00% | 1.39% |
| fail | top1_bottom1 | 0.0800 | 1.0000 | 0.5000 | -0.0500 | 0.0500 | 55.00% | 0.212765 | 0.00% | 1.39% |
| fail | top1_bottom1 | 0.0800 | 1.0000 | 0.5000 | 0.0000 | 0.0500 | 45.00% | 0.212765 | 0.00% | 1.39% |
| fail | top1_bottom1 | 0.0800 | 1.0000 | 0.5000 | 0.0000 | 0.0500 | 50.00% | 0.212765 | 0.00% | 1.39% |
| fail | top1_bottom1 | 0.0800 | 1.0000 | 0.5000 | 0.0000 | 0.0500 | 55.00% | 0.212765 | 0.00% | 1.39% |
| fail | top1_bottom1 | 0.0800 | 1.0000 | 0.5000 | 0.0500 | 0.0500 | 45.00% | 0.212765 | 0.00% | 1.39% |
| fail | top1_bottom1 | 0.0800 | 1.0000 | 0.5000 | 0.0500 | 0.0500 | 50.00% | 0.212765 | 0.00% | 1.39% |

## Passing Configs

- top3_bottom3: score_gap>=0.0000, forecast_gap>=1.5000, val_score>=0.0000, val_daily_ic>=-0.0500, val_spread>=0.0000, val_spread_hit>=45.00%
- top3_bottom3: score_gap>=0.0000, forecast_gap>=1.5000, val_score>=0.0000, val_daily_ic>=-0.0500, val_spread>=0.0200, val_spread_hit>=45.00%
- top3_bottom3: score_gap>=0.0000, forecast_gap>=1.5000, val_score>=0.0000, val_daily_ic>=0.0000, val_spread>=0.0000, val_spread_hit>=45.00%
- top3_bottom3: score_gap>=0.0000, forecast_gap>=1.5000, val_score>=0.0000, val_daily_ic>=0.0000, val_spread>=0.0200, val_spread_hit>=45.00%
- top3_bottom3: score_gap>=0.0000, forecast_gap>=1.5000, val_score>=0.0000, val_daily_ic>=0.0500, val_spread>=0.0000, val_spread_hit>=45.00%
- top3_bottom3: score_gap>=0.0000, forecast_gap>=1.5000, val_score>=0.0000, val_daily_ic>=0.0500, val_spread>=0.0200, val_spread_hit>=45.00%
- top3_bottom3: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=0.0000, val_daily_ic>=-0.0500, val_spread>=0.0000, val_spread_hit>=45.00%
- top3_bottom3: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=0.0000, val_daily_ic>=-0.0500, val_spread>=0.0200, val_spread_hit>=45.00%
- top3_bottom3: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=0.0000, val_daily_ic>=0.0000, val_spread>=0.0000, val_spread_hit>=45.00%
- top3_bottom3: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=0.0000, val_daily_ic>=0.0000, val_spread>=0.0200, val_spread_hit>=45.00%
- top3_bottom3: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=0.0000, val_daily_ic>=0.0500, val_spread>=0.0000, val_spread_hit>=45.00%
- top3_bottom3: score_gap>=0.0000, forecast_gap>=2.0000, val_score>=0.0000, val_daily_ic>=0.0500, val_spread>=0.0200, val_spread_hit>=45.00%
