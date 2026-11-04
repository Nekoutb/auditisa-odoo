"""lib/tb.ts: trial-balance parsing and validation rules, without the DB.

Column-mapping inference, row extraction, the validation engine (balance checks,
codification, unknown accounts, opening ties to prior), the lead-schedule roll-up,
the import preview and the journal balance check. Versioning and journal posting
are storage, and stay in the Odoo model.
"""
import re
import unicodedata
from functools import cmp_to_key

from ._js import JS_S, cell_str, js_round, js_str, js_trim, locale_compare, u16_slice
from .amount import amount_or, parse_amount
from .errors import TbError
from .lead_classes import LEAD_INDEXES, SUB_INDEX_BY_CODE, lead_index_for, sub_index_for, sub_index_label
from .leadsheets import resolve_section
from .subledgers import source_row_of

ALIASES = {
    "account": ["account", "accountcode", "accountnumber", "compte", "ncompte", "numerocompte", "numero", "code"],
    "label": ["label", "libelle", "intitule", "accountname", "description", "designation"],
    "openingDebit": ["openingdebit", "soldeouverturedebit", "anouveaudebit", "debitouverture", "soldeinitialdebit", "odebit"],
    "openingCredit": [
        "openingcredit",
        "soldeouverturecredit",
        "anouveaucredit",
        "creditouverture",
        "soldeinitialcredit",
        "ocredit",
    ],
    "debit": ["debit", "debits", "mouvementdebit", "mouvementsdebit", "movementdebit", "cumuldebit"],
    "credit": ["credit", "credits", "mouvementcredit", "mouvementscredit", "movementcredit", "cumulcredit"],
    "closingDebit": ["closingdebit", "soldedebit", "soldefinaldebit", "balancedebit"],
    "closingCredit": ["closingcredit", "soldecredit", "soldefinalcredit", "balancecredit"],
    "closing": ["closing", "closingbalance", "solde", "soldefinal", "soldecloture", "balance", "net"],
    "opening": [
        "opening",
        "openingbalance",
        "soldeouverture",
        "soldedouverture",
        "anouveau",
        "soldeinitial",
        "ouverture",
        "soldedebut",
    ],
}

EPSILON = 0.01

#: Pseudo-account of the aggregate 'result carried forward' opening check.
RESULT_CARRIED_FORWARD = "12x/13x"

_AMOUNT_COLUMNS = ("openingDebit", "openingCredit", "opening", "debit", "credit", "closingDebit", "closingCredit", "closing")
_SEP = "[" + JS_S + "-]?"
_TOTAL_ROW = re.compile(
    r"(sous" + _SEP + r"total|sub" + _SEP + r"total|grand" + _SEP + r"total|total)\b",
    re.IGNORECASE | re.ASCII,
)
_COMBINING = re.compile("[̀-ͯ]")
_NOT_ALNUM = re.compile(r"[^a-z0-9]")
_CODIFIED = re.compile(r"[1-9][0-9]{0,7}")
_DIGITS_4 = re.compile(r"[0-9]{4,}")
_TEXTUAL = re.compile("[a-zA-ZÀ-ɏ]{3,}")


def normalize_header(value):
    return _NOT_ALNUM.sub("", _COMBINING.sub("", unicodedata.normalize("NFD", js_trim(value).lower())))


def infer_tb_mapping(headers):
    """The column mapping from headers (EN/FR aliases)."""
    normalized = {normalize_header(header): header for header in headers}
    mapping = {}
    for column, aliases in ALIASES.items():
        for alias in aliases:
            hit = normalized.get(alias)
            if hit and hit not in mapping.values():
                mapping[column] = hit
                break
    validate_mapping(mapping)
    return mapping


def validate_mapping(mapping):
    """The account and at least one amount column must be mapped."""
    if not mapping.get("account"):
        raise TbError("missing-account-column")
    has_movements = mapping.get("debit") and mapping.get("credit")
    has_closing = (mapping.get("closingDebit") and mapping.get("closingCredit")) or mapping.get("closing")
    if not has_movements and not has_closing:
        raise TbError("missing-amount-columns")


