"""Port of the scoping of lib/file-index.ts and lib/legal-forms.ts (F052, F075), and the scope the
owner approved on 2026-11-17 ("tasks by engagement profile": facts decide whether a task applies,
complexity decides how deep it is documented).

Two scopes live side by side. A file opened before 2026-11-17 keeps the scope it was opened with
(SCOPE_LEGACY) until its partner applies the current one (engagement.action_rescope): no task comes
or goes on a live file by itself. Every new file gets SCOPE_CURRENT.
"""
import re

LEGAL_FORMS = ("SA", "SA_AG", "SARL", "SAS", "GIE", "OTHER")

FORM_EXCLUDED = {"C5.7": ("SARL", "GIE")}

STATUTORY_ONLY = re.compile(r"^C5\.(?:[2-9]|10)$")

# The substantive account tasks (E4, E5): handled by the Substantive procedures tool, their scope
# does not change with the 2026-11-17 table.
SUBSTANTIVE = re.compile(r"^E[45]\.\d+$")

SCOPE_LEGACY = 1
SCOPE_CURRENT = 2

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
RETIRED_2026_11_16 = frozenset({"P7.1", "S6.2", "C5.2"})

# Merged on 2026-11-17: the control environment is assessed in P4.1, the check of equity against
# half of the share capital is made in E6.3, and the open points are cleared in C4.1. Same rule.
MERGED_2026_11_17 = frozenset({"P4.2", "C5.8", "C4.3"})

RETIRED_CODES = RETIRED_2026_11_16 | MERGED_2026_11_17

# Where the work of a retired task is now done.
MERGED_INTO = {
    "P7.1": "P1.4", "S6.2": "S6.1", "P4.2": "P4.1", "C5.8": "E6.3", "C4.3": "C4.1",
}

# The tasks that rely on controls: on the file only when the strategy relies on them.
CONTROLS_CODES = ("S2.1", "S2.2", "S2.3", "S2.4", "S2.5", "E1.1", "E1.2", "E2.1")

# "If applicable" at every complexity: on the file but not active until the fact exists
# (new engagement, group, expert, service organisation, internal audit, reliance on controls,
# consultation, quality review decided on P1.5, alert facts, offences, joint auditors).
FACT_CODES = frozenset({
    "P1.2", "P2.3", "S5.1", "S5.2", "S5.3", "C1.3", "C4.2", "C5.5", "C5.6", "C5.9",
}) | frozenset(CONTROLS_CODES)

# Statutory papers a société anonyme owes, whatever its complexity (art. 715, registered
# securities, art. 525).
SA_ONLY = frozenset({"C5.4", "C5.7", "C5.10"})

# Required for every audit, a Very simple one included (shorter there, never absent). P4.3 is no
# longer conditional: the IT environment is understood on every file.
ALL_SIZES = frozenset({"P2.2", "P4.1", "P4.3", "S1.1", "S1.2", "S1.4", "S4.1", "S5.4", "S5.5", "C5.3"})


def is_societe_anonyme(form):
    return form in ("SA", "SA_AG")


def retired_codes(scope=SCOPE_CURRENT):
    """The codes no file of this scope gets (nor gets back through a trigger)."""
    return RETIRED_CODES if (scope or SCOPE_LEGACY) >= SCOPE_CURRENT else RETIRED_2026_11_16


def trigger_target(code, scope=SCOPE_CURRENT):
    """The task a trigger brings onto a file of ``scope``. A task merged into another paper brings
    that paper on the current scope (S6.1's detailed control-environment assessment: P4.1, where
    the control environment is now assessed); an older file still gets the task itself."""
    if code in retired_codes(scope):
        return MERGED_INTO.get(code, code)
    return code


def task_applies_to_form(code, form, scope=SCOPE_LEGACY):
    if (scope or SCOPE_LEGACY) >= SCOPE_CURRENT and code in SA_ONLY:
        # an unknown form keeps the task: the partner marks it not applicable with a reason
        return form not in LEGAL_FORMS or is_societe_anonyme(form)
    excluded = FORM_EXCLUDED.get(code)
    if not excluded or form not in LEGAL_FORMS:
        return True
    return form not in excluded


def nature_has_audit_programme(nature):
    return not nature or nature not in NATURE_FILE_INDEX


def _complexity_rule(tier, conditional, complexity):
    """itemsForComplexity: the rule of the scope before 2026-11-17."""
    if complexity == "very_simple":
        return tier == "core" and not conditional
    if complexity == "non_complex":
        return tier != "extended"
    return True


def code_in_scope(code, tier, conditional, complexity, legal_form=None, nature=None, scope=SCOPE_CURRENT):
    """Whether a new file of this scope gets the task (active or waiting for its fact)."""
    current = (scope or SCOPE_LEGACY) >= SCOPE_CURRENT
    if code in retired_codes(scope):
        return False
    own_scope = NATURE_FILE_INDEX.get(nature) if nature else None
    if own_scope is not None:
        return code in own_scope
    if not task_applies_to_form(code, legal_form, scope):
        return False
    if nature == "contractual_audit" and STATUTORY_ONLY.match(code):
        return False
    if not current or SUBSTANTIVE.match(code):
        return _complexity_rule(tier, conditional, complexity)
    if code in FACT_CODES or code in SA_ONLY:
        return True
    if complexity == "very_simple":
        return tier == "core" or code in ALL_SIZES
    if complexity == "non_complex":
        return tier != "extended"
    return True


def starts_dormant(code, conditional, scope=SCOPE_CURRENT):
    """True when the task waits for its fact: on the file, not active (file_item.conditional)."""
    if (scope or SCOPE_LEGACY) < SCOPE_CURRENT or SUBSTANTIVE.match(code):
        return bool(conditional)
    return code in FACT_CODES or (bool(conditional) and code not in ALL_SIZES)


def scope_codes(templates, complexity, legal_form=None, nature=None, scope=SCOPE_CURRENT):
    """{code: dormant} of a file. ``templates`` are (code, tier, conditional) rows."""
    return {
        code: starts_dormant(code, conditional, scope)
        for code, tier, conditional in templates
        if code_in_scope(code, tier, conditional, complexity, legal_form, nature, scope)
    }
