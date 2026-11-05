"""The firm's weekly deadline. Pure: weeks run Monday to Sunday; a week's hours may be
entered until the end of Tuesday of the following week, Africa/Douala (UTC+1, no DST).
Instants are naive UTC, as Odoo stores them."""
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

DOUALA = ZoneInfo("Africa/Douala")

OPEN = "open"
SUBMITTED = "submitted"
REOPENED = "reopened"
LOCKED = "locked"
LOCKED_SUBMITTED = "locked_submitted"
FUTURE = "future"

_DAYS = ("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")


def week_start(day):
    return day - timedelta(days=day.weekday())


def local_now(now):
    return now.replace(tzinfo=timezone.utc).astimezone(DOUALA)


def local_today(now):
    return local_now(now).date()


def deadline(monday):
    """The first instant after the deadline: Wednesday 00:00 in Douala, as naive UTC."""
    end = datetime.combine(monday + timedelta(days=9), time.min, tzinfo=DOUALA)
    return end.astimezone(timezone.utc).replace(tzinfo=None)


def week_status(monday, now, submitted=False, reopened_until=None):
    if monday > local_today(now):
        return FUTURE
    if reopened_until and now < reopened_until:
        return REOPENED
    if now >= deadline(monday):
        return LOCKED_SUBMITTED if submitted else LOCKED
    return SUBMITTED if submitted else OPEN


def editable(status):
    return status in (OPEN, REOPENED)


def date_label(day):
    return day.strftime("%d/%m/%Y")


def day_label(day):
    return "%s %s" % (_DAYS[day.weekday()], date_label(day))


def week_label(monday):
    return "Semaine du %s au %s" % (date_label(monday), date_label(monday + timedelta(days=6)))


def deadline_label(monday):
    return "mardi %s à 23:59" % date_label(monday + timedelta(days=8))


def instant_label(now):
    return local_now(now).strftime("%d/%m/%Y à %H:%M")
