"""JavaScript semantics the ports depend on. No Odoo, no third-party imports.

The TypeScript this package was ported from leans on behaviour Python does not
share. Each helper below reproduces one of them, and the parity fixtures hold
them to what Node actually returned:

- ``Math.round`` rounds halves toward +infinity (Python's ``round`` is bankers').
- ``sum()`` on floats is compensated from Python 3.12 on, so it can differ from a
  JavaScript ``reduce`` in the last bit: use ``js_sum`` (a test forbids ``sum``).
- ``\\s``, ``String.trim`` cover a different character set from Python's.
- ``String(number)`` prints 1e21 and 1e-7, never ``1.0``.
- ``new Date(text)`` accepts V8's legacy formats and rolls 30 February over.
- ``localeCompare`` and ``Intl.NumberFormat`` come from ICU.

Rounding helpers return ``int`` below 2**53 and ``float`` above it, where a
Python int would stay exact and a JavaScript number would not. ``-0`` is not
preserved: it reaches JSON, and so the database, as ``0``.

Everything "local" in JavaScript (a date-time without an offset, ``getDay``) is
UTC here. The source depends on the server's time zone at those points.
"""
import math
import re
import unicodedata
from decimal import ROUND_HALF_UP, Context, Decimal

from .errors import JsRangeError

_WIDE = Context(prec=400)  # room for the whole of 1.7976931348623157e308

# ---- whitespace ---------------------------------------------------------

#: The characters of JS ``\s`` and ``String.prototype.trim``.
JS_WHITESPACE = (
    "\t\n\x0b\x0c\r \xa0 "
    "           "
    "    　﻿"
)
#: The same set, for use inside a regular-expression character class.
JS_S = re.escape(JS_WHITESPACE)
#: What JS ``.`` does not match, for use inside a negated character class.
JS_LINE_TERMINATORS = "\n\r  "


def js_trim(value):
    """``String.prototype.trim``."""
    return value.strip(JS_WHITESPACE)


# ---- numbers ------------------------------------------------------------

_EXACT = 2 ** 53


def is_number(value):
    """``typeof value === "number"``: a bool is not a number in JavaScript."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_finite(value):
    """``Number.isFinite``."""
    return is_number(value) and math.isfinite(value)


def is_integer(value):
    """``Number.isInteger``."""
    return is_finite(value) and float(value).is_integer()


def _whole(value):
    return value if abs(value) < _EXACT else float(value)


def js_floor(value):
    """``Math.floor``: NaN and the infinities pass through instead of raising."""
    if isinstance(value, float) and not math.isfinite(value):
        return value
    return _whole(math.floor(value))


def js_ceil(value):
    """``Math.ceil``."""
    if isinstance(value, float) and not math.isfinite(value):
        return value
    return _whole(math.ceil(value))


def js_round(value):
    """``Math.round``: to the nearest integer, halves toward +infinity."""
    if isinstance(value, float) and not math.isfinite(value):
        return value
    floor = math.floor(value)
    # exact: below 2**52 the fractional part of a double is itself a double,
    # which is why this is not floor(value + 0.5) (wrong for 0.49999999999999994)
    return _whole(floor + 1 if value - floor >= 0.5 else floor)


def js_sum(values, start=0):
    """A left-to-right ``reduce``, without Python 3.12's compensated ``sum``."""
    total = start
    for value in values:
        total += value
    return total


