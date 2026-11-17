"""Data quality (IPE): the automatic checks of every file the client gives us, ISA 500
paragraph 9 (information produced by the entity). No database here.

The model reads the stored rows of an upload into columns (one list per file column, in row
order) and passes them here with the mapping of the import; these functions decide. Each check
answers with a status, a count and the lines of the file that make the exception, so a person
can find them in the file:

    passed      nothing to report
    exceptions  ``count`` lines (or entries, accounts) to explain
    na          the file has not the columns the check needs
    info        figures shown for information, nothing to explain

Dates are ISO strings (yyyy-mm-dd) throughout. Amounts are floats, read by parse_amount like
every import. No sum() and no round(): see tests_pure/test_purity.py.
"""
import re
from decimal import ROUND_HALF_UP, Decimal

from ._js import cell_str, is_number, js_str, js_trim
from .amount import parse_amount
from .dataset_mapping import je_identity, je_key_columns
from .gl_line import parse_date_iso
from .import_matching import depreciation_rate

PASSED, EXCEPTIONS, NA, INFO = "passed", "exceptions", "na", "info"
#: Lines kept per check; the count is always the full one.
LINE_CAP = 1000
#: The information table of the ledger's totals by account and month.
TOTALS_CAP = 5000
TOLERANCE = 0.005
#: The year's depreciation recomputed from cost x rate x time may differ by this share (prorata
#: by month or by day, rounding) before the difference is listed.
CHARGE_TOLERANCE = 0.02

#: Bank statements (BK) and supplier statements (SS) are no longer uploaded (owner, 18/11/2026):
#: their checks are gone; the codes stay below so a record kept from before reads the same.
KINDS = [
    "trial_balance", "journal_entries", "fixed_asset_register", "payroll_register", "ar_open_items",
    "ap_open_items", "inventory_listing",
]
KIND_CODES = {
    "trial_balance": "TB", "journal_entries": "GL", "fixed_asset_register": "FA", "payroll_register": "PR",
    "ar_open_items": "AR", "ap_open_items": "AP", "bank_statement": "BK", "inventory_listing": "IN",
    "supplier_statements": "SS",
}
TIMINGS = ["prior_year", "pre_audit", "final", "post_audit", "subsequent"]
TIMING_CODES = {"prior_year": "PY", "pre_audit": "PRE", "final": "FIN", "post_audit": "POST", "subsequent": "SUB"}

#: The working papers that rely on each kind of file (the right rail of a paper and of the page).
#: The trial balance feeds every account paper (E4.x) through the lead schedules.
PAPERS = {
    "journal_entries": ["E3.1", "S5.4"],
    "trial_balance": ["P6.1", "P6.2"],
    "fixed_asset_register": ["E4.4"],
    "payroll_register": ["E4.11", "E4.26"],
    "ar_open_items": ["E4.1"],
    "ap_open_items": ["E4.2"],
    "inventory_listing": ["E4.3"],
}
#: The tools that read each kind of file: (engagement method, English, French).
TOOLS = {
    "journal_entries": [
        ("action_tool_eagla", "EAGLA", "EAGLA"),
        ("action_tool_je", "Journal entries", "Écritures de journal"),
        ("action_tool_sampling", "Sampling", "Échantillonnage"),
    ],
    "trial_balance": [
        ("action_tool_significance", "Significant accounts", "Comptes significatifs"),
        ("action_tool_lead", "Lead schedules", "Feuilles maîtresses"),
    ],
}


def reference(kind, timing):
    """IPE-GL-PRE, IPE-TB-PY, IPE-FA-FIN, IPE-PR-SUB."""
    return "IPE-%s-%s" % (KIND_CODES.get(kind, kind.upper()), TIMING_CODES.get(timing, (timing or "").upper()))


def kinds_for_paper(code):
    """The kinds of file a working paper relies on: every account paper (E4.x) on the trial balance."""
    found = [kind for kind in KINDS if code in PAPERS[kind]]
    if code.startswith("E4.") and "trial_balance" not in found:
        found.insert(0, "trial_balance")
    return found


def papers_for_kind(kind, codes):
    """The paper codes of the file (``codes``) that rely on a kind, in the file's order."""
    return [code for code in codes if kind in kinds_for_paper(code)]


# ----------------------------------------------------------------------
# Dates, without datetime (the services keep to the standard library's small part)
# ----------------------------------------------------------------------

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _leap(year):
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def day_number(iso):
    """Days since 1970-01-01 of an ISO date (days_from_civil)."""
    match = _ISO_DATE.match(iso)
    year, month, day = int(match[1]), int(match[2]), int(match[3])
    year -= month <= 2
    era = (year if year >= 0 else year - 399) // 400
    yoe = year - era * 400
    doy = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def from_day_number(number):
    number += 719468
    era = (number if number >= 0 else number - 146096) // 146097
    doe = number - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + (3 if mp < 10 else -9)
    year = yoe + era * 400 + (month <= 2)
    return "%04d-%02d-%02d" % (year, month, day)


def add_days(iso, days):
    return from_day_number(day_number(iso) + days)


def shift_years(iso, years):
    year, month, day = int(iso[:4]) + years, int(iso[5:7]), int(iso[8:10])
    if month == 2 and day == 29 and not _leap(year):
        day = 28
    return "%04d-%02d-%02d" % (year, month, day)


def period_of(timing, period_end):
    """(first day, last day) of the period a file's dates belong to: the year audited, the year
    before it for a prior-year file, the year after it for a subsequent-period file."""
    if not period_end:
        return None, None
    if timing == "prior_year":
        end = shift_years(period_end, -1)
    elif timing == "subsequent":
        end = shift_years(period_end, 1)
    else:
        end = period_end
    return add_days(shift_years(end, -1), 1), end


def date_text(iso):
    """dd/mm/yyyy, as every screen of the application writes a date."""
    return "%s/%s/%s" % (iso[8:10], iso[5:7], iso[:4]) if iso else ""


# ----------------------------------------------------------------------
# Amounts in words
# ----------------------------------------------------------------------

