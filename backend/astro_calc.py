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
      moon_rashi, sun_rashi, nakshatra, nakshatra_pada, nakshatra_lord,
      moon_sign_uncertain, nakshatra_uncertain
    """
    year, month, day = (int(p) for p in dob_iso.split("-")[:3])

    jd_noon = swe.julday(year, month, day, 12.0)
    jd_start = swe.julday(year, month, day, 0.0)
    jd_end = swe.julday(year, month, day, 23.999)

    moon_lon_noon = _sidereal_longitude(jd_noon, swe.MOON)
    sun_lon_noon = _sidereal_longitude(jd_noon, swe.SUN)

    moon_rashi = _rashi_for_longitude(moon_lon_noon)
    sun_rashi = _rashi_for_longitude(sun_lon_noon)
    nakshatra, pada, lord = _nakshatra_for_longitude(moon_lon_noon)

    moon_rashi_start = _rashi_for_longitude(_sidereal_longitude(jd_start, swe.MOON))
    moon_rashi_end = _rashi_for_longitude(_sidereal_longitude(jd_end, swe.MOON))
    moon_sign_uncertain = not (moon_rashi_start == moon_rashi == moon_rashi_end)

    nak_start, _, _ = _nakshatra_for_longitude(_sidereal_longitude(jd_start, swe.MOON))
    nak_end, _, _ = _nakshatra_for_longitude(_sidereal_longitude(jd_end, swe.MOON))
    nakshatra_uncertain = not (nak_start == nakshatra == nak_end)

    return {
        "moon_rashi": moon_rashi,
        "sun_rashi": sun_rashi,
        "nakshatra": nakshatra,
        "nakshatra_pada": pada,
        "nakshatra_lord": lord,
        "moon_sign_uncertain": moon_sign_uncertain,
        "nakshatra_uncertain": nakshatra_uncertain,
    }