def js_number_str(value):
    """``String(number)``."""
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
    if value == 0:
        return "0"
    if isinstance(value, int) and abs(value) < _EXACT:
        return str(value)
    sign = "-" if value < 0 else ""
    mantissa, _, exponent = repr(abs(float(value))).partition("e")
    whole, _, fraction = mantissa.partition(".")
    digits = (whole + fraction).lstrip("0")
    # n as in the ES spec: the value is 0.<digits> x 10**n
    if whole == "0":
        n = -(len(fraction) - len(fraction.lstrip("0"))) + int(exponent or 0)
    else:
        n = len(whole) + int(exponent or 0)
    digits = digits.rstrip("0") or "0"
    k = len(digits)
    if k <= n <= 21:
        return sign + digits + "0" * (n - k)
    if 0 < n <= 21:
        return sign + digits[:n] + "." + digits[n:]
    if -6 < n <= 0:
        return sign + "0." + "0" * -n + digits
    e = n - 1
    tail = ("+" if e >= 0 else "-") + str(abs(e))
    if k == 1:
        return sign + digits + "e" + tail
    return sign + digits[0] + "." + digits[1:] + "e" + tail


def js_str(value):
    """``String(value)`` for the values a cell or a JSON document can hold."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return js_number_str(value)
    if isinstance(value, (list, tuple)):
        return ",".join("" if v is None else js_str(v) for v in value)
    return "[object Object]"


def cell_str(value):
    """``String(value ?? "")``, the way the source reads a cell."""
    return "" if value is None else js_str(value)


# ---- strings ------------------------------------------------------------

def u16_len(value):
    """``String.prototype.length``: UTF-16 code units."""
    length = len(value)
    for c in value:
        if ord(c) > 0xFFFF:
            length += 1
    return length


def u16_slice(value, start=0, end=None):
    """``String.prototype.slice`` for non-negative bounds, on UTF-16 code units."""
    if value.isascii() or all(ord(c) <= 0xFFFF for c in value):
        return value[start:end]
    units = value.encode("utf-16-le", "surrogatepass")
    stop = None if end is None else end * 2
    # a cut through an emoji leaves half of it, in JavaScript too
    return units[start * 2:stop].decode("utf-16-le", "surrogatepass")


def js_sorted(values):
    """``Array.prototype.sort()`` on strings: by UTF-16 code unit."""
    return sorted(values, key=lambda s: s.encode("utf-16-be", "surrogatepass"))


_REPLACEMENT = re.compile(r"\$(\$|&|`|')")


def js_replace_all(text, search, replacement):
    """``replaceAll(string, string)``: ``$&``, ``$$``, ``$``` and ``$'`` are patterns."""
    if search not in text:
        return text
    out = []
    position = 0
    while True:
        at = text.find(search, position)
        if at < 0:
            out.append(text[position:])
            return "".join(out)
        out.append(text[position:at])
        end = at + len(search)

        def expand(match, at=at, end=end):
            token = match.group(1)
            if token == "$":
                return "$"
            if token == "&":
                return search
            return text[:at] if token == "`" else text[end:]

        out.append(_REPLACEMENT.sub(expand, replacement))
        position = end


# ---- ICU ----------------------------------------------------------------

# CLDR root collation order of ASCII punctuation and symbols.
_ICU_ORDER = "_-,;:!?.'\"()[]{}@*/\\&#%`^+<=>|~$"
_ICU_RANK = {c: i + 1 for i, c in enumerate(_ICU_ORDER)}
_DIGIT_BASE = 100
_LETTER_BASE = 1000


def _collation_elements(text, numeric):
    """Per collation element: (primary, secondary, tertiary)."""
    elements = []
    i = 0
    decomposed = unicodedata.normalize("NFD", text)
    while i < len(decomposed):
        c = decomposed[i]
        if numeric and "0" <= c <= "9":
            j = i
            while j < len(decomposed) and "0" <= decomposed[j] <= "9":
                j += 1
            run = decomposed[i:j].lstrip("0") or "0"
            elements.append(((_DIGIT_BASE, len(run), int(run)), 0, 0))
            i = j
            continue
        i += 1
        if unicodedata.combining(c):
            if elements:
                primary, secondary, tertiary = elements[-1]
                elements[-1] = (primary, secondary * 1000 + ord(c), tertiary)
            continue
        if c.isspace():
            primary = (0, ord(c), 0)
        elif c in _ICU_RANK:
            primary = (1, _ICU_RANK[c], 0)
        elif "0" <= c <= "9":
            primary = (_DIGIT_BASE, 1, int(c))
        else:
            primary = (_LETTER_BASE, ord(c.lower()), 0)
        elements.append((primary, 0, 1 if c != c.lower() else 0))
    return elements


