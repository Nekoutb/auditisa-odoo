import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { shellSession } from "./context_service";

export class EaHome extends Component {
    static template = "ea_audit_ui.Home";
    static props = { ...standardActionServiceProps };
    static path = "ea-accueil";
    static displayName = _t("Dashboard");

    setup() {
        this.shell = shellSession;
        this.ctx = useService("ea_audit_context");
        this.state = useState({ todo: [], missions: [], loaded: false });
        onWillStart(async () => {
            this.ctx.enterHome();
            const data = await this.ctx.call("ea_ui_home");
            Object.assign(this.state, data, { loaded: true });
        });
    }

    openTodo(row) {
        if (row.invitation) {
            return this.ctx.openXmlid("ea_audit_core.action_my_invitations");
        }
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
