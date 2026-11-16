"""Port of the scoping of lib/file-index.ts and lib/legal-forms.ts (F052, F075)."""
import re

LEGAL_FORMS = ("SA", "SA_AG", "SARL", "SAS", "GIE", "OTHER")

FORM_EXCLUDED = {"C5.7": ("SARL", "GIE")}

STATUTORY_ONLY = re.compile(r"^C5\.(?:[2-9]|10)$")

# Natures with their own file: the list IS the file, whatever the complexity.
NATURE_FILE_INDEX = {
    "limited_review": frozenset({
        "P1.1", "P1.2", "P1.3", "P1.4", "P2.1", "P2.2",
        "P3.1", "P3.2", "P6.1", "S4.2",
        "E6.3", "E6.4", "E6.5", "E6.6", "E6.10",
        "C1.1", "C1.2", "C2.1", "C2.2", "C3.1", "C4.1", "C4.3", "C5.1", "C5.11", "C6.1", "C6.2",
    }),
    "commissariat_apports": frozenset({
        "P1.1", "P1.3", "P1.4", "P2.1", "P2.2",
        "P3.1", "S5.1",
        "E6.4", "E6.7",
        "C1.2", "C3.1", "C4.1", "C4.3", "C5.1", "C6.1", "C6.2",
    }),
}


# Tasks taken off the file (owner's decisions of 2026-11-16): the planning communication to those
# charged with governance is a block of P1.4, the partner's direction a block of S6.1, and C5.2 (the
# OHADA statutory deadlines and whether each was met) is no longer a paper of the file. A new file
# never gets them; an existing file keeps the ones that already hold work.
RETIRED_CODES = frozenset({"P7.1", "S6.2", "C5.2"})


def is_societe_anonyme(form):
    return form in ("SA", "SA_AG")


def task_applies_to_form(code, form):
    excluded = FORM_EXCLUDED.get(code)
    if not excluded or form not in LEGAL_FORMS:
        return True
    return form not in excluded


def nature_has_audit_programme(nature):
    return not nature or nature not in NATURE_FILE_INDEX


def code_in_scope(code, tier, conditional, complexity, legal_form=None, nature=None):
    """One row of itemsForComplexity."""
    if code in RETIRED_CODES:
        return False
    own_scope = NATURE_FILE_INDEX.get(nature) if nature else None
    if own_scope is not None:
        return code in own_scope
    if not task_applies_to_form(code, legal_form):
        return False
    if nature == "contractual_audit" and STATUTORY_ONLY.match(code):
        return False
    if complexity == "very_simple":
        return tier == "core" and not conditional
    if complexity == "non_complex":
        return tier != "extended"
    return True
