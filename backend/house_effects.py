"""
house_effects.py

The "Planets in Houses" reference table (source: @astrological__india,
Instagram), encoded as data so the report can show, for every planet,
which house it sits in and what the advantages / disadvantages of that
placement are.

HOW TO READ / EDIT THE TABLE BELOW
-----------------------------------
Each cell is a string of traits separated by "|", and every trait starts
with a polarity character:

    +  advantage      (shown in GREEN)
    -  disadvantage   (shown in RED)
    ~  mixed / conditional (shown in AMBER)

    e.g.  "-Angry|+Courageous"   ->  Mars in the 1st house:
                                     disadvantage "Angry", advantage "Courageous"

The overall verdict for a planet-in-house is derived from its traits:
    only advantages           -> "good"   (green)
    only disadvantages        -> "bad"    (red)
    both / mixed / neutral    -> "mixed"  (amber)

To change wording or re-classify a trait, just edit the string -- nothing
else in the app needs to change.

NOTES ON THE SOURCE IMAGE
--------------------------
The source screenshot had a few faded cells that were read as best as
possible: 3H Mercury is the least certain; 4H Mercury and 4H Jupiter are
also faint. The row the image labels "10H" that sits between 8H and the
real 10H is treated as 9H. Please double-check those cells against the
original before going live. The source only has ONE column for
"Rahu/Ketu", so both nodes use the same entries.

The source also carries this caveat, shown in the report: the intensity
of results may vary if another planet strongly influences the planet.
"""

from typing import Dict, List

SOURCE_CAVEAT = (
    "The intensity of these results may vary if another planet strongly "
    "influences the planet."
)

# House -> (short title, what the house governs). Standard Vedic bhava
# significations.
HOUSE_INFO: Dict[int, tuple] = {
    1: ("Self & Personality", "body, vitality, temperament and overall life direction"),
    2: ("Wealth & Speech", "money, family, speech, food and savings"),
    3: ("Courage & Communication", "courage, siblings, skills, effort and communication"),
    4: ("Home & Happiness", "home, mother, inner peace, comforts and vehicles"),
    5: ("Intellect & Children", "intelligence, children, creativity and past-life merit"),
    6: ("Health & Obstacles", "enemies, debts, disease, service and competition"),
    7: ("Marriage & Partnership", "spouse, marriage, partnerships and business dealings"),
    8: ("Longevity & Transformation", "longevity, sudden events, secrets and transformation"),
    9: ("Fortune & Dharma", "luck, faith, father, higher learning and spirituality"),
    10: ("Career & Status", "career, status, reputation and public life"),
    11: ("Gains & Fulfilment", "income, gains, networks and fulfilment of desires"),
    12: ("Losses & Isolation", "expenses, losses, isolation, sleep and foreign lands"),
}

