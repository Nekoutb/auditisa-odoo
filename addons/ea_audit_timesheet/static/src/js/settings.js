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
    static path = "parametres-firme";

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            mail: null, form: {}, projects: [], newProject: "", error: null, notice: null,
        });
        onWillStart(() => this.load());
    }

    get stateLabel() {
        return {
            none: _t("No server"),
            untested: _t("Off, not tested"),
            tested: _t("Off, test passed"),
            on: _t("Sending on"),
        }[this.state.mail.state];
    }

    get testedLine() {
        return _t("Test passed on %(at)s", { at: this.state.mail.tested_at });
    }

    apply(mail) {
        this.state.mail = mail;
        this.state.form = {
            host: mail.host, port: mail.port, encryption: mail.encryption,
            user: mail.user, from_filter: mail.from_filter, password: "",
        };
    }

    async load() {
        const [mail, projects] = await Promise.all([
            this.orm.call(MODEL, "ea_fm_get", []),
            this.orm.call(MODEL, "ea_fa_projects", []),
        ]);
        this.apply(mail);
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

    save() {
        return this.run(async () => {
            this.apply(await this.orm.call(MODEL, "ea_fm_save", [this.state.form]));
            this.state.notice = _t("Server saved. Sending stays off until a test passes.");
        });
    }

    test() {
        return this.run(async () => {
            const result = await this.orm.call(MODEL, "ea_fm_test", []);
            this.apply(result.state);
            if (result.ok) {
                this.state.notice = result.message;
            } else {
                this.state.error = result.message;
            }
        });
    }

    enable() {
        return this.run(async () => this.apply(await this.orm.call(MODEL, "ea_fm_enable", [])));
    }

    disable() {
        return this.run(async () => this.apply(await this.orm.call(MODEL, "ea_fm_disable", [])));
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
