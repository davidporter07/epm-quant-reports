@echo off
setlocal
cd /d "%~dp0\.."

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"

"%PY%" dl_growth24_paper_maturity_check.py --refresh-earnings --refresh-data --refresh-start 2026-05-28
exit /b %ERRORLEVEL%
