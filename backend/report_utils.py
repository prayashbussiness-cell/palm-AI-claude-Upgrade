"""
report_utils.py

Turns the raw Gemini markdown (which contains "## Section" headings,
"- bullet" lines, "**bold**" text, and [[PROBLEM]]...[[/PROBLEM]] /
[[SOLUTION]]...[[/SOLUTION]] markers) into:

- a Rashi (Moon sign) string, extracted for the header/highlight,
- a short list of "issue chips" (which problem-heavy sections fired),
- a free preview ("teaser") capped at roughly 30% of the report,
  rendered as safe HTML with problems in red and solutions in green,
- a fully marker-stripped plain-text version (used as a fallback and
  for the PDF's plain paragraphs where markers aren't relevant).

Only sections 8-12 and 14 of the prompt (Life Challenges, Manglik &
Relationship, Career, Financial, Health, Remedies) are expected to
contain markers, but the parser handles them appearing anywhere.
"""

import html
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

PROBLEM_RE = re.compile(r"\[\[PROBLEM\]\](.*?)\[\[/PROBLEM\]\]", re.DOTALL)
SOLUTION_RE = re.compile(r"\[\[SOLUTION\]\](.*?)\[\[/SOLUTION\]\]", re.DOTALL)
ANY_MARKER_RE = re.compile(r"\[\[/?(?:PROBLEM|SOLUTION)\]\]")

RASHI_RE = re.compile(
    r"\*\*Rashi\s*\(Moon Sign\):?\*\*\s*:?\s*([A-Za-z][A-Za-z \-']*)",
    re.IGNORECASE,
)

# Sections whose presence of a [[PROBLEM]] marker should surface as a
# short "issue detected" chip on the teaser card.
ISSUE_SECTION_LABELS = {
    "life challenges & dasha impact": "Life Challenges",
    "manglik dosha & relationship analysis": "Relationship Challenges",
    "career & job analysis": "Career Challenges",
    "financial outlook": "Financial Challenges",
    "health & mental well-being": "Health Challenges",
}


@dataclass
class Block:
    kind: str  # "heading" | "bullet" | "paragraph"
    text: str  # raw markdown text of this block (may contain markers)
    section: Optional[str] = None  # lowercase heading this block falls under
    plain_len: int = field(default=0)


def _plain_length(text: str) -> int:
    """Length of the block once markers/markdown syntax are stripped, for
    proportionally sizing the 30% teaser cut."""
    stripped = ANY_MARKER_RE.sub("", text)
    stripped = re.sub(r"\*\*(.+?)\*\*", r"\1", stripped)
    return len(stripped)


def _split_blocks(markdown_text: str) -> List[Block]:
    blocks: List[Block] = []
    current_section: Optional[str] = None
    buffer: List[str] = []

    def flush():
        if buffer:
            text = " ".join(buffer).strip()
            if text:
                blocks.append(Block("paragraph", text, current_section, _plain_length(text)))
            buffer.clear()

    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith("## "):
            flush()
            current_section = line[3:].strip().lower()
            blocks.append(Block("heading", line[3:].strip(), current_section, 0))
            continue
        if line.startswith(("- ", "* ")):
            flush()
            text = line[2:].strip()
            blocks.append(Block("bullet", text, current_section, _plain_length(text)))
            continue
        buffer.append(line)

    flush()
    return blocks


def strip_markers(text: str) -> str:
    """Remove [[PROBLEM]]/[[SOLUTION]] wrapper tags, keeping inner text."""
    text = PROBLEM_RE.sub(lambda m: m.group(1), text)
    text = SOLUTION_RE.sub(lambda m: m.group(1), text)
    return text


def _inline_html(text: str) -> str:
    """Escape HTML, then re-apply **bold**, and colour PROBLEM/SOLUTION spans."""
    escaped = html.escape(text)
    # Markers survive html.escape() unchanged (they use [[ ]], not < >),
    # so apply colouring first, then bold, on the escaped text.
    escaped = PROBLEM_RE.sub(
        r'<span class="mark mark-problem">\1</span>', escaped
    )
    escaped = SOLUTION_RE.sub(
        r'<span class="mark mark-solution">\1</span>', escaped
    )
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def blocks_to_html(blocks: List[Block]) -> str:
    """Render a list of Blocks to HTML, wrapping consecutive bullets in <ul>."""
    html_parts: List[str] = []
    in_list = False

    for block in blocks:
        if block.kind == "bullet":
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{_inline_html(block.text)}</li>")
            continue

        if in_list:
            html_parts.append("</ul>")
            in_list = False

        if block.kind == "heading":
            html_parts.append(f"<h3>{html.escape(block.text)}</h3>")
        else:
            html_parts.append(f"<p>{_inline_html(block.text)}</p>")

    if in_list:
        html_parts.append("</ul>")

    return "\n".join(html_parts)


def extract_rashi(markdown_text: str) -> str:
    match = RASHI_RE.search(markdown_text)
    if match:
        return match.group(1).strip().rstrip(".")
    return "Not determined"


