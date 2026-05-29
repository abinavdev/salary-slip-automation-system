"""Reusable styling helpers and layout builders for salary slip PDFs."""

from __future__ import annotations

import calendar
import os
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from utils.datetime_util import utc_now

# Ensure ReportLab can render the Indian Rupee symbol (₹) by registering a
# Unicode-capable TrueType font. DejaVu Sans and Noto Sans are commonly available
# across Windows and Render Linux.
logger = logging.getLogger(__name__)

FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"


def _find_first_existing(paths: list[str]) -> Path | None:
    for p in paths:
        candidate = Path(p)
        if candidate.is_file():
            return candidate
    return None


def _register_unicode_font() -> None:
    global FONT_REGULAR, FONT_BOLD

    override = os.getenv("UNICODE_TTF_FONT", "").strip()
    if override:
        p = Path(override)
        if p.is_file():
            FONT_REGULAR = "UnicodeTtf"
            pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(p)))
            FONT_BOLD = FONT_REGULAR
            return

    # Windows common locations (filenames vary: with/without spaces)
    windows_dejavu_regular = [
        r"C:\Windows\Fonts\DejaVuSans.ttf",
        r"C:\Windows\Fonts\DejaVuSansCondensed.ttf",
        r"C:\Windows\Fonts\DejaVu Sans.ttf",
        r"C:\Windows\Fonts\DejaVu Sans Condensed.ttf",
    ]
    windows_dejavu_bold = [
        r"C:\Windows\Fonts\DejaVuSans-Bold.ttf",
        r"C:\Windows\Fonts\DejaVuSansCondensed-Bold.ttf",
        r"C:\Windows\Fonts\DejaVu Sans-Bold.ttf",
        r"C:\Windows\Fonts\DejaVu Sans Condensed-Bold.ttf",
    ]

    # Arial Unicode MS is another common fallback with broad glyph coverage.
    windows_arial_unicode = [
        r"C:\Windows\Fonts\arialuni.ttf",
        r"C:\Windows\Fonts\ArialUni.ttf",
        r"C:\Windows\Fonts\ARIALUNI.TTF",
        r"C:\Windows\Fonts\Arial Unicode MS.ttf",
    ]

    # Linux/Render common locations
    linux_dejavu_regular = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    linux_dejavu_bold = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ]
    linux_noto_regular = [
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans.ttf",
    ]
    linux_noto_bold = ["/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"]

    regular_path = _find_first_existing(
        windows_dejavu_regular
        + windows_arial_unicode
        + linux_noto_regular
        + linux_dejavu_regular
    )

    bold_path = None

    # Fallback: use fonts bundled with ReportLab (guaranteed to exist in venv).
    if not regular_path:
        try:
            import reportlab  # local import so it doesn't add overhead

            fonts_dir = Path(reportlab.__file__).parent / "fonts"
            vera_regular = fonts_dir / "Vera.ttf"
            vera_bold = fonts_dir / "VeraBd.ttf"

            if vera_regular.is_file():
                regular_path = vera_regular
                bold_path = vera_bold if vera_bold.is_file() else None
        except Exception:
            regular_path = None

    if not regular_path:
        logger.warning("Unicode TTF font not found; rupee symbol may not render.")
        return

    FONT_REGULAR = "UnicodeSans"
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(regular_path)))

    if bold_path is None:
        bold_path = _find_first_existing(
            windows_dejavu_bold
            + windows_arial_unicode
            + linux_noto_bold
            + linux_dejavu_bold
        )

    if bold_path:
        FONT_BOLD = "UnicodeSansBold"
        pdfmetrics.registerFont(TTFont(FONT_BOLD, str(bold_path)))
    else:
        FONT_BOLD = FONT_REGULAR


try:
    _register_unicode_font()
except Exception as exc:
    logger.warning("Failed to register unicode TTF font: %s", exc)

# Optional future branding (set COMPANY_LOGO_PATH in environment)
DEFAULT_COMPANY_NAME = os.getenv("COMPANY_NAME", "Nippon Toyota")
DEFAULT_LOGO_PATH = os.getenv("COMPANY_LOGO_PATH", "").strip()


