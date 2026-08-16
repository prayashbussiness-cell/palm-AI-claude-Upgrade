"""
pdf_generator.py

Generates a professional, well-typeset PDF report from the AI-generated
markdown text and the user's submitted details. Uses reportlab for full
control over typography, margins, headers, footers, and page numbers.

The markdown contains [[PROBLEM]]...[[/PROBLEM]] / [[SOLUTION]]...[[/SOLUTION]]
markers around key sentences; these are rendered in red / green respectively
so the paid PDF visually matches the free teaser preview.
"""

import os
import re
from datetime import datetime

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
)

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "reports")

PRIMARY_COLOR = colors.HexColor("#6C3EDB")
ACCENT_COLOR = colors.HexColor("#8B5CF6")
TEXT_COLOR = colors.HexColor("#2B2140")
MUTED_COLOR = colors.HexColor("#6B7280")
PROBLEM_COLOR = colors.HexColor("#B91C1C")
SOLUTION_COLOR = colors.HexColor("#15803D")

FOOTER_TEXT = "AI Vedic Astrology Report"

PROBLEM_RE = re.compile(r"\[\[PROBLEM\]\](.*?)\[\[/PROBLEM\]\]", re.DOTALL)
SOLUTION_RE = re.compile(r"\[\[SOLUTION\]\](.*?)\[\[/SOLUTION\]\]", re.DOTALL)


