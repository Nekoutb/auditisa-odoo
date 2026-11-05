"""The refusals of the tools, under the exact kebab-case codes of the platform
(messages/en.json and fr.json), added to the ones ea_audit_core already carries."""
from odoo.tools.translate import LazyTranslate

from odoo.addons.ea_audit_core.services.errors import AuditRuleError
from odoo.addons.ea_audit_core.services.errors import rule_error as core_rule_error

_lt = LazyTranslate("ea_audit_tools")

MESSAGES = {
    "invalid-materiality": _lt("Check the materiality figures: amount > 0, percentage 0–100, performance 60–85 %, trivial 3–5 %."),
    "materiality-out-of-range": _lt("The percentage is outside the firm's range for this benchmark — give a justification for the deviation."),
    "materiality-basis-mismatch": _lt("The amount differs from the trial-balance base for this benchmark — give a justification for the deviation."),
    "performance-justification-required": _lt("Performance materiality departs from the default share of overall materiality — give the justification for the percentage chosen."),
    "justification-required": _lt("A justification is required."),
    "stale-version": _lt("Only the latest materiality version can be approved."),
    "rebut-partner-only": _lt("Only a partner can rebut the presumed revenue-fraud risk (ISA 240 ¶26)."),
    "not-rebuttable": _lt("This presumed risk cannot be rebutted or downgraded."),
    "risk-description-required": _lt("Describe the risk (at least three characters)."),
    "description-required": _lt("A description is required."),
    "rationale-required": _lt("A rationale is required."),
    "rely-without-controls": _lt("Relying on controls needs a tested control covering this assertion (S2.1) and ITGCs that support reliance (S2.5), or a written CR basis (ISA 330 ¶8)."),
    "reassessment-reason-required": _lt("Planning is closed: revising a recorded risk assessment needs a reason (E6.8)."),
    "invalid-assertion": _lt("Choose an assertion (C, E, A, V, P or RO)."),
    "invalid-index": _lt("That lead index is not one of the file's."),
    "invalid-threshold": _lt("The key-item threshold must be an amount above zero."),
    "invalid-severity": _lt("Choose a severity for the deficiency."),
    "invalid-severity-factor": _lt("Choose the likelihood and the magnitude from the options offered."),
    "invalid-date": _lt("Enter a valid date."),
    "recipient-required": _lt("A written communication needs its recipient: name who received it."),
    "related-finding-unknown": _lt("A related deficiency must be another deficiency of this file."),
    "title-required": _lt("A title is required."),
    "amount-required": _lt("An amount is required for a misstatement."),
    "trivial-confirm-required": _lt("Below the trivial threshold — tick the confirmation to log it as trivial."),
    "response-required": _lt("A response is required to clear a note."),
    "specific-above-materiality": _lt("A specific materiality must be below overall materiality (ISA 320 ¶10)."),
    "specific-above-te": _lt("A specific materiality must be below performance materiality (ISA 320 ¶10)."),
    "invalid-field": _lt("That field cannot be changed here."),
    "invalid-value": _lt("That value is not one of the options offered."),
    "invalid-caption": _lt("Choose a financial-statement caption from the options offered."),
    "invalid-type": _lt("Choose a misstatement type from the options offered."),
    "invalid-prefix": _lt("The account prefix must be 1–8 digits."),
    "invalid-section": _lt("The section must be an E-code (e.g. E4.1)."),
    "no-tb": _lt("No trial balance has been imported for this engagement yet."),
    "unsupported-file": _lt("Only .csv and .xlsx files are accepted."),
    "empty-file": _lt("The file is empty."),
    "missing-account-column": _lt("No account-number column was recognised in the file."),
    "missing-amount-columns": _lt("The file needs movement (debit/credit) or closing-balance columns."),
    "unreadable-file": _lt("The file could not be read. Check that it is a valid .xlsx or .csv export, not renamed, corrupt or password-protected."),
    "no-dataset": _lt("No ledger of that kind has been imported on this file."),
    "mapping-incomplete": _lt("The column mapping is incomplete: the required columns must be mapped."),
    "file-too-large": _lt("The file is too large (limit: 60 MB)."),
    "fields-required": _lt("Choose a file and a kind of dataset."),
    "unknown-analytic": _lt("That analytic is not one of the catalogue's thirty."),
    "invalid-accounts": _lt("Choose valid account codes: letters, digits, dot, dash or underscore, within the number allowed."),
    "same-account": _lt("Choose two different accounts."),
    "invalid-month": _lt("Enter a month as MM/YYYY, or n/a for lines with no date."),
    "invalid-weekday": _lt("Choose a weekday from Monday to Sunday, or n/a for lines with no date."),
    "invalid-amount": _lt("Enter an amount of zero or more."),
    "tool-not-available": _lt("This tool is not available yet on this version."),
}


def rule_error(env, code, **params):
    source = MESSAGES.get(code)
    if source is None:
        return core_rule_error(env, code, **params)
    text = env._(source)
    if params:
        text = text % params
    return AuditRuleError(code, "%s [%s]" % (text, code))
