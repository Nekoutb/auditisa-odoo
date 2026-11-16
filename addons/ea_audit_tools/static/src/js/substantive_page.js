import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";
import { amount } from "@ea_audit_tools/js/figures";
import { readAsBase64 } from "@ea_audit_tools/js/je_page";

const ENGAGEMENT = "ea.audit.engagement";

function kindTip(kind) {
    if (kind === "MSP") {
        return _t("Mandatory substantive procedure: must be performed for this assertion");
    }
    if (kind === "ASP") {
        return _t("Alternative substantive procedure: chosen at design for the risk");
    }
    return _t("Own procedure: written by the team for this account");
}

/**
 * "Substantive procedures" (owner's mock-up of 2026-11-16, "mock-proc-exec-overview"): only the
 * procedures selected in Procedure design, one card per account with its progress. An account
 * whose design is not finished (High risk without an alternative) is flagged. A click on a
 * procedure opens its working paper.
 */
export class SubstantivePage extends Component {
    static template = "ea_audit_tools.SubstantivePage";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const { params = {}, context = {} } = this.props.action || {};
        this.engagementId = Number(params.engagement_id || context.active_id || context.ea_engagement_id);
        this.state = useState({ p: null });
        onWillStart(() => this.load());
    }

    get p() {
        return this.state.p;
    }

    async load() {
        this.state.p = await this.orm.call(ENGAGEMENT, "ea_substantive_page", [[this.engagementId]]);
    }

    chipClass(chip) {
        return { done: "is-done", started: "is-warn" }[chip.state] || "is-open";
    }

    chipTip(chip) {
        return `${chip.title}\n${kindTip(chip.kind)}`;
    }

    cardClass(account) {
        if (account.missing.length) {
            return "is-bad";
        }
        return account.ready ? "is-good" : "is-warn";
    }

    missingText(account) {
        return _t("%s High: choose at least one alternative", account.missing.join(", "));
    }

    exportUrl() {
        return `/ea_audit_tools/export/substantive/${this.engagementId}`;
    }

    async open(method, resId = null) {
        const action = await this.orm.call(ENGAGEMENT, "ea_exec_open", [[this.engagementId], method, resId]);
        return this.action.doAction(action);
    }
}

/**
 * The working paper of one designed procedure (owner's mock-ups "mock-proc-exec-recon",
 * "-cutoff", "-manual"): its steps, the sample or the tool's work, the evidence, the conclusion
 * and the findings raised from it. Every change goes through a guarded server method, which
 * answers with the page read again.
 */
