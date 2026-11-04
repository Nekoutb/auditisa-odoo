"""lib/control-labels.ts: display labels for control and SCOT attributes."""

CONTROL_FREQUENCIES = [
    {"value": "daily", "en": "Daily", "fr": "Quotidien"},
    {"value": "weekly", "en": "Weekly", "fr": "Hebdomadaire"},
    {"value": "monthly", "en": "Monthly", "fr": "Mensuel"},
    {"value": "quarterly", "en": "Quarterly", "fr": "Trimestriel"},
    {"value": "semi_annually", "en": "Semi-annually", "fr": "Semestriel"},
    {"value": "annually", "en": "Annually", "fr": "Annuel"},
]


def freq_label(value, fr):
    for entry in CONTROL_FREQUENCIES:
        if entry["value"] == value:
            return entry["fr"] if fr else entry["en"]
    return "—" if value is None else value


def type_short(value, fr):
    if value == "manual":
        return "Manuel" if fr else "Manual"
    if value == "it_dependent":
        return "Dépendant IT" if fr else "IT-dependent"
    return "Automatisé" if fr else "Automated"


def objective_label(value, fr):
    if value == "prevent":
        return "Prévention" if fr else "Prevent"
    if value == "detect":
        return "Détection" if fr else "Detect"
    return "—" if value is None else value


def transaction_type_label(value, fr):
    if value == "routine":
        return "Routinier" if fr else "Routine"
    if value == "non_routine":
        return "Non routinier" if fr else "Non-routine"
    if value == "estimation":
        return "Estimation"
    return "—" if value is None else value
