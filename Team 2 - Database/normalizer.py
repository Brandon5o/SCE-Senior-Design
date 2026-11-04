import pandas as pd

def clean_and_normalize_loading(raw_str):
    if raw_str is None or (not isinstance(raw_str, str) and pd.isna(raw_str)):
        return None, "MISSING"

    val = " ".join(str(raw_str).split())
    if not val:
        return None, "MISSING"

    compact = val.replace(" ", "")

    if "NotConv" in compact or "NotCom" in compact:
        return None, "NOT_CONVERGED"

    if compact.startswith("<"):
        return None, "BELOW_LIMIT"

    try:
        num = float(compact.replace("%", ""))
        return num, ("OVERLOAD" if num >= 100.0 else "NORMAL")
    except ValueError:
        return None, "UNKNOWN"