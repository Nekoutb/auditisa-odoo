"""lib/standards-edition.ts: the edition of the ISAs an engagement is audited under (F045).

ISA 240 (Revised) and ISA 570 (Revised 2024) apply to periods beginning on or
after 15 December 2026. The paper definitions carry {{tokens}} where a reference
or a wording depends on the edition; this module derives and renders it.

TO VERIFY (from the source): every ``revised_2026`` entry of REFS keeps the current
paragraph number under the revised title until the technical desk confirms it.
"""
import re

from ._js import date_parts, date_utc, js_floor, make_day, to_iso_date
from .errors import ServiceError

STANDARDS_EDITIONS = ["current", "revised_2026"]

#: Periods beginning on or after this date apply the revised standards.
REVISED_2026_FROM = "2026-12-15"

#: messages/{en,fr}.json, key standardsEdition.
_MESSAGES = {
    "en": {
        "label": "Standards edition",
        "current": "ISA in force",
        "revised_2026": "Revised ISAs (periods beginning on or after 15/12/2026)",
    },
    "fr": {
        "label": "Édition des normes",
        "current": "ISA en vigueur",
        "revised_2026": "ISA révisées (périodes ouvertes à partir du 15/12/2026)",
    },
}

REFS = {
    "ISA240": {"current": ["ISA 240", "ISA 240"], "revised_2026": ["ISA 240 (Revised)", "ISA 240 révisée"]},
    "ISA570": {
        "current": ["ISA 570 (Revised)", "ISA 570 révisée"],
        "revised_2026": ["ISA 570 (Revised 2024)", "ISA 570 révisée 2024"],
    },
    "ISA240.std.P51": {
        "current": ["ISA 240 ¶12–27, ¶31–33, ¶40–43", "ISA 240 ¶12–27, ¶31–33, ¶40–43"],
        "revised_2026": ["ISA 240 (Revised) ¶12–27, ¶31–33, ¶40–43", "ISA 240 révisée ¶12–27, ¶31–33, ¶40–43"],
    },
    "ISA240.std.E31": {
        "current": ["ISA 240 ¶31–33", "ISA 240 ¶31–33"],
        "revised_2026": ["ISA 240 (Revised) ¶31–33", "ISA 240 révisée ¶31–33"],
    },
    "ISA240.records": {
        "current": ["ISA 240 ¶13", "ISA 240 ¶13"],
        "revised_2026": ["ISA 240 (Revised) ¶13", "ISA 240 révisée ¶13"],
    },
    "ISA240.discussion": {
        "current": ["ISA 240 ¶16", "ISA 240 ¶16"],
        "revised_2026": ["ISA 240 (Revised) ¶16", "ISA 240 révisée ¶16"],
    },
    "ISA240.assess": {
        "current": ["ISA 240 ¶25", "ISA 240 ¶25"],
        "revised_2026": ["ISA 240 (Revised) ¶25", "ISA 240 révisée ¶25"],
    },
    "ISA240.revenue": {
        "current": ["ISA 240 ¶26, ¶47", "ISA 240 ¶26, ¶47"],
        "revised_2026": ["ISA 240 (Revised) ¶26, ¶47", "ISA 240 révisée ¶26, ¶47"],
    },
    "ISA240.unpredictability": {
        "current": ["ISA 240 ¶29(c)", "ISA 240 ¶29 c)"],
        "revised_2026": ["ISA 240 (Revised) ¶29(c)", "ISA 240 révisée ¶29 c)"],
    },
    "ISA240.override": {
        "current": ["ISA 240 ¶31", "ISA 240 ¶31"],
        "revised_2026": ["ISA 240 (Revised) ¶31", "ISA 240 révisée ¶31"],
    },
    "ISA240.overrideResponses": {
        "current": ["ISA 240 ¶31–33", "ISA 240 ¶31–33"],
        "revised_2026": ["ISA 240 (Revised) ¶31–33", "ISA 240 révisée ¶31–33"],
    },
    "ISA240.jeTesting": {
        "current": ["ISA 240 ¶32", "ISA 240 ¶32"],
        "revised_2026": ["ISA 240 (Revised) ¶32", "ISA 240 révisée ¶32"],
    },
    "ISA240.jeCriteria": {
        "current": ["ISA 240 ¶32(a)", "ISA 240 ¶32 a)"],
        "revised_2026": ["ISA 240 (Revised) ¶32(a)", "ISA 240 révisée ¶32 a)"],
    },
    "ISA240.jeInquiry": {
        "current": ["ISA 240 ¶32(a)(i)", "ISA 240 ¶32 a) i)"],
        "revised_2026": ["ISA 240 (Revised) ¶32(a)(i)", "ISA 240 révisée ¶32 a) i)"],
    },
    "ISA240.jePeriodEnd": {
        "current": ["ISA 240 ¶32(a)(ii)", "ISA 240 ¶32 a) ii)"],
        "revised_2026": ["ISA 240 (Revised) ¶32(a)(ii)", "ISA 240 révisée ¶32 a) ii)"],
    },
    "ISA240.jeThroughout": {
        "current": ["ISA 240 ¶32(a)(iii)", "ISA 240 ¶32 a) iii)"],
        "revised_2026": ["ISA 240 (Revised) ¶32(a)(iii)", "ISA 240 révisée ¶32 a) iii)"],
    },
    "ISA240.jeEstimates": {
        "current": ["ISA 240 ¶32(b)", "ISA 240 ¶32 b)"],
        "revised_2026": ["ISA 240 (Revised) ¶32(b)", "ISA 240 révisée ¶32 b)"],
    },
    "ISA240.unusual": {
        "current": ["ISA 240 ¶32(c)", "ISA 240 ¶32 c)"],
        "revised_2026": ["ISA 240 (Revised) ¶32(c)", "ISA 240 révisée ¶32 c)"],
    },
    "ISA240.otherProcedures": {
        "current": ["ISA 240 ¶33", "ISA 240 ¶33"],
        "revised_2026": ["ISA 240 (Revised) ¶33", "ISA 240 révisée ¶33"],
    },
    "ISA240.evaluate": {
        "current": ["ISA 240 ¶35–36", "ISA 240 ¶35-36"],
        "revised_2026": ["ISA 240 (Revised) ¶35–36", "ISA 240 révisée ¶35-36"],
    },
    "ISA240.representations": {
        "current": ["ISA 240 ¶39", "ISA 240 ¶39"],
        "revised_2026": ["ISA 240 (Revised) ¶39", "ISA 240 révisée ¶39"],
    },
    "ISA240.commMgmt": {
        "current": ["ISA 240 ¶40", "ISA 240 ¶40"],
        "revised_2026": ["ISA 240 (Revised) ¶40", "ISA 240 révisée ¶40"],
    },
    "ISA240.commTcwg": {
        "current": ["ISA 240 ¶41", "ISA 240 ¶41"],
        "revised_2026": ["ISA 240 (Revised) ¶41", "ISA 240 révisée ¶41"],
    },
    "ISA240.commOther": {
        "current": ["ISA 240 ¶42", "ISA 240 ¶42"],
        "revised_2026": ["ISA 240 (Revised) ¶42", "ISA 240 révisée ¶42"],
    },
    "ISA240.authorities": {
        "current": ["ISA 240 ¶43", "ISA 240 ¶43"],
        "revised_2026": ["ISA 240 (Revised) ¶43", "ISA 240 révisée ¶43"],
    },
    "ISA570.std.S42": {
        "current": ["ISA 570 (Revised) ¶10–12", "ISA 570 révisée ¶10–12"],
        "revised_2026": ["ISA 570 (Revised 2024) ¶10–12", "ISA 570 révisée 2024 ¶10–12"],
    },
    "ISA570.std.E63": {
        "current": ["ISA 570 (Revised) ¶12–20, ¶25", "ISA 570 révisée ¶12–20, ¶25"],
        "revised_2026": ["ISA 570 (Revised 2024) ¶12–20, ¶25", "ISA 570 révisée 2024 ¶12–20, ¶25"],
    },
    "ISA570.std.C22": {
        "current": ["ISA 570 (Revised) ¶21–24", "ISA 570 révisée ¶21–24"],
        "revised_2026": ["ISA 570 (Revised 2024) ¶21–24", "ISA 570 révisée 2024 ¶21–24"],
    },
    "ISA570.riskAssessment": {
        "current": ["ISA 570 (Revised) ¶10–11", "ISA 570 révisée ¶10–11"],
        "revised_2026": ["ISA 570 (Revised 2024) ¶10–11", "ISA 570 révisée 2024 ¶10–11"],
    },
    "ISA570.period": {
        "current": ["ISA 570 (Revised) ¶13", "ISA 570 révisée ¶13"],
        "revised_2026": ["ISA 570 (Revised 2024) ¶13", "ISA 570 révisée 2024 ¶13"],
    },
    "ISA570.plans": {
        "current": ["ISA 570 (Revised) ¶16", "ISA 570 révisée ¶16"],
        "revised_2026": ["ISA 570 (Revised 2024) ¶16", "ISA 570 révisée 2024 ¶16"],
    },
    "ISA570.representation": {
        "current": ["ISA 570 (Revised) ¶16(e)", "ISA 570 révisée ¶16 e)"],
        "revised_2026": ["ISA 570 (Revised 2024) ¶16(e)", "ISA 570 révisée 2024 ¶16 e)"],
    },
    "ISA570.muDisclosure": {
        "current": ["ISA 570 (Revised) ¶19", "ISA 570 révisée ¶19"],
        "revised_2026": ["ISA 570 (Revised 2024) ¶19", "ISA 570 révisée 2024 ¶19"],
    },
    "ISA570.closeCall": {
        "current": ["ISA 570 (Revised) ¶20", "ISA 570 révisée ¶20"],
        "revised_2026": ["ISA 570 (Revised 2024) ¶20", "ISA 570 révisée 2024 ¶20"],
    },
    "ISA570.conclusions": {
        "current": ["ISA 570 (Revised) ¶21–24", "ISA 570 révisée ¶21–24"],
        "revised_2026": ["ISA 570 (Revised 2024) ¶21–24", "ISA 570 révisée 2024 ¶21–24"],
    },
    "ISA570.basis": {
        "current": ["ISA 570 (Revised) ¶21", "ISA 570 révisée ¶21"],
        "revised_2026": ["ISA 570 (Revised 2024) ¶21", "ISA 570 révisée 2024 ¶21"],
    },
    "ISA570.muSection": {
        "current": ["ISA 570 (Revised) ¶22", "ISA 570 révisée ¶22"],
        "revised_2026": ["ISA 570 (Revised 2024) ¶22", "ISA 570 révisée 2024 ¶22"],
    },
    "ISA570.muModified": {
        "current": ["ISA 570 (Revised) ¶23", "ISA 570 révisée ¶23"],
        "revised_2026": ["ISA 570 (Revised 2024) ¶23", "ISA 570 révisée 2024 ¶23"],
    },
    "ISA570.communicate": {
        "current": ["ISA 570 (Revised) ¶25", "ISA 570 révisée ¶25"],
        "revised_2026": ["ISA 570 (Revised 2024) ¶25", "ISA 570 révisée 2024 ¶25"],
    },
    "ISA570.horizon": {
        "current": [
            "at least twelve months from the date of the financial statements (ISA 570 (Revised) ¶13)",
            "au moins douze mois à compter de la date de clôture des états financiers (ISA 570 révisée ¶13)",
        ],
        "revised_2026": [
            "at least twelve months from the date of approval of the financial statements (ISA 570 (Revised 2024) ¶13)",
            "au moins douze mois à compter de la date d'approbation des états financiers (ISA 570 révisée 2024 ¶13)",
        ],
    },
    "ISA570.horizonClock": {
        "current": [
            "under the edition in force the period is measured from the balance sheet date; ISA 570 (Revised 2024), which measures it from the approval of the financial statements, applies to periods beginning on or after 15 December 2026, and a longer horizon is still examined where the facts call for it (¶15)",
            "selon l'édition en vigueur la période se mesure à partir de la date de clôture ; l'ISA 570 révisée 2024, qui la mesure à compter de l'approbation des états financiers, s'applique aux exercices ouverts à partir du 15 décembre 2026, et un horizon plus long reste examiné lorsque les faits l'exigent (¶15)",
        ],
        "revised_2026": [
            "the clock starts at approval, not at the period end, so a SYSCOHADA entity approving its accounts four to six months after the year end needs a forecast reaching sixteen to eighteen months past the balance sheet date",
            "le délai court à partir de l'approbation, non de la clôture, de sorte qu'une entité SYSCOHADA qui approuve ses comptes quatre à six mois après la clôture a besoin d'une prévision atteignant seize à dix-huit mois au-delà de la date du bilan",
        ],
    },
    "ISA570.horizonFrom": {
        "current": ["the date of the financial statements", "la date de clôture des états financiers"],
        "revised_2026": ["the date of approval of the financial statements", "la date d'approbation des états financiers"],
    },
}