@dataclass(frozen=True)
class PayrollPdfTheme:
    """Corporate payroll PDF color palette and spacing."""

    primary: colors.Color = colors.HexColor("#1565C0")
    primary_dark: colors.Color = colors.HexColor("#0D47A1")
    accent: colors.Color = colors.HexColor("#E3F2FD")
    light_gray: colors.Color = colors.HexColor("#F5F7FA")
    border: colors.Color = colors.HexColor("#CFD8DC")
    text_dark: colors.Color = colors.HexColor("#263238")
    text_muted: colors.Color = colors.HexColor("#607D8B")
    white: colors.Color = colors.white

    page_width: float = A4[0]
    page_height: float = A4[1]
    margin_left: float = 16 * mm
    margin_right: float = 16 * mm
    margin_top: float = 16 * mm
    margin_bottom: float = 22 * mm
    content_width: float = A4[0] - 32 * mm

    watermark_text: str = "CONFIDENTIAL"
    watermark_opacity: float = 0.06
    system_name: str = "Employee Salary Slip Automation System"


def format_currency_inr(amount: Any) -> str:
    """Format amount as ₹ XX,XXX.XX"""
    try:
        value = float(amount)
    except (TypeError, ValueError):
        value = 0.0
    return f"₹ {value:,.2f}"


def format_currency(amount: Any) -> str:
    """Helper required by spec: return ₹ formatted amount."""
    return format_currency_inr(amount)


def month_to_number(month_name: str) -> int:
    """Convert month name (e.g. June) to 1-12; default 1 if unknown."""
    cleaned = (month_name or "").strip().lower()
    if not cleaned:
        return 1
    for idx in range(1, 13):
        if calendar.month_name[idx].lower() == cleaned:
            return idx
        if calendar.month_abbr[idx].lower() == cleaned[:3]:
            return idx
    return 1


def build_slip_reference_id(employee_id: str, month: str, year: str | int) -> str:
    """Example: SS-2025-06-EMP002"""
    month_num = month_to_number(month)
    year_str = str(year).strip() or "0000"
    emp = (employee_id or "UNKNOWN").strip().replace(" ", "")
    return f"SS-{year_str}-{month_num:02d}-{emp}"


def _para(
    *,
    font: str = FONT_REGULAR,
    size: int = 10,
    color: colors.Color | None = None,
    align=TA_LEFT,
    leading: int | None = None,
    space_after: int = 0,
) -> ParagraphStyle:
    return ParagraphStyle(
        name=f"PdfStyle_{font}_{size}_{align}",
        fontName=font,
        fontSize=size,
        leading=leading or size + 3,
        textColor=color or colors.HexColor("#263238"),
        alignment=align,
        spaceAfter=space_after,
    )


def _table_style_base(theme: PayrollPdfTheme) -> list:
    return [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BOX", (0, 0), (-1, -1), 0.6, theme.border),
    ]


def _resolve_logo_path(employee: dict) -> Path | None:
    candidates = [
        employee.get("company_logo"),
        DEFAULT_LOGO_PATH,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(str(candidate))
        if path.is_file():
            return path
    return None


def build_header_table(
    theme: PayrollPdfTheme,
    *,
    company_name: str,
    month: str,
    year: str,
    logo_path: Path | None,
) -> Table:
    """Corporate header: optional logo, centered company name, pay period top-right."""
    pay_period = f"{month} {year}".strip()

    title_style = _para(font=FONT_BOLD, size=18, color=theme.white, align=TA_CENTER)
    subtitle_style = _para(
        font=FONT_REGULAR,
        size=11,
        color=theme.accent,
        align=TA_CENTER,
    )
    period_style = _para(
        font=FONT_REGULAR,
        size=10,
        color=theme.white,
        align=TA_RIGHT,
    )

    center_block = Table(
        [[Paragraph(company_name, title_style)], [Paragraph("Employee Salary Slip", subtitle_style)]],
        colWidths=[theme.content_width * 0.55],
    )
    center_block.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")]))

    if logo_path:
        logo = Image(str(logo_path), width=22 * mm, height=22 * mm)
        logo.hAlign = "LEFT"
        header_row = [[logo, center_block, Paragraph("", period_style)]]
        col_widths = [26 * mm, theme.content_width - 56 * mm, 30 * mm]
    else:
        header_row = [["", center_block, Paragraph("", period_style)]]
        col_widths = [2 * mm, theme.content_width - 34 * mm, 32 * mm]

    header_row[0][2] = Paragraph(f"<b>Pay Period</b><br/>{pay_period}", period_style)

    header = Table(header_row, colWidths=col_widths)
    header.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), theme.primary),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 12),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    return header


