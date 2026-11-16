"""lib/toc-sampling.ts: SAMPLE 3.3, minimum sample sizes for tests of controls.

Discovery sampling: the sizes assume no or very few exceptions in the population;
exceptions found mean extend or stop and reassess (SAMPLE 3.6.2).
"""
import random as _random
import re

from ._js import js_ceil, js_floor
from .control_labels import freq_label

#: The size a 25-item plan extends to after a single deviation.
TOC_EXTENDED_SIZE = 60


def norm_freq(frequency):
    s = (frequency if frequency is not None else "").lower()
    if "dail" in s or "jour" in s or "continuous" in s or "many" in s:
        return "daily"
    if "week" in s or "hebdo" in s:
        return "weekly"
    if "month" in s or "mens" in s:
        return "monthly"
    if "quart" in s or "trim" in s:
        return "quarterly"
    if "semi" in s or "semes" in s:
        return "semi_annually"
    if "ann" in s:
        return "annually"
    return s


#: The owner's sample table (ruling of 2026-11-16), the single source for tests of controls.
#: A periodic frequency: (normal reliance, heavy reliance or significant risk).
FREQUENCY_CODES = [
    "multiple_daily", "daily", "weekly", "twice_monthly", "monthly", "quarterly", "semi_annually", "annually", "event", "other",
]
FREQUENCY_SIZES = {
    "annually": (1, 1), "semi_annually": (1, 2), "quarterly": (2, 2), "monthly": (2, 4), "twice_monthly": (3, 6), "weekly": (5, 10),
}
#: Frequencies whose size follows the number of occurrences in the year.
OCCURRENCE_FREQUENCIES = ("multiple_daily", "daily", "event")
#: Over 250 occurrences: normal, heavy, and the only control on the assertion.
LARGE_POPULATION_SIZES = {"normal": 25, "heavy": 40, "sole": 60}
RELIANCE_LEVELS = ("normal", "heavy")

FREQUENCY_LABELS = {
    "multiple_daily": ("Multiple times a day", "Plusieurs fois par jour"),
    "daily": ("Daily", "Quotidien"),
    "weekly": ("Weekly", "Hebdomadaire"),
    "twice_monthly": ("Twice a month", "Deux fois par mois"),
    "monthly": ("Monthly", "Mensuel"),
    "quarterly": ("Quarterly", "Trimestriel"),
    "semi_annually": ("Semi-annually", "Semestriel"),
    "annually": ("Annually", "Annuel"),
    "event": ("Event-driven (each time it happens)", "À chaque événement"),
    "other": ("Other", "Autre"),
}


def frequency_label(code, fr):
    """The label of a frequency code; anything else is shown as it was typed."""
    pair = FREQUENCY_LABELS.get(code)
    if pair:
        return pair[1] if fr else pair[0]
    return freq_label(code, fr)


# The keyword parser for the free text typed before the fixed list existed. Each pattern is
# searched in the lower-cased text; French and English words both count. i18n: input
_PATTERNS = [
    ("multiple_daily", re.compile(r"several times a day|many times a day|multiple times|times a day|continuous|plusieurs fois par jour|en continu|\bcontinu")),  # i18n: input
    ("daily", re.compile(r"\bdaily\b|\bper day\b|\bevery day\b|\beach day\b|quotidien|journalier|journali[eè]re|\bpar jour\b|chaque jour|tous les jours")),  # i18n: input
    ("weekly", re.compile(r"week|hebdo")),  # i18n: input
    ("twice_monthly", re.compile(r"twice a month|twice monthly|twice-monthly|semi-?monthly|fortnight|bimensuel|deux fois par mois|quinzaine")),  # i18n: input
    ("monthly", re.compile(r"month|mensuel|\bmois\b")),  # i18n: input
    ("quarterly", re.compile(r"quarter|trimest")),  # i18n: input
    ("semi_annually", re.compile(r"semi-?annual|half-?year|half year|semestri|semester")),  # i18n: input
    ("annually", re.compile(r"\bannual|yearly|once a year|\bannuel|une fois par an")),  # i18n: input
    ("event", re.compile(r"\beach\b|\bevery\b|\bchaque\b|per transaction|\bevent|[ée]v[ée]nement|occurrence|on demand|as needed")),  # i18n: input
]


def frequency_code_from_text(text):
    """The fixed-list code a free-text frequency means, or None when it means none or several.

    A more specific wording wins over the word it contains ("semi-annually" is not "annually",
    "twice a month" is not "monthly"); "each"/"chaque" means event-driven only when no period is
    named ("each month" is monthly)."""
    s = (text or "").strip().lower()
    if not s:
        return None
    if s in FREQUENCY_CODES:
        return s
    found = {code for code, pattern in _PATTERNS if pattern.search(s)}
    if "multiple_daily" in found:
        found.discard("daily")
    if "twice_monthly" in found:
        found.discard("monthly")
        found.discard("semi_annually")
    if "semi_annually" in found:
        found.discard("annually")
    if len(found) > 1:
        found.discard("event")
    return found.pop() if len(found) == 1 else None


