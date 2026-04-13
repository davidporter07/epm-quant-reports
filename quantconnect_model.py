import yfinance as yf
import pandas as pd
import numpy as np
from datetime import timedelta
from sklearn.linear_model import LinearRegression
import time

from data_utils import load_features, save_features, upsert_features

# --- Constants ---
MAG7 = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOG", "META", "TSLA"]
TODAY = pd.Timestamp.today().normalize()
START = TODAY - timedelta(days=365 * 2)
HORIZON = 21

# --- Download Price Data with Retry ---

def fetch_data(tickers, retries=2, delay=3):
    data = pd.DataFrame()
    for attempt in range(retries):
        try:
            data = yf.download(tickers, start=START, end=TODAY, auto_adjust=True)["Close"].ffill()
            if set(tickers).issubset(set(data.columns)):
                return data
            missing = set(tickers) - set(data.columns)
            print(f" Missing tickers on attempt {attempt + 1}: {missing}")
        except Exception as e:
            print(f" Attempt {attempt + 1} failed: {e}")
        time.sleep(delay)
    print(" Final attempt failed. Some tickers may be missing.")
    return data


print(" Downloading MAG7 price data...")
data = fetch_data(MAG7)


# --- Compute Signals ---

def compute_signals(prices):
    signals = {}
    for ticker in MAG7:
        try:
            p = prices[ticker].dropna()
            if len(p) < 260:
                continue

            # Past returns
            r_1m = p.pct_change(21)
            r_3m = p.pct_change(63)
            r_12m = (p / p.shift(252)) - 1

            # Volatility (63d)
            vol = p.pct_change().rolling(63).std() * np.sqrt(252)

            # MA200 Gap
            ma200 = p.rolling(200).mean()
            momentum_gap = (p - ma200) / ma200

            # Forward return
            fwd_return = p.pct_change(periods=HORIZON).shift(-HORIZON)

            df = pd.DataFrame({
                "1M Return": r_1m,
                "3M Return": r_3m,
                "12M Return": r_12m,
                "Volatility": vol,
                "MA200 Gap": momentum_gap,
                "Forward Return": fwd_return
            }).dropna()

            df["Ticker"] = ticker
            df.index.name = "Date"
            signals[ticker] = df

        except Exception as e:
            print(f" Error with {ticker}: {e}")

    return pd.concat(signals.values()) if signals else pd.DataFrame()


print(" Computing signals...")
signal_df = compute_signals(data)

if signal_df.empty:
    print(" No valid signals  exiting.")
    raise SystemExit(0)

features = ["1M Return", "3M Return", "12M Return", "Volatility", "MA200 Gap"]

# --- Z-score normalization within each date ---
signal_df[features] = signal_df.groupby(signal_df.index)[features].transform(lambda x: (x - x.mean()) / x.std())

# --- Weighted Quant Score (institutional-style weights) ---
weights = {
    "1M Return": 0.10,
    "3M Return": 0.20,
    "12M Return": 0.30,
    "Volatility": 0.20,
    "MA200 Gap": 0.20
}

signal_df["Quant Score"] = sum(signal_df[f] * w for f, w in weights.items())

# --- Train Model: Quant Score  Forward Return ---
model_data = signal_df.dropna(subset=["Quant Score", "Forward Return"])
X = model_data[["Quant Score"]]
y = model_data["Forward Return"] * 100
model = LinearRegression().fit(X, y)

# --- Live Forecast ---
print(" Computing live forecasts...")
latest = data.iloc[-252:].copy()
forecast_rows = []
for ticker in MAG7:
    try:
        if ticker not in latest.columns:
            print(f" Skipping {ticker}  no price data.")
            continue

        p = latest[ticker].dropna()
        if len(p) < 252:
            print(f" Skipping {ticker}  insufficient history.")
            continue

        r_1m = p.pct_change(21).iloc[-1] if len(p) > 21 else np.nan
        r_3m = p.pct_change(63).iloc[-1] if len(p) > 63 else np.nan
        r_12m = (p.iloc[-1] / p.iloc[-252]) - 1 if len(p) >= 252 else np.nan
        vol = p.pct_change().rolling(63).std().iloc[-1] * np.sqrt(252) if len(p) > 63 else np.nan
        ma200 = p.iloc[-200:].mean() if len(p) >= 200 else np.nan
        gap = (p.iloc[-1] - ma200) / ma200 if pd.notna(ma200) else np.nan

        raw_row = {
            "1M Return": r_1m,
            "3M Return": r_3m,
            "12M Return": r_12m,
            "Volatility": vol,
            "MA200 Gap": gap
        }

        live_row = pd.Series({k: v for k, v in raw_row.items() if pd.notna(v)})
        if len(live_row) < 3:
            print(f" Skipping {ticker}  too few features ({len(live_row)}/5)")
            continue

        epsilon = 1e-6
        z_row = (live_row - model_data[live_row.index].mean()) / (model_data[live_row.index].std() + epsilon)

        total_weight = sum(weights[k] for k in live_row.index)
        adjusted_weights = {k: weights[k] / total_weight for k in live_row.index}
        quant_score = sum(z_row[k] * adjusted_weights[k] for k in live_row.index)

        quant_score = np.clip(quant_score, -3, 3)
        forecast = model.predict(pd.DataFrame([[quant_score]], columns=["Quant Score"]))[0]

        forecast_rows.append({
            "Ticker": ticker,
            "Quant Score": round(float(quant_score), 3),
            "QuantConnect Forecast (%)": round(float(forecast), 2),
            "Date": TODAY,
        })

    except Exception as e:
        print(f" Forecast failed for {ticker}: {e}")


if not forecast_rows:
    print(" No forecasts generated  all tickers skipped.")
    raise SystemExit(0)

# --- Output CSV ---
df_out = pd.DataFrame(forecast_rows)
df_out.set_index("Ticker").to_csv("data/quantconnect_forecasts.csv")
print(" QuantConnect-style forecasts saved to data/quantconnect_forecasts.csv")

# Save only latest row per ticker of signal_df for potential reuse
latest_rows = signal_df.reset_index().sort_values("Date").groupby("Ticker").last()
latest_rows.to_parquet("data/quantconnect_features.parquet")
print(" QuantConnect features saved to data/quantconnect_features.parquet")

# --- Upsert into features.parquet ---
base = load_features()
base = upsert_features(base, df_out[["Ticker", "Quant Score", "QuantConnect Forecast (%)"]], date_value=TODAY)
save_features(base)
print(" Updated features.parquet with QuantConnect model outputs (upsert).")
