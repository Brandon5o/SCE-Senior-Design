#app.py
import os
import sys

# Locate Team 2 folder
PROJECT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

TEAM2_DIR = os.path.join(
    PROJECT_DIR,
    "Team 2 - Database"
)

sys.path.insert(0, TEAM2_DIR)

# Standard imports
import io
import re

import pandas as pd
import pdfplumber
import numpy as np
import plotly.express as px
import streamlit as st

from sqlalchemy import create_engine

# Import Team 2 modules
from database import DB_URL
from normalizer import clean_and_normalize_loading

# Severity labels (newer normalizer versions); optional
try:
    from normalizer import classify_severity
except ImportError:
    classify_severity = None


# ---------------------------------------------------------
# PAGE CONFIGURATION
# ---------------------------------------------------------

st.set_page_config(
    page_title="SCE Transmission Findings",
    page_icon="assets/sce.png",
    layout="wide"
)

st.title("SCE Transmission Planning Findings")

st.caption(
    "Analytics Dashboard"
)


# ---------------------------------------------------------
# REQUIRED COLUMNS
# ---------------------------------------------------------

REQUIRED = [
    "report",
    "report_date",
    "facility",
    "contingency",
    "scenario",
    "loading_pct",
    "severity",
    "mitigation",
    "source_page"
]

# The pipeline stores a contingency category (P1, P6, P2/P4 ...) in
# "contingency" and the full contingency text in
# "contingency_description". Pairs are grouped on the full text so that
# different P6 events on the same facility are not merged.


# ---------------------------------------------------------
# DATABASE CONNECTION
# ---------------------------------------------------------

def load_database_findings():

    engine = create_engine(
        DB_URL,
        connect_args={"check_same_thread": False}
    )

    query = """
        SELECT
            r.title AS report,
            r.publication_date AS report_date,

            r.study_area AS study_area,

            f.canonical_name AS facility,

            c.contingency_code AS contingency,

            findings.contingency_description_raw
                AS contingency_description,

            s.scenario_name AS scenario,

            findings.raw_value AS loading_pct,

            findings.parsed_value AS loading_numeric,

            findings.status_flag AS loading_status,

            findings.severity AS severity,

            findings.confidence_score AS confidence_score,

            findings.requires_review AS requires_review,

            COALESCE(
                m.mitigation_text,
                'Not specified'
            ) AS mitigation,

            e.page_number AS source_page,

            e.table_reference AS source_table

        FROM findings

        JOIN reports r
            ON findings.report_id = r.id

        JOIN facilities f
            ON findings.facility_id = f.id

        JOIN contingencies c
            ON findings.contingency_id = c.id

        JOIN scenarios s
            ON findings.scenario_id = s.id

        LEFT JOIN mitigations m
            ON findings.mitigation_id = m.id

        LEFT JOIN evidence e
            ON findings.id = e.finding_id

        ORDER BY
            r.title,
            f.canonical_name,
            findings.source_page
    """

    try:

        df = pd.read_sql_query(query, engine)

        return df

    finally:

        engine.dispose()


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def shorten(text, limit):

    text = str(text)

    return text if len(text) <= limit else text[:limit - 3] + "..."


# ---------------------------------------------------------
# PDF LAYOUT (CAISO thermal overload tables)
# ---------------------------------------------------------
# 0 Overloaded Facility | 1 Contingency | 2 Category |
# 3 Category Description | 4-14 eleven scenario columns |
# 15 Project & Potential Mitigation Solutions

SCENARIOS = [
    "B1 2028 Summer Peak",
    "B2 2031 Summer Peak",
    "B3 2036 Summer Peak",
    "B4 2041 Summer Peak",
    "B5 2036 Summer-Off Peak",
    "B6 2041 Winter Peak",
    "B7 2028 Spring Off-Peak",
    "B8 2031 Spring Off-Peak",
    "S1 2031 SP High CEC Load",
    "S2 2028 SP High Renewable",
    "S3 2028 SprOP ES-Charging",
]

COL_FACILITY = 0
COL_CONTINGENCY = 1
COL_CATEGORY = 2
COL_CATEGORY_DESC = 3
FIRST_SCENARIO_COL = 4
COL_MITIGATION = FIRST_SCENARIO_COL + len(SCENARIOS)
EXPECTED_COLS = COL_MITIGATION + 1

