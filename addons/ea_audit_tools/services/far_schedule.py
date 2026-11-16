"""K-M1 and K-M2 on the fixed asset register (owner's request of 2026-11-16).

K-M1: the register's movement schedule is worked out from each asset's dates, cost and rate for
the year audited, in three parts, each against the general ledger:

1. gross book value (cost): opening + additions - disposals = closing, against classes 21 to 25;
2. accumulated depreciation: opening + charge of the year - on disposals = closing, against 28
   and 291-295; the charge worked out is also set against the register's own charge column and
   the ledger's depreciation expense (681);
3. net book value = (1) - (2), against the ledger's net.

Depreciation is straight line: cost x rate a year. Before the year it runs from the acquisition
date over days / 365; in the year it is cost x rate x the share of the year's days the asset was
held (from its acquisition, to its disposal). It never exceeds the cost.

K-M2: the additions (acquired in the year) and disposals (disposed of in the year) of the
register are the population the vouching sample is drawn from.

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
    return _digits(account).startswith("681")


def cost_prefix(account):
    """The ledger class of an asset's account (its first three digits), when it is a cost account."""
    digits = _digits(account)
    return digits[:3] if is_cost_account(digits) and len(digits) >= 3 else None


# ----------------------------------------------------------------------
# One asset over the year
# ----------------------------------------------------------------------

def asset_year(asset, period_start, period_end):
    """The asset's figures for the year, or None when it is out of the year (acquired after the
    year end, or disposed of before the year began) or cannot be worked out (no date, no rate,
    no cost). ``asset``: {cost, acquired, disposed, rate} with rate in percent a year."""
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
    return {
        "costOpening": cost if opening else 0.0,
        "additions": 0.0 if opening else cost,
        "costDisposals": cost if out_day is not None else 0.0,
        "depOpening": opening_acc,
        "charge": charge,
        "depDisposals": acc_end if out_day is not None else 0.0,
        "disposed": out_day is not None,
        "nbvAtDisposal": cost - acc_end if out_day is not None else None,
    }


# ----------------------------------------------------------------------
# K-M1: the schedule against the ledger
# ----------------------------------------------------------------------

def _sum_ledger(balances, test):
    values = [float(value or 0) for account, _name, value in balances if test(account)]
    return _r(js_sum(values)) if values else None


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


