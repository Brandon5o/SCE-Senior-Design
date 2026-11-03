# Team 3 — SCE Transmission Planning Analytics Dashboard

A Streamlit dashboard for reviewing transmission planning findings from the shared Team 2 database, with Team 1 extraction and source traceability. It includes filters, tables, charts, recurrence and persistence ranking, baseline/sensitivity comparisons, and cross-report comparisons.

## Required downloads

- **Python 3.11 or newer** — install from [python.org/downloads](https://www.python.org/downloads/) and select **Add Python to PATH** during Windows setup.
- **Dashboard packages** — installed from `requirements.txt` below: Streamlit, pandas, NumPy, Plotly, and SQLAlchemy. They will be installed in the `.venv` virtual environment inside this folder.

The dashboard also reads the Team 2 SQLite database from the sibling `Team 2 - Database` folder. Keep the Team 2 folder and database in place alongside this folder. Team 1/Team 2 deliverables should provide report-backed findings; any demo data shown in the app is illustrative.

## Install and run (Windows Command Prompt)

Open Command Prompt in this folder and run:

```bat
py -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m streamlit run app.py
```

If `.venv` already exists, you can skip the first command. The last command starts the app and prints a local URL to open in your browser. Keep Command Prompt open while using the dashboard; press `Ctrl+C` there to stop it. If `py` is not recognized, use `python` instead.

If the same `No module named 'sqlalchemy'` error appears after updating requirements, install it into this folder's environment with:

```bat
.venv\Scripts\python -m pip install -r requirements.txt
```

## CSV input format

If using CSV upload, provide one row per finding with these columns:

`report, report_date, facility, contingency, scenario, loading_pct, severity, mitigation, source_page`

The dashboard preserves raw loading values such as `119.0%`, `<100`, or `NotConv`, and calculates numeric comparisons when possible. Confirm source page references against the original report before relying on results.