CATEGORY_RE = re.compile(r"^(P[0-7](/P[0-7])?|N\d)$")

THERMAL_PAGE_MARKER = "Thermal Overloads"


def clean_text(value):

    if value is None:
        return ""

    return " ".join(str(value).split()).strip()


def clean_cell(value):
    """Clean a multi-line PDF cell ('Lugo-' + 'Mohave' -> 'Lugo-Mohave')."""

    if value is None:
        return ""

    text = clean_text(str(value).replace("-\n", "-"))

    return re.sub(r"^l i n e _", "line_", text)


def read_table_rows(table, last_facility=""):
    """
    One dict per data row of a pdfplumber Table.

    Facility cells are merged in the report: the facility is carried
    down from the row above. Mitigation cells are merged too: the text
    is assigned to every row inside the merged cell's bounding box.
    """

    data = table.extract()

    if not data:
        return []

    row_boxes = []
    mitigation_spans = []

    for i, row in enumerate(table.rows):

        cells = row.cells

        row_boxes.append(
            cells[COL_CONTINGENCY] if len(cells) > COL_CONTINGENCY else None
        )

        if len(cells) > COL_MITIGATION and cells[COL_MITIGATION]:

            text = (
                clean_cell(data[i][COL_MITIGATION])
                if i < len(data) and len(data[i]) > COL_MITIGATION
                else ""
            )

            if text:
                box = cells[COL_MITIGATION]
                mitigation_spans.append((box[1], box[3], text))

    rows = []

    for i, raw in enumerate(data):

        if not raw or len(raw) < EXPECTED_COLS:
            continue

        category = clean_text(raw[COL_CATEGORY]).upper()

        # Skips header rows, notes and anything that is not a finding
        if not CATEGORY_RE.match(category):
            continue

        facility = clean_cell(raw[COL_FACILITY])

        inherited = False

        if facility:
            last_facility = facility
        else:
            facility = last_facility
            inherited = True

        mitigation = clean_cell(raw[COL_MITIGATION])

        if not mitigation and row_boxes[i] is not None:

            y = (row_boxes[i][1] + row_boxes[i][3]) / 2.0

            for top, bottom, text in mitigation_spans:

                if top - 1 <= y <= bottom + 1:
                    mitigation = text
                    break

        rows.append({
            "facility": facility,
            "facility_inherited": inherited,
            "contingency": clean_cell(raw[COL_CONTINGENCY]),
            "category": category,
            "loadings": [
                clean_cell(raw[FIRST_SCENARIO_COL + n])
                for n in range(len(SCENARIOS))
            ],
            "mitigation": mitigation
        })

    return rows


# ---------------------------------------------------------
# PDF PARSING (uploaded reports)
# ---------------------------------------------------------

MONTHS = (
    "January|February|March|April|May|June|July|August|"
    "September|October|November|December"
)


def read_report_metadata(first_page_text, file_name):
    """Report title and publication date, read from the PDF itself."""

    cycle = re.search(r"\b(20\d{2}-20\d{2})\b", first_page_text)

    area = re.search(
        r"Study Area:\s*(.+?)(?:,\s*covering|\n|$)",
        first_page_text
    )

    date = re.search(
        rf"\b({MONTHS})\s+\d{{1,2}},\s+20\d{{2}}\b",
        first_page_text
    )

    parts = []

    if cycle:
        parts.append(cycle.group(1))

    if area:
        parts.append(area.group(1).strip())

    title = (
        "SCE " + " ".join(parts)
        if parts
        else os.path.splitext(file_name)[0]
    )

    report_date = (
        pd.to_datetime(date.group(0), errors="coerce")
        if date
        else pd.NaT
    )

    return title, report_date