def far_schedule(assets, balances, period_start, period_end, explanations=None):
    """The three parts of K-M1. ``assets``: the register's lines, {row, category, account, cost,
    acquired, disposed, rate, charge}. ``balances``: [(account, name, closing)], debit positive.
    ``explanations``: {cost, depreciation, nbv}: the team's words for what remains.

    Each part: rows by category (with the ledger when the category's lines carry one class of
    account of their own), a total row, ``state`` ("no-register", "no-gl", "agrees",
    "explained", "difference") and ``needsExplanation``. ``incomplete`` lists the file rows left
    out because they have no readable date, rate or cost."""
    explanations = explanations or {}
    groups, order, incomplete, outside = {}, [], [], 0
    register_charge = []
    for asset in assets:
        figures = asset_year(asset, period_start, period_end)
        if figures is None:
            if asset.get("cost") is None or asset.get("rate") is None or _day(asset.get("acquired")) is None:
                incomplete.append(asset.get("row"))
            else:
                outside += 1
            continue
        if asset.get("charge") is not None:
            register_charge.append(abs(float(asset["charge"])))
        category = str(asset.get("category") or "").strip()
        key = category.lower()
        group = groups.get(key)
        if group is None:
            group = groups[key] = {"label": category, "prefixes": set(), "lines": []}
            order.append(key)
        group["prefixes"].add(cost_prefix(asset.get("account")))
        group["lines"].append(figures)
    # a category is set against the ledger when its lines carry one class no other category uses
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

    def total_of(lines, name):
        return _r(js_sum(line[name] for line in lines))

    has_ledger = bool(balances)
    cost_rows, dep_rows, nbv_rows = [], [], []
    for key in sorted(order, key=lambda k: groups[k]["label"].lower()):
        group = groups[key]
        lines, prefix = group["lines"], group["prefix"]
        cost = {
            "label": group["label"], "opening": total_of(lines, "costOpening"), "additions": total_of(lines, "additions"),
            "disposals": -total_of(lines, "costDisposals"),
        }
        cost["closing"] = _r(cost["opening"] + cost["additions"] + cost["disposals"])
        dep = {
            "label": group["label"], "opening": total_of(lines, "depOpening"), "charge": total_of(lines, "charge"),
            "disposals": -total_of(lines, "depDisposals"),
        }
        dep["closing"] = _r(dep["opening"] + dep["charge"] + dep["disposals"])
        nbv = {"label": group["label"], "cost": cost["closing"], "depreciation": dep["closing"], "closing": _r(cost["closing"] - dep["closing"])}
        if prefix and has_ledger:
            tail = prefix[1:]
            cost["ledger"] = _sum_ledger(balances, lambda a, p=prefix: _digits(a).startswith(p)) or 0.0
            dep_ledger = _sum_ledger(balances, lambda a, t=tail: _digits(a).startswith(("28" + t, "29" + t))) or 0.0
            dep["ledger"] = _r(-dep_ledger)
            nbv["ledger"] = _r(cost["ledger"] + dep_ledger)
        else:
            cost["ledger"] = dep["ledger"] = nbv["ledger"] = None
        for row in (cost, dep, nbv):
            row["difference"] = _r(row["closing"] - row["ledger"]) if row["ledger"] is not None else None
        cost_rows.append(cost)
        dep_rows.append(dep)
        nbv_rows.append(nbv)

    def column(rows, name):
        return _r(js_sum(row[name] for row in rows))

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

    has_assets = bool(order)
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
    computed = totals["depreciation"]["charge"]
    expense = _sum_ledger(balances, is_expense_account) if has_ledger else None
    register = _r(js_sum(register_charge)) if register_charge else None
    sections["depreciation"]["charge"] = {
        "computed": computed, "register": register, "ledger": expense,
        "registerDifference": _r(computed - register) if register is not None else None,
        "ledgerDifference": _r(computed - expense) if expense is not None else None,
    }
    linked = has_assets and all(row["ledger"] is not None for row in cost_rows)
    states = [sections[name]["state"] for name in SECTIONS]
    return {
        "sections": sections, "linked": linked, "assets": len(assets), "used": len(assets) - len(incomplete) - outside,
        "outside": outside, "incomplete": [row for row in incomplete if row is not None][:50], "incompleteCount": len(incomplete),
        "state": "difference" if "difference" in states else states[0] if len(set(states)) == 1 else "explained",
    }


# ----------------------------------------------------------------------
# K-M2: the additions and disposals, and their vouching
# ----------------------------------------------------------------------

def far_movements(assets, period_start, period_end):
    """The additions and disposals of the year: [{key, side, row, item, label, category, date,
    amount (the cost), rate, proceeds, nbv, gainLoss}], the disposal's net book value worked out
    as K-M1 does."""
    first, last = _day(period_start), _day(period_end)
    out = []
    if first is None or last is None:
        return out
    for asset in assets:
        cost = asset.get("cost")
        if cost is None:
            continue
        base = {
            "row": asset.get("row"), "item": asset.get("item") or "", "label": asset.get("label") or "",
            "category": asset.get("category") or "", "amount": _r(abs(float(cost))), "rate": asset.get("rate"),
        }
        acquired, disposed = _day(asset.get("acquired")), _day(asset.get("disposed"))
        if acquired is not None and first <= acquired <= last:
            out.append(dict(base, key="A%s" % asset.get("row"), side="addition", date=asset.get("acquired"),
                            proceeds=None, nbv=None, gainLoss=None))
        if disposed is not None and first <= disposed <= last:
            figures = asset_year(asset, period_start, period_end)
            nbv = _r(figures["nbvAtDisposal"]) if figures and figures["nbvAtDisposal"] is not None else None
            proceeds = asset.get("proceeds")
            out.append(dict(base, key="D%s" % asset.get("row"), side="disposal", date=asset.get("disposed"),
                            proceeds=proceeds, nbv=nbv,
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
