# DL Abstention Gate Evaluation

- Results dir: `data\experiment\historical_regime_tests_quantcup_price_excess`
- Status: `pass`
- Candidate configs: 100
- Passing configs: 50

## Best Configs

| Status | Basket | Score Gap | Forecast Gap | Val Score | Val Daily IC | Val Spread | Val Spread Hit | Stress Spread | Stress DD | Stress Coverage |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | -0.0500 | 0.0000 | 45.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | -0.0500 | 0.0000 | 50.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | -0.0500 | 0.0000 | 55.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | -0.0500 | 0.0200 | 45.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | -0.0500 | 0.0200 | 50.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | -0.0500 | 0.0200 | 55.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | -0.0500 | 0.0500 | 45.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | -0.0500 | 0.0500 | 50.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | -0.0500 | 0.0500 | 55.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | 0.0000 | 0.0000 | 45.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | 0.0000 | 0.0000 | 50.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | 0.0000 | 0.0000 | 55.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | 0.0000 | 0.0200 | 45.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | 0.0000 | 0.0200 | 50.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | 0.0000 | 0.0200 | 55.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | 0.0000 | 0.0500 | 45.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | 0.0000 | 0.0500 | 50.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | 0.0000 | 0.0500 | 55.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | 0.0500 | 0.0000 | 45.00% | 0.058357 | 0.00% | 5.56% |
| pass | top1_bottom1 | 0.0000 | 2.5000 | 0.5000 | 0.0500 | 0.0000 | 50.00% | 0.058357 | 0.00% | 5.56% |

## Passing Configs

- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=-0.0500, val_spread>=0.0000, val_spread_hit>=45.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=-0.0500, val_spread>=0.0000, val_spread_hit>=50.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=-0.0500, val_spread>=0.0000, val_spread_hit>=55.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=-0.0500, val_spread>=0.0200, val_spread_hit>=45.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=-0.0500, val_spread>=0.0200, val_spread_hit>=50.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=-0.0500, val_spread>=0.0200, val_spread_hit>=55.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=-0.0500, val_spread>=0.0500, val_spread_hit>=45.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=-0.0500, val_spread>=0.0500, val_spread_hit>=50.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=-0.0500, val_spread>=0.0500, val_spread_hit>=55.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=0.0000, val_spread>=0.0000, val_spread_hit>=45.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=0.0000, val_spread>=0.0000, val_spread_hit>=50.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=0.0000, val_spread>=0.0000, val_spread_hit>=55.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=0.0000, val_spread>=0.0200, val_spread_hit>=45.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=0.0000, val_spread>=0.0200, val_spread_hit>=50.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=0.0000, val_spread>=0.0200, val_spread_hit>=55.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=0.0000, val_spread>=0.0500, val_spread_hit>=45.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=0.0000, val_spread>=0.0500, val_spread_hit>=50.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=0.0000, val_spread>=0.0500, val_spread_hit>=55.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=0.0500, val_spread>=0.0000, val_spread_hit>=45.00%
- top1_bottom1: score_gap>=0.0000, forecast_gap>=2.5000, val_score>=0.5000, val_daily_ic>=0.0500, val_spread>=0.0000, val_spread_hit>=50.00%