@st.cache_data(show_spinner=False)
def parse_report_pdf(pdf_bytes, file_name):
    """
    Extract thermal overload findings from one uploaded PDF.

    Returns a DataFrame in the same shape as the shared database,
    plus the number of thermal pages that were read.
    """

    records = []

    thermal_pages = 0

    last_facility = ""

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:

        first_text = (pdf.pages[0].extract_text() or "") if pdf.pages else ""

        report_title, report_date = read_report_metadata(
            first_text,
            file_name
        )

        for page_idx, page in enumerate(pdf.pages):

            page_num = page_idx + 1

            if THERMAL_PAGE_MARKER not in (page.extract_text() or ""):
                continue

            thermal_pages += 1

            for table_idx, table in enumerate(page.find_tables()):

                source_table = f"Table {table_idx + 1}"

                rows = read_table_rows(table, last_facility)

                if rows:
                    last_facility = rows[-1]["facility"]

                for item in rows:

                    for n, scenario_name in enumerate(SCENARIOS):

                        raw_loading = item["loadings"][n]

                        parsed, status = clean_and_normalize_loading(
                            raw_loading
                        )

                        # "< 100" means no overload in this scenario
                        if status in ("BELOW_LIMIT", "MISSING"):
                            continue

                        confidence = 0.95

                        if item["facility_inherited"]:
                            confidence -= 0.05

                        needs_review = status in (
                            "NOT_CONVERGED",
                            "UNKNOWN"
                        )

                        if needs_review:
                            confidence -= 0.25

                        records.append({
                            "report": report_title,
                            "report_date": report_date,
                            "facility": item["facility"] or "Unknown Facility",
                            "contingency": item["category"],
                            "contingency_description": item["contingency"],
                            "scenario": scenario_name,
                            "loading_pct": raw_loading,
                            "loading_numeric": parsed,
                            "loading_status": status,
                            "severity": (
                                classify_severity(parsed, status)
                                if classify_severity else None
                            ),
                            "confidence_score": max(confidence, 0.0),
                            "requires_review": needs_review,
                            "mitigation": item["mitigation"] or "Not specified",
                            "source_page": page_num,
                            "source_table": source_table
                        })

    return pd.DataFrame(records, columns=REQUIRED + [
        "contingency_description",
        "loading_numeric",
        "loading_status",
        "confidence_score",
        "requires_review",
        "source_table"
    ]), thermal_pages


# ---------------------------------------------------------
# DATA SOURCE SELECTION
# ---------------------------------------------------------

with st.sidebar:

    st.header("Data Source")

    data_source = st.radio(
        "Select data source",
        [
            "Shared Database",
            "Upload PDF"
        ]
    )


if data_source == "Shared Database":

    try:

        raw = load_database_findings()

        source_label = "Shared SQLite Database"

        if raw.empty:

            st.warning(
                "The database contains no findings. "
                "Run Team 1's pipeline.py first."
            )

            st.stop()

    except Exception as exc:

        st.error(
            f"Could not connect to database: {exc}"
        )

        st.stop()


else:

    uploaded_files = st.sidebar.file_uploader(
        "Upload SCE transmission planning report(s)",
        type=["pdf"],
        accept_multiple_files=True
    )

    if not uploaded_files:

        st.info(
            "Upload one or more report PDFs to continue. Several "
            "reports enable the cross-report comparison."
        )

        st.stop()

    frames = []

    for uploaded in uploaded_files:

        try:

            with st.spinner(f"Reading {uploaded.name}..."):

                parsed_df, thermal_pages = parse_report_pdf(
                    uploaded.getvalue(),
                    uploaded.name
                )

        except Exception as exc:

            st.error(f"Could not read {uploaded.name}: {exc}")

            continue

        if parsed_df.empty:

            st.warning(
                f"No thermal overload findings found in {uploaded.name}. "
                f"({thermal_pages} thermal page(s) detected.) The parser "
                "expects the CAISO Transmission Planning Process "
                "thermal overload table layout."
            )

            continue

        frames.append(parsed_df)

    if not frames:

        st.stop()

    raw = pd.concat(frames, ignore_index=True)

    source_label = ", ".join(f.name for f in uploaded_files)




# ---------------------------------------------------------
# VALIDATE DATA
# ---------------------------------------------------------

missing = sorted(
    set(REQUIRED) - set(raw.columns)
)

if missing:

    st.error(
        "Missing required columns: "
        + ", ".join(missing)
    )

    st.stop()


# ---------------------------------------------------------
# DATA CLEANING
# ---------------------------------------------------------

