"""PDF generation utilities for salary slips."""

import logging
from pathlib import Path

import pikepdf
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate

from utils.pdf_styles import (
    PayrollPdfTheme,
    build_salary_slip_story,
    draw_slip_page_frame,
)

logger = logging.getLogger(__name__)


def _format_currency(amount):
    """Backward-compatible currency helper for any external callers."""
    from utils.pdf_styles import format_currency_inr

    return format_currency_inr(amount).replace("₹ ", "")


def encrypt_pdf(input_path, output_path, password):
    """Encrypt PDF using a user/owner password."""
    with pikepdf.open(input_path) as pdf:
        pdf.save(
            output_path,
            encryption=pikepdf.Encryption(
                owner=password,
                user=password,
                R=4,
            ),
        )


def generate_pdf_password(employee):
    """Generate deterministic PDF password from employee data."""
    from utils.dob_util import dob_day_month_parts

    name_part = str(employee.get("name", "")).replace(" ", "").lower()[:4]
    parts = dob_day_month_parts(employee.get("date_of_birth"))
    if parts:
        day_part, month_part = parts
        return f"{name_part}{day_part}{month_part}"
    return str(employee.get("employee_id", ""))


def generate_salary_slip(employee, salary_record, output_path):
    """
    Generate a professional salary slip PDF for an employee.

    Args:
        employee (dict): employee_id, name, email, designation
        salary_record (dict): base_salary, hra, allowances, deductions, net_salary, month, year
        output_path (str): Full file path where the PDF should be saved

    Returns:
        tuple[str, str]: output path and generated password
    """
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)

    theme = PayrollPdfTheme()

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=theme.margin_right,
        leftMargin=theme.margin_left,
        topMargin=theme.margin_top,
        bottomMargin=theme.margin_bottom,
        title="Employee Salary Slip",
        author=theme.system_name,
    )

    def _on_page(canvas, document):
        draw_slip_page_frame(canvas, document, theme)

    story = build_salary_slip_story(employee, salary_record, theme)
    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)

    password = generate_pdf_password(employee)
    temp_output = output_file.with_name(f"{output_file.stem}_encrypted{output_file.suffix}")
    try:
        encrypt_pdf(str(output_file), str(temp_output), password)
        temp_output.replace(output_file)
    except Exception as exc:
        logger.warning(
            "PDF encryption failed for '%s': %s. Sending unencrypted PDF.",
            output_path,
            exc,
        )
        if temp_output.exists():
            temp_output.unlink(missing_ok=True)
    return output_path, password
