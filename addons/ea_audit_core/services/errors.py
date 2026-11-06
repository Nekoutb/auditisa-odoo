"""Refusal codes of the rules engine, one per kebab-case code of the Next.js
application (messages/en.json), so the UI messages map 1:1.
"""
from odoo.exceptions import UserError
from odoo.tools.translate import LazyTranslate

_lt = LazyTranslate("ea_audit_core")

MESSAGES = {
    "forbidden": _lt("You do not have permission to sign off in that role."),
    "requires-senior": _lt("Only a senior or above can sign as reviewer."),
    "requires-partner": _lt("Only a partner can do this."),
    "archived": _lt("This file is archived and immutable."),
    "not-found": _lt("Not found."),
    "eqr-own-paper": _lt("C4.2 is the engagement quality reviewer's own record: only the quality reviewer appointed on the team completes and signs it (ISQM 2 ¶24-27)."),
    "signed-locked": _lt("This working paper is already fully signed and locked."),
    "acceptance-open": _lt("The engagement is still in acceptance: pass the acceptance gates (P1.1 partner sign-off) before working on later phases."),
    "planning-open": _lt("Planning is not closed yet: pass the planning gates before recording execution or conclusion work."),
    "execution-open": _lt("Execution is not closed yet: issue the report before recording conclusion work."),
    "not-on-team-to-sign": _lt("Only an accepted member of this engagement's team can sign its working papers."),
    "accept-engagement-first": _lt("Accept the engagement invitation on its dashboard before signing work on it."),
    "partner-only": _lt("This task can only be approved by the audit partner."),
    "designate-engagement-partner-first": _lt("Designate the engagement partner on the team page before giving a partner sign-off."),
    "not-engagement-partner": _lt("Only the engagement partner, or the partner they delegated to, can give this partner sign-off."),
    "tool-output-missing-materiality": _lt("Approve materiality in the tool first (P6.1): this paper is fed by the approved figures."),
    "tool-output-missing-tb": _lt("Import a valid trial balance for the year first: this paper is fed by it (lead schedules, P6.2, C1.1)."),
    "tool-output-missing-sad": _lt("Record the team conclusion in the Summary of Audit Differences tool first (C1.1)."),
    "no-version": _lt("Generate the working paper before signing it off."),
    "checked-out": _lt("This working paper is checked out for editing. Check it in before signing."),
    "already-signed": _lt("You have already signed this working paper in that role."),
    "preparer-first": _lt("The preparer must sign off and hand off before the reviewer can sign."),
    "paper-incomplete": _lt("The working paper is incomplete — answer every procedure, evaluation and conclusion (explaining each \"No\") before signing it off."),
    "significance-unjustified": _lt("Every significance decision that departs from the default needs its justification before P6.2 is signed off."),
    "itapp-strategy-missing": _lt("Every relevant IT application needs an IT strategy before S2.3 is signed off — decide the strategy of each application still at \"— decide\"."),
    "ras-not-approved": _lt("P7.2 is approved on the Planning Review & Approval Summary: the engagement partner signs there once every confirmation and deliverable is in place. Review sign-off on the row follows that approval."),
    "self-review": _lt("You signed this paper as preparer: another member of the team must review it."),
    "open-notes": _lt("Clear the open review notes on this working paper before reviewer sign-off."),
    "review-conclusion-first": _lt("Review the section conclusion (\"Reviewed (senior/manager)\") before signing the paper as reviewer."),
    "role-below-task-minimum-staff": _lt("This task requires at least an audit staff member of the engagement team."),
    "role-below-task-minimum-senior": _lt("This task requires at least an audit senior on the engagement team."),
    "role-below-task-minimum-manager": _lt("This task requires at least an audit manager on the engagement team."),
    "role-below-task-minimum-senior-manager": _lt("This task requires at least an audit senior manager on the engagement team."),
    "role-below-task-minimum-director": _lt("This task requires at least an audit director on the engagement team."),
    "role-below-task-minimum-partner": _lt("This task requires the audit partner of the engagement team."),
    "one-engagement-partner": _lt("This engagement already has its engagement partner. Use the transfer form to hand the role over."),
    "last-partner": _lt("The engagement partner cannot be removed or re-roled: transfer the role to another partner first."),
    "partner-role-requires-partner-rank": _lt("Only a partner or firm administrator of the firm can hold the engagement partner role."),
    "eqr-rank": _lt("The engagement quality reviewer must be a partner of the firm or hold the firm role of EQR reviewer."),
    "eqr-on-team": _lt("The EQR reviewer must be independent of the engagement team."),
    "eqr-cooling-off": _lt("This person was the engagement partner of the same client within the two years before this period end: the cooling-off period applies (ISQM 2 ¶20)."),
    "eqr-declaration-required": _lt("Tick the objectivity declaration to appoint the engagement quality reviewer."),
    "preparer-equals-approver": _lt("The same person cannot be both preparer and reviewer of a task (firm sign-off policy)."),
    "email-domain-not-allowed": _lt("This email address is not on one of the firm's allowed domains (%(domains)s). Engagement-team invitations go only to those domains; a firm administrator can change the list in Settings."),
    "invalid-email-domain": _lt("One of the entries is not a valid email domain (e.g. eca.com)."),
    "engagement-partner-required": _lt("Choose the engagement partner: an engagement cannot be created without one (a partner or administrator of the firm)."),
    "not-on-this-engagement": _lt("Only accepted members of an engagement's team can open it."),
    "read-only-role": _lt("Your role can view this file but not change it."),
    "team-manager-only": _lt("Only a manager, partner or firm administrator on this engagement can change its team."),
    "partner-only-team-role": _lt("Only a partner can give or take away the engagement partner role."),
    "invalid-team-role": _lt("Choose a valid team role."),
    "unknown-task-code": _lt("One of the task codes is not in the audit file index."),
    "signoff-policy-partner-only": _lt("Only a partner or firm administrator can change the firm's sign-off rules."),
    "delegate-is-partner": _lt("The engagement partner signs in their own right: choose another partner as delegate."),
    "delegate-requires-partner-rank": _lt("The delegate must be a partner of the firm."),
    "delegate-not-on-team": _lt("Add the delegate to the engagement team first."),
    "transfer-partner-forbidden": _lt("Only the engagement partner or a firm administrator can transfer the engagement partner role."),
    "already-engagement-partner": _lt("This person is already the engagement partner."),
    "eqr-not-assignable": _lt("The engagement quality reviewer cannot be assigned engagement work (ISQM 2 ¶18-20)."),
    "eqr-read-only": _lt("The engagement quality reviewer reviews the team's work and raises notes, but does not change it. Record the review in C4.2."),
    "already-on-team": _lt("This person is already on the engagement team. To change their role, use the team assignment on the planning page."),
    "invalid-email": _lt("Enter a valid email address."),
    "email-taken": _lt("A user with this email already exists."),
    "reason-required": _lt("A reason is required."),
    "invalid-year": _lt("The new fiscal year must be after the current one."),
    "wrong-phase": _lt("The engagement is not in the right phase for this action."),
    "not-a-firm-member": _lt("That person is not a member of this firm."),
    "invalid-standards-edition": _lt("Choose a valid standards edition."),
    "engagement-archived": _lt("This file is archived and immutable."),
    "gates-failed": _lt("The gates of this phase are not all met: %(gates)s."),
    "firm-role-conflict": _lt("A person holds one firm role: read-only or EQR reviewer cannot be combined with another role."),
}

