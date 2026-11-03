# SCE Transmission Planning Reliability Analysis

Project Overview

The SCE Transmission Planning Reliability Analysis project is designed to extract, organize, and analyze transmission planning data from Southern California Edison (SCE) Transmission Planning Process (TPP) reports.

The system processes PDF reports, extracts important transmission reliability information, stores the extracted data in a relational database, and presents the results through an interactive analytics dashboard.

The goal is to make transmission planning information easier to access, analyze, and compare across reports, facilities, contingencies, and study scenarios.

Project Features

- PDF Data Extraction: Extracts facility names, contingency information, loading values, scenarios, and source references from SCE PDF reports.

- Data Normalization: Standardizes extracted values while preserving original text, including values such as 119.0%, <100, and NotConv.

- Relational Database: Organizes reports, facilities, contingencies, scenarios, findings, mitigations, and evidence.

- Data Validation: Uses validation and confidence indicators to identify uncertain extractions that may require manual review.

- Interactive Dashboard: Displays transmission findings through charts, tables, filters, and comparisons.

- Recurrence Analysis: Identifies facilities and contingencies that repeatedly appear across multiple reports.

- Source Traceability: Retains report and page references to help verify extracted information against the original documents.

# How to Run:

1. Clone the Repository:
git clone https://github.com/YOUR-USERNAME/SCE-Senior-Design.git

Navigate into the project directory:
cd cd SCE-Senior-Design

2.Install dependencies:

pip install -r requirements.txt

3. Initialize the database (first time only):

python "Team 2 - Database/database.py"
python "Team 2 - Database/normalizer.py"

4. Run the PDF ingestion pipeline:

python "Team 1 - PDF Ingestion/pipeline.py"

5. Start the dashboard:

streamlit run "Team 3 - Analytics Dashboard/app.py"

Open http://localhost:8501 in your browser to view the dashboard.
