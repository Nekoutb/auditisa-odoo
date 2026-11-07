import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class EaTasks extends Component {
    static template = "ea_audit_ui.Tasks";
    static props = { ...standardActionServiceProps };
    static path = "ea-tasks";
    static displayName = _t("Task list");

    setup() {
        this.ctx = useService("ea_audit_context");
        this.notification = useService("notification");
        this.state = useState({ data: null });
        const params = this.props.action.params || {};
        this.engagementId = Number(params.resId);
        this.groupId = params.group;
        onWillStart(async () => {
            const data = await this.ctx.call("ea_ui_tasks", this.engagementId, this.groupId || "");
            if (data.denied) {
                if (this.engagementId) {
                    this.ctx.openDashboard(this.engagementId);
                } else {
                    this.ctx.openHome();
                }
                return;
            }
            this.ctx.enterMission(data.mission);
            this.ctx.state.pageSection = data.group.section;
            this.state.data = data;
        });
        this.props.updateActionState({ resId: this.engagementId, group: this.groupId });
    }

    back() {
        return this.ctx.openDashboard(this.engagementId, this.state.data?.group.section);
    }

    openRow(row) {
        return this.ctx.openItem(row.id);
    }
}

registry.category("actions").add("ea_audit_ui.tasks", EaTasks);

/** The Tasks page of a mission (F021): Mine first, and what is still open, counted. */
export class EaAllTasks extends Component {
    static template = "ea_audit_ui.AllTasks";
    static props = { ...standardActionServiceProps };
    static path = "ea-all-tasks";
    static displayName = _t("Tasks");

    setup() {
        this.ctx = useService("ea_audit_context");
        this.state = useState({ data: null, scope: "mine", openOnly: false });
        const params = this.props.action.params || {};
        this.engagementId = Number(params.resId);
        onWillStart(async () => {
            const data = await this.ctx.call("ea_ui_all_tasks", this.engagementId);
            if (data.denied) {
                this.ctx.openHome();
                return;
            }
            this.ctx.enterMission(data.mission);
            this.state.data = data;
        });
        this.props.updateActionState({ resId: this.engagementId });
    }

    get inScope() {
        const rows = this.state.data.rows;
        return this.state.scope === "mine" ? rows.filter((row) => row.mine) : rows;
    }

    get rows() {
        return this.state.openOnly ? this.inScope.filter((row) => row.open) : this.inScope;
    }

    get mineCount() {
        return this.state.data.rows.filter((row) => row.mine).length;
    }

    get openCount() {
        return this.inScope.filter((row) => row.open).length;
    }

    back() {
        return this.ctx.openDashboard(this.engagementId);
    }

    openRow(row) {
        return this.ctx.openItem(row.id);
    }
}

registry.category("actions").add("ea_audit_ui.all_tasks", EaAllTasks);
