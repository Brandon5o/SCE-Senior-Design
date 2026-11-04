import re
import sqlite3
from pathlib import Path
import pandas as pd

DB_PATH = Path(__file__).resolve().parent / "power_system_reliability.db"


# ---------------------------------------------------------
# 1. LOADING & VALUE NORMALIZATION
# ---------------------------------------------------------
def clean_and_normalize_loading(raw_str):
    """
    Parses messy text inputs from reliability reports:
    - Handles percentages ('119.0%')
    - Handles inequality bounds ('< 100', '< 80')
    - Handles non-convergence flags ('NotConv', 'NatConv', etc.)
    """
    if pd.isna(raw_str):
        return None, "MISSING"

    val_str = str(raw_str).strip()
    if not val_str:
        return None, "MISSING"

    non_conv_tokens = ["notconv", "notcom", "natconv", "netconv", "nalconv", "norconv", "notcon", "diverged"]
    if any(token in val_str.lower() for token in non_conv_tokens):
        return None, "NOT_CONVERGED"

    if val_str.lower() == "stable":
        return 0.0, "NORMAL"

    ineq_match = re.match(r"^<\s*(\d+(?:\.\d+)?)", val_str)
    if ineq_match:
        bound = float(ineq_match.group(1))
        return round(bound - 0.1, 1), "BELOW_LIMIT"

    if "<v<" in val_str.lower() or "<" in val_str:
        return None, "VOLTAGE_RANGE"

    cleaned = val_str.replace("%", "").replace(":", ".").replace(",", ".").replace("$", "1").strip()
    try:
        clean_num = float(cleaned)
        if 0.4 <= clean_num <= 2.0:
            return clean_num, "VOLTAGE_PU"
        status = "OVERLOAD" if clean_num >= 100.0 else "NORMAL"
        return clean_num, status
    except ValueError:
        return None, "UNKNOWN"


# ---------------------------------------------------------
# 2. SEVERITY CLASSIFICATION
# ---------------------------------------------------------
def classify_severity(parsed_value, status_flag):
    if status_flag == "NOT_CONVERGED":
        return "Non-Converged / Diverged"
    if status_flag in ("VOLTAGE_RANGE", "VOLTAGE_PU"):
        return "Voltage Study"
    if parsed_value is None:
        return "Unclassified"
    if parsed_value < 100.0:
        return "Normal (<100%)"
    elif parsed_value < 120.0:
        return "Moderate Overload (100-119%)"
    elif parsed_value < 150.0:
        return "Severe Overload (120-149%)"
    else:
        return "Critical Overload (>=150%)"


# ---------------------------------------------------------
# 3. FACILITY METADATA PARSER
# ---------------------------------------------------------
def parse_facility_metadata(raw_facility_name, anonymize=False, facility_id=None):
    if not raw_facility_name or "unknown" in raw_facility_name.lower():
        return "Unknown Facility", None, "Unassigned / System-Level"
    text = " ".join(str(raw_facility_name).split())
    
    bus_pattern = re.match(
        r"^(\d+)\s+([A-Za-z0-9_.\s]+?)\s+(\d+(?:\.\d+)?)\s+(\d+)\s+([A-Za-z0-9_.\s]+?)\s+(\d+(?:\.\d+)?)\s+(\S+)\s+(\S+)$",
        text
    )
    if bus_pattern:
        _, sub1, kv1_str, _, sub2, kv2_str, ckt, _ = bus_pattern.groups()
        kv1, kv2 = float(kv1_str), float(kv2_str)
        primary_kv = max(kv1, kv2)
        fac_type = "Transformer Bank" if kv2 < 50.0 or "i" in sub2.lower() else "Transmission Line"
        if anonymize and facility_id is not None:
            return f"Facility_{facility_id:03d} ({int(primary_kv)} kV {fac_type})", primary_kv, fac_type
        return text, primary_kv, fac_type

    sub_pattern = re.search(r"(\d+(?:\.\d+)?)\s*kV", text, re.IGNORECASE)
    if sub_pattern:
        kv = float(sub_pattern.group(1))
        fac_type = "Substation"
        if anonymize and facility_id is not None:
            return f"Substation_{facility_id:03d} ({int(kv)} kV)", kv, fac_type
        return text, kv, fac_type

    return text, None, "Other"


