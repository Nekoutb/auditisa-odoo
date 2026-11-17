"""lib/alerte.ts: the procédure d'alerte state machine and its deadlines (arts. 150-156).

The letters and the storage stay in the Odoo model; this is the part that decides
which transition is allowed and which deadline it sets.

F051: FIRST_REPLY_DAYS is the 2014 reading of arts. 150 / 153, "dans le mois", which
the source applies as 30 days and marks "à valider" (the 1997 text read 15 days).
"""
import re

from ._js import js_date_parse, js_trim
from .errors import LegalError
from .legal import add_days_iso, add_months_clamped

FIRST_REPLY_DAYS = 30

_FR_TO_EN = {
    "Art. 150 — réponse du gérant dans le mois (à valider ; lecture 1997 : 15 jours)": "Art. 150 — manager's reply within one month (to validate; 1997 reading: 15 days)",
    "Art. 151 — le CAC informe la juridiction compétente": "Art. 151 — the statutory auditor informs the competent court",
    "Art. 152 — communication aux associés sous 8 jours (ou à la prochaine AG)": "Art. 152 — communication to the members within 8 days (or at the next general meeting)",
    "Résultats communiqués à la juridiction si mesures insuffisantes": "Results communicated to the court if the measures are insufficient",
    "Art. 153 — réponse du PCA/PDG ou de l'administrateur général dans le mois (à valider ; lecture 1997 : 15 jours)": "Art. 153 — reply of the chairman, the chairman and managing director or the general administrator within one month (to validate; 1997 reading: 15 days)",
    "Art. 154 — invitation du président à faire délibérer le conseil sous 15 jours de la réponse": "Art. 154 — chairman invited to have the board deliberate within 15 days of the reply",
    "Art. 154 — le président convoque le conseil sous 15 jours": "Art. 154 — the chairman convenes the board within 15 days",
    "Art. 154 — extrait du PV au CAC et à la juridiction sous 1 mois": "Art. 154 — extract of the minutes to the statutory auditor and the court within 1 month",
    "Art. 155 — rapport spécial à la prochaine AG (le CAC peut convoquer l'AG)": "Art. 155 — special report to the next general meeting (the statutory auditor may convene it)",
    "Art. 156 — juridiction informée des résultats": "Art. 156 — court informed of the results",
}


def basis_text(entry, fr):
    """The legal basis of a stage: the source's French, or its English."""
    return entry["basis"] if fr else _FR_TO_EN.get(entry["basis"], entry["basis"])


#: Ordered stages per variant; each entry: next-deadline days from the transition.
FLOWS_FR = {
    "non_sa": [
        {
            "stage": "request_sent",
            "deadlineDays": 30,
            "basis": "Art. 150 — réponse du gérant dans le mois (à valider ; lecture 1997 : 15 jours)",
        },
        {
            "stage": "reply_recorded",
            "deadlineDays": None,
            "basis": "Art. 151 — le CAC informe la juridiction compétente",
        },
        {"stage": "court_informed", "deadlineDays": None, "basis": "Art. 151"},
        {
            "stage": "rapport_special",
            "deadlineDays": 8,
            "basis": "Art. 152 — communication aux associés sous 8 jours (ou à la prochaine AG)",
        },
        {"stage": "ag_communicated", "deadlineDays": None, "basis": "Art. 152"},
        {
            "stage": "closed",
            "deadlineDays": None,
            "basis": "Résultats communiqués à la juridiction si mesures insuffisantes",
        },
    ],
    "sa": [
        {
            "stage": "request_sent",
            "deadlineDays": 30,
            "basis": "Art. 153 — réponse du PCA/PDG ou de l'administrateur général dans le mois (à valider ; lecture 1997 : 15 jours)",
        },
        {
            "stage": "reply_recorded",
            "deadlineDays": 15,
            "basis": "Art. 154 — invitation du président à faire délibérer le conseil sous 15 jours de la réponse",
        },
        {
            "stage": "board_invited",
            "deadlineDays": 15,
            "basis": "Art. 154 — le président convoque le conseil sous 15 jours",
        },
        {
            "stage": "board_deliberated",
            "deadlineDays": 30,
            "basis": "Art. 154 — extrait du PV au CAC et à la juridiction sous 1 mois",
        },
        {
            "stage": "rapport_special",
            "deadlineDays": None,
            "basis": "Art. 155 — rapport spécial à la prochaine AG (le CAC peut convoquer l'AG)",
        },
        {"stage": "ag_communicated", "deadlineDays": None, "basis": "Art. 156"},
        {"stage": "closed", "deadlineDays": None, "basis": "Art. 156 — juridiction informée des résultats"},
    ],
}
FLOWS = FLOWS_FR

_ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def variant_of(legal_form):
    """The variant derives from the client's legal form."""
    return "sa" if legal_form in ("SA", "SA_AG", "SAS") else "non_sa"


def flow_of(variant):
    return FLOWS[variant]


def next_stages_of(variant, stage, discontinued):
    if discontinued:
        return ["resumed"]
    flow = flow_of(variant)
    for index, entry in enumerate(flow):
        if entry["stage"] == stage:
            return [] if index == len(flow) - 1 else [flow[index + 1]["stage"]]
    return []


def event_date_or_today(raw, today):
    """The date the statutory clock runs from: the day the letter went out or the reply
    came in. Defaults to ``today``; a future or malformed date is refused. Only the
    shape and Date.parse are checked, so 2025-02-30 passes and later rolls to 2 March."""
    if raw is None or js_trim(raw) == "":
        return today
    value = js_trim(raw)
    if not _ISO_DATE.fullmatch(value) or js_date_parse(value + "T00:00:00Z") is None or value > today:
        raise LegalError("invalid-event-date")
    return value


def _deadline(entry, event_date):
    days = entry.get("deadlineDays") if entry else None
    return None if days is None else add_days_iso(event_date, days)


def start_alerte(legal_form, has_open_alerte, event_date, today):
    """{variant, stage, stageDeadline, eventDate} of a new procedure."""
    date = event_date_or_today(event_date, today)
    if has_open_alerte:
        raise LegalError("alerte-open")
    variant = variant_of(legal_form)
    first = flow_of(variant)[0]
    return {"variant": variant, "stage": first["stage"], "stageDeadline": _deadline(first, date), "eventDate": date}


def advance_alerte(variant, stage, discontinued_at, to_stage, last_event_date, today, satisfactory=False, event_date=None):
    """{stage, stageDeadline, discontinued, eventDate} after a transition. A satisfactory
    reply discontinues the procedure (resumable for six months)."""
    date = event_date_or_today(event_date, today)
    if discontinued_at:
        raise LegalError("alerte-discontinued")
    if to_stage not in next_stages_of(variant, stage, False):
        raise LegalError("invalid-transition")
    # The chronology holds: a step cannot be dated before the one it follows (UAT run 2 B95).
    if last_event_date and date < last_event_date:
        raise LegalError("event-date-before-previous")
    if to_stage == "reply_recorded" and satisfactory:
        return {"stage": "reply_recorded", "stageDeadline": None, "discontinued": True, "eventDate": date}
    entry = next((e for e in flow_of(variant) if e["stage"] == to_stage), None)
    return {"stage": to_stage, "stageDeadline": _deadline(entry, date), "discontinued": False, "eventDate": date}


def resume_alerte(discontinued_at, today):
    """Back to request_sent with a fresh first-reply deadline; up to six months after
    the discontinuation, the bound clamped to the month's last day."""
    if not discontinued_at:
        raise LegalError("not-discontinued")
    if today > add_months_clamped(discontinued_at, 6):
        raise LegalError("resume-expired")
    return {"stage": "request_sent", "stageDeadline": add_days_iso(today, FIRST_REPLY_DAYS), "discontinued": False}


def last_event_date(event_dates):
    """The latest recorded event date: the next step cannot be dated earlier."""
    latest = None
    for date in event_dates:
        if latest is None or date > latest:
            latest = date
    return latest
