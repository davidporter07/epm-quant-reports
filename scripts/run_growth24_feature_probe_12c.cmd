@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_growth24_feature_probe_12c.ps1"
exit /b %ERRORLEVEL%
