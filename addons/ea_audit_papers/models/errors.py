"""The refusal codes this addon adds to the rules engine. They live here rather than in
core's table so that core does not carry the working-paper vocabulary."""
from odoo.tools.translate import LazyTranslate

from odoo.addons.ea_audit_core.services.errors import MESSAGES as CORE_MESSAGES, AuditRuleError, rule_error

_lt = LazyTranslate("ea_audit_papers")

MESSAGES = {
    "stale-edit": _lt("Someone else saved this record while you were editing it. Reload, merge your text with theirs, and save again: your entry has not been stored."),
    "tieout-unexplained": _lt("The tie-out shows differences: explain them in the tie-out procedure before answering \"Yes\"."),
    "c58-equity-contradicts": _lt("C5.8 cannot state that net equity exceeds half of the share capital: the legal monitor's figures put it below half. Check the figures on the legal page, or answer No and document the article 664 procedure."),
    "body-required": _lt("Write a message first."),
    "response-required": _lt("A response is required."),
    "requires-manager-or-author": _lt("Only the note's author or a manager who did not prepare the paper can clear it."),
    "not-preparer-clears": _lt("The preparer of this paper cannot clear a note raised against it: reply to it and let the reviewer clear it."),
    "conclusion-required": _lt("A conclusion is required."),
    "steps-open": _lt("Objectives cannot be marked as achieved while program steps are still open: complete them or mark them N/A first."),
    "no-procedures-rationale-required": _lt("No procedure is retained on this section: give the rationale for concluding without procedures."),
    "walkthrough-incomplete": _lt("The walkthroughs are incomplete: every SCOT needs all its walkthrough answers on S1.3 before the paper is signed."),
    "wcgw-missing": _lt("Every SCOT needs at least one what-can-go-wrong on S1.2 before the paper is signed."),
    "control-selection-incomplete": _lt("The control selection is incomplete: every control selected for testing must answer a WCGW, and every SCOT on a controls strategy needs a control selected, before S2.1 is signed."),
    "test-design-missing": _lt("Every control selected for testing needs its test design on S2.2 before the paper is signed."),
    "no-extension": _lt("This file has no extension, so its type cannot be checked."),
    "executable-refused": _lt("Executables, scripts and macro-enabled files cannot enter an audit file."),
    "extension-not-allowed": _lt("This file type is not accepted in an audit file."),
    "empty-file": _lt("The file is empty."),
    "content-mismatch": _lt("The content of this file does not match its extension."),
    "not-an-office-file": _lt("This file is not a real Office document."),
    "file-too-large": _lt("The file is larger than the 25 MB limit."),
    "name-required": _lt("Name is required."),
    "name-taken": _lt("A file with this name already exists on this task."),
    "restore-window-expired": _lt("The 30-day recovery window of this file has passed."),
    "rationale-required": _lt("Give the reason why this task is not applicable."),
    "ras-incomplete": _lt("The summary is not ready for this signature. Still missing: %(gaps)s."),
    "ras-invalid-key": _lt("This line is not on the summary."),
    "ras-section-floor": _lt("This section is answered at a higher rank."),
    "exception-blocked": _lt("\"No exceptions noted\" is not available on this paper: a tool has raised a warning. Describe the work and its result in the box instead."),
    "autocheck-contradicts": _lt("The tool's figures do not support a \"Yes\" to this statement. Check the tool, or answer No and explain."),
    "eqr-must-be-the-quality-reviewer": _lt("Section C belongs to the engagement quality reviewer appointed on this file."),
}

INCOMPLETE_PARTS = _lt("Still to complete: %(parts)s.")


def paper_error(env, code):
    """The refusal for ``code``, core's or this addon's, with the code kept visible."""
    if code in CORE_MESSAGES or code not in MESSAGES:
        return rule_error(env, code)
    return AuditRuleError(code, "%s [%s]" % (env._(MESSAGES[code]), code))


def ras_incomplete_error(env, gaps):
    """ras-incomplete naming what is missing, in the summary's own keys (UAT B16)."""
    return AuditRuleError(
        "ras-incomplete", "%s [ras-incomplete]" % (env._(MESSAGES["ras-incomplete"]) % {"gaps": ", ".join(gaps)}),
    )


def incomplete_error(env, parts):
    """paper-incomplete naming the parts that stop the signature, in the reader's language."""
    base = rule_error(env, "paper-incomplete").args[0]
    suffix = " [paper-incomplete]"
    french = (env.lang or "").startswith("fr")
    titles = ", ".join(part["fr" if french else "en"] for part in parts)
    message = "%s %s%s" % (base[: -len(suffix)], env._(INCOMPLETE_PARTS) % {"parts": titles}, suffix)
    return AuditRuleError("paper-incomplete", message)
