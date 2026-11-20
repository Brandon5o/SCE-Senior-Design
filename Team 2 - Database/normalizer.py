"""
Data pulled out of PDFs is messy: numbers have stray symbols ("119.0%"),
scanned text has typos ("NatConv"), and names are inconsistent.

This file is to basically the clean up crew. It reads what is already in the database
and fixes/labels it:

  1. Turns messy loading values ("119.0%", "<100", "NotConv") into clean
     numbers plus a status label.
  2. Assigns a severity rating (Normal, Moderate, Severe, Critical).
  3. Works out each facility's voltage and type from its name.
  4. Sorts each proposed fix into a category.
  5. Repairs contingency category labels that the PDF reader misread.
  6. Applies all of the above to every row in the database.

"Loading" = how heavily a piece of equipment is used compared with its
limit. 100% means it is running at its limit; above 100% is an overload.
"""

import re
import sqlite3
from pathlib import Path
import pandas as pd

# Location of the database file (same folder as this script).
DB_PATH = Path(__file__).resolve().parent / "power_system_reliability.db"


# ---------------------------------------------------------
# 1. LOADING & VALUE NORMALIZATION
# Input : the raw text from the report (e.g. "119.0%")
# Output: (clean number, status label)
# ---------------------------------------------------------
def clean_and_normalize_loading(raw_str):

    # Empty cell -> nothing to clean.
    if pd.isna(raw_str):
        return None, "MISSING"

    # Trim spaces; a blank string also counts as missing.
    val_str = str(raw_str).strip()
    if not val_str:
        return None, "MISSING"

    # The studies sometimes say the computer simulation failed to find a
    # solution ("Not Converged"). The PDF reader often misspells this
    # (NatConv, NetConv, ...), so we check for all the common misspellings.
    non_conv_tokens = ["notconv", "notcom", "natconv", "netconv", "nalconv", "norconv", "notcon", "diverged"]
    if any(token in val_str.lower() for token in non_conv_tokens):
        return None, "NOT_CONVERGED"

    # "Stable" means no problem; record it as 0% loading.
    if val_str.lower() == "stable":
        return 0.0, "NORMAL"

    # Values like "<100" mean "below 100". We don't know the exact number,
    # so we record just under the limit (e.g. 99.9) and flag it as BELOW_LIMIT.
    ineq_match = re.match(r"^<\s*(\d+(?:\.\d+)?)", val_str)
    if ineq_match:
        bound = float(ineq_match.group(1))
        return round(bound - 0.1, 1), "BELOW_LIMIT"

    # Any other value containing "<" (like "0.9<V<1.1") is a voltage range,
    # not a single number, so we can't turn it into one value.
    if "<v<" in val_str.lower() or "<" in val_str:
        return None, "VOLTAGE_RANGE"

    # Fix common scan/typing mistakes before converting to a number:
    #   remove "%", turn ":" or "," into a decimal point,
    #   and turn a misread "$" into the digit "1".
    cleaned = val_str.replace("%", "").replace(":", ".").replace(",", ".").replace("$", "1").strip()
    try:
        clean_num = float(cleaned)

        # Numbers between 0.4 and 2.0 are treated as voltage in "per-unit"
        # (1.0 = normal voltage), not a percentage of equipment limit.
        if 0.4 <= clean_num <= 2.0:
            return clean_num, "VOLTAGE_PU"

        # Otherwise it's a loading %: 100 or more = overload.
        status = "OVERLOAD" if clean_num >= 100.0 else "NORMAL"
        return clean_num, status
    except ValueError:
        # Couldn't make sense of it at all.
        return None, "UNKNOWN"


