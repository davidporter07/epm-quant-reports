param(
  [string]$Device = "cuda",
  [switch]$Amp,
  [string]$Seeds = "20260506,20260507",
  [int]$CurrentEpochs = 8,
  [int]$CurrentTopN = 2,
  [int]$HistoricalCycles = 3,
  [int]$HistoricalEpochs = 3,
  [int]$HistoricalTopN = 2,
  [string]$SpreadWeights = "0.0,0.1",
  [switch]$SkipCurrent,
  [switch]$SkipHistorical
)

$ErrorActionPreference = "Stop"
Set-Location "D:\fund_monitor"

$python = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  $python = "python"
}

$runId = Get-Date -Format "yyyyMMdd_HHmmss"
$shortRunId = Get-Date -Format "MMddHHmm"
$outDir = "data\experiment\growth24_research_ladder\$runId"
$modelDir = "models\experiment\g24ladder\$shortRunId"
$logPath = "logs\growth24_research_ladder_$runId.log"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
New-Item -ItemType Directory -Force -Path $modelDir | Out-Null
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

function Write-RunLog($message) {
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message"
  $line | Tee-Object -FilePath $logPath -Append
}

function Invoke-Step($label, $argsList) {
  Write-RunLog "START $label"
  & $python @argsList
  if ($LASTEXITCODE -ne 0) {
    Write-RunLog "FAIL $label exit=$LASTEXITCODE"
    exit $LASTEXITCODE
  }
  Write-RunLog "DONE $label"
}

$ampArgs = @()
if ($Amp) {
  $ampArgs += "--amp"
}

Write-RunLog "Growth24 research ladder run_id=$runId device=$Device amp=$($Amp.IsPresent) seeds=$Seeds"

Invoke-Step "encoder-probe" @(
  "dl_growth24_encoder_probe.py",
  "--device", $Device,
  "--batch-size", "64",
  "--max-samples", "2048",
  "--output", (Join-Path $outDir "encoder_probe_summary.json")
)

Invoke-Step "foundation-sidecar" @(
  "build_growth24_foundation_sidecar_features.py",
  "--output", (Join-Path $outDir "foundation_sidecar_features.parquet"),
  "--metadata-output", (Join-Path $outDir "foundation_sidecar_features_meta.json"),
  "--augmented-panel-output", (Join-Path $outDir "growth24_panel_foundation_sidecar.parquet")
)

if (-not $SkipCurrent) {
  foreach ($spreadWeight in ($SpreadWeights -split ",")) {
    $spread = [double]$spreadWeight.Trim()
    $spreadToken = ("{0:0.###}" -f $spread).Replace(".", "p")
    $stem = "g24_${shortRunId}_${CurrentEpochs}e_s${spreadToken}"
    $forecast = Join-Path $outDir "${stem}_shadow_forecast.csv"
    $forecastLog = Join-Path $outDir "${stem}_shadow_forecast_log.parquet"
    $plan = Join-Path $outDir "${stem}_paper_plan.csv"
    $planLog = Join-Path $outDir "${stem}_paper_plan_log.csv"
    $summary = Join-Path $outDir "${stem}_shadow_summary.json"
    $gate = Join-Path $outDir "${stem}_ensemble_gate.json"
    $diag = Join-Path $outDir "${stem}_panel_diagnostics.json"
    $currentArgs = @(
      "dl_growth24_shadow_paper.py",
      "--device", $Device,
      "--seeds", $Seeds,
      "--epochs", "$CurrentEpochs",
      "--top-n", "$CurrentTopN",
      "--output-stem", $stem,
      "--forecast-output", $forecast,
      "--forecast-log", $forecastLog,
      "--paper-plan-output", $plan,
      "--paper-plan-log", $planLog,
      "--summary-output", $summary,
      "--panel-diagnostic-output", $diag,
      "--model-dir", $modelDir,
      "--spread-loss-weight", "$spread"
    ) + $ampArgs
    Invoke-Step "current-shadow spread=$spread" $currentArgs
    Invoke-Step "ensemble-gate spread=$spread" @(
      "dl_growth24_ensemble_gate.py",
      "--forecast", $forecast,
      "--summary", $summary,
      "--top-n", "$CurrentTopN",
      "--min-member-count", "$CurrentTopN",
      "--output", $gate
    )
  }
}

if (-not $SkipHistorical) {
  foreach ($spreadWeight in ($SpreadWeights -split ",")) {
    $spread = [double]$spreadWeight.Trim()
    $spreadToken = ("{0:0.###}" -f $spread).Replace(".", "p")
    $stem = "g24_${shortRunId}_${HistoricalCycles}c_${HistoricalEpochs}e_s${spreadToken}"
    $historicalLog = Join-Path $outDir "${stem}_shadow_log.parquet"
    $historicalCsv = Join-Path $outDir "${stem}_shadow_log.csv"
    $historicalSummary = Join-Path $outDir "${stem}_summary.json"
    $historicalArgs = @(
      "dl_rank_head_historical_blind_loop.py",
      "--panel", "data/experiment/dl_research_panels/research_growth_24_price_earnings_av_panel.parquet",
      "--extra-features", $features,
      "--cycles", "$HistoricalCycles",
      "--step-days", "21",
      "--epochs", "$HistoricalEpochs",
      "--seeds", $Seeds,
      "--val-days", "126",
      "--top-n", "$HistoricalTopN",
      "--paper-long-n", "2",
      "--paper-short-n", "2",
      "--device", $Device,
      "--date-grouped-batches",
      "--dates-per-batch", "64",
      "--top-excess-weight", "0.5",
      "--top-excess-temperature", "0.05",
      "--spread-loss-weight", "$spread",
      "--spread-loss-temperature", "0.05",
      "--monotonic-weight", "0.05",
      "--monotonic-quantiles", "5",
      "--stress-loss-weight", "2.0",
      "--stress-feature-min", "2.0",
      "--stress-drawdown-threshold", "-0.20",
      "--target-mode", "date_excess",
      "--output-stem", $stem,
      "--output", $historicalLog,
      "--csv-output", $historicalCsv,
      "--summary-output", $historicalSummary
    ) + $ampArgs
    Invoke-Step "historical-blind spread=$spread" $historicalArgs
  }
}

Write-RunLog "Growth24 research ladder completed out_dir=$outDir"
Write-Host "Growth24 research ladder completed."
Write-Host "Outputs: $outDir"
Write-Host "Log: $logPath"