df = raw.copy()

if "study_area" not in df.columns:
    df["study_area"] = "Unknown"
df["study_area"] = df["study_area"].fillna("Unknown").astype(str)

df["report_date"] = pd.to_datetime(
    df["report_date"],
    errors="coerce"
)

# Preserve the original loading values.
df["loading_raw"] = (
    df["loading_pct"]
    .fillna("")
    .astype(str)
    .str.strip()
)

# Normalize values consistently.
normalized = df["loading_raw"].apply(
    clean_and_normalize_loading
)

if "loading_numeric" in df.columns:

    # Use database-normalized values when available.
    df["loading_numeric"] = pd.to_numeric(
        df["loading_numeric"],
        errors="coerce"
    )

else:

    df["loading_numeric"] = normalized.apply(
        lambda result: result[0]
    )


if "loading_status" in df.columns:

    df["loading_status"] = df["loading_status"].fillna(
        normalized.apply(lambda result: result[1])
    )

else:

    df["loading_status"] = normalized.apply(
        lambda result: result[1]
    )


# Full contingency text (falls back to the category / code)
if "contingency_description" not in df.columns:

    df["contingency_description"] = df["contingency"]

df["contingency_description"] = (
    df["contingency_description"]
    .fillna(df["contingency"])
    .astype(str)
)

# Clean text columns.
for col in [
    "report",
    "study_area",
    "facility",
    "contingency",
    "scenario",
    "mitigation"
]:

    df[col] = (
        df[col]
        .fillna("Unknown")
        .astype(str)
    )


df["severity"] = (
    df["severity"]
    .fillna("Unclassified")
    .astype(str)
)

df["source_page"] = df["source_page"].fillna(
    "Unknown"
).astype(str)

if "requires_review" not in df.columns:

    df["requires_review"] = False

if "confidence_score" not in df.columns:

    df["confidence_score"] = np.nan

if "source_table" not in df.columns:

    df["source_table"] = "Unknown"

df["overload"] = df["loading_numeric"].gt(100)


# ---------------------------------------------------------
# SIDEBAR FILTERS
# ---------------------------------------------------------

with st.sidebar:

    st.divider()

    st.header("Filters")

    reports = sorted(
        df["report"].unique()
    )

    chosen_reports = st.multiselect(
        "Reports",
        reports,
        default=reports
    )

    facilities = sorted(
        df.loc[
            df["report"].isin(chosen_reports),
            "facility"
        ].unique()
    )

    chosen_facilities = st.multiselect(
        "Facilities",
        facilities,
        default=facilities
    )

<<<<<<< HEAD
    main_area_options = sorted(df["study_area"].dropna().unique()) or ["Unknown"]
    main_area_default = next(
        (idx for idx, area in enumerate(main_area_options) if "main" in area.lower()),
        0
    )
    main_area = st.selectbox(
        "Main area for summary",
        main_area_options,
        index=main_area_default
    )
=======
    categories = sorted(
        df["contingency"].unique()
    )

    chosen_categories = st.multiselect(
        "Contingency category",
        categories,
        default=categories
    )

>>>>>>> 92a0271beb0e551c4745a7076956cf9b0f046eb3
    severity_vals = sorted(
        df["severity"].unique()
    )

    chosen_severity = st.multiselect(
        "Severity",
        severity_vals,
        default=severity_vals
    )

    threshold = st.slider(
        "Overload threshold (%)",
        min_value=100,
        max_value=150,
        value=100,
        help=(
            "Only loadings at or above 100% are stored, because the "
            "report prints '< 100' for everything below that."
        )
    )


# ---------------------------------------------------------
# APPLY FILTERS
# ---------------------------------------------------------

view = df[
    df["report"].isin(chosen_reports)
    &
    df["facility"].isin(chosen_facilities)
    &
    df["contingency"].isin(chosen_categories)
    &
    df["severity"].isin(chosen_severity)
].copy()

view["overload"] = view["loading_numeric"].ge(
    threshold
)


if view.empty:

    st.warning(
        "No findings match the selected filters."
    )

    st.stop()


st.caption(
    f"Data source: {source_label} | "
    f"{len(view):,} findings shown | "
    "Original loading values are retained."
)