ISA_REF_KEYS = list(REFS)

_PERIOD_END = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_TOKEN = re.compile(r"\{\{([A-Za-z0-9_.]+)\}\}")
# `key in REFS` also finds what every JavaScript object inherits
_INHERITED = {
    "constructor", "toString", "valueOf", "hasOwnProperty", "isPrototypeOf", "propertyIsEnumerable",
    "toLocaleString", "__proto__", "__defineGetter__", "__defineSetter__", "__lookupGetter__", "__lookupSetter__",
}


def is_standards_edition(value):
    return isinstance(value, str) and value in STANDARDS_EDITIONS


def period_start_of(period_end, duration_months=None):
    """The first day of the period: the day after the period end, less the duration,
    clamped to the target month's last day as Postgres does it."""
    match = _PERIOD_END.match(period_end)
    if not match:
        raise ServiceError("invalid-period-end")
    months = js_floor(duration_months) if duration_months and duration_months > 0 else 12
    year, month0, day = date_parts(date_utc(int(match.group(1)), int(match.group(2)) - 1, int(match.group(3)) + 1))
    t_year, t_month0, _ = date_parts(make_day(year, month0 - months, 1) * 86_400_000)
    last_day = date_parts(date_utc(t_year, t_month0 + 1, 0))[2]
    return to_iso_date(make_day(t_year, t_month0, min(day, last_day)) * 86_400_000)


