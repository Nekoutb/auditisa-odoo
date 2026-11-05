import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const STATE_WORDS = {
    not_started: ["Non commencé", "Not started"],
    in_progress: ["En cours", "In progress"],
    prepared: ["Préparé", "Prepared"],
    reviewed: ["Revu", "Reviewed"],
    signed: ["Signé", "Signed"],
    not_applicable: ["N/A", "N/A"],
    absent: ["Absent", "Absent"],
};

/** P7.2: sections A to C and the four signature tiers. The server decides everything. */
export class RasBoard extends Component {
    static template = "ea_audit_papers.RasBoard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({ view: null });
        onWillStart(() => this.load());
    }

    get fr() {
        return (document.documentElement.lang || "fr").startsWith("fr");
    }

    pick(row) {
        return row[this.fr ? "fr" : "en"];
    }

    stateWord(state) {
        return (STATE_WORDS[state] || [state, state])[this.fr ? 0 : 1];
    }

    async load() {
        this.state.view = await this.call("ea_ras_view");
    }

    call(method, ...args) {
        return this.orm.call("ea.audit.engagement", method, [[this.props.payload.engagement_id], ...args]);
    }

    async save(key, value) {
        this.state.view = await this.call("ea_ras_save", key, value);
    }

    async sign(tier, clear = false) {
        this.state.view = await this.call("ea_ras_sign", tier.role, clear);
        this.notification.add(this.fr ? "Signature enregistrée." : "Signature recorded.", { type: "success" });
    }
}

registry.category("ea_audit_paper_boards").add("P7.2", {
    Component: RasBoard,
    label: { fr: "Synthèse de planification", en: "Planning summary" },
});
