"""What the screens say about dates, deadlines and people: no Odoo import."""
from datetime import timedelta

from dateutil.relativedelta import relativedelta

# phaseDeadline of lib/engagement-dashboard.ts, in days from the period end.
_PHASE_OFFSET_DAYS = {"acceptance": -90, "planning": -45, "execution": 90, "conclusion": 150}

NATURE_LABELS = {
    "statutory_audit": "commissariat aux comptes",
    "contractual_audit": "audit contractuel",
    "limited_review": "examen limité",
    "commissariat_apports": "commissariat aux apports",
    "agreed_procedures": "procédures convenues",
    "other": "autre mission",
}

FIRM_ROLE_LABELS = {
    "firm_admin": "Administrateur",
    "partner": "Associé",
    "manager": "Manager",
    "senior": "Senior",
    "staff": "Collaborateur",
    "eqr_reviewer": "Réviseur qualité",
    "read_only": "Lecture seule",
}

TEAM_ROLE_LABELS = {
    "staff": "collaborateur",
    "senior": "senior",
    "manager": "manager",
    "senior_manager": "senior manager",
    "director": "directeur",
    "partner": "associé",
    "eqr_reviewer": "réviseur qualité",
}

STATUS_PILLS = {
    "signed": ("TERMINÉE", "g"),
    "reviewed": ("À SIGNER", "y"),
    "prepared": ("EN RÉVISION", "y"),
    "in_progress": ("EN COURS", "bl"),
    "not_started": ("NON COMMENCÉE", "n"),
    "not_applicable": ("SANS OBJET", "n"),
}

STATUS_WORDS = {
    "signed": "Signée",
    "reviewed": "À signer",
    "prepared": "En revue",
    "in_progress": "En cours",
    "not_started": "Non commencée",
    "not_applicable": "Sans objet",
}


def fmt_date(value):
    """DD/MM/YYYY whatever the user's language."""
    return value.strftime("%d/%m/%Y") if value else ""


def report_due(period_end):
    """"Rapport attendu avant le": the period end plus six months."""
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
