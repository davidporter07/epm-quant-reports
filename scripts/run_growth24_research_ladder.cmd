@echo off
setlocal
cd /d "%~dp0\.."

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_growth24_research_ladder.ps1" %*
exit /b %ERRORLEVEL%
