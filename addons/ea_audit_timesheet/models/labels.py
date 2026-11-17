"""The words around a date. The dates themselves read DD/MM/YYYY in every language."""
from datetime import timedelta

from ..services import deadlines
from ..services.phases import BUDGET_PHASES


def day_label(env, day):
    names = (
        env._("Mon"), env._("Tue"), env._("Wed"), env._("Thu"), env._("Fri"), env._("Sat"), env._("Sun"),
    )
    return "%s %s" % (names[day.weekday()], deadlines.date_label(day))


def week_label(env, monday):
    return env._(
        "Week of %(start)s to %(end)s",
        start=deadlines.date_label(monday),
        end=deadlines.date_label(monday + timedelta(days=6)),
    )


def deadline_label(env, monday):
    return env._("Tuesday %(day)s, 23:59", day=deadlines.date_label(monday + timedelta(days=8)))


def status_label(env, status):
    return {
        deadlines.OPEN: env._("Open"),
        deadlines.SUBMITTED: env._("Submitted"),
        deadlines.REOPENED: env._("Reopened"),
        deadlines.LOCKED: env._("Locked, not submitted"),
        deadlines.LOCKED_SUBMITTED: env._("Locked, submitted"),
        deadlines.FUTURE: env._("Not started"),
    }[status]


def phase_labels(env):
    labels = {
        "acceptance": env._("Planning"),
        "strategy": env._("Strategy and risks"),
        "execution": env._("Execution"),
        "conclusion": env._("Conclusion"),
    }
    return [(key, labels[key]) for key, _source in BUDGET_PHASES]
