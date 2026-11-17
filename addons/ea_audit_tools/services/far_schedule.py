"""K-M1 and K-M2 on the fixed asset register (owner's requests of 2026-11-16 and 2026-11-17).

K-M1: the register's movement schedule is worked out from each asset's dates, cost and rate for
the year audited, in three parts, each against the general ledger:

1. gross book value (cost): opening + additions - disposals = closing, against classes 21 to 25;
2. accumulated depreciation: opening + charge of the year - on disposals = closing, against 28
   and 291-295; the charge worked out is also set against the register's own charge column and
   the ledger's depreciation expense (681, or the register's own expense accounts);
3. net book value = (1) - (2), against the ledger's net.

Rows are the register's general ledger accounts when its account column is mapped (2026-11-17):
the cost part by the cost account, compared with the ledger accounts that start with it; the
depreciation part by the depreciation account (the register's own, else SYSCOHADA's "28" + the
cost account's 2nd and 3rd digits: 2441 -> 2844); the net by the cost accounts that share their
depreciation accounts. Ledger accounts with a balance and no register line are rows of their
own. Without the account column, rows are the register's categories, compared in total only.

Additions are the assets acquired in the year, disposals those disposed of in the year, from the
dates. When the register's "additions of the year" or "disposals at cost" column is mapped and
the asset's cell is filled, that amount is used instead; where it disagrees with the dates the
row carries a notice (owner, 2026-11-17).

Depreciation is straight line: cost x rate a year. Before the year it runs from the acquisition
date over days / 365; in the year it is cost x rate x the share of the year's days the asset was
held (from its acquisition, to its disposal). It never exceeds the cost.

K-M2: the additions and disposals of the register are the population the vouching sample is
drawn from.

Dates are ISO texts, figures floats; no Odoo here.
"""
from ._js import js_round, js_sum
from .procedure_execution import TOLERANCE, _day

SECTIONS = ("cost", "depreciation", "nbv")
#: The questions asked of each sampled addition and disposal (Yes / No / Not applicable).
VOUCH_CHECKS = {
    "addition": ("exists", "cost", "period", "policy", "capital", "authorised"),
    "disposal": ("authorised", "removed", "proceeds", "gainloss"),
}
VOUCH_ANSWERS = ("yes", "no", "na")
VOUCH_NOTE_MAX = 2000
#: The depreciation expense account the charge is compared with when the register names none.
EXPENSE_PREFIX = "681"


def _r(value):
    return js_round(value * 100) / 100


def _digits(account):
    text = str(account or "").strip()
    out = ""
    for char in text:
        if not char.isdigit():
            break
        out += char
    return out


def is_cost_account(account):
    digits = _digits(account)
    return len(digits) >= 2 and digits[0] == "2" and digits[1] in "12345"


def is_depreciation_account(account):
    digits = _digits(account)
    return digits[:2] == "28" or (digits[:2] == "29" and len(digits) > 2 and digits[2] in "12345")


def is_expense_account(account):
    return _digits(account).startswith(EXPENSE_PREFIX)


def cost_prefix(account):
    """The ledger class of an asset's account (its first three digits), when it is a cost account."""
    digits = _digits(account)
    return digits[:3] if is_cost_account(digits) and len(digits) >= 3 else None


def depreciation_account(cost_account):
    """SYSCOHADA's depreciation account of a cost account: "28" + its 2nd and 3rd digits
    (2441 -> 2844, 2311 -> 2831, 2154 -> 2815); "" when it is not a cost account."""
    digits = _digits(cost_account)
    return "28" + digits[1:3] if len(digits) >= 3 and is_cost_account(digits) else ""


def _amount(value):
    return abs(float(value)) if value is not None else None


# ----------------------------------------------------------------------
# One asset over the year
# ----------------------------------------------------------------------

