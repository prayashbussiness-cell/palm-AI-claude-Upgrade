"""
chart_report.py

Turns the computed chart (astro_calc.compute_chart) into:

1. Two Markdown report sections, spliced into the report by main.py right
   after "Astrological Score":

       ## Planetary Positions & House Effects
       ## Current Dasha Period

   They use three inline colour markers, which report_utils.py (web
   preview) and pdf_generator.py (PDF) both understand:

       [[GOOD]]...[[/GOOD]]     green  -> favourable / advantage
       [[BAD]]...[[/BAD]]       red    -> challenging / disadvantage
       [[MIXED]]...[[/MIXED]]   amber  -> mixed / conditional

   Because the sections are plain Markdown inside the report text, they
   automatically flow through everything that already exists: the free
   preview, the PDF, the copy saved in Supabase, and the PDF regenerated
   from Supabase after a redeploy.

2. A short "ground truth" facts block for the AI prompt, so the written
   narrative describes the SAME placements and Dasha the sections show,
   instead of inventing its own.
"""

from typing import List

PLANETS_HEADING = "Planetary Positions & House Effects"
DASHA_HEADING = "Current Dasha Period"

_MARKER = {"good": "GOOD", "bad": "BAD", "mixed": "MIXED"}


def _wrap(verdict: str, text: str) -> str:
    tag = _MARKER.get(verdict, "MIXED")
    return f"[[{tag}]]{text}[[/{tag}]]"


def _join(items: List[str]) -> str:
    return ", ".join(items)


def _trait_lines(advantages, disadvantages, mixed) -> List[str]:
    lines = []
    if advantages:
        lines.append(f"- {_wrap('good', 'Advantages: ' + _join(advantages))}")
    if disadvantages:
        lines.append(f"- {_wrap('bad', 'Disadvantages: ' + _join(disadvantages))}")
    if mixed:
        lines.append(f"- {_wrap('mixed', 'Mixed / conditional: ' + _join(mixed))}")
    return lines


def _position_text(planet: dict) -> str:
    text = f"{planet['sign']} {planet['degree_text']}"
    if planet.get("retrograde"):
        text += " (Retrograde)"
    return text


def chart_near_boundary(chart: dict, minutes: int = 10) -> bool:
    """True if the birth time is within `minutes` of an Ascendant sign change."""
    w = chart.get("lagna_window")
    if not w:
        return False
    before = None if w.get("before_capped") else w.get("minutes_before")
    after = None if w.get("after_capped") else w.get("minutes_after")
    return any(v is not None and v <= minutes for v in (before, after))


def build_planets_section(chart: dict) -> str:
    """'## Planetary Positions & House Effects' markdown."""
    lines = [f"## {PLANETS_HEADING}"]

    if chart.get("reference_type") == "lagna":
        lagna_text = f"{chart['lagna']} {chart['lagna_degree_text']}"
        basis = "your birth time and place"
        if chart.get("birth_time_text") and chart.get("place_display"):
            basis = f"your birth time ({chart['birth_time_text']}) and place ({chart['place_display']})"
        intro = (
            f"Your Ascendant (Lagna) is {lagna_text}, calculated from {basis}, "
            "and houses are counted from it. "
        )
        window = chart.get("lagna_window") or {}
        if window.get("start_text") and window.get("end_text"):
            intro += (
                f"Your Ascendant stays {chart['lagna']} from {window['start_text']} to "
                f"{window['end_text']} (local time); a birth time outside that window would "
                "change every house number. "
            )
        if chart_near_boundary(chart):
            intro += (
                "Your birth time is close to an Ascendant sign change, so please double-check "
                "it: a few minutes' difference would move every planet to a different house. "
            )
        if chart.get("place_ambiguous"):
            intro += (
                "Several places share your birth place name, so please make sure "
                f"{chart['place_display']} is the right one. "
            )
    else:
        intro = "Houses are counted from your Moon sign (Chandra Lagna). "
        if chart.get("time_ignored"):
            intro += (
                "Your birth place could not be located, so the Ascendant could not be "
                "calculated from your birth time. "
            )
    intro += (
        "Green marks a favourable placement, red a challenging one and amber a mixed one. "
        + chart["source_caveat"]
    )
    if chart.get("moon_sign_uncertain"):
        intro += (
            " Your Moon changes sign during your birth date, so house positions "
            "follow the sign it occupies for most of the day."
        )
    lines.append(intro)
    lines.append("")

    # At-a-glance table (degrees / retrograde are in each planet's block below,
    # keeping this table narrow enough for a phone screen)
    lines.append("| Planet | Sign | House | Result |")
    lines.append("|---|---|---|---|")
    for p in chart["planets"]:
        lines.append(
            f"| {p['name']} | {p['sign']} | "
            f"{_wrap(p['verdict'], str(p['house']))} | "
            f"{_wrap(p['verdict'], p['verdict_label'])} |"
        )
    lines.append("")

    # One block per planet: house meaning + advantages / disadvantages
    for p in chart["planets"]:
        lines.append(
            f"### {p['name']} in House {p['house']} ({p['house_title']}) "
            f"{_wrap(p['verdict'], p['verdict_label'])}"
        )
        lines.append(f"- **Position:** {_position_text(p)}")
        lines.append(f"- **House {p['house']} governs:** {p['house_governs']}")
        lines.extend(_trait_lines(p["advantages"], p["disadvantages"], p["mixed"]))
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def _dasha_block(label: str, period: dict) -> List[str]:
    lord = period["lord"]
    lines = [
        f"### {label}: {lord} {_wrap(period['verdict'], period['verdict_label'])}",
        f"- **Period:** {period['start_text']} to {period['end_text']}",
        f"- **{lord} sits in House {period['lord_house']}** of your chart, "
        f"so this period is coloured by that placement.",
    ]
    lines.extend(_trait_lines(period["advantages"], period["disadvantages"], period["mixed"]))
    return lines


