import os
import sys
import re
import pdfplumber

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
# REPORT LAYOUT (SCE Main thermal overload tables)
# ---------------------------------------------------------
# Column layout of every thermal overload table:
#   0 Overloaded Facility | 1 Contingency | 2 Category |
#   3 Category Description | 4-14 eleven scenario columns |
#   15 Project & Potential Mitigation Solutions

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
COL_MITIGATION = FIRST_SCENARIO_COL + len(SCENARIOS)   # 15
EXPECTED_COLS = COL_MITIGATION + 1                      # 16

# P0-P7, combined categories such as P2/P4, and N-2 style codes
CATEGORY_RE = re.compile(r"^(P[0-7](/P[0-7])?|N\d)$")

# Printed in the page footer of the source PDF
DEFAULT_PUBLICATION_DATE = "2026-08-15"

THERMAL_PAGE_MARKER = "Thermal Overloads"


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


def clean_cell(value):
    """
    Clean a multi-line PDF cell. A hyphen followed by a line
    break is a wrapped compound ('Lugo-' / 'Mohave'), so the
    pieces are joined without a space.
    """

    if value is None:
        return ""

    text = str(value).replace("-\n", "-")

    text = clean_text(text)

    # pdfplumber occasionally spaces out letters: "l i n e _V_P7"
    text = re.sub(r"^l i n e _", "line_", text)

    return text


def extract_year(scenario_name):

    match = re.search(r"\b(20\d{2})\b", scenario_name)

    if match:
        return int(match.group(1))

    return None


def mid_y(bbox):

    return (bbox[1] + bbox[3]) / 2.0


# ---------------------------------------------------------
# TABLE READING
# ---------------------------------------------------------

def read_table_rows(table, last_facility=""):
    """
    Return one dict per data row of a pdfplumber Table.

    The report uses merged cells for the facility and for the
    mitigation text. pdfplumber returns those merged cells as
    blank on every row but the first, so:

      * facility  : forward-filled from the row above
      * mitigation: assigned to every row whose vertical position
                    falls inside the merged cell's bounding box
    """

    data = table.extract()

    if not data:
        return []

    # Vertical extent of every row (from the contingency cell)
    row_boxes = []
    mitigation_spans = []

    for i, row in enumerate(table.rows):

        cells = row.cells

        cont_box = (
            cells[COL_CONTINGENCY]
            if len(cells) > COL_CONTINGENCY
            else None
        )

        row_boxes.append(cont_box)

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

        # Skips the header rows, notes and anything that is not a finding
        if not CATEGORY_RE.match(category):
            continue

        facility = clean_cell(raw[COL_FACILITY])

        inherited = False

        if facility:
            last_facility = facility
        else:
            facility = last_facility
            inherited = True

        # Mitigation text for this row
        mitigation = clean_cell(raw[COL_MITIGATION])

        if not mitigation and row_boxes[i] is not None:

            y = mid_y(row_boxes[i])

            for top, bottom, text in mitigation_spans:

                if top - 1 <= y <= bottom + 1:
                    mitigation = text
                    break

        rows.append({
            "row_idx": i + 1,
            "facility": facility,
            "facility_inherited": inherited,
            "contingency": clean_cell(raw[COL_CONTINGENCY]),
            "category": category,
            "category_desc": clean_cell(raw[COL_CATEGORY_DESC]),
            "loadings": [
                clean_cell(raw[FIRST_SCENARIO_COL + n])
                for n in range(len(SCENARIOS))
            ],
            "mitigation": mitigation
        })

    return rows


# ---------------------------------------------------------
# MAIN INGESTION PIPELINE
# ---------------------------------------------------------

