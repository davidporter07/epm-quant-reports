import yfinance as yf
import pandas as pd
import plotly.graph_objs as go
import os

from universe_config import get_index_comparison_tickers, get_mag7, get_portfolio_tickers

# --- Settings ---
PORTFOLIO_TICKERS = get_portfolio_tickers()
MAG7 = get_mag7()
INDEX_TICKERS = get_index_comparison_tickers()

os.makedirs("charts", exist_ok=True)

# --- Helpers ---
def add_price_tag(trace, df):
    trace.text = [f"{df['Close'].iloc[-1]:.2f}"]
    trace.textposition = "top right"
    trace.textfont = dict(size=12)
    return trace

def safe_load(path, rename_col=None):
    try:
        df = pd.read_csv(path)
        df.set_index("Ticker", inplace=True)
        if rename_col and rename_col not in df.columns:
            df.rename(columns={df.columns[-1]: rename_col}, inplace=True)
        return df
    except Exception as e:
        print(f" Failed to load {path}: {e}")
        return pd.DataFrame()

def get_single_value(df, ticker, col):
    try:
        val = df.loc[ticker][col]
        return float(val.iloc[0]) if isinstance(val, pd.Series) else float(val)
    except Exception as e:
        print(f" Missing {col} for {ticker}: {e}")
        return None

# --- Portfolio Chart ---
print("\U0001F4E5 Downloading 3Y price data for portfolio funds...")
portfolio_data = yf.download(PORTFOLIO_TICKERS, period="3y", interval="1d", group_by='ticker', auto_adjust=True, threads=True)
print("\U0001F4CA Building portfolio chart...")
portfolio_traces, buttons = [], []

for i, ticker in enumerate(PORTFOLIO_TICKERS):
    if ticker not in portfolio_data.columns.levels[0]:
        continue
    df = portfolio_data[ticker].dropna().copy()
    df['MA20'] = df['Close'].rolling(window=20, min_periods=1).mean()
    df['MA50'] = df['Close'].rolling(window=50, min_periods=1).mean()
    df['MA200'] = df['Close'].rolling(window=200, min_periods=1).mean()
    resistance = df['Close'].max()

    traces = [
        add_price_tag(go.Scatter(x=df.index, y=df['Close'], name=f"{ticker} Price", line=dict(width=2.25)), df),
        go.Scatter(x=df.index, y=df['MA20'], name="20d MA", line=dict(width=1.5)),
        go.Scatter(x=df.index, y=df['MA50'], name="50d MA", line=dict(width=1.5)),
        go.Scatter(x=df.index, y=df['MA200'], name="200d MA", line=dict(width=1.5)),
        go.Scatter(x=[df.index[0], df.index[-1]], y=[resistance]*2, name="Resistance", line=dict(color="firebrick", dash="dash"))
    ]
    for trace in traces:
        trace.visible = (i == 0)
        portfolio_traces.append(trace)

    vis = [False] * len(PORTFOLIO_TICKERS) * 5
    for j in range(5): vis[i*5 + j] = True
    buttons.append(dict(label=ticker, method="update", args=[{"visible": vis}, {"title": ticker}]))

fig_portfolio = go.Figure(data=portfolio_traces, layout=go.Layout(
    title="Portfolio Funds (3Y Price History)",
    updatemenus=[dict(active=0, buttons=buttons)] if buttons else [],
    xaxis=dict(title="Date", showgrid=True),
    yaxis=dict(title="Price ($)", showgrid=True),
    showlegend=True,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5)
))
fig_portfolio.write_html("charts/fund_chart.html")
print(" Chart saved to charts/fund_chart.html")

# --- MAG7 Forecast Chart ---
print("\U0001F4E5 Downloading YTD data for MAG7...")
mag7_data = yf.download(MAG7, period="ytd", interval="1d", group_by='ticker', auto_adjust=True, threads=True)
ff = safe_load("data/fama_french_forecasts.csv", "FF Forecast (%)")
inst = safe_load("data/institutional_forecasts.csv", "Institutional Forecast (%)")
quant = safe_load("data/quantconnect_forecasts.csv", "QuantConnect Forecast (%)")
ml = safe_load("data/ml_forecasts.csv", "ML Forecast (%)")
linear = safe_load("data/linear_forecasts.csv", "Linear Model Forecast (%)")
arimax = safe_load("data/arimax_forecasts.csv", "ARIMAX Forecast (%)")
dl = safe_load("data/dl_forecasts.csv", "DL Forecast (%)")