def build_dasha_section(chart: dict) -> str:
    """'## Current Dasha Period' markdown."""
    d = chart["dasha"]
    lines = [f"## {DASHA_HEADING}"]

    intro = (
        f"Your running Vimshottari Dasha as of {d['as_of_text']}, calculated from "
        "the Moon's position at birth. "
        + ("" if chart.get("birth_time_used") else "Dates are approximate. ")
        + "A period is coloured "
        "by the house its planet occupies in your chart: green is favourable, red "
        "challenging, amber mixed."
    )
    if d.get("dasha_uncertain"):
        intro += (
            " The Moon moves quickly through the day, so the running Mahadasha "
            "could shift slightly on either side of the dates shown."
        )
    lines.append(intro)
    lines.append("")

    for label, key in (
        ("Mahadasha (major period)", "mahadasha"),
        ("Antardasha (sub-period)", "antardasha"),
        ("Pratyantardasha (sub-sub-period)", "pratyantardasha"),
    ):
        lines.extend(_dasha_block(label, d[key]))
        lines.append("")

    lines.append("### Mahadasha Timeline")
    for t in d["timeline"]:
        running = " (running now)" if t["is_current"] else ""
        lines.append(
            f"- **{t['lord']}**{running}: {t['start_text']} to {t['end_text']} \u2014 "
            f"{_wrap(t['verdict'], 'House ' + str(t['lord_house']) + ', ' + t['verdict_label'])}"
        )
    lines.append("")

    return "\n".join(lines).strip() + "\n"


def build_prompt_facts(chart: dict) -> str:
    """
    Plain-text ground-truth block for the AI prompt (no colour markers).
    Lists each planet's sign/house/verdict and the running Dasha periods so
    the narrative stays consistent with the deterministic sections above.
    """
    if chart.get("reference_type") == "lagna":
        lines = [
            f"- **Ascendant (Lagna):** {chart['lagna']} (calculated from the exact birth time and place)",
            "- **Planetary placements (houses counted from the Ascendant):**",
        ]
    else:
        lines = ["- **Planetary placements (houses counted from the Moon sign, Chandra Lagna):**"]
    for p in chart["planets"]:
        traits = p["advantages"] + p["disadvantages"] + p["mixed"]
        detail = f" ({', '.join(traits)})" if traits else ""
        lines.append(
            f"  - {p['name']}: {p['sign']}, House {p['house']} \u2014 "
            f"{p['verdict_label'].lower()}{detail}"
        )

    d = chart["dasha"]
    lines.append(f"- **Running Vimshottari Dasha (as of {d['as_of_text']}):**")
    for label, key in (
        ("Mahadasha", "mahadasha"),
        ("Antardasha", "antardasha"),
        ("Pratyantardasha", "pratyantardasha"),
    ):
        p = d[key]
        lines.append(
            f"  - {label}: {p['lord']} ({p['start_text']} to {p['end_text']}); "
            f"{p['lord']} is in House {p['lord_house']} \u2014 {p['verdict_label'].lower()}"
        )
    return "\n".join(lines) + "\n"
