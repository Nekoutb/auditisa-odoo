"""Journal entry testing (ISA 240; owner's mock-up approved 18/11). No Odoo import.

The ledger is read once per entry (models/je_testing.py: one GROUP BY over the lines, the same
facts as ``entry_facts`` below builds from lines); every criterion is then a plain function of
those facts and of the counts over the whole ledger (who posts how often, how many entries use
each account), so the criteria cost one pass over the entries, not one query each.

An entry's facts: ``je``, ``date`` (yyyy-mm-dd, the earliest journal date of its lines),
``journal``, ``description``, ``preparer``, ``approver``, ``amount`` (total of its debits),
``debits`` and ``credits`` (the accounts debited and credited), ``next`` (true for an entry of the
subsequent-period ledger: only the two after-year-end criteria read those).

The selection is every entry found by at least one criterion. Ticking criteria narrows what is
shown to the entries those criteria find (a union); nothing ticked shows the whole selection.
"""
import re
import unicodedata

from .je_selection import iso_weekday

_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_WORDS = re.compile(r"[a-z0-9]+")

GROUPS = [
    {"key": "when", "en": "When it was posted", "fr": "Quand elle a été passée"},
    {"key": "who", "en": "Who posted it", "fr": "Qui l'a passée"},
    {"key": "what", "en": "What it says", "fr": "Ce qu'elle indique"},
    {"key": "pairing", "en": "Unusual account pairings", "fr": "Associations de comptes inhabituelles"},
]

#: The criteria in the order of the screen, with the owner's numbers.
CRITERIA = [
    {"key": "sunday", "no": "1", "group": "when", "en": "Posted on a Sunday", "fr": "Passée un dimanche"},
    {"key": "saturday", "no": "2", "group": "when", "en": "Posted on a Saturday", "fr": "Passée un samedi"},
    {"key": "holiday", "no": "3", "group": "when", "en": "Posted on a public holiday", "fr": "Passée un jour férié"},
    {"key": "year-end", "no": "9", "group": "when",
     "en": "Last %(n)s days of the year or first %(n)s days after", "fr": "%(n)s derniers jours de l'exercice ou %(n)s premiers jours suivants"},
    {"key": "same-person", "no": "4", "group": "who", "en": "Same person prepared and approved", "fr": "Même personne pour la préparation et l'approbation"},
    {"key": "no-approver", "no": "5", "group": "who", "en": "No approver recorded", "fr": "Aucun approbateur enregistré"},
    {"key": "rare-poster", "no": "6", "group": "who", "en": "Posted by a person who rarely posts entries", "fr": "Passée par une personne qui passe rarement des écritures"},
    {"key": "round", "no": "7", "group": "what", "en": "Round amounts", "fr": "Montants ronds"},
    {"key": "below-limit", "no": "8", "group": "what", "en": "Just below an approval limit", "fr": "Juste sous un seuil d'approbation"},
    {"key": "vague", "no": "10", "group": "what", "en": "Missing or vague description", "fr": "Libellé absent ou vague"},
    {"key": "rare-account", "no": "11", "group": "what", "en": "Rarely used or suspense accounts", "fr": "Comptes rarement utilisés ou d'attente"},
    {"key": "revenue-cash", "no": "12", "group": "pairing", "en": "Revenue against cash", "fr": "Produits contre trésorerie"},
    {"key": "cash-expense", "no": "13", "group": "pairing", "en": "Expenses paid in cash above a limit", "fr": "Charges payées en espèces au-delà d'un seuil"},
    {"key": "assets-revenue", "no": "14", "group": "pairing", "en": "Fixed assets against revenue", "fr": "Immobilisations contre produits"},
    {"key": "payables-receivables", "no": "15", "group": "pairing", "en": "Payables against receivables", "fr": "Fournisseurs contre clients"},
    {"key": "revenue-after", "no": "15a", "group": "pairing", "en": "Revenue debited after year end", "fr": "Produits débités après la clôture"},
    {"key": "equity-result", "no": "15b", "group": "pairing", "en": "Equity against income or expense", "fr": "Capitaux propres contre produits ou charges"},
]
CRITERION_KEYS = [c["key"] for c in CRITERIA]
#: What an entry of the subsequent-period ledger can be found by.
AFTER_YEAR_END = ("year-end", "revenue-after")

