"""Production-ready email utilities for salary slips (SendGrid API)."""

import base64
import logging
import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from python_http_client.exceptions import HTTPError
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Attachment,
    Disposition,
    Email,
    FileContent,
    FileName,
    FileType,
    Mail,
    ReplyTo,
)

logger = logging.getLogger(__name__)


def _get_company_config() -> dict:
    company_name = os.getenv("COMPANY_NAME", "Nippon Toyota").strip() or "Nippon Toyota"
    company_email = os.getenv("COMPANY_EMAIL", "").strip() or os.getenv("FROM_EMAIL", "").strip()
    company_phone = os.getenv("COMPANY_PHONE", "").strip()
    company_address = os.getenv("COMPANY_ADDRESS", "").strip()
    company_logo_url = os.getenv("COMPANY_LOGO_URL", "").strip()
    sender_name = os.getenv("SENDER_NAME", company_name).strip() or company_name

    return {
        "company_name": company_name,
        "company_email": company_email,
        "company_phone": company_phone,
        "company_address": company_address,
        "company_logo_url": company_logo_url,
        "sender_name": sender_name,
    }


def _email_template_env() -> Environment:
    templates_dir = Path(__file__).resolve().parent.parent / "templates" / "emails"
    return Environment(
        loader=FileSystemLoader(str(templates_dir)),
        autoescape=select_autoescape(enabled_extensions=("html", "xml")),
    )


def _render_email_templates(context: dict) -> tuple[str, str]:
    env = _email_template_env()
    html_t = env.get_template("salary_slip.html")
    txt_t = env.get_template("salary_slip.txt")
    return txt_t.render(**context).strip() + "\n", html_t.render(**context)


def _get_sendgrid_config():
    """Read SendGrid API key and verified sender email from environment."""
    api_key = os.environ.get("SENDGRID_API_KEY", "").strip()
    from_email = os.environ.get("FROM_EMAIL", "").strip()
    return api_key or None, from_email or None


def _sendgrid_timeout() -> int:
    return int(os.environ.get("SENDGRID_TIMEOUT", "30"))


def _create_sendgrid_client(api_key: str) -> SendGridAPIClient:
    """Create SendGrid client (uses HTTPS; default library timeouts apply)."""
    return SendGridAPIClient(api_key)


def send_email(
    to_email: str,
    subject: str,
    plain_content: str,
    html_content: str,
    pdf_path=None,
    *,
    reply_to: str | None = None,
    sender_name: str | None = None,
):
    """
    Send an email via SendGrid HTTP API (Render-friendly, no SMTP blocking).

    Returns:
        tuple: (success: bool, error_message: str | None)
    """
    api_key, from_email = _get_sendgrid_config()

    logger.info(
        "SendGrid send start | to=%s | from=%s | api_key_set=%s | attachment=%s",
        to_email,
        from_email or "NOT SET",
        "yes" if api_key else "no",
        pdf_path or "none",
    )

    if not api_key or not from_email:
        msg = "Missing SENDGRID_API_KEY or FROM_EMAIL on server."
        logger.error(msg)
        return False, msg

    if not to_email:
        msg = "Recipient email is empty."
        logger.error(msg)
        return False, msg

    try:
        message = Mail(
            from_email=Email(from_email, name=(sender_name or "").strip() or None),
            to_emails=to_email,
            subject=subject,
            plain_text_content=plain_content,
            html_content=html_content,
        )

        if reply_to:
            message.reply_to = ReplyTo(reply_to)

        if pdf_path:
            pdf_file = Path(pdf_path)
            if not pdf_file.is_file():
                msg = f"PDF attachment not found: {pdf_path}"
                logger.error(msg)
                return False, msg

            with pdf_file.open("rb") as attachment_file:
                raw = attachment_file.read()
                encoded_pdf = base64.b64encode(raw).decode("ascii")
                # Validate base64 round-trip (helps avoid malformed attachments)
                try:
                    base64.b64decode(encoded_pdf.encode("ascii"), validate=True)
                except Exception:
                    return False, "PDF attachment encoding failed (base64 validation)."

            safe_name = pdf_file.name.replace(" ", "_")

            message.add_attachment(
                Attachment(
                    FileContent(encoded_pdf),
                    FileName(safe_name),
                    FileType("application/pdf"),
                    Disposition("attachment"),
                )
            )

        client = _create_sendgrid_client(api_key)
        response = client.send(message)

        status = response.status_code
        message_id = None
        try:
            message_id = (response.headers or {}).get("X-Message-Id")
        except Exception:
            message_id = None
        if 200 <= status < 300:
            logger.info(
                "SendGrid send success | to=%s | status=%s | message_id=%s",
                to_email,
                status,
                message_id or "-",
            )
            return True, None

        body = response.body
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        msg = f"SendGrid rejected (HTTP {status}): {body}"
        logger.error(
            "SendGrid rejected | to=%s | status=%s | message_id=%s | body=%s",
            to_email,
            status,
            message_id or "-",
            body,
        )
        return False, msg

    except HTTPError as exc:
        body = getattr(exc, "body", b"")
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        status = getattr(exc, "status_code", "unknown")
        msg = f"SendGrid HTTP {status}: {body}"
        logger.error("SendGrid HTTP error | to=%s | %s", to_email, msg)
        return False, msg
    except Exception as exc:
        logger.exception("Unexpected SendGrid error sending to %s: %s", to_email, exc)
        return False, str(exc)


