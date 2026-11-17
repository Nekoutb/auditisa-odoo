"""The adjustment of a misstatement (owner's mock-ups of 2026-11-16 and 2026-11-17, "wp-finding-sad").

The team writes the entry that corrects the misstatement at the bottom of its working paper: lines
of heading, label, debit and credit, balanced. Since 2026-11-17 a line no longer names a
trial-balance account: it picks one of seven headings of the financial statements (HEADINGS).
Saving the entry sends it to the summary of audit differences by itself, as the summary's lines
(one debit heading against one credit heading each, the structure the summary already reads).

A line is a dict: ``heading``, ``label``, ``debit``, ``credit``, and ``account``: the account a
line typed before 2026-11-17 carried, kept as information only (its heading starts empty, "to
classify").
"""
from ._js import js_round

ACCOUNT_MAX = 64
LABEL_MAX = 200
#: The natures the working paper offers; the summary knows two more (reclassification, disclosure).
ADJUSTMENT_NATURES = ["factual", "judgmental", "projected"]
#: The seven headings an adjustment line picks from, in the order of the statements.
HEADINGS = [
    "non_current_assets",
    "current_assets",
    "non_current_liabilities",
    "current_liabilities",
    "equity",
    "revenue",
    "expenditure",
]
HEADING_LABELS = {
    "non_current_assets": {"en": "Non-current assets", "fr": "Actifs non courants"},
    "current_assets": {"en": "Current assets", "fr": "Actifs courants"},
    "non_current_liabilities": {"en": "Non-current liabilities", "fr": "Passifs non courants"},
    "current_liabilities": {"en": "Current liabilities", "fr": "Passifs courants"},
    "equity": {"en": "Equity", "fr": "Capitaux propres"},
    "revenue": {"en": "Revenue", "fr": "Produits"},
    "expenditure": {"en": "Expenditure", "fr": "Charges"},
}
#: A heading and the summary's caption it lands under (services/sad_model.SAD_CAPTIONS).
HEADING_CAPTION = {
    "non_current_assets": "non_current_asset",
    "current_assets": "current_asset",
    "non_current_liabilities": "non_current_liability",
    "current_liabilities": "current_liability",
    "equity": "equity",
    "revenue": "income",
    "expenditure": "expense",
}
CAPTION_HEADING = {caption: heading for heading, caption in HEADING_CAPTION.items()}
#: A debit raises these; a credit raises the others.
DEBIT_HEADINGS = {"non_current_assets", "current_assets", "expenditure"}


def _r2(value):
    """To the cent, as Math.round does it."""
    return js_round(value * 100) / 100


def _total(values):
    out = 0.0
    for value in values:
        out += value
    return _r2(out)


def _clean(value):
    return 0.0 if abs(value) < 0.005 else _r2(value)


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


def heading_label(heading, locale="en"):
    labels = HEADING_LABELS.get(heading)
    return labels[locale if locale in labels else "en"] if labels else ""


def clean_lines(lines):
    """The lines as saved: trimmed, fully blank lines dropped. A line with an amount on both
    sides, a negative one, or an unknown heading is refused; a line still missing its heading
    or amount is kept (the team is typing it, or it is an old line "to classify") and stops
    only the sending to the summary."""
    out = []
    for line in lines or ():
        heading = str(line.get("heading") or "").strip()
        if heading and heading not in HEADINGS:
            raise AdjustmentError("adjustment-line")
        account = str(line.get("account") or "").strip()[:ACCOUNT_MAX]
        label = str(line.get("label") or "").strip()[:LABEL_MAX]
        debit, credit = _amount(line.get("debit")), _amount(line.get("credit"))
        if not (heading or label or debit or credit):
            continue
        if debit and credit:
            raise AdjustmentError("adjustment-line")
        out.append({"heading": heading, "account": account, "label": label, "debit": debit, "credit": credit})
    return out


