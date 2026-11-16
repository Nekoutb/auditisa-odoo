import { Component, onMounted, onPatched, onWillStart, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { EaDocsPane } from "./page_kit";

/**
 * SCOTs and controls (owner's mock-ups of 2026-11-16): the totals above the cards, the counts on
 * the SCOT's tabs, the "which control answers which risk" grid and the SCOT's documents.
 */

function errorText(error) {
    return error?.data?.message || error?.message || _t("The action failed.");
}

// ---------------------------------------------------------------------------------------------
// Overview: the totals and the buttons above the cards
// ---------------------------------------------------------------------------------------------

export class ScotTotalsBar extends Component {
    static template = "ea_audit_tools.ScotTotalsBar";
    static props = { engagementId: Number, reload: Function };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ totals: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.totals = await this.orm.call("ea.audit.engagement", "ea_scot_totals", [[this.props.engagementId]]);
    }

    get context() {
        return { ea_engagement_id: this.props.engagementId };
    }

    async newScot() {
        const action = await this.orm.call("ea.audit.scot", "action_list_new_scot", [[]], { context: this.context });
        await this.action.doAction(action, {
            onClose: async () => {
                await this.props.reload();
                await this.load();
            },
        });
    }

    async exportExcel() {
        const action = await this.orm.call("ea.audit.scot", "action_list_export_scots", [[]], { context: this.context });
        await this.action.doAction(action);
    }
}

export class ScotKanbanController extends KanbanController {
    static template = "ea_audit_tools.ScotKanbanView";
    static components = { ...KanbanController.components, ScotTotalsBar };

    get eaEngagementId() {
        const context = this.props.context || {};
        return context.ea_engagement_id || context.default_engagement_id || 0;
    }

    async eaReload() {
        await this.model.load();
    }
}

registry.category("views").add("ea_scot_kanban", { ...kanbanView, Controller: ScotKanbanController });

// ---------------------------------------------------------------------------------------------
// Inside a SCOT: the count on each tab
// ---------------------------------------------------------------------------------------------

/** Adds the count to each of the four tabs (the documents sit in the pane at the right). The tabs work without it: it only decorates them. */
export class ScotTabCounts extends Component {
    static template = "ea_audit_tools.ScotTabCounts";
    static props = { ...standardWidgetProps };

    setup() {
        this.root = useRef("root");
        onMounted(() => this.decorate());
        onPatched(() => this.decorate());
    }

    get counts() {
        const data = this.props.record.data;
        return [
            String(data.index_count || 0),
            String(data.wcgw_count || 0),
            String(data.control_count || 0),
            data.walkthrough_open ? String(data.walkthrough_open) : "✓",
        ];
    }

    decorate() {
        const form = this.root.el?.closest(".o_form_sheet, .o_form_renderer");
        const links = form ? form.querySelectorAll(".o_ea_scot_notebook .o_notebook_headers .nav-link") : [];
        const counts = this.counts;
        links.forEach((link, index) => {
            if (index >= counts.length) {
                return;
            }
            let badge = link.querySelector(".o_ea_tab_count");
            if (!badge) {
                badge = document.createElement("span");
                badge.className = "o_ea_tab_count";
                link.appendChild(badge);
            }
            badge.textContent = counts[index];
        });
    }
}

registry.category("view_widgets").add("ea_scot_tab_counts", { component: ScotTabCounts });

// ---------------------------------------------------------------------------------------------
// Which control answers which risk
// ---------------------------------------------------------------------------------------------

export class ScotGrid extends Component {
    static template = "ea_audit_tools.ScotGrid";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({ grid: null, busy: false });
        onWillStart(() => this.load());
    }

    async load() {
        const id = this.props.record.resId;
        this.state.grid = id ? await this.orm.call("ea.audit.scot", "ea_grid", [[id]]) : null;
    }

    isLinked(wcgw, control) {
        return this.state.grid.links.some(([w, c]) => w === wcgw.id && c === control.id);
    }

    async toggle(wcgw, control) {
        if (!this.state.grid.canEdit || this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            this.state.grid = await this.orm.call("ea.audit.scot", "ea_toggle_link", [[this.props.record.resId], wcgw.id, control.id]);
            await this.props.record.model.load();
        } catch (error) {
            this.notification.add(errorText(error), { type: "danger" });
        } finally {
            this.state.busy = false;
        }
    }
}

registry.category("view_widgets").add("ea_scot_grid", { component: ScotGrid });

// ---------------------------------------------------------------------------------------------
// The SCOT's documents
// ---------------------------------------------------------------------------------------------

/** The SCOT's documents, in the pane at the right of the SCOT (owner, 2026-11-16): always in
 * view beside the tabs, no longer a tab of their own. The pane is the one every page shares. */
export class ScotDocuments extends Component {
    static template = "ea_audit_tools.ScotDocuments";
    static props = { ...standardWidgetProps };
    static components = { EaDocsPane };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({ docs: null });
        onWillStart(() => this.load());
    }

    get scotId() {
        return this.props.record.resId;
    }

    async load() {
        this.state.docs = this.scotId ? await this.orm.call("ea.audit.scot", "ea_documents", [[this.scotId]]) : null;
    }

    async call(method, args) {
        try {
            this.state.docs = await this.orm.call("ea.audit.scot", method, [[this.scotId], ...args]);
            await this.props.record.model.load();
            return true;
        } catch (error) {
            this.notification.add(errorText(error), { type: "danger" });
            return false;
        }
    }

    async upload(files, options) {
        for (const file of files) {
            if (!(await this.call("upload_document", [file.name, file.content, options.type || "other", options.controlId || false]))) {
                break;
            }
        }
    }

    attachExisting(ids, options) {
        return this.call("attach_existing_documents", [ids, options.type || "other", options.controlId || false]);
    }

    setType(doc, value) {
        return this.call("set_document", [doc.id, value, null]);
    }

    setControl(doc, value) {
        return this.call("set_document", [doc.id, null, value || false]);
    }

    remove(doc) {
        return this.call("remove_document", [doc.id]);
    }

    restore(doc) {
        return this.call("restore_document", [doc.id]);
    }
}

registry.category("view_widgets").add("ea_scot_documents", { component: ScotDocuments });