# ---------------------------------------------------------
# 4. MITIGATION SOLUTION TYPE CLASSIFIER
# ---------------------------------------------------------
def classify_mitigation_type(mitigation_text):
    if not mitigation_text:
        return "Unspecified"
    t = mitigation_text.lower()
    if "hvdc" in t or "submarine" in t:
        return "HVDC / New Transmission Corridor"
    if "reconductor" in t or "htls" in t or "rebuild" in t:
        return "Reconductor / Line Upgrade"
    if "statcom" in t or "capacitor" in t or "reactive power" in t:
        return "Reactive Power / Voltage Support"
    if "aa bank" in t or "transformer" in t or "switchyard" in t:
        return "Substation / Transformer Bank Upgrade"
    if "ras" in t or "curtail" in t or "operational" in t or "redispatch" in t:
        return "RAS / Operational Mitigation"
    if "criteria met" in t:
        return "No Mitigation Needed (Criteria Met)"
    if "further evaluation" in t:
        return "Further Engineering Evaluation"
    return "General Mitigation"


# ---------------------------------------------------------
# 5. CONTINGENCY CATEGORY CLEANER
# ---------------------------------------------------------
def clean_contingency_category(cat_str):
    if not cat_str:
        return "Unspecified"
    c = str(cat_str).strip().upper()
    ocr_map = {"РБ": "P6", "PB": "P6", "PT": "P7", "PS": "P5", "PO": "P0"}
    return ocr_map.get(c, c)


# ---------------------------------------------------------
# 6. DATABASE NORMALIZER
# ---------------------------------------------------------
def normalize_existing_database(db_path=DB_PATH):
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # A. Clean Findings
    cur.execute("SELECT id, raw_value FROM findings")
    findings_rows = cur.fetchall()
    updated_findings = 0
    for f_id, raw_val in findings_rows:
        parsed_val, status_flag = clean_and_normalize_loading(raw_val)
        severity = classify_severity(parsed_val, status_flag)
        cur.execute(
            """
            UPDATE findings
            SET parsed_value = ?, status_flag = ?, severity = ?
            WHERE id = ?
            """,
            (parsed_val, status_flag, severity, f_id),
        )
        updated_findings += 1

    # B. Enrich Facilities
    cur.execute("SELECT id, canonical_name FROM facilities")
    fac_rows = cur.fetchall()
    updated_facilities = 0
    for fac_id, cname in fac_rows:
        _, voltage_kv, fac_type = parse_facility_metadata(cname, facility_id=fac_id)
        cur.execute(
            """
            UPDATE facilities
            SET voltage_kv = ?, facility_type = ?
            WHERE id = ?
            """,
            (voltage_kv, fac_type, fac_id),
        )
        updated_facilities += 1

    # C. Categorize Mitigations
    cur.execute("SELECT id, mitigation_text FROM mitigations")
    mit_rows = cur.fetchall()
    updated_mitigations = 0
    for mit_id, m_text in mit_rows:
        sol_type = classify_mitigation_type(m_text)
        cur.execute(
            "UPDATE mitigations SET solution_type = ? WHERE id = ?",
            (sol_type, mit_id),
        )
        updated_mitigations += 1

    # D. Fix Contingency Categories
    cur.execute("SELECT id, category FROM contingencies")
    cont_rows = cur.fetchall()
    for c_id, cat in cont_rows:
        clean_cat = clean_contingency_category(cat)
        cur.execute(
            "UPDATE contingencies SET category = ? WHERE id = ?",
            (clean_cat, c_id),
        )

    conn.commit()
    conn.close()
    print(f"Database normalization complete on {db_path.name}:")
    print(f"  - Findings normalized & classified: {updated_findings}")
    print(f"  - Facilities enriched (voltage/type): {updated_facilities}")
    print(f"  - Mitigations categorized: {updated_mitigations}")


if __name__ == "__main__":
    test_inputs = ["119.0%", "<100", "< 100", "< 80", "NotConv", "NatConv", "95.5%"]
    for item in test_inputs:
        parsed, flag = clean_and_normalize_loading(item)
        sev = classify_severity(parsed, flag)
        print(f"Raw: {item:<8} -> Parsed: {str(parsed):<6} | Status: {flag:<14} | Severity: {sev}")
    print("-" * 70)
    normalize_existing_database()