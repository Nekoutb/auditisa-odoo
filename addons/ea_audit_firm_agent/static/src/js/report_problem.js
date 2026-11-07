import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

// "Report a problem", in the user menu of every screen: a message to the operator, with a warning
// on the form not to write client details.
function reportProblemItem(env) {
    return {
        type: "item",
        id: "ea_report_problem",
        description: _t("Report a problem"),
        callback: () => env.services.action.doAction("ea_audit_firm_agent.action_support_ticket_new"),
        sequence: 45,
    };
}

function myProblemsItem(env) {
    return {
        type: "item",
        id: "ea_my_problems",
        description: _t("My reported problems"),
        callback: () => env.services.action.doAction("ea_audit_firm_agent.action_support_tickets"),
        sequence: 46,
    };
}

registry.category("user_menuitems").add("ea_report_problem", reportProblemItem).add("ea_my_problems", myProblemsItem);
