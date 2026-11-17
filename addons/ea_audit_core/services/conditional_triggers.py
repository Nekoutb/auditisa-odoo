"""What brings each conditional task onto the file, stated exactly (F031)."""
import re

from odoo.tools.translate import LazyTranslate

from .file_scope import CONTROLS_CODES, SCOPE_LEGACY, retired_codes

_lt = LazyTranslate("ea_audit_core")

# The S6.1 question that brings each planning task onto the file.
S61_TRIGGERS = {
    "assess_control_env": "P4.2",
    "assess_it_env": "P4.3",
    "uses_expert": "S5.1",
    "uses_service_org": "S5.2",
    "has_internal_audit": "S5.3",
}

_TEXT = {
    "P1.2": _lt("P1.1: new engagement or change of auditor = Yes"),
    "P4.2": _lt("S6.1: detailed control-environment assessment = Yes"),
    "P4.3": _lt("S6.1: IT environment assessment = Yes"),
    "S5.1": _lt("S6.1: expert used = Yes"),
    "S5.2": _lt("S6.1: service organisation used = Yes"),
    "S5.3": _lt("S6.1: internal audit function = Yes"),
    # the facts of the scope of 2026-11-17 (file_scope.FACT_CODES)
    "P2.3": _lt("Profile question 4: a parent that consolidates, or whose components other auditors audit"),
    "C1.3": _lt("Was a consultation needed? = Yes"),
    "C4.2": _lt("P1.5: the firm decided to appoint an engagement quality reviewer"),
    "C5.5": _lt("Facts that may threaten continuity (S4.2, E6.3 or C2.2), or an alert procedure started"),
    "C5.6": _lt("Non-compliance found (E6.1), or criminal facts recorded in the legal file"),
    "C5.9": _lt("Are there joint auditors? = Yes"),
}
_CONTROLS_TEXT = _lt("The strategy relies on controls (a class of transactions tested through its controls, a combined risk assessment cell set to rely, or an IT application whose controls are relied on)")
_RETIRED_P_AND_L = re.compile(r"^E5\.[1-5]$")
_RETIRED_TEXT = _lt("Income statement accounts are covered by the E4 indexes")
# Merged into another paper (owner's decision of 2026-11-16, file_scope.RETIRED_CODES).
_MERGED_TEXT = {
    "P7.1": _lt("Now recorded in P1.4, Part D (planning communication with those charged with governance)"),
    "S6.2": _lt("Now recorded in S6.1, Part E (direction, supervision and review by the partner)"),
    "C5.2": _lt("No longer a paper of the file (owner's decision of 2026-11-16)"),
    # owner's decision of 2026-11-17
    "P4.2": _lt("Merged into P4.1 (internal control at the entity level, the control environment included)"),
    "C5.8": _lt("Merged into E6.3 (the check of equity against half of the share capital)"),
    "C4.3": _lt("Merged into C4.1 (the open points are cleared there before the report date)"),
}


def merged_text(code, lang):
    """Where the work of a retired task is now done, in ``lang``; False for a task still in use."""
    label = _MERGED_TEXT.get(code)
    return label._translate(lang or "en_US") if label else False


def trigger_text(code, lang, scope=SCOPE_LEGACY):
    """The reason a conditional task is not on the file, in ``lang``; False when none is known.
    On a file of the current scope a merged task says where its work is now done."""
    if code in retired_codes(scope):
        return merged_text(code, lang)
    label = (
        _TEXT.get(code) or (_CONTROLS_TEXT if code in CONTROLS_CODES else None) or _MERGED_TEXT.get(code)
        or (_RETIRED_TEXT if _RETIRED_P_AND_L.match(code or "") else None)
    )
    return label._translate(lang or "en_US") if label else False