def _unreadable(value):
    """A cell that holds something but not an amount."""
    return value is not None and js_trim(js_str(value)) != "" and parse_amount(value) is None


def is_account_cell(value):
    """SYSCOHADA codes are numeric: a title line in the account column is no row (B28)."""
    return value[:1] in tuple("0123456789") and value != ""


def _skip_tb_row(account, raw, mapping):
    """A row with no account, a total line, and a word in the account column with nothing
    readable in the amount columns are not rows of the balance (B28). A word that DOES
    carry amounts is a mis-coded account: it stays in and the codification check reports it."""
    if not account:
        return True
    if is_account_cell(account):
        return False
    if _TOTAL_ROW.match(account):
        return True
    for column in _AMOUNT_COLUMNS:
        header = mapping.get(column)
        if header and parse_amount(raw.get(header)) is not None:
            return False
    return True


def readability_of(table, mapping):
    """What the parser could and could not read; validate_tb_rows folds it into the summary."""
    found = {}
    rows_without_account = 0
    for i, raw in enumerate(table["rows"]):
        account = js_trim(cell_str(raw.get(mapping.get("account"))))
        if _skip_tb_row(account, raw, mapping):
            rows_without_account += 1
            continue
        for column in _AMOUNT_COLUMNS:
            header = mapping.get(column)
            if not header:
                continue
            value = raw.get(header)
            if not _unreadable(value):
                continue
            entry = found.get(column)
            if entry is None:
                entry = {"column": column, "header": header, "count": 0, "examples": []}
            entry["count"] += 1
            if len(entry["examples"]) < 5:
                row_no = source_row_of(raw)
                entry["examples"].append({
                    "row": row_no if row_no is not None else i + 1,
                    "account": account,
                    "value": u16_slice(js_str(value), 0, 40),
                })
            found[column] = entry
    return {"rows": len(table["rows"]), "rowsWithoutAccount": rows_without_account, "unreadable": list(found.values())}


def extract_tb_rows(table, mapping):
    """A parsed file as TB rows. Closing-only files land in debit/credit."""
    rows = []
    for raw in table["rows"]:
        account = js_trim(cell_str(raw.get(mapping.get("account"))))
        if _skip_tb_row(account, raw, mapping):
            continue

        def get(column):
            header = mapping.get(column)
            return amount_or(raw.get(header), 0) if header else 0

        opening_debit = get("openingDebit")
        opening_credit = get("openingCredit")
        if not mapping.get("openingDebit") and not mapping.get("openingCredit") and mapping.get("opening"):
            opening = get("opening")
            opening_debit = opening if opening > 0 else 0
            opening_credit = -opening if opening < 0 else 0
        debit = get("debit")
        credit = get("credit")
        if not mapping.get("debit") and not mapping.get("credit"):
            # Closing columns hold BALANCES, not movements. The movement is closing -
            # opening, so opening + movements always equals the file's closing.
            if mapping.get("closingDebit") or mapping.get("closingCredit"):
                closing_net = get("closingDebit") - get("closingCredit")
            else:
                closing_net = get("closing")
            movement = closing_net - (opening_debit - opening_credit)
            debit = movement if movement > 0 else 0
            credit = -movement if movement < 0 else 0
        label = None
        if mapping.get("label"):
            label = js_trim(cell_str(raw.get(mapping["label"]))) or None
        rows.append({
            "account": account,
            "label": label,
            "openingDebit": opening_debit,
            "openingCredit": opening_credit,
            "debit": debit,
            "credit": credit,
            "raw": raw,
        })
    if not rows:
        raise TbError("empty-file")
    return rows


def _total(rows, field):
    total = 0
    for row in rows:
        total += row[field]
    return total


