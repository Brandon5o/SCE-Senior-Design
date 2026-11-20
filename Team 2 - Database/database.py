"""
This file defines the structure of the database (not the data itself).
Think of the database as an Excel workbook with several sheets (called
"tables"). This file says which sheets exist, what columns each one has,
and how the sheets connect to each other.

The tables are:
  - reports       : one row per source PDF report (e.g. a transmission planning study)
  - facilities    : power lines / transformers / substations that were studied
  - contingencies : "what if" events, e.g. "what if this line fails?"
  - scenarios     : the study conditions (year, summer peak, etc.)
  - mitigations   : the proposed fixes for problems that were found
  - findings      : the MAIN table. Each row says: "In this report, under this
                    scenario, if this contingency happens, this facility is
                    loaded to X%." It links to all the tables above.
  - evidence      : points back to the exact page/table in the PDF where a
                    finding came from, so anyone can double-check it.

Running this file directly creates an empty database with these tables.
"""

from pathlib import Path
from functools import lru_cache

# Tools from the SQLAlchemy library, which lets us describe database tables
# using Python instead of writing raw database commands.
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    ForeignKey,
    Text,
    Boolean,
    UniqueConstraint,
    event
)

from sqlalchemy.orm import (
    declarative_base,
    relationship,
    sessionmaker
)


# ---------------------------------------------------------
# DATABASE CONFIGURATION
# ---------------------------------------------------------

# The folder this file lives in.
BASE_DIR = Path(__file__).resolve().parent

# The database is a single file ("power_system_reliability.db") saved
# in that same folder.
DB_PATH = BASE_DIR / "power_system_reliability.db"

# The "address" of the database, in the format the library expects.
# "sqlite" is a simple, file-based type of database (no server needed).
DB_URL = f"sqlite:///{DB_PATH}"

# Base is the starting point that every table below builds on.
Base = declarative_base()


# @lru_cache means: "only create the connection once, then reuse it."
# This avoids opening many duplicate connections to the same file.
@lru_cache(maxsize=1)
def get_engine():
    """Open (or reuse) the connection to the database file."""

    engine = create_engine(
        DB_URL,
        echo=False,  # False = don't print every database command to the screen
        # Allows the connection to be used from different parts of the program.
        connect_args={"check_same_thread": False}
    )

    # Every time a connection opens, switch on "foreign key" checking.
    # This is a safety rule: you can't link a finding to a facility that
    # doesn't exist. (SQLite has this turned off by default.)
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def init_db():
    """Create all the tables (if they don't exist yet) and return a
    'session factory' - a tool other code uses to read/write data."""

    engine = get_engine()

    # Builds every table defined below. Existing tables are left alone.
    Base.metadata.create_all(engine)

    return sessionmaker(
        bind=engine,
        expire_on_commit=False  # keep data usable after saving it
    )


# ---------------------------------------------------------
# REPORTS
# One row per source document (PDF) that data was pulled from.
# ---------------------------------------------------------

class Report(Base):

    __tablename__ = "reports"

    # Rule: the same file / cycle / study area combination can only be
    # added once. This prevents loading the same report twice.
    __table_args__ = (
        UniqueConstraint(
            "source_file",
            "tpp_cycle",
            "study_area",
            name="uq_report_source"
        ),
    )

    # Unique ID number for each row (assigned automatically).
    id = Column(Integer, primary_key=True)

    # Report title. "nullable=False" means this can't be left blank.
    title = Column(String(255), nullable=False)

    publication_date = Column(String(50))

    # Name of the PDF file the data came from (required).
    source_file = Column(String(255), nullable=False)

    # Which planning cycle, e.g. "2026-2027".
    tpp_cycle = Column(String(50))

    # Geographic/system area covered by the study.
    study_area = Column(String(150))

    # Link to all the findings that came from this report.
    # "delete-orphan" = if a report is deleted, its findings are deleted too.
    findings = relationship(
        "Finding",
        back_populates="report",
        cascade="all, delete-orphan"
    )


# ---------------------------------------------------------
# FACILITIES
# One row per piece of equipment studied (line, transformer, substation).
# ---------------------------------------------------------

class Facility(Base):

    __tablename__ = "facilities"

    id = Column(Integer, primary_key=True)

    # The standard, cleaned-up name. "unique=True" = no two facilities
    # can share the same name.
    canonical_name = Column(
        String(255),
        unique=True,
        nullable=False
    )

    # Voltage in kilovolts (kV), e.g. 230.
    voltage_kv = Column(Float)

    # Kind of equipment: "Transmission Line", "Transformer Bank", etc.
    facility_type = Column(String(100))

    findings = relationship(
        "Finding",
        back_populates="facility"
    )


# ---------------------------------------------------------
# CONTINGENCIES
# A "what if" event, e.g. losing a line or a generator.
# ---------------------------------------------------------

class Contingency(Base):

    __tablename__ = "contingencies"

    id = Column(Integer, primary_key=True)

    # Short code identifying the event; must be unique.
    contingency_code = Column(
        String(50),
        unique=True,
        nullable=False
    )

    # Category label from the reliability standard (e.g. P1, P6).
    category = Column(String(50))

    # Longer text description of the event.
    description = Column(Text)

    findings = relationship(
        "Finding",
        back_populates="contingency"
    )