# ---------------------------------------------------------
# 2. SEVERITY CLASSIFICATION
# Turns the number + status into a human-readable severity bucket.
# ---------------------------------------------------------
def classify_severity(parsed_value, status_flag):

    if status_flag == "NOT_CONVERGED":
        return "Non-Converged / Diverged"
    if status_flag in ("VOLTAGE_RANGE", "VOLTAGE_PU"):
        return "Voltage Study"
    if parsed_value is None:
        return "Unclassified"

    # Overload tiers, from mild to serious:
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
# Reads a facility's name and works out its voltage and type.
# Returns: (display name, voltage in kV, facility type)
# The "anonymize" option can swap real names for generic ones
# like "Facility_007" (useful when sharing data publicly).
# ---------------------------------------------------------
def parse_facility_metadata(raw_facility_name, anonymize=False, facility_id=None):

    # No usable name -> label it as unknown.
    if not raw_facility_name or "unknown" in raw_facility_name.lower():
        return "Unknown Facility", None, "Unassigned / System-Level"

    # Collapse extra spaces/line breaks into single spaces.
    text = " ".join(str(raw_facility_name).split())

    # PATTERN A: a line or transformer written as two connected locations, e.g.
    # "12345 SUBSTATION-A 230 67890 SUBSTATION-B 115 1 ..."
    # (bus number, name, kV, bus number, name, kV, circuit ID, ...)
    bus_pattern = re.match(
        r"^(\d+)\s+([A-Za-z0-9_.\s]+?)\s+(\d+(?:\.\d+)?)\s+(\d+)\s+([A-Za-z0-9_.\s]+?)\s+(\d+(?:\.\d+)?)\s+(\S+)\s+(\S+)$",
        text
    )
    if bus_pattern:
        _, sub1, kv1_str, _, sub2, kv2_str, ckt, _ = bus_pattern.groups()
        kv1, kv2 = float(kv1_str), float(kv2_str)

        # Use the higher of the two voltages as the facility's voltage.
        primary_kv = max(kv1, kv2)

        # Rule of thumb: if the low side is under 50 kV (or the second
        # name contains an "i"), call it a transformer; else a line.
        fac_type = "Transformer Bank" if kv2 < 50.0 or "i" in sub2.lower() else "Transmission Line"
        if anonymize and facility_id is not None:
            return f"Facility_{facility_id:03d} ({int(primary_kv)} kV {fac_type})", primary_kv, fac_type
        return text, primary_kv, fac_type

    # PATTERN B: a name that just mentions a voltage like "230 kV" -> substation.
    sub_pattern = re.search(r"(\d+(?:\.\d+)?)\s*kV", text, re.IGNORECASE)
    if sub_pattern:
        kv = float(sub_pattern.group(1))
        fac_type = "Substation"
        if anonymize and facility_id is not None:
            return f"Substation_{facility_id:03d} ({int(kv)} kV)", kv, fac_type
        return text, kv, fac_type

    # Nothing matched: keep the name, type "Other".
    return text, None, "Other"


# ---------------------------------------------------------
# 4. MITIGATION SOLUTION TYPE CLASSIFIER
# Reads the fix description and files it under a category by
# looking for keywords. The first keyword group that matches wins.
# ---------------------------------------------------------
def classify_mitigation_type(mitigation_text):
    if not mitigation_text:
        return "Unspecified"
    t = mitigation_text.lower()  # lowercase so capitalization doesn't matter
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
# Categories look like "P0", "P1", ... "P7". The PDF reader sometimes
# misreads letters (including Cyrillic look-alikes like "Р" and "Б"),
# so this swaps known mistakes for the correct label.
# ---------------------------------------------------------
def clean_contingency_category(cat_str):
    if not cat_str:
        return "Unspecified"
    c = str(cat_str).strip().upper()
    ocr_map = {"РБ": "P6", "PB": "P6", "PT": "P7", "PS": "P5", "PO": "P0"}
    # If it's a known mistake, use the fix; otherwise keep it as is.
    return ocr_map.get(c, c)


# ---------------------------------------------------------
# 6. DATABASE NORMALIZER
# The "run everything" step: goes through the database tables
# row by row, applies the cleaning functions above, and saves
# the results back.
# ---------------------------------------------------------
def normalize_existing_database(db_path=DB_PATH):

    # Stop early if the database file isn't there.
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return

    # Open the database.
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # A. Clean Findings
    # For every finding: clean the raw value, label it, rate its severity.
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
    # For every facility: fill in its voltage and type from its name.
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
    # For every proposed fix: assign its category.
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
    # Repair misread category labels.
    cur.execute("SELECT id, category FROM contingencies")
    cont_rows = cur.fetchall()
    for c_id, cat in cont_rows:
        clean_cat = clean_contingency_category(cat)
        cur.execute(
            "UPDATE contingencies SET category = ? WHERE id = ?",
            (clean_cat, c_id),
        )

    # Save all changes permanently and close the database.
    conn.commit()
    conn.close()

    # Print a summary of what was done.
    print(f"Database normalization complete on {db_path.name}:")
    print(f"  - Findings normalized & classified: {updated_findings}")
    print(f"  - Facilities enriched (voltage/type): {updated_facilities}")
    print(f"  - Mitigations categorized: {updated_mitigations}")


# ---------------------------------------------------------
# RUNNING THIS FILE DIRECTLY
# First a quick demo with sample values so you can see how the
# cleaning works, then the real clean-up of the database.
# ---------------------------------------------------------
if __name__ == "__main__":
    test_inputs = ["119.0%", "<100", "< 100", "< 80", "NotConv", "NatConv", "95.5%"]
    for item in test_inputs:
        parsed, flag = clean_and_normalize_loading(item)
        sev = classify_severity(parsed, flag)
        print(f"Raw: {item:<8} -> Parsed: {str(parsed):<6} | Status: {flag:<14} | Severity: {sev}")
    print("-" * 70)
    normalize_existing_database()