def ingest_sce_report(
    pdf_path,
    tpp_cycle,
    study_area,
    publication_date=DEFAULT_PUBLICATION_DATE
):

    if not os.path.exists(pdf_path):
        raise FileNotFoundError(
            f"PDF file not found: {pdf_path}"
        )

    Session = init_db()
    session = Session()

    inserted_count = 0
    skipped_count = 0
    review_count = 0
    below_limit_count = 0
    last_facility = ""

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
                publication_date=publication_date,
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

                # Only the thermal overload section has this layout.
                # Voltage, stability and load-drop pages are skipped.
                page_text = page.extract_text() or ""

                if THERMAL_PAGE_MARKER not in page_text:
                    continue

                tables = page.find_tables()

                if not tables:
                    continue

                page_rows = 0

                for table_idx, table in enumerate(tables):

                    source_table = f"Table {table_idx + 1}"

                    # A table can start mid-facility when the previous
                    # page ended with a merged facility cell, so the last
                    # facility is carried across pages.
                    rows = read_table_rows(table, last_facility)

                    if rows:
                        last_facility = rows[-1]["facility"]

                    for item in rows:

                        page_rows += 1

                        facility_name = item["facility"] or "Unknown Facility"

                        # ---------------------------------
                        # Facility / contingency / mitigation
                        # ---------------------------------

                        facility = get_or_create(
                            session,
                            Facility,
                            canonical_name=facility_name
                        )

                        # Contingency rows are keyed by category code
                        # (P1, P6, P2/P4 ...). The full contingency text
                        # is stored on each finding.
                        contingency = get_or_create(
                            session,
                            Contingency,
                            contingency_code=item["category"],
                            defaults={
                                "category": item["category"],
                                "description": item["category_desc"]
                            }
                        )

                        mitigation = None

                        if item["mitigation"]:

                            mitigation = get_or_create(
                                session,
                                Mitigation,
                                mitigation_text=item["mitigation"]
                            )

                        # ---------------------------------
                        # One finding per scenario overload
                        # ---------------------------------

                        for n, scenario_name in enumerate(SCENARIOS):

                            raw_loading = item["loadings"][n]

                            parsed_value, status = (
                                clean_and_normalize_loading(raw_loading)
                            )

                            # "< 100" means no overload in this scenario
                            if status in ("BELOW_LIMIT", "MISSING"):
                                below_limit_count += 1
                                continue

                            scenario = get_or_create(
                                session,
                                Scenario,
                                scenario_name=scenario_name,
                                defaults={
                                    "study_year": extract_year(
                                        scenario_name
                                    )
                                }
                            )

                            existing = session.query(Finding).filter_by(
                                report_id=report.id,
                                facility_id=facility.id,
                                contingency_id=contingency.id,
                                scenario_id=scenario.id,
                                raw_value=raw_loading,
                                source_page=page_num,
                                source_table=source_table,
                                source_row=item["row_idx"]
                            ).first()

                            if existing:
                                skipped_count += 1
                                continue

                            # -----------------------------
                            # Confidence and review
                            # -----------------------------

                            confidence = 0.95

                            if item["facility_inherited"]:
                                confidence -= 0.05

                            if not item["contingency"]:
                                confidence -= 0.20

                            requires_review = False

                            if status in ("NOT_CONVERGED", "UNKNOWN"):
                                confidence -= 0.25
                                requires_review = True

                            if not item["contingency"]:
                                requires_review = True

                            finding = Finding(
                                report_id=report.id,
                                facility_id=facility.id,
                                contingency_id=contingency.id,
                                scenario_id=scenario.id,

                                mitigation_id=(
                                    mitigation.id if mitigation else None
                                ),

                                facility_name_raw=facility_name,

                                contingency_description_raw=(
                                    item["contingency"]
                                ),

                                raw_value=raw_loading,

                                parsed_value=parsed_value,

                                status_flag=status,

                                confidence_score=max(confidence, 0.0),

                                requires_review=requires_review,

                                # The report does not publish severity
                                severity=None,

                                source_page=page_num,

                                source_table=source_table,

                                source_row=item["row_idx"]
                            )

                            session.add(finding)
                            session.flush()

                            # -----------------------------
                            # Save source evidence
                            # -----------------------------

                            session.add(Evidence(
                                finding_id=finding.id,
                                source_document=file_name,
                                page_number=page_num,
                                table_reference=source_table
                            ))

                            inserted_count += 1

                            if requires_review:
                                review_count += 1

                print(
                    f"Processing page {page_num}: "
                    f"{page_rows} contingency row(s)"
                )

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
        print(f"'< 100' cells not stored: {below_limit_count}")

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
                f"Scenario: {finding.scenario.scenario_name} | "
                f"Loading: {finding.raw_value} | "
                f"Page: {finding.source_page}"
            )

        print("\n--- NUMERICAL OVERLOADS ABOVE 120% ---")

        findings = session.query(Finding).filter(
            Finding.parsed_value > 120
        ).order_by(Finding.parsed_value.desc()).limit(25).all()

        for finding in findings:

            print(
                f"Facility: {finding.facility.canonical_name} | "
                f"Scenario: {finding.scenario.scenario_name} | "
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