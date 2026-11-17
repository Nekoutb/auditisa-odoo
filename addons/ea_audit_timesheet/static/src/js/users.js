import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { refusal } from "./common";

const MODEL = "ea.audit.firm.admin";

export class EaFirmUsers extends Component {
    static template = "ea_audit_timesheet.Users";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        // an app opened by its address leaves any mission, and no audit tab is lit
        const shell = useService("ea_audit_context").state;
        shell.mission = null;
        shell.openSection = null;
        shell.screen = "users";
        this.state = useState({
            data: null, error: null, notice: null, link: null, linkFor: "", linkKind: "invite", linkUser: null,
            copied: false, emailed: false,
            invite: { email: "", name: "", role: "staff", engagement: "", teamRole: "staff" },
            domains: "",
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.data = await this.orm.call(MODEL, "ea_fa_users", []);
        this.state.domains = this.state.data.domains;
    }

    async run(work, notice = null) {
        this.state.error = null;
        this.state.notice = null;
        try {
            const said = await work();
            this.state.notice = typeof said === "string" ? said : notice;
        } catch (error) {
            this.state.error = refusal(error);
        }
        await this.load();
    }

    invite() {
        const form = this.state.invite;
        return this.run(async () => {
            const engagementId = form.engagement ? parseInt(form.engagement) : false;
            const result = await this.orm.call(MODEL, "ea_fa_invite", [
                form.email, form.name, form.role, engagementId, engagementId ? form.teamRole : false,
            ]);
            this.showLink(result.link, form.email, "invite", result.user_id);
            form.email = "";
            form.name = "";
            form.engagement = "";
            if (result.engagement) {
                return _t("Also invited to %s. They accept it after their first sign-in.", result.engagement);
            }
        });
    }

    showLink(link, login, kind, userId) {
        this.state.link = link;
        this.state.linkFor = login;
        this.state.linkKind = kind;
        // Only an invitation can be sent by email (a signed-in person is refused by ea_fa_send_link).
        this.state.linkUser = kind === "invite" ? userId : null;
        this.state.copied = false;
        this.state.emailed = false;
    }

    newLink(row) {
        return this.run(async () => {
            const result = await this.orm.call(MODEL, "ea_fa_link", [row.id]);
            this.showLink(result.link, row.login, "invite", row.id);
        });
    }

    passwordLink(row) {
        return this.run(async () => {
            const result = await this.orm.call(MODEL, "ea_fa_password_link", [row.id]);
            this.showLink(result.link, row.login, "password", row.id);
        });
    }

    async copyLink() {
        await navigator.clipboard?.writeText(this.state.link);
        this.state.copied = true;
    }

    // Shown only while the firm's own email is on (set by AuditISA from its console).
    sendLink() {
        return this.run(async () => {
            await this.orm.call(MODEL, "ea_fa_send_link", [this.state.linkUser]);
            this.state.emailed = true;
        }, _t("Invitation sent by email."));
    }

    setRole(row, ev) {
        return this.run(() => this.orm.call(MODEL, "ea_fa_set_role", [row.id, ev.target.value]), _t("Role changed."));
    }

    setActive(row, active) {
        return this.run(
            () => this.orm.call(MODEL, "ea_fa_set_active", [row.id, active]),
            active ? _t("Account reactivated.") : _t("Account deactivated.")
        );
    }

    saveDomains() {
        return this.run(() => this.orm.call(MODEL, "ea_fa_set_domains", [this.state.domains]), _t("Allowed domains saved."));
    }
}

registry.category("actions").add("ea_audit_timesheet.users", EaFirmUsers);