def totals(lines):
    debit = _total(line["debit"] for line in lines)
    credit = _total(line["credit"] for line in lines)
    return {"debit": debit, "credit": credit, "balanced": bool(debit) and abs(debit - credit) < 0.005}


def booking_error(lines):
    """Why the adjustment cannot go to the summary yet, as a rule code; None when it can."""
    if not lines:
        return "adjustment-unbalanced"
    for line in lines:
        if not line["heading"] or not (line["debit"] or line["credit"]):
            return "adjustment-line"
    if not totals(lines)["balanced"] or not any(line["debit"] for line in lines) or not any(line["credit"] for line in lines):
        return "adjustment-unbalanced"
    return None


def heading_effects(lines):
    """What the entry does to each heading, positive when it raises it (a debit raises assets
    and expenditure, a credit the others), plus ``profit`` (revenue - expenditure). The
    ``equity`` figure includes the profit for the year. A line with no heading counts nowhere."""
    out = {heading: 0.0 for heading in HEADINGS}
    for line in lines:
        heading = line.get("heading")
        if heading not in out:
            continue
        net = line["debit"] - line["credit"]
        out[heading] += net if heading in DEBIT_HEADINGS else -net
    profit = out["revenue"] - out["expenditure"]
    out["equity"] += profit
    out["profit"] = profit
    return {key: _clean(value) for key, value in out.items()}


def adjustment_effect(lines):
    """The effect line: profit, assets, liabilities and equity (equity takes the profit as
    well, so assets = liabilities + equity for a balanced entry), from the headings."""
    by_heading = heading_effects(lines)
    return {
        "profit": by_heading["profit"],
        "assets": _clean(by_heading["non_current_assets"] + by_heading["current_assets"]),
        "liabilities": _clean(by_heading["non_current_liabilities"] + by_heading["current_liabilities"]),
        "equity": by_heading["equity"],
    }


def adjustment_pairs(lines, key="heading"):
    """The summary lines of a balanced entry: each debit set against the credits in order, so
    an entry of one debit and one credit is one line, and Dr A 100, Dr B 50 / Cr C 150 is two.
    Each pair carries the ``key`` of both sides (``dr``, ``cr``) and their labels."""
    debits = [[line[key], line["debit"], line.get("label") or ""] for line in lines if line["debit"]]
    credits = [[line[key], line["credit"], line.get("label") or ""] for line in lines if line["credit"]]
    pairs, i, j = [], 0, 0
    while i < len(debits) and j < len(credits):
        amount = _r2(min(debits[i][1], credits[j][1]))
        if amount:
            pairs.append({
                "dr": debits[i][0], "cr": credits[j][0], "amount": amount,
                "dr_label": debits[i][2], "cr_label": credits[j][2],
            })
        debits[i][1] = _r2(debits[i][1] - amount)
        credits[j][1] = _r2(credits[j][1] - amount)
        if debits[i][1] < 0.005:
            i += 1
        if credits[j][1] < 0.005:
            j += 1
    return pairs


def accounts_text(lines, locale="en"):
    """For the C1.1 schedule: "Dr Expenditure / Cr Current assets", headings in the entry's
    order, each once."""
    def unique(side):
        seen = []
        for line in lines:
            name = heading_label(line["heading"], locale) or line.get("account") or ""
            if line[side] and name and name not in seen:
                seen.append(name)
        return ", ".join(seen)
    return "Dr %s / Cr %s" % (unique("debit"), unique("credit"))


def effect_table(groups):
    """The SAD's "Effect on the financial statements": ``groups`` are lists of lines, each with a
    ``posted`` flag. One row per heading, ``all`` and ``posted`` columns; equity includes the
    profit for the year."""
    every, posted = [], []
    for lines, is_posted in groups:
        every.extend(lines)
        if is_posted:
            posted.extend(lines)
    a, p = heading_effects(every), heading_effects(posted)
    return [{"heading": heading, "all": a[heading], "posted": p[heading]} for heading in HEADINGS]
