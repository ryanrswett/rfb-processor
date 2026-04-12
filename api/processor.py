"""Core processing logic for Regional Food Bank files.

Handles:
- House list XLSX (14 columns, has Constituent ID)
- Rental list XLSX (7 columns, no Constituent ID)
- Rental list CSV (6 columns: FirstName,LastName,Address,City,State,Zip5)
"""

import io
import csv
import os
import re
from datetime import datetime

import pandas as pd
from .scanline import make_scanline


# Output columns in canonical order
OUTPUT_COLUMNS = [
    "ConstituentId", "LastName", "FirstName", "OrganizationName",
    "PrimaryAddressee", "PrimarySalutation", "AddressLine1", "AddressLine2",
    "CityState", "ZIP", "County", "LastGiftDate", "AcquisitionId", "DonorId",
    "KeyCodeListId", "CheckDigit", "ScanLine",
]

# ---------------------------------------------------------------------------
# Database connection (optional -- used for rental list sequence numbers)
# Set MAILWORKS_CONN_STRING env var or .env to enable.
# When not configured, rental lists will fail with a clear error.
# House lists never need it.
# ---------------------------------------------------------------------------
_db_conn_string = os.environ.get("MAILWORKS_CONN_STRING", "")


def db_available() -> bool:
    """Check if database connection is configured."""
    return bool(_db_conn_string)


def get_sequence_number_from_db(count: int, serial_number: str) -> int:
    """Pull next sequence number block from the MailWorks stored procedure."""
    if not db_available():
        raise RuntimeError("Database connection not configured.")
    try:
        import pyodbc
    except ImportError:
        raise RuntimeError(
            "pyodbc is not installed. Run: pip install pyodbc"
        )

    sql = f"""
        DECLARE @maxCount INT;
        EXEC MailWorksInventory.[dbo].[GetNextIntelligentBarCode]
             0, {count}, '{serial_number}', 0,
             @maxCount = @maxCount OUTPUT;
        SELECT @maxCount;
    """
    conn = pyodbc.connect(_db_conn_string)
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        result = cursor.fetchone()[0]
        return int(result)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# File type detection
# ---------------------------------------------------------------------------

def detect_file_type(filename: str, df: pd.DataFrame) -> str:
    """Detect whether file is house_list, rental_xlsx, or rental_csv."""
    cols = set(df.columns)
    if "Constituent ID" in cols and "Primary Addressee" in cols:
        return "house_list"
    if filename.lower().endswith(".csv"):
        return "rental_csv"
    return "rental_xlsx"


# ---------------------------------------------------------------------------
# Key code generation
# ---------------------------------------------------------------------------

def build_key_code_list_id(list_id: int) -> str:
    """Build the 8-char KeyCodeListId from year+week preamble + listId."""
    now = datetime.now()
    year_part = now.strftime("%y")
    week = now.isocalendar()[1]
    preamble = year_part + str(week).zfill(3)
    raw = preamble + str(list_id)
    return raw.zfill(8)[:8]


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------

