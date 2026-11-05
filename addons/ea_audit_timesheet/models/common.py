from odoo.tools.translate import LazyTranslate

from odoo.addons.ea_audit_core.services.errors import AuditRuleError

_lt = LazyTranslate("ea_audit_timesheet")

MESSAGES = {
    "ts-week-locked": _lt("This week is locked: the deadline (Tuesday 23:59 of the following week, Douala time) has passed."),
    "ts-week-submitted": _lt("This week is submitted: take it back before the deadline to change it."),
    "ts-future-date": _lt("Hours cannot be entered on a future date."),
    "ts-hours-range": _lt("Hours must be between 0 and 24."),
    "ts-day-over-24": _lt("More than 24 hours on this day."),
    "ts-not-on-team": _lt("Only an accepted member of the team can charge hours to this engagement."),
    "ts-archived": _lt("This engagement is archived: it takes no more hours."),
    "ts-project-not-chargeable": _lt("This project takes no hours."),
    "ts-project-required": _lt("A time line stays on its project."),
    "ts-task-other-project": _lt("This task does not belong to this project."),
    "ts-own-lines-only": _lt("Everyone enters their own hours only."),
    "ts-submit-closed": _lt("The deadline of this week has passed: it can no longer be submitted."),
    "ts-submit-future": _lt("This week has not started."),
    "ts-recall-closed": _lt("This week can no longer be taken back."),
    "ts-reopen-forbidden": _lt("Only a firm administrator, or the partner of one of this person's engagements, can reopen their week."),
    "ts-reopen-self": _lt("You cannot reopen your own week: ask another partner or administrator."),
    "ts-reopen-reason": _lt("Give the reason for reopening (at least 10 characters)."),
    "ts-reopen-not-locked": _lt("This week is not locked."),
    "ts-reopen-active": _lt("This week is already reopened."),
    "ts-budget-range": _lt("A budget is a positive number of hours."),
    "fa-forbidden": _lt("Reserved for the firm administrator."),
    "fa-role-invalid": _lt("Choose a firm role."),
    "fa-email-invalid": _lt("Invalid email address."),
    "fa-user-exists": _lt("A user already exists with this address."),
    "fa-technical-target": _lt("The technical support account is not managed from this screen."),
    "fa-last-admin": _lt("The firm must keep at least one active administrator."),
    "fa-self": _lt("You cannot change your own access: ask another administrator."),
    "fa-holds-partner-seat": _lt("This person is the engagement partner of a file: transfer that role first."),
    "fa-already-joined": _lt("This person has already activated their account: no invitation link."),
    "fa-user-inactive": _lt("This account is deactivated."),
    "fa-project-name": _lt("Give the project a name."),
    "fm-host": _lt("Enter a valid server. Local or private addresses are refused."),
    "fm-port": _lt("Port refused: 25, 465, 587 or 2525."),
    "fm-encryption": _lt("Choose an encryption."),
    "fm-plaintext-password": _lt("A password does not travel unencrypted: choose STARTTLS or SSL."),
    "fm-none": _lt("Save the server first."),
    "fm-untested": _lt("Test the connection before enabling sending."),
    "fm-staging-policy": _lt("Sending email stays off on the test environment, by policy."),
}


def refuse(env, code):
    """The same refusal class as the rules engine, in the language of ``env``."""
    return AuditRuleError(code, env._(MESSAGES[code]))
