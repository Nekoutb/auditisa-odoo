"""lib/gl-line.ts: the typed projection of an imported ledger, and its population checks.

No database here. The model reads the rows and runs the aggregates, these functions decide.
Amount convention, applied here and never reversed downstream:
    signed = debit - credit: debits positive, credits negative.
"""
import math
import re

from ._js import date_utc, is_number, js_date_parse, js_round, js_str, js_trim, to_iso_date
from .amount import parse_amount
from .dataset_mapping import je_identity, je_key_columns, je_number_looks_like_journal_code
from .errors import ServiceError

BATCH = 2000
TOLERANCE = 0.005

_ISO = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T ].*)?$")
_DMY = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$")
_SERIAL = re.compile(r"^\d+(\.\d+)?$")
_DAY_MS = 86_400_000
_EXCEL_EPOCH = date_utc(1899, 11, 30)


def _iso(year, month, day):
    if month < 1 or month > 12 or day < 1 or day > 31:
        return None
    text = "%04d-%02d-%02d" % (year, month, day)
    # refuses 31/02 and friends rather than roll them forward
    return text if to_iso_date(date_utc(year, month - 1, day)) == text else None


def _from_serial(serial):
    if not math.isfinite(serial) or serial < 1 or serial > 2_958_465:
        return None
    return to_iso_date(_EXCEL_EPOCH + math.floor(serial) * _DAY_MS)


def parse_date_iso(value):
    """ISO, dd/mm/yyyy, mm/dd/yyyy when the second part is above 12, Excel serials.
    A null date is honest, a guessed date is not."""
    if value is None:
        return None
    if is_number(value):
        return _from_serial(value)
    raw = js_trim(js_str(value))
    if not raw:
        return None
    match = _ISO.match(raw)
    if match:
        return _iso(int(match[1]), int(match[2]), int(match[3]))
    match = _DMY.match(raw)
    if match:
        first, second = int(match[1]), int(match[2])
        year = int("20" + match[3] if len(match[3]) == 2 else match[3])
        return _iso(year, first, second) if second > 12 else _iso(year, second, first)
    if _SERIAL.match(raw):
        return _from_serial(float(raw))
    parsed = js_date_parse(raw)
    return None if parsed is None or math.isnan(parsed) else to_iso_date(parsed)


def safe_text(value):
    """Neutralise spreadsheet formula injection: a leading quote keeps the characters, inert."""
    if value is None:
        return None
    raw = js_trim(js_str(value))
    if not raw:
        return None
    return "'" + raw if raw[0] in "=+-@" else raw


def _column(mapping, key):
    header = mapping.get(key)
    return header if isinstance(header, str) and js_trim(header) else None


def mapped_fields(mapping):
    """Which projection columns a mapping can actually feed."""
    found = {key for key, header in (mapping or {}).items() if isinstance(header, str) and js_trim(header)}
    if "preparedBy" in found or "recordedBy" in found:
        found.add("preparer")
    if je_key_columns(mapping):
        found.add("jeNumber")
    if "amount" in found or ("debit" in found and "credit" in found):
        found.add("signedAmount")
    return found


def projector(mapping):
    """row data -> a projection dict, or None when the row has no account or entry identity.
    Refuses mapping-incomplete when the spine columns are not mapped."""
    mapping = mapping or {}
    account_col = _column(mapping, "account")
    je_col = _column(mapping, "jeNumber")
    key_columns = je_key_columns(mapping)
    if not account_col or (not je_col and not key_columns):
        raise ServiceError("mapping-incomplete")
    debit_col, credit_col, amount_col = _column(mapping, "debit"), _column(mapping, "credit"), _column(mapping, "amount")
    use_pair = bool(debit_col and credit_col)  # the pair wins over a single amount column
    texts = {
        "account_name": _column(mapping, "accountName"),
        "journal_code": _column(mapping, "journalCode"),
        "je_description": _column(mapping, "jeDescription"),
        "line_description": _column(mapping, "lineDescription"),
        "reference": _column(mapping, "reference"),
        "third_party_code": _column(mapping, "thirdPartyCode"),
        "third_party_name": _column(mapping, "thirdPartyName"),
        "preparer": _column(mapping, "preparedBy") or _column(mapping, "recordedBy"),
        "reviewer": _column(mapping, "reviewer"),
        "approver": _column(mapping, "approvedBy"),
        "cost_center": _column(mapping, "costCenter"),
    }
    journal_date_col, entry_date_col = _column(mapping, "journalDate"), _column(mapping, "jeDate")

    def project(data):
        data = data or {}
        account = safe_text(data.get(account_col))
        je_number = je_identity(data, key_columns, je_col, safe_text)
        if not account or not je_number:
            return None
        debit = credit = 0
        if use_pair:
            debit = parse_amount(data.get(debit_col)) or 0
            credit = parse_amount(data.get(credit_col)) or 0
        else:
            value = (parse_amount(data.get(amount_col)) if amount_col else None) or 0
            if value >= 0:
                debit = value
            else:
                credit = -value
        line = {
            "account": account, "je_number": je_number, "debit": debit, "credit": credit, "signed": debit - credit,
            "journal_date": parse_date_iso(data.get(journal_date_col)) if journal_date_col else None,
            "entry_date": parse_date_iso(data.get(entry_date_col)) if entry_date_col else None,
        }
        for key, header in texts.items():
            line[key] = safe_text(data.get(header)) if header else None
        return line

    return project