def validate_tb_rows(rows, known_prefixes, prior_closings, mapping, readability=None):
    """The 3.2 validation engine. ``prior_closings``: {account: closing} in the query's
    order, or None when there is no prior year."""
    total_debit = _total(rows, "debit")
    total_credit = _total(rows, "credit")
    total_opening_debit = _total(rows, "openingDebit")
    total_opening_credit = _total(rows, "openingCredit")

    has_closing_columns = bool(mapping.get("closingDebit") or mapping.get("closingCredit") or mapping.get("closing"))
    has_opening = bool(mapping.get("openingDebit") or mapping.get("openingCredit"))

    # closing = opening + movements per account: checkable only when the file
    # carries opening + movements + closing simultaneously.
    closing_failures = []
    if has_opening and has_closing_columns and mapping.get("debit") and mapping.get("credit"):
        for row in rows:
            raw = row["raw"]
            closing_from_file = (
                (amount_or(raw.get(mapping["closingDebit"]), 0) if mapping.get("closingDebit") else 0)
                - (amount_or(raw.get(mapping["closingCredit"]), 0) if mapping.get("closingCredit") else 0)
                + (amount_or(raw.get(mapping["closing"]), 0) if mapping.get("closing") else 0)
            )
            computed = row["openingDebit"] - row["openingCredit"] + row["debit"] - row["credit"]
            if abs(closing_from_file - computed) > EPSILON:
                closing_failures.append(row["account"])

    bad_accounts = [row["account"] for row in rows if not _CODIFIED.fullmatch(row["account"])]

    unknown_accounts = [
        row["account"]
        for row in rows
        if row["account"][:1] in tuple("123456789") and row["account"] != ""
        and not any(row["account"].startswith(prefix) for prefix in known_prefixes)
    ]

    opening_exceptions = []
    if prior_closings is not None and has_opening:
        # P&L accounts (classes 6-8) reset at year start and the result accounts
        # (12x/13x) receive the prior result: tie those in one aggregate check
        def is_result(account):
            return account[:2] in ("12", "13")

        def carried(account):
            return account[:1] in ("6", "7", "8") or is_result(account)

        for row in rows:
            if carried(row["account"]):
                continue
            opening = row["openingDebit"] - row["openingCredit"]
            prior = prior_closings.get(row["account"], 0)
            if abs(opening - prior) > EPSILON:
                opening_exceptions.append({"account": row["account"], "opening": opening, "priorClosing": prior})
        prior_result = 0
        for account, closing in prior_closings.items():
            if carried(account):
                prior_result += closing
        opening_result = 0
        for row in rows:
            if is_result(row["account"]):
                opening_result = opening_result + row["openingDebit"] - row["openingCredit"]
        if abs(opening_result - prior_result) > EPSILON:
            opening_exceptions.append({"account": RESULT_CARRIED_FORWARD, "opening": opening_result, "priorClosing": prior_result})

    balanced_ok = abs(total_debit - total_credit) <= EPSILON
    opening_ok = abs(total_opening_debit - total_opening_credit) <= EPSILON
    closing_ok = len(closing_failures) == 0
    # a figure the parser could not read went in as 0: the balance is not the file's
    readable_ok = not readability or len(readability["unreadable"]) == 0

    summary = {
        "status": "valid" if balanced_ok and opening_ok and closing_ok and readable_ok else "invalid",
        "checks": {
            "balanced": {"ok": balanced_ok, "totalDebit": total_debit, "totalCredit": total_credit},
            "openingBalanced": {"ok": opening_ok, "totalDebit": total_opening_debit, "totalCredit": total_opening_credit},
            "closingEquation": {"ok": closing_ok, "failures": closing_failures[:50]},
            "codification": {"ok": len(bad_accounts) == 0, "badAccounts": bad_accounts[:50]},
            "unknownAccounts": unknown_accounts[:50],
            "openingTiesToPrior": {"checked": prior_closings is not None, "exceptions": opening_exceptions[:50]},
        },
        "mapping": mapping,
    }
    if readability is not None:
        summary["readability"] = readability
    return summary


