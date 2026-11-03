import pandas as pd

def clean_and_normalize_loading(raw_str):
    """
    Parses messy text inputs from reliability reports:
    - Handles percentages ('119.0%')
    - Handles inequality bounds ('<100')
    - Handles non-convergence flags ('NotConv')
    """
    if pd.isna(raw_str):
        return None, "MISSING"
    
    val_str = str(raw_str).strip()
    
    if "NotConv" in val_str or "NotCom" in val_str:
        return None, "NOT_CONVERGED"
    
    if "<100" in val_str:
        return 99.9, "BELOW_LIMIT"
    
    try:
        clean_num = float(val_str.replace('%', '').strip())
        status = "OVERLOAD" if clean_num >= 100.0 else "NORMAL"
        return clean_num, status
    except ValueError:
        return None, "UNKNOWN"

# Example test run to verify normalization logic
if __name__ == "__main__":
    test_inputs = ["119.0%", "<100", "NotConv", "95.5%"]
    for item in test_inputs:
        parsed, flag = clean_and_normalize_loading(item)
        print(f"Raw: {item} ➔ Parsed: {parsed} | Status: {flag}")