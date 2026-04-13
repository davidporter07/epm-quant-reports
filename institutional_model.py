import yfinance as yf
import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta
from sklearn.linear_model import LinearRegression

from data_utils import load_features, save_features, upsert_features

MAG7 = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOG", "META", "TSLA"]
LOOKBACK = 252
HORIZON = 21

# --- Step 1: Build Historical Dataset ---

def build_historical_data(ticker):
    stock = yf.Ticker(ticker)
    hist = stock.history(period="2y")["Close"].dropna()
    rows = []

    for i in range(LOOKBACK, len(hist) - HORIZON):
        window = hist.iloc[i - LOOKBACK:i]
        future = hist.iloc[i + HORIZON] / hist.iloc[i] - 1

        try:
            info = stock.info
            price = window.iloc[-1]
            rows.append({
                "EarningsPrice": info.get("trailingEps", np.nan) / price,
                "BookPrice": info.get("bookValue", np.nan) / price,
                "ROE": info.get("returnOnEquity", np.nan),
                "Gross_Margin": info.get("grossMargins", np.nan),
                "Revenue_Growth": info.get("revenueGrowth", np.nan),
                "12M_Momentum": price / window.iloc[0] - 1,
                "Forward_21D_Return": future,
                "Ticker": ticker
            })
        except Exception:
            continue

    return pd.DataFrame(rows)


print(" Building historical dataset...")
all_data = pd.concat([build_historical_data(t) for t in MAG7], ignore_index=True)

factor_cols = ["EarningsPrice", "BookPrice", "ROE", "Gross_Margin", "Revenue_Growth", "12M_Momentum"]

# Z-score and institutional score (AQR-style weights)
for col in factor_cols:
    all_data[f"Z_{col}"] = (all_data[col] - all_data[col].mean()) / all_data[col].std()

all_data["Institutional_Score"] = (
    0.20 * all_data["Z_EarningsPrice"] +
    0.15 * all_data["Z_BookPrice"] +
    0.15 * all_data["Z_ROE"] +
    0.10 * all_data["Z_Gross_Margin"] +
    0.10 * all_data["Z_Revenue_Growth"] +
    0.30 * all_data["Z_12M_Momentum"]
)

model_data = all_data.dropna(subset=["Institutional_Score", "Forward_21D_Return"])
model = LinearRegression().fit(model_data[["Institutional_Score"]], model_data["Forward_21D_Return"])

# Save historical features for ML use
z_feature_cols = [f"Z_{col}" for col in factor_cols]
historical = model_data.reset_index(drop=True)
historical[z_feature_cols + ["Institutional_Score", "Ticker"]].to_parquet(
    "data/institutional_features.parquet", index=False
)
print(" Institutional features saved to data/institutional_features.parquet")

# --- Step 2: Live Forecasts ---

def get_fundamentals(ticker):
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        hist = stock.history(period="1y")["Close"].dropna()
        return {
            "Ticker": ticker,
            "EarningsPrice": info.get("trailingEps", np.nan) / info.get("currentPrice", np.nan),
            "BookPrice": info.get("bookValue", np.nan) / info.get("currentPrice", np.nan),
            "ROE": info.get("returnOnEquity", np.nan),
            "Gross_Margin": info.get("grossMargins", np.nan),
            "Revenue_Growth": info.get("revenueGrowth", np.nan),
            "12M_Momentum": hist.iloc[-1] / hist.iloc[0] - 1
        }
    except Exception as e:
        print(f" Failed to fetch fundamentals for {ticker}: {e}")
        return None


print(" Generating live forecasts...")
live_data = [get_fundamentals(t) for t in MAG7]
live_df = pd.DataFrame([d for d in live_data if d is not None]).dropna()

if live_df.empty:
    print(" No valid live data  skipping institutional forecast generation.")
    raise SystemExit(0)

# Z-score and AQR-weighted Institutional Score
z_live = live_df[factor_cols].apply(lambda x: (x - x.mean()) / x.std())
live_df["Institutional_Score"] = (
    0.20 * z_live["EarningsPrice"] +
    0.15 * z_live["BookPrice"] +
    0.15 * z_live["ROE"] +
    0.10 * z_live["Gross_Margin"] +
    0.10 * z_live["Revenue_Growth"] +
    0.30 * z_live["12M_Momentum"]
)

# Percent output (consistent with the rest of the report)
live_df["Institutional Forecast (%)"] = model.predict(live_df[["Institutional_Score"]]).round(4) * 100

# Save forecast file
os.makedirs("data", exist_ok=True)
forecast_out = live_df.set_index("Ticker")[["Institutional_Score", "Institutional Forecast (%)"]].copy()
forecast_out.to_csv("data/institutional_forecasts.csv", float_format="%.2f")
print(" Institutional model forecasts saved to data/institutional_forecasts.csv")

# --- Step 3: Upsert into features.parquet (do NOT wipe other columns) ---
base = load_features()
upd = forecast_out.reset_index()
base = upsert_features(base, upd, date_value=pd.Timestamp.today())
save_features(base)
print(" Updated features.parquet with institutional model outputs (upsert).")
