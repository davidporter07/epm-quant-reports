@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" call ".venv\Scripts\activate.bat"

set RESULTS=data\experiment\rank_head_walkforward_3w_5seed.json
set PANEL=data\experiment\directional_feature_panel_fmp.parquet
set WEIGHTS=0.0 0.3 0.5 0.7

for %%W in (%WEIGHTS%) do (
  set WDIR=%%W
  set WDIR=!WDIR:.=p!
  set OUTDIR=artifacts\distill_sweep\w!WDIR!
  if not exist "!OUTDIR!" mkdir "!OUTDIR!"
  python dl_rank_head_distill_train.py ^
    --results "%RESULTS%" ^
    --panel "%PANEL%" ^
    --top-n 3 ^
    --distill-weight %%W ^
    --seeds 20260601,20260602,20260603 ^
    --epochs 8 ^
    --device auto ^
    --date-grouped-batches ^
    --dates-per-batch 64 ^
    --output "!OUTDIR!\metrics.json" ^
    --artifact-dir "!OUTDIR!\models"
  if errorlevel 1 exit /b %ERRORLEVEL%
)

python summarize_distill_sweep.py --root artifacts\distill_sweep
exit /b %ERRORLEVEL%