def default_standards_edition(period_start):
    """The edition a period beginning on ``period_start`` (str or date) falls under."""
    if not period_start:
        return "current"
    iso = period_start[:10] if isinstance(period_start, str) else period_start.isoformat()[:10]
    return "revised_2026" if iso >= REVISED_2026_FROM else "current"


def edition_for_period(period_end, duration_months=None):
    return default_standards_edition(period_start_of(period_end, duration_months))


def edition_label(edition, locale):
    return _MESSAGES[locale][edition]


def edition_line(edition, locale):
    """"Standards edition: ISA in force": the header line of a paper or a workbook."""
    messages = _MESSAGES[locale]
    return "%s%s%s" % (messages["label"], " : " if locale == "fr" else ": ", messages[edition])


def isa_ref(edition, key, locale="en"):
    """The reference string for one requirement under one edition."""
    pair = REFS[key][edition]
    return pair[1] if locale == "fr" else pair[0]


def resolve_text(text, edition, locale):
    """Substitute every {{key}}. Unknown keys are left visible."""
    if "{{" not in text:
        return text

    def replace(match):
        key = match.group(1)
        if key in _INHERITED:
            # the source finds the inherited member, then fails reading its edition
            raise TypeError("Cannot read properties of undefined (reading '%s')" % ("1" if locale == "fr" else "0"))
        return isa_ref(edition, key, locale) if key in REFS else match.group(0)

    return _TOKEN.sub(replace, text)


def _lang_of(key):
    """Which language a paper property is written in, from its name: fr, srcFr, tipFr..."""
    return "fr" if key == "fr" or key.endswith("Fr") else "en"


def _resolve_value(value, edition, locale):
    if isinstance(value, str):
        return resolve_text(value, edition, locale)
    if isinstance(value, list):
        return [_resolve_value(v, edition, locale) for v in value]
    if isinstance(value, dict):
        return {k: _resolve_value(v, edition, _lang_of(k)) for k, v in value.items()}
    return value


def resolve_paper(definition, edition):
    """The paper as the engagement reads it. The source caches per definition so the
    wizard sees one stable object; nothing here depends on that, so no cache."""
    return _resolve_value(definition, edition, "en")


def has_unresolved_token(text):
    """True when a paper still carries a token: the test that guards the catalogue."""
    return _TOKEN.search(text) is not None
