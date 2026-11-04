"""lib/assertions.ts: the platform's six assertion codes and their labels."""

ASSERTIONS = ["C", "E", "A", "V", "P", "RO"]

ASSERTION_LABELS = {
    "C": {"en": "Completeness", "fr": "Exhaustivité"},
    "E": {"en": "Existence / occurrence", "fr": "Existence / réalité"},
    "A": {"en": "Accuracy / cut-off", "fr": "Exactitude / séparation"},
    "V": {"en": "Valuation", "fr": "Évaluation"},
    "P": {"en": "Presentation / disclosure", "fr": "Présentation / information"},
    "RO": {"en": "Rights and obligations", "fr": "Droits et obligations"},
}


def is_assertion(value):
    return isinstance(value, str) and value in ASSERTIONS


def clean_assertions(values):
    """Keep only the platform codes, in the order given, without duplicates."""
    if not isinstance(values, (list, tuple)):
        return []
    return list(dict.fromkeys(v for v in values if is_assertion(v)))


def assertion_name(code, locale):
    """The long name alone; an unknown code comes back as typed."""
    return ASSERTION_LABELS[code][locale] if is_assertion(code) else code


def assertion_label(code, locale):
    """The full label every select, option and chip shows: "C — Completeness"."""
    return "%s — %s" % (code, ASSERTION_LABELS[code][locale]) if is_assertion(code) else code


def assertion_labels(codes, locale):
    return " · ".join(assertion_label(c, locale) for c in codes)
