import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";
import { EaCrumbs } from "./page_kit";

const ENGAGEMENT = "ea.audit.engagement";

/**
 * The summary of audit differences on one page (owner's mock-up of 2026-11-16): a bar with the
 * uncorrected total against the materiality levels, one grid of differences with their effect
 * on profit, assets, liabilities and equity, and the side topics as tabs. Every figure and its
 * verdict come from the server (ea_sad_page); every change goes through the SAD's own rules.
 */
export class SadPage extends Component {
    static template = "ea_audit_tools.SadPage";
    static props = ["*"];
    static components = { EaCrumbs };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const { params = {}, context = {} } = this.props.action || {};
        this.engagementId = Number(params.engagement_id || context.active_id || context.ea_engagement_id);
        this.state = useState({ p: null, tab: "uncorrected", busy: false });
        this.queue = Promise.resolve();
        useSetupAction({ beforeLeave: () => this.queue.then(() => true) });
        onWillStart(() => this.load());
    }

    get p() {
        return this.state.p;
    }

    async load() {
        this.state.p = await this.orm.call(ENGAGEMENT, "ea_sad_page", [[this.engagementId]]);
    }

    get tabs() {
        const p = this.p;
        return [
            { key: "uncorrected", label: _t("1 Uncorrected"), count: p.rows.uncorrected.length, tone: p.rows.uncorrected.length ? "amber" : "" },
            { key: "corrected", label: _t("2 Corrected"), count: p.rows.corrected.length, tone: "green" },
            { key: "disclosures", label: _t("3 Disclosures"), count: p.discRows.length, tone: "" },
            { key: "cashflow", label: _t("4 Cash flow"), count: p.cfRows.length, tone: "" },
            {
                key: "factors", label: _t("5 Other factors"), tone: p.unanswered ? "amber" : "green",
                count: p.unanswered ? _t("%s to answer", p.unanswered) : "✓",
            },
            { key: "tax", label: _t("6 Tax and conclusion"), count: false, tone: "" },
            { key: "trivial", label: _t("Clearly trivial"), count: p.rows.trivial.length, tone: "" },
        ];
    }

    get gridRows() {
        return this.p.rows[this.state.tab] || [];
    }

    get isGrid() {
        return ["uncorrected", "corrected", "trivial"].includes(this.state.tab);
    }

    setTab(key) {
        this.state.tab = key;
    }

    stop(ev) {
        ev.stopPropagation();
    }

    at(value) {
        return `left: ${value}%`;
    }

    width(value) {
        return `width: ${value}%`;
    }

    run(method, args = []) {
        const job = this.queue.then(async () => {
            this.state.busy = true;
            try {
                this.state.p = await this.orm.call(ENGAGEMENT, method, [[this.engagementId], ...args]);
            } catch (error) {
                await this.load();
                throw error;
            } finally {
                this.state.busy = false;
            }
        });
        this.queue = job.catch(() => {});
        return job;
    }

    saveMeta(field, value) {
        if (this.p.readonly) {
            return;
        }
        return this.run("ea_sad_page_meta_save", [{ [field]: value }]);
    }

    onMeta(field, ev, number = false) {
        const raw = ev.target.value;
        if (!number) {
            return this.saveMeta(field, raw || false);
        }
        const value = Number(String(raw).replace(/\s/g, "").replace(",", ".")) || 0;
        return this.saveMeta(field, value);
    }

    toggleCorrected(row, ev) {
        ev.stopPropagation();
        return this.run("ea_sad_page_entry_save", [row.id, { corrected: ev.target.checked }]);
    }

    postAll() {
        return this.run("ea_sad_post_all");
    }

    async open(method, entryId = null) {
        await this.queue;
        const action = await this.orm.call(ENGAGEMENT, "ea_sad_page_open", [[this.engagementId], method, entryId]);
        return this.action.doAction(action, { onClose: () => this.load() });
    }

    async openFinding(row, ev) {
        ev.stopPropagation();
        if (!row.sourceFindingId) {
            return;
        }
        await this.queue;
        const action = await this.orm.call(ENGAGEMENT, "action_tool_findings", [[this.engagementId]], {
            context: { ea_finding_id: row.sourceFindingId },
        });
        return this.action.doAction(action);
    }
}

registry.category("actions").add("ea_audit_tools.sad_page", SadPage);