export class ProcedurePaper extends Component {
    static template = "ea_audit_tools.ProcedurePaper";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const { params = {}, context = {} } = this.props.action || {};
        this.engagementId = Number(params.engagement_id || context.active_id || context.ea_engagement_id);
        this.procId = Number(params.procedure_id);
        this.state = useState({
            p: null, busy: false, dragging: false, note: "", days: "", threshold: "", showAll: false,
            finding: null, party: "", book: "",
        });
        this.queue = Promise.resolve();
        useSetupAction({ beforeLeave: () => this.queue.then(() => true) });
        onWillStart(() => this.load());
    }

    get p() {
        return this.state.p;
    }

    get editable() {
        return this.p && !this.p.readonly && !this.p.locked;
    }

    show(page) {
        this.state.p = page;
        this.state.note = page.note || "";
        if (page.selection) {
            this.state.days = String(page.selection.days ?? "");
            this.state.threshold = page.selection.threshold === null || page.selection.threshold === undefined ? "" : String(page.selection.threshold);
        }
    }

    async load() {
        this.show(await this.orm.call(ENGAGEMENT, "ea_procedure_paper", [[this.engagementId], this.procId]));
    }

    call(method, args) {
        const run = this.queue.then(async () => {
            this.state.busy = true;
            try {
                this.show(await this.orm.call(ENGAGEMENT, method, [[this.engagementId], this.procId, ...args]));
            } catch (error) {
                await this.load();
                throw error;
            } finally {
                this.state.busy = false;
            }
        });
        this.queue = run.catch(() => {});
        return run;
    }

    // ---- reading -------------------------------------------------------------

    fmt(value) {
        return amount(value);
    }

    get kindTip() {
        return kindTip(this.p.kind);
    }

    get kindLabel() {
        return { MSP: _t("Mandatory"), ASP: _t("Alternative") }[this.p.kind] || _t("Own procedure");
    }

    get stepsDone() {
        return this.p.steps.filter((step) => step.done).length;
    }

    get leftText() {
        const { steps, items } = this.p.toTick;
        if (items) {
            return _t("%s items still to tick", items);
        }
        if (steps) {
            return _t("%s step(s) still to tick", steps);
        }
        if (!this.p.conclusion || !this.state.note.trim()) {
            return _t("Choose a result and write the conclusion");
        }
        return "";
    }

    get canMarkDone() {
        return this.editable && !this.leftText && !this.state.busy;
    }

    reconStateText(recon) {
        return {
            "no-gl": _t("Data missing: no trial balance and no general ledger for the year. Upload one to compare."),
            "no-subledger": _t("Data missing: the sub-ledger of the year is not uploaded yet."),
            agrees: _t("The sub-ledger agrees with the general ledger."),
            explained: _t("The difference is explained."),
            difference: _t("Part of the difference is not explained yet."),
        }[recon.state];
    }

    sideLabel(side) {
        return side === "before" ? _t("Before") : _t("After");
    }

    statusClass(state) {
        return {
            agrees: "is-good", explained: "is-good", difference: "is-bad", alternative: "is-warn", waiting: "is-open",
        }[state] || "is-open";
    }

    confirmStateText(state) {
        return {
            agrees: _t("Agrees"),
            explained: _t("Difference explained"),
            difference: _t("Difference not explained"),
            alternative: _t("No reply: perform alternative procedures (payments after year end, invoices, delivery notes)"),
            waiting: _t("Waiting for the reply"),
        }[state] || "";
    }

    resultLabel(result) {
        return { agreed: _t("Agreed"), error: _t("Error"), to_test: _t("To test") }[result] || "";
    }

    get visibleItems() {
        const items = this.p.selection ? this.p.selection.items : [];
        return this.state.showAll ? items : items.slice(0, 12);
    }

    // ---- steps, conclusion -----------------------------------------------------

    tick(step) {
        if (!this.editable) {
            return;
        }
        return this.call("ea_proc_step", [step.index, !step.done]);
    }

    setResult(value) {
        if (!this.editable || this.p.conclusion === value) {
            return;
        }
        return this.call("ea_proc_save", [{ conclusion: value }]);
    }

    saveNote() {
        if (!this.editable || (this.p.note || "") === this.state.note.trim()) {
            return;
        }
        return this.call("ea_proc_save", [{ note: this.state.note }]);
    }

    async markDone() {
        await this.saveNote();
        return this.call("ea_proc_done", []);
    }

    reopen() {
        return this.call("ea_proc_reopen", []);
    }

    // ---- reconciliation --------------------------------------------------------

    addExplanation() {
        return this.call("ea_proc_explain", ["add", null, { text: "", amount: 0 }]);
    }

    saveExplanation(index, field, value) {
        return this.call("ea_proc_explain", ["update", index, { [field]: value }]);
    }

    removeExplanation(index) {
        return this.call("ea_proc_explain", ["remove", index, null]);
    }

    // ---- selections --------------------------------------------------------------

    select() {
        return this.call("ea_proc_select", [this.state.days, this.state.threshold]);
    }

    async answer(item, field, value) {
        await this.call("ea_proc_select_item", [item.key, { [field]: value }]);
        if (field === "period" && value === "no" && !item.finding) {
            this.offerFinding(item);
        }
    }

    offerFinding(item) {
        const text = _t("Entry %(entry)s of %(date)s (%(amount)s) is recorded in the wrong period", {
            entry: item.entry, date: item.date, amount: this.fmt(item.amount),
        });
        this.state.finding = { description: text, amount: String(item.amount), type: "misstatement", trivial: false, itemKey: item.key };
    }

    sampleItem(sample, row, field, value) {
        return this.call("ea_proc_sample_item", [sample.id, row.rowNo, { [field]: value }]);
    }

    // ---- confirmations -------------------------------------------------------------

    enableConfirm() {
        return this.call("ea_proc_confirm", ["enable", null, null]);
    }

    async addRequest() {
        const party = this.state.party.trim();
        if (!party) {
            return;
        }
        const values = { party };
        if (this.state.book.trim()) {
            values.book = this.state.book;
        }
        await this.call("ea_proc_confirm", ["add", null, values]);
        this.state.party = "";
        this.state.book = "";
    }

    saveRequest(row, field, value) {
        return this.call("ea_proc_confirm", ["update", row.id, { [field]: value }]);
    }

    removeRequest(row) {
        return this.call("ea_proc_confirm", ["remove", row.id, null]);
    }

    requestFinding(row) {
        return this.call("ea_proc_confirm_finding", [row.id]);
    }

    // ---- evidence ------------------------------------------------------------------

    downloadUrl(attachmentId) {
        return `/web/content/${attachmentId}?download=true`;
    }

    async attach(files) {
        if (!this.editable) {
            return;
        }
        for (const file of files) {
            const content = await readAsBase64(file);
            await this.call("ea_proc_upload", [file.name, content]);
        }
    }

    onFiles(ev) {
        const files = [...ev.target.files];
        ev.target.value = "";
        return this.attach(files);
    }

    onDrop(ev) {
        ev.preventDefault();
        this.state.dragging = false;
        return this.attach([...(ev.dataTransfer?.files || [])]);
    }

    onDragOver(ev) {
        ev.preventDefault();
        this.state.dragging = true;
    }

    removeFile(file) {
        return this.call("ea_proc_remove_file", [file.id]);
    }

    // ---- findings ------------------------------------------------------------------

    startFinding() {
        this.state.finding = { description: "", amount: "", type: "misstatement", trivial: false, itemKey: null };
    }

    get findingBelowTrivial() {
        const f = this.state.finding;
        if (!f || f.type !== "misstatement" || !this.p.trivial) {
            return false;
        }
        const value = Math.abs(Number(String(f.amount).replace(/\s/g, "").replace(",", ".")) || 0);
        return value > 0 && value < this.p.trivial;
    }

    async addFinding() {
        const f = this.state.finding;
        await this.call("ea_proc_finding", [
            f.description, f.type === "misstatement" ? f.amount : null, f.type, Boolean(f.trivial), f.itemKey, null,
        ]);
        this.state.finding = null;
    }

    // ---- leaving -------------------------------------------------------------------

    async open(method, resId = null) {
        await this.queue;
        const action = await this.orm.call(ENGAGEMENT, "ea_exec_open", [[this.engagementId], method, resId]);
        return this.action.doAction(action, { onClose: () => this.load() });
    }
}

registry.category("actions").add("ea_audit_tools.substantive_page", SubstantivePage);
registry.category("actions").add("ea_audit_tools.procedure_paper", ProcedurePaper);
