import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";
import { EaCrumbs, EaDocsPane } from "./page_kit";

const ENGAGEMENT = "ea.audit.engagement";

/**
 * The findings page (owner's mock-up of 2026-11-16): the totals at the top, the stages as tabs
 * with their counts, the list coloured by severity, and the selected finding in full beside it:
 * what was found, why it matters, the recommendation, management's answer, the ISA 265
 * assessment in place and the documents. Every change goes through the server's own rules
 * (ea_findings_page_*), which answer with the whole page again.
 */
export class FindingsPage extends Component {
    static template = "ea_audit_tools.FindingsPage";
    static props = ["*"];
    static components = { EaCrumbs, EaDocsPane };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        const { params = {}, context = {} } = this.props.action || {};
        this.engagementId = Number(params.engagement_id || context.active_id || context.ea_engagement_id);
        this.state = useState({
            p: null, tab: "all", selected: Number(params.finding_id) || null, docs: [], busy: false,
            closing: "", reopening: "", extraLines: 0,
        });
        this.queue = Promise.resolve();
        useSetupAction({ beforeLeave: () => this.queue.then(() => true) });
        onWillStart(() => this.load());
    }

    get p() {
        return this.state.p;
    }

    async load() {
        this.state.p = await this.orm.call(ENGAGEMENT, "ea_findings_page", [[this.engagementId]]);
        await this.settle();
    }

    async settle() {
        const ids = this.p.findings.map((f) => f.id);
        if (!ids.includes(this.state.selected)) {
            this.state.selected = this.visible[0] ? this.visible[0].id : ids[0] || null;
        }
        await this.loadDocs();
    }

    async loadDocs() {
        this.state.docs = this.state.selected
            ? await this.orm.call(ENGAGEMENT, "ea_findings_page_documents", [[this.engagementId], this.state.selected])
            : [];
    }

    // ---- reading -------------------------------------------------------------

    get tabs() {
        const s = this.p.summary.stages;
        return [
            { key: "all", label: _t("All"), count: this.p.summary.total, tone: "" },
            { key: "raised", label: _t("1 Raised"), count: s.raised, tone: s.raised ? "amber" : "" },
            { key: "assessed", label: _t("2 Assessed (ISA 265)"), count: s.assessed, tone: s.assessed ? "amber" : "" },
            { key: "discussed", label: _t("3 Discussed with management"), count: s.discussed, tone: "" },
            { key: "reported", label: _t("4 Reported"), count: s.reported, tone: "" },
            { key: "closed", label: _t("5 Closed"), count: s.closed, tone: "green" },
        ];
    }

    get visible() {
        const all = this.p.findings;
        return this.state.tab === "all" ? all : all.filter((f) => f.stage === this.state.tab);
    }

    get current() {
        return this.p.findings.find((f) => f.id === this.state.selected) || null;
    }

    style(width) {
        return `width: ${width}%`;
    }

    async select(finding) {
        this.state.selected = finding.id;
        this.state.closing = "";
        this.state.reopening = "";
        this.state.extraLines = 0;
        await this.loadDocs();
    }

    async setTab(key) {
        this.state.tab = key;
        if (!this.visible.find((f) => f.id === this.state.selected) && this.visible.length) {
            await this.select(this.visible[0]);
        }
    }

    // ---- saving ---------------------------------------------------------------

    run(method, args) {
        const job = this.queue.then(async () => {
            this.state.busy = true;
            try {
                this.state.p = await this.orm.call(ENGAGEMENT, method, [[this.engagementId], ...args]);
                await this.settle();
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

    onText(finding, field, ev) {
        const value = ev.target.value;
        if (this.p.readonly || value === (finding[field === "management_response" ? "answer" : field] || "")) {
            return;
        }
        return this.run("ea_findings_page_save", [finding.id, { [field]: value || false }]);
    }

    evaluate(finding, field, value) {
        if (this.p.readonly || finding.evaluation[field] === value) {
            return;
        }
        return this.run("ea_findings_page_evaluate", [finding.id, { [field]: value }]);
    }

    onCommunicated(finding, field, ev) {
        return this.evaluate(finding, field, ev.target.value || false);
    }

    close(finding) {
        const response = this.state.closing.trim();
        if (!response) {
            this.notification.add(_t("Write how the finding was resolved, then close it."), { type: "warning" });
            return;
        }
        this.state.closing = "";
        return this.run("ea_findings_page_clear", [finding.id, response]);
    }

    reopen(finding) {
        const reason = this.state.reopening.trim();
        if (!reason) {
            this.notification.add(_t("Write why the finding is reopened, then reopen it."), { type: "warning" });
            return;
        }
        this.state.reopening = "";
        return this.run("ea_findings_page_reopen", [finding.id, reason]);
    }

    // ---- the adjustment of a misstatement -------------------------------------

    get natures() {
        return [
            { key: "factual", label: _t("Factual") },
            { key: "judgmental", label: _t("Judgemental") },
            { key: "projected", label: _t("Projected") },
        ];
    }

    adjRows(finding) {
        const rows = finding.adjustment.lines.map((line) => ({ ...line }));
        const blanks = this.state.extraLines || (rows.length ? 0 : 2);
        for (let i = 0; i < blanks; i++) {
            rows.push({ account: "", label: "", debit: "", credit: "" });
        }
        return rows;
    }

    amount(value) {
        return String(value || "").replace(/[^0-9.]/g, "");
    }

    saveRows(finding, rows) {
        const lines = rows.map((row) => ({
            account: row.account, label: row.label, debit: this.amount(row.debit), credit: this.amount(row.credit),
        }));
        return this.run("ea_findings_page_adjust", [finding.id, lines, null]);
    }

    editLine(finding, rows, index, field, ev) {
        if (this.p.readonly || finding.adjustment.booked) {
            return;
        }
        rows[index][field] = ev.target.value;
        // one amount per line: a debit clears the credit, and the other way round
        if (field === "debit" && ev.target.value) {
            rows[index].credit = "";
        } else if (field === "credit" && ev.target.value) {
            rows[index].debit = "";
        }
        if (index >= finding.adjustment.lines.length) {
            this.state.extraLines = Math.max(0, this.adjRows(finding).length - finding.adjustment.lines.length - 1);
        }
        return this.saveRows(finding, rows);
    }

    addLine(finding) {
        this.state.extraLines = Math.max(this.adjRows(finding).length - finding.adjustment.lines.length, 0) + 1;
    }

    removeLine(finding, rows, index) {
        if (index >= finding.adjustment.lines.length) {
            this.state.extraLines = Math.max(0, this.state.extraLines - 1);
            return;
        }
        rows.splice(index, 1);
        return this.saveRows(finding, rows);
    }

    setNature(finding, key) {
        if (this.p.readonly || finding.adjustment.booked || finding.adjustment.nature === key) {
            return;
        }
        return this.run("ea_findings_page_adjust", [finding.id, null, key]);
    }

    book(finding) {
        if (this.p.readonly || !finding.adjustment.canBook) {
            return;
        }
        this.state.extraLines = 0;
        return this.run("ea_findings_page_book", [finding.id]);
    }

    // ---- documents (the pane at the right) --------------------------------

    async upload(files) {
        const finding = this.current;
        if (!finding || this.p.readonly) {
            return;
        }
        for (const file of files) {
            await this.run("ea_findings_page_upload", [finding.id, file.name, file.content]);
        }
    }

    attachExisting(ids) {
        const finding = this.current;
        if (!finding || this.p.readonly) {
            return;
        }
        return this.run("ea_findings_page_attach", [finding.id, ids]);
    }

    remove(doc) {
        return this.run("ea_findings_page_remove", [this.current.id, doc.id]);
    }

    // ---- leaving ---------------------------------------------------------------

    async open(method, findingId = null) {
        await this.queue;
        const action = await this.orm.call(ENGAGEMENT, "ea_findings_page_open", [[this.engagementId], method, findingId]);
        return this.action.doAction(action, { onClose: () => this.load() });
    }
}

registry.category("actions").add("ea_audit_tools.findings_page", FindingsPage);
