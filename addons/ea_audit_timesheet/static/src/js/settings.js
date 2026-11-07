import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { refusal } from "./common";

const MODEL = "ea.audit.firm.admin";

export class EaFirmSettings extends Component {
    static template = "ea_audit_timesheet.Settings";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        // an app opened by its address leaves any mission, and no audit tab is lit
        const shell = useService("ea_audit_context").state;
        shell.mission = null;
        shell.openSection = null;
        shell.screen = "settings";
        this.state = useState({
            mail: null, projects: [], newProject: "", error: null, notice: null,
        });
        onWillStart(() => this.load());
    }

    /** Sending on or off: the firm's mail is set by AuditISA at onboarding, never on this screen. */
    get stateLabel() {
        if (this.state.mail.staging) {
            return _t("Off on the test environment");
        }
        return this.state.mail.on ? _t("Sending on") : _t("Sending off");
    }

    async load() {
        const [mail, projects] = await Promise.all([
            this.orm.call(MODEL, "ea_fm_get", []),
            this.orm.call(MODEL, "ea_fa_projects", []),
        ]);
        this.state.mail = mail;
        this.state.projects = projects;
    }

    async run(work) {
        this.state.error = null;
        this.state.notice = null;
        try {
            await work();
        } catch (error) {
            this.state.error = refusal(error);
        }
    }

    addProject() {
        return this.run(async () => {
            await this.orm.call(MODEL, "ea_fa_project_add", [this.state.newProject]);
            this.state.newProject = "";
            this.state.projects = await this.orm.call(MODEL, "ea_fa_projects", []);
        });
    }

    setProjectActive(project, active) {
        return this.run(async () => {
            await this.orm.call(MODEL, "ea_fa_project_active", [project.id, active]);
            this.state.projects = await this.orm.call(MODEL, "ea_fa_projects", []);
        });
    }
}

registry.category("actions").add("ea_audit_timesheet.settings", EaFirmSettings);
