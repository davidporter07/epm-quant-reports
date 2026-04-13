# generate_charts.py

import os
import datetime as dt
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

from universe_config import get_index_comparison_tickers, get_mag7, get_portfolio_tickers

plt.style.use("seaborn-v0_8-whitegrid")

CHART_DIR = "charts"
os.makedirs(CHART_DIR, exist_ok=True)

for f in os.listdir(CHART_DIR):
    if f.endswith(".png"):
        os.remove(os.path.join(CHART_DIR, f))

MAG7 = get_mag7()
INDEXES = get_index_comparison_tickers()

TODAY = dt.date.today()
START = TODAY - dt.timedelta(days=3 * 365)
print("[INFO] Downloading index data...")
data = yf.download(INDEXES, start=START, end=TODAY, auto_adjust=True)["Close"].ffill()


def safe_csv(path):
    try:
        return pd.read_csv(path).set_index("Ticker")
    except Exception as e:
        print(f"[WARN] Could not load {path}: {e}")
        return pd.DataFrame()


def plot_fund_chart(ticker, series):
    ma20 = series.rolling(window=20, min_periods=1).mean()
    ma50 = series.rolling(window=50, min_periods=1).mean()
    ma200 = series.rolling(window=200, min_periods=1).mean()
    resistance = series.max()

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(series.index, series, label="Price", linewidth=2.2, color="navy")
    ax.plot(ma20.index, ma20, label="20d MA", linewidth=1.25, color="steelblue")
    ax.plot(ma50.index, ma50, label="50d MA", linewidth=1.25, color="darkorange")
    ax.plot(ma200.index, ma200, label="200d MA", linewidth=1.25, color="darkgreen")

    ax.axhline(resistance, linestyle="--", color="red", linewidth=1)
    ax.text(
        series.index[int(len(series) * 0.05)],
        resistance + (resistance * 0.01),
        f"Resistance: {resistance:.2f}",
        color="red",
        fontsize=9,
        ha="left",
        va="bottom",
    )

    def tag_last_point(line, color):
        last = line.dropna().iloc[-1]
        time = line.dropna().index[-1]
        ax.annotate(
            f"{last:.2f}",
            xy=(time, last),
            xytext=(5, 0),
            textcoords="offset points",
            color=color,
            fontsize=9,
            fontweight="bold",
        )

    tag_last_point(series, "navy")
    tag_last_point(ma20, "steelblue")
    tag_last_point(ma50, "darkorange")
    tag_last_point(ma200, "darkgreen")

    ax.set_title(f"{ticker}  3Y Price with 20/50/200 MAs")
    ax.set_xlabel("Date")
    ax.set_ylabel("Price ($)")
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(CHART_DIR, f"{ticker}.png"), dpi=300)
    plt.close()
    print(f"[OK] Chart saved: {ticker}.png")


print("[INFO] Building index comparison chart...")
index_data = data[INDEXES].dropna()
index_data = index_data[index_data.notnull().all(axis=1)]
normalized = index_data / index_data.iloc[0] * 100

INDEX_LABELS = {
    "^SPX":     "S&P 500",
    "^STOXX50E": "Euro Stoxx 50",
    "^N225":    "Nikkei 225",
}
INDEX_COLORS = {
    "^SPX":     "#0d1f2d",   # EPM Navy
    "^STOXX50E": "#b8965a",  # EPM Gold
    "^N225":    "#2c6e9e",   # Steel Blue
}

fig, ax = plt.subplots(figsize=(10, 4.5))
ax.set_facecolor("#fdfcfa")
fig.patch.set_facecolor("#fdfcfa")
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
ax.spines["left"].set_color("#dde3ea")
ax.spines["bottom"].set_color("#dde3ea")
ax.tick_params(colors="#4a5568", labelsize=9)
ax.yaxis.label.set_color("#4a5568")
ax.xaxis.label.set_color("#4a5568")

for ticker in INDEXES:
    label = INDEX_LABELS.get(ticker, ticker)
    color = INDEX_COLORS.get(ticker, "#333333")
    ax.plot(normalized.index, normalized[ticker], label=label,
            linewidth=2.2, color=color)
    # Annotate final return at end of line
    final_val = normalized[ticker].iloc[-1]
    total_ret = final_val - 100
    sign = "+" if total_ret >= 0 else ""
    ax.annotate(
        f"{label}\n{sign}{total_ret:.1f}%",
        xy=(normalized.index[-1], final_val),
        xytext=(6, 0), textcoords="offset points",
        fontsize=8, color=color, fontweight="bold",
        va="center",
    )

