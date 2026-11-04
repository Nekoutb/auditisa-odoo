import { Component, onMounted, useExternalListener, useState } from "@odoo/owl";
import { useBus, useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { debounce } from "@web/core/utils/timing";
import { shellSession } from "./context_service";

const PHASES = [
    { key: "acceptance", label: "Planification" },
    { key: "strategy", label: "Stratégie & risques" },
    { key: "execution", label: "Exécution" },
    { key: "conclusion", label: "Conclusion" },
];

function timeAgo(created) {
    const minutes = Math.floor((Date.now() - new Date(`${created.replace(" ", "T")}Z`)) / 60000);
    if (minutes < 1) {
        return "à l'instant";
    }
    if (minutes < 60) {
        return `il y a ${minutes} min`;
    }
    const hours = Math.floor(minutes / 60);
    if (hours < 24) {
        return `il y a ${hours} h`;
    }
    const days = Math.floor(hours / 24);
    return days === 1 ? "hier" : `il y a ${days} j`;
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
        this.state = useState({ open: null, query: "", results: null, notifications: [] });
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
        return this.ctxState.mission?.label || "Choisir une mission";
    }

    get gearItems() {
        const items = [];
        if (this.inMission) {
            items.push({ label: "Fiche de la mission", run: () => this.ctx.openForm("ea.audit.engagement", this.ctxState.mission.id) });
        }
        items.push({ label: "Clients", run: () => this.ctx.openXmlid("ea_audit_core.action_client") });
        items.push({ label: "Mes invitations", run: () => this.ctx.openXmlid("ea_audit_core.action_my_invitations") });
        if (this.shell.is_partner) {
            items.push({ label: "Politique de signature", run: () => this.ctx.openXmlid("ea_audit_core.action_signoff_policy_open") });
            items.push({ label: "Règles de signature par tâche", run: () => this.ctx.openXmlid("ea_audit_core.action_signoff_task_rule") });
            items.push({ label: "Index du dossier", run: () => this.ctx.openXmlid("ea_audit_core.action_task_template") });
        }
        if (this.shell.is_system) {
            items.push({ label: "Utilisateurs", run: () => this.ctx.openXmlid("base.action_res_users") });
            items.push({ label: "Applications", run: () => this.ctx.openXmlid("base.open_module_tree") });
        }
        items.push({ label: "Préférences", run: () => this.openPreferences() });
        return items;
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
            this.ctxState.unread = data.unread;
        }
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
        this.state.results = await this.ctx.call("ea_ui_search", term);
        this.state.open = "search";
    }

    onSearchFocus() {
        if (this.state.results) {
            this.state.open = "search";
        }
    }
}
