"""Lightweight SQLite schema upgrades without Flask-Migrate."""

import logging
from datetime import date, datetime

from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


def _column_names(inspector, table_name: str) -> set:
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade_schema(db) -> None:
    """Add new columns/tables for existing deployments."""
    engine = db.engine
    inspector = inspect(engine)

    if "employees" in inspector.get_table_names():
        cols = _column_names(inspector, "employees")
        with engine.begin() as conn:
            if "created_at" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE employees ADD COLUMN created_at DATETIME"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE employees SET created_at = CURRENT_TIMESTAMP "
                        "WHERE created_at IS NULL"
                    )
                )
                logger.info("Added employees.created_at")
            if "updated_at" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE employees ADD COLUMN updated_at DATETIME"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE employees SET updated_at = CURRENT_TIMESTAMP "
                        "WHERE updated_at IS NULL"
                    )
                )
                logger.info("Added employees.updated_at")

    db.create_all()
    _migrate_dob_values_to_date_objects(db)


def _migrate_dob_values_to_date_objects(db) -> None:
    """Convert legacy string DOB values to Python date objects in the database."""
    from models import Employee
    from utils.dob_util import DobValidationError, coerce_dob_to_date

    try:
        employees = Employee.query.filter(Employee.date_of_birth.isnot(None)).all()
    except Exception as exc:
        logger.debug("DOB value migration skipped: %s", exc)
        return

    changed = 0
    cleared = 0
    for employee in employees:
        val = employee.date_of_birth
        if isinstance(val, date) and not isinstance(val, datetime):
            continue
        if isinstance(val, datetime):
            employee.date_of_birth = val.date()
            changed += 1
            continue
        if isinstance(val, str):
            try:
                parsed = coerce_dob_to_date(
                    val,
                    employee_id=employee.employee_id,
                    log_debug=False,
                )
                employee.date_of_birth = parsed
                changed += 1
            except DobValidationError:
                employee.date_of_birth = None
                cleared += 1
                logger.warning(
                    "Cleared unparseable DOB for Employee ID '%s' during migration",
                    employee.employee_id,
                )

    if changed or cleared:
        try:
            db.session.commit()
            logger.info(
                "DOB migration: %s value(s) converted to date, %s cleared",
                changed,
                cleared,
            )
        except Exception as exc:
            db.session.rollback()
            logger.warning("DOB migration commit failed: %s", exc)
