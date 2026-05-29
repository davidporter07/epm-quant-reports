@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_growth24_stress_weight_36c.ps1"
exit /b %ERRORLEVEL%
