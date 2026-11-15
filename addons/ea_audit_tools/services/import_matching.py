"""The matching step of an import, for the nine kinds of file: the fields a kind offers, the
ones it cannot do without, the guess made from the file, the reading options a person may set
over the readers' own guesses, and the figures of the check screen. No database here.

A mandatory field is needed by itself, or is one way among several of giving the same thing:
a trial balance states its amounts as movements, as a closing debit and credit, or as one
signed closing column.
"""
import re

from ._js import cell_str, is_number, js_str, js_trim, u16_slice
from .amount import parse_amount
from .dataset_mapping import FIELDS, JE_KEY, auto_map, encode_je_key, je_key_columns, norm
from .gl_line import TOLERANCE, mapped_fields, parse_date_iso, population_checks, projector
from .subledger_kinds import SUB_LEDGER_KINDS
from .subledgers import source_row_of
from .tb import EPSILON, alias_tb_mapping, heuristic_fill

TB_KIND = "trial_balance"
IMPORT_KINDS = [TB_KIND] + SUB_LEDGER_KINDS

#: The trial balance's fields, in the order the matching screen offers them.
TB_FIELDS = [
    {"key": "account", "en": "Account", "fr": "Compte", "required": True},
    {"key": "label", "en": "Description", "fr": "Libellé"},
    {"key": "openingDebit", "en": "Opening debit", "fr": "Ouverture débit"},
    {"key": "openingCredit", "en": "Opening credit", "fr": "Ouverture crédit"},
    {"key": "opening", "en": "Opening (signed)", "fr": "Ouverture (signé)"},
    {"key": "debit", "en": "Debit (movements)", "fr": "Débit (mouvements)"},
    {"key": "credit", "en": "Credit (movements)", "fr": "Crédit (mouvements)"},
    {"key": "closingDebit", "en": "Closing debit", "fr": "Clôture débit"},
    {"key": "closingCredit", "en": "Closing credit", "fr": "Clôture crédit"},
    {"key": "closing", "en": "Closing (signed)", "fr": "Clôture (signé)"},
]

#: One of its alternatives satisfies a group, and every field of an alternative is needed for it.
#: The first alternative is the usual one: its fields carry the star in the list of choices.
GROUPS = {
    TB_KIND: [
        {
            "key": "amounts", "en": "Amounts", "fr": "Montants",
            "alternatives": [["debit", "credit"], ["closingDebit", "closingCredit"], ["closing"]],
        },
    ],
    "journal_entries": [
        {"key": "entry", "en": "JE number", "fr": "Numéro d'écriture", "alternatives": [["jeNumber"], [JE_KEY]]},
        {"key": "amount", "en": "Amount", "fr": "Montant", "alternatives": [["amount"], ["debit", "credit"]]},
    ],
}

#: Shown for the entry identified by several columns, which is an option of the screen and no field.
JE_KEY_LABEL = {"en": "Entry identified by several columns", "fr": "Écriture identifiée par plusieurs colonnes"}
#: The choice that leaves a column of the file out.
SKIP_LABEL = {"en": "Do not import", "fr": "Ne pas importer"}

_AMOUNT_KEYS = {
    "openingDebit", "openingCredit", "opening", "debit", "credit", "closingDebit", "closingCredit", "closing",
    "amount", "quantity", "unitPrice", "depreciation", "nbv", "net",
}
_DATE_KEYS = {"date", "journalDate", "jeDate"}

#: How far a ledger's debits may be from its credits, in total and per entry, before it is refused:
#: the trial balance's own tolerance (owner's ruling of 2026-11-15, "an unbalanced general ledger
#: should be rejected").
BALANCE_TOLERANCE = EPSILON

DECIMALS = ("auto", "comma", "point")
DATE_FORMATS = ("auto", "dmy", "mdy", "ymd")

_THREE_DECIMALS = re.compile(r"\.\d{3}(?!\d)")
_DECIMAL_TAIL = re.compile(r"\d([.,])\d{1,2}\D*$")
_DATE_PARTS = re.compile(r"^(\d{1,4})[/.\-](\d{1,2})[/.\-](\d{1,4})(?:[T ].*)?$")
_YEAR_FIRST = re.compile(r"^\d{4}[/.\-]")


