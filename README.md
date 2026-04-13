# EPM Market Intelligence

A quantitative market intelligence pipeline and web application that aggregates fund data, runs multi-model forecasts, and serves results through a live web dashboard.

Live at: [epm-market-intelligence.com](https://epm-market-intelligence.com)

---

## What It Does

The pipeline runs daily and produces forecasts, market commentary, and dashboards for a universe of funds and indices. It covers:

- **Data ingestion** — scrapes fund data from YCharts, pulls Fama-French factors, fetches news headlines and sentiment
- **Multi-model forecasting** — five model families run in parallel: Fama-French, Linear Panel, ML (gradient boosting), Deep Learning (TCN), and Institutional
- **MAG7 analysis** — dedicated forecasting for the Magnificent 7 mega-cap stocks
- **Market commentary** — LLM-generated daily narrative summaries
- **Web dashboard** — FastAPI backend serving a live UI with fund search, forecasting charts, portfolio views, and market boards

---

## Project Structure

```
app.py                   FastAPI web server (entry point)
monitor.py               Daily pipeline orchestrator
post_run.py              Post-pipeline tasks (DL inference, prediction logging)
universe_config.py       Fund universe definition

# Models
fama_french_model.py     Fama-French 3-factor model
linear_model.py          Linear panel regression
ml_model.py              Gradient boosting model
deep_learning_model.py   TCN (Temporal Convolutional Network) model
institutional_model.py   Institutional flow model
arimax_model.py          ARIMAX time-series model
quantconnect_model.py    QuantConnect integration model

# Data pipeline
data_arbiter.py          Unified data ingestion coordinator
scrape_ycharts.py        YCharts scraper
features.py              Feature engineering
fama_french.py           Fama-French factor processing
fetch_enrichment.py      News and sentiment enrichment
update_sentiment.py      Sentiment score updates
refresh_fama_french_factors.py  Factor data refresh
forecast_common.py       Shared forecasting utilities
sync_forecasts_to_features.py   Forecast → feature sync
build_training_dataset.py       Training data builder

# Feature pipeline (gated DL feature lifecycle)
feature_registry.py      Approved feature registry
dl_feature_gate.py       Feature promotion gating
feature_tester.py        Feature evaluation harness
feature_promoter.py      Promotes tested features to production
feature_validator.py     Feature integrity validation
feature_drift_monitor.py Monitors for feature drift

# Chart and report generation
generate_charts.py       Fund chart generation
generate_toggle_chart.py Interactive toggle charts
generate_market_commentary.py  LLM market commentary
generate_pdf_report.py   PDF report generation
feature_dashboard_gen.py Feature importance dashboard

# Infrastructure
snapshot_engine.py       Ticker snapshot caching engine
data_utils.py            Shared data utilities
news_store.py            News headline storage
record_predictions.py    Prediction logging
model_leaderboard.py     Model performance leaderboard
model_ranking.py         Model ranking system

# Services / providers
services/                Auth, email, market board, ticker page, news ranking
providers/               OpenBB data provider integration
static/                  Web frontend (HTML, CSS, JS)
config/                  Portfolio and universe configuration
models/                  Trained model artifacts
```

---

## Setup

### 1. Install dependencies

PyTorch must be installed first (GPU build for CUDA 12.1):

```bash
pip install torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements.txt
```

### 2. Configure secrets

Create `epm_secrets.py` and `config/ycharts_creds.json` (not included — contain API keys and credentials).

### 3. Run the pipeline

```bash
python monitor.py        # Full daily pipeline
python post_run.py       # Post-pipeline DL inference + prediction logging
```

### 4. Start the web server

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

---

## Models

| Model | File | Description |
|-------|------|-------------|
| Fama-French | `fama_french_model.py` | 3-factor risk model |
| Linear Panel | `linear_model.py` | Panel regression across fund universe |
| ML | `ml_model.py` | Gradient boosting ensemble |
| Deep Learning | `deep_learning_model.py` | TCN with gated feature lifecycle |
| Institutional | `institutional_model.py` | Institutional flow signals |

The DL model uses a gated feature promotion pipeline — new features must pass evaluation in `feature_tester.py` before being promoted to production via `feature_promoter.py`.

---

## Tech Stack

- **Backend:** FastAPI, Python 3.12
- **ML/DL:** PyTorch, scikit-learn, pandas, numpy
- **Data:** YCharts (scraper), yfinance, OpenBB, Fama-French factors
- **Frontend:** Vanilla JS, Plotly (CDN), custom CSS
- **Deployment:** Linux server, systemd service (`epm.service`)
