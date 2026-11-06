# Team 3 — SCE Transmission Planning Analytics Dashboard

A Streamlit dashboard for reviewing transmission planning findings from the shared Team 2 database. It supports PDF ingestion through Team 1's extraction pipeline, as well as filters, findings tables, charts, recurrence ranking, and report comparisons.

## Required downloads and folders

- **Python 3.11 or newer** — install from [python.org/downloads](https://www.python.org/downloads/) and select **Add Python to PATH** during Windows setup.
- **Dashboard and PDF packages** — installed from `requirements.txt` below: Streamlit, pandas, NumPy, Plotly, SQLAlchemy, and pdfplumber. They are installed in the `.venv` virtual environment inside this folder.
- Keep the sibling **`Team 1 - PDF Ingestion`** and **`Team 2 - Database`** folders alongside this folder. Team 3 calls Team 1's PDF pipeline and reads the shared Team 2 SQLite database.

## Install and run (Windows Command Prompt)

Open Command Prompt in this folder and run:

```bat
py -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m streamlit run app.py
```

If `.venv` already exists, skip the first command. Open the local URL printed by Streamlit in your browser. Keep Command Prompt open while using the dashboard; press `Ctrl+C` there to stop it. If `py` is not recognized, use `python` instead.

## Ingest a planning report

1. In the sidebar, select **PDF Ingestion Upload**.
2. Choose the report PDF and enter its TPP cycle and study area.
3. Click **Ingest PDF**. Team 1 extracts the report tables and stores findings and source references in the shared Team 2 database.
4. The dashboard loads the database findings so you can filter and compare them.

The uploaded PDF is held temporarily in the Team 3 folder during processing and removed afterward. Team 1's pipeline handles duplicate findings when the same report is ingested again.

The **Illustrative Demo** source remains available for a quick UI preview; those sample values are not report findings.
