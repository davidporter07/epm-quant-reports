@echo off
cd /d D:\fund_monitor
"C:\Users\david\AppData\Local\Programs\Python\Python312\python.exe" -c "from dotenv import load_dotenv; load_dotenv(); from quant_cup.earnings_av import download_earnings; from quant_cup.data_loader import get_sp500_tickers; import os; download_earnings(get_sp500_tickers(), os.environ['AV_API_KEY'])" >> D:\fund_monitor\av_download_log.txt 2>&1
