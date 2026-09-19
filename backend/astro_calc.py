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

from datetime import datetime, timedelta, timezone

import swisseph as swe

try:
    # Run from inside backend/ (uvicorn main:app)
    import house_effects
except ImportError:
    # Run from the repo root (uvicorn backend.main:app)
    from backend import house_effects

swe.set_sid_mode(swe.SIDM_LAHIRI)


def _use_lahiri() -> None:
    """
    Swiss Ephemeris keeps its sidereal-mode setting PER THREAD. The
    module-level call above only reaches the thread that imported this
    file; in any other thread (a sync FastAPI endpoint, a thread pool, the
    test client...) the library silently falls back to its default
    ayanamsa (Fagan-Bradley, ~0.9 deg away from Lahiri), which would shift
    every planet, Rashi, Nakshatra and Dasha date. So every calculation
    below re-asserts Lahiri first -- it is a trivial, cheap call.
    """
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
    _use_lahiri()
    (lon, *_rest), _flags = swe.calc_ut(jd_ut, planet, swe.FLG_SIDEREAL | swe.FLG_MOSEPH)
    return lon % 360.0


def _jd_from_utc(dt: datetime) -> float:
    """Julian day (UT) for a naive UTC datetime."""
    return swe.julday(dt.year, dt.month, dt.day, dt.hour + dt.minute / 60.0 + dt.second / 3600.0)


