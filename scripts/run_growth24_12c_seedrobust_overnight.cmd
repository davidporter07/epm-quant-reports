@echo off
cd /d D:\fund_monitor
set OUT=data\experiment\historical_blind_rank_head\growth24_12c_8e_date_excess_topmono_seedrobust_2seed_overnight_stdout.log
set ERR=data\experiment\historical_blind_rank_head\growth24_12c_8e_date_excess_topmono_seedrobust_2seed_overnight_stderr.log
echo Started %DATE% %TIME% > "%OUT%"
echo Started %DATE% %TIME% > "%ERR%"
D:\fund_monitor\.venv\Scripts\python.exe dl_rank_head_historical_blind_loop.py ^
  --panel data/experiment/dl_research_panels/research_growth_24_price_panel.parquet ^
  --extra-features momentum_12_1,momentum_6_1,momentum_3_1,overnight_return_5d,intraday_return_5d,overnight_return_20d,intraday_return_20d,atr_percentile,hv_percentile,vol_regime,gap_magnitude_5d,gap_5d_count,Market_Ret_5D,Market_Ret_21D,Market_Ret_63D,Market_Vol_21D,Market_Vol_63D,Market_Drawdown_63D,Market_Drawdown_252D,Market_Stress_Regime,Rel_Ret_5D,Rel_Ret_21D,Rel_Ret_63D ^
  --cycles 12 ^
  --step-days 21 ^
  --epochs 8 ^
  --seeds 20260506,20260507 ^
  --val-days 126 ^
  --top-n 1 ^
  --paper-long-n 1 ^
  --paper-short-n 1 ^
  --device cpu ^
  --date-grouped-batches ^
  --dates-per-batch 64 ^
  --top-excess-weight 0.5 ^
  --top-excess-temperature 0.05 ^
  --monotonic-weight 0.05 ^
  --monotonic-quantiles 5 ^
  --target-mode date_excess ^
  --output-stem growth24_12c_8e_date_excess_topmono_seedrobust_2seed_overnight ^
  --output data/experiment/historical_blind_rank_head/growth24_12c_8e_date_excess_topmono_seedrobust_2seed_overnight_shadow_log.parquet ^
  --csv-output data/experiment/historical_blind_rank_head/growth24_12c_8e_date_excess_topmono_seedrobust_2seed_overnight_shadow_log.csv ^
  --summary-output data/experiment/historical_blind_rank_head/growth24_12c_8e_date_excess_topmono_seedrobust_2seed_overnight_summary.json >> "%OUT%" 2>> "%ERR%"
echo ExitCode %ERRORLEVEL% %DATE% %TIME% >> "%OUT%"
exit /b %ERRORLEVEL%
