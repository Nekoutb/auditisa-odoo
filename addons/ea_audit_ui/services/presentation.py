"""What the screens say about dates, deadlines and people: no Odoo import."""
from datetime import timedelta

from dateutil.relativedelta import relativedelta

# phaseDeadline of lib/engagement-dashboard.ts, in days from the period end.


def _lt(text):
    """Marks an English source for fr.po; the model layer translates it with env._."""
    return text


_PHASE_OFFSET_DAYS = {"acceptance": -90, "planning": -45, "execution": 90, "conclusion": 150}

NATURE_LABELS = {
    "statutory_audit": _lt("statutory audit"),
    "contractual_audit": _lt("non-statutory audit"),
    "limited_review": _lt("limited review"),
    "commissariat_apports": _lt("contribution audit"),
    "agreed_procedures": _lt("agreed-upon procedures"),
    "other": _lt("other engagement"),
}

FIRM_ROLE_LABELS = {
    "firm_admin": _lt("Administrator"),
    "partner": _lt("Partner"),
    "manager": _lt("Manager"),
    "senior": _lt("Senior"),
    "staff": _lt("Staff"),
    "eqr_reviewer": _lt("Quality reviewer"),
    "read_only": _lt("Read only"),
}

TEAM_ROLE_LABELS = {
    "staff": _lt("staff member"),
    "senior": _lt("senior"),
    "manager": _lt("manager"),
    "senior_manager": _lt("senior manager"),
    "director": _lt("director"),
    "partner": _lt("partner"),
    "eqr_reviewer": _lt("quality reviewer"),
}

STATUS_PILLS = {
    "signed": (_lt("COMPLETE"), "g"),
    "reviewed": (_lt("TO SIGN"), "y"),
    "prepared": (_lt("IN REVIEW"), "y"),
    "in_progress": (_lt("IN PROGRESS"), "bl"),
    "not_started": (_lt("NOT STARTED"), "n"),
    "not_applicable": (_lt("NOT APPLICABLE"), "n"),
}

STATUS_WORDS = {
    "signed": _lt("Signed"),
    "reviewed": _lt("To sign"),
    "prepared": _lt("In review"),
    "in_progress": _lt("In progress"),
    "not_started": _lt("Not started"),
    "not_applicable": _lt("Not applicable"),
}


def fmt_date(value):
    """DD/MM/YYYY whatever the user's language."""
    return value.strftime("%d/%m/%Y") if value else ""


def report_due(period_end):
    """The report's due date: the period end plus six months."""
    return period_end + relativedelta(months=6)


def phase_deadline(period_end, phase):
    """The target date of a phase; an archived file has none."""
    days = _PHASE_OFFSET_DAYS.get(phase)
    return period_end + timedelta(days=days) if days is not None else None


def percent(done, total):
    return round(done * 100 / total) if total else 0


def _words(name):
    return (name or "").split()


def first_name(name):
    words = _words(name)
    return words[0] if words else ""


def _initial(word):
    # Jean-Pierre -> J.-P.
    return "-".join("%s." % part[0].upper() for part in word.split("-") if part)


def short_name(name):
    """Jean-Pierre Mbarga -> J.-P. Mbarga; one word stays as it is."""
    words = _words(name)
    if len(words) < 2:
        return name or ""
    return " ".join([_initial(word) for word in words[:-1]] + [words[-1]])


def initials(name):
    words = _words(name)
    if not words:
        return ""
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[-1][0]).upper()


# What an empty screen says: why it is empty and what to do next.
HOME_EMPTY = _lt("You are in the firm. Your engagements appear here once a manager adds you to a team and you accept.")
HOME_EMPTY_START = _lt("Start with + New engagement.")
TASKS_AWAIT_PROFILE = _lt(
    "No tasks yet: the partner has answered %(n)s of %(total)s questions in the engagement questionnaire."
)
TASKS_NONE_MINE = _lt("Nothing is assigned to you yet. Ask the manager to set you as preparer.")
TASKS_NONE_OPEN = _lt("Nothing open is assigned to you on this file.")

# the firm roles that open engagements themselves
_STARTER_ROLES = ("firm_admin", "partner", "manager")


def home_empty_lines(role, can_write):
    """The lines of the Home page when no engagement is visible, English sources."""
    lines = [HOME_EMPTY]
    if can_write and role in _STARTER_ROLES:
        lines.append(HOME_EMPTY_START)
    return lines


def my_tasks_empty(profile_pending, answered, total, any_mine=False):
    """(English source, parameters) of an empty My tasks: waiting for the questionnaire
    while it is not concluded, waiting for someone to hand a task out while nothing is
    mine, and only then "nothing open"."""
    if profile_pending:
        return TASKS_AWAIT_PROFILE, {"n": answered, "total": total}
    if not any_mine:
        return TASKS_NONE_MINE, {}
    return TASKS_NONE_OPEN, {}