def effective_frequency(code, text):
    """The stored code, else what the legacy text parses to."""
    return code if code in FREQUENCY_CODES else frequency_code_from_text(text)


def toc_suggested(control_type, frequency, population, sole, fr, reliance="normal"):
    """{size, rule}, {needPopulation: True}, or None when the frequency is unknown or "other".

    ``frequency`` is a code of the fixed list or, for a control recorded before it, free text."""
    # The test of one belongs to a genuinely AUTOMATED control. An IT-dependent
    # manual control still has a person performing it: it follows the table.
    if control_type == "automated":
        return {
            "size": 1,
            "rule": "Contrôle automatisé — test unique (ITGC efficaces)" if fr else "Automated/application control — test of one (ITGCs effective)",
        }
    heavy = reliance == "heavy"
    f = effective_frequency(frequency, frequency)
    if f is None or f == "other":
        return None
    label = frequency_label(f, fr)
    if heavy:
        label = "%s, %s" % (label, "forte confiance" if fr else "heavy reliance")
    if f in OCCURRENCE_FREQUENCIES:
        if not population or population < 1:
            return {"needPopulation": True}
        if population > 250:
            if sole:
                size = LARGE_POPULATION_SIZES["sole"]
                return {"size": size, "rule": "%s, seul contrôle sur l'assertion → %d" % (label, size) if fr else "%s, only control on its assertion → %d" % (label, size)}
            size = LARGE_POPULATION_SIZES["heavy" if heavy else "normal"]
            return {"size": size, "rule": "%s, population > 250 → %d" % (label, size)}
        if population >= 50:
            return {"size": js_ceil(population * 0.1), "rule": "50–250 occurrences → 10 %" if fr else "50–250 occurrences → 10%"}
        if population >= 5:
            return {"size": 5, "rule": "< 50 occurrences → 5" if fr else "Under 50 occurrences → 5"}
        return {"size": population, "rule": "< 5 occurrences → 100 %" if fr else "Under 5 occurrences → all of them"}
    size = FREQUENCY_SIZES[f][1 if heavy else 0]
    capped = min(size, population) if population and population > 0 else size
    if fr:
        return {"size": capped, "rule": "Manuel, %s → minimum %d" % (label.lower(), size)}
    return {"size": capped, "rule": "Manual, %s → minimum %d" % (label.lower(), size)}


def frequency_choice_sizes(code, fr):
    """What the frequency list shows beside a choice: "normal · heavy", or what it needs."""
    if code in FREQUENCY_SIZES:
        return "%d · %d" % FREQUENCY_SIZES[code]
    if code in OCCURRENCE_FREQUENCIES:
        return "nombre requis" if fr else "count needed"
    return "motif requis" if fr else "reason needed"


def draw_toc_sample(population, size, rng=None):
    """``size`` distinct occurrence numbers from 1 to ``population``, ascending.

    ``rng`` supplies the randomness: the server passes a generator derived from a
    stored seed, so a draw can be reproduced from its seed (F061).
    """
    rng = rng or _random.random
    n = max(0, js_floor(population))
    k = min(max(0, js_floor(size)), n)
    if k == 0:
        return []
    # partial Fisher-Yates over 1..n: exact, unbiased, cheap for a large population
    picked = {}
    out = []
    for i in range(k):
        j = i + js_floor(rng() * (n - i))
        vi = picked.get(i, i + 1)
        vj = picked.get(j, j + 1)
        out.append(vj)
        picked[j] = vi
        picked[i] = vj
    return sorted(out)


def seeded_rng(seed, random):
    """A generator whose i-th call returns ``random(seed, i)``."""
    index = [0]

    def rng():
        value = random(seed, index[0])
        index[0] += 1
        return value

    return rng


def toc_testing_started(grid):
    """True once any row of the E1.2 grid carries a result for any attribute."""
    if not grid or not isinstance(grid.get("rows"), list):
        return False
    for row in grid["rows"]:
        results = (row or {}).get("results") or {}
        if any(isinstance(v, str) and v != "" for v in results.values()):
            return True
    return False


def toc_evaluate(plan, tested, deviations):
    """Deviation evaluation: "high", "moderate", "rely", "extend" or "none"."""
    if deviations < 0:
        return "none"
    # A test extended to 60, or planned at 60, is judged on the 60 rule.
    if tested >= TOC_EXTENDED_SIZE or plan >= TOC_EXTENDED_SIZE:
        if deviations == 0:
            return "high"
        return "moderate" if deviations == 1 else "none"
    if plan >= 25:
        if deviations == 0:
            return "rely"
        return "extend" if deviations == 1 else "none"
    # 5, 2, 1 and the occurrence plans: the hypothesis is no exceptions at all.
    return "rely" if deviations == 0 else "none"
