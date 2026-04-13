# fama_french.py

import pandas as pd
import yfinance as yf
import datetime as dt

CSV_PATH = "data/F-F_Research_Data_Factors_daily.csv"

def load_fama_french_factors(path=CSV_PATH):
    # Load and clean existing Fama-French data
    df = pd.read_csv(path, skiprows=3)
    df = df[~df.iloc[:, 0].str.contains("^[A-Z]", na=False)]
    df.columns = ["Date", "Mkt-RF", "SMB", "HML", "RF"]
# Auto-detect date format (works with both %Y%m%d and ISO8601)
    try:
        df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d")
    except:
        df["Date"] = pd.to_datetime(df["Date"])

    df = df.set_index("Date")
    for col in ["Mkt-RF", "SMB", "HML", "RF"]:
        df[col] = df[col] / 100.0

    # Append RF if missing days up to today
    last = df.index.max()
    today = pd.Timestamp.today().normalize()

    if last < today:
        print(f" Appending RF data from {last.date()+pd.Timedelta(days=1)} to {today.date()}...")
        try:
            yield_df = yf.download('^IRX', start=last + pd.Timedelta(days=1), end=today + pd.Timedelta(days=1))['Close'] / 100
            yield_df.name = 'RF'

            # Create rows with NaNs for Mkt-RF, SMB, HML
            new = pd.DataFrame(index=yield_df.index)
            new['Mkt-RF'] = pd.NA
            new['SMB'] = pd.NA
            new['HML'] = pd.NA
            new['RF'] = yield_df

            df = pd.concat([df, new])
            df = df[~df.index.duplicated()]
            df = df.sort_index()
            df.to_csv(path, float_format="%.8f")
            print(f" Appended {len(new)} new RF row(s) from Yahoo Finance.")
        except Exception as e:
            print(f" Failed to fetch RF from Yahoo Finance: {e}")

    return df

if __name__ == "__main__":
    df = load_fama_french_factors()
    print(" Loaded Fama-French factors:")
    print(df.tail())
    print("\nDate range:", df.index.min().date(), "to", df.index.max().date())
    print("\nColumns:", df.columns.tolist())
    print("\nSample row:\n", df.iloc[-1])