def fields_of(kind):
    """The fields a kind offers: [{key, en, fr, required}]."""
    return TB_FIELDS if kind == TB_KIND else FIELDS[kind]


def groups_of(kind):
    return GROUPS.get(kind, [])


def _grouped_keys(kind):
    return {key for group in groups_of(kind) for alternative in group["alternatives"] for key in alternative}


def required_keys(kind):
    """The fields needed by themselves: required in the catalogue and in no group."""
    grouped = _grouped_keys(kind)
    return [field["key"] for field in fields_of(kind) if field.get("required") and field["key"] not in grouped]


def starred_keys(kind):
    """The fields the list of choices marks: needed by themselves, or the usual way of a group."""
    return set(required_keys(kind)) | {key for group in groups_of(kind) for key in group["alternatives"][0]}


def _has(mapping, key):
    if key == JE_KEY:
        return bool(je_key_columns(mapping))
    header = (mapping or {}).get(key)
    return isinstance(header, str) and js_trim(header) != ""


def _satisfied(mapping, group):
    """The first alternative of a group the mapping gives whole, or None."""
    for alternative in group["alternatives"]:
        if all(_has(mapping, key) for key in alternative):
            return alternative
    return None


def missing_fields(kind, mapping):
    """What still stops the import: [{key, en, fr, alternatives}], where ``alternatives`` lists
    the keys of each way of giving a group, and is empty for a field needed by itself."""
    labels = {field["key"]: field for field in fields_of(kind)}
    out = []
    for key in required_keys(kind):
        if not _has(mapping, key):
            out.append({"key": key, "en": labels[key]["en"], "fr": labels[key]["fr"], "alternatives": []})
    for group in groups_of(kind):
        if _satisfied(mapping, group) is None:
            out.append({"key": group["key"], "en": group["en"], "fr": group["fr"], "alternatives": group["alternatives"]})
    return out


def mandatory_marks(kind, mapping):
    """The matched fields the screen marks mandatory: those needed by themselves, and those of
    the alternative that satisfies each group."""
    marks = set(required_keys(kind))
    for group in groups_of(kind):
        marks.update(_satisfied(mapping, group) or [])
    return marks


def clean_mapping(kind, mapping, headers):
    """The mapping kept to this kind's fields and this file's columns."""
    keys = {field["key"] for field in fields_of(kind)}
    out = {}
    for key, header in (mapping or {}).items():
        if key in keys and isinstance(header, str) and header in headers:
            out[key] = header
    if kind == "journal_entries":
        columns = je_key_columns(mapping)
        if columns and all(header in headers for header in columns):
            out[JE_KEY] = encode_je_key(columns)
    return out


# ----------------------------------------------------------------------
# The guess
# ----------------------------------------------------------------------

def remember_payload(headers, mapping):
    """What is kept for the client's next file of the kind: the fields matched, and the columns
    left out, so that a column a person set aside is not matched again by its name."""
    used = {header for key, header in mapping.items() if key != JE_KEY}
    used.update(je_key_columns(mapping))
    return {"fields": dict(mapping), "skipped": [header for header in headers if header not in used]}


def _apply_remembered(kind, headers, remembered):
    """The remembered pairs whose column is in this file under the same title, read as the
    aliases read a title: case, accents and punctuation aside."""
    by_title = {}
    for header in headers:
        by_title.setdefault(norm(header), header)
    keys = {field["key"] for field in fields_of(kind)}
    mapping, skipped = {}, []
    fields = (remembered or {}).get("fields") or {}
    for key, title in fields.items():
        header = by_title.get(norm(title)) if isinstance(title, str) else None
        if key in keys and header and header not in mapping.values():
            mapping[key] = header
    if kind == "journal_entries" and je_key_columns(fields):
        columns = [by_title.get(norm(title)) for title in je_key_columns(fields)]
        if all(columns):
            mapping[JE_KEY] = fields[JE_KEY] if columns == je_key_columns(fields) else "\u001f".join(columns)
    for title in (remembered or {}).get("skipped") or []:
        header = by_title.get(norm(title)) if isinstance(title, str) else None
        if header and header not in mapping.values():
            skipped.append(header)
    return mapping, skipped