def asset_year(asset, period_start, period_end):
    """The asset's figures for the year, or None when it is out of the year (acquired after the
    year end, or disposed of before the year began) or cannot be worked out (no date, no rate,
    no cost). ``asset``: {cost, acquired, disposed, rate, additions, disposalsCost} with rate in
    percent a year; ``additions`` and ``disposalsCost``, the register's own amounts (None when
    the column is not mapped or the cell empty), replace the cost the dates move.

    ``notices``: "additions" / "disposals" when the register's amount disagrees with the dates."""
    cost, rate = asset.get("cost"), asset.get("rate")
    acquired, disposed = _day(asset.get("acquired")), _day(asset.get("disposed"))
    first, last = _day(period_start), _day(period_end)
    if cost is None or rate is None or acquired is None or first is None or last is None:
        return None
    if acquired > last or (disposed is not None and disposed < first):
        return None
    cost = abs(float(cost))
    annual = cost * float(rate) / 100
    year_days = last - first + 1
    opening = acquired < first
    opening_acc = min(cost, annual * (first - acquired) / 365) if opening else 0.0
    out_day = disposed if disposed is not None and disposed <= last else None
    start, end = max(acquired, first), out_day if out_day is not None else last
    held = max(0, end - start + 1)
    charge = min(cost - opening_acc, annual * held / year_days)
    acc_end = opening_acc + charge
    by_date_in, by_date_out = (0.0 if opening else cost), (cost if out_day is not None else 0.0)
    given_in, given_out = _amount(asset.get("additions")), _amount(asset.get("disposalsCost"))
    notices = []
    if given_in is not None and abs(given_in - by_date_in) >= TOLERANCE:
        notices.append("additions")
    if given_out is not None and abs(given_out - by_date_out) >= TOLERANCE:
        notices.append("disposals")
    return {
        "costOpening": cost if opening else 0.0,
        "additions": given_in if given_in is not None else by_date_in,
        "costDisposals": given_out if given_out is not None else by_date_out,
        "depOpening": opening_acc,
        "charge": charge,
        "depDisposals": acc_end if out_day is not None else 0.0,
        "disposed": out_day is not None,
        "nbvAtDisposal": cost - acc_end if out_day is not None else None,
        "notices": notices,
    }


# ----------------------------------------------------------------------
# K-M1: the schedule against the ledger
# ----------------------------------------------------------------------

def _sum_ledger(balances, test):
    values = [float(value or 0) for account, _name, value in balances if test(account)]
    return _r(js_sum(values)) if values else None


def _allocate(balances, prefixes, test):
    """The ledger accounts that pass ``test``, each given to the longest of ``prefixes`` it
    starts with (so no balance is counted twice): ({prefix: total}, {account: (name, total)} of
    those with a balance that no prefix takes)."""
    ordered = sorted((p for p in prefixes if p), key=len, reverse=True)
    found = {p: [] for p in ordered}
    rest = {}
    for account, name, value in balances:
        if not test(account):
            continue
        digits = _digits(account)
        hit = next((p for p in ordered if digits.startswith(p)), None)
        if hit is not None:
            found[hit].append(float(value or 0))
        else:
            entry = rest.setdefault(digits or str(account), [name or "", []])
            entry[1].append(float(value or 0))
    totals = {p: _r(js_sum(values)) if values else 0.0 for p, values in found.items()}
    left = {account: (name, _r(js_sum(values))) for account, (name, values) in rest.items()}
    return totals, {account: entry for account, entry in left.items() if abs(entry[1]) >= 0.005}


def _state(has_assets, has_ledger, gaps, explanation):
    if not has_assets:
        return "no-register"
    if not has_ledger:
        return "no-gl"
    if not gaps:
        return "agrees"
    return "explained" if (explanation or "").strip() else "difference"


def _gap(value):
    return value is not None and abs(value) >= TOLERANCE


def _total_of(lines, name):
    return _r(js_sum(figures[name] for _asset, figures in lines))


def _names(values):
    """Distinct texts in their first order."""
    return list(dict.fromkeys(value for value in values if value))


def _categories(lines):
    return _names(str(asset.get("category") or "").strip() for asset, _figures in lines)


def _notices(lines):
    """The assets whose register amounts disagree with their dates: their number, else file row."""
    return [str(asset.get("item") or asset.get("row") or "") for asset, figures in lines if figures["notices"]][:20]


