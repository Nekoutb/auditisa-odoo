import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";
import { amount } from "@ea_audit_tools/js/figures";
import { EaCrumbs, EaDocsPane } from "./page_kit";

const ENGAGEMENT = "ea.audit.engagement";

const STATE_WORDS = {
    done: () => _t("Done"),
    started: () => _t("In progress"),
    draft: () => _t("Not started"),
};

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
    static components = { EaCrumbs };

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
        return { done: "is-good", started: "is-warn" }[account.state] || "is-open";
    }

    barStyle(account) {
        const share = account.total ? Math.round((100 * account.done) / account.total) : 0;
        return `width: ${share}%;`;
    }

    openAccount(account) {
        // an account with no procedure yet opens Procedure design, where they are chosen
        return account.total ? this.open("account", account.code) : this.open("action_tool_dsp");
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
    static components = { EaCrumbs, EaDocsPane };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const { params = {}, context = {} } = this.props.action || {};
        this.engagementId = Number(params.engagement_id || context.active_id || context.ea_engagement_id);
        this.procId = Number(params.procedure_id);
        this.state = useState({
            p: null, busy: false, dragging: false, note: "", days: "", threshold: "", showAll: false,
            finding: null, party: "", book: "", farText: "", countSize: "15", floorItem: "", floorLocation: "",
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
        // every list the page reads is there, even from an older server (the "Oops" of F-M1, 2026-11-16)
        page.tabs = page.tabs || [];
        page.steps = page.steps || [];
        page.samples = page.samples || [];
        page.findings = page.findings || [];
        page.evidence = page.evidence || [];
        page.assertions = page.assertions || [];
        page.mtypes = page.mtypes || [];
        page.misstatements = page.misstatements || { count: 0, total: 0 };
        page.toTick = page.toTick || { steps: 0, items: 0, explain: false };
        this.state.p = page;
        this.state.note = page.note || "";
        this.state.farText = page.far ? page.far.explanation || "" : "";
        if (page.count && page.count.size) {
            this.state.countSize = String(page.count.size);
        }
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
        const { steps, items, explain } = this.p.toTick;
        if (explain) {
            return _t("Explain the difference with the general ledger");
        }
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

    // ---- tabs ------------------------------------------------------------------

    get tabsDone() {
        return this.p.tabs.filter((tab) => tab.state === "done").length;
    }

    get ownLabel() {
        return _t("Own");
    }

    tabTip(tab) {
        const word = STATE_WORDS[tab.state];
        return `${tab.code} ${tab.title}\n${kindTip(tab.kind)}\n${word ? word() : ""}`;
    }

    async switchTab(tab) {
        if (tab.id === this.procId) {
            return;
        }
        await this.queue;
        this.procId = tab.id;
        this.state.finding = null;
        this.state.showAll = false;
        this.state.party = "";
        this.state.book = "";
        await this.load();
    }

    // ---- figures -----------------------------------------------------------------

    cell(value) {
        return value === null || value === undefined ? "—" : this.fmt(value);
    }

    qty(value) {
        if (value === null || value === undefined || value === "") {
            return "—";
        }
        return value < 0 ? `(${Math.abs(value)})` : String(value);
    }

    numText(value) {
        return value === null || value === undefined ? "" : String(value);
    }

    // ---- K-M1 ----------------------------------------------------------------------

    gapText(gap) {
        return _t("%(label)s: the register differs from the ledger by %(amount)s. Explain the difference below, or raise a finding.", {
            label: gap.label || _t("Ledger accounts not in the register"), amount: this.fmt(gap.difference),
        });
    }

    movedText(gap) {
        return _t("%(label)s: opening + additions − disposals − depreciation differs from the closing value by %(amount)s.", {
            label: gap.label, amount: this.fmt(gap.difference),
        });
    }

    saveFar() {
        if (!this.editable || (this.p.far.explanation || "") === this.state.farText.trim()) {
            return;
        }
        return this.call("ea_proc_far", [this.state.farText]);
    }

    // ---- F-M1 ----------------------------------------------------------------------

    get countPhases() {
        return [
            { key: "before", label: _t("Before the count"), checks: [
                { key: "before.instructions", label: _t("Count instructions obtained and assessed") },
                { key: "before.teams", label: _t("Locations, teams and segregation planned") },
                { key: "before.numbers", label: _t("Last delivery and receipt numbers before the count noted") },
                { key: "before.special", label: _t("Slow, damaged and third-party stock identified") },
            ] },
            { key: "during", label: _t("During the count"), checks: [
                { key: "during.follow", label: _t("Counters follow the instructions") },
                { key: "during.testcounts", label: _t("Test counts: sheet to floor (existence) and floor to sheet (completeness), samples below") },
                { key: "during.sheets", label: _t("Count sheets controlled (numbered, all returned)") },
            ] },
            { key: "after", label: _t("After the count"), checks: [
                { key: "after.agree", label: _t("Our test counts agree to the final listing") },
                { key: "after.cutoff", label: _t("Cut-off documents traced to the ledger") },
                { key: "after.rollforward", label: _t("Count date different from the year end: roll-forward or roll-back to the year end") },
            ] },
        ];
    }

    get notePlaceholder() {
        return _t("Notes: document numbers, who was met, what was seen");
    }

    countClass(state) {
        return { ok: "is-good", diff: "is-bad", missing: "is-warn" }[state] || "is-open";
    }

    countStateText(state) {
        return {
            ok: _t("Agrees"),
            diff: _t("Difference"),
            missing: _t("Not on the sheets"),
            todo: _t("To count"),
        }[state] || "";
    }

    countCheck(key, done) {
        return this.call("ea_proc_count", ["check", key, { done }]);
    }

    countNote(phase, text) {
        return this.call("ea_proc_count", ["note", phase, { text }]);
    }

    drawCount() {
        return this.call("ea_proc_count", ["draw", null, { size: this.state.countSize }]);
    }

    countItem(item, field, value) {
        return this.call("ea_proc_count", ["item", item.key, { [field]: value }]);
    }

    async floorAdd() {
        const item = this.state.floorItem.trim();
        if (!item) {
            return;
        }
        await this.call("ea_proc_count", ["floor_add", null, { item, location: this.state.floorLocation.trim() }]);
        this.state.floorItem = "";
        this.state.floorLocation = "";
    }

    floorSave(item, field, value) {
        return this.call("ea_proc_count", ["floor_update", item.index, { [field]: value }]);
    }

    floorRemove(item) {
        return this.call("ea_proc_count", ["floor_remove", item.index, null]);
    }

    saveRoll(field, value) {
        return this.call("ea_proc_count", ["roll", null, { [field]: value }]);
    }

    offerCountFinding(item, side) {
        const label = side === "count" ? `${item.label || ""} ${item.item ? `(${item.item})` : ""}`.trim() : item.item;
        const text = item.state === "missing"
            ? _t("%(item)s: %(counted)s counted on the floor, not on the count sheets", { item: label, counted: this.qty(item.counted) })
            : _t("%(item)s: %(sheet)s per the count sheets, %(counted)s counted", { item: label, sheet: this.qty(item.sheet), counted: this.qty(item.counted) });
        const key = side === "count" ? `count:${item.key}` : `floor:${item.index}`;
        this.state.finding = { ...this.blankFinding(), description: text, itemKey: key };
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
        this.state.finding = { ...this.blankFinding(), description: text, amount: String(item.amount), itemKey: item.key };
    }

    sampleItem(sample, row, field, value) {
        return this.call("ea_proc_sample_item", [sample.id, row.rowNo, { [field]: value }]);
    }

    // ---- confirmations -------------------------------------------------------------

    get confirmEditable() {
        return Boolean(this.editable && this.p.confirm && this.p.confirm.editable);
    }

    pickParties() {
        return this.call("ea_proc_confirm", ["pick", null, null]);
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

    // the evidence of the procedure, in the pane at the right
    async attach(files) {
        if (!this.editable) {
            return;
        }
        for (const file of files) {
            await this.call("ea_proc_upload", [file.name, file.content]);
        }
    }

    attachExisting(ids) {
        if (!this.editable) {
            return;
        }
        return this.call("ea_proc_attach_existing", [ids]);
    }

    removeFile(file) {
        return this.call("ea_proc_remove_file", [file.id]);
    }

    // ---- findings ------------------------------------------------------------------

    blankFinding() {
        return { description: "", amount: "", type: "misstatement", trivial: false, itemKey: null, dr: "", cr: "", mtype: "factual" };
    }

    startFinding() {
        this.state.finding = this.blankFinding();
    }

    get findingReady() {
        const f = this.state.finding;
        if (!f || !f.description.trim()) {
            return false;
        }
        // a misstatement reaches the summary with its accounts: one of the two at least
        return f.type !== "misstatement" || Boolean(f.amount && (f.dr.trim() || f.cr.trim()));
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
        const misstatement = f.type === "misstatement";
        await this.call("ea_proc_finding", [
            f.description, misstatement ? f.amount : null, f.type, Boolean(f.trivial), f.itemKey, null,
            misstatement ? f.dr.trim() : null, misstatement ? f.cr.trim() : null, misstatement ? f.mtype : "factual",
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
