import os
import sys

PROJECT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

TEAM2_DIR = os.path.join(
    PROJECT_DIR,
    "Team 2 - Database"
)

sys.path.insert(0, TEAM2_DIR)

# Standard imports
import pandas as pd
import numpy as np
import plotly.express as px
import streamlit as st

from sqlalchemy import create_engine

# Import Team 2 modules
from database import DB_URL
from normalizer import clean_and_normalize_loading


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
# REQUIRED CSV COLUMNS
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
# ILLUSTRATIVE DEMO DATA
# ---------------------------------------------------------

DEMO = pd.DataFrame([

    [
        "2026-2027 Preliminary",
        "2026-01-15",
        "Mesa 500 kV",
        "N-1: Line 1-2",
        "Summer Peak",
        "119.0%",
        "High",
        "Series compensation / reconductoring under study",
        24
    ],

    [
        "2026-2027 Preliminary",
        "2026-01-15",
        "Mesa 500 kV",
        "N-1: Line 1-2",
        "Summer Peak Sensitivity",
        "112.0%",
        "High",
        "Series compensation / reconductoring under study",
        24
    ],

    [
        "2026-2027 Preliminary",
        "2026-01-15",
        "Valley 230 kV",
        "N-1: Transformer A",
        "Summer Peak",
        "107.0%",
        "Medium",
        "Transformer replacement evaluated",
        38
    ],

    [
        "2026-2027 Preliminary",
        "2026-01-15",
        "Canyon 500 kV",
        "N-1: Line 4-5",
        "Summer Peak",
        "103.0%",
        "Low",
        "Not specified",
        51
    ],

    [
        "2025-2026 Final",
        "2025-01-10",
        "Mesa 500 kV",
        "N-1: Line 1-2",
        "Summer Peak",
        "116.0%",
        "High",
        "Reconductoring recommended",
        29
    ],

    [
        "2025-2026 Final",
        "2025-01-10",
        "Valley 230 kV",
        "N-1: Transformer A",
        "Summer Peak",
        "101.0%",
        "Low",
        "Transformer replacement evaluated",
        44
    ],

    [
        "2025-2026 Final",
        "2025-01-10",
        "Harbor 230 kV",
        "N-1: Line 8-9",
        "Summer Peak",
        "105.0%",
        "Medium",
        "Not specified",
        63
    ]

], columns=REQUIRED)


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def shorten(text, limit):

    text = str(text)

    return text if len(text) <= limit else text[:limit - 3] + "..."


# ---------------------------------------------------------
# DATA SOURCE SELECTION
# ---------------------------------------------------------

with st.sidebar:

    st.header("Data Source")

    data_source = st.radio(
        "Select data source",
        [
            "Shared Database",
            "Upload CSV",
            "Illustrative Demo"
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


elif data_source == "Upload CSV":

    uploaded = st.sidebar.file_uploader(
        "Upload normalized findings CSV",
        type=["csv"]
    )

    if uploaded is None:

        st.info("Upload a CSV file to continue.")

        st.stop()

    try:

        raw = pd.read_csv(uploaded)

        source_label = uploaded.name

    except Exception as exc:

        st.error(f"Could not read CSV: {exc}")

        st.stop()


else:

    raw = DEMO.copy()

    source_label = "Illustrative sample data"


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

    categories = sorted(
        df["contingency"].unique()
    )

    chosen_categories = st.multiselect(
        "Contingency category",
        categories,
        default=categories
    )

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
    "Total Findings",
    f"{len(view):,}"
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
        lambda s: s.str.lower().isin(
            ["high", "critical"]
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

    mitigation_counts = (
        view.groupby("mitigation", as_index=False)
        .size()
        .sort_values("size", ascending=False)
        .head(10)
    )

    mitigation_counts["mitigation_label"] = mitigation_counts[
        "mitigation"
    ].apply(lambda text: shorten(text, 58))

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
        title="Most Common Mitigation Descriptions"
    )

    fig.update_layout(
        height=max(360, 48 * len(mitigation_counts)),
        margin=dict(l=20, r=20, t=60, b=30),
        yaxis=dict(title=None, automargin=True, tickfont=dict(size=10)),
        xaxis=dict(title="Findings", rangemode="tozero")
    )

    st.plotly_chart(fig, use_container_width=True)


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
        view[cols].to_csv(index=False).encode("utf-8"),
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
)