"""Portal 1 formatting logic (Step 2).

Transforms the Step 1 output (17-column scanline CSV) into the
21-column Final For Entry format required by Portal 1's Order Importer.

Transformations:
- Drop: ConstituentId, OrganizationName, PrimaryAddressee, PrimarySalutation,
        AddressLine2, County, LastGiftDate
- Split CityState into City + State
- Split ZIP into 5-digit ZIP + zip4 (always empty)
- Org names: FirstName = "Our Friends at ", LastName = org name
- Individuals: Take PrimaryAddressee, collapse spaces,
  split on first space for FirstName/LastName
- Add Reserve17 (KeyCodeListId), Reserve18 (sequential row number),
  Reserve19 (ScanLine), Reserve20 (PrimarySalutation)
- Add campaign fields: Store, Creative, eventdate (optional)
- Add empty placeholders: zip4, Phone, ihd
"""

import io
import csv
import re
import pandas as pd


PORTAL_COLUMNS = [
    "FirstName", "LastName", "AddressLine1", "City", "State", "ZIP", "zip4",
    "Store", "Creative", "Phone", "ihd", "eventdate",
    "Reserve17", "Reserve18", "Reserve19", "Reserve20",
    "AcquisitionId", "DonorId", "KeyCodeListId", "CheckDigit", "ScanLine",
]


def _clean(val) -> str:
    """Clean a value: convert NaN/None/nan to empty string, collapse internal spaces."""
    s = str(val).strip() if val is not None else ""
    if s in ("nan", "None", "NaT"):
        return ""
    return re.sub(r" {2,}", " ", s)


def format_for_portal(
    step1_df: pd.DataFrame,
    store: str = "",
    creative: str = "",
    eventdate: str = "",
) -> tuple[pd.DataFrame, dict]:
    """Transform Step 1 output into Portal 1 Final For Entry format.

    Args:
        step1_df: DataFrame from Step 1 processing (17 columns)
        store: Campaign store value (e.g., "RFBB0001")
        creative: Campaign creative value (e.g., "April HV")
        eventdate: Campaign event date (e.g., "April 1, 2026")

    Returns:
        (portal_df, stats) where stats has org_count, individual_count, etc.
    """
    records = []
    org_count = 0
    ind_count = 0

    for idx, (_, row) in enumerate(step1_df.iterrows()):
        row_num = idx + 1

        org_name = _clean(row.get("OrganizationName"))
        first_name = _clean(row.get("FirstName"))
        last_name = _clean(row.get("LastName"))
        primary_addressee = _clean(row.get("PrimaryAddressee"))
        primary_salutation = _clean(row.get("PrimarySalutation"))
        address1 = _clean(row.get("AddressLine1"))
        address2 = _clean(row.get("AddressLine2"))
        if address2:
            address1 = address1 + " " + address2
        city_state = _clean(row.get("CityState"))
        zip_full = _clean(row.get("ZIP"))
        acquisition_id = _clean(row.get("AcquisitionId"))
        donor_id = _clean(row.get("DonorId"))
        key_code_list_id = _clean(row.get("KeyCodeListId"))
        check_digit = _clean(row.get("CheckDigit"))
        scan_line = _clean(row.get("ScanLine"))

        # Determine org vs individual
        is_org = bool(org_name) and not first_name and not last_name

        # Name transformation
        if is_org:
            final_first = "Our Friends at"
            final_last = org_name
            org_count += 1
        else:
            # Use PrimaryAddressee, collapse multiple spaces, split on first space
            addressee = " ".join(primary_addressee.split())
            space_idx = addressee.find(" ")
            if space_idx == -1:
                final_first = addressee
                final_last = ""
            else:
                final_first = addressee[:space_idx]
                final_last = addressee[space_idx + 1:]
            ind_count += 1

        # Split CityState on last comma
        city = ""
        state = ""
        comma_idx = city_state.rfind(",")
        if comma_idx != -1:
            city = city_state[:comma_idx].strip()
            state = city_state[comma_idx + 1:].strip()
        else:
            city = city_state

        # Split ZIP (take 5-digit part only)
        zip5 = zip_full.split("-")[0] if zip_full else ""

        # Reserve18 = sequential row number, zero-padded to 5
        reserve18 = str(row_num).zfill(5)

        records.append({
            "FirstName": final_first,
            "LastName": final_last,
            "AddressLine1": address1,
            "City": city,
            "State": state,
            "ZIP": zip5,
            "zip4": "",
            "Store": store,
            "Creative": creative,
            "Phone": "",
            "ihd": "",
            "eventdate": eventdate,
            "Reserve17": key_code_list_id,
            "Reserve18": reserve18,
            "Reserve19": scan_line,
            "Reserve20": primary_salutation,
            "AcquisitionId": acquisition_id,
            "DonorId": donor_id,
            "KeyCodeListId": key_code_list_id,
            "CheckDigit": check_digit,
            "ScanLine": scan_line,
        })

    portal_df = pd.DataFrame(records, columns=PORTAL_COLUMNS)

    stats = {
        "org_count": org_count,
        "individual_count": ind_count,
        "total_count": len(records),
    }

    return portal_df, stats


def portal_to_csv_bytes(portal_df: pd.DataFrame) -> bytes:
    """Convert Portal DataFrame to CSV bytes for download."""
    buf = io.StringIO()
    portal_df.to_csv(buf, index=False, quoting=csv.QUOTE_NONNUMERIC)
    return buf.getvalue().encode("utf-8")
