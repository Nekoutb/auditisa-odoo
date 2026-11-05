"""lib/je-selection.ts: the risk-directed selection of the journal-entry lines to test (ISA 240 ¶32).

The unit is the line: a line caught by four criteria appears once with four reasons. SQL narrows,
this module decides; the model holds the query. The catalogue is data, in je_catalogue.py.
"""
import re
import unicodedata

from ._js import is_finite, js_number_str, js_round, js_str, js_trim, locale_compare, u16_len, u16_slice, weekday, date_utc
from .errors import ServiceError
from .gl_line import TOLERANCE, nf
from .je_catalogue import CLASS_LABEL, JE_CRITERIA, PAIRINGS, RULE_FIELDS, RULE_OPERATOR_LABELS, RULE_OPERATORS
from .lead_classes import LEAD_INDEX_BY_CODE, lead_index_for

SELECTION_CAP = 500
DEFAULT_SELECTION_LIMIT = 200
CANDIDATE_CEILING = 20000

PAIRING_BY_KEY = {pairing["key"]: pairing for pairing in PAIRINGS}
CRITERION_BY_KEY = {criterion["key"]: criterion for criterion in JE_CRITERIA}
RULE_FIELD_BY_KEY = {field["key"]: field for field in RULE_FIELDS}
_DEFAULT_TERMS = next(param for param in CRITERION_BY_KEY["incomplete-description"]["params"] if param["key"] == "uninformativeTerms")["default"]

_ISO_DATE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
_COUNTRY = re.compile(r"^[A-Za-z]{2}$")
_NO_VALUE = ("isEmpty", "isNotEmpty")
_ID_CLEAN = re.compile(r"[^A-Za-z0-9_-]")
_COMBINING = re.compile("[̀-ͯ]")
_LETTERS = re.compile(r"[^\W\d_]+")
_SPACES = re.compile(r"\s+")
DAY_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def t(locale, en, fr):
    return fr if locale == "fr" else en


def selection_class_for(account_or_prefix):
    """The grouping an account or prefix belongs to, derived from the lead-class map; None when none."""
    index = lead_index_for(account_or_prefix)
    definition = LEAD_INDEX_BY_CODE.get(index) if index else None
    if not definition:
        return None
    account_class = definition["accountClass"]
    if account_class == "Revenue":
        return "Revenue"
    if account_class == "Cash":
        return "Cash"
    if account_class == "Fixed Assets":
        return "FixedAssets"
    if account_class == "Inventory":
        return "Inventory"
    return "Expense" if definition["accountType"] == "Expenses" else None


def build_class_cover():
    """Every numeric prefix up to three digits, kept only where it says something its parent did
    not. The null entries matter: 28 is fixed assets but 281 is amortisation."""
    cover = []
    resolved = {}
    for length in (1, 2, 3):
        for number in range(0 if length == 1 else 10 ** (length - 1), 10 ** length):
            prefix = str(number).rjust(length, "0")
            klass = selection_class_for(prefix)
            parent = None if length == 1 else resolved.get(prefix[: length - 1])
            resolved[prefix] = klass
            if klass != parent:
                cover.append({"prefix": prefix, "klass": klass})
    return cover


CLASS_PREFIXES = build_class_cover()


def _coerce_rule_value(kind, raw):
    if raw is None:
        return None
    if kind == "number":
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            return raw if is_finite(raw) else None
        try:
            number = float(js_str(raw).replace(",", ".", 1).strip() or "0")
        except ValueError:
            return None
        if not is_finite(number):
            return None
        return int(number) if number == int(number) else number
    text = js_trim(js_str(raw))
    if not text:
        return None
    if kind == "date":
        return text if _ISO_DATE.match(text) else None
    return u16_slice(text, 0, 200).lower()