def _slugify(name: str) -> str:
    """Turn a user's name into a filesystem-safe slug for the PDF filename."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().lower()).strip("_")
    return slug or "user"


def _build_styles():
    styles = getSampleStyleSheet()

    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            fontName="Helvetica-Bold",
            fontSize=24,
            leading=28,
            textColor=PRIMARY_COLOR,
            alignment=TA_CENTER,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportSubtitle",
            fontName="Helvetica",
            fontSize=11,
            leading=14,
            textColor=MUTED_COLOR,
            alignment=TA_CENTER,
            spaceAfter=16,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            fontName="Helvetica-Bold",
            fontSize=14,
            leading=18,
            textColor=PRIMARY_COLOR,
            spaceBefore=16,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyTextCustom",
            fontName="Helvetica",
            fontSize=10.5,
            leading=16,
            textColor=TEXT_COLOR,
            alignment=TA_LEFT,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BulletCustom",
            fontName="Helvetica",
            fontSize=10.5,
            leading=15,
            textColor=TEXT_COLOR,
            leftIndent=14,
            bulletIndent=2,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="DetailLabel",
            fontName="Helvetica-Bold",
            fontSize=10,
            textColor=TEXT_COLOR,
        )
    )
    styles.add(
        ParagraphStyle(
            name="DetailValue",
            fontName="Helvetica",
            fontSize=10,
            textColor=TEXT_COLOR,
        )
    )
    styles.add(
        ParagraphStyle(
            name="RashiValue",
            fontName="Helvetica-Bold",
            fontSize=11,
            textColor=PROBLEM_COLOR,
        )
    )
    return styles


def _inline_markdown_to_html(text: str) -> str:
    # Colour [[PROBLEM]]/[[SOLUTION]] marked sentences first, then apply
    # **bold** / *italic* markdown on top.
    text = PROBLEM_RE.sub(
        r'<font color="#B91C1C"><b>\1</b></font>', text
    )
    text = SOLUTION_RE.sub(
        r'<font color="#15803D"><b>\1</b></font>', text
    )
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*(?!\*)", r"<i>\1</i>", text)
    return text


def _parse_markdown_to_flowables(markdown_text: str, styles) -> list:
    """
    Very small markdown -> reportlab flowable converter, tailored to the
    predictable structure of the Gemini-generated report ("## Heading",
    "- bullet", "**bold**", "[[PROBLEM]]/[[SOLUTION]]" markers, and plain
    paragraphs).
    """
    flowables = []
    lines = markdown_text.splitlines()

    buffer_paragraph = []

    def flush_paragraph():
        if buffer_paragraph:
            text = " ".join(buffer_paragraph).strip()
            if text:
                flowables.append(
                    Paragraph(_inline_markdown_to_html(text), styles["BodyTextCustom"])
                )
            buffer_paragraph.clear()

    for raw_line in lines:
        line = raw_line.strip()

        if not line:
            flush_paragraph()
            continue

        if line.startswith("## "):
            flush_paragraph()
            heading = line[3:].strip()
            flowables.append(Paragraph(heading, styles["SectionHeading"]))
            flowables.append(
                HRFlowable(
                    width="100%",
                    thickness=0.75,
                    color=ACCENT_COLOR,
                    spaceAfter=6,
                )
            )
            continue

        if line.startswith("# "):
            flush_paragraph()
            heading = line[2:].strip()
            flowables.append(Paragraph(heading, styles["SectionHeading"]))
            continue

        if line.startswith(("- ", "* ")):
            flush_paragraph()
            bullet_text = _inline_markdown_to_html(line[2:].strip())
            flowables.append(
                Paragraph(f"&bull;&nbsp;&nbsp;{bullet_text}", styles["BulletCustom"])
            )
            continue

        buffer_paragraph.append(line)

    flush_paragraph()
    return flowables


def _add_page_number(canvas, doc):
    """Draw the footer text and page number on every page."""
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED_COLOR)

    # Footer left: brand text
    canvas.drawString(20 * mm, 12 * mm, FOOTER_TEXT)

    # Footer right: page number
    page_num_text = f"Page {doc.page}"
    canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, page_num_text)

    # Thin top rule above footer
    canvas.setStrokeColor(colors.HexColor("#E5E7EB"))
    canvas.line(20 * mm, 16 * mm, A4[0] - 20 * mm, 16 * mm)
    canvas.restoreState()


def generate_pdf(
    name: str,
    email: str,
    dob: str,
    place: str,
    rashi: str,
    report_markdown: str,
) -> str:
    """
    Build a professional PDF report and save it to the reports/ directory.

    Args:
        name, email, dob, place: the submitted birth/contact details
            (no time of birth is collected any more).
        rashi: the Moon sign (Rashi) extracted from the report, shown
            prominently and highlighted instead of an exact birth time.
        report_markdown: the full Gemini-generated markdown, including
            [[PROBLEM]]/[[SOLUTION]] markers.

    Returns:
        The filename (not full path) of the generated PDF, e.g.
        "jane_doe_20260807153000.pdf"
    """
    os.makedirs(REPORTS_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"{_slugify(name)}_{timestamp}.pdf"
    filepath = os.path.join(REPORTS_DIR, filename)

    styles = _build_styles()

    doc = SimpleDocTemplate(
        filepath,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=22 * mm,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        title="AI Vedic Astrology Report",
        author="AI Vedic Astrology Report Generator",
    )

    story = []

    # Title block
    story.append(Paragraph("AI Vedic Astrology Report", styles["ReportTitle"]))
    generated_date = datetime.now().strftime("%B %d, %Y at %I:%M %p")
    story.append(
        Paragraph(f"Generated on {generated_date}", styles["ReportSubtitle"])
    )

    # User details table -- Date/Time of birth are no longer displayed here;
    # the Rashi (Moon Sign) derived from them is shown instead, highlighted.
    detail_rows = [
        [Paragraph("Full Name", styles["DetailLabel"]), Paragraph(name, styles["DetailValue"])],
        [Paragraph("Email", styles["DetailLabel"]), Paragraph(email, styles["DetailValue"])],
        [Paragraph("Place of Birth", styles["DetailLabel"]), Paragraph(place, styles["DetailValue"])],
        [Paragraph("Rashi (Moon Sign)", styles["DetailLabel"]), Paragraph(rashi, styles["RashiValue"])],
    ]
    detail_table = Table(detail_rows, colWidths=[40 * mm, 120 * mm])
    detail_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F5F3FF")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E5E7EB")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#FEF2F2")),
            ]
        )
    )
    story.append(detail_table)
    story.append(Spacer(1, 6 * mm))

    # Small legend explaining the red/green highlighting used throughout.
    legend = (
        '<font color="#B91C1C"><b>&#9632;</b></font> Problem areas identified in your chart &nbsp;&nbsp; '
        '<font color="#15803D"><b>&#9632;</b></font> Recommended solutions &amp; remedies'
    )
    story.append(Paragraph(legend, styles["ReportSubtitle"]))
    story.append(Spacer(1, 4 * mm))

    # Report body (converted from markdown, with PROBLEM/SOLUTION colouring)
    story.extend(_parse_markdown_to_flowables(report_markdown, styles))

    doc.build(story, onFirstPage=_add_page_number, onLaterPages=_add_page_number)

    return filename