def locale_compare(left, right, numeric=False):
    """``left.localeCompare(right, undefined, { numeric })`` in the root collation.

    Faithful for what the source sorts: account prefixes and sub-index codes,
    that is ASCII and accented Latin. It is not a general ICU replacement.
    """
    a = _collation_elements(left, numeric)
    b = _collation_elements(right, numeric)
    for level in range(3):
        x = [e[level] for e in a]
        y = [e[level] for e in b]
        if x != y:
            return -1 if x < y else 1
    return 0


def format_fr(value):
    """``new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 2 }).format``."""
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "∞" if value > 0 else "-∞"
    negative = value < 0 or (isinstance(value, float) and math.copysign(1, value) < 0)
    # ICU rounds the shortest decimal that names the double, half away from zero
    rounded = Decimal(repr(abs(value))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP, context=_WIDE)
    whole, _, fraction = format(rounded, "f").partition(".")
    fraction = fraction.rstrip("0")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    body = " ".join(groups)
    if fraction:
        body += "," + fraction
    return ("-" if negative else "") + body


# ---- dates --------------------------------------------------------------

_MS_PER_DAY = 86_400_000
_MAX_TIME = 8.64e15


def _days_from_civil(year, month, day):
    """Days since 1970-01-01 of a proleptic Gregorian date, month 1 to 12."""
    year -= month <= 2
    era = year // 400
    yoe = year - era * 400
    doy = (153 * (month + (-3 if month > 2 else 9)) + 2) // 5 + day - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def _civil_from_days(days):
    days += 719468
    era = days // 146097
    doe = days - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + (3 if mp < 10 else -9)
    return yoe + era * 400 + (month <= 2), month, day


