"""The refusals of the reports, under the exact kebab-case codes of the platform, added to the
ones ea_audit_core and ea_audit_tools already carry."""
from odoo.tools.translate import LazyTranslate

from odoo.addons.ea_audit_core.services.errors import AuditRuleError
from odoo.addons.ea_audit_tools.rules import rule_error as tools_rule_error

_lt = LazyTranslate("ea_audit_reports")

MESSAGES = {
    "system-key": _lt("This completion record is written by the system."),
    "stale-edit": _lt("Someone else saved this record while you were editing it. Reload, merge your text with theirs, and save again: your entry has not been stored."),
    "report-requires-execution": _lt("The report can be issued only once the engagement is in execution or conclusion."),
    "already-issued": _lt("The report has already been issued."),
    "fields-required": _lt("Fill in the required fields."),
    "basis-required": _lt("A modified opinion needs the basis of the modification."),
    "kam-required": _lt("A listed entity needs its key audit matters, or a statement that there are none with the reason."),
    "archive-partner-only": _lt("Only a partner can archive the file."),
    "no-report": _lt("The report must be issued before the file is archived."),
    "already-archived": _lt("This file is already archived."),
    "requires-firm-admin": _lt("Only a firm administrator can change this setting."),
    "requires-manager": _lt("Only a manager or above can do this."),
    "retention-out-of-range": _lt("The retention period must be between 10 and 30 years."),
    "already-held": _lt("This file is already under a legal hold."),
    "no-active-hold": _lt("This file is not under a legal hold."),
    "legal-hold": _lt("This file is under a legal hold and cannot be destroyed."),
    "checklist-incomplete": _lt("Tick the confirmation that the disclosure checklist is complete."),
    "reviewed-before-period-end": _lt("Subsequent events must be reviewed to a date after the period end."),
    "tieout-failed": _lt("The financial statements do not tie out to the trial balance."),
    "task-not-in-scope": _lt("This task is not in the file's scope."),
    "invalid-letter-kind": _lt("Choose a letter from those offered."),
    "reason-required": _lt("A reason is required."),
}

GATES_FAILED = _lt("These gates are not met: %(gates)s.")


def rule_error(env, code, **params):
    source = MESSAGES.get(code)
    if source is None:
        return tools_rule_error(env, code, **params)
    text = env._(source)
    if params:
        text = text % params
    return AuditRuleError(code, "%s [%s]" % (text, code))


def gates_error(env, failed, labels):
    """gates-failed:<keys>, the code of CompletionGateError, naming the gates in the reader's language."""
    code = "gates-failed:%s" % ",".join(failed)
    return AuditRuleError(code, "%s [%s]" % (env._(GATES_FAILED) % {"gates": "; ".join(labels)}, code))