DEFAULT_VAGUE_WORDS = [
    "divers", "diverses", "od", "operation diverse", "operations diverses", "regul", "regularisation", "ajustement",
    "correction", "extourne", "ecriture", "misc", "miscellaneous", "various", "adjustment", "correction", "entry", "test", "xxx",
]
DEFAULTS = {
    "roundStep": 1000000.0,
    "approvalLimit": 5000000.0,
    "approvalBand": 10.0,
    "cashLimit": 500000.0,
    "yearEndDays": 5,
    "rarePosterShare": 2.0,
    "rareAccountEntries": 3,
    "vagueMinChars": 4,
    "vagueWords": DEFAULT_VAGUE_WORDS,
}

#: The four questions of a test, each Yes / No / Not applicable.
ATTRIBUTES = [
    {"key": "attr_document", "en": "Supporting document obtained and agreed to the entry (amount, date, accounts)",
     "fr": "Pièce justificative obtenue et rapprochée de l'écriture (montant, date, comptes)"},
    {"key": "attr_approval", "en": "Entry approved by an appropriate person, other than its preparer",
     "fr": "Écriture approuvée par une personne habilitée, autre que celle qui l'a préparée"},
    {"key": "attr_reason", "en": "Business reason understood and consistent with our knowledge of the entity",
     "fr": "Justification économique comprise et cohérente avec notre connaissance de l'entité"},
    {"key": "attr_recording", "en": "Recorded in the right accounts, period and amount",
     "fr": "Enregistrée dans les bons comptes, sur la bonne période et pour le bon montant"},
]
ANSWERS = ("yes", "no", "na")
#: The stored status of a review (since 2026-11-16) read as the test's conclusion.
LEGACY_STATUS = {"to_clear": "to_test", "cleared": "no_exception", "problem": "exception"}
STATUS_LABELS = {
    "to_test": {"en": "To test", "fr": "À tester"},
    "no_exception": {"en": "No exception", "fr": "Aucune exception"},
    "exception": {"en": "Exception", "fr": "Exception"},
}


def pick(locale, en, fr):
    return fr if locale == "fr" else en


# ---------------------------------------------------------------------------
# Numbers, dates and words
# ---------------------------------------------------------------------------

def spaced(value, decimals=0):
    """An amount with spaces between thousands (1 000 000), a negative with a minus sign."""
    if value is None or value is False:
        return ""
    number = float(value)
    negative = number < 0
    scaled = int(abs(number) * 10 ** decimals + 0.5)
    whole, cents = str(scaled // 10 ** decimals), str(scaled % 10 ** decimals).zfill(decimals) if decimals else ""
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    out = " ".join(groups) + ("," + cents if cents else "")
    return "-" + out if negative and out.strip("0 ,") else out


def day_number(iso):
    """Days since 1970-01-01 of a yyyy-mm-dd date (proleptic Gregorian), or None."""
    if not iso or not _ISO.match(str(iso)[:10]):
        return None
    year, month, day = int(iso[:4]), int(iso[5:7]), int(iso[8:10])
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    if not 1 <= month <= 12 or not 1 <= day <= [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]:
        return None
    year -= month <= 2
    era = (year if year >= 0 else year - 399) // 400
    yoe = year - era * 400
    doy = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def dmy(iso):
    return "%s/%s/%s" % (iso[8:10], iso[5:7], iso[0:4]) if iso and _ISO.match(str(iso)[:10]) else ""


WEEKDAYS = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "fr": ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"],
}