def _register_rows(label, lines, extra=None):
    """The cost and depreciation rows of one group of assets, without the ledger."""
    cost = {
        "label": label, "opening": _total_of(lines, "costOpening"), "additions": _total_of(lines, "additions"),
        "disposals": -_total_of(lines, "costDisposals"),
    }
    cost["closing"] = _r(cost["opening"] + cost["additions"] + cost["disposals"])
    dep = {
        "label": label, "opening": _total_of(lines, "depOpening"), "charge": _total_of(lines, "charge"),
        "disposals": -_total_of(lines, "depDisposals"),
    }
    dep["closing"] = _r(dep["opening"] + dep["charge"] + dep["disposals"])
    for row in (cost, dep):
        row.update(extra or {}, notices=_notices(lines))
    return cost, dep


def _ledger_only(account, name, value, columns):
    """A ledger account with a balance and no register line: nothing per register, all a difference."""
    row = {"label": account, "ledgerName": name, "ledgerOnly": True, "categories": [], "notices": []}
    row.update({column: None for column in columns})
    row["closing"] = 0.0
    row["ledger"] = value
    return row


def _by_category(lines, balances, has_ledger):
    """The grouping kept for a register without its account column: rows by category, set
    against the ledger when a category's lines carry one class of account no other uses."""
    groups, order = {}, []
    for asset, figures in lines:
        category = str(asset.get("category") or "").strip()
        key = category.lower()
        group = groups.get(key)
        if group is None:
            group = groups[key] = {"label": category, "prefixes": set(), "lines": []}
            order.append(key)
        group["prefixes"].add(cost_prefix(asset.get("account")))
        group["lines"].append((asset, figures))
    owners = {}
    for key in order:
        prefixes = groups[key]["prefixes"]
        prefix = next(iter(prefixes)) if len(prefixes) == 1 else None
        groups[key]["prefix"] = prefix
        if prefix:
            owners.setdefault(prefix, []).append(key)
    for key in order:
        prefix = groups[key]["prefix"]
        if prefix and len(owners[prefix]) > 1:
            groups[key]["prefix"] = None
    cost_rows, dep_rows, nbv_rows = [], [], []
    for key in sorted(order, key=lambda k: groups[k]["label"].lower()):
        group = groups[key]
        prefix = group["prefix"]
        cost, dep = _register_rows(group["label"], group["lines"], {"categories": []})
        nbv = {"label": group["label"], "cost": cost["closing"], "depreciation": dep["closing"],
               "closing": _r(cost["closing"] - dep["closing"]), "categories": [], "notices": cost["notices"]}
        if prefix and has_ledger:
            tail = prefix[1:]
            cost["ledger"] = _sum_ledger(balances, lambda a, p=prefix: _digits(a).startswith(p)) or 0.0
            dep_ledger = _sum_ledger(balances, lambda a, t=tail: _digits(a).startswith(("28" + t, "29" + t))) or 0.0
            dep["ledger"] = _r(-dep_ledger)
            nbv["ledger"] = _r(cost["ledger"] + dep_ledger)
        else:
            cost["ledger"] = dep["ledger"] = nbv["ledger"] = None
        cost_rows.append(cost)
        dep_rows.append(dep)
        nbv_rows.append(nbv)
    return cost_rows, dep_rows, nbv_rows


def _sort_key(row):
    return (row["label"] == "", row["label"])