def amount_text(value, lang="en"):
    """Spaces between thousands, FCFA; decimals only when there are some; a negative in brackets."""
    if value is None:
        return ""
    rounded = Decimal(repr(abs(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    whole, _, fraction = format(rounded, "f").partition(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    body = " ".join(groups)
    if fraction.strip("0"):
        body += ("," if lang == "fr" else ".") + fraction
    text = "%s FCFA" % body
    return "(%s)" % text if value < 0 and rounded != 0 else text


#: Columns that hold quantities, not money.
QUANTITIES = {"quantity"}


def figure_text(field, value, lang="en"):
    """An amount in FCFA, or a quantity as a plain number."""
    text = amount_text(value, lang)
    return text.replace(" FCFA", "") if field in QUANTITIES else text


def _total(values):
    total = 0.0
    for value in values:
        if value is not None:
            total += value
    return total


def _close(a, b, tolerance=TOLERANCE):
    return abs((a or 0) - (b or 0)) <= tolerance


# ----------------------------------------------------------------------
# The file as columns
# ----------------------------------------------------------------------

_TOTAL_LINE = re.compile(r"^\s*(grand[\s-]*)?(sous[\s-]*)?(total|totaux|sub[\s-]*total)\b", re.I)  # i18n: input


class Data:
    """The stored rows of one upload, as columns. ``columns`` maps a file column to its values,
    ``rows`` holds the file line of each row, ``mapping`` the import's field -> file column."""

    def __init__(self, columns, rows, mapping):
        self.columns = columns
        self.rows = rows
        self.n = len(rows)
        self.mapping = {key: header for key, header in (mapping or {}).items() if isinstance(header, str) and header.strip()}
        self._text, self._num, self._date = {}, {}, {}
        self.total_rows = set()

    def has(self, field):
        header = self.mapping.get(field)
        return bool(header) and header in self.columns

    def header(self, field):
        return self.mapping.get(field) or field

    def raw(self, field):
        return self.columns.get(self.mapping.get(field)) or [None] * self.n

    def text(self, field):
        if field not in self._text:
            self._text[field] = [js_trim(cell_str(value)) if value is not None else "" for value in self.raw(field)]
        return self._text[field]

    def num(self, field):
        if field not in self._num:
            self._num[field] = [parse_amount(value) for value in self.raw(field)]
        return self._num[field]

    def date(self, field):
        if field not in self._date:
            self._date[field] = [parse_date_iso(value) for value in self.raw(field)]
        return self._date[field]

    def kept(self):
        """The row positions the checks read: every row but the file's total lines."""
        return [i for i in range(self.n) if i not in self.total_rows]


def _blank(value):
    return value is None or (not is_number(value) and js_trim(js_str(value)) == "")


def _cell(value):
    if value is None:
        return ""
    return js_trim(cell_str(value))[:80]


class Check:
    """One check's result, built line by line."""

    def __init__(self, code, cap=LINE_CAP):
        self.code = code
        self.cap = cap
        self.count = 0
        self.lines = []
        self.status = PASSED
        self.note = None

    def add(self, row=None, ref="", column="", value="", en="", fr="", amount=None, expected=None, count=True):
        if count:
            self.count += 1
        if len(self.lines) < self.cap:
            self.lines.append({
                "row": row, "ref": ref or "", "column": column or "", "value": value or "",
                "amount": amount, "expected": expected, "en": en, "fr": fr,
            })

    def says(self, text):
        """The sentence under the check, {"en", "fr"}."""
        self.note = text
        return self

    def result(self):
        status = self.status
        if status == PASSED and self.count:
            status = EXCEPTIONS
        return {"code": self.code, "status": status, "count": self.count if status == EXCEPTIONS else 0,
                "lines": self.lines, "note": self.note}


def _d(en, fr):
    """A sentence in both languages."""
    return {"en": en, "fr": fr}


def not_applicable(code, text):
    check = Check(code)
    check.status = NA
    return check.says(text).result()


def _missing_columns(data, fields):
    return [field for field in fields if not data.has(field)]


# ----------------------------------------------------------------------
# The checks every kind of file gets
# ----------------------------------------------------------------------

def mark_total_lines(data, key_fields, text_fields, amount_fields):
    """The file's own total lines: a key cell reading "Total", or every key cell blank with an
    amount. They are kept apart: they add down, they are not records."""
    keys = [data.text(field) for field in key_fields if data.has(field)]
    texts = [data.text(field) for field in text_fields if data.has(field)]
    amounts = [data.num(field) for field in amount_fields if data.has(field)]
    for i in range(data.n):
        if any(_TOTAL_LINE.match(column[i]) for column in keys + texts):
            data.total_rows.add(i)
        elif keys and all(not column[i] for column in keys) and any(column[i] for column in amounts):
            data.total_rows.add(i)


def check_rows(code, data, rows_read, left_out=(), set_apart=0):
    """Every line read: the lines the file holds against the lines kept. ``left_out`` lists the
    lines read but kept out of the records, with why; ``set_apart`` counts the lines the import
    already set apart (titles and totals of a trial balance), which are not in ``data``."""
    check = Check(code)
    for row, en, fr in left_out:
        check.add(row=row, en=en, fr=fr)
    if rows_read is not None and rows_read != data.n + set_apart:
        check.add(en="%d lines in the file, %d kept." % (rows_read, data.n + set_apart),
                  fr="%d lignes dans le fichier, %d conservées." % (rows_read, data.n + set_apart))
    totals = len(data.total_rows) + set_apart
    kept = data.n - len(left_out) - len(data.total_rows)
    text = _d("%d lines read, %d kept as records." % (data.n + set_apart, kept),
              "%d lignes lues, %d retenues comme enregistrements." % (data.n + set_apart, kept))
    if totals:
        text = _d("%d lines read, %d kept as records, %d title or total lines set apart." % (data.n + set_apart, kept, totals),
                  "%d lignes lues, %d retenues comme enregistrements, %d lignes de titre ou de total mises à part." % (data.n + set_apart, kept, totals))
    return check.says(text).result()


def check_mandatory(code, data, fields, amount_pair=None):
    """Mandatory cells filled: each blank cell, by column. ``amount_pair`` (debit, credit) counts
    as one amount: blank when both are blank."""
    present = [field for field in fields if data.has(field)]
    if not present and not amount_pair:
        return not_applicable(code, _d("The file has none of the mandatory columns.", "Le fichier n'a aucune des colonnes obligatoires."))
    check = Check(code)
    by_column = {}
    raw = {field: data.raw(field) for field in present}
    pair = None
    if amount_pair and all(data.has(field) for field in amount_pair):
        pair = (data.raw(amount_pair[0]), data.raw(amount_pair[1]))
    for i in data.kept():
        for field in present:
            if _blank(raw[field][i]):
                header = data.header(field)
                by_column[header] = by_column.get(header, 0) + 1
                check.add(row=data.rows[i], column=header, en="Blank cell", fr="Cellule vide")
        if pair and _blank(pair[0][i]) and _blank(pair[1][i]):
            header = "%s / %s" % (data.header(amount_pair[0]), data.header(amount_pair[1]))
            by_column[header] = by_column.get(header, 0) + 1
            check.add(row=data.rows[i], column=header, en="No amount", fr="Aucun montant")
    if by_column:
        parts = ", ".join("%s: %d" % item for item in sorted(by_column.items()))
        check.says(_d("Blank cells by column: %s." % parts, "Cellules vides par colonne : %s." % parts))
    else:
        columns = ", ".join(data.header(field) for field in present)
        check.says(_d("Every mandatory cell is filled (%s)." % columns, "Toutes les cellules obligatoires sont remplies (%s)." % columns))
    return check.result()


_ACCOUNT_FORM = re.compile(r"^[1-9][0-9A-Za-z]*$")


def check_values(code, data, amount_fields=(), date_fields=(), account_fields=()):
    """Values valid: an amount column holds amounts, a date column dates, an account column
    account codes (a figure from 1 to 9 first)."""
    amounts = [field for field in amount_fields if data.has(field)]
    dates = [field for field in date_fields if data.has(field)]
    accounts = [field for field in account_fields if data.has(field)]
    if not (amounts or dates or accounts):
        return not_applicable(code, _d("The file has no amount, date or code column.", "Le fichier n'a aucune colonne de montant, de date ou de code."))
    check = Check(code)
    for field in amounts:
        raw, parsed, header = data.raw(field), data.num(field), data.header(field)
        for i in data.kept():
            if parsed[i] is None and not _blank(raw[i]):
                check.add(row=data.rows[i], column=header, value=_cell(raw[i]), en="Not an amount", fr="N'est pas un montant")
    for field in dates:
        raw, parsed, header = data.raw(field), data.date(field), data.header(field)
        for i in data.kept():
            if parsed[i] is None and not _blank(raw[i]):
                check.add(row=data.rows[i], column=header, value=_cell(raw[i]), en="Not a date", fr="N'est pas une date")
    for field in accounts:
        texts, header = data.text(field), data.header(field)
        for i in data.kept():
            if texts[i] and not _ACCOUNT_FORM.match(texts[i]):
                check.add(row=data.rows[i], column=header, value=texts[i], en="Not an account code", fr="N'est pas un numéro de compte")
    if not check.count:
        check.says(_d("Every amount, date and code can be read.", "Tous les montants, dates et codes sont lisibles."))
    return check.result()


def check_dates_in_period(code, data, field, start, end, timing, upper_only=False):
    """Dates inside the period of the file. ``upper_only``: a date before the period is no
    exception (an open invoice, an asset bought years ago), a date after it is."""
    if not data.has(field):
        return not_applicable(code, _d("The file has no date column.", "Le fichier n'a pas de colonne de date."))
    if not end:
        return not_applicable(code, _d("The engagement has no period end.", "La mission n'a pas de date de clôture."))
    check = Check(code)
    dates, header = data.date(field), data.header(field)
    first = last = None
    for i in data.kept():
        value = dates[i]
        if value is None:
            continue
        first = value if first is None or value < first else first
        last = value if last is None or value > last else last
        if value > end or (not upper_only and value < start):
            check.add(row=data.rows[i], column=header, value=date_text(value),
                      en="Outside the period %s to %s" % (date_text(start), date_text(end)) if not upper_only else "After the period end %s" % date_text(end),
                      fr="Hors de la période du %s au %s" % (date_text(start), date_text(end)) if not upper_only else "Après la clôture du %s" % date_text(end))
    if first:
        dates = (date_text(first), date_text(last), date_text(start), date_text(end))
        text = _d("Dates run from %s to %s; the period is %s to %s." % dates, "Les dates vont du %s au %s ; la période va du %s au %s." % dates)
        if timing == "pre_audit" and last < end:
            text = _d("%s The file stops on %s, before the period end: for information." % (text["en"], date_text(last)),
                      "%s Le fichier s'arrête au %s, avant la clôture : pour information." % (text["fr"], date_text(last)))
        check.says(text)
    return check.result()


def check_duplicates(code, data, fields=None):
    """No duplicated lines: every mapped cell the same as an earlier line."""
    fields = [field for field in (fields or data.mapping) if data.has(field)]
    if not fields:
        return not_applicable(code, _d("The file has no column to compare.", "Le fichier n'a aucune colonne à comparer."))
    check = Check(code)
    columns = [data.text(field) for field in fields]
    seen = {}
    for i in data.kept():
        key = tuple(column[i] for column in columns)
        if key in seen:
            first = seen[key]
            check.add(row=data.rows[i], value=str(first), en="Same as line %s" % first, fr="Identique à la ligne %s" % first)
        else:
            seen[key] = data.rows[i]
    if not check.count:
        check.says(_d("No line repeats another.", "Aucune ligne n'en répète une autre."))
    return check.result()


def check_totals_down(code, data, amount_fields):
    """Totals add down: the columns recomputed, and compared with the file's own total line
    (the last one) when it has one."""
    fields = [field for field in amount_fields if data.has(field)]
    if not fields:
        return not_applicable(code, _d("The file has no amount column.", "Le fichier n'a pas de colonne de montant."))
    check = Check(code)
    kept = data.kept()
    totals = {field: _total(data.num(field)[i] for i in kept) for field in fields}
    words_en = "; ".join("%s %s" % (data.header(field), figure_text(field, totals[field], "en")) for field in fields)
    words_fr = " ; ".join("%s %s" % (data.header(field), figure_text(field, totals[field], "fr")) for field in fields)
    if not data.total_rows:
        check.status = INFO
        return check.says(_d("No total line in the file. Totals recomputed: %s." % words_en,
                          "Pas de ligne de total dans le fichier. Totaux recalculés : %s." % words_fr)).result()
    last = max(data.total_rows)
    for field in fields:
        stated = data.num(field)[last]
        if stated is not None and not _close(stated, totals[field], 0.5):
            check.add(row=data.rows[last], column=data.header(field), amount=stated, expected=totals[field],
                      en="The file's total differs from the lines by %s" % figure_text(field, stated - totals[field], "en"),
                      fr="Le total du fichier diffère des lignes de %s" % figure_text(field, stated - totals[field], "fr"))
    return check.says(_d("Totals recomputed: %s." % words_en, "Totaux recalculés : %s." % words_fr)).result()


def check_same_name(code, data, pairs, need_name=False):
    """Same code, same name: a code that carries two names, or (``need_name``) none."""
    pairs = [(c, n) for c, n in pairs if data.has(c) and data.has(n)]
    if not pairs:
        return not_applicable(code, _d("The file has no code and name columns.", "Le fichier n'a pas de colonnes de code et de nom."))
    check = Check(code)
    for code_field, name_field in pairs:
        codes, names = data.text(code_field), data.text(name_field)
        found = {}
        for i in data.kept():
            if codes[i]:
                found.setdefault(codes[i], {}).setdefault(names[i], data.rows[i])
        for key, by_name in found.items():
            named = [name for name in by_name if name]
            if len(named) > 1:
                second = by_name[named[1]]
                check.add(row=second, ref=key, column=data.header(name_field), value=" | ".join(named[:4]),
                          en="One code, %d names" % len(named), fr="Un code, %d noms" % len(named))
            elif need_name and not named:
                check.add(row=by_name[""], ref=key, column=data.header(name_field), en="No name", fr="Aucun nom")
    if not check.count:
        check.says(_d("Every code carries one name.", "Chaque code porte un seul nom."))
    return check.result()


def check_unique(code, data, key_fields, what):
    """A code used once (per the other key fields)."""
    if not all(data.has(field) for field in key_fields):
        return not_applicable(code, _d("The file has not the columns this check needs.", "Le fichier n'a pas les colonnes nécessaires à ce contrôle."))
    check = Check(code)
    columns = [data.text(field) for field in key_fields]
    seen = {}
    for i in data.kept():
        key = tuple(column[i] for column in columns)
        if not key[0]:
            continue
        if key in seen:
            check.add(row=data.rows[i], ref=" · ".join(part for part in key if part), value=str(seen[key]),
                      en="Already on line %s" % seen[key], fr="Déjà à la ligne %s" % seen[key])
        else:
            seen[key] = data.rows[i]
    if not check.count:
        check.says(_d("Every %s is used once." % what["en"], "Chaque %s n'est utilisé qu'une fois." % what["fr"]))
    return check.result()


_NUMBERED = re.compile(r"^(.*?)(\d+)$")


def check_sequence(code, data, number_field, group_field=None, status_if_gaps=EXCEPTIONS):
    """Numbers follow each other (per ``group_field``): the gaps, and the numbers used for two
    different dates (an entry or an invoice numbered twice). Prefixes such as VE-0001 are read."""
    if not data.has(number_field):
        return not_applicable(code, _d("The file has no number column.", "Le fichier n'a pas de colonne de numéro."))
    numbers = data.text(number_field)
    groups = data.text(group_field) if group_field and data.has(group_field) else None
    dates = None
    for field in ("journalDate", "date", "jeDate"):
        if data.has(field):
            dates = data.date(field)
            break
    series, first_row, dated = {}, {}, {}
    readable = total = 0
    for i in data.kept():
        number = numbers[i]
        if not number:
            continue
        total += 1
        match = _NUMBERED.match(number)
        if not match:
            continue
        readable += 1
        key = (groups[i] if groups else "", match[1])
        series.setdefault(key, set()).add(int(match[2]))
        first_row.setdefault((key, number), data.rows[i])
        if dates and dates[i]:
            dated.setdefault((key[0], number), {}).setdefault(dates[i], data.rows[i])
    if not total or readable * 2 < total:
        return not_applicable(code, _d("The numbers are not numbered in sequence (no figures at their end).",
                              "Les numéros ne sont pas séquentiels (pas de chiffres à la fin)."))
    check = Check(code)
    gaps = 0
    for (group, prefix), values in sorted(series.items()):
        ordered = sorted(values)
        for low, high in zip(ordered, ordered[1:]):
            if high - low > 1:
                gaps += 1
                missing = high - low - 1
                where = "%s%s" % (prefix, low + 1) if missing == 1 else "%s%s to %s%s" % (prefix, low + 1, prefix, high - 1)
                where_fr = "%s%s" % (prefix, low + 1) if missing == 1 else "%s%s à %s%s" % (prefix, low + 1, prefix, high - 1)
                check.add(ref=group, value=where, en="%d number(s) missing: %s" % (missing, where),
                          fr="%d numéro(s) manquant(s) : %s" % (missing, where_fr), count=status_if_gaps == EXCEPTIONS)
    reused = 0
    for (group, number), by_date in dated.items():
        if len(by_date) > 1:
            reused += 1
            days = sorted(by_date)
            check.add(row=by_date[days[1]], ref=number, value=", ".join(date_text(day) for day in days[:3]),
                      en="Number used on %d different dates" % len(days), fr="Numéro utilisé à %d dates différentes" % len(days),
                      count=status_if_gaps == EXCEPTIONS)
    if status_if_gaps == INFO and check.lines:
        # open items: a paid invoice leaves a gap, and the uniqueness check names a number used twice
        check.status = INFO
    text = _d("%d gap(s) and %d number(s) used twice." % (gaps, reused), "%d trou(s) et %d numéro(s) utilisé(s) deux fois." % (gaps, reused))
    if status_if_gaps == INFO:
        text = _d("%s Gaps are expected for invoices already paid." % text["en"],
                  "%s Des trous sont attendus pour les factures déjà réglées." % text["fr"])
    return check.says(text).result()


def check_formula(code, data, need, compute, rule, tolerance=0.5, relative=0.0):
    """Totals add across: ``compute(i)`` -> (stated, expected) or None, for the rows that have the
    columns ``need``."""
    if _missing_columns(data, need):
        return not_applicable(code, _d("The file has not the columns of this check (%s)." % ", ".join(need),
                              "Le fichier n'a pas les colonnes de ce contrôle (%s)." % ", ".join(need)))
    check = Check(code)
    for i in data.kept():
        found = compute(i)
        if found is None:
            continue
        stated, expected = found
        if abs(stated - expected) > max(tolerance, relative * abs(expected)):
            check.add(row=data.rows[i], amount=stated, expected=expected,
                      en="Difference %s" % amount_text(stated - expected, "en"), fr="Écart %s" % amount_text(stated - expected, "fr"))
    return check.says(rule).result()


def check_rows_where(code, data, need, test, rule, status=EXCEPTIONS, column=None):
    """Lines that meet ``test(i)`` -> None or (value, en, fr)."""
    if _missing_columns(data, need):
        return not_applicable(code, _d("The file has not the columns of this check (%s)." % ", ".join(need),
                              "Le fichier n'a pas les colonnes de ce contrôle (%s)." % ", ".join(need)))
    check = Check(code)
    for i in data.kept():
        found = test(i)
        if found:
            value, en, fr = found
            check.add(row=data.rows[i], column=column or "", value=value, en=en, fr=fr, count=status == EXCEPTIONS)
            if status == INFO:
                check.status = INFO
    return check.says(rule).result()


def _num0(data, field):
    return [value or 0 for value in data.num(field)] if data.has(field) else [0] * data.n


# ----------------------------------------------------------------------
# The catalogue: the title of each check, in both languages
# ----------------------------------------------------------------------

_COMMON = {
    "rows": {"en": "Every line read", "fr": "Toutes les lignes lues"},
    "mandatory": {"en": "Mandatory cells filled", "fr": "Cellules obligatoires remplies"},
    "values": {"en": "Values valid (amounts, dates, codes)", "fr": "Valeurs valides (montants, dates, codes)"},
    "period": {"en": "Dates inside the period of the file", "fr": "Dates dans la période du fichier"},
    "duplicates": {"en": "No duplicated lines", "fr": "Pas de lignes en double"},
    "down": {"en": "Totals add down", "fr": "Les totaux des colonnes sont justes"},
    "names": {"en": "Same code, same name", "fr": "Même code, même nom"},
}

CATALOGUE = {
    "trial_balance": [
        ("rows", _COMMON["rows"]),
        ("mandatory", {"en": "Mandatory cells filled (an amount on every account line)", "fr": "Cellules obligatoires remplies (un montant sur chaque ligne de compte)"}),
        ("values", _COMMON["values"]),
        ("down", _COMMON["down"]),
        ("balanced", {"en": "Total debits equal total credits; opening and closing net to zero", "fr": "Total des débits égal au total des crédits ; ouverture et clôture soldées à zéro"}),
        ("equation", {"en": "Opening + debit − credit = closing, account by account", "fr": "Ouverture + débit − crédit = clôture, compte par compte"}),
        ("unique", {"en": "Account codes used once", "fr": "Numéros de compte utilisés une seule fois"}),
        ("form", {"en": "Account codes in SYSCOHADA form (class 1 to 9)", "fr": "Numéros de compte au format SYSCOHADA (classes 1 à 9)"}),
        ("noname", {"en": "No account with a balance but no name", "fr": "Aucun compte avec un solde mais sans libellé"}),
        ("prior", {"en": "Opening balances equal the prior-year closing balances", "fr": "Soldes d'ouverture égaux aux soldes de clôture de l'exercice précédent"}),
        ("suspense", {"en": "Waiting and suspense accounts (class 47) with a balance", "fr": "Comptes d'attente (classe 47) présentant un solde"}),
    ],
    "journal_entries": [
        ("rows", _COMMON["rows"]),
        ("mandatory", {"en": "Mandatory cells filled (account, entry number, date, description, amount)", "fr": "Cellules obligatoires remplies (compte, numéro d'écriture, date, libellé, montant)"}),
        ("values", _COMMON["values"]),
        ("period", _COMMON["period"]),
        ("duplicates", _COMMON["duplicates"]),
        ("down", _COMMON["down"]),
        ("names", _COMMON["names"]),
        ("entries", {"en": "Every journal entry balances to zero", "fr": "Chaque écriture est équilibrée"}),
        ("ledger", {"en": "The whole ledger balances to zero", "fr": "Le grand livre est équilibré dans son ensemble"}),
        ("sequence", {"en": "Entry numbers follow each other within each journal", "fr": "Les numéros d'écriture se suivent dans chaque journal"}),
        ("both", {"en": "No line with both a debit and a credit", "fr": "Aucune ligne à la fois au débit et au crédit"}),
        ("zero", {"en": "No line with a zero amount", "fr": "Aucune ligne à montant nul"}),
        ("extraction", {"en": "No entry dated after the extraction date", "fr": "Aucune écriture datée après la date d'extraction"}),
        ("people", {"en": "Preparer and approver filled", "fr": "Préparateur et approbateur renseignés"}),
        ("bymonth", {"en": "Totals by account and month recomputed", "fr": "Totaux par compte et par mois recalculés"}),
    ],
    "fixed_asset_register": [
        ("rows", _COMMON["rows"]),
        ("mandatory", _COMMON["mandatory"]),
        ("values", _COMMON["values"]),
        ("period", {"en": "Acquisition dates not after the period end", "fr": "Dates d'acquisition antérieures à la clôture"}),
        ("duplicates", _COMMON["duplicates"]),
        ("down", _COMMON["down"]),
        ("unique", {"en": "Asset numbers used once", "fr": "Numéros d'immobilisation utilisés une seule fois"}),
        ("net", {"en": "Cost − accumulated depreciation = net value", "fr": "Valeur brute − amortissements cumulés = valeur nette"}),
        ("rollforward", {"en": "Opening net value + additions − disposals − charge = closing net value", "fr": "Valeur nette d'ouverture + acquisitions − cessions − dotation = valeur nette de clôture"}),
        ("limits", {"en": "Accumulated depreciation not above cost, no negative net value", "fr": "Amortissements cumulés inférieurs à la valeur brute, aucune valeur nette négative"}),
        ("disposal", {"en": "Disposal dates after acquisition and inside the period", "fr": "Dates de cession après l'acquisition et dans la période"}),
        ("rate", {"en": "Depreciation rates between 0 and 100 %", "fr": "Taux d'amortissement entre 0 et 100 %"}),
        ("charge", {"en": "Charge of the year recomputed from cost × rate × time", "fr": "Dotation de l'exercice recalculée : valeur brute × taux × temps"}),
    ],
    "payroll_register": [
        ("rows", _COMMON["rows"]),
        ("mandatory", _COMMON["mandatory"]),
        ("values", _COMMON["values"]),
        ("period", {"en": "Pay months inside the period of the file", "fr": "Mois de paie dans la période du fichier"}),
        ("duplicates", _COMMON["duplicates"]),
        ("down", _COMMON["down"]),
        ("names", _COMMON["names"]),
        ("once", {"en": "Each employee at most once per month", "fr": "Chaque salarié au plus une fois par mois"}),
        ("grossnet", {"en": "Gross pay not below net pay", "fr": "Salaire brut au moins égal au salaire net"}),
        ("gross", {"en": "Gross = base + allowances + overtime + benefits", "fr": "Brut = base + indemnités + heures supplémentaires + avantages"}),
        ("net", {"en": "Net = gross − employee deductions", "fr": "Net = brut − retenues salariales"}),
        ("hire", {"en": "Hire dates not after the period end", "fr": "Dates d'embauche antérieures à la clôture"}),
        ("leaving", {"en": "Leaving dates not before hire dates", "fr": "Dates de sortie postérieures aux dates d'embauche"}),
        ("pay", {"en": "No zero or negative pay", "fr": "Aucune paie nulle ou négative"}),
    ],
    "ar_open_items": [
        ("rows", _COMMON["rows"]),
        ("mandatory", _COMMON["mandatory"]),
        ("values", _COMMON["values"]),
        ("period", {"en": "Invoice dates not after the period end", "fr": "Dates de facture antérieures à la clôture"}),
        ("duplicates", _COMMON["duplicates"]),
        ("down", _COMMON["down"]),
        ("names", {"en": "Each customer number has one name", "fr": "Chaque numéro client a un seul nom"}),
        ("unique", {"en": "Invoice numbers used once", "fr": "Numéros de facture utilisés une seule fois"}),
        ("sequence", {"en": "Invoice numbers in sequence (gaps listed)", "fr": "Numéros de facture séquentiels (trous listés)"}),
        ("aged", {"en": "Items older than 12 months", "fr": "Éléments de plus de 12 mois"}),
        ("sign", {"en": "Credit notes negative, invoices positive", "fr": "Avoirs négatifs, factures positives"}),
        ("zero", {"en": "No item with a zero amount", "fr": "Aucun élément à montant nul"}),
        ("byparty", {"en": "Total by customer recomputed", "fr": "Total par client recalculé"}),
    ],
    "ap_open_items": [
        ("rows", _COMMON["rows"]),
        ("mandatory", _COMMON["mandatory"]),
        ("values", _COMMON["values"]),
        ("period", {"en": "Invoice dates not after the period end", "fr": "Dates de facture antérieures à la clôture"}),
        ("duplicates", _COMMON["duplicates"]),
        ("down", _COMMON["down"]),
        ("names", {"en": "Each supplier number has one name", "fr": "Chaque numéro fournisseur a un seul nom"}),
        ("unique", {"en": "Invoice numbers used once per supplier", "fr": "Numéros de facture utilisés une seule fois par fournisseur"}),
        ("aged", {"en": "Items older than 12 months", "fr": "Éléments de plus de 12 mois"}),
        ("sign", {"en": "Credit notes negative, invoices positive", "fr": "Avoirs négatifs, factures positives"}),
        ("zero", {"en": "No item with a zero amount", "fr": "Aucun élément à montant nul"}),
        ("byparty", {"en": "Total by supplier recomputed", "fr": "Total par fournisseur recalculé"}),
    ],
    "inventory_listing": [
        ("rows", _COMMON["rows"]),
        ("mandatory", _COMMON["mandatory"]),
        ("values", _COMMON["values"]),
        ("duplicates", _COMMON["duplicates"]),
        ("down", _COMMON["down"]),
        ("names", _COMMON["names"]),
        ("unique", {"en": "Item codes used once per location", "fr": "Codes article utilisés une seule fois par emplacement"}),
        ("extend", {"en": "Quantity × unit price = amount", "fr": "Quantité × prix unitaire = montant"}),
        ("negative", {"en": "No negative quantity or price", "fr": "Aucune quantité ni aucun prix négatif"}),
        ("zerocost", {"en": "Items at zero cost", "fr": "Articles à coût nul"}),
    ],
}


def catalogue(kind):
    """[{code, key, en, fr}] of a kind, in order: GL-01, GL-02..."""
    prefix = KIND_CODES[kind]
    return [
        {"code": "%s-%02d" % (prefix, position), "key": key, "en": title["en"], "fr": title["fr"]}
        for position, (key, title) in enumerate(CATALOGUE[kind], start=1)
    ]


def _codes(kind):
    return {entry["key"]: entry["code"] for entry in catalogue(kind)}


def _finish(kind, results):
    """The results in catalogue order, each with its title."""
    titles = {entry["code"]: entry for entry in catalogue(kind)}
    out = []
    for result in results:
        entry = titles[result["code"]]
        out.append(dict(result, key=entry["key"], en=entry["en"], fr=entry["fr"]))
    order = [entry["code"] for entry in catalogue(kind)]
    return sorted(out, key=lambda result: order.index(result["code"]))


def score(results):
    """(applicable, without exceptions, with exceptions): "Reliable · 13/13"."""
    applicable = [result for result in results if result["status"] != NA]
    failing = [result for result in applicable if result["status"] == EXCEPTIONS]
    return len(applicable), len(applicable) - len(failing), len(failing)


# ----------------------------------------------------------------------
# Trial balance
# ----------------------------------------------------------------------

def run_trial_balance(data, context):
    """``data``: the kept account lines, with the typed columns _od, _oc, _d, _c (opening debit,
    opening credit, debit, credit as the import read them), "account" and "label", and the raw
    cells under the file's headers. ``context``: rows_read, left_out [{row, text, total, amounts
    {field: value}}], prior_closings {account: closing} or None."""
    c = _codes("trial_balance")
    mapping = data.mapping
    amount_fields = [field for field in ("openingDebit", "openingCredit", "opening", "debit", "credit", "closingDebit", "closingCredit", "closing") if data.has(field)]
    accounts = data.columns["account"]
    labels = data.columns.get("label") or [""] * data.n
    od, oc, d, cr = (data.columns[key] for key in ("_od", "_oc", "_d", "_c"))
    closing = [od[i] - oc[i] + d[i] - cr[i] for i in range(data.n)]
    results = []

    left_out = context.get("left_out") or []
    left = [
        (line.get("row"), "Left out: amounts with no account code", "Écartée : des montants sans numéro de compte")
        for line in left_out
        if not line.get("total") and any(value not in (None, "", 0) for value in (line.get("amounts") or {}).values())
    ]
    check = Check(c["rows"])
    base = check_rows(c["rows"], data, context.get("rows_read"), (), set_apart=len(left_out))
    for row, en, fr in left:
        check.add(row=row, en=en, fr=fr)
    for line in base["lines"]:
        check.add(**{key: line[key] for key in ("row", "ref", "column", "value", "en", "fr", "amount", "expected")})
    results.append(check.says(base["note"]).result())

    check = Check(c["mandatory"])
    raws = [data.raw(field) for field in amount_fields]
    for i in range(data.n):
        if raws and all(_blank(column[i]) for column in raws):
            check.add(row=data.rows[i], ref=accounts[i], en="No figure in any amount column", fr="Aucun chiffre dans les colonnes de montant")
    if not check.count:
        check.says(_d("Every account line has its figures.", "Chaque ligne de compte porte ses chiffres."))
    results.append(check.result())

    results.append(check_values(c["values"], data, amount_fields=amount_fields))

    check = Check(c["down"])
    totals = {field: _total(data.num(field)) for field in amount_fields}
    stated_lines = [line for line in (context.get("left_out") or []) if line.get("total")]
    words_en = "; ".join("%s %s" % (data.header(field), amount_text(totals[field], "en")) for field in amount_fields)
    words_fr = " ; ".join("%s %s" % (data.header(field), amount_text(totals[field], "fr")) for field in amount_fields)
    if not stated_lines:
        check.status = INFO
        check.says(_d("No total line in the file. Totals recomputed: %s." % words_en, "Pas de ligne de total dans le fichier. Totaux recalculés : %s." % words_fr))
    else:
        last = stated_lines[-1]
        for field in amount_fields:
            stated = parse_amount((last.get("amounts") or {}).get(field))
            if stated is not None and not _close(stated, totals[field], 0.5):
                check.add(row=last.get("row"), column=data.header(field), amount=stated, expected=totals[field],
                          en="The file's total differs from the lines by %s" % amount_text(stated - totals[field], "en"),
                          fr="Le total du fichier diffère des lignes de %s" % amount_text(stated - totals[field], "fr"))
        check.says(_d("Totals recomputed: %s." % words_en, "Totaux recalculés : %s." % words_fr))
    results.append(check.result())

    check = Check(c["balanced"])
    total_d, total_c = _total(d), _total(cr)
    opening_net, closing_net = _total(od) - _total(oc), _total(closing)
    if not _close(total_d, total_c, 0.01):
        check.add(ref="Debit / Credit", amount=total_d, expected=total_c,
                  en="Total debits %s, total credits %s" % (amount_text(total_d, "en"), amount_text(total_c, "en")),
                  fr="Total des débits %s, total des crédits %s" % (amount_text(total_d, "fr"), amount_text(total_c, "fr")))
    if not _close(opening_net, 0, 0.01):
        check.add(amount=opening_net, expected=0, en="Opening balances net to %s" % amount_text(opening_net, "en"),
                  fr="Les soldes d'ouverture se soldent à %s" % amount_text(opening_net, "fr"))
    if not _close(closing_net, 0, 0.01):
        check.add(amount=closing_net, expected=0, en="Closing balances net to %s" % amount_text(closing_net, "en"),
                  fr="Les soldes de clôture se soldent à %s" % amount_text(closing_net, "fr"))
    results.append(check.says(
        _d("Debits %s, credits %s." % (amount_text(total_d, "en"), amount_text(total_c, "en")),
        "Débits %s, crédits %s." % (amount_text(total_d, "fr"), amount_text(total_c, "fr"))),
    ).result())

    has_movements = data.has("debit") or data.has("credit")
    closing_fields = [field for field in ("closingDebit", "closingCredit", "closing") if data.has(field)]
    if has_movements and closing_fields:
        if data.has("closingDebit") or data.has("closingCredit"):
            file_closing = [a - b for a, b in zip(_num0(data, "closingDebit"), _num0(data, "closingCredit"))]
        else:
            file_closing = _num0(data, "closing")
        check = Check(c["equation"])
        for i in range(data.n):
            if not _close(closing[i], file_closing[i], 0.5):
                check.add(row=data.rows[i], ref=accounts[i], amount=file_closing[i], expected=closing[i],
                          en="Closing in the file %s, recomputed %s" % (amount_text(file_closing[i], "en"), amount_text(closing[i], "en")),
                          fr="Clôture du fichier %s, recalculée %s" % (amount_text(file_closing[i], "fr"), amount_text(closing[i], "fr")))
        if not check.count:
            check.says(_d("Every account adds across.", "Chaque compte s'additionne correctement."))
        results.append(check.result())
    else:
        results.append(not_applicable(c["equation"], _d("The file has not both movement and closing columns.", "Le fichier n'a pas à la fois des colonnes de mouvements et de clôture.")))

    check = Check(c["unique"])
    seen = {}
    for i in range(data.n):
        if accounts[i] in seen:
            check.add(row=data.rows[i], ref=accounts[i], value=str(seen[accounts[i]]), en="Already on line %s" % seen[accounts[i]], fr="Déjà à la ligne %s" % seen[accounts[i]])
        else:
            seen[accounts[i]] = data.rows[i]
    if not check.count:
        check.says(_d("Every account code is used once.", "Chaque numéro de compte n'est utilisé qu'une fois."))
    results.append(check.result())

    check = Check(c["form"])
    for i in range(data.n):
        if not re.match(r"^[1-9][0-9]*$", accounts[i] or ""):
            check.add(row=data.rows[i], ref=accounts[i], value=accounts[i], en="Not a SYSCOHADA account code", fr="N'est pas un numéro de compte SYSCOHADA")
    if not check.count:
        check.says(_d("Every account code starts with a class from 1 to 9.", "Chaque numéro de compte commence par une classe de 1 à 9."))
    results.append(check.result())

    if "label" in mapping:
        check = Check(c["noname"])
        for i in range(data.n):
            if not (labels[i] or "").strip() and not _close(closing[i], 0):
                check.add(row=data.rows[i], ref=accounts[i], amount=closing[i], en="Balance but no name", fr="Solde mais aucun libellé")
        results.append(check.result())
    else:
        results.append(not_applicable(c["noname"], _d("The file has no account name column.", "Le fichier n'a pas de colonne de libellé.")))

    prior = context.get("prior_closings")
    if prior is None:
        results.append(not_applicable(c["prior"], _d("No prior-year trial balance to compare with.", "Aucune balance de l'exercice précédent à comparer.")))
    else:
        check = Check(c["prior"])
        opening = {}
        first_row = {}
        for i in range(data.n):
            opening[accounts[i]] = opening.get(accounts[i], 0) + od[i] - oc[i]
            first_row.setdefault(accounts[i], data.rows[i])
        for account in sorted(set(opening) | set(prior)):
            here, there = opening.get(account, 0), prior.get(account, 0) or 0
            if not _close(here, there, 0.5):
                check.add(row=first_row.get(account), ref=account, amount=here, expected=there,
                          en="Opening %s, prior-year closing %s" % (amount_text(here, "en"), amount_text(there, "en")),
                          fr="Ouverture %s, clôture précédente %s" % (amount_text(here, "fr"), amount_text(there, "fr")))
        if not check.count:
            check.says(_d("Every opening balance equals last year's closing balance.", "Chaque solde d'ouverture est égal au solde de clôture de l'exercice précédent."))
        results.append(check.result())

    check = Check(c["suspense"])
    for i in range(data.n):
        if (accounts[i] or "").startswith("47") and not _close(closing[i], 0):
            check.add(row=data.rows[i], ref=accounts[i], value=(labels[i] or "")[:80], amount=closing[i],
                      en="Suspense account with a balance", fr="Compte d'attente avec un solde", count=False)
    if check.lines:
        check.status = INFO
        check.says(_d("%d waiting or suspense account(s) with a balance: for information." % len(check.lines),
                   "%d compte(s) d'attente avec un solde : pour information." % len(check.lines)))
    results.append(check.result())
    return _finish("trial_balance", results)


# ----------------------------------------------------------------------
# General ledger
# ----------------------------------------------------------------------

def _entry_ids(data):
    """The entry identity of each row: the entry number, or the columns that identify it."""
    keys = je_key_columns(data.mapping) if data.mapping.get("jeKey") else []
    if keys:
        columns = [data.columns.get(header) or [None] * data.n for header in keys]
        out = []
        for i in range(data.n):
            row = {header: column[i] for header, column in zip(keys, columns)}
            out.append(je_identity(row, keys, None, lambda value: js_trim(cell_str(value)) or None) or "")
        return out
    return data.text("jeNumber")


def run_general_ledger(data, context):
    """``context``: rows_read, period (start, end), timing, extraction_date (ISO or None)."""
    c = _codes("journal_entries")
    start, end = context.get("period") or (None, None)
    entries = _entry_ids(data)
    accounts = data.text("account")
    pair = data.has("debit") and data.has("credit")
    if pair:
        debit, credit = _num0(data, "debit"), _num0(data, "credit")
    else:
        amount = _num0(data, "amount")
        debit = [value if value > 0 else 0 for value in amount]
        credit = [-value if value < 0 else 0 for value in amount]
    mark_total_lines(data, ["account", "jeNumber"], ["jeDescription"], ["debit", "credit", "amount"])
    results = []

    left = [
        (data.rows[i], "Left out of the ledger: no account or no entry number", "Écartée du grand livre : sans compte ou sans numéro d'écriture")
        for i in data.kept() if not accounts[i] or not entries[i]
    ]
    results.append(check_rows(c["rows"], data, context.get("rows_read"), left))
    lines = [i for i in data.kept() if accounts[i] and entries[i]]

    mandatory = ["account", "journalDate", "jeDescription"] + (["jeNumber"] if data.has("jeNumber") else [])
    results.append(check_mandatory(c["mandatory"], data, mandatory + ([] if pair else ["amount"]), amount_pair=("debit", "credit") if pair else None))
    results.append(check_values(c["values"], data, amount_fields=("debit", "credit", "amount"), date_fields=("journalDate", "jeDate"), account_fields=("account",)))
    results.append(check_dates_in_period(c["period"], data, "journalDate", start, end, context.get("timing")))
    results.append(check_duplicates(c["duplicates"], data))
    results.append(check_totals_down(c["down"], data, ["debit", "credit"] if pair else ["amount"]))
    results.append(check_same_name(c["names"], data, [("account", "accountName"), ("thirdPartyCode", "thirdPartyName")]))

    by_entry, order = {}, []
    for i in lines:
        entry = entries[i]
        if entry not in by_entry:
            by_entry[entry] = [0.0, data.rows[i]]
            order.append(entry)
        by_entry[entry][0] += debit[i] - credit[i]
    check = Check(c["entries"])
    for entry in order:
        difference, row = by_entry[entry]
        if abs(difference) > TOLERANCE:
            check.add(row=row, ref=entry, amount=difference, en="Out of balance by %s" % amount_text(difference, "en"),
                      fr="Déséquilibrée de %s" % amount_text(difference, "fr"))
    results.append(check.says(_d("%d entries read." % len(order), "%d écritures lues." % len(order))).result())

    total_d = _total(debit[i] for i in lines)
    total_c = _total(credit[i] for i in lines)
    check = Check(c["ledger"])
    if not _close(total_d, total_c, 0.01):
        check.add(amount=total_d, expected=total_c, en="Debits and credits differ by %s" % amount_text(total_d - total_c, "en"),
                  fr="Les débits et les crédits diffèrent de %s" % amount_text(total_d - total_c, "fr"))
    results.append(check.says(_d("Debits %s, credits %s." % (amount_text(total_d, "en"), amount_text(total_c, "en")),
                              "Débits %s, crédits %s." % (amount_text(total_d, "fr"), amount_text(total_c, "fr")))).result())

    if data.has("jeNumber"):
        results.append(check_sequence(c["sequence"], data, "jeNumber", "journalCode"))
    else:
        results.append(not_applicable(c["sequence"], _d("Entries are identified by several columns: no number to follow.", "Les écritures sont identifiées par plusieurs colonnes : aucun numéro à suivre.")))

    line_set = set(lines)
    if pair:
        results.append(check_rows_where(
            c["both"], data, [],
            lambda i: (entries[i], "Debit and credit on one line", "Débit et crédit sur une même ligne") if i in line_set and debit[i] and credit[i] else None,
            _d("Each line is a debit or a credit.", "Chaque ligne est un débit ou un crédit.")))
    else:
        results.append(not_applicable(c["both"], _d("The file has one amount column, not a debit and a credit.", "Le fichier a une colonne de montant, pas un débit et un crédit.")))

    results.append(check_rows_where(
        c["zero"], data, [], lambda i: (entries[i], "Zero amount", "Montant nul") if i in line_set and not debit[i] and not credit[i] else None,
        _d("No line has a zero amount.", "Aucune ligne n'a un montant nul.")))

    extraction = context.get("extraction_date")
    if not extraction:
        results.append(not_applicable(c["extraction"], _d("Enter the extraction date under \"Where the data comes from\".", "Saisissez la date d'extraction dans « D'où viennent les données ».")))
    elif not data.has("journalDate"):
        results.append(not_applicable(c["extraction"], _d("The file has no date column.", "Le fichier n'a pas de colonne de date.")))
    else:
        dates = data.date("journalDate")
        results.append(check_rows_where(
            c["extraction"], data, [], lambda i: (date_text(dates[i]), "Dated after the extraction date", "Datée après la date d'extraction")
            if i in line_set and dates[i] and dates[i] > extraction else None,
            _d("Extraction date %s." % date_text(extraction), "Date d'extraction %s." % date_text(extraction)), column=data.header("journalDate")))

    people = [field for field in ("preparedBy", "recordedBy", "approvedBy") if data.has(field)]
    if people:
        check = Check(c["people"])
        for field in people:
            texts = data.text(field)
            for i in lines:
                if not texts[i]:
                    check.add(row=data.rows[i], ref=entries[i], column=data.header(field), en="Blank cell", fr="Cellule vide")
        results.append(check.says(_d("Columns read: %s." % ", ".join(data.header(field) for field in people),
                                  "Colonnes lues : %s." % ", ".join(data.header(field) for field in people))).result())
    else:
        results.append(not_applicable(c["people"], _d("The file has no preparer or approver column.", "Le fichier n'a pas de colonne de préparateur ni d'approbateur.")))

    dates = data.date("journalDate") if data.has("journalDate") else [None] * data.n
    totals = {}
    for i in lines:
        key = (accounts[i], (dates[i] or "")[:7])
        found = totals.setdefault(key, [0.0, 0.0])
        found[0] += debit[i]
        found[1] += credit[i]
    check = Check(c["bymonth"], cap=TOTALS_CAP)
    check.status = INFO
    for (account, month), (dr, cr_) in sorted(totals.items()):
        check.add(ref=account, value=month, amount=dr, expected=cr_, count=False,
                  en="Debit %s, credit %s" % (amount_text(dr, "en"), amount_text(cr_, "en")),
                  fr="Débit %s, crédit %s" % (amount_text(dr, "fr"), amount_text(cr_, "fr")))
    results.append(check.says(_d("%d account and month totals: in the Excel download." % len(totals),
                              "%d totaux par compte et par mois : dans le téléchargement Excel." % len(totals))).result())
    return _finish("journal_entries", results)


# ----------------------------------------------------------------------
# Fixed asset register
# ----------------------------------------------------------------------

FA_AMOUNTS = ("amount", "depreciation", "nbv", "openingNbv", "additions", "disposals", "disposalsCost", "charge", "proceeds")


def run_fixed_assets(data, context):
    c = _codes("fixed_asset_register")
    start, end = context.get("period") or (None, None)
    mark_total_lines(data, ["item"], ["itemDescription", "category"], FA_AMOUNTS)
    results = [check_rows(c["rows"], data, context.get("rows_read"))]
    results.append(check_mandatory(c["mandatory"], data, ["item", "itemDescription", "amount", "category", "acquisitionDate", "depreciationRate"]))
    results.append(check_values(c["values"], data, amount_fields=FA_AMOUNTS + ("depreciationRate",), date_fields=("acquisitionDate", "disposalDate")))
    results.append(check_dates_in_period(c["period"], data, "acquisitionDate", start, end, context.get("timing"), upper_only=True))
    results.append(check_duplicates(c["duplicates"], data))
    results.append(check_totals_down(c["down"], data, FA_AMOUNTS))
    results.append(check_unique(c["unique"], data, ["item"], _d("asset number", "numéro d'immobilisation")))
    cost, dep, nbv = _num0(data, "amount"), _num0(data, "depreciation"), _num0(data, "nbv")
    results.append(check_formula(c["net"], data, ["amount", "depreciation", "nbv"], lambda i: (nbv[i], cost[i] - dep[i]),
                                 _d("Net value = cost − accumulated depreciation.", "Valeur nette = valeur brute − amortissements cumulés.")))
    opening, additions, disposals, charge = _num0(data, "openingNbv"), _num0(data, "additions"), _num0(data, "disposals"), _num0(data, "charge")
    results.append(check_formula(c["rollforward"], data, ["openingNbv", "charge", "nbv"],
                                 lambda i: (nbv[i], opening[i] + additions[i] - disposals[i] - charge[i]),
                                 _d("Closing net value = opening + additions − disposals − charge.",
                                 "Valeur nette de clôture = ouverture + acquisitions − cessions − dotation.")))
    if data.has("depreciation") or data.has("nbv"):
        def limits(i):
            if data.has("depreciation") and dep[i] > cost[i] + 0.5:
                return (amount_text(dep[i], "en"), "Accumulated depreciation above cost", "Amortissements cumulés supérieurs à la valeur brute")
            if data.has("nbv") and nbv[i] < -0.5:
                return (amount_text(nbv[i], "en"), "Negative net value", "Valeur nette négative")
            return None
        results.append(check_rows_where(c["limits"], data, ["amount"], limits, _d("Every asset within its cost.", "Chaque immobilisation dans les limites de sa valeur brute.")))
    else:
        results.append(not_applicable(c["limits"], _d("The file has no accumulated depreciation or net value column.", "Le fichier n'a pas de colonne d'amortissements cumulés ni de valeur nette.")))
    acquired = data.date("acquisitionDate") if data.has("acquisitionDate") else [None] * data.n
    if data.has("disposalDate"):
        disposed = data.date("disposalDate")

        def disposal(i):
            if not disposed[i]:
                return None
            if acquired[i] and disposed[i] < acquired[i]:
                return (date_text(disposed[i]), "Disposed before it was acquired", "Cédée avant son acquisition")
            if start and (disposed[i] < start or disposed[i] > end):
                return (date_text(disposed[i]), "Disposal outside the period", "Cession hors de la période")
            return None
        results.append(check_rows_where(c["disposal"], data, [], disposal, _d("Disposal dates checked.", "Dates de cession contrôlées."), column=data.header("disposalDate")))
    else:
        results.append(not_applicable(c["disposal"], _d("The file has no disposal date column.", "Le fichier n'a pas de colonne de date de cession.")))
    raw_rate = data.raw("depreciationRate")
    rates = [depreciation_rate(value) for value in raw_rate] if data.has("depreciationRate") else [None] * data.n
    results.append(check_rows_where(
        c["rate"], data, ["depreciationRate"],
        lambda i: (_cell(raw_rate[i]), "Rate outside 0 to 100 %", "Taux hors de 0 à 100 %") if rates[i] is None and not _blank(raw_rate[i]) else None,
        _d("Every rate is between 0 and 100 %.", "Chaque taux est compris entre 0 et 100 %."), column=data.header("depreciationRate")))
    if start and not _missing_columns(data, ["amount", "depreciationRate", "acquisitionDate", "charge"]):
        disposed = data.date("disposalDate") if data.has("disposalDate") else [None] * data.n
        days_period = day_number(end) - day_number(start) + 1

        def expected_charge(i):
            if rates[i] is None or not acquired[i]:
                return None
            first = max(acquired[i], start)
            last = min(disposed[i] or end, end)
            if first > last:
                return (charge[i], 0.0)
            days = day_number(last) - day_number(first) + 1
            value = cost[i] * rates[i] / 100 * days / days_period
            if data.has("openingNbv") and (data.has("additions") or acquired[i] < start):
                # no more than the value left to depreciate
                value = min(value, max(opening[i] + additions[i], 0))
            return (charge[i], value)
        results.append(check_formula(c["charge"], data, ["amount", "depreciationRate", "acquisitionDate", "charge"], expected_charge,
                                     _d("Charge = cost × rate × days in use ÷ days in the period, 2 % tolerance.",
                                     "Dotation = valeur brute × taux × jours d'utilisation ÷ jours de la période, tolérance de 2 %."),
                                     tolerance=1, relative=CHARGE_TOLERANCE))
    else:
        results.append(not_applicable(c["charge"], _d("The file has not the cost, rate, acquisition date and charge columns.", "Le fichier n'a pas les colonnes de valeur brute, taux, date d'acquisition et dotation.")))
    return _finish("fixed_asset_register", results)


# ----------------------------------------------------------------------
# Payroll register
# ----------------------------------------------------------------------

PAY_AMOUNTS = ("amount", "net", "baseSalary", "allowances", "benefitsInKind", "overtime", "incomeTax", "socialEmployee", "socialEmployer", "otherEmployerCharges")
_MONTH = (re.compile(r"^(\d{4})[-/.](\d{1,2})$"), re.compile(r"^(\d{1,2})[-/.](\d{4})$"))


def pay_month(value):
    """yyyy-mm of a pay period cell: 2025-03, 03/2025 or a date; None otherwise."""
    if value is None:
        return None
    text = js_trim(cell_str(value))
    match = _MONTH[0].match(text)
    if match and 1 <= int(match[2]) <= 12:
        return "%s-%02d" % (match[1], int(match[2]))
    match = _MONTH[1].match(text)
    if match and 1 <= int(match[1]) <= 12:
        return "%s-%02d" % (match[2], int(match[1]))
    iso = parse_date_iso(value)
    return iso[:7] if iso else None


def run_payroll(data, context):
    c = _codes("payroll_register")
    start, end = context.get("period") or (None, None)
    mark_total_lines(data, ["party"], ["partyName"], PAY_AMOUNTS)
    results = [check_rows(c["rows"], data, context.get("rows_read"))]
    results.append(check_mandatory(c["mandatory"], data, ["party", "partyName", "amount"]))
    results.append(check_values(c["values"], data, amount_fields=PAY_AMOUNTS, date_fields=("hireDate", "leavingDate")))
    if data.has("period") and start:
        months = [pay_month(value) for value in data.raw("period")]
        results.append(check_rows_where(
            c["period"], data, ["period"],
            lambda i: (months[i], "Pay month outside the period", "Mois de paie hors de la période") if months[i] and (months[i] < start[:7] or months[i] > end[:7]) else None,
            _d("The period is %s to %s." % (date_text(start), date_text(end)), "La période va du %s au %s." % (date_text(start), date_text(end))),
            column=data.header("period")))
    else:
        results.append(not_applicable(c["period"], _d("The file has no month or period column.", "Le fichier n'a pas de colonne de mois ou de période.")))
    results.append(check_duplicates(c["duplicates"], data))
    results.append(check_totals_down(c["down"], data, PAY_AMOUNTS))
    results.append(check_same_name(c["names"], data, [("party", "partyName")]))
    results.append(check_unique(c["once"], data, ["party", "period"] if data.has("period") else ["party"], _d("employee number", "matricule")))
    gross, net = _num0(data, "amount"), _num0(data, "net")
    results.append(check_rows_where(
        c["grossnet"], data, ["amount", "net"],
        lambda i: (amount_text(net[i], "en"), "Net pay above gross pay", "Salaire net supérieur au brut") if net[i] > gross[i] + 0.5 else None,
        _d("Gross pay compared with net pay.", "Salaire brut comparé au salaire net.")))
    base, allowances, overtime, benefits = (_num0(data, key) for key in ("baseSalary", "allowances", "overtime", "benefitsInKind"))
    results.append(check_formula(c["gross"], data, ["amount", "baseSalary"], lambda i: (gross[i], base[i] + allowances[i] + overtime[i] + benefits[i]),
                                 _d("Gross = base + allowances + overtime + benefits (the columns given).",
                                 "Brut = base + indemnités + heures supplémentaires + avantages (les colonnes fournies).")))
    if data.has("net") and (data.has("incomeTax") or data.has("socialEmployee")):
        tax, social = _num0(data, "incomeTax"), _num0(data, "socialEmployee")
        results.append(check_formula(c["net"], data, ["amount", "net"], lambda i: (net[i], gross[i] - tax[i] - social[i]),
                                     _d("Net = gross − income tax withheld − employee social security.",
                                     "Net = brut − IRPP retenu − part salariale de la CNPS.")))
    else:
        results.append(not_applicable(c["net"], _d("The file has not the net pay and employee deduction columns.", "Le fichier n'a pas les colonnes de salaire net et de retenues salariales.")))
    hired = data.date("hireDate") if data.has("hireDate") else [None] * data.n
    results.append(check_rows_where(
        c["hire"], data, ["hireDate"],
        lambda i: (date_text(hired[i]), "Hired after the period end", "Embauché après la clôture") if hired[i] and end and hired[i] > end else None,
        _d("Hire dates checked.", "Dates d'embauche contrôlées."), column=data.header("hireDate")))
    left = data.date("leavingDate") if data.has("leavingDate") else [None] * data.n
    results.append(check_rows_where(
        c["leaving"], data, ["hireDate", "leavingDate"],
        lambda i: (date_text(left[i]), "Left before being hired", "Sorti avant son embauche") if left[i] and hired[i] and left[i] < hired[i] else None,
        _d("Leaving dates checked.", "Dates de sortie contrôlées."), column=data.header("leavingDate")))

    def pay(i):
        if gross[i] <= 0:
            return (amount_text(gross[i], "en"), "Zero or negative gross pay", "Salaire brut nul ou négatif")
        if data.has("net") and net[i] <= 0:
            return (amount_text(net[i], "en"), "Zero or negative net pay", "Salaire net nul ou négatif")
        return None
    results.append(check_rows_where(c["pay"], data, ["amount"], pay, _d("Every pay is above zero.", "Chaque paie est supérieure à zéro.")))
    return _finish("payroll_register", results)


# ----------------------------------------------------------------------
# Receivables and payables open items
# ----------------------------------------------------------------------

_CREDIT_NOTE = re.compile(r"avoir|credit|crédit|\bav\b|\bcn\b", re.I)  # i18n: input
_INVOICE = re.compile(r"factur|invoice|\bfa\b|\binv\b", re.I)  # i18n: input


def run_open_items(kind, data, context):
    """Receivables (``ar_open_items``) or payables (``ap_open_items``). ``context["aged_before"]``:
    the ISO date 12 months before the period end."""
    c = _codes(kind)
    start, end = context.get("period") or (None, None)
    mark_total_lines(data, ["party", "reference"], ["partyName"], ["amount"])
    results = [check_rows(c["rows"], data, context.get("rows_read"))]
    results.append(check_mandatory(c["mandatory"], data, ["party", "partyName", "reference", "date", "amount"]))
    results.append(check_values(c["values"], data, amount_fields=("amount",), date_fields=("date",)))
    results.append(check_dates_in_period(c["period"], data, "date", start, end, context.get("timing"), upper_only=True))
    results.append(check_duplicates(c["duplicates"], data))
    results.append(check_totals_down(c["down"], data, ["amount"]))
    results.append(check_same_name(c["names"], data, [("party", "partyName")], need_name=True))
    if kind == "ar_open_items":
        results.append(check_unique(c["unique"], data, ["reference"], _d("invoice number", "numéro de facture")))
        results.append(check_sequence(c["sequence"], data, "reference", status_if_gaps=INFO))
    else:
        results.append(check_unique(c["unique"], data, ["reference", "party"], _d("invoice number", "numéro de facture")))
    aged = context.get("aged_before")
    dates = data.date("date") if data.has("date") else [None] * data.n
    amounts = _num0(data, "amount")
    if aged and data.has("date"):
        results.append(check_rows_where(
            c["aged"], data, ["date"],
            lambda i: (date_text(dates[i]), "Older than 12 months: %s" % amount_text(amounts[i], "en"), "Plus de 12 mois : %s" % amount_text(amounts[i], "fr"))
            if dates[i] and dates[i] < aged else None,
            _d("Items dated before %s: for information." % date_text(aged), "Éléments datés avant le %s : pour information." % date_text(aged)),
            status=INFO, column=data.header("date")))
    else:
        results.append(not_applicable(c["aged"], _d("The file has no date column.", "Le fichier n'a pas de colonne de date.")))
    types = data.text("transactionType") if data.has("transactionType") else None

    def sign(i):
        if _CREDIT_NOTE.search(types[i]) and amounts[i] > 0:
            return (types[i], "Credit note with a positive amount", "Avoir de montant positif")
        if _INVOICE.search(types[i]) and not _CREDIT_NOTE.search(types[i]) and amounts[i] < 0:
            return (types[i], "Invoice with a negative amount", "Facture de montant négatif")
        return None
    results.append(check_rows_where(c["sign"], data, ["transactionType", "amount"], sign, _d("Signs read from the transaction type.", "Signes lus d'après le type de transaction."),
                                    column=data.header("transactionType")))
    results.append(check_rows_where(c["zero"], data, ["amount"], lambda i: ("0", "Zero amount", "Montant nul") if not amounts[i] else None,
                                    _d("No item has a zero amount.", "Aucun élément n'a un montant nul.")))
    if data.has("party"):
        parties, names = data.text("party"), data.text("partyName")
        by_party = {}
        for i in data.kept():
            found = by_party.setdefault(parties[i], [0.0, names[i]])
            found[0] += amounts[i]
        check = Check(c["byparty"], cap=TOTALS_CAP)
        check.status = INFO
        for party, (total, name) in sorted(by_party.items()):
            check.add(ref=party, value=name, amount=total, en=amount_text(total, "en"), fr=amount_text(total, "fr"), count=False)
        results.append(check.says(_d("%d totals: in the Excel download." % len(by_party), "%d totaux : dans le téléchargement Excel." % len(by_party))).result())
    else:
        results.append(not_applicable(c["byparty"], _d("The file has no customer or supplier number column.", "Le fichier n'a pas de colonne de numéro de tiers.")))
    return _finish(kind, results)


# ----------------------------------------------------------------------
# Inventory listing
# ----------------------------------------------------------------------

def run_inventory(data, context):
    c = _codes("inventory_listing")
    mark_total_lines(data, ["item"], ["itemDescription"], ["quantity", "amount"])
    results = [check_rows(c["rows"], data, context.get("rows_read"))]
    results.append(check_mandatory(c["mandatory"], data, ["item", "itemDescription", "quantity", "unitPrice", "amount"]))
    results.append(check_values(c["values"], data, amount_fields=("quantity", "unitPrice", "amount")))
    results.append(check_duplicates(c["duplicates"], data))
    results.append(check_totals_down(c["down"], data, ["quantity", "amount"]))
    results.append(check_same_name(c["names"], data, [("item", "itemDescription")]))
    results.append(check_unique(c["unique"], data, ["item", "location"] if data.has("location") else ["item"], _d("item code", "code article")))
    quantity, price, amount = _num0(data, "quantity"), _num0(data, "unitPrice"), _num0(data, "amount")
    results.append(check_formula(c["extend"], data, ["quantity", "unitPrice", "amount"], lambda i: (amount[i], quantity[i] * price[i]),
                                 _d("Amount = quantity × unit price.", "Montant = quantité × prix unitaire."), tolerance=1, relative=0.0005))

    def negative(i):
        if quantity[i] < 0:
            return (str(quantity[i]), "Negative quantity", "Quantité négative")
        if price[i] < 0:
            return (amount_text(price[i], "en"), "Negative unit price", "Prix unitaire négatif")
        return None
    results.append(check_rows_where(c["negative"], data, ["quantity", "unitPrice"], negative, _d("Quantities and prices read.", "Quantités et prix lus.")))
    results.append(check_rows_where(
        c["zerocost"], data, ["quantity"],
        lambda i: (str(quantity[i]), "Quantity at zero cost", "Quantité à coût nul") if quantity[i] and not price[i] and not amount[i] else None,
        _d("Items held at no cost: for information.", "Articles détenus sans coût : pour information."), status=INFO))
    return _finish("inventory_listing", results)


def run(kind, data, context):
    """The checks of one file: [{code, key, en, fr, status, count, lines, note}]."""
    if kind == "trial_balance":
        return run_trial_balance(data, context)
    if kind == "journal_entries":
        return run_general_ledger(data, context)
    if kind == "fixed_asset_register":
        return run_fixed_assets(data, context)
    if kind == "payroll_register":
        return run_payroll(data, context)
    if kind in ("ar_open_items", "ap_open_items"):
        return run_open_items(kind, data, context)
    if kind == "inventory_listing":
        return run_inventory(data, context)
    raise ValueError(kind)


def chip(results, conclusion, has_file, explained):
    """The status of a box of the matrix: (state, tone, passed, applicable, to explain).
    ``explained``: the codes whose exceptions carry an explanation."""
    if not has_file:
        return {"state": "not_uploaded", "tone": "grey", "passed": 0, "applicable": 0, "toExplain": 0}
    applicable, passed, _failing = score(results)
    to_explain = len([r for r in results if r["status"] == EXCEPTIONS and r["code"] not in explained])
    if conclusion == "not_reliable":
        state, tone = "not_reliable", "red"
    elif to_explain:
        state, tone = "to_explain", "amber"
    elif conclusion == "reliable":
        state, tone = "reliable", "green"
    elif conclusion == "limitations":
        state, tone = "limitations", "amber"
    else:
        state, tone = "to_conclude", "amber"
    return {"state": state, "tone": tone, "passed": passed, "applicable": applicable, "toExplain": to_explain}
