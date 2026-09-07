"""
astro_calc.py

Computes REAL sidereal (Vedic / Lahiri ayanamsa) planetary positions for
a date of birth, using the Swiss Ephemeris library (pyswisseph) in
Moshier mode -- a semi-analytic model that ships inside the package
itself, needs no external ephemeris data files, and is accurate to a
few arcseconds, far more than enough to place the Moon in the correct
sign (Rashi) and lunar mansion (Nakshatra).

WHY THIS EXISTS
----------------
Previously, the AI model was asked to "derive" the Moon sign (Rashi)
using only its own reasoning over a text date/place. Language models
cannot do real ephemeris math, so this was effectively a guess -- which
is why the Rashi shown in reports was frequently wrong. This module
computes the astronomically correct value, and the app now (a) feeds it
to the model as a fact it must use verbatim, and (b) force-corrects the
Rashi line in the model's output afterward as a safety net, so the
result is always right regardless of what the model does with it.

KNOWN LIMITATION
-----------------
The app collects a date of birth only -- no exact time of birth, and no
geocoded birthplace/timezone. This module therefore evaluates the chart
at local noon UTC on the given date as a fixed, documented reference
point. On the small number of dates per year where the Moon crosses a
sign or nakshatra boundary, someone born very early or very late in the
day could technically fall on the other side of that boundary --
`moon_sign_uncertain` / `nakshatra_uncertain` flag exactly this case so
the report can word itself appropriately instead of asserting false
certainty. Fully resolving that would require collecting an exact birth
time and geocoding the birthplace to a timezone, which is a larger
feature than this fix.
"""

import swisseph as swe

swe.set_sid_mode(swe.SIDM_LAHIRI)

RASHI_NAMES = [
    "Mesha (Aries)",
    "Vrishabha (Taurus)",
    "Mithuna (Gemini)",
    "Karka (Cancer)",
    "Simha (Leo)",
    "Kanya (Virgo)",
    "Tula (Libra)",
    "Vrishchika (Scorpio)",
    "Dhanu (Sagittarius)",
    "Makara (Capricorn)",
    "Kumbha (Aquarius)",
    "Meena (Pisces)",
]

NAKSHATRA_NAMES = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra",
    "Punarvasu", "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni",
    "Hasta", "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha",
    "Mula", "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati",
]

# 27 nakshatras cycle through these 9 lords repeatedly (used by the
# Vimshottari Dasha system too).
NAKSHATRA_LORDS_CYCLE = [
    "Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury",
]

_NAKSHATRA_SPAN = 360.0 / 27.0  # 13.333...deg


def _sidereal_longitude(jd_ut: float, planet: int) -> float:
    (lon, *_rest), _flags = swe.calc_ut(jd_ut, planet, swe.FLG_SIDEREAL | swe.FLG_MOSEPH)
    return lon % 360.0