# planet -> house -> "traits"
_RAW: Dict[str, Dict[int, str]] = {
    "Sun": {
        1: "-Ego|-Anger",
        2: "-Poor|-Harsh Speech",
        3: "+High Courage",
        4: "-Unhappy",
        5: "-Progeny loss or problems",
        6: "+Victorious",
        7: "-Marriage problems",
        8: "-Short Lived",
        9: "+Religious",
        10: "+Eminent (Top placed)",
        11: "+Wealthy",
        12: "-Isolated|-Cruel",
    },
    "Moon": {
        1: "+Pleasant",
        2: "+Rich",
        3: "+Curious & active mind",
        4: "+Happy",
        5: "+Wealthy",
        6: "-Mental & Physical Stress",
        7: "+Happily married",
        8: "-Diseased|-Stress",
        9: "+Religious",
        10: "+Learned",
        11: "+Wealthy",
        12: "-Over Sexed|-Sleep disorders",
    },
    "Mars": {
        1: "-Angry|+Courageous",
        2: "-Harsh Speech",
        3: "+Energetic fighter",
        4: "-Domestic clashes",
        5: "-Restless, agitated mind",
        6: "+Victorious",
        7: "-Loss of partner",
        8: "-Diseased",
        9: "-Frustrated",
        10: "+Eminent (Top placed)",
        11: "+Wealthy",
        12: "-Dishonest",
    },
    "Mercury": {
        1: "+Happy|+Clever",
        2: "+Healthy",
        3: "+Good communication skill",  # faint in source
        4: "-O.C.D problem",  # faint in source
        5: "+Intelligent",
        6: "-Diseased",
        7: "-Unfaithful",
        8: "+Eminent",
        9: "+Sharp intellect",
        10: "+Famous",
        11: "+Wealthy",
        12: "-Poor|-Indecisive",
    },
    "Jupiter": {
        1: "+Good Knowledge",
        2: "+Wealthy",
        3: "+Good communication skill",
        4: "+Happy",  # faint in source
        5: "+Wealthy|+Famous",
        6: "-Wealth & Progeny issues",
        7: "+Gives a wise partner",
        8: "-Chronic disease",
        9: "+Religious",
        10: "+Eminent",
        11: "+Self made",
        12: "-Poor",
    },
    "Venus": {
        1: "+Pleasant|+Outgoing",
        2: "+Rich|+Pleasant",
        3: "+Artistic|+Creative",
        4: "+Happy|+Good cars",
        5: "~Emotional|+Artistic",
        6: "-Frustrated",
        7: "-Over Sexed",
        8: "+Rich|-Low sperm",
        9: "+Spiritual",
        10: "+Rich",
        11: "+Rich",
        12: "+Rich|-Over Sexed",
    },
    "Saturn": {
        1: "-Melancholy|-Diseased",
        2: "-Loss of wealth",
        3: "+Courageous|+Brave",
        4: "-Melancholy",
        5: "-Dull|-Sad",
        6: "-Disputes|-Sad",
        7: "-Delayed marriage",
        8: "+Good longevity",
        9: "-Setbacks",
        10: "~Rich after downfall",
        11: "+Rich",
        12: "-Isolated",
    },
    # The source has a single "Rahu/Ketu" column.
    "Rahu/Ketu": {
        1: "-Diseased",
        2: "-Wealth loss",
        3: "+Brave",
        4: "-Melancholy",
        5: "+Shrewd|-Idiot & stupid",
        6: "+Victorious",
        7: "-Marriage problem",
        8: "-Diseased",
        9: "-Setbacks & Clue",
        10: "+Famous",
        11: "+Wealthy",
        12: "-Wealth loss",
    },
}

POLARITY = {"+": 1, "-": -1, "~": 0}

VERDICT_LABELS = {
    "good": "Favourable",
    "bad": "Challenging",
    "mixed": "Mixed",
}


def _table_key(planet: str) -> str:
    """Rahu and Ketu share one column in the source table."""
    return "Rahu/Ketu" if planet in ("Rahu", "Ketu") else planet


def get_traits(planet: str, house: int) -> List[dict]:
    """
    Returns the traits for `planet` in `house` (1-12) as
    [{"text": "Harsh Speech", "polarity": -1}, ...]. Empty list if the
    planet/house isn't in the table.
    """
    raw = _RAW.get(_table_key(planet), {}).get(house, "")
    traits = []
    for part in raw.split("|"):
        part = part.strip()
        if not part or part[0] not in POLARITY:
            continue
        traits.append({"text": part[1:].strip(), "polarity": POLARITY[part[0]]})
    return traits


def verdict_for(traits: List[dict]) -> str:
    """'good' (only advantages), 'bad' (only disadvantages), else 'mixed'."""
    has_pos = any(t["polarity"] > 0 for t in traits)
    has_neg = any(t["polarity"] < 0 for t in traits)
    if has_pos and not has_neg:
        return "good"
    if has_neg and not has_pos:
        return "bad"
    return "mixed"