def build_reference_section(
    theme: PayrollPdfTheme,
    *,
    slip_id: str,
    generated_date: str,
    generated_time: str,
    pay_period: str,
) -> Table:
    """Salary slip reference metadata below header."""
    label_style = _para(font=FONT_BOLD, size=9, color=theme.text_muted)
    value_style = _para(font=FONT_REGULAR, size=10, color=theme.text_dark)

    rows = [
        [
            Paragraph("<b>Salary Slip ID</b>", label_style),
            Paragraph(slip_id, value_style),
            Paragraph("<b>Generated Date</b>", label_style),
            Paragraph(generated_date, value_style),
        ],
        [
            Paragraph("<b>Pay Period</b>", label_style),
            Paragraph(pay_period, value_style),
            Paragraph("<b>Generated Time</b>", label_style),
            Paragraph(generated_time, value_style),
        ],
    ]

    table = Table(rows, colWidths=[38 * mm, 49 * mm, 38 * mm, 49 * mm])
    styles = _table_style_base(theme)
    styles.extend(
        [
            ("BACKGROUND", (0, 0), (-1, -1), theme.light_gray),
            ("LINEBELOW", (0, 0), (-1, 0), 0.4, theme.border),
        ]
    )
    table.setStyle(TableStyle(styles))
    return table


def build_employee_card(
    theme: PayrollPdfTheme,
    *,
    employee_id: str,
    name: str,
    designation: str,
    email: str,
    department: str | None,
    pay_period: str,
) -> Table:
    """Bordered employee information card."""
    section_title_style = _para(
        font=FONT_BOLD,
        size=11,
        color=theme.primary_dark,
        space_after=4,
    )

    label = _para(font=FONT_BOLD, size=9, color=theme.text_muted)
    value = _para(font=FONT_REGULAR, size=10, color=theme.text_dark)

    left_rows = [
        [Paragraph("<b>Employee ID</b>", label), Paragraph(employee_id, value)],
        [Paragraph("<b>Employee Name</b>", label), Paragraph(name, value)],
        [Paragraph("<b>Designation</b>", label), Paragraph(designation, value)],
    ]
    right_rows = [
        [Paragraph("<b>Email</b>", label), Paragraph(email, value)],
        [Paragraph("<b>Pay Period</b>", label), Paragraph(pay_period, value)],
    ]
    if department:
        right_rows.append(
            [Paragraph("<b>Department</b>", label), Paragraph(department, value)]
        )

    left_table = Table(left_rows, colWidths=[38 * mm, 49 * mm])
    right_table = Table(right_rows, colWidths=[38 * mm, 49 * mm])

    for tbl in (left_table, right_table):
        tbl.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )

    body = Table([[left_table, right_table]], colWidths=[87 * mm, 87 * mm])
    body.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    wrapper = Table(
        [[Paragraph("Employee Information", section_title_style)], [body]],
        colWidths=[theme.content_width],
    )
    wrapper.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.8, theme.primary),
                ("BACKGROUND", (0, 0), (-1, 0), theme.accent),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]
        )
    )
    return wrapper


