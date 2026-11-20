"""EAGLR, Elite Advisors GL Review (owner's mock-ups "eaglr" and "gl-journal-types", 20/11/2026).

One page per engagement on the general ledger in use. Rows that already exist in another tool
are read from that tool (the model calls it); this file holds only what EAGLR adds: the journal
types a person gives each journal code, the description checks, the provisions pairing, the
accuracy of a reconciliation and the score. No Odoo, no database: the model reads the lines.

Descriptions are the client's own words, so the word lists below are French and English input
matched against them, never shown.
"""
import re
import unicodedata

from ._js import js_round, js_sum

# ---------------------------------------------------------------------------
# Journal types (step "Journal types (optional)" of a general ledger upload)
# ---------------------------------------------------------------------------

#: (key, English, French, class). "manual" entries are the ones section 3 reviews; "opening"
#: balances are neither manual nor automatic and stay out of the manual checks.
JOURNAL_TYPES = [
    ("sales", "Sales", "Ventes", "automatic"),
    ("purchases", "Purchases", "Achats", "automatic"),
    ("cash", "Cash", "Caisse", "automatic"),
    ("bank", "Bank", "Banque", "automatic"),
    ("fixed_assets", "Fixed assets", "Immobilisations", "automatic"),
    ("payroll", "Payroll", "Paie", "automatic"),
    ("manual", "Manual (miscellaneous)", "Manuel (opérations diverses)", "manual"),
    ("opening", "Opening balances", "À-nouveaux", "opening"),
]
TYPE_KEYS = [row[0] for row in JOURNAL_TYPES]
TYPE_CLASS = {row[0]: row[3] for row in JOURNAL_TYPES}

#: Usual journal codes of Cameroonian ledgers (Sage, Odoo, Excel). SAL is read as Sales: a payroll
#: journal is PAIE, PAY or SLR, never SAL, so the two never clash.
_SUGGESTED = {
    "sales": ("VTE", "VT", "VE", "VEN", "VENTE", "VENTES", "SAL", "SALES", "SJ"),
    "purchases": ("ACH", "AC", "HA", "PUR", "ACHAT", "ACHATS", "PURCHASES", "PJ"),
    "cash": ("CAI", "CA", "CSH", "CAISSE", "CASH", "CS"),
    "bank": ("BQ", "BNK", "BAN", "BQE", "BANK", "BANQUE", "BK"),
    "fixed_assets": ("IMMO", "IMM", "FA", "IMMOS", "IMMOBILISATIONS"),
    "payroll": ("PAIE", "PAY", "SLR", "PAYROLL", "SALAIRES", "PR"),
    "manual": ("OD", "MISC", "JNL", "ODV", "DIV", "GEN", "OPD", "OPERATIONS DIVERSES"),
    "opening": ("AN", "RAN", "OB", "ANO", "ANOUV", "OPEN", "OUV"),
}
_BY_CODE = {code: key for key, codes in _SUGGESTED.items() for code in codes}
_TRAILING = re.compile(r"[\s_\-./]*\d+$")


def suggest_type(code):
    """The journal type a code usually means, or None: "VTE" -> sales, "BQ2" -> bank."""
    text = str(code or "").strip().upper()
    if not text:
        return None
    if text in _BY_CODE:
        return _BY_CODE[text]
    bare = _TRAILING.sub("", text)
    if bare in _BY_CODE:
        return _BY_CODE[bare]
    # "BQ-SGBC", "CAISSE PRINCIPALE": a code of three letters or more that the code starts with
    for known in sorted(_BY_CODE, key=len, reverse=True):
        if (len(known) >= 3 or known == "BQ") and re.match(re.escape(known) + r"(?![A-Z])", bare):
            return _BY_CODE[known]
    return None


