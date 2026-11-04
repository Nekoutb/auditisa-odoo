"""Port of the period arithmetic of lib/standards-edition.ts (F045)."""
import calendar
from datetime import date, timedelta

STANDARDS_EDITIONS = ("current", "revised_2026")
REVISED_2026_FROM = date(2026, 12, 15)


def period_start_of(period_end, duration_months=None):
    """The day after the period end less the duration (twelve months when
    unknown), clamped to the end of the target month like Postgres intervals."""
    months = int(duration_months) if duration_months and duration_months > 0 else 12
    start = period_end + timedelta(days=1)
    index = start.year * 12 + (start.month - 1) - months
    year, month0 = divmod(index, 12)
    month = month0 + 1
    return date(year, month, min(start.day, calendar.monthrange(year, month)[1]))


def default_standards_edition(period_start):
    if not period_start:
        return "current"
    return "revised_2026" if period_start >= REVISED_2026_FROM else "current"


def edition_for_period(period_end, duration_months=None):
    return default_standards_edition(period_start_of(period_end, duration_months))