# ---------------------------------------------------------
# SUMMARY METRICS
# ---------------------------------------------------------

numeric = view["loading_numeric"].dropna()

m1, m2, m3, m4 = st.columns(4)

m1.metric(
    "Main Area Findings",
    f"{int(view['study_area'].eq(main_area).sum()):,}"
)

m2.metric(
    f"At or above {threshold}%",
    f"{int(view['overload'].sum()):,}"
)

m3.metric(
    "Facilities",
    f"{view['facility'].nunique():,}"
)

m4.metric(
    "Peak Loading",
    f"{numeric.max():.1f}%"
    if not numeric.empty
    else "N/A"
)


# ---------------------------------------------------------
# RECURRENCE CALCULATIONS
# ---------------------------------------------------------

# Scenarios in which each facility/contingency pair is at or above
# the threshold (the report publishes one loading per scenario).
overloaded_scenarios = (
    view[view["overload"]]
    .groupby(["facility", "contingency_description"])["scenario"]
    .nunique()
    .rename("scenarios_overloaded")
)

recurrence = view.groupby(
    ["facility", "contingency", "contingency_description"],
    dropna=False
).agg(

    recurrence_reports=(
        "report",
        "nunique"
    ),

    occurrences=(
        "report",
        "size"
    ),

    peak_loading=(
        "loading_numeric",
        "max"
    ),

    mean_loading=(
        "loading_numeric",
        "mean"
    ),

    high_severity=(
        "severity",
        lambda s: s.str.lower().str.contains(
            "high|severe|critical"
        ).sum()
    ),

    mitigation=(
        "mitigation",
        "first"
    )

).reset_index()

recurrence = recurrence.merge(
    overloaded_scenarios.reset_index(),
    on=["facility", "contingency_description"],
    how="left"
)

recurrence["scenarios_overloaded"] = (
    recurrence["scenarios_overloaded"].fillna(0).astype(int)
)

# Screening metric, not an engineering risk score.
recurrence["persistence_score"] = (
    recurrence["recurrence_reports"]
    *
    (
        recurrence["peak_loading"]
        .fillna(0)
        .clip(lower=0) / 100
    )
    *
    (
        1
        + recurrence["high_severity"]
        + recurrence["scenarios_overloaded"]
    )
)

recurrence["label"] = (
    recurrence["facility"].apply(lambda t: shorten(t, 30))
    + " | "
    + recurrence["contingency_description"].apply(
        lambda t: shorten(t, 45)
    )
)

recurrence = recurrence.sort_values(
    ["persistence_score", "peak_loading"],
    ascending=False
)


# ---------------------------------------------------------
# DASHBOARD TABS
# ---------------------------------------------------------

tab_overview, tab_findings, tab_recurrence, tab_compare = st.tabs(
    [
        "Overview",
        "Findings",
        "Recurrence & Ranking",
        "Comparisons"
    ]
)


# =========================================================
# TAB 1: OVERVIEW
# =========================================================