def read_upload(filename: str, file_bytes: bytes) -> pd.DataFrame:
    """Read uploaded file into a DataFrame."""
    if filename.lower().endswith(".xlsx"):
        return pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    elif filename.lower().endswith(".csv"):
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                return pd.read_csv(
                    io.BytesIO(file_bytes), dtype=str, encoding=enc
                )
            except UnicodeDecodeError:
                continue
        raise ValueError("Could not decode CSV file with any supported encoding.")
    else:
        raise ValueError(f"Unsupported file type: {filename}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean(val) -> str:
    """Clean a pandas cell value: convert NaN/None to empty string."""
    s = str(val).strip() if val is not None else ""
    return "" if s in ("nan", "None", "NaT") else s


def _is_org(record: dict) -> bool:
    """Check if a processed record is an organization."""
    return record["OrganizationName"] != ""


def _fix_and_in_addressee(record: dict) -> tuple[dict, bool]:
    """Replace ' and ' with ' & ' in PrimaryAddressee for individual records only.

    Returns (record, was_changed).
    Orgs are left untouched to preserve legal/brand names.
    """
    if _is_org(record):
        return record, False
    addr = record.get("PrimaryAddressee", "")
    if " and " in addr:
        record["PrimaryAddressee"] = addr.replace(" and ", " & ")
        return record, True
    return record, False


_ZIP_PATTERN = re.compile(r"^\d{5}(-\d{4})?$")


def _validate_zip(zip_val: str) -> bool:
    """Check if ZIP matches 5-digit or ZIP+4 format."""
    return bool(_ZIP_PATTERN.match(zip_val))


# ---------------------------------------------------------------------------
# House list processing
# ---------------------------------------------------------------------------

def process_house_list(
    df: pd.DataFrame,
    key_code_list_id: str,
) -> tuple[pd.DataFrame, dict]:
    """Process a house list file.

    House list: AcquisitionId is all zeros, DonorId = ConstituentID padded to 7.
    Returns (output_df, stats).
    """
    records = []
    and_replaced_count = 0

    for _, row in df.iterrows():
        constituent_id = _clean(row.get("Constituent ID"))
        donor_id = constituent_id.zfill(7) if constituent_id else "0" * 7
        acquisition_id = "0" * 10

        full_scan, check_digit = make_scanline(
            acquisition_id, donor_id, key_code_list_id
        )

        city = _clean(row.get("Preferred City"))
        state = _clean(row.get("Preferred State"))
        last_gift = _clean(row.get("Last Gift Date"))

        record = {
            "ConstituentId": constituent_id,
            "LastName": _clean(row.get("Last Name")),
            "FirstName": _clean(row.get("First Name")),
            "OrganizationName": _clean(row.get("Organization Name")),
            "PrimaryAddressee": _clean(row.get("Primary Addressee")),
            "PrimarySalutation": _clean(row.get("Primary Salutation")),
            "AddressLine1": _clean(row.get("Preferred Address Line 1")),
            "AddressLine2": _clean(row.get("Preferred Address Line 2")),
            "CityState": f"{city}, {state}" if city else state,
            "ZIP": _clean(row.get("Preferred ZIP")),
            "County": _clean(row.get("Preferred County")),
            "LastGiftDate": last_gift,
            "AcquisitionId": acquisition_id,
            "DonorId": donor_id,
            "KeyCodeListId": key_code_list_id,
            "CheckDigit": check_digit,
            "ScanLine": full_scan,
        }

        record, was_changed = _fix_and_in_addressee(record)
        if was_changed:
            and_replaced_count += 1

        records.append(record)

    output_df = pd.DataFrame(records, columns=OUTPUT_COLUMNS)
    stats = {"and_replaced_count": and_replaced_count}
    return output_df, stats


# ---------------------------------------------------------------------------
# Rental list processing
# ---------------------------------------------------------------------------

def process_rental_list(
    df: pd.DataFrame,
    key_code_list_id: str,
    starting_acquisition_id: int,
    file_type: str,
) -> pd.DataFrame:
    """Process a rental list (CSV or XLSX).

    Rental list: DonorId is all zeros, AcquisitionId is sequential.
    """
    records = []
    current_acq_id = starting_acquisition_id

    for _, row in df.iterrows():
        acquisition_id = str(current_acq_id).zfill(10)
        donor_id = "0" * 7

        full_scan, check_digit = make_scanline(
            acquisition_id, donor_id, key_code_list_id
        )

        if file_type == "rental_csv":
            city = _clean(row.get("City"))
            state = _clean(row.get("State"))
            records.append({
                "ConstituentId": "0",
                "LastName": _clean(row.get("LastName")),
                "FirstName": _clean(row.get("FirstName")),
                "OrganizationName": "",
                "PrimaryAddressee": "",
                "PrimarySalutation": "",
                "AddressLine1": _clean(row.get("Address")),
                "AddressLine2": "",
                "CityState": f"{city}, {state}" if city else state,
                "ZIP": _clean(row.get("Zip5")),
                "County": "",
                "LastGiftDate": "",
                "AcquisitionId": acquisition_id,
                "DonorId": donor_id,
                "KeyCodeListId": key_code_list_id,
                "CheckDigit": check_digit,
                "ScanLine": full_scan,
            })
        else:  # rental_xlsx
            city_col = "City " if "City " in df.columns else "City"
            state_col = "State " if "State " in df.columns else "State"
            city = _clean(row.get(city_col))
            state = _clean(row.get(state_col))

            records.append({
                "ConstituentId": "0",
                "LastName": _clean(row.get("Last Name")),
                "FirstName": _clean(row.get("First Name")),
                "OrganizationName": "",
                "PrimaryAddressee": "",
                "PrimarySalutation": "",
                "AddressLine1": _clean(row.get("Address 1")),
                "AddressLine2": _clean(row.get("Address 2")),
                "CityState": f"{city}, {state}" if city else state,
                "ZIP": _clean(row.get("Zip")),
                "County": "",
                "LastGiftDate": "",
                "AcquisitionId": acquisition_id,
                "DonorId": donor_id,
                "KeyCodeListId": key_code_list_id,
                "CheckDigit": check_digit,
                "ScanLine": full_scan,
            })

        current_acq_id += 1

    return pd.DataFrame(records, columns=OUTPUT_COLUMNS)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(output_df: pd.DataFrame, file_type: str) -> list[dict]:
    """Run validation checks. Returns list of warning dicts.

    Each: {level: "warning"|"error", message: str, count: int, sample: list}
    """
    warnings = []

    # --- Name length checks ---
    long_first = output_df[output_df["FirstName"].str.len() > 50]
    if len(long_first) > 0:
        warnings.append({
            "level": "warning",
            "message": "FirstName exceeds 50 characters",
            "count": len(long_first),
            "sample": long_first["FirstName"].head(3).tolist(),
        })

    long_last = output_df[output_df["LastName"].str.len() > 50]
    if len(long_last) > 0:
        warnings.append({
            "level": "warning",
            "message": "LastName exceeds 50 characters",
            "count": len(long_last),
            "sample": long_last["LastName"].head(3).tolist(),
        })

    if file_type == "house_list":
        long_org = output_df[output_df["OrganizationName"].str.len() > 50]
        if len(long_org) > 0:
            warnings.append({
                "level": "warning",
                "message": "OrganizationName exceeds 50 characters",
                "count": len(long_org),
                "sample": long_org["OrganizationName"].head(3).tolist(),
            })

        long_addressee = output_df[output_df["PrimaryAddressee"].str.len() > 50]
        if len(long_addressee) > 0:
            warnings.append({
                "level": "warning",
                "message": "PrimaryAddressee exceeds 50 characters",
                "count": len(long_addressee),
                "sample": long_addressee["PrimaryAddressee"].head(3).tolist(),
            })

    # --- Address checks ---
    long_addr1 = output_df[output_df["AddressLine1"].str.len() > 50]
    if len(long_addr1) > 0:
        warnings.append({
            "level": "warning",
            "message": "AddressLine1 exceeds 50 characters",
            "count": len(long_addr1),
            "sample": long_addr1["AddressLine1"].head(3).tolist(),
        })

    long_addr2 = output_df[output_df["AddressLine2"].str.len() > 50]
    if len(long_addr2) > 0:
        warnings.append({
            "level": "warning",
            "message": "AddressLine2 exceeds 50 characters",
            "count": len(long_addr2),
            "sample": long_addr2["AddressLine2"].head(3).tolist(),
        })

    missing_addr = output_df[output_df["AddressLine1"] == ""]
    if len(missing_addr) > 0:
        warnings.append({
            "level": "error",
            "message": "AddressLine1 is empty",
            "count": len(missing_addr),
            "sample": [],
        })

    # --- ZIP checks ---
    missing_zip = output_df[output_df["ZIP"] == ""]
    if len(missing_zip) > 0:
        warnings.append({
            "level": "error",
            "message": "ZIP is empty",
            "count": len(missing_zip),
            "sample": [],
        })

    bad_zip = output_df[
        (output_df["ZIP"] != "")
        & (~output_df["ZIP"].apply(_validate_zip))
    ]
    if len(bad_zip) > 0:
        warnings.append({
            "level": "warning",
            "message": "ZIP does not match 5-digit or ZIP+4 format",
            "count": len(bad_zip),
            "sample": bad_zip["ZIP"].head(5).tolist(),
        })

    # --- City/State checks ---
    missing_city = output_df[
        (output_df["CityState"] == "")
        | (output_df["CityState"] == ", ")
        | (output_df["CityState"].str.strip() == ",")
    ]
    if len(missing_city) > 0:
        warnings.append({
            "level": "error",
            "message": "City/State is empty or malformed",
            "count": len(missing_city),
            "sample": [],
        })

    # --- Duplicate Constituent ID check (house list) ---
    if file_type == "house_list":
        real_ids = output_df[
            (output_df["ConstituentId"] != "")
            & (output_df["ConstituentId"] != "0")
        ]
        dups = real_ids[real_ids["ConstituentId"].duplicated(keep=False)]
        if len(dups) > 0:
            n_unique = dups["ConstituentId"].nunique()
            warnings.append({
                "level": "error",
                "message": f"Duplicate Constituent IDs ({n_unique} IDs appear more than once)",
                "count": len(dups),
                "sample": dups["ConstituentId"].unique()[:5].tolist(),
            })

    return warnings


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process_file(
    filename: str,
    file_bytes: bytes,
    list_id: int,
    key_code_override: str | None = None,
) -> dict:
    """Main entry point. Returns processing results.

    For house lists: sequence numbers are not needed (acquisition ID = all zeros).
    For rental lists: pulls sequence numbers from database if configured,
                      otherwise raises an error.
    """
    df = read_upload(filename, file_bytes)
    file_type = detect_file_type(filename, df)
    key_code_list_id = key_code_override or build_key_code_list_id(list_id)

    if file_type == "house_list":
        output_df, proc_stats = process_house_list(df, key_code_list_id)

        org_mask = output_df["OrganizationName"] != ""
        org_count = int(org_mask.sum())
        individual_count = len(output_df) - org_count

    else:
        # Rental list -- need sequence numbers from database
        if db_available():
            starting_acq_id = get_sequence_number_from_db(
                len(df), "FoodBankAcquisitionId"
            )
        else:
            raise RuntimeError(
                "Database connection not configured. "
                "Rental lists require the MailWorks database for sequence numbers. "
                "Set MAILWORKS_CONN_STRING environment variable."
            )

        output_df = process_rental_list(
            df, key_code_list_id, starting_acq_id, file_type
        )
        org_count = 0
        individual_count = len(output_df)
        proc_stats = {"and_replaced_count": 0}

    # Run validation
    validation_warnings = validate(output_df, file_type)

    preview = output_df.head(10).fillna("").to_dict(orient="records")

    return {
        "file_type": file_type,
        "record_count": len(output_df),
        "org_count": org_count,
        "individual_count": individual_count,
        "preview": preview,
        "output_df": output_df,
        "key_code_list_id": key_code_list_id,
        "warnings": validation_warnings,
        "and_replaced_count": proc_stats.get("and_replaced_count", 0),
        "db_connected": db_available(),
    }


def output_to_csv_bytes(output_df: pd.DataFrame) -> bytes:
    """Convert processed DataFrame to CSV bytes for download."""
    buf = io.StringIO()
    output_df.to_csv(buf, index=False, quoting=csv.QUOTE_ALL)
    return buf.getvalue().encode("utf-8")
