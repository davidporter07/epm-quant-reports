$ErrorActionPreference = "Stop"
Set-Location "D:\fund_monitor"

$outDir = "data\experiment\final4_growth24_earnings_stress_weight_8e2seed_probe"
$logPath = "logs\final4_growth24_stress_weight_8e2seed_run.log"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
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

$windows = @(
  @{ name = "gfc_2008"; start = "2009-04-02"; end = "2009-06-03" },
  @{ name = "q4_2018_drawdown"; start = "2018-10-03"; end = "2018-12-03" },
  @{ name = "rate_bear_2022"; start = "2022-10-04"; end = "2022-12-02" },
  @{ name = "current_2026"; start = "2026-02-03"; end = "2026-04-06" }
)

function Write-RunLog($message) {
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message"
  $line | Tee-Object -FilePath $logPath -Append
}

Write-RunLog "Starting Final Four Growth24 stress-weight 8e/2seed validation"

foreach ($window in $windows) {
  $regimeDir = Join-Path $outDir $window.name
  New-Item -ItemType Directory -Force -Path $regimeDir | Out-Null
  $stem = "$($window.name)_3c_8e_stress_drawdown20_w2_seedrobust_2seed"
  $log = Join-Path $regimeDir "${stem}_shadow_log.parquet"

  if (Test-Path $log) {
    Write-RunLog "Skipping $($window.name); found $log"
  } else {
    Write-RunLog "Running $($window.name): $($window.start) -> $($window.end)"
    & ".\.venv\Scripts\python.exe" "dl_rank_head_historical_blind_loop.py" `
      --panel "data/experiment/dl_research_panels/research_growth_24_price_earnings_av_panel.parquet" `
      --extra-features $features `
      --start-date $window.start `
      --end-date $window.end `
      --cycles 3 `
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
      --output-stem $stem `
      --output $log `
      --csv-output (Join-Path $regimeDir "${stem}_shadow_log.csv") `
      --summary-output (Join-Path $regimeDir "${stem}_summary.json")
    if ($LASTEXITCODE -ne 0) {
      Write-RunLog "$($window.name) failed with exit code $LASTEXITCODE"
      exit $LASTEXITCODE
    }
    Write-RunLog "Finished $($window.name)"
  }

  foreach ($n in 1, 2, 3) {
    $summary = Join-Path $regimeDir "${stem}_top${n}_bottom${n}.json"
    if (Test-Path $summary) {
      continue
    }
    & ".\.venv\Scripts\python.exe" "dl_rank_head_paper_trade.py" `
      --log-path $log `
      --long-n $n `
      --short-n $n `
      --ledger-output (Join-Path $regimeDir "${stem}_top${n}_bottom${n}.csv") `
      --summary-output $summary
    if ($LASTEXITCODE -ne 0) {
      Write-RunLog "$($window.name) top${n}/bottom${n} scoring failed with exit code $LASTEXITCODE"
      exit $LASTEXITCODE
    }
  }
}

Write-RunLog "Running regime gate"
& ".\.venv\Scripts\python.exe" "dl_regime_gate_report.py" `
  --results-dir $outDir `
  --output (Join-Path $outDir "regime_gate.json") `
  --markdown-output "notes/final4_growth24_earnings_stress_weight_8e2seed_regime_gate.md" `
  --max-drawdown -0.25 `
  --min-hit 0.5 `
  --min-spread 0.0
if ($LASTEXITCODE -ne 0) {
  Write-RunLog "Regime gate failed with exit code $LASTEXITCODE"
  exit $LASTEXITCODE
}

Write-RunLog "Completed Final Four Growth24 stress-weight 8e/2seed validation"
