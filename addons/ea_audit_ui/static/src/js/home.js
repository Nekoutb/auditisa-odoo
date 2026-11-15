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
        this.state = useState({ missions: [], loaded: false });
        onWillStart(async () => {
            this.ctx.enterHome();
            const data = await this.ctx.call("ea_ui_home");
            Object.assign(this.state, data, { loaded: true });
        });
    }

    openMission(mission) {
        return this.ctx.openDashboard(mission.id);
    }

    newMission() {
        return this.ctx.openXmlid("ea_audit_core.action_engagement_create_wizard");
    }
}

registry.category("actions").add("ea_audit_ui.home", EaHome);
