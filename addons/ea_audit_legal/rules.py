"""The refusals of the legal register, under the platform's codes."""
from odoo.tools.translate import LazyTranslate

from odoo.addons.ea_audit_core.services.errors import AuditRuleError
from odoo.addons.ea_audit_reports.rules import rule_error as reports_rule_error

_lt = LazyTranslate("ea_audit_legal")

MESSAGES = {
    "invalid-capacity": _lt("Choose the capacity of the interested person from those offered."),
    "alerte-open": _lt("An alert procedure is already open on this file."),
    "alerte-discontinued": _lt("This alert procedure is discontinued: resume it first."),
    "invalid-transition": _lt("The procedure cannot move to that stage from where it stands."),
    "not-discontinued": _lt("This alert procedure is not discontinued."),
    "resume-expired": _lt("The six months for resuming this alert procedure have passed."),
    "invalid-event-date": _lt("Enter a valid date, not in the future."),
    "event-date-before-previous": _lt("This step cannot be dated before the step it follows."),
    "titres-inspection-date-required": _lt("Enter the date the register was inspected."),
    "titres-count-required": _lt("Enter the number of securities the register shows."),
    "titres-intermediary-required": _lt("Name the financial intermediary holding the accounts."),
    "titres-task-missing": _lt("The C5.7 task is not on this file."),
    "titres-work-incomplete": _lt("Complete C5.7 first: the attestation needs the conclusions that the register is kept and agrees."),
    "invalid-amount": _lt("Enter an amount above zero."),
    "invalid-key": _lt("That section of the joint auditor file does not exist."),
    "art525-task-missing": _lt("The C5.10 task is not on this file."),
    "art525-work-incomplete": _lt("Complete C5.10 first: the certification needs the number of persons and the total amount."),
}


def rule_error(env, code, **params):
    source = MESSAGES.get(code)
    if source is None:
        return reports_rule_error(env, code, **params)
    text = env._(source)
    if params:
        text = text % params
    return AuditRuleError(code, "%s [%s]" % (text, code))
