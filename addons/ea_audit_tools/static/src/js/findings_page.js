import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";

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

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        const { params = {}, context = {} } = this.props.action || {};
        this.engagementId = Number(params.engagement_id || context.active_id || context.ea_engagement_id);
        this.state = useState({
            p: null, tab: "all", selected: Number(params.finding_id) || null, docs: [], busy: false,
            closing: "", drag: false,
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

    // ---- documents ------------------------------------------------------------

    readFile(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
            reader.onerror = () => reject(reader.error);
            reader.readAsDataURL(file);
        });
    }

    async upload(files) {
        const finding = this.current;
        if (!finding || this.p.readonly) {
            return;
        }
        for (const file of files) {
            const content = await this.readFile(file);
            await this.run("ea_findings_page_upload", [finding.id, file.name, content]);
        }
    }

    onPick(ev) {
        const files = [...(ev.target.files || [])];
        ev.target.value = "";
        return this.upload(files);
    }

    onDrop(ev) {
        ev.preventDefault();
        this.state.drag = false;
        return this.upload([...(ev.dataTransfer.files || [])]);
    }

    onDragOver(ev) {
        ev.preventDefault();
        this.state.drag = true;
    }

    onDragLeave() {
        this.state.drag = false;
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
