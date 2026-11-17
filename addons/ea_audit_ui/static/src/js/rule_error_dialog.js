import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { WarningDialog } from "@web/core/errors/error_dialogs";

// A refusal of the rules engine is a sentence for the reader. Odoo maps dialogs by the exact name of
// the exception, so this subclass of UserError would otherwise open "Oops!" with a traceback.
const RULE_ERROR = "odoo.addons.ea_audit_core.services.errors.AuditRuleError";

// The server ends each refusal with its code in brackets ("... [not-in-firm-yet]"), for the logs and
// the tests. The reader sees the sentence only, under a plain title (review of 2026-11-17).
const CODE_AT_END = /\s*\[([A-Za-z0-9][A-Za-z0-9:_.,-]*)\]\s*$/;

/** The sentence of a refusal and its code, apart: {text, code}. */
export function splitRefusal(message) {
    const text = String(message ?? "");
    const match = text.match(CODE_AT_END);
    if (!match) {
        return { text, code: "" };
    }
    return { text: text.slice(0, match.index), code: match[1] };
}

// Refusals that only wait for something to happen first.
const NOT_YET = new Set(["not-in-firm-yet"]);

export class EaRuleErrorDialog extends WarningDialog {
    setup() {
        super.setup();
        const { text, code } = splitRefusal(this.message);
        this.message = text;
        this.title = NOT_YET.has(code.split(":")[0]) ? _t("Not possible yet") : _t("Not possible");
    }
}

registry.category("error_dialogs").add(RULE_ERROR, EaRuleErrorDialog);