def weekday_name(iso, locale):
    day = iso_weekday(iso) if iso else None
    return WEEKDAYS["fr" if locale == "fr" else "en"][day - 1] if day else ""


def plain_words(text):
    """Lower case, accents off, the words only."""
    folded = unicodedata.normalize("NFKD", (text or "").lower())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return _WORDS.findall(folded)


def person(value):
    return " ".join((value or "").split()).lower()


def _number(value, low, high, fallback):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number != number or number < low or number > high:
        return fallback
    return number


def resolve_settings(saved=None):
    """The engagement's settings, every value checked, the defaults where nothing is saved."""
    saved = saved or {}
    words = saved.get("vagueWords")
    if isinstance(words, str):
        words = [part for part in re.split(r"[,;\n]", words)]
    if isinstance(words, list):
        words = [" ".join(plain_words(str(word))) for word in words]
        words = [word for word in dict.fromkeys(words) if word][:60]
    else:
        words = list(DEFAULT_VAGUE_WORDS)
    out = {
        "roundStep": _number(saved.get("roundStep"), 1, 1e15, DEFAULTS["roundStep"]),
        "approvalLimit": _number(saved.get("approvalLimit"), 1, 1e15, DEFAULTS["approvalLimit"]),
        "approvalBand": _number(saved.get("approvalBand"), 0.1, 50, DEFAULTS["approvalBand"]),
        "cashLimit": _number(saved.get("cashLimit"), 0, 1e15, DEFAULTS["cashLimit"]),
        "yearEndDays": int(_number(saved.get("yearEndDays"), 1, 60, DEFAULTS["yearEndDays"])),
        "rarePosterShare": _number(saved.get("rarePosterShare"), 0.01, 50, DEFAULTS["rarePosterShare"]),
        "rareAccountEntries": int(_number(saved.get("rareAccountEntries"), 1, 1000, DEFAULTS["rareAccountEntries"])),
        "vagueMinChars": int(_number(saved.get("vagueMinChars"), 1, 50, DEFAULTS["vagueMinChars"])),
        "vagueWords": words,
        "holidays": clean_holidays(saved.get("holidays")) if saved.get("holidays") is not None else None,
    }
    return out


def clean_holidays(rows):
    """[{date, label}] sorted, one per date, only real dates."""
    out = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        date = str(row.get("date") or "").strip()[:10]
        if day_number(date) is None:
            continue
        out[date] = {"date": date, "label": str(row.get("label") or "").strip()[:120]}
    return [out[key] for key in sorted(out)]


def year_holidays(calendar, period_start, period_end):
    """The calendar's dates inside the year audited: {date: label} -> [{date, label}]."""
    start, end = day_number(period_start), day_number(period_end)
    rows = []
    for date in sorted(calendar or {}):
        number = day_number(date)
        if number is None or end is None:
            continue
        if (start is None and end - 365 < number <= end) or (start is not None and start <= number <= end):
            rows.append({"date": date, "label": calendar[date]})
    return rows


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------

def entry_facts(lines, next_period=False):
    """The facts of each entry, from its lines (the SQL of models/je_testing.py does the same).
    A line: je_number, journal_date, journal_code, je_description, line_description, preparer,
    approver, reviewer, account, debit, credit."""
    by_entry = {}
    for line in lines:
        je = str(line.get("je_number") or "").strip()
        if not je:
            continue
        entry = by_entry.setdefault(je, {
            "je": je, "date": None, "journal": None, "description": "", "line_description": "", "preparer": "",
            "approver": "", "reviewer": "", "amount": 0.0, "credit_total": 0.0, "debits": [], "credits": [],
            "lines": 0, "next": bool(next_period),
        })
        entry["lines"] += 1
        date = line.get("journal_date")
        if date and (entry["date"] is None or date < entry["date"]):
            entry["date"] = date
        journal = (line.get("journal_code") or "").strip()
        if journal and (entry["journal"] is None or journal < entry["journal"]):
            entry["journal"] = journal
        for source, target in (("je_description", "description"), ("line_description", "line_description"),
                               ("preparer", "preparer"), ("approver", "approver"), ("reviewer", "reviewer")):
            value = (line.get(source) or "").strip()
            if value and value > entry[target]:
                entry[target] = value
        signed = float(line.get("debit") or 0) - float(line.get("credit") or 0)
        account = str(line.get("account") or "").strip()
        if signed > 0:
            entry["amount"] += signed
            if account not in entry["debits"]:
                entry["debits"].append(account)
        elif signed < 0:
            entry["credit_total"] -= signed
            if account not in entry["credits"]:
                entry["credits"].append(account)
    out = []
    for je in sorted(by_entry):
        entry = by_entry[je]
        out.append(finish_facts(entry))
    return out