RASHI_LINE_RE = re.compile(
    r"(\*\*Rashi\s*\(Moon Sign\):?\*\*\s*:?\s*)([^\n]*)",
    re.IGNORECASE,
)


def force_rashi(markdown_text: str, correct_rashi: str) -> str:
    """
    Overwrites whatever Rashi value the model wrote in the Basic
    Astrological Details bullet with the astronomically-computed correct
    one (see astro_calc.compute_birth_facts). This is a safety net: even
    if the model doesn't follow the "use this exact value" instruction,
    the Rashi shown to the user (and highlighted/used in the PDF) is
    always the real one, not a guess.
    """
    if not correct_rashi:
        return markdown_text
    if RASHI_LINE_RE.search(markdown_text):
        return RASHI_LINE_RE.sub(lambda m: m.group(1) + correct_rashi, markdown_text, count=1)
    return markdown_text


def detect_issue_chips(markdown_text: str) -> List[str]:
    """Which problem-heavy sections actually contain a [[PROBLEM]] marker."""
    blocks = _split_blocks(markdown_text)
    sections_with_problems = set()
    for block in blocks:
        if block.section and PROBLEM_RE.search(block.text):
            sections_with_problems.add(block.section)

    chips = []
    for section_key, label in ISSUE_SECTION_LABELS.items():
        if section_key in sections_with_problems:
            chips.append(label)
    return chips


SECTION_HEADING_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")


def insert_section_after(markdown_text: str, after_heading: str, section_markdown: str) -> str:
    """
    Insert `section_markdown` (a full "## Heading\\n..." block) right
    after the section named `after_heading` ends -- i.e. immediately
    before whatever "## " heading comes next -- regardless of exactly
    how that following section is titled. Used to splice the
    backend-computed Astrological Score section into the model's
    markdown at a fixed position, rather than trusting the model to
    generate (and correctly compute) it itself.

    Falls back to inserting right after the first heading if
    `after_heading` isn't found, so the section is never silently lost.
    """
    matches = list(SECTION_HEADING_RE.finditer(markdown_text))
    target_idx = None
    for i, m in enumerate(matches):
        if m.group(1).strip().lower() == after_heading.strip().lower():
            target_idx = i
            break

    if target_idx is None:
        if not matches:
            return markdown_text.strip() + "\n\n" + section_markdown.strip() + "\n"
        insert_pos = matches[0].end()
    elif target_idx + 1 < len(matches):
        insert_pos = matches[target_idx + 1].start()
    else:
        insert_pos = len(markdown_text)

    return (
        markdown_text[:insert_pos].rstrip()
        + "\n\n"
        + section_markdown.strip()
        + "\n\n"
        + markdown_text[insert_pos:].lstrip()
    )


# Sections always shown in full in the free teaser (no markers expected).
ALWAYS_FULL_SECTIONS = {"executive summary", "basic astrological details", "astrological score"}

TEASER_RATIO = 0.30


def build_teaser_html(markdown_text: str) -> Tuple[str, bool]:
    """
    Returns (teaser_html, is_truncated).

    Always includes the Executive Summary + Basic Astrological Details in
    full, then includes further sections/blocks in order until roughly
    30% of the *remaining* report's length has been shown, cutting only
    at block boundaries so a [[PROBLEM]]/[[SOLUTION]] sentence is never
    shown half-cut. Everything after the cut is simply not sent to the
    client (never hidden-but-present in the HTML), so it can't be
    revealed by inspecting the page source.
    """
    blocks = _split_blocks(markdown_text)

    always_blocks = [b for b in blocks if b.section in ALWAYS_FULL_SECTIONS]
    rest_blocks = [b for b in blocks if b.section not in ALWAYS_FULL_SECTIONS]

    rest_total = sum(b.plain_len for b in rest_blocks) or 1
    budget = rest_total * TEASER_RATIO

    included: List[Block] = []
    running = 0
    truncated = False
    for block in rest_blocks:
        included.append(block)
        running += block.plain_len
        if running >= budget:
            truncated = True
            break

    if len(included) < len(rest_blocks):
        truncated = True

    # Trim a trailing lone heading with nothing under it (looks broken).
    while included and included[-1].kind == "heading":
        included.pop()
        truncated = True

    teaser_blocks = always_blocks + included
    return blocks_to_html(teaser_blocks), truncated


def clean_plain_text(markdown_text: str) -> str:
    """Full report with [[PROBLEM]]/[[SOLUTION]] markers removed, for any
    plain-text fallback display."""
    return strip_markers(markdown_text)


def normalize_phone(phone: str) -> str:
    """
    Normalize a phone number for matching purposes: strip everything but
    digits, then keep the last 10 digits so "9876543210", "+91 9876543210",
    and "091-9876543210" all normalize to the same value.
    """
    digits = re.sub(r"\D", "", phone or "")
    return digits[-10:] if len(digits) >= 10 else digits


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()
