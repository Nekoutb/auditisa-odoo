from datetime import date, datetime

from ..deadlines import (
    FUTURE,
    LOCKED,
    LOCKED_SUBMITTED,
    OPEN,
    REOPENED,
    SUBMITTED,
    date_label,
    deadline,
    instant_label,
    local_today,
    week_start,
    week_status,
)

MONDAY = date(2026, 11, 2)


def test_weeks_run_monday_to_sunday():
    assert week_start(date(2026, 11, 2)) == MONDAY
    assert week_start(date(2026, 11, 8)) == MONDAY
    assert week_start(date(2026, 11, 9)) == date(2026, 11, 9)


def test_deadline_is_wednesday_midnight_in_douala():
    assert deadline(MONDAY) == datetime(2026, 11, 10, 23, 0)


def test_no_daylight_saving_in_douala():
    assert deadline(date(2026, 6, 1)) == datetime(2026, 6, 9, 23, 0)
    assert deadline(date(2026, 1, 5)) == datetime(2026, 1, 13, 23, 0)


def test_status_at_the_boundaries():
    assert week_status(MONDAY, datetime(2026, 11, 9, 8, 0)) == OPEN
    assert week_status(MONDAY, datetime(2026, 11, 10, 22, 59, 59)) == OPEN
    assert week_status(MONDAY, datetime(2026, 11, 10, 23, 0)) == LOCKED
    assert week_status(MONDAY, datetime(2026, 11, 10, 23, 0), submitted=True) == LOCKED_SUBMITTED
    assert week_status(MONDAY, datetime(2026, 11, 3, 8, 0), submitted=True) == SUBMITTED


def test_a_reopening_holds_until_it_expires():
    until = datetime(2026, 11, 20, 8, 0)
    assert week_status(MONDAY, datetime(2026, 11, 20, 7, 59), reopened_until=until) == REOPENED
    assert week_status(MONDAY, datetime(2026, 11, 20, 8, 0), reopened_until=until) == LOCKED


def test_the_future_is_read_in_douala():
    # Sunday 23:30 UTC is already Monday 00:30 in Douala
    assert local_today(datetime(2026, 11, 1, 23, 30)) == MONDAY
    assert week_status(MONDAY, datetime(2026, 11, 1, 22, 59)) == FUTURE
    assert week_status(MONDAY, datetime(2026, 11, 1, 23, 0)) == OPEN


def test_labels_read_dd_mm_yyyy():
    assert date_label(MONDAY) == "02/11/2026"
    assert instant_label(datetime(2026, 11, 10, 22, 59)) == "10/11/2026 23:59"