def finish_facts(entry):
    """The last step shared with the SQL read: one description, the approver (else the
    reviewer), the amount, sorted accounts."""
    return {
        "je": entry["je"], "date": entry["date"] or None, "journal": entry.get("journal") or "",
        "description": entry.get("description") or entry.get("line_description") or "",
        "preparer": entry.get("preparer") or "",
        "approver": entry.get("approver") or entry.get("reviewer") or "",
        "amount": int(max(entry.get("amount") or 0, entry.get("credit_total") or 0) * 100 + 0.5) / 100,
        "debits": sorted(a for a in entry.get("debits") or [] if a),
        "credits": sorted(a for a in entry.get("credits") or [] if a),
        "lines": entry.get("lines") or 0, "next": bool(entry.get("next")),
    }


def accounts_summary(entry, most=3):
    """"601, 6052 → 571": the accounts debited, then those credited."""
    def side(accounts):
        shown = accounts[:most]
        extra = len(accounts) - len(shown)
        return ", ".join(shown) + (" +%d" % extra if extra > 0 else "")
    return "%s → %s" % (side(entry["debits"]) or "—", side(entry["credits"]) or "—")


def _has(accounts, prefixes):
    return any(account.startswith(prefix) for account in accounts for prefix in prefixes)


def _either_way(entry, left, right):
    """The entry debits one side and credits the other."""
    debits, credits = entry["debits"], entry["credits"]
    return (_has(debits, left) and _has(credits, right)) or (_has(debits, right) and _has(credits, left))


# ---------------------------------------------------------------------------
# The criteria: each one a function of an entry's facts and the ledger context
# ---------------------------------------------------------------------------

def build_context(entries, settings, period_end, holidays):
    """What the criteria need from the whole ledger: who posts how many entries, how many
    entries use each account. Entries of the subsequent-period ledger are not counted."""
    posters, accounts, total = {}, {}, 0
    for entry in entries:
        if entry["next"]:
            continue
        total += 1
        who = person(entry["preparer"])
        if who:
            posters[who] = posters.get(who, 0) + 1
        for account in set(entry["debits"]) | set(entry["credits"]):
            accounts[account] = accounts.get(account, 0) + 1
    poster_floor = total * settings["rarePosterShare"] / 100.0
    return {
        "settings": settings, "periodEnd": day_number(period_end), "holidays": {row["date"] for row in holidays or []},
        "entries": total, "posters": posters, "accounts": accounts,
        "rarePosters": {who for who, count in posters.items() if count < poster_floor},
        "rareAccounts": {a for a, count in accounts.items() if count < settings["rareAccountEntries"]},
    }


def is_sunday(entry, ctx):
    return bool(entry["date"]) and iso_weekday(entry["date"]) == 7


def is_saturday(entry, ctx):
    return bool(entry["date"]) and iso_weekday(entry["date"]) == 6


def is_holiday(entry, ctx):
    return bool(entry["date"]) and entry["date"] in ctx["holidays"]


def is_year_end(entry, ctx):
    day, end = day_number(entry["date"]), ctx["periodEnd"]
    if day is None or end is None:
        return False
    days = ctx["settings"]["yearEndDays"]
    return end - days < day <= end + days


