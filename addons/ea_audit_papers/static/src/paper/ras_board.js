import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";

const STATE_WORDS = {
    not_started: _t("Not started"),
    in_progress: _t("In progress"),
    prepared: _t("Prepared"),
    reviewed: _t("Reviewed"),
    signed: _t("Signed"),
    not_applicable: "N/A",
    absent: _t("Absent"),
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
        return (user.lang || "").startsWith("fr");
    }

    pick(row) {
        return row[this.fr ? "fr" : "en"];
    }

    stateWord(state) {
        return String(STATE_WORDS[state] || state);
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
        this.notification.add(_t("Signature recorded."), { type: "success" });
    }
}

registry.category("ea_audit_paper_boards").add("P7.2", {
    Component: RasBoard,
    label: { fr: "Synthèse de planification", en: "Planning summary" },
});