def _by_account(lines, balances, has_ledger):
    """Rows by the register's general ledger accounts (owner, 2026-11-17)."""
    cost_groups, dep_groups, links = {}, {}, {}
    for asset, figures in lines:
        cost_account = _digits(asset.get("account"))
        dep_account = _digits(asset.get("depAccount")) or depreciation_account(cost_account)
        cost_groups.setdefault(cost_account, []).append((asset, figures))
        dep_groups.setdefault(dep_account, []).append((asset, figures))
        links.setdefault(cost_account, set()).add(dep_account)

    cost_ledger, cost_rest = _allocate(balances, cost_groups, is_cost_account) if has_ledger else ({}, {})
    dep_ledger, dep_rest = _allocate(balances, dep_groups, is_depreciation_account) if has_ledger else ({}, {})

    cost_rows, dep_rows = [], []
    for account, group in cost_groups.items():
        cost, _dep = _register_rows(account, group, {"categories": _categories(group)})
        cost["ledger"] = cost_ledger.get(account, 0.0) if has_ledger and account else None
        cost_rows.append(cost)
    for account, group in dep_groups.items():
        _cost, dep = _register_rows(account, group, {
            "categories": _categories(group), "costAccounts": _names(_digits(a.get("account")) for a, _f in group),
        })
        dep["ledger"] = _r(-dep_ledger.get(account, 0.0)) if has_ledger and account else None
        dep_rows.append(dep)

    # the net: cost accounts that share a depreciation account make one row, so each ledger
    # balance is set against the register once
    parent = {}

    def find(node):
        while parent.setdefault(node, node) != node:
            node = parent[node]
        return node

    for cost_account, deps in links.items():
        for dep_account in deps:
            parent[find(("d", dep_account))] = find(("c", cost_account))
    components = {}
    for cost_account in cost_groups:
        components.setdefault(find(("c", cost_account)), set()).add(cost_account)
    nbv_rows = []
    for cost_accounts in components.values():
        accounts = sorted(cost_accounts)
        group = [line for account in accounts for line in cost_groups[account]]
        dep_accounts = sorted({d for account in accounts for d in links[account]})
        cost, dep = _register_rows("", group)
        nbv = {
            "label": " + ".join(accounts) if all(accounts) else "",
            "cost": cost["closing"], "depreciation": dep["closing"], "closing": _r(cost["closing"] - dep["closing"]),
            "categories": _categories(group), "notices": cost["notices"],
        }
        if has_ledger and all(accounts) and all(dep_accounts):
            nbv["ledger"] = _r(js_sum([cost_ledger.get(a, 0.0) for a in accounts] + [dep_ledger.get(d, 0.0) for d in dep_accounts]))
        else:
            nbv["ledger"] = None
        nbv_rows.append(nbv)

    for account, (name, value) in cost_rest.items():
        cost_rows.append(_ledger_only(account, name, value, ("opening", "additions", "disposals")))
        nbv_rows.append(_ledger_only(account, name, value, ("cost", "depreciation")))
    for account, (name, value) in dep_rest.items():
        dep_rows.append(_ledger_only(account, name, _r(-value), ("opening", "charge", "disposals")))
        nbv_rows.append(_ledger_only(account, name, value, ("cost", "depreciation")))
    return sorted(cost_rows, key=_sort_key), sorted(dep_rows, key=_sort_key), sorted(nbv_rows, key=_sort_key)


def _charge(lines, balances, has_ledger, by_expense_account):
    """The charge worked out against the register's charge column and the ledger: against 681 in
    total, or, when the register names its expense accounts, account by account (a line naming
    none goes to 681)."""
    groups, register_charge = {}, []
    for asset, figures in lines:
        if asset.get("charge") is not None:
            register_charge.append(abs(float(asset["charge"])))
        key = (_digits(asset.get("chargeAccount")) if by_expense_account else "") or EXPENSE_PREFIX
        groups.setdefault(key, []).append(figures["charge"])
    computed = _r(js_sum(figures["charge"] for _asset, figures in lines))
    register = _r(js_sum(register_charge)) if register_charge else None
    expense = rows = None
    if by_expense_account:
        prefixes = tuple(groups)
        found, rest = (_allocate(balances, prefixes, lambda a: is_expense_account(a) or _digits(a).startswith(prefixes))
                       if has_ledger else ({}, {}))
        rows = []
        for account in sorted(groups):
            amount = _r(js_sum(groups[account]))
            ledger = found.get(account, 0.0) if has_ledger else None
            rows.append({"label": account, "computed": amount, "ledger": ledger, "ledgerOnly": False,
                         "difference": _r(amount - ledger) if ledger is not None else None})
        for account, (name, value) in sorted(rest.items()):
            rows.append({"label": account, "ledgerName": name, "computed": 0.0, "ledger": value, "ledgerOnly": True,
                         "difference": _r(-value)})
        if has_ledger:
            expense = _r(js_sum(row["ledger"] for row in rows))
    elif has_ledger:
        expense = _sum_ledger(balances, is_expense_account)
    return {
        "computed": computed, "register": register, "ledger": expense, "rows": rows,
        "registerDifference": _r(computed - register) if register is not None else None,
        "ledgerDifference": _r(computed - expense) if expense is not None else None,
    }


