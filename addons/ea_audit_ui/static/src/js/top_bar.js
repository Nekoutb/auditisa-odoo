import { Component, onMounted, useExternalListener, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { _t } from "@web/core/l10n/translation";
import { useBus, useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { debounce } from "@web/core/utils/timing";
import { shellSession } from "./context_service";

const PHASES = [
    { key: "acceptance", label: _t("Planning") },
    { key: "strategy", label: _t("Strategy & risks") },
    { key: "execution", label: _t("Execution") },
    { key: "conclusion", label: _t("Conclusion") },
];

function timeAgo(created) {
    const minutes = Math.floor((Date.now() - new Date(`${created.replace(" ", "T")}Z`)) / 60000);
    if (minutes < 1) {
        return _t("just now");
    }
    if (minutes < 60) {
        return _t("%s min ago", minutes);
    }
    const hours = Math.floor(minutes / 60);
    if (hours < 24) {
        return _t("%s h ago", hours);
    }
    const days = Math.floor(hours / 24);
    return days === 1 ? _t("yesterday") : _t("%s d ago", days);
}

export class EaTopBar extends Component {
    static template = "ea_audit_ui.TopBar";
    static props = {};

    setup() {
        this.shell = shellSession;
        this.phases = PHASES;
        this.timeAgo = timeAgo;
        this.ctx = useService("ea_audit_context");
        this.action = useService("action");
        this.orm = useService("orm");
        this.ctxState = useState(this.ctx.state);
        this.state = useState({ open: null, query: "", results: null, notifications: [], notificationTotal: 0 });
        this.search = debounce(this.search.bind(this), 250);

        // One panel at a time. Bell, selector, gear and search open on a click
        // only; a click anywhere else and Esc close them.
        useExternalListener(window, "click", this.onWindowClick.bind(this), { capture: true });
        useExternalListener(window, "keydown", this.onKeydown.bind(this));
        useBus(this.env.bus, "ACTION_MANAGER:UI-UPDATED", () => {
            this.ctx.syncFromController();
            this.ctx.refreshShell();
        });
        onMounted(() => this.ctx.refreshShell());
    }

    get inMission() {
        return Boolean(this.ctxState.mission);
    }

    get currentSection() {
        return this.ctxState.openSection || this.ctxState.mission?.section;
    }

    get selectorLabel() {
        return this.ctxState.mission?.label || _t("Select engagement");
    }

    /** The mission one is in comes first, then the most recently worked. */
    get recentMissions() {
        const current = this.ctxState.mission?.id;
        return [...this.ctxState.recent].sort((a, b) => (b.id === current) - (a.id === current));
    }

    get unreadLabel() {
        const count = this.ctxState.unread;
        return count > 1 ? _t("%s unread", count) : _t("1 unread");
    }

    /** The saved language of the user; the web client comes back in it. */
    get language() {
        return this.shell.language;
    }

    async setLanguage(code) {
        if (code !== this.shell.language) {
            await this.ctx.call("ea_ui_set_language", code);
            browser.location.reload();
        }
    }

    get gearItems() {
        const items = [];
        if (this.inMission) {
            items.push({ label: _t("Engagement record"), run: () => this.ctx.openForm("ea.audit.engagement", this.ctxState.mission.id) });
            for (const entry of this.shell.mission_items || []) {
                items.push({
                    label: entry.label,
                    run: () => this.action.doAction({ type: "ir.actions.client", tag: entry.tag, name: entry.label, params: { resId: this.ctxState.mission.id } }),
                });
            }
        }
        items.push({ label: _t("Clients"), run: () => this.ctx.openXmlid("ea_audit_core.action_client") });
        items.push({ label: _t("My invitations"), run: () => this.ctx.openXmlid("ea_audit_core.action_my_invitations") });
        if (this.shell.is_partner) {
            items.push({ label: _t("Sign-off policy"), run: () => this.ctx.openXmlid("ea_audit_core.action_signoff_policy_open") });
            items.push({ label: _t("Sign-off rules by task"), run: () => this.ctx.openXmlid("ea_audit_core.action_signoff_task_rule") });
            items.push({ label: _t("File index"), run: () => this.ctx.openXmlid("ea_audit_core.action_task_template") });
        }
        if (this.shell.is_system) {
            items.push({ label: _t("Users"), run: () => this.ctx.openXmlid("base.action_res_users") });
            items.push({ label: _t("Apps"), run: () => this.ctx.openXmlid("base.open_module_tree") });
        }
        for (const app of this.apps.filter((a) => a.gear)) {
            items.push({ label: app.label, run: () => this.openApp(app) });
        }
        items.push({ label: _t("Preferences"), run: () => this.openPreferences() });
        return items;
    }

    get apps() {
        return this.shell.apps || [];
    }

    get quickApps() {
        return this.apps.filter((app) => app.top);
    }

    /** Every app opens inside this bar; the audit is one click away, here and on the logo. */
    openApp(app) {
        this.state.open = null;
        if (app.key === "audit") {
            return this.ctx.openHome();
        }
        this.ctxState.mission = null;
        this.ctxState.openSection = null;
        this.ctxState.screen = app.key;
        return this.action.doAction(app.xmlid, { clearBreadcrumbs: true });
    }

    async openPreferences() {
        const description = await this.orm.call("res.users", "action_get");
        description.res_id = user.userId;
        return this.action.doAction(description);
    }

    onWindowClick(ev) {
        const panel = ev.target.closest?.("[data-ea-panel]");
        if (this.state.open && panel?.dataset.eaPanel !== this.state.open) {
            this.state.open = null;
        }
    }

    onKeydown(ev) {
        if (ev.key === "Escape" && this.state.open) {
            this.state.open = null;
        }
    }

    toggle(name) {
        this.state.open = this.state.open === name ? null : name;
    }

    async toggleSelector() {
        this.toggle("selector");
        if (this.state.open === "selector") {
            await this.ctx.refreshShell();
        }
    }

    async toggleBell() {
        this.toggle("bell");
        if (this.state.open === "bell") {
            const data = await this.ctx.call("ea_ui_notifications");
            this.state.notifications = data.rows;
            this.state.notificationTotal = data.total;
            this.ctxState.unread = data.unread;
        }
    }

    openTools() {
        this.state.open = null;
        return this.ctx.openTool(this.ctxState.mission.id, "action_open_tools");
    }

    goHome() {
        this.state.open = null;
        return this.ctx.openHome();
    }

    goMissions() {
        this.state.open = null;
        return this.ctx.openMissions();
    }

    goPhase(key) {
        return this.ctx.openDashboard(this.ctxState.mission.id, key);
    }

    pickMission(mission) {
        this.state.open = null;
        return this.ctx.openDashboard(mission.id);
    }

    pickTask(task) {
        this.state.open = null;
        return this.ctx.openItem(task.id);
    }

    runGear(item) {
        this.state.open = null;
        return item.run();
    }

    onNotificationClick(ev, row) {
        // A modified click keeps its own meaning: a new tab, a new window.
        if (ev.ctrlKey || ev.metaKey || ev.shiftKey || ev.button) {
            return;
        }
        ev.preventDefault();
        return this.openNotification(row);
    }

    openAllNotifications() {
        this.state.open = null;
        return this.ctx.openXmlid("ea_audit_ui.action_notifications");
    }

    async openNotification(row) {
        this.state.open = null;
        const link = await this.ctx.call("ea_ui_notification_open", row.id);
        this.ctx.refreshShell();
        if (!link) {
            return;
        }
        if (link.kind === "invitation") {
            return this.ctx.openXmlid("ea_audit_core.action_my_invitations");
        }
        if (link.file_item_id) {
            return this.ctx.openItem(link.file_item_id);
        }
        return this.ctx.openDashboard(link.engagement_id);
    }

    onSearchInput(ev) {
        this.state.query = ev.target.value;
        this.search();
    }

    async search() {
        const term = this.state.query.trim();
        if (term.length < 2) {
            this.state.results = null;
            if (this.state.open === "search") {
                this.state.open = null;
            }
            return;
        }
        this.state.results = await this.ctx.call("ea_ui_search", term, this.ctxState.mission?.id || false);
        this.state.open = "search";
    }

    onSearchFocus() {
        if (this.state.results) {
            this.state.open = "search";
        }
    }
}