def is_same_person(entry, ctx):
    who = person(entry["preparer"])
    return bool(who) and who == person(entry["approver"])


def is_no_approver(entry, ctx):
    return not person(entry["approver"])


def is_rare_poster(entry, ctx):
    return person(entry["preparer"]) in ctx["rarePosters"]


def is_round(entry, ctx):
    step = ctx["settings"]["roundStep"]
    cents = int(entry["amount"] * 100 + 0.5)
    step_cents = int(step * 100 + 0.5)
    return cents >= step_cents > 0 and cents % step_cents == 0


def is_below_limit(entry, ctx):
    limit = ctx["settings"]["approvalLimit"]
    floor = limit * (1 - ctx["settings"]["approvalBand"] / 100.0)
    return floor <= entry["amount"] < limit


def is_vague(entry, ctx):
    text = " ".join((entry["description"] or "").split())
    if len(text) < ctx["settings"]["vagueMinChars"]:
        return True
    words = plain_words(text)
    if not words:
        return True
    generic = set()
    for phrase in ctx["settings"]["vagueWords"]:
        generic.update(phrase.split())
    return all(word in generic or word.isdigit() for word in words)


def is_rare_account(entry, ctx):
    used = set(entry["debits"]) | set(entry["credits"])
    return any(a.startswith("47") for a in used) or bool(used & ctx["rareAccounts"])


def is_revenue_cash(entry, ctx):
    used = entry["debits"] + entry["credits"]
    return _has(entry["credits"], ("70",)) and _has(entry["debits"], ("52", "57")) and not _has(used, ("41",))


def is_cash_expense(entry, ctx):
    return _has(entry["debits"], ("6",)) and _has(entry["credits"], ("57",)) and entry["amount"] > ctx["settings"]["cashLimit"]


def is_assets_revenue(entry, ctx):
    return _either_way(entry, ("2",), ("7",))


def is_payables_receivables(entry, ctx):
    return _either_way(entry, ("40",), ("41",))


def is_revenue_after(entry, ctx):
    day, end = day_number(entry["date"]), ctx["periodEnd"]
    return day is not None and end is not None and day > end and _has(entry["debits"], ("70",))


def is_equity_result(entry, ctx):
    return _either_way(entry, ("1",), ("6", "7"))


TESTS = {
    "sunday": is_sunday, "saturday": is_saturday, "holiday": is_holiday, "year-end": is_year_end,
    "same-person": is_same_person, "no-approver": is_no_approver, "rare-poster": is_rare_poster,
    "round": is_round, "below-limit": is_below_limit, "vague": is_vague, "rare-account": is_rare_account,
    "revenue-cash": is_revenue_cash, "cash-expense": is_cash_expense, "assets-revenue": is_assets_revenue,
    "payables-receivables": is_payables_receivables, "revenue-after": is_revenue_after, "equity-result": is_equity_result,
}


def run_criteria(entries, ctx):
    """{je key: [criteria that found it]} for the entries found by at least one, and the count
    of entries each criterion finds (a criterion that finds nothing counts 0)."""
    found, counts = {}, {key: 0 for key in CRITERION_KEYS}
    for entry in entries:
        keys = AFTER_YEAR_END if entry["next"] else CRITERION_KEYS
        hits = [key for key in keys if TESTS[key](entry, ctx)]
        if hits:
            found[entry_key(entry)] = hits
            for key in hits:
                counts[key] += 1
    return found, counts


def entry_key(entry):
    """An entry of the subsequent-period ledger is told apart from one of the same number."""
    return ("next:" if entry["next"] else "") + entry["je"]


def filter_selection(selection, ticked):
    """The entries shown: those found by any ticked criterion; nothing ticked, the whole selection.
    ``selection`` is a list of rows with ``reasons`` (criterion keys)."""
    wanted = {key for key in ticked or [] if key in TESTS}
    if not wanted:
        return list(selection)
    return [row for row in selection if wanted & set(row["reasons"])]