def nf(value):
    """Intl.NumberFormat("en-US", {maximumFractionDigits: 2})."""
    text = "{:,.2f}".format(js_round(value * 100) / 100).rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def population_checks(aggregate):
    """The ten population checks. `aggregate` carries: fields (set), mapping, source_rows, lines,
    entries, no_account, no_je, no_date, zero_amount, total_debit, total_credit, out_of_period,
    period_start, period_end, unbalanced, dup_groups, dup_extra.
    A failed check: the population cannot be relied on. A warning: usable, to be considered."""
    a = aggregate
    fields_mapped, mapping = a["fields"], a["mapping"] or {}
    lines, entries = a["lines"], a["entries"]
    checks = []

    def push(key, label_en, label_fr, status, detail_en, detail_fr):
        checks.append({"key": key, "labelEn": label_en, "labelFr": label_fr, "status": status, "detailEn": detail_en, "detailFr": detail_fr})

    missing = [name for name in ("account", "jeNumber", "jeDescription", "journalDate") if name not in fields_mapped]
    if "signedAmount" not in fields_mapped:
        missing.append("amount")
    push(
        "mandatory-mapped", "Mandatory fields mapped", "Champs obligatoires mappés",
        "passed" if not missing else "failed",
        "Account, JE number, description, journal date and amount are all mapped." if not missing else "Not mapped: %s." % ", ".join(missing),
        "Compte, numéro d'écriture, libellé, date du journal et montant sont tous mappés." if not missing else "Non mappés : %s." % ", ".join(missing),
    )
    no_account = a["no_account"]
    push(
        "account-populated", "Account populated on every line", "Compte renseigné sur chaque ligne",
        "passed" if not no_account else "failed",
        "All %s lines carry an account." % nf(lines) if not no_account else "%s lines carry no account." % nf(no_account),
        "Les %s lignes portent un compte." % nf(lines) if not no_account else "%s lignes sans compte." % nf(no_account),
    )
    no_je = a["no_je"]
    push(
        "je-populated", "JE number populated on every line", "Numéro d'écriture renseigné sur chaque ligne",
        "passed" if not no_je else "failed",
        "All lines belong to one of %s journal entries." % nf(entries) if not no_je else "%s lines carry no JE number." % nf(no_je),
        "Toutes les lignes appartiennent à l'une des %s écritures." % nf(entries) if not no_je else "%s lignes sans numéro d'écriture." % nf(no_je),
    )
    key_cols = je_key_columns(mapping)
    identity = key_cols if key_cols else [h for h in [mapping.get("jeNumber")] if isinstance(h, str)]
    same_header = "journalCode" in fields_mapped and len(identity) == 1 and identity[0] == mapping.get("journalCode")
    code_like = same_header or je_number_looks_like_journal_code(lines, entries)
    per_entry = js_round(lines / entries) if entries > 0 else 0
    if code_like and same_header:
        detail_en = "The JE number and the journal code are mapped to the same column. Re-import with the entry-number column (JE N°, N° écriture, N° pièce) as the unique JE identifier."  # i18n: term
        detail_fr = "Le numéro d'écriture et le code journal sont mappés sur la même colonne. Réimporter avec la colonne du numéro d'écriture (JE N°, N° écriture, N° pièce) comme identifiant unique d'écriture."  # i18n: term
    elif code_like:
        detail_en = '%s distinct JE identifiers over %s lines — about %s lines per "entry". That is a journal code, not an entry number: re-import and map the unique JE identifier (one column, or several that together identify an entry, e.g. journal + voucher number).' % (nf(entries), nf(lines), nf(per_entry))
        detail_fr = "%s identifiants d'écriture distincts pour %s lignes — environ %s lignes par « écriture ». C'est un code journal, pas un numéro d'écriture : réimporter en mappant l'identifiant unique d'écriture (une colonne, ou plusieurs qui ensemble identifient une écriture, p. ex. journal + numéro de pièce)." % (nf(entries), nf(lines), nf(per_entry))
    else:
        detail_en = "%s entries, about %s lines each." % (nf(entries), nf(per_entry))
        detail_fr = "%s écritures, environ %s lignes chacune." % (nf(entries), nf(per_entry))
    push("je-distinguishes", "JE number distinguishes entries", "Le numéro d'écriture distingue les écritures", "failed" if code_like else "passed", detail_en, detail_fr)
    no_date = a["no_date"]
    push(
        "dates-parsed", "Journal dates readable", "Dates du journal lisibles",
        "passed" if not no_date else "warning" if no_date < lines * 0.01 else "failed",
        "Every journal date parsed." if not no_date else "%s lines have an unreadable journal date and are grouped separately." % nf(no_date),
        "Toutes les dates du journal ont été lues." if not no_date else "%s lignes ont une date du journal illisible et sont regroupées à part." % nf(no_date),
    )
    zero = a["zero_amount"]
    push(
        "amounts-numeric", "Amounts read as numbers", "Montants lus comme des nombres",
        "passed" if not zero else "warning",
        "Every line carries a numeric debit or credit." if not zero else "%s lines carry neither a debit nor a credit (nil amount or an unreadable value)." % nf(zero),
        "Chaque ligne porte un débit ou un crédit numérique." if not zero else "%s lignes ne portent ni débit ni crédit (montant nul ou valeur illisible)." % nf(zero),
    )
    debit, credit = a["total_debit"], a["total_credit"]
    diff = debit - credit
    push(
        "debit-credit-reconcile", "Total debits equal total credits", "Total des débits égal au total des crédits",
        "passed" if abs(diff) <= TOLERANCE else "failed",
        "Debits %s vs credits %s; difference %s." % (nf(debit), nf(credit), nf(diff)),
        "Débits %s contre crédits %s ; différence %s." % (nf(debit), nf(credit), nf(diff)),
    )
    unbalanced = a["unbalanced"]
    push(
        "entries-balance", "Every journal entry balances", "Chaque écriture est équilibrée",
        "passed" if not unbalanced else "failed",
        "All %s journal entries net to nil." % nf(entries) if not unbalanced else "%s of %s journal entries do not net to nil." % (nf(unbalanced), nf(entries)),
        "Les %s écritures se soldent à zéro." % nf(entries) if not unbalanced else "%s écritures sur %s ne se soldent pas à zéro." % (nf(unbalanced), nf(entries)),
    )
    start, end, out = a["period_start"], a["period_end"], a["out_of_period"]
    if start is None:
        status, detail_en, detail_fr = (
            "warning", "The engagement period could not be read, so the check was not performed.",
            "La période de la mission n'a pas pu être lue ; le contrôle n'a pas été effectué.",
        )
    elif not out:
        status, detail_en, detail_fr = (
            "passed", "All dated lines fall within %s to %s." % (start, end),
            "Toutes les lignes datées se situent entre le %s et le %s." % (start, end),
        )
    else:
        status, detail_en, detail_fr = (
            "warning", "%s lines fall outside %s to %s — an exception requiring audit consideration." % (nf(out), start, end),
            "%s lignes se situent hors de la période du %s au %s — exception à examiner." % (nf(out), start, end),
        )
    push("dates-in-period", "Journal dates within the engagement period", "Dates du journal dans la période de la mission", status, detail_en, detail_fr)
    groups, extra = a["dup_groups"], a["dup_extra"]
    push(
        "duplicate-rows", "No identical source rows", "Aucune ligne source identique",
        "passed" if not groups else "warning",
        "No two lines share account, JE number, date, reference, amount and description." if not groups else "%s lines repeat one of %s identical combinations — an exception requiring audit consideration." % (nf(extra), nf(groups)),
        "Aucune ligne ne partage compte, numéro d'écriture, date, référence, montant et libellé." if not groups else "%s lignes répètent l'une des %s combinaisons identiques — exception à examiner." % (nf(extra), nf(groups)),
    )
    source = a["source_rows"]
    gap = source - lines
    push(
        "row-count", "Imported line count complete", "Nombre de lignes importées complet",
        "passed" if not gap else "warning",
        "%s of %s source rows projected." % (nf(lines), nf(source)) if not gap else "%s of %s source rows projected; %s were skipped for a missing account or JE number." % (nf(lines), nf(source), nf(gap)),
        "%s lignes source sur %s projetées." % (nf(lines), nf(source)) if not gap else "%s lignes source sur %s projetées ; %s écartées faute de compte ou de numéro d'écriture." % (nf(lines), nf(source), nf(gap)),
    )
    failed = len([check for check in checks if check["status"] == "failed"])
    warnings = len([check for check in checks if check["status"] == "warning"])
    return {
        "checks": checks, "status": "failed" if failed else "warning" if warnings else "passed",
        "lines": lines, "sourceRows": source, "passed": len(checks) - failed - warnings, "warnings": warnings, "failed": failed,
    }