def normalise_user_rule(rule, index):
    """A rule whose operator does not fit its field is refused: it would select nothing, and a paper
    saying "no exceptions" because the rule was nonsense is worse than an error."""
    field = RULE_FIELD_BY_KEY.get(js_str(rule.get("field") if rule.get("field") is not None else ""))
    if not field:
        raise ServiceError("invalid-rule-field")
    operator = rule.get("operator")
    if operator not in RULE_OPERATORS[field["type"]]:
        raise ServiceError("invalid-rule-operator")
    value = value2 = None
    if operator not in _NO_VALUE:
        value = _coerce_rule_value(field["type"], rule.get("value"))
        if value is None:
            raise ServiceError("invalid-rule-value")
        if operator == "between":
            value2 = _coerce_rule_value(field["type"], rule.get("value2"))
            if value2 is None:
                raise ServiceError("invalid-rule-value")
    cleaned = _ID_CLEAN.sub("", u16_slice(js_trim(js_str(rule.get("id") if rule.get("id") is not None else "")), 0, 40))
    rule_id = cleaned or "r%d" % (index + 1)

    def shown(item):
        return "" if item is None else js_str(item)

    tail = "%s … %s" % (shown(value), shown(value2)) if operator == "between" else shown(value)
    labels = RULE_OPERATOR_LABELS[operator]
    return {
        "key": "user:%s" % rule_id, "field": field, "operator": operator, "value": value, "value2": value2,
        "labelEn": js_trim(rule.get("labelEn") or "") or js_trim("%s %s %s" % (field["labelEn"], labels["en"], tail)),
        "labelFr": js_trim(rule.get("labelFr") or "") or js_trim("%s %s %s" % (field["labelFr"], labels["fr"], tail)),
    }


def _clamp_number(value, low, high, fallback):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if not is_finite(number):
        return fallback
    number = min(high, max(low, number))
    return int(number) if number == int(number) else number


def _clamp_int(value, low, high, fallback):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if not is_finite(number):
        return fallback
    return min(high, max(low, js_round(number)))


def _term_ok(term):
    return 1 <= len(term) <= 40 and all(c.isalpha() or c.isnumeric() or c in "'-" for c in term)


def expand_terms(terms):
    """Accented and unaccented spellings both count; the pair is built here so that the narrowing
    SQL and this module test exactly the same list."""
    out = {}
    for raw in terms:
        term = u16_slice(js_trim(js_str(raw)).lower(), 0, 40)
        if not _term_ok(term):
            continue
        out[term] = True
        out[_COMBINING.sub("", unicodedata.normalize("NFD", term))] = True
    return list(out)[:200]


def resolve_settings(params=None):
    """Every threshold clamped to a range it can be defended in, never taken raw from the request."""
    params = params or {}
    raw_pairings = params.get("pairings")
    pairings = [key for key in raw_pairings if key in PAIRING_BY_KEY] if isinstance(raw_pairings, list) else []
    country = js_str(params.get("country") if params.get("country") is not None else "")
    terms = params.get("uninformativeTerms")
    terms = terms if isinstance(terms, list) and terms else _DEFAULT_TERMS
    return {
        "dateBasis": "entry" if params.get("dateBasis") == "entry" else "journal",
        "country": country.upper() if _COUNTRY.match(country) else "CM",
        "roundMin": _clamp_number(params.get("roundMin"), 1, 1e15, 100000),
        "roundStep": _clamp_number(params.get("roundStep"), 1, 1e15, 100000),
        "pairings": list(dict.fromkeys(pairings)) if pairings else [pairing["key"] for pairing in PAIRINGS],
        "topEntries": _clamp_int(params.get("topEntries"), 1, 100, 5),
        "yearEndDays": _clamp_int(params.get("yearEndDays"), 1, 90, 15),
        "volumeBasis": "value" if params.get("volumeBasis") == "value" else "lines",
        "minDescriptionChars": _clamp_int(params.get("minDescriptionChars"), 1, 200, 10),
        "minDescriptionWords": _clamp_int(params.get("minDescriptionWords"), 1, 20, 2),
        "uninformativeTerms": expand_terms(terms),
    }


