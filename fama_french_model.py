import pandas as pd
import numpy as np
import yfinance as yf
from sklearn.linear_model import LinearRegression
from fama_french import load_fama_french_factors

TICKERS = ["AAPL", "MSFT", "AMZN", "NVDA", "GOOG", "META", "TSLA"]

IPO_DATES = {
    "AAPL": "1980-12-12",
    "MSFT": "1986-03-13",
    "AMZN": "1997-05-15",
    "NVDA": "1999-01-22",
    "GOOG": "2004-08-19",
    "META": "2012-05-18",
    "TSLA": "2010-06-29"
}

def run_ff_model(ticker, ff_factors):
    ipo_date = pd.to_datetime(IPO_DATES.get(ticker, "2000-01-01"))
    latest_ff_date = ff_factors.index.max()
    start_date = max(latest_ff_date - pd.Timedelta(days=120), ipo_date)  # Extended lookback

    data = yf.download(
        ticker,
        start=start_date,
        end=latest_ff_date + pd.Timedelta(days=2),
        progress=False,
        auto_adjust=False
    )

    if "Adj Close" not in data.columns or data["Adj Close"].dropna().empty:
        return None

    data = data["Adj Close"]
    data.index = data.index.normalize()
    data = data.loc[:latest_ff_date]

    returns = data.ffill().pct_change().dropna()
    returns = pd.Series(returns.values.ravel(), index=returns.index, name="Return")

    if returns.empty:
        return None

    ff_valid = ff_factors.dropna(subset=["Mkt-RF", "SMB", "HML", "RF"])
    combined = pd.concat([returns, ff_valid], axis=1, join="inner").dropna()
    print(f" {ticker}: Combined rows = {len(combined)}")

    if "Return" not in combined.columns or len(combined) < 15:  # Lowered threshold
        return None

    combined["Excess"] = combined["Return"] - combined["RF"]
    X = combined[["Mkt-RF", "SMB", "HML"]]
    y = combined["Excess"]
    model = LinearRegression().fit(X, y)

    alpha = model.intercept_
    coefs = model.coef_
    r2 = model.score(X, y)

    recent_factors = ff_valid.loc[ff_valid.index <= latest_ff_date]
    avg_factors = recent_factors.tail(21)[["Mkt-RF", "SMB", "HML"]].mean()
    avg_rf = recent_factors.tail(21)["RF"].mean()

    forecast_excess = model.predict(avg_factors.values.reshape(1, -1))[0]
    forecast_total = forecast_excess + avg_rf

    return {
        "Ticker": ticker,
        "Alpha": round(alpha * 100, 2),
        "Beta_Mkt": round(coefs[0], 3),
        "Beta_SMB": round(coefs[1], 3),
        "Beta_HML": round(coefs[2], 3),
        "R2": round(r2, 3),
        "FF Forecast (%)": round(forecast_total * 100, 4)
    }

if __name__ == "__main__":
    ff_factors = load_fama_french_factors()
    latest_full_date = ff_factors.dropna(subset=["Mkt-RF", "SMB", "HML", "RF"]).index.max()
    ff_factors = ff_factors.loc[:latest_full_date]

    results = [run_ff_model(ticker, ff_factors) for ticker in TICKERS]
    results = [r for r in results if r]

    if results:
        df = pd.DataFrame(results).set_index("Ticker")
        df.reset_index().to_csv("data/fama_french_forecasts.csv", index=False)
    else:
        print(" No model results  all tickers skipped due to insufficient data.")
        exit()

    try:
        features = pd.read_parquet("data/features.parquet")
        if "Ticker" in features.columns:
            features = features.set_index("Ticker")
    except:
        features = pd.DataFrame(index=df.index)

    #  Remove any existing rows for MAG7 to prevent duplication
    features = features[~features.index.isin(TICKERS)]

    #  Append new forecasts
    df["Date"] = pd.Timestamp.today().normalize()
    features = pd.concat([features, df], axis=0)

    # Clean duplicates and save
    features = features.reset_index()
    features = features.loc[:, ~features.columns.duplicated()].copy()
    features.to_parquet("data/features.parquet", index=False)
    print(" features.parquet updated with FF Forecast (%)")


