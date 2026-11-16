import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { amount } from "@ea_audit_tools/js/figures";

const ENGAGEMENT = "ea.audit.engagement";
const STUDIO = "ea.audit.je.studio";

/** A file read as base64, without its data: prefix. */
export function readAsBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
    });
}

/**
 * Journal entries on one page (owner's mock-up of 2026-11-16, "mock-ws-je"): the four steps
 * as tabs, each criterion with the entries it catches, the selected entries in a grid with
 * their reasons as tags, and, for the entry opened, clear it with a note, file its support or
 * raise a finding in place. The selection itself is the existing engine's (je_run_selection).
 */
export class JePage extends Component {
    static template = "ea_audit_tools.JePage";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const { params = {}, context = {} } = this.props.action || {};
        this.engagementId = Number(params.engagement_id || context.active_id || context.ea_engagement_id);
        this.studioId = Number(params.studio_id || 0) || false;
        this.state = useState({
            p: null, tab: "entries", current: null, note: "", busy: false, dragging: false,
            finding: null,
        });
        onWillStart(() => this.load());
    }

    get p() {
        return this.state.p;
    }

    async call(method, args) {
        this.state.busy = true;
        try {
            return await this.orm.call(ENGAGEMENT, method, [[this.engagementId], ...args]);
        } finally {
            this.state.busy = false;
        }
    }

    show(page) {
        this.state.p = page;
        this.studioId = page.studioId;
        if (page.missing) {
            this.state.tab = "ledger";
        }
        const still = page.entries.find((entry) => entry.je === this.state.current);
        if (!still) {
            this.state.current = page.entries.length ? page.entries[0].je : null;
            this.state.note = page.entries.length ? page.entries[0].note : "";
            this.state.finding = null;
        }
    }

    async load() {
        this.show(await this.call("ea_je_page", [this.studioId]));
    }

    // ---- reading -----------------------------------------------------------

    get entry() {
        return this.p.entries.find((entry) => entry.je === this.state.current) || null;
    }

    get progressText() {
        const { total, cleared, problems } = this.p.progress;
        return _t("%(cleared)s of %(total)s selected entries cleared · %(problems)s with a problem", { cleared, total, problems });
    }

    barStyle(kind) {
        const { total, cleared, problems } = this.p.progress;
        const share = kind === "cleared" ? cleared : problems;
        return `width: ${Math.round((100 * share) / (total || 1))}%`;
    }

    get countedOnce() {
        return _t("An entry caught by several criteria is counted once (%s in all).", this.p.selectedEntries);
    }

    get criteriaOn() {
        return this.p.criteria.filter((c) => c.on).length;
    }

    get problems() {
        return this.p.entries.filter((entry) => entry.status === "problem");
    }

    fmt(value) {
        return amount(value);
    }

    date(iso) {
        return iso ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}` : "";
    }

    statusLabel(status) {
        return { cleared: _t("Cleared"), problem: _t("Problem"), to_clear: _t("To clear") }[status];
    }

    checkLabel(status) {
        return { passed: _t("Passed"), warning: _t("To look at"), failed: _t("Failed") }[status] || status;
    }

    fileUrl(file) {
        return `/web/content/${file.id}?download=true`;
    }

    // ---- choosing ----------------------------------------------------------

    setTab(tab) {
        this.state.tab = tab;
    }

    open(entry) {
        this.state.current = entry.je;
        this.state.note = entry.note;
        this.state.finding = null;
    }

    async toggle(criterion) {
        if (this.state.busy) {
            return;
        }
        this.show(await this.call("ea_je_toggle", [this.studioId, criterion.key]));
    }

    async chooseDataset(ev) {
        this.show(await this.call("ea_je_dataset", [this.studioId, Number(ev.target.value)]));
    }

    async mark(status) {
        const entry = this.entry;
        if (!entry || this.p.readonly) {
            return;
        }
        this.show(await this.call("ea_je_review", [this.studioId, entry.je, status, this.state.note]));
    }

    startFinding() {
        const entry = this.entry;
        this.state.finding = {
            type: "b5",
            description: this.state.note || _t("Journal entry %s", entry.je),
            amount: entry.amount,
            trivial: false,
        };
    }

    async raiseFinding() {
        const entry = this.entry;
        const form = this.state.finding;
        const value = Number(String(form.amount).replace(/[\s ]/g, "").replace(",", "."));
        this.show(await this.call("ea_je_finding", [
            this.studioId, entry.je, form.description, form.type, form.type === "b5" ? value : false, form.trivial,
        ]));
        this.state.finding = null;
    }

    async attach(files) {
        const entry = this.entry;
        if (!entry || this.p.readonly) {
            return;
        }
        for (const file of files) {
            const content = await readAsBase64(file);
            this.show(await this.call("ea_je_attach", [this.studioId, entry.je, file.name, content]));
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

    // ---- leaving -----------------------------------------------------------

    async studio(method) {
        const action = await this.orm.call(STUDIO, "ea_open", [[this.studioId], method]);
        return this.action.doAction(action);
    }

    async record() {
        await this.orm.call(STUDIO, "action_record", [[this.studioId]]);
        return this.load();
    }
}

registry.category("actions").add("ea_audit_tools.je_page", JePage);
