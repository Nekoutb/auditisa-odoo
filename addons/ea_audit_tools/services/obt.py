"""Opening Balance Testing (owner's mock-ups "obt", approved 20/11/2026). Pure: no Odoo, no network.

The opening balances of the trial balance are grouped into the lines of the SYSCOHADA balance sheet,
with the owner's own table (data/obt_syscohada_bilan.csv, sent 20/11/2026): for each line of the
form, the accounts of its gross amount and of its depreciation. That table serves this tool only;
the lead schedules keep their own grouping (owner's ruling, 20/11/2026).

How an account finds its line:
- the longest prefix that names it wins, "sauf" (except) taking accounts out of a prefix;
- a line marked "debit balances" (BJ, BS) takes an account only in debit, one marked "credit
  balances" (DK, DM, DR) only in credit: 44 in debit goes to BJ, in credit to DK. Each account is
  placed on its own balance, never netted with another;
- an account marked "p" is shared by several lines (2818p is in AE and AH): it goes with the asset
  it depreciates, 28181 with 2181 (AE), the rest of 2818 with 218 (AH). One the rule cannot place
  is left for the user to choose, once per client (owner, 20/11/2026);
- a depreciation account reduces its asset line: lines are compared on their net amount.

Amounts: an asset line is the sum of its accounts' balances (debit positive); a liability line is
the opposite of that sum, so that both sides read as positive figures, as the statements print them.
"""
import re

from ._js import js_round, js_sum

#: The owner's table, beside this module (read by the caller: this module opens no file).
FORM_FILE_NAME = "data/obt_syscohada_bilan.csv"
#: The owner's tolerance (20/11/2026): above 1 FCFA a line is a difference.
TOLERANCE = 1.0
DEBIT_ONLY = "debit balances"
CREDIT_ONLY = "credit balances"
UNITS = {"units": 1, "thousands": 1000, "millions": 1000000}

_NUMBER = re.compile(r"\d+")


def _r2(value):
    """To the cent, as Math.round does it."""
    return js_round(value * 100) / 100


def _csv_rows(text):
    """The rows of the table: ";" between cells, no quoted cell, the first line names the columns."""
    lines = [line.rstrip("\r") for line in (text or "").split("\n") if line.strip()]
    heads = [cell.strip() for cell in lines[0].lstrip("\ufeff").split(";")]
    return [dict(zip(heads, line.split(";"))) for line in lines[1:]]


def load_form(text):
    """The form's 57 references in their printed order, from the table's text: {ref, side, kind,
    label_fr, label_en, gross, depreciation, balance, parts}. ``parts`` is the formula of a sub-total."""
    rows = []
    for raw in _csv_rows(text):
        kind = raw["kind"].strip()
        row = {
            "ref": raw["ref"].strip(), "side": raw["side"].strip(), "kind": kind,
            "label_fr": raw["label_fr"].strip(), "label_en": raw["label_en"].strip(),
            "balance": raw["balance_rule"].strip(), "gross": [], "depreciation": [], "parts": [],
        }
        if kind == "line":
            row["gross"] = parse_accounts(raw["gross_accounts"])
            row["depreciation"] = parse_accounts(raw["depreciation_accounts"])
        else:
            row["parts"] = [part.strip() for part in raw["gross_accounts"].split("+") if part.strip()]
        rows.append(row)
    return rows


def parse_accounts(text):
    """[{prefix, excludes, partial}] of a cell such as "24 (sauf 245 et 2495), 2949p".

    "sauf" lists exceptions; "ou" in brackets (12 (121 ou 129)) only says which sub-accounts the
    prefix holds and changes nothing; a trailing "p" marks an account shared with another line."""
    out = []
    for part in re.split(r",(?![^()]*\))", text or ""):
        part = part.strip()
        if not part:
            continue
        head, _sep, bracket = part.partition("(")
        found = _NUMBER.match(head.strip())
        if not found:
            continue
        prefix = found.group(0)
        partial = head.strip()[len(prefix):].strip().lower().startswith("p")
        excludes = _NUMBER.findall(bracket) if "sauf" in bracket.lower() else []
        out.append({"prefix": prefix, "excludes": excludes, "partial": partial})
    return out


def _rules(form):
    """Every (prefix, excludes, partial, ref, side, balance, kind) of the form, gross and depreciation."""
    rules = []
    for row in form:
        if row["kind"] != "line":
            continue
        for kind in ("gross", "depreciation"):
            for rule in row[kind]:
                rules.append({**rule, "ref": row["ref"], "side": row["side"], "balance": row["balance"], "of": kind})
    return rules


def _matches(rule, account, balance):
    if not account.startswith(rule["prefix"]) or any(account.startswith(ex) for ex in rule["excludes"]):
        return False
    if rule["balance"] == DEBIT_ONLY and balance < 0:
        return False
    if rule["balance"] == CREDIT_ONLY and balance > 0:
        return False
    return True