def _rashi_for_longitude(lon: float) -> str:
    return RASHI_NAMES[int(lon // 30) % 12]


def _nakshatra_for_longitude(lon: float):
    idx = int(lon // _NAKSHATRA_SPAN) % 27
    pada = int((lon % _NAKSHATRA_SPAN) // (_NAKSHATRA_SPAN / 4)) + 1
    lord = NAKSHATRA_LORDS_CYCLE[idx % 9]
    return NAKSHATRA_NAMES[idx], pada, lord


def compute_birth_facts(dob_iso: str, birth_dt_utc: datetime = None) -> dict:
    """
    dob_iso: "YYYY-MM-DD" (the format the frontend's date picker sends).
    birth_dt_utc: optional exact birth moment as a naive UTC datetime. When
        given (the person supplied a time of birth and the place could be
        located), the Moon/Sun are evaluated at that exact moment instead of
        the noon-UTC reference, and the "uncertain" flags are False.

    Returns real, computed facts:
      moon_rashi, moon_rashi_index, sun_rashi, sun_rashi_index, nakshatra,
      nakshatra_index, nakshatra_pada, nakshatra_lord,
      moon_sign_uncertain, nakshatra_uncertain
    """
    if birth_dt_utc is not None:
        jd = _jd_from_utc(birth_dt_utc)
        moon_lon = _sidereal_longitude(jd, swe.MOON)
        sun_lon = _sidereal_longitude(jd, swe.SUN)
        nak, pada, lord = _nakshatra_for_longitude(moon_lon)
        return {
            "moon_rashi": _rashi_for_longitude(moon_lon),
            "moon_rashi_index": int(moon_lon // 30) % 12,
            "sun_rashi": _rashi_for_longitude(sun_lon),
            "sun_rashi_index": int(sun_lon // 30) % 12,
            "nakshatra": nak,
            "nakshatra_index": int(moon_lon // _NAKSHATRA_SPAN) % 27,
            "nakshatra_pada": pada,
            "nakshatra_lord": lord,
            "moon_sign_uncertain": False,
            "nakshatra_uncertain": False,
        }

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



# ---------------------------------------------------------------------------
# Planetary positions, houses & Vimshottari Dasha
# ---------------------------------------------------------------------------
# WHICH "LAGNA" (ASCENDANT) DO THE HOUSES USE?
#   The app only collects a date of birth (no time, no geocoded place), so
#   the true Ascendant can't be calculated -- it changes every ~2 hours.
#   Instead, houses are counted from the MOON SIGN ("Chandra Lagna" /
#   Chandra Kundali), a genuine, traditional Vedic method for exactly this
#   situation. The Moon sign is the same Rashi already shown in the report,
#   so everything stays consistent. Consequence: the Moon is always in the
#   1st house of this chart, and every other planet's house is its distance
#   from the Moon sign.
#
# WHAT IS APPROXIMATE?
#   Planets are evaluated at 12:00 UTC on the birth date (same reference
#   point as compute_birth_facts). The Moon covers ~13 deg per day, so the
#   exact Moon position -- and therefore the Dasha start dates -- can be off
#   by up to several years. `dasha_uncertain` flags when the running
#   Mahadasha itself could change depending on the time of day.

PLANET_ORDER = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Rahu", "Ketu"]

_PLANET_IDS = {
    "Sun": swe.SUN,
    "Moon": swe.MOON,
    "Mars": swe.MARS,
    "Mercury": swe.MERCURY,
    "Jupiter": swe.JUPITER,
    "Venus": swe.VENUS,
    "Saturn": swe.SATURN,
    "Rahu": swe.MEAN_NODE,  # Ketu is always exactly 180 deg opposite Rahu
}

# Vimshottari Dasha: total 120 years, in this fixed order (same order as
# NAKSHATRA_LORDS_CYCLE).
DASHA_YEARS = {
    "Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10, "Mars": 7,
    "Rahu": 18, "Jupiter": 16, "Saturn": 19, "Mercury": 17,
}
DASHA_ORDER = NAKSHATRA_LORDS_CYCLE
_DASHA_TOTAL_YEARS = 120.0
_YEAR_DAYS = 365.25


def _sidereal_with_speed(jd_ut: float, planet: int):
    _use_lahiri()
    xx, _flags = swe.calc_ut(jd_ut, planet, swe.FLG_SIDEREAL | swe.FLG_MOSEPH | swe.FLG_SPEED)
    return xx[0] % 360.0, xx[3]


def _fmt_degree(deg_in_sign: float) -> str:
    d = int(deg_in_sign)
    m = int((deg_in_sign - d) * 60)
    return f"{d}\u00b0{m:02d}'"


def _sublords(start_lord: str):
    """The 9 Dasha lords in Vimshottari order, beginning with start_lord."""
    i = DASHA_ORDER.index(start_lord)
    return DASHA_ORDER[i:] + DASHA_ORDER[:i]


def _sub_periods(lord: str, start: datetime, total_days: float):
    """
    Split a period of `total_days` owned by `lord` into its 9 sub-periods
    (Mahadasha -> Antardasha, Antardasha -> Pratyantardasha). Each
    sub-lord's share is its Dasha years / 120, and the sequence starts with
    the period's own lord.
    """
    out = []
    cursor = start
    for sub in _sublords(lord):
        days = total_days * DASHA_YEARS[sub] / _DASHA_TOTAL_YEARS
        end = cursor + timedelta(days=days)
        out.append({"lord": sub, "start": cursor, "end": end, "days": days})
        cursor = end
    return out


def _mahadashas(moon_lon: float, birth_dt: datetime):
    """
    All Mahadashas from birth onward (first one is the partial "balance"
    period). `start` of the first entry is the *virtual* full-period start
    (before birth), which is what Antardasha maths must be based on.
    """
    idx = int(moon_lon // _NAKSHATRA_SPAN) % 27
    first_lord = NAKSHATRA_LORDS_CYCLE[idx % 9]
    elapsed_fraction = (moon_lon % _NAKSHATRA_SPAN) / _NAKSHATRA_SPAN

    first_total_days = DASHA_YEARS[first_lord] * _YEAR_DAYS
    cursor = birth_dt - timedelta(days=first_total_days * elapsed_fraction)

    periods = []
    # 3 full cycles is far more than a human lifetime (120y each).
    for lord in (_sublords(first_lord) * 3):
        days = DASHA_YEARS[lord] * _YEAR_DAYS
        end = cursor + timedelta(days=days)
        periods.append({"lord": lord, "start": cursor, "end": end, "days": days})
        cursor = end
    return periods


def _find_current(periods, as_of: datetime):
    for p in periods:
        if p["start"] <= as_of < p["end"]:
            return p
    return periods[-1]


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _nice(dt: datetime) -> str:
    return dt.strftime("%d %b %Y")


def _period_view(p: dict) -> dict:
    return {
        "lord": p["lord"],
        "start": _iso(p["start"]),
        "end": _iso(p["end"]),
        "start_text": _nice(p["start"]),
        "end_text": _nice(p["end"]),
        "years": round(p["days"] / _YEAR_DAYS, 2),
    }


def _current_mahadasha_lord(moon_lon: float, birth_dt: datetime, as_of: datetime) -> str:
    return _find_current(_mahadashas(moon_lon, birth_dt), as_of)["lord"]


def compute_dasha(dob_iso: str, as_of: datetime = None, birth_dt_utc: datetime = None) -> dict:
    """
    Vimshottari Dasha for a birth date, evaluated at `as_of` (default:
    now, UTC). Returns the running Mahadasha, Antardasha and
    Pratyantardasha (with start/end dates) plus a short timeline of
    neighbouring Mahadashas.
    """
    year, month, day = (int(p) for p in dob_iso.split("-")[:3])
    exact = birth_dt_utc is not None
    # Exact birth moment when known, else the same 12:00 UTC reference as the Moon calc.
    birth_dt = birth_dt_utc if exact else datetime(year, month, day, 12, 0)
    if as_of is None:
        as_of = datetime.now(timezone.utc).replace(tzinfo=None)
    if as_of < birth_dt:
        as_of = birth_dt

    jd_birth = _jd_from_utc(birth_dt)
    moon_lon, _ = _sidereal_with_speed(jd_birth, swe.MOON)

    periods = _mahadashas(moon_lon, birth_dt)
    md = _find_current(periods, as_of)

    ads = _sub_periods(md["lord"], md["start"], md["days"])
    ad = _find_current(ads, as_of)

    pds = _sub_periods(ad["lord"], ad["start"], ad["days"])
    pd = _find_current(pds, as_of)

    # Timeline: previous, current and next three Mahadashas.
    md_index = periods.index(md)
    lo = max(0, md_index - 1)
    timeline = []
    for p in periods[lo: md_index + 4]:
        view = _period_view(p)
        view["is_current"] = p is md
        timeline.append(view)

    # Is the running Mahadasha itself sensitive to the (unknown) time of day?
    lords_seen = {md["lord"]}
    if not exact:  # with an exact birth time there is no time-of-day ambiguity
        for hour in (0.0, 23.99):
            jd = swe.julday(year, month, day, hour)
            lon, _ = _sidereal_with_speed(jd, swe.MOON)
            lords_seen.add(_current_mahadasha_lord(lon, birth_dt, as_of))

    return {
        "as_of": _iso(as_of),
        "as_of_text": _nice(as_of),
        "mahadasha": _period_view(md),
        "antardasha": _period_view(ad),
        "pratyantardasha": _period_view(pd),
        "timeline": timeline,
        "dasha_uncertain": len(lords_seen) > 1,
    }


def _lagna_sign_at(dt_utc: datetime, lat: float, lon: float) -> int:
    _use_lahiri()
    _cusps, ascmc = swe.houses_ex(_jd_from_utc(dt_utc), lat, lon, b"W", swe.FLG_SIDEREAL)
    return int((ascmc[0] % 360.0) // 30) % 12


def compute_lagna_window(birth_dt_utc: datetime, lat: float, lon: float, max_minutes: int = 360) -> dict:
    """
    How long the Ascendant sign stays the same around the birth moment:
    minutes back to the previous sign change and forward to the next one
    (searched minute by minute, capped at `max_minutes` each way). This
    tells the person how precise their birth time needs to be: inside this
    window every house number stays the same; outside it they all shift.
    """
    base = _lagna_sign_at(birth_dt_utc, lat, lon)

    def scan(direction: int):
        for minute in range(1, max_minutes + 1):
            if _lagna_sign_at(birth_dt_utc + timedelta(minutes=direction * minute), lat, lon) != base:
                return minute - 1, False
        return max_minutes, True

    before, before_capped = scan(-1)
    after, after_capped = scan(+1)
    return {
        "minutes_before": before,
        "minutes_after": after,
        "before_capped": before_capped,
        "after_capped": after_capped,
    }


def compute_chart(
    dob_iso: str,
    birth_facts: dict,
    as_of: datetime = None,
    birth_dt_utc: datetime = None,
    lat: float = None,
    lon: float = None,
) -> dict:
    """
    Real sidereal positions (Lahiri) of Sun, Moon, Mars, Mercury, Jupiter,
    Venus, Saturn, Rahu and Ketu, the house each occupies (counted from
    the Moon sign -- see the section comment above), the advantages /
    disadvantages of that placement from the Planets-in-Houses table
    (house_effects.py), and the running Vimshottari Dasha.

    `birth_facts` is the dict from compute_birth_facts(); its Moon sign is
    reused so the chart always agrees with the Rashi shown elsewhere.

    TWO MODES
      * Date only (default): planets at 12:00 UTC, houses counted from the
        Moon sign (Chandra Lagna).
      * Exact time + place (`birth_dt_utc`, `lat`, `lon` all given): planets
        at the exact birth moment and houses counted from the true
        Ascendant (Lagna, whole-sign houses, Lahiri) -- this is what a
        normal Kundli shows.
    """
    year, month, day = (int(p) for p in dob_iso.split("-")[:3])
    exact = birth_dt_utc is not None
    jd_noon = _jd_from_utc(birth_dt_utc) if exact else swe.julday(year, month, day, 12.0)

    lagna_sign = None
    lagna_degree_text = None
    lagna_window = None
    if exact and lat is not None and lon is not None:
        _use_lahiri()
        _cusps, ascmc = swe.houses_ex(jd_noon, lat, lon, b"W", swe.FLG_SIDEREAL)
        asc_lon = ascmc[0] % 360.0
        lagna_sign = int(asc_lon // 30) % 12
        lagna_degree_text = _fmt_degree(asc_lon % 30)
        lagna_window = compute_lagna_window(birth_dt_utc, lat, lon)

    # House 1 = the Ascendant's sign when known, else the Moon's sign.
    moon_sign = birth_facts["moon_rashi_index"]
    reference_sign = lagna_sign if lagna_sign is not None else moon_sign

    longitudes = {}
    retro = {}
    for name, pid in _PLANET_IDS.items():
        lon, speed = _sidereal_with_speed(jd_noon, pid)
        longitudes[name] = lon
        # The nodes are *always* retrograde in the mean-node model; Ketu is
        # opposite Rahu. Marking them "retrograde" would just be noise.
        retro[name] = speed < 0 and name != "Rahu"
    longitudes["Ketu"] = (longitudes["Rahu"] + 180.0) % 360.0
    retro["Ketu"] = False

    planets = []
    for name in PLANET_ORDER:
        lon = longitudes[name]
        sign_index = int(lon // 30) % 12
        deg_in_sign = lon % 30
        house = (sign_index - reference_sign) % 12 + 1
        traits = house_effects.get_traits(name, house)
        verdict = house_effects.verdict_for(traits)
        title, governs = house_effects.HOUSE_INFO[house]
        planets.append(
            {
                "name": name,
                "sign": RASHI_NAMES[sign_index],
                "sign_index": sign_index,
                # floor (not round): 29.996 must stay 29.99, never become "30.0"
                "degree": int(deg_in_sign * 100) / 100,
                "degree_text": _fmt_degree(deg_in_sign),
                "retrograde": retro[name],
                "house": house,
                "house_title": title,
                "house_governs": governs,
                "advantages": [t["text"] for t in traits if t["polarity"] > 0],
                "disadvantages": [t["text"] for t in traits if t["polarity"] < 0],
                "mixed": [t["text"] for t in traits if t["polarity"] == 0],
                "verdict": verdict,
                "verdict_label": house_effects.VERDICT_LABELS[verdict],
            }
        )

    dasha = compute_dasha(dob_iso, as_of, birth_dt_utc=birth_dt_utc)

    # Attach the Dasha lords' own placement quality: a running period is as
    # good or bad as the house its lord occupies in this chart.
    by_name = {p["name"]: p for p in planets}
    for key in ("mahadasha", "antardasha", "pratyantardasha"):
        lord = dasha[key]["lord"]
        dasha[key]["lord_house"] = by_name[lord]["house"]
        dasha[key]["verdict"] = by_name[lord]["verdict"]
        dasha[key]["verdict_label"] = by_name[lord]["verdict_label"]
        dasha[key]["advantages"] = by_name[lord]["advantages"]
        dasha[key]["disadvantages"] = by_name[lord]["disadvantages"]
        dasha[key]["mixed"] = by_name[lord]["mixed"]
    for entry in dasha["timeline"]:
        entry["verdict"] = by_name[entry["lord"]]["verdict"]
        entry["verdict_label"] = by_name[entry["lord"]]["verdict_label"]
        entry["lord_house"] = by_name[entry["lord"]]["house"]

    return {
        "reference_type": "lagna" if lagna_sign is not None else "moon",
        "reference": (
            "Lagna (houses counted from the Ascendant)"
            if lagna_sign is not None
            else "Chandra Lagna (houses counted from the Moon sign)"
        ),
        "lagna": RASHI_NAMES[lagna_sign] if lagna_sign is not None else None,
        "lagna_degree_text": lagna_degree_text,
        "lagna_window": lagna_window,
        "birth_time_used": exact,
        "moon_sign": RASHI_NAMES[moon_sign],
        "moon_sign_uncertain": bool(birth_facts.get("moon_sign_uncertain")),
        "planets": planets,
        "dasha": dasha,
        "source_caveat": house_effects.SOURCE_CAVEAT,
    }
