# refresh_fama_french_factors.py

import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import time

# === Constants ===
CSV_PATH = "data/F-F_Research_Data_Factors_daily.csv"
today = pd.Timestamp.today().normalize()

ETF_MAPPING = {
    "IJS": "Small Value",         # for SMB
    "SCHA": "Small Blend",        # for SMB
    "IJT": "Small Growth",        # for SMB
    "VTV": "Large Value",         # for HML
    "SPY": "Market",              # for Mkt-RF
    "IVW": "Large Growth"         # for HML
}

RISK_FREE = "^IRX"

# === Load Existing CSV ===
# File is always written in clean pandas format: Date index (YYYY-MM-DD), columns Mkt-RF SMB HML RF
print("Loading existing Fama-French CSV...")
df_existing = pd.read_csv(CSV_PATH, index_col=0, parse_dates=True)
df_existing.index.name = "Date"
df_existing = df_existing.sort_index()

# start_date = day after the last complete row already in the file
start_date = df_existing.index.max() + pd.Timedelta(days=1)

if start_date > today:
    print(f" FF data already current through {today.date()}. Nothing to extend.")
    exit()

print(f" Extending FF data from {start_date.date()} to {today.date()}...")

# === Download ETF Close Prices ===
adj_close_dict = {}

for symbol in ETF_MAPPING:
    print(f" Downloading {symbol}...")
    try:
        df = yf.download(symbol, start=start_date, progress=False, auto_adjust=True)
        if "Close" in df.columns:
            adj_close_dict[symbol] = df["Close"].ffill()
        else:
            print(f"WARNING: {symbol}: No 'Close' data returned. Skipping.")
            continue
    except Exception as e:
        print(f"ERROR: Failed to download {symbol}: {e}")

# Filter only the ones that succeeded
if not adj_close_dict:
    print("ERROR: No ETF data available. Exiting.")
    exit()

etf_data = pd.concat(adj_close_dict.values(), axis=1)
etf_data.columns = list(adj_close_dict.keys())
etf_data.index = adj_close_dict[list(adj_close_dict.keys())[0]].index  # Set index from one of the series

if etf_data.empty or etf_data.isnull().all().any():
    print("ERROR: ETF data is incomplete. Aborting.")
    exit()

etf_data.columns = [ETF_MAPPING[ticker] for ticker in etf_data.columns]
returns = etf_data.pct_change().dropna()

# === Download ^IRX Risk-Free Rate ===
print(" Downloading ^IRX risk-free rate...")
rf_data = yf.download(RISK_FREE, start=start_date, end=today + timedelta(days=1), progress=False)

try:
    rf_series = rf_data["Close"]
except KeyError:
    rf_series = rf_data.iloc[:, 0]  # fallback to first column if "Close" not found

if isinstance(rf_series, pd.DataFrame):
    rf_series = rf_series.iloc[:, 0]  # ensure it's a Series

if rf_series.dropna().empty:
    print("WARNING: No valid data found for ^IRX. Exiting.")
    exit()

rf_series = (rf_series / 100) / 252  # Convert to daily decimal rate
rf_series.name = "RF"
rf_df = rf_series.to_frame()

# === Join & Build Synthetic Factors ===
combined = returns.join(rf_df, how="inner").dropna()

# Fill missing columns with NaNs if any ETFs failed
for col in ["Small_Growth", "Big_Growth"]:
    if col not in combined.columns:
        combined[col] = float("nan")

combined["SMB"] = (
    (combined.get("Small_Value", 0) + combined.get("Small_Neutral", 0) + combined.get("Small_Growth", 0)) / 3
    - (combined.get("Big_Value", 0) + combined.get("Big_Neutral", 0) + combined.get("Big_Growth", 0)) / 3
)
combined["HML"] = (
    (combined.get("Small_Value", 0) + combined.get("Big_Value", 0)) / 2
    - (combined.get("Small_Growth", 0) + combined.get("Big_Growth", 0)) / 2
)

combined["Mkt-RF"] = combined["Market"] - combined["RF"]

# OK: Construct factor returns
factor_df = pd.DataFrame(index=etf_data.index)

# Mkt-RF  SPY return minus risk-free rate (use IVW as proxy)
factor_df["Mkt-RF"] = etf_data["Market"].pct_change()

# SMB  (Small Value + Small Blend + Small Growth)/3 - (Large Value + Large Growth)/2
small_avg = etf_data[["Small Value", "Small Blend", "Small Growth"]].mean(axis=1)
large_avg = etf_data[["Large Value", "Large Growth"]].mean(axis=1)
factor_df["SMB"] = small_avg.pct_change() - large_avg.pct_change()

# HML  (Large Value - Large Growth)
factor_df["HML"] = etf_data["Large Value"].pct_change() - etf_data["Large Growth"].pct_change()

# Drop NA from first day change
factor_df.dropna(inplace=True)

# === Final Fama-French Data ===
# Merge calculated factor_df with RF
factor_df = factor_df.join(rf_df, how="inner").dropna()

# Ensure the correct column order
ff_new = factor_df[["Mkt-RF", "SMB", "HML", "RF"]].copy()

preserved = df_existing[df_existing.index < start_date]
updated = pd.concat([preserved, ff_new]).sort_index()

updated.to_csv(CSV_PATH, float_format="%.8f")
print(f"OK: Replaced Fama-French rows from {start_date.date()} to {today.date()} in CSV.")


