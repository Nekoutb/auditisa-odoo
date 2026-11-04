"""lib/amount.ts: one amount parser for the whole product.

A French user types "1 500 000,75", an English one "1,500,000.75", a spreadsheet
export may produce either. All three must mean the same number.
"""
import math
import re
import unicodedata

from ._js import JS_LINE_TERMINATORS, JS_S, is_number, js_str, js_trim

_GROUPING_SPACE = re.compile("[" + JS_S + "\xa0  ]")
_NOISE = re.compile(r"[^0-9.,()+\-]")
# re.ASCII gives \b JavaScript's ASCII-only word boundary, and re.IGNORECASE the
# non-unicode /i behaviour (a non-ASCII character never folds onto an ASCII one)
_CURRENCY_TOKENS = re.compile(
    r"\b(F[" + JS_S + r"]?CFA|FCFA|XAF|XOF|CFA|EUR|USD|GBP|F)\b|[€$£]",
    re.IGNORECASE | re.ASCII,
)
_BRACKETED = re.compile(r"\(([^" + JS_LINE_TERMINATORS + r"]*)\)")
_NUMBER = re.compile(r"[0-9]*\.?[0-9]+")


def _has_letter(text):
    return any(unicodedata.category(c)[0] == "L" for c in text)


def parse_amount(value):
    """A human-entered or exported amount; None when it is not a number."""
    if is_number(value):
        return value if math.isfinite(value) else None
    if value is None:
        return None

    raw = js_trim(js_str(value))
    if raw == "":
        return None

    raw = raw.replace("−", "-")

    # Accounting negatives: (1 234,56)
    bracketed = _BRACKETED.fullmatch(raw) is not None
    if bracketed:
        raw = raw[1:-1]

    # A trailing sign, as some ledger exports write it: 1 234,56-
    trailing_negative = False
    if raw.endswith("-"):
        trailing_negative = True
        raw = raw[:-1]

    raw = _CURRENCY_TOKENS.sub("", raw)
    if _has_letter(raw):
        return None
    had_grouping = _GROUPING_SPACE.search(raw) is not None
    s = _NOISE.sub("", _GROUPING_SPACE.sub("", raw))
    if s == "":
        return None

    negative = bracketed or trailing_negative
    if s[0] in "+-":
        if s[0] == "-":
            negative = not negative
        s = s[1:]
    # A sign anywhere else means this was never a single number.
    if "+" in s or "-" in s:
        return None

    decimal_index = _decimal_separator_index(s, had_grouping)
    if decimal_index == -1:
        s = s.replace(".", "").replace(",", "")
    else:
        whole = s[:decimal_index].replace(".", "").replace(",", "")
        fraction = s[decimal_index + 1:].replace(".", "").replace(",", "")
        s = whole + "." + fraction

    if s == "" or s == ".":
        return None
    if _NUMBER.fullmatch(s) is None:
        return None

    parsed = float(s)
    if not math.isfinite(parsed):
        return None
    return -parsed if negative else parsed


def amount_or(value, fallback=0):
    """Same, but yields ``fallback`` instead of None: for sums and control totals."""
    parsed = parse_amount(value)
    return fallback if parsed is None else parsed


def _decimal_separator_index(s, had_grouping):
    """Which separator is the decimal point, -1 when all of them group digits.

    ``had_grouping`` resolves the one ambiguous case: "12 345,678" is 12345.678,
    while a bare "1,500" is conventionally 1500.
    """
    last_dot = s.rfind(".")
    last_comma = s.rfind(",")
    if last_dot == -1 and last_comma == -1:
        return -1

    # Both present: the rightmost is the decimal point, the other groups digits.
    if last_dot != -1 and last_comma != -1:
        return max(last_dot, last_comma)

    index = last_comma if last_dot == -1 else last_dot
    # Repeated means grouping: 1.500.000 is one and a half million.
    if s.count(s[index]) > 1:
        return -1

    fraction_digits = len(s) - index - 1
    if fraction_digits != 3:
        return index if fraction_digits > 0 else -1
    # Exactly three digits after a lone separator is the ambiguous case.
    return index if had_grouping else -1