def _filled(assets, key):
    return any(_digits(asset.get(key)) for asset in assets)


def far_schedule(assets, balances, period_start, period_end, explanations=None, columns=None):
    """The three parts of K-M1. ``assets``: the register's lines, {row, item, category, account,
    depAccount, chargeAccount, cost, acquired, disposed, rate, charge, additions, disposalsCost}.
    ``balances``: [(account, name, closing)], debit positive. ``explanations``: {cost,
    depreciation, nbv}: the team's words for what remains. ``columns``: {account: bool,
    chargeAccount: bool}, whether the register's columns are mapped (by default, whether a line
    fills them).

    Each part: rows by account (``byAccount``) or by category, ledger-only rows flagged
    ``ledgerOnly``, a total row, ``state`` ("no-register", "no-gl", "agrees", "explained",
    "difference") and ``needsExplanation``. ``incomplete`` lists the file rows left out because
    they have no readable date, rate or cost; ``notices`` the assets whose additions or disposals
    amounts disagree with their dates."""
    explanations = explanations or {}
    columns = columns or {}
    by_account = columns["account"] if "account" in columns else _filled(assets, "account")
    by_expense = columns["chargeAccount"] if "chargeAccount" in columns else _filled(assets, "chargeAccount")
    lines, incomplete, outside = [], [], 0
    for asset in assets:
        figures = asset_year(asset, period_start, period_end)
        if figures is None:
            if asset.get("cost") is None or asset.get("rate") is None or _day(asset.get("acquired")) is None:
                incomplete.append(asset.get("row"))
            else:
                outside += 1
            continue
        lines.append((asset, figures))

    has_ledger = bool(balances)
    if by_account:
        cost_rows, dep_rows, nbv_rows = _by_account(lines, balances, has_ledger)
    else:
        cost_rows, dep_rows, nbv_rows = _by_category(lines, balances, has_ledger)
    for rows in (cost_rows, dep_rows, nbv_rows):
        for row in rows:
            row.setdefault("ledgerOnly", False)
            row["difference"] = _r(row["closing"] - row["ledger"]) if row["ledger"] is not None else None

    def column(rows, name):
        return _r(js_sum(row[name] or 0 for row in rows))

    ledger_cost = (_sum_ledger(balances, is_cost_account) or 0.0) if has_ledger else None
    ledger_dep = (_sum_ledger(balances, is_depreciation_account) or 0.0) if has_ledger else None
    totals = {
        "cost": {name: column(cost_rows, name) for name in ("opening", "additions", "disposals", "closing")},
        "depreciation": {name: column(dep_rows, name) for name in ("opening", "charge", "disposals", "closing")},
        "nbv": {name: column(nbv_rows, name) for name in ("cost", "depreciation", "closing")},
    }
    totals["cost"]["ledger"] = ledger_cost
    totals["depreciation"]["ledger"] = _r(-ledger_dep) if ledger_dep is not None else None
    totals["nbv"]["ledger"] = _r(ledger_cost + ledger_dep) if has_ledger else None
    for total in totals.values():
        total["difference"] = _r(total["closing"] - total["ledger"]) if total["ledger"] is not None else None

    has_assets = bool(lines)
    sections = {}
    for name, rows in (("cost", cost_rows), ("depreciation", dep_rows), ("nbv", nbv_rows)):
        gaps = [row for row in rows if _gap(row["difference"])]
        if _gap(totals[name]["difference"]):
            gaps.append(totals[name])
        text = str(explanations.get(name) or "")
        state = _state(has_assets, has_ledger, gaps, text)
        sections[name] = {
            "rows": rows, "total": totals[name], "state": state, "explanation": text,
            "needsExplanation": state in ("difference", "explained"),
        }
    sections["depreciation"]["charge"] = _charge(lines, balances, has_ledger, by_expense)
    linked = has_assets and all(row["ledger"] is not None for row in cost_rows if not row["ledgerOnly"])
    states = [sections[name]["state"] for name in SECTIONS]
    notices = [str(asset.get("item") or asset.get("row") or "") for asset, figures in lines if figures["notices"]]
    return {
        "sections": sections, "linked": linked, "byAccount": bool(by_account), "byExpenseAccount": bool(by_expense),
        "assets": len(assets), "used": len(lines), "outside": outside,
        "incomplete": [row for row in incomplete if row is not None][:50], "incompleteCount": len(incomplete),
        "notices": notices[:50], "noticeCount": len(notices),
        "state": "difference" if "difference" in states else states[0] if len(set(states)) == 1 else "explained",
    }


