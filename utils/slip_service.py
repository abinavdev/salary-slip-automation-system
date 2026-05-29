"""Generate one salary slip PDF and send email (single employee per call)."""

import gc
import logging
from pathlib import Path

from utils.datetime_util import utc_now
from utils.email_sender import send_salary_slip_email
from utils.pdf_generator import generate_salary_slip

logger = logging.getLogger(__name__)


def process_one_slip(record, employee, pdf_folder, db_session, email_log_model):
    """
    Generate PDF, send email, and write EmailLog for one salary record.

    Returns:
        dict: ok, password (str|None), error (str|None), employee_id, employee_name
    """
    employee_id = record.employee_id
    employee_name = employee.name if employee else "Unknown"

    logger.info(
        "slip-dispatch process_one_slip start | employee_id=%s month=%s year=%s",
        employee_id,
        record.month,
        record.year,
    )

    if not employee:
        error = f"No employee found for ID {employee_id}"
        logger.error(error)
        db_session.add(
            email_log_model(
                employee_id=employee_id,
                employee_name="Unknown",
                month=record.month,
                year=record.year,
                sent_at=utc_now(),
                status="failed",
            )
        )
        return {
            "ok": False,
            "password": None,
            "error": error,
            "employee_id": employee_id,
            "employee_name": "Unknown",
        }

    employee_data = {
        "employee_id": employee.employee_id,
        "name": employee.name,
        "email": employee.email,
        "designation": employee.designation,
        "date_of_birth": employee.date_of_birth,
    }
    salary_data = {
        "base_salary": record.base_salary,
        "hra": record.hra,
        "allowances": record.allowances,
        "deductions": record.deductions,
        "net_salary": record.net_salary,
        "month": record.month,
        "year": record.year,
    }

    safe_month = str(record.month).replace(" ", "_")
    pdf_filename = f"salary_slip_{employee.employee_id}_{safe_month}_{record.year}.pdf"
    pdf_path = str(Path(pdf_folder) / pdf_filename)

    try:
        pdf_path, pdf_password = generate_salary_slip(employee_data, salary_data, pdf_path)
        logger.info("PDF generated for %s: %s", employee_id, pdf_path)
    except Exception as pdf_err:
        error = f"PDF error for {employee_id}: {pdf_err}"
        logger.exception(error)
        db_session.add(
            email_log_model(
                employee_id=employee.employee_id,
                employee_name=employee.name,
                month=record.month,
                year=record.year,
                sent_at=utc_now(),
                status="failed",
            )
        )
        return {
            "ok": False,
            "password": None,
            "error": error,
            "employee_id": employee_id,
            "employee_name": employee_name,
        }

    logger.info(
        "Sending salary slip via SendGrid | employee=%s | to=%s | pdf=%s",
        employee_id,
        employee_data.get("email"),
        pdf_path,
    )

    try:
        sent_ok, send_err = send_salary_slip_email(
            employee_data, salary_data, pdf_path, pdf_password
        )
    except Exception as email_err:
        error = f"SendGrid error for {employee_id}: {email_err}"
        logger.exception(error)
        db_session.add(
            email_log_model(
                employee_id=employee.employee_id,
                employee_name=employee.name,
                month=record.month,
                year=record.year,
                sent_at=utc_now(),
                status="failed",
            )
        )
        gc.collect()
        return {
            "ok": False,
            "password": None,
            "error": error,
            "employee_id": employee_id,
            "employee_name": employee_name,
        }

    if not sent_ok:
        error = send_err or f"SendGrid send failed for {employee_id} ({employee_data.get('email')})"
        logger.error(error)
        db_session.add(
            email_log_model(
                employee_id=employee.employee_id,
                employee_name=employee.name,
                month=record.month,
                year=record.year,
                sent_at=utc_now(),
                status="failed",
            )
        )
        gc.collect()
        return {
            "ok": False,
            "password": None,
            "error": error,
            "employee_id": employee_id,
            "employee_name": employee_name,
        }

    db_session.add(
        email_log_model(
            employee_id=employee.employee_id,
            employee_name=employee.name,
            month=record.month,
            year=record.year,
            sent_at=utc_now(),
            status="success",
        )
    )
    logger.info(
        "SendGrid email sent successfully | employee=%s | to=%s",
        employee_id,
        employee_data.get("email"),
    )

    try:
        Path(pdf_path).unlink(missing_ok=True)
    except OSError as cleanup_err:
        logger.warning("Could not remove PDF after send %s: %s", pdf_path, cleanup_err)

    gc.collect()
    return {
        "ok": True,
        "password": pdf_password,
        "error": None,
        "employee_id": employee_id,
        "employee_name": employee_name,
    }