def detect_mapping(kind, table, remembered=None):
    """The mapping proposed for a file, and where each match came from:
    ({key: header}, {header: "remembered" | "alias" | "data"}).

    The client's remembered matching first, then the titles the aliases know, then, for a trial
    balance only, the account and the description recognised by what their column holds."""
    headers = table["headers"]
    mapping, skipped = _apply_remembered(kind, headers, remembered)
    sources = {header: "remembered" for key, header in mapping.items() if key != JE_KEY}
    free = [header for header in headers if header not in skipped]
    if kind == TB_KIND:
        named = alias_tb_mapping(free, mapping)
        # By what the columns hold, the account and the description only. An amount column is
        # never taken for what it is by its place in the file: a person chooses it.
        by_values = heuristic_fill({"headers": free, "rows": table["rows"]}, named)
        guessed = dict(named)
        for key in ("account", "label"):
            if by_values.get(key) and not guessed.get(key):
                guessed[key] = by_values[key]
    else:
        named = auto_map(kind, free, mapping)
        guessed = named
    for key, header in guessed.items():
        if key == JE_KEY or header in sources:
            continue
        sources[header] = "alias" if named.get(key) == header else "data"
    return guessed, sources


# ----------------------------------------------------------------------
# The reading options
# ----------------------------------------------------------------------

def _columns(kind, mapping, keys):
    return [header for key, header in (mapping or {}).items() if key in keys and isinstance(header, str) and header]


def amount_columns(kind, mapping):
    return _columns(kind, mapping, _AMOUNT_KEYS)


def date_columns(kind, mapping):
    return _columns(kind, mapping, _DATE_KEYS)


def forced_amount_text(value, decimal):
    """The cell rewritten so that parse_amount reads it with the decimal mark the person chose.
    Left as it is when it holds no figure."""
    if value is None or is_number(value):
        return value
    raw = js_str(value)
    text = raw.replace(".", "").replace(",", ".") if decimal == "comma" else raw.replace(",", "")
    # parse_amount reads exactly three decimals as thousands: a fourth digit removes the doubt
    text = _THREE_DECIMALS.sub(lambda match: match[0] + "0", text)
    return text if parse_amount(text) is not None else value


def forced_date_text(value, order):
    """The cell rewritten as year-month-day, read in the order the person chose. Left as it is
    when it is no date in that order."""
    if value is None or is_number(value):
        return value
    match = _DATE_PARTS.match(js_trim(js_str(value)))
    if not match:
        return value
    first, second, third = int(match[1]), int(match[2]), int(match[3])
    if order == "dmy":
        year, month, day = third, second, first
    elif order == "mdy":
        year, month, day = third, first, second
    else:
        year, month, day = first, second, third
    if year < 100:
        year += 2000
    return parse_date_iso("%04d-%02d-%02d" % (year, month, day)) or value


def apply_reading_options(table, kind, mapping, decimal="auto", date_format="auto"):
    """A person's choice of decimal mark and date order, written into the cells of the matched
    amount and date columns. Automatic touches nothing: the readers guess as they always did."""
    amounts = amount_columns(kind, mapping) if decimal in ("comma", "point") else []
    dates = date_columns(kind, mapping) if date_format in ("dmy", "mdy", "ymd") else []
    if not amounts and not dates:
        return table
    for row in table["rows"]:
        for header in amounts:
            row[header] = forced_amount_text(row.get(header), decimal)
        for header in dates:
            row[header] = forced_date_text(row.get(header), date_format)
    return table


def found_decimal(table, headers):
    """The decimal mark the amount columns show, "comma" or "point"; None when they show none."""
    for row in table["rows"][:200]:
        for header in headers:
            match = _DECIMAL_TAIL.search(js_trim(cell_str(row.get(header))))
            if match:
                return "comma" if match[1] == "," else "point"
    return None


