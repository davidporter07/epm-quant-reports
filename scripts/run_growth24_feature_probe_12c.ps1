$ErrorActionPreference = "Stop"
Set-Location "D:\fund_monitor"

$features = @(
  "momentum_12_1",
  "momentum_6_1",
  "momentum_3_1",
  "overnight_return_5d",
  "intraday_return_5d",
  "overnight_return_20d",
  "intraday_return_20d",
  "atr_percentile",
  "hv_percentile",
  "vol_regime",
  "gap_magnitude_5d",
  "gap_5d_count",
  "Market_Ret_5D",
  "Market_Ret_21D",
  "Market_Ret_63D",
  "Market_Vol_21D",
  "Market_Vol_63D",
  "Market_Drawdown_63D",
  "Market_Drawdown_252D",
  "Market_Stress_Regime",
  "Rel_Ret_5D",
  "Rel_Ret_21D",
  "Rel_Ret_63D",
  "RSI_14",
  "MA_20",
  "MA_50",
  "MA_200",
  "Volume",
  "earnings_surprise_last",
  "earnings_beat_rate_4q",
  "days_since_earnings",
  "post_earnings_window_active",
  "earnings_surprise_direction",
  "earnings_abs_surprise",
  "post_earnings_positive_drift_window",
  "post_earnings_negative_drift_window",
  "earnings_surprise_x_atr_regime",
  "earnings_surprise_x_gap_count"
) -join ","

& "D:\fund_monitor\.venv\Scripts\python.exe" `
  "dl_rank_head_historical_blind_loop.py" `
  --panel "data/experiment/dl_research_panels/research_growth_24_price_earnings_av_panel.parquet" `
  --extra-features $features `
  --cycles 12 `
  --step-days 21 `
  --epochs 8 `
  --seeds "20260506,20260507" `
  --val-days 126 `
  --top-n 1 `
  --paper-long-n 1 `
  --paper-short-n 1 `
  --device cpu `
  --date-grouped-batches `
  --dates-per-batch 64 `
  --top-excess-weight 0.5 `
  --top-excess-temperature 0.05 `
  --monotonic-weight 0.05 `
  --monotonic-quantiles 5 `
  --target-mode date_excess `
  --output-stem "growth24_12c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed" `
  --output "data/experiment/historical_blind_rank_head/growth24_12c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_shadow_log.parquet" `
  --csv-output "data/experiment/historical_blind_rank_head/growth24_12c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_shadow_log.csv" `
  --summary-output "data/experiment/historical_blind_rank_head/growth24_12c_8e_feature_probe_rsi_ma_volume_earnings_seedrobust_2seed_summary.json"

exit $LASTEXITCODE