def clean_journal_types(raw):
    """{code: type} kept as given: codes trimmed, unknown types and empty choices dropped."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for code, kind in raw.items():
        text = str(code or "").strip()
        if text and kind in TYPE_CLASS:
            out[text] = kind
    return out


def codes_of(journal_types, wanted):
    """The codes whose type is of a class: "manual", "automatic" or "opening"."""
    return sorted(code for code, kind in clean_journal_types(journal_types).items() if TYPE_CLASS[kind] == wanted)


def has_types(journal_types):
    return bool(clean_journal_types(journal_types))


def type_label(key, locale):
    for row in JOURNAL_TYPES:
        if row[0] == key:
            return row[2] if locale == "fr" else row[1]
    return ""


# ---------------------------------------------------------------------------
# Description checks (section 2 and the information rows)
# ---------------------------------------------------------------------------

def fold(text):
    """Lower case, no accents, single spaces: how a description is compared with the lists."""
    plain = unicodedata.normalize("NFD", str(text or ""))
    plain = "".join(char for char in plain if not unicodedata.combining(char)).lower()
    return re.sub(r"\s+", " ", plain).strip()


def description(line_description, je_description):
    """The client's description of a line: its own, else the entry's. A leading quote that the
    projection adds to neutralise a spreadsheet formula is not part of it."""
    for text in (line_description, je_description):
        value = str(text or "").strip()
        if value.startswith("'"):
            value = value[1:].strip()
        if value:
            return value
    return ""


def _words(items):
    return re.compile(r"(?<![a-z0-9])(?:%s)(?![a-z0-9])" % "|".join(re.escape(fold(item)) for item in items))


PLACEHOLDERS_FR = [  # i18n: input
    "journal entry", "posting", "transaction", "auto", "n/a", "gl upload", "import", "écriture comptable",
    "saisie", "téléchargement", "opération", "libellé", "import batch", "ecriture",
]
_PLACEHOLDER = re.compile(
    r"^(?:%s)(?:\s*(?:n[o°]|#)?\s*[\w/-]*\d[\w/-]*)?$" % "|".join(re.escape(fold(item)) for item in PLACEHOLDERS_FR)
)
_PUNCTUATION = re.compile(r"^[\W_]+$")
_NUMERIC = re.compile(r"^[\d\s.,/\-]+$")
_YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
VAGUE_FR = [  # i18n: input
    "various", "sundry", "misc", "miscellaneous", "adjustment", "reclassification", "correction", "per management",
    "divers", "diverses", "autres", "régularisation", "ajustement", "reclassement", "rectification", "sur instruction",
    "à régulariser",
]
_VAGUE = _words(VAGUE_FR)
REVERSAL_FR = ("reversal", "reverse", "annul", "extourne", "contre-passation", "contrepassation", "contre passation")  # i18n: input
_ENTRY_NUMBER = re.compile(r"[A-Z]{1,5}/\d{2,4}/\d+|\d{4,}", re.IGNORECASE)
MONTHS_FR = [  # i18n: input, index + 1 is the month
    ("january", "janvier"), ("february", "fevrier"), ("march", "mars"), ("april", "avril"), ("may", "mai"),
    ("june", "juin"), ("july", "juillet"), ("august", "aout"), ("september", "septembre"), ("october", "octobre"),
    ("november", "novembre"), ("december", "decembre"),
]
_MONTH = re.compile(r"(?<![a-z])(%s)(?![a-z])" % "|".join(name for pair in MONTHS_FR for name in pair))
_MONTH_NUMBER = {name: index + 1 for index, pair in enumerate(MONTHS_FR) for name in pair}
PROVISIONAL_FR = ["estimated", "provisional", "tbc", "to be confirmed", "provisoire", "estimé", "à confirmer"]  # i18n: input
_PROVISIONAL = _words(PROVISIONAL_FR)
_ENCODING = re.compile("\\?{3,}|\ufffd|\u00c3[\u0080-\u00bf]|\u00c2[\u00a0-\u00bf]|\u00e2\u20ac")  # i18n: input
_CURRENCY = re.compile(r"(?<![A-Za-z])(USD|EUR|GBP|CAD|JPY|CHF|CNY)(?![A-Za-z])", re.IGNORECASE)
STOP_WORDS_FR = ["de la", "du", "des", "pour", "sur", "avec", "sans", "écriture", "paiement", "achat", "vente", "facture"]  # i18n: input
STOP_WORDS_EN = ["the", "and", "for", "from", "to", "invoice", "payment", "purchase", "sale", "reversal"]
_FRENCH = _words(STOP_WORDS_FR)
_ENGLISH = _words(STOP_WORDS_EN)
_TAX_PERIOD = re.compile(
    r"(?<!\d)(?:20\d{2}[-/.](?:0?[1-9]|1[0-2])|(?:0?[1-9]|1[0-2])[-/.]20\d{2})(?!\d)"
    r"|(?<![a-z])(?:q[1-4]|t[1-4]|trimestre|quarter)(?![a-z])"
)


def is_placeholder(text):
    """2.2 A system placeholder ("Import", "Saisie 2231", "/", "...") and nothing else."""
    folded = fold(text)
    return bool(folded) and bool(_PLACEHOLDER.match(folded) or _PUNCTUATION.match(folded))


def is_short(text):
    """2.3 Present but under ten characters, or figures only. A blank one is 2.1's."""
    stripped = str(text or "").strip()
    return bool(stripped) and (len(stripped) < 10 or bool(_NUMERIC.match(stripped)))


