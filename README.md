# EPM Market Intelligence

A quantitative market intelligence pipeline and web application that aggregates fund data, runs multi-model forecasts, and serves results through a live web dashboard.

Live at: [epm-market-intelligence.com](https://epm-market-intelligence.com)

---

## What It Does

The pipeline runs daily and produces forecasts, market commentary, and dashboards for a universe of funds and indices. It covers:

- **Data ingestion** - scrapes fund data from YCharts, pulls Fama-French factors, fetches news headlines and sentiment
- **Multi-model forecasting** - five model families run in parallel: Fama-French, Linear Panel, ML (gradient boosting), Deep Learning (TCN), and Institutional
- **MAG7 analysis** - dedicated forecasting for the Magnificent 7 mega-cap stocks
- **Market commentary** - LLM-generated daily narrative summaries
- **Web dashboard** - FastAPI backend serving a live UI with fund search, forecasting charts, portfolio views, and market boards

---

## Contributors

This is an AI-assisted, vibe-coded market intelligence app built through iterative human direction and agentic development.

- **David / project owner** - product direction, research goals, operating decisions, and validation priorities.
- **Codex** - codebase navigation, implementation, testing, cleanup, GitNexus-aware impact checks, and PyTorch deep-learning experimentation.
- **Claude** - prior agent contributions across architecture notes, handoff records, implementation support, and repo guidance.

Human review remains required before treating model output, trading signals, commentary, or generated code as production-grade.

---

## Project Structure

```text
app.py                   FastAPI web server (entry point)
monitor.py               Daily pipeline orchestrator
post_run.py              Post-pipeline tasks (DL inference, prediction logging)
universe_config.py       Fund universe definition
requirements.txt         Python dependency list

# Core model modules
fama_french_model.py     Fama-French 3-factor model
linear_model.py          Linear panel regression
ml_model.py              Gradient boosting model
deep_learning_model.py   TCN (Temporal Convolutional Network) model
institutional_model.py   Institutional flow model
arimax_model.py          ARIMAX time-series model
quantconnect_model.py    QuantConnect integration model

# DL research and evaluation scripts
dl_*                     Deep-learning experiments, calibration, ensembles, and walk-forward testing
build_*                  Training and directional feature panel builders

# Data pipeline
data_arbiter.py          Unified data ingestion coordinator
scrape_ycharts.py        YCharts scraper
features.py              Feature engineering
fama_french.py           Fama-French factor processing
fetch_enrichment.py      News and sentiment enrichment
update_sentiment.py      Sentiment score updates

# Feature pipeline
feature_registry.py      Approved feature registry
dl_feature_gate.py       Feature promotion gating
feature_tester.py        Feature evaluation harness
feature_promoter.py      Promotes tested features to production
feature_validator.py     Feature integrity validation
feature_drift_monitor.py Monitors for feature drift

# App support
services/                Auth, email, market board, ticker page, news ranking
providers/               OpenBB data provider integration
static/                  Web frontend (HTML, CSS, JS)
config/                  Portfolio and universe configuration
models/                  Trained model artifacts

# Project records and generated references
notes/                   Testing journals and durable project notes
notes/handoffs/          Detailed agent handoff records
docs/reports/            Archived generated PDFs and design reports
docs/assets/screenshots/ UI verification screenshots
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

Create `epm_secrets.py` and `config/ycharts_creds.json`. These are intentionally not included because they contain API keys and credentials.

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

The DL model uses a gated feature promotion pipeline. New features must pass evaluation in `feature_tester.py` before being promoted to production via `feature_promoter.py`.

---

## Tech Stack

- **Backend:** FastAPI, Python 3.12
- **ML/DL:** PyTorch, scikit-learn, pandas, numpy
- **Data:** YCharts scraper, yfinance, OpenBB, Fama-French factors
- **Frontend:** Vanilla JS, Plotly CDN, custom CSS
- **Deployment:** Linux server, systemd service (`epm.service`)
