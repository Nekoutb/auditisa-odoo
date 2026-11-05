from odoo.addons.ea_audit_core.services.errors import AuditRuleError

from ..services.codes import MESSAGES


def refuse(code):
    """The same refusal class as the rules engine, so that screens and tests read ``code``."""
    return AuditRuleError(code, MESSAGES.get(code, code))