GATE_LABELS = {
    "d31_form_complete": _lt("P1.1 checklist complete and concluded \"accept\""),
    "d31_partner_signed": _lt("Partner sign-off on P1.1"),
    "engagement_partner_designated": _lt("Exactly one engagement partner designated on the team, who has accepted the engagement"),
    "materiality_approved": _lt("Materiality approved by a partner"),
    "p22_partner_signed": _lt("Partner sign-off on P2.2"),
    "p52_partner_signed": _lt("Partner sign-off on P5.2"),
    "s31_partner_signed": _lt("Partner sign-off on S3.1"),
    "cra_reliance_supported": _lt("Every control-risk \"rely\" on S3.1 rests on a control selected for testing, or on a written basis (ISA 330 ¶8)"),
    "p72_partner_signed": _lt("Partner approval of the plan on P7.2"),
    "significant_risks_linked": _lt("Every significant risk linked to at least one program step"),
    "rebuttals_approved": _lt("Rebuttals carry partner approval"),
    "material_sections_covered": _lt("Every material section has planned coverage (stand-back)"),
    "tb_mapped": _lt("Trial balance fully mapped (no unknown accounts)"),
    "d31_checks_passed": _lt("Every required P1.1 acceptance check answered \"yes\" (predecessor contact for a new engagement)"),
    "review_notes_cleared": _lt("Review notes cleared (papers and tasks)"),
}


class AuditRuleError(UserError):
    """A refusal of the rules engine. ``code`` is the exact code of the current
    application; the message shown is its translation, followed by the code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def rule_error(env, code, **params):
    """Build the refusal for ``code`` in the language of ``env``.

    gates-failed:<keys> carries its failed gates in the code, as GateError does.
    """
    source = MESSAGES.get(code.split(":", 1)[0])
    if source is None:
        return AuditRuleError(code, code)
    text = env._(source)
    if params:
        text = text % params
    return AuditRuleError(code, "%s [%s]" % (text, code))


def gate_label(env, key):
    source = GATE_LABELS.get(key)
    return env._(source) if source is not None else key
