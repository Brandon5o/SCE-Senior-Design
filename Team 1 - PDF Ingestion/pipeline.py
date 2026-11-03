import os
import sys
import re
import pdfplumber

# Locate Team 2 folder
PROJECT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

TEAM2_DIR = os.path.join(
    PROJECT_DIR,
    "Team 2 - Database"
)

sys.path.insert(0, TEAM2_DIR)

# Import Team 2 modules
from database import (
    init_db,
    Report,
    Facility,
    Contingency,
    Scenario,
    Mitigation,
    Evidence,
    Finding
)

from normalizer import clean_and_normalize_loading


# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------

def get_or_create(session, model, defaults=None, **kwargs):

    instance = session.query(model).filter_by(**kwargs).first()

    if instance:
        return instance

    values = kwargs.copy()

    if defaults:
        values.update(defaults)

    instance = model(**values)

    session.add(instance)
    session.flush()

    return instance


def clean_text(value):

    if value is None:
        return ""

    return " ".join(str(value).split()).strip()


def canonicalize_facility(raw_name):

    if not raw_name:
        return "Unknown Facility"

    return clean_text(raw_name.splitlines()[0])


def extract_contingency_code(raw_text):

    match = re.search(
        r"\b(P[0-7]|N-1-1|N-1)\b",
        raw_text,
        re.IGNORECASE
    )

    if match:
        return match.group(1).upper()

    return "UNKNOWN"


def extract_year(scenario_name):

    match = re.search(r"\b(20\d{2})\b", scenario_name)

    if match:
        return int(match.group(1))

    return None


def get_confidence(facility, contingency, loading, header_detected):

    confidence = 0.95
    requires_review = False

    if not header_detected:
        confidence -= 0.20
        requires_review = True

    if not facility or facility == "Unknown Facility":
        confidence -= 0.25
        requires_review = True

    if not contingency:
        confidence -= 0.20
        requires_review = True

    if not loading:
        confidence -= 0.15
        requires_review = True

    return max(confidence, 0.0), requires_review


# ---------------------------------------------------------
# TABLE HEADER DETECTION
# ---------------------------------------------------------

def find_column(headers, possible_names):

    for index, header in enumerate(headers):

        normalized = clean_text(header).lower()

        for name in possible_names:

            if name in normalized:
                return index

    return None


def identify_columns(header_row):

    headers = [
        clean_text(value).lower()
        for value in header_row
    ]

    columns = {
        "facility": find_column(
            headers,
            ["facility name", "facility", "monitored element", "element"]
        ),

        "contingency": find_column(
            headers,
            ["contingency", "outage", "event"]
        ),

        "loading": find_column(
            headers,
            ["loading", "percent loading", "loading %", "percent"]
        ),

        "scenario": find_column(
            headers,
            ["scenario", "case name", "study case"]
        ),

        "mitigation": find_column(
            headers,
            ["mitigation", "recommended action", "solution"]
        ),

        "severity": find_column(
            headers,
            ["severity", "priority", "risk level"]
        )
    }

    required_found = all(
        columns[name] is not None
        for name in ["facility", "contingency", "loading"]
    )

    if not required_found:

        # Original demonstration mapping.
        columns["facility"] = 0
        columns["contingency"] = 1
        columns["loading"] = 2

        return columns, False

    return columns, True


def get_cell(row, index):

    if index is None or index >= len(row):
        return ""

    return clean_text(row[index])


# ---------------------------------------------------------
# MAIN INGESTION PIPELINE
# ---------------------------------------------------------

