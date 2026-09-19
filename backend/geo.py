"""
geo.py

Turns the free-text "Place of Birth" into coordinates + a time zone, and
converts a local birth time into UTC. Needed only when the person supplies
the OPTIONAL Time of Birth: with an exact moment and a location the
Ascendant (Lagna) -- and therefore the true house of every planet -- can
be calculated.

Lookup uses the free Open-Meteo geocoding API (no API key). It returns
latitude, longitude AND the IANA time zone (e.g. "Asia/Kolkata") in one
call, and Python's zoneinfo (tzdata) applies the historical UTC offset for
the birth date, including any past daylight-saving rules.

EVERYTHING HERE FAILS SAFE: any network error, timeout, unknown place or
bad time returns None, and the app simply falls back to the date-only
chart (houses counted from the Moon sign). It never blocks or breaks
report generation.
"""

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger("palmai")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
TIMEOUT_SECONDS = 6


def _fetch(name: str) -> list:
    """One geocoding request; returns the raw result list (may be empty)."""
    query = urllib.parse.urlencode({"name": name, "count": 10, "language": "en", "format": "json"})
    request = urllib.request.Request(
        f"{GEOCODE_URL}?{query}", headers={"User-Agent": "PalmAI-VedicReport/1.0"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        payload = json.load(response)
    return payload.get("results") or []


def resolve_place(place: str) -> Optional[dict]:
    """
    "Bhubaneswar, Odisha, India" -> {"lat", "lon", "timezone", "name"}.

    The first comma-separated part is the city that is searched; the
    remaining parts (state / country) are used to pick the right match when
    several places share the city name. Returns None if nothing usable is
    found or the lookup fails.
    """
    parts = [p.strip() for p in (place or "").split(",") if p.strip()]
    if not parts:
        return None
    city, hints = parts[0], [h.lower() for h in parts[1:]]

    try:
        results = _fetch(city)
        if not results and " " in city:
            # "Cuttack Odisha" typed without commas -> retry with the first word.
            results = _fetch(city.split()[0])
            hints = [w.lower() for w in city.split()[1:]] + hints
    except Exception:
        logger.exception("Geocoding lookup failed for place=%r", place)
        return None

    usable = [
        r for r in results
        if r.get("latitude") is not None and r.get("longitude") is not None and r.get("timezone")
    ]
    if not usable:
        return None

    def score(result: dict) -> int:
        haystack = " ".join(
            str(result.get(k, "")) for k in ("admin1", "admin2", "admin3", "country", "country_code")
        ).lower()
        return sum(1 for hint in hints if hint in haystack)

    best = max(usable, key=score)  # ties keep the API's own relevance order
    best_score = score(best)

    # Ambiguous = another, clearly different place matches just as well
    # (e.g. "Aurangabad" with no state). The person should double-check it.
    ambiguous = any(
        score(r) == best_score
        and (abs(r["latitude"] - best["latitude"]) > 0.5 or abs(r["longitude"] - best["longitude"]) > 0.5)
        for r in usable
        if r is not best
    )

    name = best.get("name") or city
    display = ", ".join(str(x) for x in (name, best.get("admin1"), best.get("country")) if x)
    return {
        "lat": float(best["latitude"]),
        "lon": float(best["longitude"]),
        "timezone": best["timezone"],
        "name": name,
        "display": display,
        "ambiguous": ambiguous,
    }


def parse_time_of_birth(tob: str) -> Optional[tuple]:
    """'10:30' or '10:30:15' -> (10, 30). None if empty or invalid."""
    if not tob or not tob.strip():
        return None
    bits = tob.strip().split(":")
    if len(bits) not in (2, 3):
        return None
    try:
        hour, minute = int(bits[0]), int(bits[1])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def format_time_12h(hour: int, minute: int) -> str:
    """(10, 5) -> '10:05 AM'."""
    suffix = "AM" if hour < 12 else "PM"
    return f"{(hour % 12) or 12}:{minute:02d} {suffix}"


def utc_to_local_text(dt_utc: datetime, tz_name: str, reference_local_date=None) -> str:
    """
    Naive UTC datetime -> '11:30 PM' in tz_name. If `reference_local_date`
    is given and the local date differs, ' (next day)' / ' (previous day)'
    is appended.
    """
    local = dt_utc.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name))
    text = format_time_12h(local.hour, local.minute)
    if reference_local_date is not None and local.date() != reference_local_date:
        text += " (next day)" if local.date() > reference_local_date else " (previous day)"
    return text


def local_to_utc(dob_iso: str, tob: str, tz_name: str) -> Optional[datetime]:
    """
    Local birth date + time in `tz_name` -> naive UTC datetime, or None if
    anything is invalid.
    """
    hm = parse_time_of_birth(tob)
    if hm is None:
        return None
    try:
        year, month, day = (int(p) for p in dob_iso.split("-")[:3])
        local = datetime(year, month, day, hm[0], hm[1], tzinfo=ZoneInfo(tz_name))
    except Exception:
        logger.exception("Could not convert birth time (dob=%s tob=%s tz=%s)", dob_iso, tob, tz_name)
        return None
    return local.astimezone(timezone.utc).replace(tzinfo=None)
