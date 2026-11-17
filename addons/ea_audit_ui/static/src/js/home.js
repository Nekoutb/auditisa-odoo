import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { shellSession } from "./context_service";

export class EaHome extends Component {
    static template = "ea_audit_ui.Home";
    static props = { ...standardActionServiceProps };
    static path = "ea-home";
    static displayName = _t("Dashboard");

    setup() {
        this.shell = shellSession;
        this.ctx = useService("ea_audit_context");
        this.action = useService("action");
        this.state = useState({ todo: [], missions: [], invitations: [], loaded: false });
        onWillStart(async () => {
            this.ctx.enterHome();
            await this.load();
        });
    }

    async load() {
        const data = await this.ctx.call("ea_ui_home");
        Object.assign(this.state, data, { loaded: true });
    }

    // Accept opens the invitation itself: its form carries the independence confirmation.
    acceptInvitation(invitation) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "ea.audit.team.member",
            res_id: invitation.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    declineInvitation(invitation) {
        return this.action.doAction("ea_audit_core.action_team_decline_wizard", {
            additionalContext: { default_member_id: invitation.id },
            onClose: () => this.load(),
        });
    }

    openTodo(row) {
        if (row.tool) {
            return this.ctx.openTool(row.engagement_id, row.tool);
        }
        if (row.item_ids?.length === 1) {
            return this.ctx.openItem(row.item_ids[0]);
        }
        if (row.item_ids?.length) {
            return this.ctx.openItems(row.item_ids, row.title);
        }
        return this.ctx.openDashboard(row.engagement_id);
    }

    openMission(mission) {
        return this.ctx.openDashboard(mission.id);
    }

    newMission() {
        return this.ctx.openXmlid("ea_audit_core.action_engagement_create_wizard");
    }
}

registry.category("actions").add("ea_audit_ui.home", EaHome);