def heuristic_fill(table, mapping):
    """Columns from the DATA when header names are unrecognised: the account column is
    full of 4+ digit codes, the label the most textual, unclaimed numeric columns
    become opening then closing. The user confirms on the analyzer screen either way."""
    out = dict(mapping)
    used = set(out.values())
    sample = table["rows"][:50]
    stats = []
    for header in table["headers"]:
        digits = text = numeric = filled = 0
        for row in sample:
            value = js_trim(cell_str(row.get(header)))
            if not value:
                continue
            filled += 1
            if _DIGITS_4.fullmatch(value):
                digits += 1
            if _TEXTUAL.search(value):
                text += 1
            if parse_amount(value) is not None:
                numeric += 1
        stats.append({
            "header": header,
            "digits": digits / filled if filled else 0,
            "text": text / filled if filled else 0,
            "numeric": numeric / filled if filled else 0,
        })

    def free():
        return [x for x in stats if x["header"] not in used]

    if not out.get("account"):
        candidates = sorted((x for x in free() if x["digits"] >= 0.6), key=lambda x: -x["digits"])
        if candidates:
            out["account"] = candidates[0]["header"]
            used.add(candidates[0]["header"])
    if not out.get("label"):
        candidates = sorted((x for x in free() if x["text"] >= 0.6), key=lambda x: -x["text"])
        if candidates:
            out["label"] = candidates[0]["header"]
            used.add(candidates[0]["header"])
    has_amounts = (out.get("debit") and out.get("credit")) or (out.get("closingDebit") and out.get("closingCredit")) or out.get("closing")
    if not has_amounts:
        numerics = [x for x in free() if x["numeric"] >= 0.6 and x["digits"] < 0.6]
        if len(numerics) >= 2 and not out.get("opening"):
            out["opening"] = numerics[0]["header"]
            used.add(numerics[0]["header"])
        last = numerics[-1] if numerics else None
        if last and last["header"] not in used:
            out["closing"] = last["header"]
            used.add(last["header"])
        elif len(numerics) == 1:
            out["closing"] = numerics[0]["header"]
    return out


def _closing_of(row):
    return row["openingDebit"] - row["openingCredit"] + row["debit"] - row["credit"]


def preview_trial_balance(table, mapping_override=None, overrides=(), global_rules=(), index_overrides=None):
    """A TB file analysed WITHOUT ingesting: the confirm-and-map screen renders this.

    ``overrides`` are client_grouping_override rows and ``global_rules``
    syscohada_grouping_rule rows, as {prefix, sectionCode, exact, priority};
    ``index_overrides`` is {account_prefix: index_code}.
    """
    index_overrides = index_overrides or {}
    mapping = mapping_override if mapping_override is not None else {}
    mapping_error = None
    rows = []
    try:
        if mapping_override is None:
            try:
                mapping = infer_tb_mapping(table["headers"])
            except TbError:
                mapping = {}
            mapping = heuristic_fill(table, mapping)
        validate_mapping(mapping)
        rows = extract_tb_rows(table, mapping)
    except TbError as error:
        mapping_error = error.code

    by_prefix = {}
    for row in rows:
        prefix = u16_slice(row["account"], 0, 4)
        entry = by_prefix.setdefault(prefix, {"accounts": set(), "total": 0, "sections": {}})
        entry["accounts"].add(row["account"])
        entry["total"] += _closing_of(row)
        section = resolve_section(row["account"], overrides, global_rules)
        entry["sections"][section] = entry["sections"].get(section, 0) + 1

    classes = []
    for prefix in sorted(by_prefix, key=cmp_to_key(locale_compare)):
        entry = by_prefix[prefix]
        # the class maps to the section most of its accounts resolve to
        section = None
        best = -1
        for candidate, count in entry["sections"].items():
            if count > best:
                best = count
                section = candidate
        override = index_overrides.get(prefix)
        classes.append({
            "prefix": prefix,
            "accountCount": len(entry["accounts"]),
            "closingTotal": js_round(entry["total"]),
            "section": section,
            "leadIndex": override if override is not None else lead_index_for(prefix),
        })

    header_samples = {}
    for header in table["headers"]:
        values = []
        for raw in table["rows"]:
            value = js_trim(cell_str(raw.get(header)))
            if value:
                values.append(value)
            if len(values) >= 3:
                break
        header_samples[header] = values

    return {
        "headers": table["headers"],
        "headerSamples": header_samples,
        "mapping": mapping,
        "mappingError": mapping_error,
        "rowCount": len(rows),
        "sample": [
            {
                "account": row["account"],
                "label": row["label"],
                "opening": js_round(row["openingDebit"] - row["openingCredit"]),
                "closing": js_round(_closing_of(row)),
            }
            for row in rows[:6]
        ],
        "classes": classes,
    }