# ----------------------------------------------------------------------
# K-M2: the additions and disposals, and their vouching
# ----------------------------------------------------------------------

def far_movements(assets, period_start, period_end):
    """The additions and disposals of the year: [{key, side, row, item, label, category, date,
    amount, rate, proceeds, nbv, gainLoss, notice}], the disposal's net book value worked out as
    K-M1 does.

    An addition is an asset acquired in the year, at its cost; a disposal one disposed of in the
    year, at its cost. When the register's own "additions of the year" or "disposals at cost"
    amount is filled, that amount decides instead (no movement when it is nil); ``notice`` is
    True when it disagrees with the dates or the cost. An asset acquired after the year end or
    disposed of before the year began is never a movement of the year."""
    first, last = _day(period_start), _day(period_end)
    out = []
    if first is None or last is None:
        return out
    for asset in assets:
        cost = asset.get("cost")
        if cost is None:
            continue
        cost = abs(float(cost))
        acquired, disposed = _day(asset.get("acquired")), _day(asset.get("disposed"))
        if (acquired is not None and acquired > last) or (disposed is not None and disposed < first):
            continue
        base = {
            "row": asset.get("row"), "item": asset.get("item") or "", "label": asset.get("label") or "",
            "category": asset.get("category") or "", "rate": asset.get("rate"),
        }
        acquired_in = acquired is not None and first <= acquired
        disposed_in = disposed is not None and disposed <= last
        given_in, given_out = _amount(asset.get("additions")), _amount(asset.get("disposalsCost"))
        if given_in is not None:
            addition = given_in if given_in >= TOLERANCE else None
            notice = abs(given_in - (cost if acquired_in else 0.0)) >= TOLERANCE
        else:
            addition, notice = (cost if acquired_in else None), False
        if addition is not None:
            out.append(dict(base, key="A%s" % asset.get("row"), side="addition", date=asset.get("acquired"),
                            amount=_r(addition), proceeds=None, nbv=None, gainLoss=None, notice=notice))
        if given_out is not None:
            removal = given_out if given_out >= TOLERANCE else None
            notice = abs(given_out - (cost if disposed_in else 0.0)) >= TOLERANCE
        else:
            removal, notice = (cost if disposed_in else None), False
        if removal is not None:
            figures = asset_year(asset, period_start, period_end) if disposed_in else None
            nbv = _r(figures["nbvAtDisposal"]) if figures and figures["nbvAtDisposal"] is not None else None
            proceeds = asset.get("proceeds")
            out.append(dict(base, key="D%s" % asset.get("row"), side="disposal", date=asset.get("disposed"),
                            amount=_r(removal), proceeds=proceeds, nbv=nbv, notice=notice,
                            gainLoss=_r(float(proceeds) - nbv) if proceeds is not None and nbv is not None else None))
    return out


def clean_vouch_patch(side, values):
    """What a person may change on a sampled item: an answer per question of its side, a note.
    None when refused."""
    if side not in VOUCH_CHECKS or not isinstance(values, dict) or not values:
        return None
    clean = {}
    for key, value in values.items():
        if key == "note":
            clean["note"] = str(value or "").strip()[:VOUCH_NOTE_MAX]
        elif key in VOUCH_CHECKS[side] and (value in VOUCH_ANSWERS or value in (None, "")):
            clean[key] = value or None
        else:
            return None
    return clean


def vouch_state(side, answers):
    """"exception" when one answer is No, "done" when every question is answered, else "todo"."""
    answers = answers or {}
    values = [answers.get(key) for key in VOUCH_CHECKS.get(side, ())]
    if "no" in values:
        return "exception"
    return "done" if values and all(value in VOUCH_ANSWERS for value in values) else "todo"