def build_summary_card(
    theme: PayrollPdfTheme,
    *,
    gross_salary: float,
    total_deductions: float,
    net_salary: float,
) -> Table:
    """At-a-glance salary summary for HR."""
    header_style = _para(
        font=FONT_BOLD,
        size=11,
        color=theme.primary_dark,
        align=TA_CENTER,
    )

    cell_label = _para(font=FONT_REGULAR, size=10, color=theme.text_muted, align=TA_CENTER)
    cell_value = _para(font=FONT_BOLD, size=12, color=theme.text_dark, align=TA_CENTER)
    net_label = _para(
        font=FONT_BOLD,
        size=10,
        color=theme.primary_dark,
        align=TA_CENTER,
    )
    net_value_style = _para(
        font=FONT_BOLD,
        size=16,
        color=theme.primary_dark,
        align=TA_CENTER,
    )

    summary = Table(
        [
            [Paragraph("Salary Summary", header_style)],
            [
                Paragraph("Gross Salary", cell_label),
                Paragraph("Total Deductions", cell_label),
                Paragraph("Net Salary", net_label),
            ],
            [
                Paragraph(format_currency(gross_salary), cell_value),
                Paragraph(format_currency(total_deductions), cell_value),
                Paragraph(format_currency(net_salary), net_value_style),
            ],
        ],
        colWidths=[theme.content_width / 3] * 3,
    )
    summary.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 0), (2, 0)),
                ("BACKGROUND", (0, 0), (-1, 0), theme.accent),
                ("BACKGROUND", (0, 1), (-1, 1), theme.light_gray),
                ("BACKGROUND", (2, 2), (2, 2), theme.accent),
                ("BOX", (0, 0), (-1, -1), 0.8, theme.border),
                ("INNERGRID", (0, 1), (-1, -1), 0.4, theme.border),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return summary


def build_breakdown_table(
    theme: PayrollPdfTheme,
    *,
    base_salary: float,
    hra: float,
    allowances: float,
    deductions: float,
    total_earnings: float,
    total_deductions: float,
) -> Table:
    """Detailed earnings and deductions breakdown."""
    section_style = _para(
        font=FONT_BOLD,
        size=11,
        color=theme.primary_dark,
        space_after=4,
    )

    data = [
        ["Description", "Earnings (₹)", "Description", "Deductions (₹)"],
        ["Base Salary", format_currency(base_salary), "Deductions", format_currency(deductions)],
        ["HRA", format_currency(hra), "", ""],
        ["Allowances", format_currency(allowances), "", ""],
        [
            "Total Earnings",
            format_currency(total_earnings),
            "Total Deductions",
            format_currency(total_deductions),
        ],
    ]

    table = Table(data, colWidths=[52 * mm, 35 * mm, 52 * mm, 35 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), theme.primary),
                ("TEXTCOLOR", (0, 0), (-1, 0), theme.white),
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTSIZE", (0, 0), (-1, 0), 10),
                ("FONTNAME", (0, 1), (-1, -1), FONT_REGULAR),
                ("FONTSIZE", (0, 1), (-1, -1), 10),
                ("FONTNAME", (0, -1), (-1, -1), FONT_BOLD),
                ("BACKGROUND", (0, 1), (-1, 1), theme.white),
                ("BACKGROUND", (0, 2), (-1, 2), theme.light_gray),
                ("BACKGROUND", (0, 3), (-1, 3), theme.white),
                ("BACKGROUND", (0, 4), (-1, 4), theme.accent),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("ALIGN", (3, 0), (3, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, theme.border),
                ("BOX", (0, 0), (-1, -1), 0.8, theme.primary),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )

    wrapper = Table([[Paragraph("Salary Breakdown", section_style)], [table]], colWidths=[theme.content_width])
    wrapper.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    return wrapper


def build_net_payable_banner(theme: PayrollPdfTheme, net_salary: float) -> Table:
    """Prominent net salary payable section."""
    label_style = _para(
        font=FONT_BOLD,
        size=12,
        color=theme.white,
        align=TA_CENTER,
    )
    amount_style = _para(
        font=FONT_BOLD,
        size=20,
        color=theme.white,
        align=TA_CENTER,
    )

    banner = Table(
        [
            [Paragraph("NET SALARY PAYABLE", label_style)],
            [Paragraph(format_currency(net_salary), amount_style)],
        ],
        colWidths=[theme.content_width],
    )
    banner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), theme.primary_dark),
                ("BOX", (0, 0), (-1, -1), 1.2, theme.primary),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
            ]
        )
    )
    return banner