def iso_weekday(date):
    """ISO weekday (1 = Monday, 7 = Sunday) of a YYYY-MM-DD date, or None."""
    if not date or not _ISO_DATE.match(date):
        return None
    day = weekday(date_utc(int(date[:4]), int(date[5:7]) - 1, int(date[8:10])))
    return 7 if day == 0 else day


def description_of(line):
    """The line's own description, falling back to the entry's."""
    return js_trim(line.get("lineDescription") or "") or js_trim(line.get("jeDescription") or "")


def is_incomplete_description(description, settings):
    """Present but uninformative: too short, too few words, or nothing but filler."""
    if not description:
        return False
    if u16_len(description) < settings["minDescriptionChars"]:
        return True
    if len([word for word in _SPACES.split(description) if word]) < settings["minDescriptionWords"]:
        return True
    tokens = _LETTERS.findall(description.lower())
    return not tokens or all(token in settings["uninformativeTerms"] for token in tokens)


def is_round_amount(signed, settings):
    """Round when it clears the floor and divides exactly by the step, judged at six decimals."""
    amount = abs(signed)
    if amount < settings["roundMin"]:
        return False
    return js_round((amount % settings["roundStep"]) * 1e6) / 1e6 == 0


def _person(value):
    return js_trim(value or "").lower()


_RULE_VALUE = {
    "account": "account", "accountName": "accountName", "jeNumber": "jeNumber", "journalCode": "journalCode",
    "jeDescription": "jeDescription", "lineDescription": "lineDescription", "reference": "reference",
    "thirdPartyCode": "thirdPartyCode", "thirdPartyName": "thirdPartyName", "preparer": "preparer", "reviewer": "reviewer",
    "approver": "approver", "costCenter": "costCenter", "journalDate": "journalDate", "entryDate": "entryDate",
    "debit": "debit", "credit": "credit", "signed": "signed", "lineNo": "lineNo",
}


def _rule_value_of(line, field):
    if field == "absAmount":
        return abs(line["signed"])
    return line.get(_RULE_VALUE.get(field, ""))


def matches_user_rule(line, rule):
    raw = _rule_value_of(line, rule["field"]["key"])
    operator = rule["operator"]
    if operator == "isEmpty":
        return raw is None or js_trim(js_str(raw)) == ""
    if operator == "isNotEmpty":
        return raw is not None and js_trim(js_str(raw)) != ""
    if raw is None:
        return False
    kind = rule["field"]["type"]
    if kind == "number":
        actual, expected = float(raw), float(rule["value"])
        if operator == "equals":
            return abs(actual - expected) <= TOLERANCE
        if operator == "notEquals":
            return abs(actual - expected) > TOLERANCE
        if operator == "greaterThan":
            return actual > expected
        if operator == "greaterOrEqual":
            return actual >= expected
        if operator == "lessThan":
            return actual < expected
        if operator == "lessOrEqual":
            return actual <= expected
        if operator == "between":
            other = float(rule["value2"])
            return min(expected, other) <= actual <= max(expected, other)
        return False
    if kind == "date":
        actual, expected = js_str(raw), js_str(rule["value"])
        if operator == "equals":
            return actual == expected
        if operator == "before":
            return actual < expected
        if operator == "after":
            return actual > expected
        if operator == "between":
            other = js_str(rule.get("value2") or "")
            low, high = (expected, other) if expected <= other else (other, expected)
            return low <= actual <= high
        return False
    actual, expected = js_trim(js_str(raw)).lower(), js_str(rule["value"])
    if operator == "equals":
        return actual == expected
    if operator == "notEquals":
        return actual != expected
    if operator == "contains":
        return expected in actual
    if operator == "notContains":
        return expected not in actual
    if operator == "startsWith":
        return actual.startswith(expected)
    if operator == "endsWith":
        return actual.endswith(expected)
    return False


