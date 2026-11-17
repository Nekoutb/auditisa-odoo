"""EAGLA analyses 31 and 32: two-way and three-way correlation between accounts, month by month.

The database sums the ledger by account and calendar month of the year audited (one row per
account and month, whatever the size of the ledger); everything here works on those rows.

Sign convention: every account counts on its natural side. Credits are positive for classes 1
and 7, for the credit accounts of class 4 and for the income accounts of class 8 (82, 84, 86,
88); debits are positive for every other account. So sales (70) and the VAT they carry (443)
are both positive, as are purchases (60) and the VAT recoverable on them (445).
"""
import re

from ._js import js_sum
from .errors import ServiceError

#: Months apart: more than this many percentage points from the yearly average.
DEFAULT_TOLERANCE = 1.5
MAX_PREFIXES = 20
_PREFIX = re.compile(r"^[0-9A-Za-z]{1,12}$")
#: The debit accounts of class 4: supplier advances, customers (but not their advances, 419),
#: VAT recoverable and other amounts the State owes.
DEBIT_CLASS_4 = ("409", "41", "445", "449")

MONTHS = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "fr": ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."],
}

SIGN_LINE = {
    "en": "Each account counts on its natural side: credits are positive for classes 1 and 7 and for the credit accounts of classes 4 and 8, debits for all others.",
    "fr": "Chaque compte est pris de son côté naturel : les crédits sont positifs pour les classes 1 et 7 et pour les comptes créditeurs des classes 4 et 8, les débits pour tous les autres.",
}


def read_prefixes(text):
    """Accounts or account prefixes typed with commas, spaces or semicolons between them."""
    pieces = [piece for piece in re.split(r"[\s,;]+", text or "") if piece]
    if not pieces or len(pieces) > MAX_PREFIXES or not all(_PREFIX.match(piece) for piece in pieces):
        raise ServiceError("invalid-accounts")
    return list(dict.fromkeys(pieces))


def credit_normal(account):
    """True when the account's natural balance is a credit."""
    code = (account or "").strip()
    first = code[:1]
    if first in ("1", "7"):
        return True
    if first == "4":
        return code.startswith("419") or not code.startswith(DEBIT_CLASS_4)
    if first == "8":
        return code[1:2] in ("2", "4", "6", "8")
    return False


def natural(account, signed):
    """A movement (debit minus credit) on the account's natural side."""
    return -signed if credit_normal(account) else signed


def month_keys(start_year, start_month):
    """The twelve (year, month) of the year audited, from its first month."""
    keys = []
    for offset in range(12):
        index = start_month - 1 + offset
        keys.append((start_year + index // 12, index % 12 + 1))
    return keys


def month_labels(keys, locale):
    return [MONTHS[locale][month - 1] for _year, month in keys]


def matches(account, prefixes):
    return any(account.startswith(prefix) for prefix in prefixes)


def totals(rows, prefixes, keys):
    """Twelve monthly totals and the year's, on the natural side, of the accounts that start with
    any of the prefixes. ``rows`` are dicts with account, y, m and v (debit minus credit)."""
    position = {key: index for index, key in enumerate(keys)}
    months = [0.0] * 12
    for row in rows:
        index = position.get((row["y"], row["m"]))
        if index is None or not matches(row["account"], prefixes):
            continue
        months[index] += natural(row["account"], row["v"])
    return months, js_sum(months, 0.0)


def percent(numerator, denominator):
    """numerator ÷ denominator in %, or None when the denominator is nil."""
    if not denominator:
        return None
    return numerator / denominator * 100


def two_way(rows, numerator, denominator, keys, tolerance=DEFAULT_TOLERANCE):
    """The numerator and denominator by month, their ratio in % and the months that stand apart:
    further than ``tolerance`` percentage points from the year's ratio."""
    if tolerance is None or tolerance < 0:
        tolerance = DEFAULT_TOLERANCE
    num, num_year = totals(rows, numerator, keys)
    den, den_year = totals(rows, denominator, keys)
    ratios = [percent(n, d) for n, d in zip(num, den)]
    year = percent(num_year, den_year)
    apart = [
        index for index, value in enumerate(ratios)
        if value is not None and year is not None and abs(value - year) > tolerance + 1e-9
    ]
    return {
        "numeratorAccounts": numerator, "denominatorAccounts": denominator,
        "numerator": num, "numeratorYear": num_year, "denominator": den, "denominatorYear": den_year,
        "ratios": ratios, "yearRatio": year, "apart": apart, "tolerance": tolerance,
    }


def three_way(rows, a, b, c, keys):
    """A, B and C by month, with B ÷ A, A ÷ C and B ÷ C in % for each month and for the year."""
    a_months, a_year = totals(rows, a, keys)
    b_months, b_year = totals(rows, b, keys)
    c_months, c_year = totals(rows, c, keys)
    return {
        "accounts": {"a": a, "b": b, "c": c},
        "a": a_months, "b": b_months, "c": c_months,
        "years": {"a": a_year, "b": b_year, "c": c_year},
        "ratios": {
            "ba": [percent(y, x) for x, y in zip(a_months, b_months)],
            "ac": [percent(x, z) for x, z in zip(a_months, c_months)],
            "bc": [percent(y, z) for y, z in zip(b_months, c_months)],
        },
        "yearRatios": {"ba": percent(b_year, a_year), "ac": percent(a_year, c_year), "bc": percent(b_year, c_year)},
    }


def apart_line(apart, labels, year, locale):
    """One plain line naming the months that stand apart from the year's ratio."""
    if year is None:
        return "Aucun rapport annuel : le dénominateur est nul sur l'année." if locale == "fr" else "No yearly ratio: the denominator is nil over the year."
    if not apart:
        return "Aucun mois ne s'écarte de la moyenne annuelle." if locale == "fr" else "No month stands apart from the yearly average."
    names = [labels[index] for index in apart]
    joined = names[0] if len(names) == 1 else "%s %s %s" % (", ".join(names[:-1]), "et" if locale == "fr" else "and", names[-1])
    if locale == "fr":
        return "%s %s de la moyenne annuelle." % (joined, "s'écarte" if len(names) == 1 else "s'écartent")
    return "%s %s apart from the yearly average." % (joined, "stands" if len(names) == 1 else "stand")


def radii(values, largest=70.0, smallest=8.0):
    """Circle radii whose areas follow the yearly totals (their sizes, whatever their sign)."""
    sizes = [abs(value or 0.0) for value in values]
    top = max(sizes) if sizes else 0.0
    if not top:
        return [smallest for _value in sizes]
    return [max(smallest, largest * (size / top) ** 0.5) for size in sizes]


def month_rows(lines, start, end):
    """The database's work, in Python, for the tests: ledger lines (account, date, debit, credit)
    of the year summed by account and calendar month."""
    sums = {}
    for line in lines:
        if not line["date"] or not start <= line["date"] <= end:
            continue
        key = (line["account"], int(line["date"][0:4]), int(line["date"][5:7]))
        sums[key] = sums.get(key, 0.0) + (line.get("debit") or 0) - (line.get("credit") or 0)
    return [{"account": account, "y": y, "m": m, "v": value} for (account, y, m), value in sorted(sums.items())]
