import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { odooExceptionTitleMap, WarningDialog } from "@web/core/errors/error_dialogs";

// A refusal of the rules engine is a sentence for the reader. Odoo maps dialogs by the exact name of
// the exception, so this subclass of UserError would otherwise open "Oops!" with a traceback.
const RULE_ERROR = "odoo.addons.ea_audit_core.services.errors.AuditRuleError";

odooExceptionTitleMap.set(RULE_ERROR, _t("Invalid Operation"));
registry.category("error_dialogs").add(RULE_ERROR, WarningDialog);