def wrong_year(text, posting_year):
    """2.6 Names a year, and none of the years named is the posting year."""
    years = {int(found) for found in _YEAR.findall(str(text or ""))}
    return bool(years) and posting_year is not None and posting_year not in years


def is_vague(text):
    """2.8 "Divers", "régularisation", "adjustment" and the like."""
    return bool(_VAGUE.search(fold(text)))


def reversal_without_reference(text):
    """2.16 Starts as a reversal and names no entry number (AB/2025/12, or four digits or more)."""
    folded = fold(text)
    return folded.startswith(REVERSAL_FR) and not _ENTRY_NUMBER.search(str(text or ""))


def wrong_month(text, posting_month):
    """2.18 Names a month, and none of the months named is the posting month."""
    months = {_MONTH_NUMBER[name] for name in _MONTH.findall(fold(text))}
    return bool(months) and posting_month is not None and posting_month not in months


def is_provisional(text):
    """2.19 "Provisoire", "à confirmer", "estimated" on a posted entry."""
    return bool(_PROVISIONAL.search(fold(text)))


def has_encoding_error(text):
    """2.14/2.15 "???", the replacement character, or "Ã©"-style garbling from a wrong import."""
    return bool(_ENCODING.search(str(text or "")))


def names_currency(text):
    """Information: a currency code in the description."""
    return bool(_CURRENCY.search(str(text or "")))


def mixed_languages(text):
    """Information: French and English stop-words in one description."""
    folded = fold(text)
    return bool(_FRENCH.search(folded)) and bool(_ENGLISH.search(folded))


def tax_without_period(account, text):
    """Information: a tax account (44) whose description names no period (month, quarter, YYYY-MM)."""
    if not str(account or "").startswith("44"):
        return False
    folded = fold(text)
    return not (_TAX_PERIOD.search(folded) or _MONTH.search(folded))


def normalised(text):
    """The description as the naming check compares it: lower case, letters and figures only."""
    return re.sub(r"[^a-z0-9]", "", fold(text))


#: The checks a line's description is put through, in the order of the page.
DESCRIPTION_CHECKS = ("2.2", "2.3", "2.6", "2.8", "2.14", "2.16", "2.18", "2.19")
TEXT_INFO_CHECKS = ("i.currency", "i.languages")


def description_flags(text, posting_date):
    """The description checks a line fails. ``posting_date`` is a date or None."""
    flags = []
    if not text:
        return flags
    year = posting_date.year if posting_date else None
    month = posting_date.month if posting_date else None
    if is_placeholder(text):
        flags.append("2.2")
    if is_short(text):
        flags.append("2.3")
    if wrong_year(text, year):
        flags.append("2.6")
    if is_vague(text):
        flags.append("2.8")
    if has_encoding_error(text):
        flags.append("2.14")
    if reversal_without_reference(text):
        flags.append("2.16")
    if wrong_month(text, month):
        flags.append("2.18")
    if is_provisional(text):
        flags.append("2.19")
    if names_currency(text):
        flags.append("i.currency")
    if mixed_languages(text):
        flags.append("i.languages")
    return flags


# ---------------------------------------------------------------------------
# Manual entries and provisions (section 3)
# ---------------------------------------------------------------------------

