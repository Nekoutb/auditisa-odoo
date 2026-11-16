"""What brings each conditional task onto the file, stated exactly (F031)."""
import re

from odoo.tools.translate import LazyTranslate

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
}
_RETIRED_P_AND_L = re.compile(r"^E5\.[1-5]$")
_RETIRED_TEXT = _lt("Income statement accounts are covered by the E4 indexes")
# Merged into another paper (owner's decision of 2026-11-16, file_scope.RETIRED_CODES).
_MERGED_TEXT = {
    "P7.1": _lt("Now recorded in P1.4, Part D (planning communication with those charged with governance)"),
    "S6.2": _lt("Now recorded in S6.1, Part E (direction, supervision and review by the partner)"),
    "C5.2": _lt("No longer a paper of the file (owner's decision of 2026-11-16)"),
}


def trigger_text(code, lang):
    """The reason a conditional task is not on the file, in ``lang``; False when none is known."""
    label = _TEXT.get(code) or _MERGED_TEXT.get(code) or (_RETIRED_TEXT if _RETIRED_P_AND_L.match(code or "") else None)
    return label._translate(lang or "en_US") if label else False
