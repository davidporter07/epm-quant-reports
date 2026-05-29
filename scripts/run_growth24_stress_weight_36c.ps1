$ErrorActionPreference = "Stop"
Set-Location "D:\fund_monitor"

$stem = "growth24_36c_8e_feature_probe_stress_drawdown20_w2_seedrobust_2seed"
$baseDir = "data\experiment\historical_blind_rank_head\$stem"
$logPath = "logs\${stem}_run.log"
$transcriptPath = "logs\${stem}_transcript.log"
New-Item -ItemType Directory -Force -Path $baseDir | Out-Null
New-Item -ItemType Directory -Force -Path "logs" | Out-Null

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

$chunks = @(
  @{ n = 1; start = "2023-04-12"; end = "2023-09-12" },
  @{ n = 2; start = "2023-10-11"; end = "2024-03-13" },
  @{ n = 3; start = "2024-04-12"; end = "2024-09-12" },
  @{ n = 4; start = "2024-10-11"; end = "2025-03-17" },
  @{ n = 5; start = "2025-04-15"; end = "2025-09-16" },
  @{ n = 6; start = "2025-10-15"; end = "2026-03-18" }
)

function Write-RunLog($message) {
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message"
  $line | Tee-Object -FilePath $logPath -Append
}

Start-Transcript -Path $transcriptPath -Append | Out-Null
Write-RunLog "Starting $stem"

foreach ($chunk in $chunks) {
  $chunkStem = "${stem}_chunk$($chunk.n)"
  $chunkLog = "$baseDir\${chunkStem}_shadow_log.parquet"
  if (Test-Path $chunkLog) {
    Write-RunLog "Skipping chunk $($chunk.n); found $chunkLog"
    continue
  }

  Write-RunLog "Running chunk $($chunk.n): $($chunk.start) -> $($chunk.end)"
  & ".\.venv\Scripts\python.exe" "dl_rank_head_historical_blind_loop.py" `
    --panel "data/experiment/dl_research_panels/research_growth_24_price_earnings_av_panel.parquet" `
    --extra-features $features `
    --start-date $chunk.start `
    --end-date $chunk.end `
    --cycles 6 `
    --step-days 21 `
    --epochs 8 `
    --seeds "20260506,20260507" `
    --val-days 126 `
    --top-n 1 `
    --paper-long-n 2 `
    --paper-short-n 2 `
    --device cpu `
    --date-grouped-batches `
    --dates-per-batch 64 `
    --top-excess-weight 0.5 `
    --top-excess-temperature 0.05 `
    --monotonic-weight 0.05 `
    --monotonic-quantiles 5 `
    --stress-loss-weight 2.0 `
    --stress-feature-min 2.0 `
    --stress-drawdown-threshold -0.20 `
    --target-mode date_excess `
    --output-stem $chunkStem `
    --output $chunkLog `
    --csv-output "$baseDir\${chunkStem}_shadow_log.csv" `
    --summary-output "$baseDir\${chunkStem}_summary.json"
  if ($LASTEXITCODE -ne 0) {
    Write-RunLog "Chunk $($chunk.n) failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
  }
  Write-RunLog "Finished chunk $($chunk.n)"
}

Write-RunLog "Combining chunks"
& ".\.venv\Scripts\python.exe" "combine_growth24_stress_weight_36c.py"
if ($LASTEXITCODE -ne 0) {
  Write-RunLog "Combiner failed with exit code $LASTEXITCODE"
  exit $LASTEXITCODE
}

Write-RunLog "Running diagnostics and gates"
& ".\.venv\Scripts\python.exe" "dl_shadow_diagnostic_report.py" `
  --log-path "data/experiment/historical_blind_rank_head/${stem}_shadow_log.parquet" `
  --output "data/experiment/historical_blind_rank_head/${stem}_diagnostic.json" `
  --markdown-output "notes/dl_shadow_diagnostic_${stem}.md"
& ".\.venv\Scripts\python.exe" "dl_long_only_gate_eval.py" `
  --log-path "data/experiment/historical_blind_rank_head/${stem}_shadow_log.parquet" `
  --output "data/experiment/historical_blind_rank_head/${stem}_long_only_gate.json" `
  --markdown-output "notes/dl_long_only_gate_${stem}_dd35.md" `
  --gate-max-drawdown -0.35
& ".\.venv\Scripts\python.exe" "dl_cap_aware_replay_report.py" `
  --log-path "data/experiment/historical_blind_rank_head/${stem}_shadow_log.parquet" `
  --output "data/experiment/historical_blind_rank_head/${stem}_cap_aware_top2_cap50.json" `
  --markdown-output "notes/dl_cap_aware_replay_${stem}_top2_cap50.md" `
  --top-n-values 2 `
  --max-ticker-shares 0.50 `
  --min-score-gaps 0 `
  --min-forecast-gaps 0 `
  --min-validation-scores -10 `
  --min-validation-daily-ics -0.05 `
  --min-validation-spreads -0.02 `
  --min-validation-spread-positive-rates 0.45 `
  --gate-max-drawdown -0.35

Write-RunLog "Completed $stem"
Stop-Transcript | Out-Null