with tab_overview:

    left, right = st.columns(2)

    with left:

        chart_df = view.dropna(subset=["loading_numeric"]).copy()

        if chart_df.empty:

            st.info("No numerical loading values available.")

        else:

            # Peak loading per facility and report
            peaks = (
                chart_df
                .groupby(["facility", "report"], as_index=False)
                ["loading_numeric"]
                .max()
            )

            top_facilities = (
                peaks.groupby("facility")["loading_numeric"]
                .max()
                .sort_values(ascending=False)
                .head(12)
                .index
            )

            peaks = peaks[peaks["facility"].isin(top_facilities)].copy()

            peaks["facility_label"] = peaks["facility"].apply(
                lambda name: shorten(name, 42)
            )

            fig = px.bar(
                peaks,
                x="loading_numeric",
                y="facility_label",
                color="report",
                hover_data={
                    "facility": True,
                    "loading_numeric": ":.1f",
                    "facility_label": False
                },
                barmode="group",
                orientation="h",
                labels={
                    "loading_numeric": "Peak Loading (%)",
                    "facility_label": "Facility",
                    "report": "Report"
                },
                title="Highest Peak Loadings by Facility"
            )

            fig.add_vline(
                x=threshold,
                line_dash="dash",
                line_color="red",
                annotation_text=f"Threshold {threshold}%",
                annotation_position="top"
            )

            fig.update_layout(
                height=max(380, 38 * peaks["facility"].nunique()),
                margin=dict(l=20, r=20, t=75, b=35),
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="left",
                    x=0
                ),
                yaxis=dict(
                    title=None,
                    automargin=True,
                    tickfont=dict(size=10),
                    categoryorder="total ascending"
                ),
                xaxis=dict(title="Peak Loading (%)", rangemode="tozero")
            )

            if chart_df["facility"].nunique() > 12:

                st.caption(
                    "Showing the 12 facilities with the highest peak "
                    "loading; full results remain in the Findings tab."
                )

            st.plotly_chart(fig, use_container_width=True)

    with right:

        # The report does not publish severity. When nothing is
        # classified, break findings down by contingency category.
        if view["severity"].nunique() == 1 and (
            view["severity"].iloc[0] == "Unclassified"
        ):
            pie_col = "contingency"
            pie_title = "Findings by Contingency Category"
        else:
            pie_col = "severity"
            pie_title = "Findings by Severity"

        counts = (
            view.groupby(pie_col, as_index=False)
            .size()
            .rename(columns={"size": "findings"})
        )

        fig = px.pie(
            counts,
            names=pie_col,
            values="findings",
            title=pie_title,
            hole=0.35
        )

        fig.update_layout(
            height=420,
            margin=dict(l=15, r=15, t=60, b=25),
            legend=dict(
                orientation="h",
                yanchor="top",
                y=-0.05,
                xanchor="center",
                x=0.5
            )
        )

        st.plotly_chart(fig, use_container_width=True)

<<<<<<< HEAD
    area_counts = view.groupby("study_area", as_index=False).size().rename(columns={"size": "findings"})
    area_counts = area_counts.sort_values("findings", ascending=False)
    st.subheader("Findings by Study Area")
    st.caption("Double-click an area bar to view its detailed findings.")
    area_fig = px.bar(
        area_counts,
        x="findings",
        y="study_area",
        orientation="h",
        custom_data=["study_area"],
        labels={"findings": "Findings", "study_area": "Study Area"},
        title="Total Findings by Study Area"
    )
    area_fig.update_layout(
        height=max(260, 42 * len(area_counts)),
        margin=dict(l=20, r=20, t=60, b=25),
        yaxis=dict(title=None, automargin=True),
        xaxis=dict(title="Findings", rangemode="tozero")
    )
    area_event = st.plotly_chart(
        area_fig,
        use_container_width=True,
        key="study_area_findings_chart",
        on_select="rerun",
        selection_mode="points"
    )
    selected_points = area_event.selection.points
    if selected_points:
        selected_area = selected_points[-1].get("customdata", [None])[0]
        if selected_area in set(view["study_area"]):
            area_detail = view[view["study_area"] == selected_area].copy()
            st.markdown(f"#### {selected_area} — Detailed View")
            detail_a, detail_b, detail_c = st.columns(3)
            detail_a.metric("Findings", f"{len(area_detail):,}")
            area_facility_count = area_detail["facility"].nunique()
            detail_b.metric("Facilities", f"{area_facility_count:,}")
            area_peak = area_detail["loading_numeric"].max()
            detail_c.metric("Peak Loading", f"{area_peak:.1f}%" if pd.notna(area_peak) else "N/A")
            detail_cols = [
                "report", "facility", "contingency", "scenario",
                "loading_raw", "severity", "mitigation", "source_page"
            ]
            st.dataframe(
                area_detail[detail_cols].sort_values(["report", "facility", "contingency"]),
                use_container_width=True,
                hide_index=True
            )

    st.subheader("Mitigation Options")
    st.caption("Mitigation describes a proposed action to reduce a transmission constraint, such as a system upgrade or operating change.")