def build_salary_slip_story(
    employee: dict,
    salary_record: dict,
    theme: PayrollPdfTheme | None = None,
) -> list:
    """Build platypus flowables for one salary slip (no calculations changed)."""
    theme = theme or PayrollPdfTheme()
    story: list = []

    employee_id = str(employee.get("employee_id", "")).strip()
    name = str(employee.get("name", "")).strip()
    email = str(employee.get("email", "")).strip()
    designation = str(employee.get("designation", "")).strip()
    department = (employee.get("department") or "").strip() or None

    base_salary = float(salary_record.get("base_salary", 0) or 0)
    hra = float(salary_record.get("hra", 0) or 0)
    allowances = float(salary_record.get("allowances", 0) or 0)
    deductions = float(salary_record.get("deductions", 0) or 0)
    net_salary = float(
        salary_record.get("net_salary", (base_salary + hra + allowances) - deductions) or 0
    )
    month = str(salary_record.get("month", "")).strip()
    year = str(salary_record.get("year", "")).strip()
    pay_period = f"{month} {year}".strip()

    total_earnings = base_salary + hra + allowances
    total_deductions = deductions

    now = utc_now()
    generated_date = now.strftime("%d-%m-%Y")
    generated_time = now.strftime("%H:%M")
    slip_id = build_slip_reference_id(employee_id, month, year)

    company_name = str(employee.get("company_name") or DEFAULT_COMPANY_NAME).strip()
    logo_path = _resolve_logo_path(employee)

    story.append(
        build_header_table(
            theme,
            company_name=company_name,
            month=month,
            year=year,
            logo_path=logo_path,
        )
    )
    story.append(Spacer(1, 4 * mm))
    story.append(
        build_reference_section(
            theme,
            slip_id=slip_id,
            generated_date=generated_date,
            generated_time=generated_time,
            pay_period=pay_period,
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(
        build_employee_card(
            theme,
            employee_id=employee_id,
            name=name,
            designation=designation,
            email=email,
            department=department,
            pay_period=pay_period,
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(
        build_summary_card(
            theme,
            gross_salary=total_earnings,
            total_deductions=total_deductions,
            net_salary=net_salary,
        )
    )
    story.append(Spacer(1, 5 * mm))
    story.append(
        build_breakdown_table(
            theme,
            base_salary=base_salary,
            hra=hra,
            allowances=allowances,
            deductions=deductions,
            total_earnings=total_earnings,
            total_deductions=total_deductions,
        )
    )
    story.append(Spacer(1, 6 * mm))
    story.append(build_net_payable_banner(theme, net_salary))
    story.append(Spacer(1, 4 * mm))

    return story


def draw_slip_page_frame(canvas, doc, theme: PayrollPdfTheme | None = None) -> None:
    """Draw watermark, footer, and page number on each page."""
    theme = theme or PayrollPdfTheme()
    canvas.saveState()

    # Subtle CONFIDENTIAL watermark
    canvas.setFont(FONT_BOLD, 52)
    canvas.setFillColor(theme.primary)
    try:
        canvas.setFillAlpha(theme.watermark_opacity)
    except AttributeError:
        pass

    canvas.translate(theme.page_width / 2, theme.page_height / 2)
    canvas.rotate(42)
    canvas.drawCentredString(0, 0, theme.watermark_text)
    canvas.rotate(-42)
    canvas.translate(-theme.page_width / 2, -theme.page_height / 2)

    try:
        canvas.setFillAlpha(1)
    except AttributeError:
        pass

    now = utc_now()
    footer_y = 12 * mm
    footer_style = dict(fontName=FONT_REGULAR, fontSize=8, fillColor=theme.text_muted)

    canvas.setFont(footer_style["fontName"], footer_style["fontSize"])
    canvas.setFillColor(footer_style["fillColor"])

    left_text = f"Generated on: {now.strftime('%d-%m-%Y %H:%M')}"
    center_text = f"Generated by: {theme.system_name}"
    right_text = f"Page {canvas.getPageNumber()}"

    canvas.drawString(theme.margin_left, footer_y, left_text)
    canvas.drawCentredString(theme.page_width / 2, footer_y, center_text)
    canvas.drawRightString(theme.page_width - theme.margin_right, footer_y, right_text)

    disclaimer_y = footer_y - 10
    canvas.setFont(FONT_REGULAR, 7)
    canvas.drawCentredString(
        theme.page_width / 2,
        disclaimer_y,
        "This is a system-generated salary slip and does not require a signature.",
    )

    canvas.restoreState()