def found_date_format(table, headers):
    """The order the date columns are read in when nothing is chosen; None when they hold no date."""
    for row in table["rows"][:200]:
        for header in headers:
            text = js_trim(cell_str(row.get(header)))
            match = _DATE_PARTS.match(text)
            if not match:
                continue
            if _YEAR_FIRST.match(text):
                return "ymd"
            return "mdy" if int(match[2]) > 12 else "dmy"
    return None


# ----------------------------------------------------------------------
# The check screen
# ----------------------------------------------------------------------

def _file_row(record, position):
    row_no = source_row_of(record)
    return row_no if row_no is not None else position + 1


def gl_population(table, mapping, period_start=None, period_end=None):
    """The population checks of a ledger, on the file itself: what the projection and its checks
    will say once the file is imported. ``period_start`` and ``period_end`` are ISO dates.

    Also whether it balances, in total and entry by entry, over the lines that belong to an entry
    (those the projection keeps): ``balanced``, and ``unbalancedEntries`` in file order, each with
    its identity, first date, debit, credit, difference and file rows."""
    project = projector(mapping)
    rows = table["rows"]
    left_out = []
    lines = no_date = zero = out_of_period = 0
    total_debit = total_credit = 0
    by_entry, same = {}, {}
    for position, raw in enumerate(rows):
        line = project(raw)
        if line is None:
            left_out.append(_file_row(raw, position))
            continue
        lines += 1
        total_debit += line["debit"]
        total_credit += line["credit"]
        if line["debit"] == 0 and line["credit"] == 0:
            zero += 1
        journal_date = line["journal_date"]
        if journal_date is None:
            no_date += 1
        elif period_start is None or journal_date < period_start or journal_date > period_end:
            out_of_period += 1
        entry = by_entry.get(line["je_number"])
        if entry is None:
            entry = by_entry[line["je_number"]] = {"entry": line["je_number"], "date": journal_date, "debit": 0, "credit": 0, "rows": []}
        entry["debit"] += line["debit"]
        entry["credit"] += line["credit"]
        entry["rows"].append(_file_row(raw, position))
        if entry["date"] is None:
            entry["date"] = journal_date
        key = (line["account"], line["je_number"], journal_date, line["reference"] or "", line["signed"], line["je_description"] or "")
        same[key] = same.get(key, 0) + 1
    repeated = [count for count in same.values() if count > 1]
    extra = 0
    for count in repeated:
        extra += count - 1
    validation = population_checks({
        "fields": mapped_fields(mapping), "mapping": mapping, "source_rows": len(rows), "lines": lines, "entries": len(by_entry),
        "no_account": 0, "no_je": 0, "no_date": no_date, "zero_amount": zero,
        "total_debit": total_debit, "total_credit": total_credit, "out_of_period": out_of_period,
        "period_start": period_start, "period_end": period_end,
        "unbalanced": len([entry for entry in by_entry.values() if abs(entry["debit"] - entry["credit"]) > TOLERANCE]),
        "dup_groups": len(repeated), "dup_extra": extra,
    })
    unbalanced = [
        dict(entry, difference=entry["debit"] - entry["credit"])
        for entry in by_entry.values() if abs(entry["debit"] - entry["credit"]) > BALANCE_TOLERANCE
    ]
    return {
        "validation": validation, "lines": lines, "fileRows": len(rows), "leftOut": left_out,
        "totalDebit": total_debit, "totalCredit": total_credit,
        "balanced": abs(total_debit - total_credit) <= BALANCE_TOLERANCE and not unbalanced,
        "unbalancedEntries": unbalanced,
    }


def amount_check(table, mapping):
    """A sub-ledger's figures before it is imported: its rows, the total of its amount column,
    and the cells of that column which hold something that is no amount."""
    header = (mapping or {}).get("amount")
    total = None
    unreadable = []
    for position, raw in enumerate(table["rows"]):
        value = raw.get(header) if header else None
        parsed = parse_amount(value)
        if parsed is not None:
            total = (total or 0) + parsed
        elif value is not None and js_trim(js_str(value)) != "":
            unreadable.append({"row": _file_row(raw, position), "value": u16_slice(js_str(value), 0, 40)})
    return {"fileRows": len(table["rows"]), "total": total, "header": header, "unreadable": unreadable}
