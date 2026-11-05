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
