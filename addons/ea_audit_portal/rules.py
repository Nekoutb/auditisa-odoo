"""The refusals of the client portal, under the platform's codes. A file refused by the upload
check carries the code and the message of ea_audit_papers."""
from odoo.tools.translate import LazyTranslate

from odoo.addons.ea_audit_core.services.errors import AuditRuleError
from odoo.addons.ea_audit_papers.models.errors import MESSAGES as PAPER_MESSAGES
from odoo.addons.ea_audit_papers.models.errors import paper_error
from odoo.addons.ea_audit_reports.rules import rule_error as reports_rule_error

_lt = LazyTranslate("ea_audit_portal")

MESSAGES = {
    "portal-only": _lt("This page is for the client's portal contacts."),
    "not-your-client": _lt("This request belongs to another client."),
    "no-portal-contact": _lt("This client has no portal contact: a reminder would reach nobody. Add a contact first."),
    "wrong-status": _lt("This request is not in the right state for that."),
    "attach-required": _lt("Choose the task this upload is filed under."),
    "already-active": _lt("This contact has already chosen a password."),
    "invalid-or-expired": _lt("This invitation has expired or has already been used. Ask your auditor for a new one."),
    "mismatch": _lt("The two passwords differ."),
    "too-short": _lt("Use at least 12 characters."),
    "needs-mixed-case": _lt("Use upper and lower case letters."),
    "needs-digit": _lt("Use at least one digit."),
    "contains-email": _lt("The password must not contain your email address."),
}


def rule_error(env, code, **params):
    source = MESSAGES.get(code)
    if source is not None:
        return AuditRuleError(code, "%s [%s]" % (env._(source) % params if params else env._(source), code))
    if code in PAPER_MESSAGES:
        return paper_error(env, code)
    return reports_rule_error(env, code, **params)
