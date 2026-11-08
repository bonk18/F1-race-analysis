# F1 Race Strategy and Performance Analytics Platform 🏎️📊

[![CI/CD Pipeline](https://github.com/bonk18/F1-race-analysis/actions/workflows/test.yml/badge.svg)](https://github.com/bonk18/F1-race-analysis/actions)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/release/python-3110/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An end-to-end data engineering, analytics, and machine learning platform for Formula 1 race strategy. 

## Overview

This platform ingests raw telemetry and race-control data from the OpenF1 API, cleans and normalizes it using a bespoke Median Absolute Deviation (MAD) engine, and models tyre degradation and pit-stop outcomes using Gradient Boosting (LightGBM).

The ultimate goal of the platform is to answer the fundamental F1 strategy question:
> **"What is the expected net race time if we pit NOW versus pitting N laps later?"**

##  Features

- **Automated Data Ingestion**: Python-based client that syncs directly with OpenF1, handling API rate limits, caching, and database UPSERT operations.
- **Robust Data Cleaning**: A MAD-based lap classification engine that mathematically isolates pure "race pace" from VSC periods, pit-laps, and statistical outliers.
- **Machine Learning (LightGBM)**: Predicts tyre degradation (lap time decay) with a Mean Absolute Error of **0.275s**, reducing baseline prediction error by 72% by isolating track evolution and fuel burn.
- **Counterfactual Strategy Explorer**: Simulates pit-stop outcomes in real-time, accounting for average pit lane time loss, out-lap pace gains (the undercut), and multi-compound tyre wear.
- **React dashboard**: Explore race overview, driver pace, tyre degradation, pit strategy, simulation, data quality and cross-race metrics using the Python analytics.

##  Quick Start (Local Environment)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/bonk18/F1-race-analysis.git
   cd F1-race-analysis
   ```

2. **Create and activate a virtual environment:**
   ```bash
   conda create -n f1_strategy python=3.11
   conda activate f1_strategy
   ```

3. **Install dependencies:**
   ```bash
   pip install -e .
   ```

4. **Sync Data (e.g., 2024 Bahrain GP):**
   ```bash
   python -m src.ingestion.sync --year 2024 --meeting-key 1229
   ```

5. **Start the local Python API** (from the repository root):
   ```bash
   python dashboard_api.py
   ```

6. **Start the Node dashboard** in another terminal (Node 20.19+ or 22.12+):
   ```bash
   npm --prefix frontend install
   npm --prefix frontend run dev
   ```
   Open the Vite URL printed in the terminal (normally http://localhost:5173). The development server proxies `/api` to `127.0.0.1:8000`. The API is intended for local use only. The database is `data/f1_strategy.db`; sync data first if it is empty.

   Build and type-check with `npm --prefix frontend run build`. The old `dashboard/` Streamlit app is retained as a legacy reference and is not the primary UI. The strategy simulation trains on the selected session and uses estimated input features and a fixed 24-second pit loss; it is not a race prediction guarantee.

##  Architecture

```
F1-race-analysis/
├── frontend/                  # React/Vite dashboard
├── dashboard_api.py           # Local Python analytics API
├── dashboard/                 # Legacy Streamlit UI
├── data/                      # Local SQLite Database (f1_strategy.db)
├── sql/                       # Core analytical views
├── src/
│   ├── ingestion/             # OpenF1 Client & DB Loader
│   ├── cleaning/              # MAD Lap Classification Engine
│   ├── analytics/             # KPIs, Race Summary, Undercut detection
│   ├── features/              # ML Feature Engineering Pipeline
│   └── models/                # LightGBM Tyre & Pit Outcome Models
├── tests/                     # Pytest suite
└── pyproject.toml
```

##  Testing

The platform is heavily tested using `pytest`. The test suite uses offline fixture data to ensure reliability independent of the OpenF1 API.

```bash
pytest tests/
```

##  License

This project is [MIT](https://opensource.org/licenses/MIT) licensed.