=======
    # -----------------------------------------------------
    # Findings by scenario
    # -----------------------------------------------------

    st.subheader("Overloads by Scenario")

    scenario_counts = (
        view[view["overload"]]
        .groupby(["scenario", "report"], as_index=False)
        .size()
        .rename(columns={"size": "findings"})
    )

    if scenario_counts.empty:

        st.info("No findings at or above the threshold.")

    else:

        fig = px.bar(
            scenario_counts,
            x="scenario",
            y="findings",
            color="report",
            barmode="group",
            labels={
                "scenario": "Scenario",
                "findings": "Findings at or above threshold"
            },
            title=f"Findings at or above {threshold}% by Scenario"
        )

        fig.update_layout(
            height=420,
            margin=dict(l=20, r=20, t=60, b=30),
            xaxis=dict(tickangle=-35)
        )

        st.plotly_chart(fig, use_container_width=True)

    # -----------------------------------------------------
    # Mitigations
    # -----------------------------------------------------

    st.subheader("Most Common Mitigation Descriptions")

>>>>>>> 92a0271beb0e551c4745a7076956cf9b0f046eb3
    mitigation_counts = (
        view.groupby("mitigation", as_index=False)
        .size()
        .sort_values("size", ascending=False)
        .head(10)
    )
<<<<<<< HEAD
    mitigation_counts["mitigation_label"] = mitigation_counts["mitigation"].apply(
        lambda text: text if len(text) <= 46 else text[:43] + "..."
    )
=======

    mitigation_counts["mitigation_label"] = mitigation_counts[
        "mitigation"
    ].apply(lambda text: shorten(text, 58))

>>>>>>> 92a0271beb0e551c4745a7076956cf9b0f046eb3
    fig = px.bar(
        mitigation_counts.sort_values("size"),
        x="size",
        y="mitigation_label",
        orientation="h",
        hover_data={
            "mitigation": True,
            "size": True,
            "mitigation_label": False
        },
        labels={"size": "Findings", "mitigation_label": "Mitigation"},
        title="Most Common Mitigation Options"
    )

    fig.update_layout(
        height=max(360, 48 * len(mitigation_counts)),
        margin=dict(l=20, r=20, t=60, b=30),
        yaxis=dict(title=None, automargin=True, tickfont=dict(size=10)),
        xaxis=dict(title="Findings", rangemode="tozero")
    )

    st.plotly_chart(fig, use_container_width=True)
<<<<<<< HEAD
=======


>>>>>>> 92a0271beb0e551c4745a7076956cf9b0f046eb3
# =========================================================
# TAB 2: FINDINGS
# =========================================================

with tab_findings:

    st.subheader("Extracted Transmission Findings")

    cols = [
        "report",
        "report_date",
        "facility",
        "contingency",
        "contingency_description",
        "scenario",
        "loading_raw",
        "loading_status",
        "severity",
        "mitigation",
        "source_page",
        "source_table"
    ]

    st.dataframe(
        view[cols].sort_values(
            ["report", "facility", "contingency_description"]
        ),
        use_container_width=True,
        hide_index=True
    )

    st.subheader("Findings Requiring Human Review")

    review_df = view[
        view["requires_review"].fillna(False).astype(bool)
    ]

    if review_df.empty:

        st.success(
            "No findings are currently flagged for review."
        )

    else:

        review_cols = [
            "facility",
            "contingency_description",
            "scenario",
            "loading_raw",
            "source_page",
            "confidence_score"
        ]

        st.dataframe(
            review_df[review_cols],
            use_container_width=True,
            hide_index=True
        )

    st.download_button(
        "Download Filtered Findings CSV",
        view[["report", "report_date", "facility", "contingency", "scenario", "loading_raw", "loading_status", "severity", "mitigation", "source_page", "source_table"]].to_csv(index=False).encode("utf-8"),
        "filtered_findings.csv",
        "text/csv"
    )


# =========================================================
# TAB 3: RECURRENCE AND RANKING
# =========================================================

