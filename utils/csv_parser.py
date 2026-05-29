"""CSV/Excel parsing utilities for employee and salary uploads."""

import logging
from pathlib import Path

import pandas as pd

from utils.dob_util import DobValidationError, parse_dob_from_upload

logger = logging.getLogger(__name__)


def _read_file_to_dataframe(filepath):
    """Read CSV or Excel file into a pandas DataFrame."""
    path = Path(filepath)
    suffix = path.suffix.lower()

    if not path.exists():
        raise FileNotFoundError(f"File not found: {filepath}")

    if suffix == ".csv":
        df = pd.read_csv(path)
    elif suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
    else:
        raise ValueError(
            "Unsupported file format. Please upload a CSV or Excel file (.csv, .xlsx, .xls)."
        )

    if "Date of Birth" in df.columns:
        df["Date of Birth"] = pd.to_datetime(
            df["Date of Birth"],
            errors="coerce",
            dayfirst=True,
        )

    return df


def _validate_required_columns(df, required_columns):
    """Validate that all required columns are present."""
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        raise ValueError(
            f"Missing required columns: {', '.join(missing_columns)}. "
            f"Expected columns are: {', '.join(required_columns)}."
        )


def _clean_string(value):
    """Convert value to clean string with whitespace stripped."""
    if pd.isna(value):
        return ""
    return str(value).strip()


def _to_float(value):
    """Safely convert value to float. Missing/invalid values become 0.0."""
    if pd.isna(value):
        return 0.0

    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if value == "":
            return 0.0

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _cell_has_dob_value(raw_dob) -> bool:
    if raw_dob is None:
        return False
    if isinstance(raw_dob, float) and pd.isna(raw_dob):
        return False
    try:
        if pd.isna(raw_dob):
            return False
    except (TypeError, ValueError):
        pass
    text = str(raw_dob).strip()
    return text not in ("", "nan", "NaT", "None")


def parse_employee_csv(filepath):
    """
    Parse employee CSV/Excel file.

    Expected columns: Employee ID, Name, Email, Designation
    Optional column: Date of Birth (Excel date, DD-MM-YYYY, or YYYY-MM-DD)

    Returns:
        tuple: (records, dob_errors)
        - records: list of employee dicts with date_of_birth as datetime.date or None
        - dob_errors: list of (employee_id, error_message) for invalid DOBs
    """
    required_columns = ["Employee ID", "Name", "Email", "Designation"]

    try:
        df = _read_file_to_dataframe(filepath)
        _validate_required_columns(df, required_columns)

        has_dob = "Date of Birth" in df.columns
        records = []
        dob_errors = []

        for row_num, (_, row) in enumerate(df.iterrows(), start=2):
            employee_id = _clean_string(row.get("Employee ID"))
            date_of_birth = None

            if has_dob and _cell_has_dob_value(row.get("Date of Birth")):
                raw_dob = row.get("Date of Birth")
                try:
                    date_of_birth = parse_dob_from_upload(
                        raw_dob,
                        employee_id=employee_id or None,
                        row_num=row_num,
                    )
                except DobValidationError as exc:
                    label = employee_id or f"row {row_num}"
                    message = str(exc)
                    dob_errors.append((label, message))
                    logger.warning(
                        "Skipping invalid DOB for Employee ID '%s' (row %s): %s",
                        label,
                        row_num,
                        message,
                    )

            records.append(
                {
                    "employee_id": employee_id,
                    "name": _clean_string(row.get("Name")),
                    "email": _clean_string(row.get("Email")),
                    "designation": _clean_string(row.get("Designation")),
                    "date_of_birth": date_of_birth,
                }
            )

        if dob_errors:
            logger.warning(
                "Employee file '%s' had %s row(s) with invalid DOB (employees still imported).",
                filepath,
                len(dob_errors),
            )

        return records, dob_errors
    except Exception:
        logger.exception("Error parsing employee file '%s'", filepath)
        raise
    finally:
        if "df" in locals():
            del df


def parse_salary_csv(filepath):
    """
    Parse salary CSV/Excel file.

    Expected columns: Employee ID, Base Salary, HRA, Allowances, Deductions, Month, Year
    """
    required_columns = [
        "Employee ID",
        "Base Salary",
        "HRA",
        "Allowances",
        "Deductions",
        "Month",
        "Year",
    ]

    try:
        df = _read_file_to_dataframe(filepath)
        _validate_required_columns(df, required_columns)

        records = []
        for _, row in df.iterrows():
            base_salary = _to_float(row.get("Base Salary"))
            hra = _to_float(row.get("HRA"))
            allowances = _to_float(row.get("Allowances"))
            deductions = _to_float(row.get("Deductions"))
            net_salary = (base_salary + hra + allowances) - deductions

            records.append(
                {
                    "employee_id": _clean_string(row.get("Employee ID")),
                    "base_salary": float(base_salary),
                    "hra": float(hra),
                    "allowances": float(allowances),
                    "deductions": float(deductions),
                    "net_salary": float(net_salary),
                    "month": _clean_string(row.get("Month")),
                    "year": int(_to_float(row.get("Year"))),
                }
            )

        return records
    except Exception:
        logger.exception("Error parsing salary file '%s'", filepath)
        raise
    finally:
        if "df" in locals():
            del df