print(" Building MAG7 forecast chart...")
mag7_forecast_traces, forecast_buttons = [], []
trace_offsets, offset = [], 0
built_mag7 = []
default_ticker = "AAPL"

for ticker in MAG7:
    if ticker not in mag7_data.columns.levels[0]:
        continue

    df = mag7_data[ticker].dropna()
    date = df.index[-1]
    last_price = df["Close"].iloc[-1]
    future_date = date + pd.Timedelta(days=21)
    visible_now = (ticker == default_ticker if default_ticker in MAG7 else len(built_mag7) == 0)

    traces = [add_price_tag(
        go.Scatter(
            x=df.index,
            y=df["Close"],
            name="Price",
            line=dict(width=2.25),
            visible=visible_now
        ),
        df
    )]

    def add_forecast(label, forecast_pct, color):
        if forecast_pct is not None:
            future_price = last_price * (1 + forecast_pct / 100)
            traces.append(go.Scatter(
                x=[date, future_date],
                y=[last_price, future_price],
                name=label,
                mode="lines+text",
                text=[None, f"{forecast_pct:.2f}%"],
                textposition="top right",
                line=dict(dash="dot", color=color),
                visible=visible_now
            ))

    add_forecast("Fama-French", get_single_value(ff, ticker, "FF Forecast (%)"), "crimson")
    add_forecast("Institutional", get_single_value(inst, ticker, "Institutional Forecast (%)"), "lime")
    add_forecast("QuantConnect", get_single_value(quant, ticker, "QuantConnect Forecast (%)"), "mediumorchid")
    add_forecast("ML", get_single_value(ml, ticker, "ML Forecast (%)"), "darkorange")
    add_forecast("Linear", get_single_value(linear, ticker, "Linear Model Forecast (%)"), "steelblue")
    add_forecast("ARIMAX", get_single_value(arimax, ticker, "ARIMAX Forecast (%)"), "teal")
    add_forecast("Deep Learning", get_single_value(dl, ticker, "DL Forecast (%)"), "goldenrod")

    mag7_forecast_traces += traces
    built_mag7.append(ticker)
    trace_offsets.append((offset, len(traces)))
    offset += len(traces)

if built_mag7 and default_ticker not in built_mag7:
    default_ticker = built_mag7[0]

for ticker, (start, count) in zip(built_mag7, trace_offsets):
    vis = [False] * offset
    for j in range(count):
        vis[start + j] = True
    forecast_buttons.append(
        dict(
            label=ticker,
            method="update",
            args=[{"visible": vis}, {"title": f"Forecast: {ticker}"}]
        )
    )

fig_mag7 = go.Figure(data=mag7_forecast_traces, layout=go.Layout(
    title=f"Forecast: {default_ticker}",
    updatemenus=[dict(active=0, buttons=forecast_buttons)] if forecast_buttons else [],
    showlegend=True,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
    xaxis=dict(title="Date", showgrid=True),
    yaxis=dict(title="Price ($)", showgrid=True)
))
fig_mag7.write_html("charts/mag7_forecast_chart.html")
print(" MAG7 forecast chart saved to charts/mag7_forecast_chart.html")

# --- Index Comparison Chart ---
print("\U0001F4E5 Downloading index comparison data...")
index_data = yf.download(INDEX_TICKERS, period="3y", interval="1d", group_by='ticker', auto_adjust=True, threads=True)
print("\U0001F4CA Building index comparison chart...")
traces = []
for ticker in INDEX_TICKERS:
    df = index_data[ticker].dropna()
    if df.empty:
        print(f" Skipping {ticker}  no data available.")
        continue
    returns = (df["Close"] / df["Close"].iloc[0] - 1) * 100
    trace = add_price_tag(go.Scatter(x=df.index, y=returns, name=ticker), df)
    traces.append(trace)

fig_index = go.Figure(data=traces, layout=go.Layout(
    title="Index Comparison (3Y Returns)",
    xaxis=dict(title="Date", showgrid=True),
    yaxis=dict(title="Return (%)", showgrid=True),
    showlegend=True,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
))
fig_index.write_html("charts/index_comparison_chart.html")
print(" Index chart saved to charts/index_comparison_chart.html")

