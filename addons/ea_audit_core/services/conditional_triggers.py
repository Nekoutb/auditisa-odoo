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


def trigger_text(code, lang):
    """The reason a conditional task is not on the file, in ``lang``; False when none is known."""
    label = _TEXT.get(code) or (_RETIRED_TEXT if _RETIRED_P_AND_L.match(code or "") else None)
    return label._translate(lang or "en_US") if label else False