def asset_of(account):
    """The asset a depreciation or impairment account reduces: 28181 -> 2181, 29193 -> 2193."""
    if len(account) > 2 and account[:2] in ("28", "29"):
        return "2" + account[2:]
    return None


def place(account, balance, form, rules=None, chosen=None):
    """(ref, how) for one account: how is "rule", "asset" (a "p" account placed with its asset),
    "chosen" (the user's choice for this client), or (None, "choose", [refs]) / (None, "none")."""
    account = str(account or "").strip()
    rules = rules if rules is not None else _rules(form)
    candidates = [rule for rule in rules if _matches(rule, account, balance)]
    if not candidates:
        return None, "none", []
    best = max(len(rule["prefix"]) for rule in candidates)
    top = [rule for rule in candidates if len(rule["prefix"]) == best]
    refs = sorted({rule["ref"] for rule in top})
    if len(refs) == 1:
        return refs[0], "rule", refs
    if chosen and chosen.get(account) in refs:
        return chosen[account], "chosen", refs
    if all(rule["partial"] for rule in top):
        asset = asset_of(account)
        if asset:
            gross = [rule for rule in rules if rule["of"] == "gross" and _matches(rule, asset, 1)]
            if gross:
                longest = max(len(rule["prefix"]) for rule in gross)
                found = sorted({rule["ref"] for rule in gross if len(rule["prefix"]) == longest} & set(refs))
                if len(found) == 1:
                    return found[0], "asset", refs
    return None, "choose", refs


def group(accounts, form, chosen=None):
    """Grouping of the trial balance's opening balances: ({ref: {amount, accounts}}, unmapped, to_choose).

    ``accounts``: [{account, name, opening}] (opening debit minus opening credit). ``chosen``:
    {account: ref}, the user's placements of "p" accounts for this client."""
    rules = _rules(form)
    side = {row["ref"]: row["side"] for row in form}
    lines, unmapped, to_choose = {}, [], []
    for item in accounts:
        balance = float(item.get("opening") or 0)
        if abs(balance) < 0.005:
            continue
        ref, how, refs = place(item["account"], balance, form, rules, chosen)
        if ref is None:
            (to_choose if how == "choose" else unmapped).append({**item, "choices": refs})
            continue
        line = lines.setdefault(ref, {"amount": 0.0, "accounts": []})
        line["amount"] += balance if side[ref] == "asset" else -balance
        line["accounts"].append({**item, "how": how})
    return lines, unmapped, to_choose


def with_totals(values, form):
    """{ref: amount} for every reference of the form: its lines as given (0 if absent), each
    sub-total and total worked out from its parts, in the form's order (a total uses sub-totals)."""
    out = {}
    for row in form:
        if row["kind"] == "line":
            out[row["ref"]] = float(values.get(row["ref"]) or 0)
    for row in form:
        if row["kind"] != "line":
            out[row["ref"]] = js_sum([out.get(part, 0.0) for part in row["parts"]])
    return out


def compare(statements, opening, form, tolerance=TOLERANCE):
    """Rows of the result: every reference, the prior-year statements' figure, the trial balance's,
    the difference (trial balance minus statements) and whether it agrees. A line with nothing on
    either side is marked empty (hidden on the page, shown on request)."""
    left = with_totals(statements, form)
    right = with_totals(opening, form)
    rows = []
    for row in form:
        ref = row["ref"]
        a, b = left[ref], right[ref]
        difference = _r2(b - a)
        rows.append({
            "ref": ref, "side": row["side"], "kind": row["kind"],
            "statements": a, "opening": b, "difference": difference,
            "agrees": abs(difference) <= tolerance,
            "empty": row["kind"] == "line" and abs(a) < 0.005 and abs(b) < 0.005,
        })
    return rows


def summary(rows):
    """What the score box says: lines compared, lines that agree, by side, and the totals' differences."""
    lines = [row for row in rows if row["kind"] == "line" and not row["empty"]]
    by_side = {}
    for side in ("asset", "liability"):
        mine = [row for row in lines if row["side"] == side]
        by_side[side] = {"lines": len(mine), "agree": len([row for row in mine if row["agrees"]])}
    totals = {row["ref"]: row["difference"] for row in rows if row["ref"] in ("BZ", "DZ")}
    differences = [row for row in lines if not row["agrees"]]
    return {
        "lines": len(lines), "agree": len(lines) - len(differences), "differences": len(differences),
        "by_side": by_side, "assets_difference": totals.get("BZ", 0.0), "liabilities_difference": totals.get("DZ", 0.0),
    }