def _rashi_for_longitude(lon: float) -> str:
    return RASHI_NAMES[int(lon // 30) % 12]


def _nakshatra_for_longitude(lon: float):
    idx = int(lon // _NAKSHATRA_SPAN) % 27
    pada = int((lon % _NAKSHATRA_SPAN) // (_NAKSHATRA_SPAN / 4)) + 1
    lord = NAKSHATRA_LORDS_CYCLE[idx % 9]
    return NAKSHATRA_NAMES[idx], pada, lord


def compute_birth_facts(dob_iso: str) -> dict:
    """
    dob_iso: "YYYY-MM-DD" (the format the frontend's date picker sends).

    Returns real, computed facts:
      moon_rashi, moon_rashi_index, sun_rashi, sun_rashi_index, nakshatra,
      nakshatra_index, nakshatra_pada, nakshatra_lord,
      moon_sign_uncertain, nakshatra_uncertain
    """
    year, month, day = (int(p) for p in dob_iso.split("-")[:3])

    jd_noon = swe.julday(year, month, day, 12.0)
    jd_start = swe.julday(year, month, day, 0.0)
    jd_end = swe.julday(year, month, day, 23.999)

    moon_lon_noon = _sidereal_longitude(jd_noon, swe.MOON)
    sun_lon_noon = _sidereal_longitude(jd_noon, swe.SUN)

    moon_rashi_index = int(moon_lon_noon // 30) % 12
    sun_rashi_index = int(sun_lon_noon // 30) % 12
    moon_rashi = RASHI_NAMES[moon_rashi_index]
    sun_rashi = RASHI_NAMES[sun_rashi_index]
    nakshatra_index = int(moon_lon_noon // _NAKSHATRA_SPAN) % 27
    nakshatra, pada, lord = _nakshatra_for_longitude(moon_lon_noon)

    moon_rashi_start = _rashi_for_longitude(_sidereal_longitude(jd_start, swe.MOON))
    moon_rashi_end = _rashi_for_longitude(_sidereal_longitude(jd_end, swe.MOON))
    moon_sign_uncertain = not (moon_rashi_start == moon_rashi == moon_rashi_end)

    nak_start, _, _ = _nakshatra_for_longitude(_sidereal_longitude(jd_start, swe.MOON))
    nak_end, _, _ = _nakshatra_for_longitude(_sidereal_longitude(jd_end, swe.MOON))
    nakshatra_uncertain = not (nak_start == nakshatra == nak_end)

    return {
        "moon_rashi": moon_rashi,
        "moon_rashi_index": moon_rashi_index,
        "sun_rashi": sun_rashi,
        "sun_rashi_index": sun_rashi_index,
        "nakshatra": nakshatra,
        "nakshatra_index": nakshatra_index,
        "nakshatra_pada": pada,
        "nakshatra_lord": lord,
        "moon_sign_uncertain": moon_sign_uncertain,
        "nakshatra_uncertain": nakshatra_uncertain,
    }


# ---------------------------------------------------------------------------
# Astrological Score
# ---------------------------------------------------------------------------
# A transparent, deterministic "chart strength" score (0-100) plus Career /
# Relationship / Power-to-Face-Situations sub-scores, built from the real
# computed Moon sign, Sun sign, and Nakshatra lord above -- NOT an AI
# guess, so the same birth date always produces the same score (asking the
# model to invent a number would give a different score every time the
# same person's report is regenerated). This is a heuristic entertainment
# feature (the report's Disclaimer section already frames the whole
# reading as being for self-reflection/entertainment, not certified
# astrology) built from traditional, real correspondences -- each sign's
# element (Fire/Earth/Air/Water) and modality (Cardinal/Fixed/Mutable),
# and each nakshatra lord's classical significations (karakas) -- combined
# with a simple, fixed, documented formula. It is not a claim of any
# single authoritative Vedic scoring method; no such universal formula
# exists.

ELEMENTS = ["Fire", "Earth", "Air", "Water"]  # Aries=Fire, Taurus=Earth, ... repeating
MODALITIES = ["Cardinal", "Fixed", "Mutable"]  # Aries=Cardinal, Taurus=Fixed, ... repeating

# planet -> (career, relationship, resilience/"power to face situations")
_KARAKA_WEIGHTS = {
    "Sun": (18, 2, 10),
    "Moon": (5, 12, 5),
    "Mars": (8, 2, 18),
    "Mercury": (15, 8, 5),
    "Jupiter": (12, 12, 8),
    "Venus": (5, 18, 3),
    "Saturn": (10, 3, 18),
    "Rahu": (14, 4, 10),
    "Ketu": (2, 4, 16),
}

_ELEMENT_WEIGHTS = {
    "Fire": (8, 2, 10),
    "Earth": (10, 5, 6),
    "Air": (5, 10, 4),
    "Water": (2, 10, 6),
}

_MODALITY_WEIGHTS = {
    "Cardinal": (8, 3, 6),
    "Fixed": (4, 4, 10),
    "Mutable": (3, 6, 3),
}

_BASE_SCORE = 40


def _clip_score(value: float) -> int:
    return max(20, min(96, round(value)))


def compute_score(birth_facts: dict) -> dict:
    """
    Returns {"overall", "career", "relationship", "resilience"}, each an
    int 0-100. See the module-level comment above for what this is (and
    isn't) based on.
    """
    moon_elem = ELEMENTS[birth_facts["moon_rashi_index"] % 4]
    moon_mod = MODALITIES[birth_facts["moon_rashi_index"] % 3]
    sun_elem = ELEMENTS[birth_facts["sun_rashi_index"] % 4]
    lord_weights = _KARAKA_WEIGHTS.get(birth_facts["nakshatra_lord"], (0, 0, 0))

    career = relationship = resilience = float(_BASE_SCORE)
    for c, r, s in (lord_weights, _ELEMENT_WEIGHTS[moon_elem], _MODALITY_WEIGHTS[moon_mod]):
        career += c
        relationship += r
        resilience += s

    # Sun sign is a smaller, secondary influence.
    sc, sr, ss = _ELEMENT_WEIGHTS[sun_elem]
    career += sc / 2
    relationship += sr / 2
    resilience += ss / 2

    career = _clip_score(career)
    relationship = _clip_score(relationship)
    resilience = _clip_score(resilience)
    overall = _clip_score((career + relationship + resilience) / 3)

    return {
        "overall": overall,
        "career": career,
        "relationship": relationship,
        "resilience": resilience,
    }
