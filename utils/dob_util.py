"""Date of birth parsing, validation, and display (stored as date, shown as DD-MM-YYYY)."""

import logging
from datetime import date, datetime
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

DOB_FORMAT = "%d-%m-%Y"
DOB_FORMAT_DISPLAY = "DD-MM-YYYY"
EXCEL_SERIAL_ORIGIN = "1899-12-30"
_EMPTY_TOKENS = frozenset({"", "nan", "none", "nat", "null", "<na>"})


class DobValidationError(ValueError):
    """Raised when a date of birth value is invalid."""


def detect_dob_type(value: Any) -> str:
    """Return a readable label for the incoming DOB value type."""
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, pd.Timestamp):
        return "pandas.Timestamp"
    if isinstance(value, datetime):
        return "datetime.datetime"
    if isinstance(value, date):
        return "datetime.date"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        if pd.isna(value):
            return "float(nan)"
        # Excel serial dates are typically > 1 (1900-01-01 ~= 1)
        if value > 1:
            return "excel_serial(float)"
        return "float"
    if isinstance(value, str):
        return "str"
    return type(value).__name__


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and value.strip().lower() in _EMPTY_TOKENS:
        return True
    return False


def _excel_serial_to_date(serial: float) -> date:
    """Convert Excel day serial (float/int) to a calendar date."""
    converted = pd.to_datetime(serial, unit="D", origin=EXCEL_SERIAL_ORIGIN)
    if pd.isna(converted):
        raise DobValidationError(f"Invalid Excel date serial: {serial}")
    return converted.date()


def _parse_dob_string(raw: str) -> date:
    text = raw.strip()
    if not text or text.lower() in _EMPTY_TOKENS:
        raise DobValidationError("Date of birth is empty.")

    # YYYY-MM-DD (ISO)
    if len(text) >= 10 and text[4] == "-" and text[7] == "-" and text[:4].isdigit():
        try:
            parsed = datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError as exc:
            raise DobValidationError(
                f"Invalid date of birth '{raw}'. Use {DOB_FORMAT_DISPLAY} or a valid Excel date."
            ) from exc
    else:
        try:
            parsed = datetime.strptime(text, DOB_FORMAT).date()
        except ValueError as exc:
            raise DobValidationError(
                f"Invalid date of birth '{raw}'. Use {DOB_FORMAT_DISPLAY} (e.g. 15-06-1995)."
            ) from exc

    if parsed > date.today():
        raise DobValidationError("Date of birth cannot be in the future.")
    return parsed


def _finalize_date(parsed: date) -> date:
    if parsed > date.today():
        raise DobValidationError("Date of birth cannot be in the future.")
    return parsed


def coerce_dob_to_date(
    value: Any,
    *,
    employee_id: str | None = None,
    row_num: int | None = None,
    log_debug: bool = True,
) -> date | None:
    """
    Parse any supported DOB input into a Python date object.

    Supports: date/datetime, pandas Timestamp, Excel serial (int/float),
    DD-MM-YYYY strings, YYYY-MM-DD strings.
    """
    raw_repr = repr(value)
    type_label = detect_dob_type(value)

    if _is_empty(value):
        if log_debug:
            logger.debug(
                "DOB parse | employee=%s row=%s | raw=%s | type=%s | converted=None (empty)",
                employee_id or "-",
                row_num or "-",
                raw_repr,
                type_label,
            )
        return None

    try:
        if isinstance(value, date) and not isinstance(value, datetime):
            parsed = value
        elif isinstance(value, datetime):
            parsed = value.date()
        elif isinstance(value, pd.Timestamp):
            parsed = value.to_pydatetime().date()
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            if isinstance(value, float) and pd.isna(value):
                return None
            parsed = _excel_serial_to_date(float(value))
        elif isinstance(value, str):
            parsed = _parse_dob_string(value)
        else:
            # Fallback: pandas may return numpy datetime64, etc.
            converted = pd.to_datetime(value, errors="coerce", dayfirst=True)
            if pd.isna(converted):
                raise DobValidationError(f"Unsupported DOB value: {value!r}")
            parsed = converted.date() if hasattr(converted, "date") else converted.to_pydatetime().date()

        parsed = _finalize_date(parsed)

        if log_debug:
            logger.info(
                "DOB parse | employee=%s row=%s | raw=%s | type=%s | converted=%s",
                employee_id or "-",
                row_num or "-",
                raw_repr,
                type_label,
                parsed.isoformat(),
            )
        return parsed

    except DobValidationError:
        if log_debug:
            logger.warning(
                "DOB parse failed | employee=%s row=%s | raw=%s | type=%s",
                employee_id or "-",
                row_num or "-",
                raw_repr,
                type_label,
            )
        raise
    except Exception as exc:
        if log_debug:
            logger.warning(
                "DOB parse failed | employee=%s row=%s | raw=%s | type=%s | error=%s",
                employee_id or "-",
                row_num or "-",
                raw_repr,
                type_label,
                exc,
            )
        raise DobValidationError(
            f"Could not parse date of birth '{value}'. Use {DOB_FORMAT_DISPLAY} or an Excel date cell."
        ) from exc


def parse_dob(value: str | None, *, required: bool = False) -> date | None:
    """Validate DOB from HTML forms (DD-MM-YYYY or YYYY-MM-DD string)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise DobValidationError(
                f"Date of birth is required. Use format {DOB_FORMAT_DISPLAY}."
            )
        return None
    return coerce_dob_to_date(value.strip(), log_debug=False)


def parse_dob_from_upload(
    value: Any,
    *,
    employee_id: str | None = None,
    row_num: int | None = None,
) -> date | None:
    """Parse DOB from CSV/Excel upload cells with debug logging."""
    return coerce_dob_to_date(
        value,
        employee_id=employee_id,
        row_num=row_num,
        log_debug=True,
    )


def format_dob_display(value: date | str | None) -> str | None:
    """Format stored DOB for UI as DD-MM-YYYY."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.strftime(DOB_FORMAT)
    if isinstance(value, datetime):
        return value.date().strftime(DOB_FORMAT)
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            parsed = coerce_dob_to_date(value, log_debug=False)
            return parsed.strftime(DOB_FORMAT) if parsed else None
        except DobValidationError:
            return value.strip()
    try:
        parsed = coerce_dob_to_date(value, log_debug=False)
        return parsed.strftime(DOB_FORMAT) if parsed else None
    except DobValidationError:
        return str(value)


def dob_day_month_parts(value: date | str | None) -> tuple[str, str] | None:
    """Extract two-digit day and month for PDF password generation."""
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.strftime("%d"), value.strftime("%m")
    displayed = format_dob_display(value)
    if not displayed or len(displayed) < 10:
        return None
    return displayed[0:2], displayed[3:5]
