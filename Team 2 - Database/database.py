from pathlib import Path
from functools import lru_cache

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

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = BASE_DIR / "power_system_reliability.db"

DB_URL = f"sqlite:///{DB_PATH}"

Base = declarative_base()


@lru_cache(maxsize=1)
def get_engine():

    engine = create_engine(
        DB_URL,
        echo=False,
        connect_args={"check_same_thread": False}
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def init_db():

    engine = get_engine()

    Base.metadata.create_all(engine)

    return sessionmaker(
        bind=engine,
        expire_on_commit=False
    )


# ---------------------------------------------------------
# REPORTS
# ---------------------------------------------------------

class Report(Base):

    __tablename__ = "reports"

    __table_args__ = (
        UniqueConstraint(
            "source_file",
            "tpp_cycle",
            "study_area",
            name="uq_report_source"
        ),
    )

    id = Column(Integer, primary_key=True)

    title = Column(String(255), nullable=False)

    publication_date = Column(String(50))

    source_file = Column(String(255), nullable=False)

    tpp_cycle = Column(String(50))

    study_area = Column(String(150))

    findings = relationship(
        "Finding",
        back_populates="report",
        cascade="all, delete-orphan"
    )


# ---------------------------------------------------------
# FACILITIES
# ---------------------------------------------------------

class Facility(Base):

    __tablename__ = "facilities"

    id = Column(Integer, primary_key=True)

    canonical_name = Column(
        String(255),
        unique=True,
        nullable=False
    )

    voltage_kv = Column(Float)

    facility_type = Column(String(100))

    findings = relationship(
        "Finding",
        back_populates="facility"
    )


# ---------------------------------------------------------
# CONTINGENCIES
# ---------------------------------------------------------

class Contingency(Base):

    __tablename__ = "contingencies"

    id = Column(Integer, primary_key=True)

    contingency_code = Column(
        String(50),
        unique=True,
        nullable=False
    )

    category = Column(String(50))

    description = Column(Text)

    findings = relationship(
        "Finding",
        back_populates="contingency"
    )


# ---------------------------------------------------------
# SCENARIOS
# ---------------------------------------------------------

class Scenario(Base):

    __tablename__ = "scenarios"

    id = Column(Integer, primary_key=True)

    scenario_name = Column(
        String(255),
        unique=True,
        nullable=False
    )

    study_year = Column(Integer)

    condition_type = Column(String(100))

    findings = relationship(
        "Finding",
        back_populates="scenario"
    )


# ---------------------------------------------------------
# MITIGATIONS
# ---------------------------------------------------------

class Mitigation(Base):

    __tablename__ = "mitigations"

    id = Column(Integer, primary_key=True)

    mitigation_text = Column(
        Text,
        nullable=False,
        unique=True
    )

    solution_type = Column(String(100))

    findings = relationship(
        "Finding",
        back_populates="mitigation"
    )


# ---------------------------------------------------------
# FINDINGS
# ---------------------------------------------------------

class Finding(Base):

    __tablename__ = "findings"

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

    mitigation_id = Column(
        Integer,
        ForeignKey("mitigations.id"),
        nullable=True
    )

    # Original extracted information
    facility_name_raw = Column(Text)

    contingency_description_raw = Column(Text)

    # Loading values
    raw_value = Column(String(50))

    parsed_value = Column(Float)

    status_flag = Column(String(50))

    # Extraction validation
    confidence_score = Column(Float)

    requires_review = Column(Boolean, default=False)

    # Only populated when severity is actually available
    # in the source document.
    severity = Column(String(50))

    # Source location for duplicate prevention and traceability
    source_page = Column(Integer)

    source_table = Column(String(100))

    source_row = Column(Integer)

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

    evidence_records = relationship(
        "Evidence",
        back_populates="finding",
        cascade="all, delete-orphan"
    )


# ---------------------------------------------------------
# EVIDENCE
# ---------------------------------------------------------

class Evidence(Base):

    __tablename__ = "evidence"

    id = Column(Integer, primary_key=True)

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
# ---------------------------------------------------------

if __name__ == "__main__":

    init_db()

    print("Database schema created successfully!")
    print(f"Database location: {DB_PATH}")