def _variance_pct(current, prior):
    return js_round(((current - prior) / abs(prior)) * 1000) / 10 if prior != 0 else None


def lead_schedules(rows, prior_closings=None, overrides=()):
    """The lead schedules from {account_code, closing} rows. ``prior_closings``:
    {account: closing}; ``overrides``: (prefix, index_code) pairs."""
    if not rows:
        return []
    prior = prior_closings if prior_closings is not None else {}
    ordered = sorted(overrides, key=lambda pair: -len(pair[0]))

    def index_of(account):
        for prefix, code in ordered:
            if account.startswith(prefix):
                return code
        return lead_index_for(account)

    # account to (index, sub-total): current from the TB; prior-only accounts still
    # appear, so a disappeared balance shows its variance
    cells = {}

    def put(account, current, prior_amount):
        index = index_of(account)
        if not index:
            return
        sub = sub_index_for(account)
        if sub is None:
            sub = index + "-1"
        cell = cells.setdefault(index + "|" + sub, {"index": index, "sub": sub, "current": 0, "prior": 0})
        cell["current"] += current
        cell["prior"] += prior_amount

    seen = set()
    for row in rows:
        seen.add(row["account_code"])
        put(row["account_code"], row["closing"], prior.get(row["account_code"], 0))
    for account, amount in prior.items():
        if account not in seen:
            put(account, 0, amount)

    by_index = {}
    for cell in cells.values():
        current = js_round(cell["current"])
        prior_amount = js_round(cell["prior"])
        definition = SUB_INDEX_BY_CODE.get(cell["sub"])
        by_index.setdefault(cell["index"], []).append({
            "code": cell["sub"],
            "label": sub_index_label(definition, "en") if definition else cell["sub"],
            "current": current,
            "prior": prior_amount,
            "variance": current - prior_amount,
            "variancePct": _variance_pct(current, prior_amount),
        })

    def by_code(a, b):
        return locale_compare(a["code"], b["code"], numeric=True)

    out = []
    for definition in LEAD_INDEXES:
        subtotals = by_index.get(definition["code"])
        if not subtotals:
            continue
        subtotals.sort(key=cmp_to_key(by_code))
        current = 0
        prior_amount = 0
        for subtotal in subtotals:
            current += subtotal["current"]
            prior_amount += subtotal["prior"]
        out.append({
            "index": definition["code"],
            "label": definition["labelEn"],
            "accountType": definition["accountType"],
            "accountClass": definition["accountClass"],
            "subtotals": subtotals,
            "current": current,
            "prior": prior_amount,
            "variance": current - prior_amount,
            "variancePct": _variance_pct(current, prior_amount),
        })
    return out


def validate_journal(description, lines):
    """An adjusting journal: described, at least two lines, debits equal to credits."""
    if not js_trim(description):
        raise TbError("description-required")
    if len(lines) < 2:
        raise TbError("journal-lines-required")
    if abs(_total(lines, "debit") - _total(lines, "credit")) > EPSILON:
        raise TbError("journal-unbalanced")


def diff_tb_versions(rows):
    """Lines that differ between two versions, from {account, a, b} closing values
    (None when the account is absent from that version)."""
    out = []
    for row in rows:
        closing_a = 0 if row.get("a") is None else row["a"]
        closing_b = 0 if row.get("b") is None else row["b"]
        difference = closing_b - closing_a
        if abs(difference) > EPSILON:
            out.append({"account": row["account"], "closingA": closing_a, "closingB": closing_b, "difference": difference})
    return out