def make_day(year, month0, day):
    """``MakeDay``: month and day overflow roll over, as ``setUTC*`` does."""
    return _days_from_civil(year + month0 // 12, month0 % 12 + 1, 1) + day - 1


def _time_clip(ms):
    return None if abs(ms) > _MAX_TIME else ms


def date_utc(year, month0, day=1, hour=0, minute=0, second=0, ms=0):
    """``Date.UTC``, years 0 to 99 meaning 19xx. None stands for an invalid date."""
    if 0 <= year <= 99:
        year += 1900
    return _time_clip(make_day(year, month0, day) * _MS_PER_DAY + hour * 3_600_000 + minute * 60_000 + second * 1000 + ms)


def date_parts(ms):
    """(year, month0, day) of a time value."""
    year, month, day = _civil_from_days(ms // _MS_PER_DAY)
    return year, month - 1, day


def add_utc(ms, years=0, months=0, days=0):
    """``setUTCFullYear`` / ``setUTCMonth`` / ``setUTCDate`` on a time value: the
    fields move and whatever does not exist rolls over (29 Feb + 1 y = 1 Mar)."""
    year, month0, day = date_parts(ms)
    time_of_day = ms % _MS_PER_DAY
    return _time_clip(make_day(year + years, month0 + months, day + days) * _MS_PER_DAY + time_of_day)


def weekday(ms):
    """``getUTCDay``: 0 is Sunday."""
    return (ms // _MS_PER_DAY + 4) % 7


def to_iso(ms):
    """``toISOString``; an invalid date raises ``RangeError`` as JavaScript does."""
    if ms is None:
        raise JsRangeError("Invalid time value")
    year, month0, day = date_parts(ms)
    rest = ms % _MS_PER_DAY
    if 0 <= year <= 9999:
        y = "%04d" % year
    else:
        y = ("-" if year < 0 else "+") + "%06d" % abs(year)
    return "%s-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        y, month0 + 1, day, rest // 3_600_000, rest // 60_000 % 60, rest // 1000 % 60, rest % 1000,
    )


def to_iso_date(ms):
    """``toISOString().slice(0, 10)``."""
    return to_iso(ms)[:10]


class _Token:
    __slots__ = ("kind", "value", "length", "keyword")

    def __init__(self, kind, value=None, length=0, keyword=None):
        self.kind = kind  # number, symbol, space, word, end, invalid
        self.value = value
        self.length = length
        self.keyword = keyword

    def is_symbol(self, c):
        return self.kind == "symbol" and self.value == c

    def is_sign(self):
        return self.kind == "symbol" and self.value in "+-"

    def fixed(self, n):
        return self.kind == "number" and self.length == n

    def is_z(self):
        return self.kind == "word" and self.keyword == ("tz", 0, "z")


_MONTHS = {m: i + 1 for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split())}
_WORDS = {
    "am": ("ampm", 0), "pm": ("ampm", 12),
    "ut": ("tz", 0, "ut"), "utc": ("tz", 0, "utc"), "z": ("tz", 0, "z"), "gmt": ("tz", 0, "gmt"),
    "cdt": ("tz", -5, "cdt"), "cst": ("tz", -6, "cst"), "edt": ("tz", -4, "edt"), "est": ("tz", -5, "est"),
    "mdt": ("tz", -6, "mdt"), "mst": ("tz", -7, "mst"), "pdt": ("tz", -7, "pdt"), "pst": ("tz", -8, "pst"),
    "t": ("t",),
}


def _tokenize(text):
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if "0" <= c <= "9":
            j = i
            while j < n and "0" <= text[j] <= "9":
                j += 1
            run = text[i:j]
            significant = run.lstrip("0")
            # V8 keeps nine significant digits; more than that cannot name a field
            number = int(significant[:9] or "0")
            tokens.append(_Token("number", number, j - i))
            i = j
        elif c in JS_WHITESPACE:
            tokens.append(_Token("space"))
            i += 1
        elif c >= "A" and c not in "[\\]^_`{|}~" or ord(c) > 127:
            j = i
            while j < n and (text[j] >= "A" and text[j] not in "[\\]^_`{|}~" or ord(text[j]) > 127) and text[j] not in JS_WHITESPACE:
                j += 1
            word = text[i:j].lower()
            prefix = word[:3]
            keyword = None
            if len(word) >= 3 and prefix in _MONTHS:
                keyword = ("month", _MONTHS[prefix])
            elif word in _WORDS:
                keyword = _WORDS[word]
            tokens.append(_Token("word", word, j - i, keyword))
            i = j
        else:
            tokens.append(_Token("symbol", c, 1))
            i += 1
    tokens.append(_Token("end"))
    return tokens


class _Parser:
    def __init__(self, text):
        self.tokens = _tokenize(text)
        self.at = 0
        self.day = []
        self.named_month = None
        self.is_iso = False
        self.time = []
        self.hour_offset = None
        self.tz_sign = None
        self.tz_hour = None
        self.tz_minute = None

    def peek(self):
        return self.tokens[self.at]

    def next(self):
        token = self.tokens[self.at]
        if token.kind != "end":
            self.at += 1
        return token

    def skip(self, c):
        if self.peek().is_symbol(c):
            self.next()
            return True
        return False

    def tz_set(self, offset_hours):
        self.tz_sign = 1 if offset_hours >= 0 else -1
        self.tz_hour = abs(offset_hours)
        self.tz_minute = 0

    def time_expecting(self, n):
        length = len(self.time)
        return (length == 1 and 0 <= n < 60) or (length == 2 and 0 <= n < 60) or (length == 3 and 0 <= n < 1000)

    def es5(self):
        """V8's ParseES5DateTime: the next unhandled token, ``end`` on success."""
        if self.peek().is_sign():
            sign_token = self.next()
            if not self.peek().fixed(6):
                return sign_token
            sign = -1 if sign_token.value == "-" else 1
            year = self.next().value
            if sign < 0 and year == 0:
                return sign_token
            self.day.append(sign * year)
        elif self.peek().fixed(4):
            self.day.append(self.next().value)
        else:
            return self.next()
        if self.skip("-"):
            if not self.peek().fixed(2) or not 1 <= self.peek().value <= 12:
                return self.next()
            self.day.append(self.next().value)
            if self.skip("-"):
                if not self.peek().fixed(2) or not 1 <= self.peek().value <= 31:
                    return self.next()
                self.day.append(self.next().value)
        token = self.peek()
        if not (token.kind == "word" and token.keyword == ("t",)):
            if token.kind != "end":
                return self.next()
        else:
            invalid = _Token("invalid")
            self.next()
            if not self.peek().fixed(2) or not 0 <= self.peek().value <= 24:
                return invalid
            hour_24 = self.peek().value == 24
            self.time.append(self.next().value)
            if not self.skip(":"):
                return invalid
            if not self.peek().fixed(2) or not self.peek().value < 60 or (hour_24 and self.peek().value > 0):
                return invalid
            self.time.append(self.next().value)
            if self.skip(":"):
                if not self.peek().fixed(2) or not self.peek().value < 60 or (hour_24 and self.peek().value > 0):
                    return invalid
                self.time.append(self.next().value)
                if self.skip("."):
                    if self.peek().kind != "number" or (hour_24 and self.peek().value > 0):
                        return invalid
                    self.time.append(_read_ms(self.next()))
            if self.peek().is_z():
                self.next()
                self.tz_set(0)
            elif self.peek().is_sign():
                self.tz_sign = 1 if self.next().value == "+" else -1
                if self.peek().fixed(4):
                    hourmin = self.next().value
                    if not hourmin // 100 < 24 or not hourmin % 100 < 60:
                        return invalid
                    self.tz_hour = hourmin // 100
                    self.tz_minute = hourmin % 100
                else:
                    if not self.peek().fixed(2) or not self.peek().value < 24:
                        return invalid
                    self.tz_hour = self.next().value
                    if not self.skip(":"):
                        return invalid
                    if not self.peek().fixed(2) or not self.peek().value < 60:
                        return invalid
                    self.tz_minute = self.next().value
            if self.peek().kind != "end":
                return invalid
        if self.tz_sign is None and not self.time:
            self.tz_set(0)
        self.is_iso = True
        return _Token("end")

    def legacy(self, token):
        """V8's legacy loop over what the ES5 attempt left."""
        has_number = bool(self.day)
        while token.kind != "end":
            if token.kind == "number":
                has_number = True
                n = token.value
                if self.skip(":"):
                    if self.skip(":"):
                        return False
                    if len(self.time) >= 4:
                        return False
                    self.time.append(n)
                    if self.peek().is_symbol("."):
                        self.next()
                elif self.peek().is_symbol(".") and self.time_expecting(n):
                    self.next()
                    self.time.append(n)
                    if self.peek().kind != "number":
                        return False
                    self.time.append(_read_ms(self.next()))
                    self.time.extend([0] * (4 - len(self.time)))
                elif self.peek().is_symbol("."):
                    # SkipSymbol('.') already consumed it in V8, whichever branch follows
                    self.next()
                    if not self._plain_number(n):
                        return False
                elif not self._plain_number(n):
                    return False
            elif token.kind == "word":
                keyword = token.keyword
                kind = keyword[0] if keyword else None
                if kind == "ampm" and self.time:
                    self.hour_offset = keyword[1]
                elif kind == "month":
                    self.named_month = keyword[1]
                    self.skip("-")
                elif kind == "tz" and has_number:
                    self.tz_set(keyword[1])
                else:
                    if has_number:
                        return False
                    if self.peek().kind == "number":
                        return False
            elif token.is_sign() and ((self.tz_hour == 0 and self.tz_minute == 0) or self.time):
                self.tz_sign = 1 if token.value == "+" else -1
                n = 0
                length = 0
                if self.peek().kind == "number":
                    number = self.next()
                    n = number.value
                    length = number.length
                has_number = True
                if self.peek().is_symbol(":"):
                    self.tz_hour = n
                    self.tz_minute = None
                elif length in (1, 2):
                    self.tz_hour = n
                    self.tz_minute = 0
                elif length in (3, 4):
                    self.tz_hour = n // 100
                    self.tz_minute = n % 100
                else:
                    return False
            elif (token.is_sign() or token.is_symbol(")")) and has_number:
                return False
            elif token.is_symbol("("):
                depth = 1
                while depth and self.peek().kind != "end":
                    inner = self.next()
                    if inner.is_symbol("("):
                        depth += 1
                    elif inner.is_symbol(")"):
                        depth -= 1
            token = self.next()
        return True

    def _plain_number(self, n):
        if self.tz_hour is not None and self.tz_minute is None and 0 <= n < 60:
            self.tz_minute = n
        elif self.time_expecting(n):
            self.time.append(n)
            self.time.extend([0] * (4 - len(self.time)))
            peek = self.peek()
            if not (peek.kind in ("end", "space") or peek.is_z() or peek.is_sign()):
                return False
        else:
            if len(self.day) >= 3:
                return False
            self.day.append(n)
            self.skip("-")
        return True

    def result(self):
        if not self.day:
            return None
        comp = self.day + [1] * (3 - len(self.day))
        if self.named_month is None:
            if self.is_iso or not 1 <= comp[0] <= 31:
                year, month, day = comp
            else:
                month, day, year = comp
        else:
            month = self.named_month
            # the unread fields already default to 1 here: "15 Jan" is 15 January 2001
            if not 1 <= comp[0] <= 31:
                year, day = comp[0], comp[1]
            else:
                day, year = comp[0], comp[1]
        if not self.is_iso:
            if 0 <= year <= 49:
                year += 2000
            elif 50 <= year <= 99:
                year += 1900
        if not 1 <= month <= 12 or not 1 <= day <= 31:
            return None
        time = self.time + [0] * (4 - len(self.time))
        hour, minute, second, ms = time[:4]
        if self.hour_offset is not None:
            if not 0 <= hour <= 12:
                return None
            hour = hour % 12 + self.hour_offset
        if not (hour < 24 and minute < 60 and second < 60 and ms < 1000):
            if hour != 24 or minute != 0 or second != 0 or ms != 0:
                return None
        offset = 0
        if self.tz_sign is not None:
            offset = self.tz_sign * ((self.tz_hour or 0) * 3600 + (self.tz_minute or 0) * 60)
        days = make_day(year, month - 1, day)
        return _time_clip(days * _MS_PER_DAY + hour * 3_600_000 + minute * 60_000 + second * 1000 + ms - offset * 1000)


def _read_ms(token):
    """V8's ReadMilliseconds: the first three digits of the fraction."""
    number = token.value
    length = token.length
    if length == 1:
        return number * 100
    if length == 2:
        return number * 10
    if length > 3:
        # leading zeros were dropped from `number`; put the digits back in place
        digits = str(number).rjust(length, "0") if length <= 9 else str(number)
        return int(digits[:3])
    return number


def js_date_parse(text):
    """``Date.parse`` as V8 does it (time value in ms, None for NaN), with UTC as
    the local zone. Mirrors the ES5 attempt, then the legacy fallback."""
    parser = _Parser(text)
    token = parser.es5()
    if token.kind == "invalid":
        return None
    if not parser.legacy(token):
        return None
    return parser.result()