ax.axhline(100, color="#dde3ea", linewidth=1, linestyle="--")
ax.set_xlabel("Date", fontsize=9, color="#4a5568")
ax.set_ylabel("Normalized Return (Base = 100)", fontsize=9, color="#4a5568")
ax.set_title("Global Index Performance  3-Year Normalized Returns", fontsize=11,
             fontweight="bold", color="#0d1f2d", pad=10)
ax.legend(loc="upper left", fontsize=9, framealpha=0.7,
          edgecolor="#dde3ea", facecolor="#fdfcfa")
ax.grid(True, alpha=0.25, color="#dde3ea")
fig.tight_layout(pad=1.5)

# Add EPM logo watermark in the lower-left corner
_logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "epm_logo.png")
if os.path.exists(_logo_path):
    try:
        _logo_img = Image.open(_logo_path).convert("RGBA")
        _logo_w, _logo_h = _logo_img.size
        _target_h = 36  # pixels in figure at 200 dpi
        _scale = _target_h / _logo_h
        _logo_img = _logo_img.resize(
            (int(_logo_w * _scale), _target_h), Image.LANCZOS
        )
        _ax_logo = fig.add_axes([0.01, 0.01, 0.10, 0.10])
        _ax_logo.imshow(_logo_img)
        _ax_logo.axis("off")
    except Exception as _e:
        print(f"[WARN] Could not add logo to index comparison chart: {_e}")

plt.savefig(os.path.join(CHART_DIR, "index_comparison.png"), dpi=200,
            facecolor="#fdfcfa", bbox_inches="tight")
plt.close()
print("[OK] Index comparison chart saved: index_comparison.png")

print("[INFO] Generating MAG7 forecast charts...")
features_df = pd.read_parquet("data/features.parquet").set_index("Ticker")
ff = safe_csv("data/fama_french_forecasts.csv")
inst = safe_csv("data/institutional_forecasts.csv")
qc = safe_csv("data/quantconnect_forecasts.csv")
ml = safe_csv("data/ml_forecasts.csv")
linear = safe_csv("data/linear_forecasts.csv")
arimax = safe_csv("data/arimax_forecasts.csv")
dl = safe_csv("data/dl_forecasts.csv")


def get(tkr, df, col):
    try:
        val = df.loc[tkr, col]
        return float(val.iloc[0]) if isinstance(val, pd.Series) else float(val)
    except Exception:
        return None


for tkr in MAG7:
    try:
        df = yf.download(tkr, period="ytd", interval="1d", auto_adjust=True)["Close"].dropna()
        last = df.iloc[-1]
        today = df.index[-1]
        future = today + pd.Timedelta(days=21)

        fig, ax = plt.subplots(figsize=(10, 4.5))
        ax.plot(df.index, df, label="Price", linewidth=2, color="black")

        def forecast_line(label, pct, color):
            if pct is None:
                return
            predicted = last * (1 + pct / 100)
            ax.plot([today, future], [last, predicted], label=f"{label}: {pct:.2f}%", linestyle="--", color=color)
            ax.annotate(f"{pct:.2f}%", xy=(future, predicted), xytext=(5, 0), textcoords="offset points", fontsize=9, color=color)

        forecast_line("Linear", get(tkr, linear, "Linear Model Forecast (%)"), "steelblue")
        forecast_line("Fama-French", get(tkr, ff, "FF Forecast (%)"), "darkgreen")
        forecast_line("Institutional", get(tkr, inst, "Institutional Forecast (%)"), "orange")
        forecast_line("QuantConnect", get(tkr, qc, "QuantConnect Forecast (%)"), "purple")
        forecast_line("ML", get(tkr, ml, "ML Forecast (%)"), "crimson")
        forecast_line("ARIMAX", get(tkr, arimax, "ARIMAX Forecast (%)"), "teal")
        forecast_line("Deep Learning", get(tkr, dl, "DL Forecast (%)"), "goldenrod")

        ax.set_title(f"{tkr}  Forecasts Only (YTD)")
        ax.set_xlim(df.index[0], future + pd.Timedelta(days=3))
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(os.path.join(CHART_DIR, f"mag7_forecast_{tkr}.png"), dpi=300)
        plt.close()
        print(f"[OK] Forecast chart saved: mag7_forecast_{tkr}.png")

    except Exception as e:
        print(f"[ERR] Failed {tkr}: {e}")