# ---------------------------------------------------------------------------
# Labels, tests and the export
# ---------------------------------------------------------------------------

def criterion_name(criterion, settings, locale):
    text = criterion["fr" if locale == "fr" else "en"]
    return text % {"n": settings["yearEndDays"]} if "%(n)s" in text else text


def settings_text(settings, holidays_count, locale):
    """The settings line under the criteria."""
    return pick(
        locale,
        "Set once for the engagement: round amounts are multiples of %(round)s · approval limit %(limit)s, band %(band)s %% · "
        "cash expenses above %(cash)s · %(days)s days around the year end · rare poster below %(share)s %% of entries · "
        "rare accounts in fewer than %(acc)s entries · %(hol)s public holidays",
        "Fixés une fois pour la mission : montants ronds multiples de %(round)s · seuil d'approbation %(limit)s, marge %(band)s %% · "
        "charges en espèces au-delà de %(cash)s · %(days)s jours autour de la clôture · auteur rare sous %(share)s %% des écritures · "
        "comptes utilisés dans moins de %(acc)s écritures · %(hol)s jours fériés",
    ) % {
        "round": spaced(settings["roundStep"]), "limit": spaced(settings["approvalLimit"]), "band": _short(settings["approvalBand"]),
        "cash": spaced(settings["cashLimit"]), "days": settings["yearEndDays"], "share": _short(settings["rarePosterShare"]),
        "acc": settings["rareAccountEntries"], "hol": holidays_count,
    }


def _short(number):
    text = ("%.2f" % number).rstrip("0").rstrip(".")
    return text.replace(".", ",")


def entry_conclusion(review):
    """No exception, Exception or To test, from the four answers; a review recorded before the
    four questions existed reads its stored status."""
    review = review or {}
    answers = [review.get(a["key"]) for a in ATTRIBUTES]
    if "no" in answers:
        return "exception"
    if all(answer in ANSWERS for answer in answers):
        return "no_exception"
    if any(answers):
        return "to_test"
    return LEGACY_STATUS.get(review.get("status") or "to_clear", "to_test")


def stored_status(conclusion):
    """The review's own status column, kept in step with the conclusion."""
    return {"to_test": "to_clear", "no_exception": "cleared", "exception": "problem"}[conclusion]


def selection_totals(rows):
    """Tested n of N, without and with exceptions."""
    out = {"selected": len(rows), "tested": 0, "clean": 0, "exceptions": 0}
    for row in rows:
        if row["test"] == "no_exception":
            out["tested"] += 1
            out["clean"] += 1
        elif row["test"] == "exception":
            out["tested"] += 1
            out["exceptions"] += 1
    return out


def export_rows(rows, locale):
    """The selection for the client: one row per entry, with every reason it was selected."""
    names = {c["key"]: c for c in CRITERIA}
    head = [
        pick(locale, "Entry", "Écriture"), pick(locale, "Date", "Date"), pick(locale, "Day", "Jour"),
        pick(locale, "Journal", "Journal"), pick(locale, "Description", "Libellé"),
        pick(locale, "Accounts (debit → credit)", "Comptes (débit → crédit)"), pick(locale, "Amount", "Montant"),
        pick(locale, "Prepared by", "Préparée par"), pick(locale, "Approved by", "Approuvée par"),
        pick(locale, "Why selected", "Motifs de sélection"), pick(locale, "Document requested", "Pièce demandée"),
    ]
    body = []
    for row in rows:
        body.append([
            row["je"], dmy(row["date"]), weekday_name(row["date"], locale), row["journal"], row["description"],
            row["accounts"], row["amount"], row["preparer"], row["approver"],
            "; ".join(names[key]["no"] + " " + row["reasonNames"][index] for index, key in enumerate(row["reasons"])),
            "",
        ])
    return head, body