def reasons_for(line, ctx):
    """Every reason one line was selected, in catalogue order: the only definition of each criterion."""
    locale, settings = ctx["locale"], ctx["settings"]
    chosen = set(ctx["criteria"])
    reasons = []

    def name(key):
        return t(locale, CRITERION_BY_KEY[key]["nameEn"], CRITERION_BY_KEY[key]["nameFr"])

    entry_basis = settings["dateBasis"] == "entry"
    tested = line.get("entryDate") if entry_basis else line.get("journalDate")
    date_word = t(locale, "entry date" if entry_basis else "journal date", "date de saisie" if entry_basis else "date de journal")
    if "weekend-posting" in chosen:
        day = iso_weekday(tested)
        if day in (6, 7):
            reasons.append({
                "criterion": "weekend-posting", "label": name("weekend-posting"),
                "detail": t(locale, "%s %s falls on a %s" % (date_word, tested, DAY_EN[day - 1]), "%s %s : un %s" % (date_word, tested, DAY_FR[day - 1])),
            })
    description = description_of(line)
    if "no-description" in chosen and description == "":
        reasons.append({
            "criterion": "no-description", "label": name("no-description"),
            "detail": t(locale, "neither the entry nor the line carries a description", "ni l'écriture ni la ligne ne portent de libellé"),
        })
    if "public-holiday" in chosen and tested:
        holiday = ctx["holidays"].get(tested)
        if holiday:
            origin = t(locale, "firm calendar", "calendrier du cabinet") if holiday["origin"] == "firm" else t(locale, "national calendar", "calendrier national")
            reasons.append({
                "criterion": "public-holiday", "label": name("public-holiday"),
                "detail": t(
                    locale,
                    "%s %s is %s in %s (%s)" % (date_word, tested, holiday["labelEn"], settings["country"], origin),
                    "%s %s : %s au %s (%s)" % (date_word, tested, holiday["labelFr"], settings["country"], origin),
                ),
            })
    if "round-amount" in chosen and is_round_amount(line["signed"], settings):
        amount, step = js_number_str(abs(line["signed"])), js_number_str(settings["roundStep"])
        reasons.append({
            "criterion": "round-amount", "label": name("round-amount"),
            "detail": t(locale, "%s is an exact multiple of %s" % (amount, step), "%s est un multiple exact de %s" % (amount, step)),
        })
    if "unusual-pairing" in chosen:
        present = set(line["entry"]["classes"])
        for key in settings["pairings"]:
            pairing = PAIRING_BY_KEY.get(key)
            if not pairing or pairing["left"] not in present or pairing["right"] not in present:
                continue
            left, right = CLASS_LABEL[pairing["left"]], CLASS_LABEL[pairing["right"]]
            reasons.append({
                "criterion": "unusual-pairing", "label": t(locale, pairing["labelEn"], pairing["labelFr"]),
                "detail": t(
                    locale,
                    "entry %s touches %s and %s together — %s" % (line["jeNumber"], left["en"], right["en"], pairing["whyEn"]),
                    "l'écriture %s mouvemente ensemble %s et %s — %s" % (line["jeNumber"], left["fr"], right["fr"], pairing["whyFr"]),
                ),
            })
    rank = line["entry"].get("yearEndRank")
    if "year-end-volume" in chosen and rank is not None:
        gross = js_number_str(line["entry"]["grossValue"])
        count = line["entry"]["lines"]
        measure = (
            t(locale, "gross value %s" % gross, "valeur brute %s" % gross) if settings["volumeBasis"] == "value"
            else t(locale, "%s lines" % count, "%s lignes" % count)
        )
        reasons.append({
            "criterion": "year-end-volume", "label": name("year-end-volume"),
            "detail": t(
                locale,
                "entry %s ranks %s of the %s largest in the last %s days of the period (%s)" % (line["jeNumber"], rank, settings["topEntries"], settings["yearEndDays"], measure),
                "l'écriture %s occupe le rang %s des %s plus importantes des %s derniers jours de la période (%s)" % (line["jeNumber"], rank, settings["topEntries"], settings["yearEndDays"], measure),
            ),
        })
    if "incomplete-description" in chosen and is_incomplete_description(description, settings):
        reasons.append({
            "criterion": "incomplete-description", "label": name("incomplete-description"),
            "detail": t(
                locale,
                '"%s" does not meet the stated minimum of %s characters and %s informative words' % (description, settings["minDescriptionChars"], settings["minDescriptionWords"]),
                "« %s » n'atteint pas le minimum retenu de %s caractères et %s mots porteurs de sens" % (description, settings["minDescriptionChars"], settings["minDescriptionWords"]),
            ),
        })
    for key, other, en, fr in (
        ("preparer-is-reviewer", "reviewer", "%s both recorded and reviewed this line", "%s a saisi et revu cette ligne"),
        ("preparer-is-approver", "approver", "%s both recorded and approved this line", "%s a saisi et approuvé cette ligne"),
    ):
        if key in chosen:
            preparer = _person(line.get("preparer"))
            if preparer and preparer == _person(line.get(other)):
                reasons.append({"criterion": key, "label": name(key), "detail": t(locale, en % line["preparer"], fr % line["preparer"])})
    all_rules = ctx.get("userRulesMode") == "all"
    every = all_rules and all(matches_user_rule(line, rule) for rule in ctx["userRules"])
    for rule in ctx["userRules"]:
        if (not every) if all_rules else not matches_user_rule(line, rule):
            continue
        reasons.append({
            "criterion": rule["key"], "label": t(locale, rule["labelEn"], rule["labelFr"]),
            "detail": t(locale, "the auditor's own rule: %s" % rule["labelEn"], "règle propre à l'auditeur : %s" % rule["labelFr"]),
        })
    return reasons