# ---------------------------------------------------------
# SCENARIOS
# The study conditions the grid was tested under.
# ---------------------------------------------------------

class Scenario(Base):

    __tablename__ = "scenarios"

    id = Column(Integer, primary_key=True)

    scenario_name = Column(
        String(255),
        unique=True,
        nullable=False
    )

    # Year being studied, e.g. 2031.
    study_year = Column(Integer)

    # Type of conditions, e.g. peak load, off-peak.
    condition_type = Column(String(100))

    findings = relationship(
        "Finding",
        back_populates="scenario"
    )


# ---------------------------------------------------------
# MITIGATIONS
# Proposed fixes for problems found in the studies.
# ---------------------------------------------------------

class Mitigation(Base):

    __tablename__ = "mitigations"

    id = Column(Integer, primary_key=True)

    # The fix as written in the report; each distinct text is stored once.
    mitigation_text = Column(
        Text,
        nullable=False,
        unique=True
    )

    # A tidy category for the fix (e.g. "Reconductor / Line Upgrade").
    solution_type = Column(String(100))

    findings = relationship(
        "Finding",
        back_populates="mitigation"
    )


# ---------------------------------------------------------
# FINDINGS
# The MAIN table: one row per result pulled from a report table.
# ---------------------------------------------------------

class Finding(Base):

    __tablename__ = "findings"

    # Duplicate protection: the exact same result from the exact same
    # spot in the PDF can't be saved twice.
    __table_args__ = (
        UniqueConstraint(
            "report_id",
            "facility_id",
            "contingency_id",
            "scenario_id",
            "raw_value",
            "source_page",
            "source_table",
            "source_row",
            name="uq_finding_source"
        ),
    )

    id = Column(Integer, primary_key=True)

    # --- Links to the other tables (like "look up this row over there") ---
    report_id = Column(
        Integer,
        ForeignKey("reports.id"),
        nullable=False
    )

    facility_id = Column(
        Integer,
        ForeignKey("facilities.id"),
        nullable=False
    )

    contingency_id = Column(
        Integer,
        ForeignKey("contingencies.id"),
        nullable=False
    )

    scenario_id = Column(
        Integer,
        ForeignKey("scenarios.id"),
        nullable=False
    )

    # A finding may or may not have a proposed fix, so this can be blank.
    mitigation_id = Column(
        Integer,
        ForeignKey("mitigations.id"),
        nullable=True
    )

    # Original extracted information (exactly as read from the PDF,
    # kept untouched in case we need to check it later)
    facility_name_raw = Column(Text)

    contingency_description_raw = Column(Text)

    # Loading values
    # raw_value    = the text exactly as it appeared (e.g. "119.0%")
    # parsed_value = the cleaned-up number (e.g. 119.0)
    # status_flag  = a label describing the value (e.g. OVERLOAD, NORMAL)
    raw_value = Column(String(50))

    parsed_value = Column(Float)

    status_flag = Column(String(50))

    # Extraction validation
    # How confident the PDF-reading step was (0 to 1), and whether a
    # human should double-check this row.
    confidence_score = Column(Float)

    requires_review = Column(Boolean, default=False)

    # Only populated when severity is actually available
    # in the source document.
    severity = Column(String(50))

    # Source location for duplicate prevention and traceability
    # (which page, table and row of the PDF this came from)
    source_page = Column(Integer)

    source_table = Column(String(100))

    source_row = Column(Integer)

    # Shortcuts to jump from a finding to its related records in Python.
    report = relationship(
        "Report",
        back_populates="findings"
    )

    facility = relationship(
        "Facility",
        back_populates="findings"
    )

    contingency = relationship(
        "Contingency",
        back_populates="findings"
    )

    scenario = relationship(
        "Scenario",
        back_populates="findings"
    )

    mitigation = relationship(
        "Mitigation",
        back_populates="findings"
    )

    # Evidence records belong to a finding; deleting the finding
    # deletes its evidence too.
    evidence_records = relationship(
        "Evidence",
        back_populates="finding",
        cascade="all, delete-orphan"
    )


# ---------------------------------------------------------
# EVIDENCE
# The "receipts": where in the source document a finding was found.
# ---------------------------------------------------------

class Evidence(Base):

    __tablename__ = "evidence"

    id = Column(Integer, primary_key=True)

    # Which finding this evidence supports.
    finding_id = Column(
        Integer,
        ForeignKey("findings.id"),
        nullable=False
    )

    source_document = Column(String(255))

    page_number = Column(Integer)

    table_reference = Column(String(100))

    finding = relationship(
        "Finding",
        back_populates="evidence_records"
    )


# ---------------------------------------------------------
# INITIALIZATION
# This block only runs when you run this file directly
# (not when another file imports it).
# ---------------------------------------------------------

if __name__ == "__main__":

    init_db()

    print("Database schema created successfully!")
    print(f"Database location: {DB_PATH}")