"""lib/retention.ts: retention arithmetic and the legal-hold refusals, without the DB."""
import re

from ._js import add_utc, is_integer, js_date_parse, js_trim, to_iso_date
from .errors import JsRangeError, RetentionError

RETENTION_MIN_YEARS = 10
RETENTION_MAX_YEARS = 30

_ISO_DATE = re.compile(r"(-?[0-9]+)-([0-9]{2})-([0-9]{2})")


def assert_retention_years(years):
    """OHADA / ISA 230 practice: ten years is the floor (UAT B65)."""
    if not is_integer(years) or years < RETENTION_MIN_YEARS or years > RETENTION_MAX_YEARS:
        raise RetentionError("retention-out-of-range")


def retention_date(report_date, period_end, years):
    """The date a file may first be considered for destruction: the report date, or
    the period end when no report was issued, plus the firm's period.

    JavaScript arithmetic: 29 February plus 10 years is 1 March. The date actually
    stamped on an archived file comes from SQL: see ``retention_until_sql``.
    """
    start = js_date_parse("%sT00:00:00Z" % (period_end if report_date is None else report_date))
    if start is None:
        raise JsRangeError("Invalid time value")
    return to_iso_date(add_utc(start, years=years))


def retention_until_sql(report_date, period_end, years):
    """What stampRetention writes: ``coalesce(report_date, period_end) + 'n years'``.
    Postgres clamps, so 29 February plus 10 years is 28 February."""
    base = period_end if report_date is None else report_date
    match = _ISO_DATE.fullmatch(base)
    if not match:
        raise JsRangeError("Invalid time value")
    year = int(match.group(1)) + years
    month = int(match.group(2))
    day = int(match.group(3))
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    if month == 2 and day == 29 and not leap:
        day = 28
    return "%04d-%02d-%02d" % (year, month, day)


def due_for_destruction(retention_until, held, today):
    """retention_until has passed and no hold is active (dates as YYYY-MM-DD)."""
    return not held and retention_until is not None and retention_until <= today


def clean_hold_reason(reason):
    """A hold is placed or released with a reason, or not at all."""
    text = js_trim(reason)
    if not text:
        raise RetentionError("reason-required")
    return text


def assert_can_place_hold(already_held):
    if already_held:
        raise RetentionError("already-held")