def manual_check(account):
    """Which of 3.2 to 3.5 a line of a manual journal falls in, or None."""
    code = str(account or "")
    if code.startswith("5") and not code.startswith("58"):
        return "3.2"
    if code[:2] in ("20", "21", "22", "23", "24", "28", "68"):
        return "3.3"
    if code.startswith("3") and not code.startswith("39"):
        return "3.4"
    if code[:2] in ("40", "41"):
        return "3.5"
    return None


PROVISION_PREFIXES = ("19", "29", "39", "49", "59")
#: A provision credited is charged to 69, 659 or 85 (HAO); one debited is released to 79, 759 or 86.
CHARGE_PREFIXES = ("69", "659", "85")
RELEASE_PREFIXES = ("79", "759", "86")


def is_provision(account):
    return str(account or "").startswith(PROVISION_PREFIXES)


def provision_exceptions(lines):
    """3.8 The provision lines whose entry lacks the counter-leg. ``lines``: the lines of the
    entries touching a provision account, each {id, je, account, debit, credit}. Returns the ids."""
    by_entry = {}
    for line in lines:
        by_entry.setdefault(line["je"], []).append(line)
    flagged = []
    for entry_lines in by_entry.values():
        charged = any(str(l["account"]).startswith(CHARGE_PREFIXES) and (l["debit"] or 0) > (l["credit"] or 0) for l in entry_lines)
        released = any(str(l["account"]).startswith(RELEASE_PREFIXES) and (l["credit"] or 0) > (l["debit"] or 0) for l in entry_lines)
        for line in entry_lines:
            if not is_provision(line["account"]):
                continue
            net = (line["debit"] or 0) - (line["credit"] or 0)
            if (net < 0 and not charged) or (net > 0 and not released):
                flagged.append(line["id"])
    return flagged


def implied_rate(loans, interest):
    """3.7 Interest of the year as a percentage of the loans outstanding, or None."""
    if not loans or abs(loans) < 0.01:
        return None
    return _r(abs(interest or 0) / abs(loans) * 100, 2)


# ---------------------------------------------------------------------------
# Accuracy and score
# ---------------------------------------------------------------------------

PASS_MARK = 96.0


def _r(value, places):
    scale = 10 ** places
    return js_round(value * scale) / scale


PASSED, EXCEPTIONS, NOT_RUN, INFORMATION, NOT_APPLICABLE = "passed", "exceptions", "not_run", "information", "not_applicable"
#: The section numbers, in the order of the score box.
SECTIONS = ("1", "2", "3", "4")


def accuracy(left, right):
    """100 - min(100, |left - right| / max(|left|, |right|, 0.01) x 100), to two decimals."""
    left, right = float(left or 0), float(right or 0)
    if abs(left) < 0.01 and abs(right) < 0.01:
        return 100.0
    gap = abs(left - right) / max(abs(left), abs(right), 0.01) * 100
    return _r(100 - min(100.0, gap), 2)


def section_score(section, rows):
    """A section's score, or None when no check of it could be applied. Section 1 is the average
    accuracy of the reconciliations that ran; the others passed / applicable x 100. A check that
    could not run, or that is information only, counts for nothing either way."""
    applied = [row for row in rows if row["status"] in (PASSED, EXCEPTIONS)]
    if not applied:
        return None
    if section == "1":
        values = [row["accuracy"] for row in applied if row.get("accuracy") is not None]
        return _r(js_sum(values) / len(values), 1) if values else None
    return _r(len([row for row in applied if row["status"] == PASSED]) / len(applied) * 100, 1)


def overall_score(scores):
    """The average of the section scores that exist, or None."""
    found = [value for value in scores.values() if value is not None]
    return _r(js_sum(found) / len(found), 1) if found else None


def score_summary(rows):
    """{sections: {number: score}, overall, passed} from the rows of the page."""
    sections = {
        number: section_score(number, [row for row in rows if row["section"] == number]) for number in SECTIONS
    }
    overall = overall_score(sections)
    return {"sections": sections, "overall": overall, "passMark": PASS_MARK,
            "passed": None if overall is None else overall >= PASS_MARK}


def count_status(count):
    return EXCEPTIONS if count else PASSED
