"""lib/legal.ts: the two date helpers the statutory clocks run on. The rest of that
file is the statutory-deadline models and documents, which are not pure."""
from ._js import add_utc, date_parts, date_utc, js_date_parse, to_iso_date
from .errors import JsRangeError


def add_months_clamped(iso, months):
    """Calendar months, clamped to the target month's last day."""
    year, month, day = (int(p) for p in iso.split("-"))
    target = month - 1 + months
    last_day = date_parts(date_utc(year, target + 1, 0))[2]
    return to_iso_date(date_utc(year, target, min(day, last_day)))


def add_days_iso(iso, days):
    """``days`` later. 30 February parses and rolls over before the days are added."""
    start = js_date_parse("%sT00:00:00Z" % iso)
    if start is None:
        raise JsRangeError("Invalid time value")
    return to_iso_date(add_utc(start, days=days))