def ingest_sce_report(pdf_path, tpp_cycle, study_area):

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(
            f"PDF file not found: {pdf_path}"
        )

    Session = init_db()
    session = Session()

    inserted_count = 0
    skipped_count = 0
    review_count = 0

    try:

        file_name = os.path.basename(pdf_path)

        # ---------------------------------------------
        # Register report without duplicating it
        # ---------------------------------------------

        report = session.query(Report).filter_by(
            source_file=file_name,
            tpp_cycle=tpp_cycle,
            study_area=study_area
        ).first()

        if report is None:

            report = Report(
                title=f"SCE {tpp_cycle} {study_area}",
                source_file=file_name,
                tpp_cycle=tpp_cycle,
                study_area=study_area
            )

            session.add(report)
            session.flush()

        print(f"\nIngesting: {file_name}")
        print(f"Report ID: {report.id}")

        # ---------------------------------------------
        # Read PDF
        # ---------------------------------------------

        with pdfplumber.open(pdf_path) as pdf:

            for page_idx, page in enumerate(pdf.pages):

                page_num = page_idx + 1

                tables = page.extract_tables()

                if not tables:
                    continue

                print(
                    f"Processing page {page_num}: "
                    f"{len(tables)} table(s)"
                )

                for table_idx, table in enumerate(tables):

                    if not table or len(table) < 2:
                        continue

                    # First row is treated as the header.
                    columns, header_detected = identify_columns(
                        table[0]
                    )

                    for row_idx, row in enumerate(table[1:], start=2):

                        if not row:
                            continue

                        # ---------------------------------
                        # Extract raw fields
                        # ---------------------------------

                        raw_facility = get_cell(
                            row, columns["facility"]
                        )

                        raw_contingency = get_cell(
                            row, columns["contingency"]
                        )

                        raw_loading = get_cell(
                            row, columns["loading"]
                        )

                        raw_scenario = get_cell(
                            row, columns["scenario"]
                        )

                        raw_mitigation = get_cell(
                            row, columns["mitigation"]
                        )

                        raw_severity = get_cell(
                            row, columns["severity"]
                        )

                        # Skip empty rows
                        if not raw_facility and not raw_contingency:
                            continue

                        # Skip repeated headers
                        if raw_facility.lower() in (
                            "facility",
                            "facility name"
                        ):
                            continue

                        # ---------------------------------
                        # Normalize facility
                        # ---------------------------------

                        facility_name = canonicalize_facility(
                            raw_facility
                        )

                        # ---------------------------------
                        # Normalize loading
                        # ---------------------------------

                        parsed_value, status = clean_and_normalize_loading(
                            raw_loading
                        )

                        # ---------------------------------
                        # Extract contingency
                        # ---------------------------------

                        contingency_code = extract_contingency_code(
                            raw_contingency
                        )

                        # ---------------------------------
                        # Scenario
                        # ---------------------------------

                        if not raw_scenario:
                            raw_scenario = "Unspecified scenario"

                        scenario_year = extract_year(raw_scenario)

                        # ---------------------------------
                        # Confidence and review
                        # ---------------------------------

                        confidence, requires_review = get_confidence(
                            raw_facility,
                            raw_contingency,
                            raw_loading,
                            header_detected
                        )

                        if contingency_code == "UNKNOWN":
                            requires_review = True

                        if status in ("UNKNOWN", "MISSING"):
                            requires_review = True

                        if status == "NOT_CONVERGED":
                            requires_review = True

                        # ---------------------------------
                        # Create or retrieve facility
                        # ---------------------------------

                        facility = get_or_create(
                            session,
                            Facility,
                            canonical_name=facility_name
                        )

                        # ---------------------------------
                        # Create or retrieve contingency
                        # ---------------------------------

                        contingency = get_or_create(
                            session,
                            Contingency,
                            contingency_code=contingency_code,
                            defaults={
                                "category": contingency_code,
                                "description": raw_contingency
                            }
                        )

                        # ---------------------------------
                        # Create or retrieve scenario
                        # ---------------------------------

                        scenario = get_or_create(
                            session,
                            Scenario,
                            scenario_name=raw_scenario,
                            defaults={
                                "study_year": scenario_year
                            }
                        )

                        # ---------------------------------
                        # Create mitigation if available
                        # ---------------------------------

                        mitigation = None

                        if raw_mitigation:

                            mitigation = get_or_create(
                                session,
                                Mitigation,
                                mitigation_text=raw_mitigation
                            )

                        # ---------------------------------
                        # Prevent duplicate findings
                        # ---------------------------------

                        source_table = f"Table {table_idx + 1}"

                        existing = session.query(Finding).filter_by(
                            report_id=report.id,
                            facility_id=facility.id,
                            contingency_id=contingency.id,
                            scenario_id=scenario.id,
                            raw_value=raw_loading,
                            source_page=page_num,
                            source_table=source_table,
                            source_row=row_idx
                        ).first()

                        if existing:
                            skipped_count += 1
                            continue

                        # ---------------------------------
                        # Create finding
                        # ---------------------------------

                        finding = Finding(
                            report_id=report.id,
                            facility_id=facility.id,
                            contingency_id=contingency.id,
                            scenario_id=scenario.id,

                            mitigation_id=(
                                mitigation.id if mitigation else None
                            ),

                            facility_name_raw=raw_facility,

                            contingency_description_raw=raw_contingency,

                            raw_value=raw_loading,

                            parsed_value=parsed_value,

                            status_flag=status,

                            confidence_score=confidence,

                            requires_review=requires_review,

                            severity=raw_severity or None,

                            source_page=page_num,

                            source_table=source_table,

                            source_row=row_idx
                        )

                        session.add(finding)
                        session.flush()

                        # ---------------------------------
                        # Save source evidence
                        # ---------------------------------

                        evidence = Evidence(
                            finding_id=finding.id,
                            source_document=file_name,
                            page_number=page_num,
                            table_reference=source_table
                        )

                        session.add(evidence)

                        inserted_count += 1

                        if requires_review:
                            review_count += 1

        # ---------------------------------------------
        # Commit everything
        # ---------------------------------------------

        session.commit()

        print("\n--------------------------------")
        print("PIPELINE COMPLETED")
        print("--------------------------------")

        print(f"Inserted findings: {inserted_count}")
        print(f"Skipped duplicates: {skipped_count}")
        print(f"Requires review: {review_count}")

        print("--------------------------------\n")

    except Exception as exc:

        session.rollback()

        print(f"Pipeline error: {exc}")

        raise

    finally:

        session.close()


# ---------------------------------------------------------
# DATABASE QUERY
# ---------------------------------------------------------

def query_database():

    Session = init_db()
    session = Session()

    try:

        print("\n--- FINDINGS REQUIRING REVIEW ---")

        findings = session.query(Finding).filter_by(
            requires_review=True
        ).all()

        for finding in findings:

            print(
                f"Facility: {finding.facility.canonical_name} | "
                f"Loading: {finding.raw_value} | "
                f"Page: {finding.source_page}"
            )

        print("\n--- NUMERICAL OVERLOADS ABOVE 120% ---")

        findings = session.query(Finding).filter(
            Finding.parsed_value > 120
        ).all()

        for finding in findings:

            print(
                f"Facility: {finding.facility.canonical_name} | "
                f"Loading: {finding.parsed_value}% | "
                f"Page: {finding.source_page}"
            )

    finally:

        session.close()


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

if __name__ == "__main__":

    # Get the folder containing pipeline.py
    TEAM1_DIR = os.path.dirname(os.path.abspath(__file__))

    pdf_filename = os.path.join(
        TEAM1_DIR,
        "SCE-Main-2026-2027-Transmission-Planning-Process-Preliminary-Results.pdf"
    )

    if os.path.exists(pdf_filename):

        ingest_sce_report(
            pdf_filename,
            tpp_cycle="2026-2027",
            study_area="SCE Main"
        )

        query_database()

    else:

        print(f"PDF not found: {pdf_filename}")