def _compare(a, b):
    difference = len(b["reasons"]) - len(a["reasons"])
    if difference:
        return difference
    if abs(b["signed"]) != abs(a["signed"]):
        return 1 if abs(b["signed"]) > abs(a["signed"]) else -1
    order = locale_compare(a.get("journalDate") or "9999-12-31", b.get("journalDate") or "9999-12-31")
    if order:
        return order
    order = locale_compare(a["jeNumber"], b["jeNumber"])
    return order or a["lineNo"] - b["lineNo"]


def select_from_candidates(candidates, ctx):
    """Attach the reasons, drop what no criterion claims, and put the line caught most ways first."""
    from functools import cmp_to_key

    lines, coverage, entries_by_criterion, selected_entries = [], {}, {}, set()
    for candidate in candidates:
        reasons = reasons_for(candidate, ctx)
        if not reasons:
            continue
        line = {key: value for key, value in candidate.items() if key != "entry"}
        line.update({
            "accountClass": selection_class_for(candidate["account"]), "entryLines": candidate["entry"]["lines"],
            "entryGrossValue": candidate["entry"]["grossValue"], "reasons": reasons,
        })
        lines.append(line)
        selected_entries.add(candidate["jeNumber"])
        for key in dict.fromkeys(reason["criterion"] for reason in reasons):
            tally = coverage.setdefault(key, {"lines": 0, "entries": 0})
            tally["lines"] += 1
            entries_by_criterion.setdefault(key, set()).add(candidate["jeNumber"])
    for key, entries in entries_by_criterion.items():
        coverage[key]["entries"] = len(entries)
    lines.sort(key=cmp_to_key(_compare))
    return {"lines": lines, "selectedLines": len(lines), "selectedEntries": len(selected_entries), "coverage": coverage}


