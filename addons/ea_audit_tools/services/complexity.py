"""lib/complexity.ts: nature-of-entity assessment and engagement naming.

Seventeen yes/no questions classify the entity as complex, non-complex or very
simple. Some answers force "complex"; the rest accumulate weighted points.
"""
import re

from ._js import is_number, js_number_str, js_replace_all, js_str, js_trim, u16_len, u16_slice

COMPLEXITY_QUESTIONS = [
    {"key": "listed", "autoComplex": True, "weight": 0},
    {"key": "publicInterest", "autoComplex": True, "weight": 0},
    {"key": "group", "autoComplex": True, "weight": 0},
    {"key": "jointAudit", "weight": 2},
    {"key": "foreignOps", "weight": 2},
    {"key": "complexFinancing", "weight": 2},
    {"key": "complexRevenue", "weight": 2},
    {"key": "estimates", "weight": 2},
    {"key": "controlsReliance", "weight": 1},
    {"key": "complexIt", "weight": 1},
    {"key": "multiLocation", "weight": 1},
    {"key": "largeSize", "weight": 2},
    {"key": "firstAudit", "weight": 1},
    {"key": "goingConcern", "weight": 2},
    {"key": "relatedParties", "weight": 1},
    {"key": "restructuring", "weight": 2},
    {"key": "litigation", "weight": 2},
]

_COMPLEX_THRESHOLD = 8
_NON_COMPLEX_THRESHOLD = 3

DEFAULT_ENGAGEMENT_NAMING = "{CLIENT}_{PERIOD_END}_{NATURE}"

YEAR_END_OPTIONS = [
    {"value": "06-30", "en": "June 30", "fr": "30 juin"},
    {"value": "07-31", "en": "July 31", "fr": "31 juillet"},
    {"value": "12-31", "en": "December 31", "fr": "31 décembre"},
    {"value": "03-31", "en": "March 31", "fr": "31 mars"},
]

DURATION_OPTIONS = [6, 12]

NATURE_OPTIONS = [
    {"value": "statutory_audit", "en": "Statutory audit", "fr": "Commissariat aux comptes"},
    {"value": "agreed_procedures", "en": "Agreed-upon procedures", "fr": "Procédures convenues"},
    {"value": "other", "en": "Other", "fr": "Autre"},
]

ENGAGEMENT_PHASE_OPTIONS = [
    {"value": "interim", "en": "Interim", "fr": "Intérimaire"},
    {"value": "year_end", "en": "Year end", "fr": "Clôture"},
]

FRAMEWORK_OPTIONS = [
    {"value": "syscohada", "en": "SYSCOHADA", "fr": "SYSCOHADA"},
    {"value": "ifrs", "en": "IFRS", "fr": "IFRS"},
]

_MONTHS_EN = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"]
_MONTHS_FR = ["JANVIER", "FÉVRIER", "MARS", "AVRIL", "MAI", "JUIN", "JUILLET", "AOÛT", "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DÉCEMBRE"]
_MONTH_DAY = re.compile(r"([0-9]{2})-([0-9]{2})")


def classify_complexity(answers):
    """{level, score, knockouts} from an answers dict."""
    knockouts = [q["key"] for q in COMPLEXITY_QUESTIONS if q.get("autoComplex") and answers.get(q["key"])]
    score = 0
    for question in COMPLEXITY_QUESTIONS:
        if not question.get("autoComplex") and answers.get(question["key"]):
            score += question["weight"]
    if knockouts or score >= _COMPLEX_THRESHOLD:
        level = "complex"
    elif score >= _NON_COMPLEX_THRESHOLD:
        level = "non_complex"
    else:
        level = "very_simple"
    return {"level": level, "score": score, "knockouts": knockouts}


def answers_from_form(get):
    """Parse checkbox form data (q_<key>=on) into an answers dict."""
    return {q["key"]: get("q_" + q["key"]) == "on" for q in COMPLEXITY_QUESTIONS}


def period_end_label(month_day, locale="en"):
    """"MM-DD" to "DECEMBER 31" (en) or "31 DÉCEMBRE" (fr); any month-day (UAT run2-B117)."""
    for option in YEAR_END_OPTIONS:
        if option["value"] == month_day:
            return (option["fr"] if locale == "fr" else option["en"]).upper()
    match = _MONTH_DAY.fullmatch(month_day)
    if not match:
        return ""
    index = int(match.group(1)) - 1
    if index < 0 or index > 11:
        return ""
    month = (_MONTHS_FR if locale == "fr" else _MONTHS_EN)[index]
    day = int(match.group(2))
    return "%d %s" % (day, month) if locale == "fr" else "%s %d" % (month, day)


def nature_label(nature, locale="en"):
    """A known nature renders its label; free text passes through as typed."""
    for option in NATURE_OPTIONS:
        if option["value"] == nature:
            return (option["fr"] if locale == "fr" else option["en"]).upper()
    return nature.replace("_", " ").upper()


def _year_str(fiscal_year):
    return js_number_str(fiscal_year) if is_number(fiscal_year) else js_str(fiscal_year)


def apply_naming_convention(pattern, client_name, fiscal_year, parts=None, locale="en"):
    parts = parts or {}
    year = _year_str(fiscal_year)
    period_end = parts.get("periodEnd")
    if period_end is None:
        period_end = year + "-12-31"
    month_day = u16_slice(period_end, 5) if u16_len(period_end) == 10 else period_end
    nature = parts.get("nature")
    if nature is None:
        nature = "statutory_audit"
    text = pattern or DEFAULT_ENGAGEMENT_NAMING
    # replaceAll with a string replacement: a client called "A$&B" expands, as in the source
    text = js_replace_all(text, "{CLIENT}", js_trim(client_name).upper())
    text = js_replace_all(text, "{YEAR}", year)
    text = js_replace_all(text, "{PERIOD_END}", js_trim("%s %s" % (period_end_label(month_day, locale), year)))
    text = js_replace_all(text, "{NATURE}", nature_label(nature, locale))
    return u16_slice(js_trim(text), 0, 120)


def generate_engagement_name(client_name, year_end, fiscal_year, nature):
    """CLIENT_PERIOD END_NATURE, uppercase: the tool generates it, the user does not type it."""
    parts = [
        js_trim(client_name).upper(),
        "%s %s" % (period_end_label(year_end), _year_str(fiscal_year)),
        nature_label(nature),
    ]
    return u16_slice("_".join(p for p in parts if p), 0, 120)
