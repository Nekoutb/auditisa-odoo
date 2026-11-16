"""The adjustment of a misstatement finding (owner's mock-up of 2026-11-16, "mock-finding-adj").

The team writes the entry that corrects the misstatement on the finding itself: lines of account,
label, debit and credit, balanced. Booking it writes the summary of audit differences' lines (one
debit account against one credit account each, the structure the summary already reads), so the
summary keeps no figure of its own. A line is a dict: ``account``, ``label``, ``debit``, ``credit``.
"""
from ._js import js_round
from .sad_model import suggest_caption

ACCOUNT_MAX = 64
LABEL_MAX = 200
#: The natures the finding offers; the summary knows two more (reclassification, disclosure).
ADJUSTMENT_NATURES = ["factual", "judgmental", "projected"]


def _r2(value):
    """To the cent, as Math.round does it."""
    return js_round(value * 100) / 100


def _total(values):
    out = 0.0
    for value in values:
        out += value
    return _r2(out)


class AdjustmentError(ValueError):
    """``code`` is the rule code the model raises."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _amount(value):
    if value in (None, False, ""):
        return 0.0
    try:
        amount = _r2(float(value))
    except (TypeError, ValueError) as error:
        raise AdjustmentError("adjustment-line") from error
    if amount < 0:
        raise AdjustmentError("adjustment-line")
    return amount


def clean_lines(lines):
    """The lines as saved: trimmed, fully blank lines dropped. A line with an amount on both
    sides, or a negative one, is refused; a line still missing its account or amount is kept
    (the team is typing it) and stops only the booking."""
    out = []
    for line in lines or ():
        account = str(line.get("account") or "").strip()[:ACCOUNT_MAX]
        label = str(line.get("label") or "").strip()[:LABEL_MAX]
        debit, credit = _amount(line.get("debit")), _amount(line.get("credit"))
        if not (account or label or debit or credit):
            continue
        if debit and credit:
            raise AdjustmentError("adjustment-line")
        out.append({"account": account, "label": label, "debit": debit, "credit": credit})
    return out


def totals(lines):
    debit = _total(line["debit"] for line in lines)
    credit = _total(line["credit"] for line in lines)
    return {"debit": debit, "credit": credit, "balanced": bool(debit) and abs(debit - credit) < 0.005}


def booking_error(lines):
    """Why the adjustment cannot be booked yet, as a rule code; None when it can."""
    if not lines:
        return "adjustment-unbalanced"
    for line in lines:
        if not line["account"] or not (line["debit"] or line["credit"]):
            return "adjustment-line"
    if not totals(lines)["balanced"] or not any(line["debit"] for line in lines) or not any(line["credit"] for line in lines):
        return "adjustment-unbalanced"
    return None


def adjustment_effect(lines):
    """What the entry does, each figure positive when it raises the item: profit, assets,
    liabilities and equity. Equity takes the effect on profit as well (the result is part of it),
    so assets = liabilities + equity for a balanced entry. Captions are suggested from the
    SYSCOHADA account number, as on the summary."""
    profit = assets = liabilities = equity = 0.0
    for line in lines:
        net = line["debit"] - line["credit"]
        caption = suggest_caption(line["account"] or "")
        if caption in ("income", "expense"):
            profit -= net
        elif caption in ("current_asset", "non_current_asset"):
            assets += net
        elif caption in ("current_liability", "non_current_liability"):
            liabilities -= net
        else:
            equity -= net
    clean = lambda value: 0.0 if abs(value) < 0.005 else _r2(value)  # noqa: E731
    return {
        "profit": clean(profit), "assets": clean(assets), "liabilities": clean(liabilities),
        "equity": clean(equity + profit),
    }


def adjustment_pairs(lines):
    """The summary lines of a balanced entry: each debit set against the credits in order, so
    an entry of one debit and one credit is one line, and Dr A 100, Dr B 50 / Cr C 150 is two."""
    debits = [[line["account"], line["debit"]] for line in lines if line["debit"]]
    credits = [[line["account"], line["credit"]] for line in lines if line["credit"]]
    pairs, i, j = [], 0, 0
    while i < len(debits) and j < len(credits):
        amount = _r2(min(debits[i][1], credits[j][1]))
        if amount:
            pairs.append({"dr_account": debits[i][0], "cr_account": credits[j][0], "amount": amount})
        debits[i][1] = _r2(debits[i][1] - amount)
        credits[j][1] = _r2(credits[j][1] - amount)
        if debits[i][1] < 0.005:
            i += 1
        if credits[j][1] < 0.005:
            j += 1
    return pairs


def accounts_text(lines):
    """For the C1.1 schedule: "Dr 6033 / Cr 32", accounts in the entry's order, each once."""
    def unique(side):
        seen = []
        for line in lines:
            if line[side] and line["account"] not in seen:
                seen.append(line["account"])
        return ", ".join(seen)
    return "Dr %s / Cr %s" % (unique("debit"), unique("credit"))