def coverage_of(criteria, user_rules, settings, core, locale):
    rows = []
    for key in criteria:
        definition = CRITERION_BY_KEY[key]
        tally = core["coverage"].get(key, {"lines": 0, "entries": 0})
        rows.append({
            "key": key, "name": t(locale, definition["nameEn"], definition["nameFr"]),
            "description": t(locale, definition["descriptionEn"], definition["descriptionFr"]),
            "settings": {param["key"]: settings.get(param["key"]) for param in definition["params"]},
            "matchedLines": tally["lines"], "matchedEntries": tally["entries"],
        })
    custom = CRITERION_BY_KEY["user-defined"]
    for rule in user_rules:
        tally = core["coverage"].get(rule["key"], {"lines": 0, "entries": 0})
        rows.append({
            "key": rule["key"], "name": t(locale, rule["labelEn"], rule["labelFr"]),
            "description": t(locale, custom["descriptionEn"], custom["descriptionFr"]),
            "settings": {"field": rule["field"]["key"], "operator": rule["operator"]},
            "matchedLines": tally["lines"], "matchedEntries": tally["entries"],
        })
    return rows


def filler_regex(terms):
    """A description of nothing but filler terms, figures and punctuation. Terms are escaped."""
    escaped = "|".join(re.sub(r"([.*+?^${}()|\[\]\\/-])", r"\\\1", term) for term in terms)
    gap = "[^[:alpha:]]"
    return "^%s*(%s)(%s+(%s))*%s*$" % (gap, escaped, gap, escaped, gap)


def describe_selection_design(design, locale, when=""):
    """One design as the S5.4 paper prints it: criteria by name with their thresholds, the rules,
    the size of the selection, who recorded it and when (UAT B133)."""
    fr = locale == "fr"
    settings = resolve_settings(design.get("params") or {})
    colon = " : " if fr else ": "
    criteria = []
    for key in design.get("criteria") or []:
        definition = CRITERION_BY_KEY.get(key)
        if not definition:
            criteria.append(key)
            continue
        parts = []
        for param in definition["params"]:
            label = param["labelFr" if fr else "labelEn"]
            if param["kind"] == "multi":
                raw = (design.get("params") or {}).get(param["key"])
                items = raw if isinstance(raw, list) and raw else param["default"]
                if param["key"] == "pairings":
                    items = [PAIRING_BY_KEY[pair]["labelFr" if fr else "labelEn"] for pair in settings["pairings"]]
                parts.append("%s%s%s" % (label, colon, ", ".join(items)))
                continue
            value = settings.get(param["key"])
            if param["kind"] == "choice":
                option = next((o for o in param.get("options") or [] if o["value"] == value), None)
                parts.append("%s%s%s" % (label, colon, option["labelFr" if fr else "labelEn"] if option else js_str(value)))
            elif isinstance(value, (int, float)):
                shown = nf(value).replace(",", " ") if fr else nf(value)
                parts.append("%s%s%s" % (label, colon, shown))
            else:
                parts.append("%s%s%s" % (label, colon, js_str(value if value is not None else "")))
        name = definition["nameFr" if fr else "nameEn"]
        criteria.append("%s (%s)" % (name, " ; ".join(parts)) if parts else name)
    rules = []
    for index, rule in enumerate(design.get("userRules") or []):
        try:
            rules.append(normalise_user_rule(rule, index)["labelFr" if fr else "labelEn"])
        except ServiceError:
            rules.append("règle invalide" if fr else "invalid rule")
    criteria_text = " · ".join(criteria) or "—"
    joined = (" (toutes les conditions)" if fr else " (all conditions)") if design.get("userRulesMode") == "all" and len(rules) > 1 else ""
    rules_text = "%d%s — %s" % (len(rules), joined, " ; ".join(rules)) if rules else "0"
    selected, population = design.get("selectedLines") or 0, design.get("populationLines") or 0
    by = design.get("recordedBy") or "—"
    if fr:
        return "Critères : %s · règles : %s · %s ligne(s) sélectionnée(s) sur %s · par %s le %s" % (criteria_text, rules_text, selected, population, by, when)
    return "Criteria: %s · rules: %s · %s line(s) selected of %s · by %s on %s" % (criteria_text, rules_text, selected, population, by, when)