def _format_currency(amount):
    """Format numeric salary value for email display."""
    try:
        return f"{float(amount):,.2f}"
    except (TypeError, ValueError):
        return "0.00"


def send_salary_slip_email(employee, salary_record, pdf_path, pdf_password=None):
    """
    Send one salary slip email with PDF attachment.

    Args:
        employee (dict): name, email, employee_id, date_of_birth (optional)
        salary_record (dict): month, year, net_salary (optional)
        pdf_path (str): Path to generated PDF
        pdf_password (str | None): Kept for API compatibility; not included in email body

    Returns:
        bool: True if sent successfully
    """
    employee_name = str(employee.get("name", "Employee")).strip()
    recipient_email = str(employee.get("email", "")).strip()
    employee_id = str(employee.get("employee_id", "")).strip()
    date_of_birth = str(employee.get("date_of_birth", "")).strip()
    month = str(salary_record.get("month", "")).strip()
    year = str(salary_record.get("year", "")).strip()
    net_salary = salary_record.get("net_salary", 0)

    logger.info(
        "Salary slip email | employee=%s | to=%s | month=%s %s | pdf=%s",
        employee_id or employee_name,
        recipient_email or "MISSING",
        month,
        year,
        pdf_path,
    )

    if not recipient_email:
        msg = f"Recipient email missing for {employee_name}"
        logger.error(msg)
        return False, msg

    try:
        company = _get_company_config()
        company_name = company["company_name"]
        subject = f"Salary Slip for {month} - {company_name}"

        if date_of_birth:
            password_hint_html = (
                "This PDF is password protected for your privacy.<br>"
                "Password formula: first 4 letters of your name (lowercase) + birth day + birth month.<br>"
                "Example: Arjun, 15 June → <strong>arju1506</strong>."
            )
            password_hint_text = (
                "This PDF is password protected for your privacy.\n"
                "Password formula: first 4 letters of your name (lowercase) + birth day + birth month.\n"
                "Example: Arjun, 15 June -> arju1506."
            )
        else:
            password_hint_html = (
                "This PDF is password protected.<br>"
                f"Password: your Employee ID (<strong>{employee_id or 'N/A'}</strong>)."
            )
            password_hint_text = (
                "This PDF is password protected.\n"
                f"Password: your Employee ID ({employee_id or 'N/A'})."
            )

        net_salary_text = f"₹ {_format_currency(net_salary)}"

        context = {
            "company_name": company_name,
            "company_email": company["company_email"] or "hr@example.com",
            "company_phone": company["company_phone"],
            "company_address": company["company_address"],
            "company_logo_url": company["company_logo_url"],
            "system_name": "Employee Salary Slip Automation System",
            "employee_name": employee_name,
            "employee_id": employee_id,
            "month": month,
            "year": year,
            "net_salary": net_salary_text,
            "password_hint_html": password_hint_html,
            "password_hint_text": password_hint_text,
        }

        plain_content, html_content = _render_email_templates(context)

        sent, err = send_email(
            to_email=recipient_email,
            subject=subject,
            plain_content=plain_content,
            html_content=html_content,
            pdf_path=pdf_path,
            reply_to=(company["company_email"] or None),
            sender_name=company["sender_name"],
        )
        if sent:
            logger.info(
                "Salary slip email delivered via SendGrid | employee=%s | to=%s",
                employee_id or employee_name,
                recipient_email,
            )
            return True, None
        logger.error(
            "Salary slip email failed | employee=%s | to=%s | pdf=%s | %s",
            employee_id or employee_name,
            recipient_email,
            pdf_path,
            err,
        )
        return False, err

    except Exception as exc:
        logger.exception("Failed to build salary slip email for %s", employee_name)
        return False, str(exc)


def send_all_slips(employees_and_records, pdf_folder):
    """Send salary slips to all employees in a collection."""
    sent_count = 0
    total_count = len(employees_and_records)

    for item in employees_and_records:
        employee = item.get("employee", {})
        salary_record = item.get("salary_record", {})

        pdf_path = item.get("pdf_path")
        if not pdf_path:
            employee_id = str(employee.get("employee_id", "")).strip()
            month = str(salary_record.get("month", "")).strip().replace(" ", "_")
            year = str(salary_record.get("year", "")).strip()
            filename = f"salary_slip_{employee_id}_{month}_{year}.pdf"
            pdf_path = str(Path(pdf_folder) / filename)

        employee_id = str(employee.get("employee_id", "unknown"))
        ok, _err = send_salary_slip_email(
            employee, salary_record, pdf_path, item.get("pdf_password")
        )
        if ok:
            sent_count += 1
            logger.info("SendGrid batch item success | employee=%s", employee_id)
        else:
            logger.error(
                "SendGrid batch item failed | employee=%s | to=%s | pdf=%s",
                employee_id,
                employee.get("email"),
                pdf_path,
            )

    logger.info("SendGrid batch dispatch complete: %s/%s sent", sent_count, total_count)
    return {"sent": sent_count, "failed": total_count - sent_count, "total": total_count}