with tab_recurrence:

    st.subheader("Facility Recurrence Analysis")

    st.caption(
        "Persistence ranks facility/contingency pairs using "
        "report recurrence, peak loading, the number of scenarios "
        "at or above the threshold, and high/critical severity "
        "counts. This is a screening metric, "
        "not an engineering risk score."
    )

    st.dataframe(
        recurrence.drop(columns=["label"]),
        use_container_width=True,
        hide_index=True
    )

    chart_recurrence = recurrence.head(15).sort_values(
        "persistence_score"
    )

    fig = px.bar(
        chart_recurrence,
        x="persistence_score",
        y="label",
        color="scenarios_overloaded",
        orientation="h",
        hover_data=[
            "facility",
            "contingency_description",
            "peak_loading",
            "scenarios_overloaded",
            "occurrences"
        ],
        labels={
            "label": "Facility | Contingency",
            "persistence_score": "Persistence Score",
            "scenarios_overloaded": "Scenarios overloaded"
        },
        title="Highest Persistence Scores"
    )

    fig.update_layout(
        height=max(420, 34 * len(chart_recurrence)),
        yaxis=dict(title=None, automargin=True, tickfont=dict(size=10))
    )

    st.plotly_chart(
        fig,
        use_container_width=True
    )


# =========================================================
# TAB 4: COMPARISONS
# =========================================================

with tab_compare:

    st.subheader("Baseline vs. Sensitivity")

    scenarios = sorted(
        view["scenario"].unique()
    )

    if len(scenarios) < 2:

        st.info("At least two scenarios are needed for a comparison.")

    else:

        default_base = next(
            (s for s in scenarios if s.startswith("B1")),
            scenarios[0]
        )

        default_sens = next(
            (s for s in scenarios if s.startswith("S2")),
            scenarios[1]
        )

        base = st.selectbox(
            "Baseline Scenario",
            scenarios,
            index=scenarios.index(default_base),
            key="base"
        )

        sensitivity = st.selectbox(
            "Sensitivity Scenario",
            scenarios,
            index=scenarios.index(default_sens),
            key="sens"
        )

        st.caption(
            "Only loadings at or above 100% are stored. A blank cell "
            "means the report printed '< 100' for that scenario, or "
            "the case did not converge."
        )

        paired = view[
            view["scenario"].isin(
                [base, sensitivity]
            )
        ].pivot_table(
            index=["facility", "contingency_description"],
            columns="scenario",
            values="loading_numeric",
            aggfunc="max"
        ).reset_index()

        if base in paired.columns and sensitivity in paired.columns:

            paired["change_pct_points"] = (
                paired[sensitivity] - paired[base]
            )

            st.dataframe(
                paired,
                use_container_width=True,
                hide_index=True
            )

            chart_paired = paired.dropna(
                subset=["change_pct_points"]
            ).copy()

            if chart_paired.empty:

                st.info(
                    "No facility/contingency pair has a stored loading "
                    "in both scenarios."
                )

            else:

                chart_paired["label"] = (
                    chart_paired["facility"].apply(
                        lambda t: shorten(t, 30)
                    )
                    + " | "
                    + chart_paired["contingency_description"].apply(
                        lambda t: shorten(t, 40)
                    )
                )

                fig = px.bar(
                    chart_paired,
                    x="label",
                    y="change_pct_points",
                    color="change_pct_points",
                    hover_data=["facility", "contingency_description"],
                    title=f"Change: {sensitivity} minus {base}",
                    labels={
                        "label": "Facility | Contingency",
                        "change_pct_points":
                            "Loading Change (Percentage Points)"
                    }
                )

                fig.update_layout(xaxis=dict(tickangle=-45))

                st.plotly_chart(
                    fig,
                    use_container_width=True
                )

        else:

            st.info(
                "Both scenarios need numerical readings "
                "for a paired comparison."
            )

    # ---------------------------------------------
    # Cross-report comparison
    # ---------------------------------------------

    st.subheader("Cross-Report Comparison")

    cross = view.pivot_table(
        index=["facility", "contingency_description"],
        columns="report",
        values="loading_numeric",
        aggfunc="max"
    ).reset_index()

    st.dataframe(
        cross,
        use_container_width=True,
        hide_index=True
    )


# ---------------------------------------------------------
# FOOTER
# ---------------------------------------------------------

st.divider()

st.caption(
    "SCE Transmission Planning Analytics"
)

st.caption(
    "Traceability: Findings retain report, scenario, "
    "source page, and table references. Verify extracted "
    "values against the original PDF before engineering use."
<<<<<<< HEAD
)








=======
)
>>>>>>> 92a0271beb0e551c4745a7076956cf9b0f046eb3
