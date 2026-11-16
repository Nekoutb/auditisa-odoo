import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class EaDashboard extends Component {
    static template = "ea_audit_ui.Dashboard";
    static props = { ...standardActionServiceProps };
    static path = "ea-mission";
    static displayName = _t("Engagement dashboard");

    setup() {
        this.ctx = useService("ea_audit_context");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.action = useService("action");
        this.ctxState = useState(this.ctx.state);
        this.state = useState({ data: null });
        const params = this.props.action.params || {};
        this.engagementId = Number(params.resId);
        onWillStart(async () => {
            const data = await this.ctx.call("ea_ui_dashboard", this.engagementId);
            if (data.denied) {
                this.notification.add(_t("You are not a member of this engagement's team."), { type: "warning" });
                this.ctx.openHome();
                return;
            }
            this.ctx.enterMission(data.mission);
            if (params.section) {
                this.ctxState.openSection = params.section;
            }
            this.state.data = data;
        });
        this.props.updateActionState({ resId: this.engagementId });
    }

    get openSection() {
        return this.ctxState.openSection;
    }

    /** Beside an open ring its panel takes its own column: nothing clips or overlaps. */
    get gridStyle() {
        const rings = this.state.data.rings;
        if (!this.openSection) {
            return `grid-template-columns: repeat(${rings.length}, minmax(0, 1fr));`;
        }
        const columns = rings.flatMap((ring) =>
            ring.key === this.openSection ? ["1.05fr", "1.45fr"] : ["1fr"]
        );
        return `grid-template-columns: ${columns.map((c) => `minmax(0, ${c})`).join(" ")};`;
    }

    ringStyle(ring) {
        return `background: conic-gradient(var(--ea-green2) ${ring.pct * 3.6}deg, var(--ea-line) 0);`;
    }

    toggleRing(ring) {
        this.ctxState.openSection = this.openSection === ring.key ? null : ring.key;
    }

    openGroup(group) {
        if (group.tool) {
            return this.ctx.openTool(this.engagementId, group.tool);
        }
        return this.ctx.openTasks(this.engagementId, group.id);
    }

    openItem(id) {
        return this.ctx.openItem(id);
    }

    openNotes() {
        const ids = this.state.data.notes.note_item_ids;
        if (ids.length === 1) {
            return this.ctx.openItem(ids[0]);
        }
        return ids.length ? this.ctx.openItems(ids, _t("Review notes for me")) : undefined;
    }

    openTool(method) {
        return this.ctx.openTool(this.engagementId, method);
    }

    openAllTasks() {
        return this.ctx.openAllTasks(this.engagementId);
    }

    openUnassigned() {
        return this.ctx.openItems(this.state.data.unassigned_ids, _t("Tasks without a preparer"));
    }

    /** The profile questionnaire: until it is concluded the file has no task. */
    async openProfile() {
        const action = await this.orm.call("ea.audit.engagement", "action_open_profile", [[this.engagementId]]);
        return this.action.doAction(action);
    }

    openClient() {
        return this.ctx.openForm("ea.audit.client", this.state.data.mission.client_id);
    }
}

registry.category("actions").add("ea_audit_ui.dashboard", EaDashboard);
