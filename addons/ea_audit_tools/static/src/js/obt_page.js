import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";
import { EaCrumbs, EaDocsPane } from "./page_kit";

const ENGAGEMENT = "ea.audit.engagement";

/**
 * Opening Balance Testing (owner's mock-ups "obt" v4, 20/11/2026): upload the prior-year financial
 * statements, check what AuditISA read (or type the figures), then the comparison with the trial
 * balance's opening balances and the differences for appreciation. Every change goes through the
 * server (ea_obt_*), which answers with the whole page again; every word comes from it or this
 * template, already translated.
 */
export class ObtPage extends Component {
    static template = "ea_audit_tools.ObtPage";
    static props = ["*"];
    static components = { EaCrumbs, EaDocsPane };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const { params = {}, context = {} } = this.props.action || {};
        this.engagementId = Number(params.engagement_id || context.active_id || context.ea_engagement_id);
        this.state = useState({ p: null, busy: false, showEmpty: false });
        this.queue = Promise.resolve();
        useSetupAction({ beforeLeave: () => this.queue.then(() => true) });
        onWillStart(() => this.load());
    }

    get p() {
        return this.state.p;
    }

    get paneTitle() {
        return _t("Prior-year financial statements");
    }

    get paneHint() {
        return _t("PDF, or photos / scans (JPG, PNG), one or several pages.");
    }

    get paneEmpty() {
        return _t("No statement uploaded yet.");
    }

    get docs() {
        return (this.p?.files || []).map((file) => ({
            id: file.id, name: file.name, url: file.url, ext: file.ext, by: file.by, date: file.date,
        }));
    }

    get checkRows() {
        const rows = this.p?.check?.rows || [];
        return this.state.showEmpty ? rows : rows.filter((row) => row.kind !== "line" || row.amount !== null);
    }

    async load() {
        this.state.p = await this.orm.call(ENGAGEMENT, "ea_obt_page", [[this.engagementId]]);
    }

    run(method, args = []) {
        const job = this.queue.then(async () => {
            this.state.busy = true;
            try {
                this.state.p = await this.orm.call(ENGAGEMENT, method, [[this.engagementId], ...args]);
            } catch (error) {
                // what is on the screen must be what is saved
                await this.load();
                throw error;
            } finally {
                this.state.busy = false;
            }
        });
        this.queue = job.catch(() => {});
        return job;
    }

    upload(files) {
        return this.run("ea_obt_upload", [files]);
    }

    remove(doc) {
        return this.run("ea_obt_remove_file", [doc.id]);
    }

    onMeta(field, ev) {
        const value = ev.target.type === "checkbox" ? ev.target.checked : ev.target.value;
        return this.run("ea_obt_meta", [{ [field]: value }]);
    }

    read() {
        return this.run("ea_obt_read");
    }

    byHand() {
        return this.run("ea_obt_by_hand");
    }

    onAmount(row, ev) {
        const raw = String(ev.target.value || "").replace(/[\s  ]/g, "").replace(/\((.*)\)/, "-$1");
        const text = raw.includes(",") && !raw.includes(".") ? raw.replace(",", ".") : raw.replace(/,/g, "");
        const value = text === "" ? null : Number(text);
        if (value !== null && Number.isNaN(value)) {
            ev.target.value = row.text;
            return;
        }
        if (value === row.amount) {
            return;
        }
        return this.run("ea_obt_set", [row.ref, value]);
    }

    confirm() {
        return this.run("ea_obt_confirm");
    }

    change() {
        return this.run("ea_obt_change");
    }

    backToCheck() {
        return this.run("ea_obt_back_to_check");
    }

    toggleEmpty() {
        this.state.showEmpty = !this.state.showEmpty;
    }

    onAppreciation(row, ev) {
        const value = ev.target.value;
        if (this.p.readonly || value === row.appreciation) {
            return;
        }
        return this.run("ea_obt_appreciate", [row.ref, value]);
    }

    place(item, ev) {
        if (ev.target.value) {
            return this.run("ea_obt_place", [item.account, ev.target.value]);
        }
    }

    download(url) {
        if (url) {
            return this.action.doAction({ type: "ir.actions.act_url", url, target: "self" });
        }
    }

    async open(target, value) {
        await this.queue;
        const action = await this.orm.call(ENGAGEMENT, "ea_obt_open", [[this.engagementId], target, value || false]);
        return this.action.doAction(action, { onClose: () => this.load() });
    }
}

registry.category("actions").add("ea_audit_tools.obt_page", ObtPage);