def arithmetic_checks(read, form, tolerance=TOLERANCE):
    """The checks of what was read, to catch a misread figure before anything is compared:
    total assets = total liabilities and equity, each sub-total read = the sum of its parts read.
    ``read``: {ref: amount} as read or typed, sub-totals included when the document prints them.
    [{key, ok, refs, expected, found}]."""
    checks = []
    if "BZ" in read and "DZ" in read:
        checks.append({"key": "balance", "ok": abs(read["BZ"] - read["DZ"]) <= tolerance,
                       "refs": ["BZ", "DZ"], "expected": read["BZ"], "found": read["DZ"]})
    # a sub-total is checked against its parts as printed (a part's own sub-total when the document
    # prints it), so one misread figure is pointed at once, not at every total above it
    computed = with_totals({ref: amount for ref, amount in read.items()}, form)
    for row in form:
        if row["kind"] == "line" or row["ref"] not in read:
            continue
        expected = js_sum([read[part] if part in read else computed.get(part, 0.0) for part in row["parts"]])
        checks.append({"key": "subtotal", "ok": abs(expected - read[row["ref"]]) <= tolerance,
                       "refs": [row["ref"]], "expected": expected, "found": read[row["ref"]]})
    return checks


# ---------------------------------------------------------------------------
# Reading a document
# ---------------------------------------------------------------------------

def reading_schema():
    """The JSON the reading service must give back, and nothing else."""
    return {
        "type": "object",
        "properties": {
            "year_end": {"type": "string", "description": "Closing date of the statements, YYYY-MM-DD, or empty."},
            "unit": {"type": "string", "enum": list(UNITS)},
            "signed": {"type": "boolean", "description": "True if the document bears signatures or an approval stamp."},
            "column": {"type": "string", "description": "The heading of the column read, as printed."},
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "ref": {"type": "string"},
                        "amount": {"type": "number"},
                        "page": {"type": "integer"},
                    },
                    "required": ["ref", "amount", "page"],
                    "additionalProperties": False,
                },
            },
            "net_result_income_statement": {"type": ["number", "null"]},
        },
        "required": ["year_end", "unit", "signed", "column", "lines", "net_result_income_statement"],
        "additionalProperties": False,
    }


def reading_instructions(form):
    """What the reader is asked: the form's references and how to read them."""
    lines = ["%s %s" % (row["ref"], row["label_fr"]) for row in form]
    return (
        "These pages are a company's financial statements in the SYSCOHADA format (bilan actif, bilan passif "  # i18n: input
        "and compte de résultat). Read the balance sheet into the references below.\n"  # i18n: input
        "- For every reference printed on the balance sheet, give the amount of the year's own column: on the "  # i18n: input
        "asset side the NET column of the year (Net N / Exercice N), never the gross or depreciation columns, "  # i18n: input
        "never the comparative year; on the liability side the year's column.\n"  # i18n: input
        "- Give sub-totals and totals (AD, AI, AQ, AZ, BG, BK, BT, BZ, CP, DD, DF, DP, DT, DZ) as printed.\n"  # i18n: input
        "- Amounts as printed, without converting: a negative amount (in brackets or with a minus sign) is negative. "  # i18n: input
        "Leave out a reference that has no amount or is not printed.\n"  # i18n: input
        "- unit: units, thousands or millions, as the document states (\"en milliers\" is thousands).\n"  # i18n: input
        "- page: the page of the uploaded file, counting from 1, where the amount is printed.\n"  # i18n: input
        "- net_result_income_statement: the net result of the year on the income statement, or null if absent.\n"  # i18n: input
        "- signed: whether the document shows signatures, an approval stamp or an approval date.\n\n"  # i18n: input
        "References:\n" + "\n".join(lines)  # i18n: input
    )


def parse_reading(data, form):
    """What a reading gave, cleaned: {lines: {ref: {amount, page}}, unit, multiplier, year_end, signed,
    column, net_result}. Unknown references are dropped; amounts are converted to units."""
    if not isinstance(data, dict):
        raise ValueError("reading")
    known = {row["ref"] for row in form}
    unit = data.get("unit") if data.get("unit") in UNITS else "units"
    multiplier = UNITS[unit]
    lines = {}
    for item in data.get("lines") or []:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("ref") or "").strip().upper()
        amount = item.get("amount")
        if ref not in known or not isinstance(amount, (int, float)) or isinstance(amount, bool):
            continue
        page = item.get("page") if isinstance(item.get("page"), int) and not isinstance(item.get("page"), bool) else None
        lines[ref] = {"amount": _r2(float(amount) * multiplier), "page": page}
    net = data.get("net_result_income_statement")
    year_end = str(data.get("year_end") or "").strip()
    return {
        "lines": lines, "unit": unit, "multiplier": multiplier,
        "year_end": year_end if re.fullmatch(r"\d{4}-\d{2}-\d{2}", year_end) else "",
        "signed": data.get("signed") is True,
        "column": str(data.get("column") or "")[:120],
        "net_result": _r2(float(net) * multiplier) if isinstance(net, (int, float)) and not isinstance(net, bool) else None,
    }
