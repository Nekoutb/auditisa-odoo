import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { amount } from "@ea_audit_tools/js/figures";
import { EaCrumbs, EaDocsPane } from "./page_kit";

const ENGAGEMENT = "ea.audit.engagement";
const RUN = "ea.audit.automation.run";

/**
 * Sampling on one page (owner's mock-up of 2026-11-16, "mock-ws-sampling"): one card per
 * sample, tests of controls and tests of details, with its five steps coloured; the items
 * tested in a grid below and the result (projected against tolerable) beside them, with what
 * to do next and the documents. Sizes, draws and the projection are the existing ones.
 */
export class SamplingPage extends Component {
    static template = "ea_audit_tools.SamplingPage";
    static props = ["*"];
    static components = { EaCrumbs, EaDocsPane };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const { params = {}, context = {} } = this.props.action || {};
        this.engagementId = Number(params.engagement_id || context.active_id || context.ea_engagement_id);
        this.state = useState({ p: null, tab: "toc", current: null, busy: false, dragging: false, purpose: "" });
        // "tod:12": the sample to open on, from the procedure design page
        this.focus = params.focus || null;
        onWillStart(() => this.load(true));
    }

    get p() {
        return this.state.p;
    }

    show(page, first = false) {
        this.state.p = page;
        if (first && !page.toc.length && page.tod.length) {
            this.state.tab = "tod";
        }
        if (first && this.focus) {
            const [kind] = this.focus.split(":");
            if (kind === "tod" || kind === "toc") {
                this.state.tab = kind;
                this.state.current = this.focus;
            }
        }
        const cards = this.cards;
        if (!cards.find((card) => this.keyOf(card) === this.state.current)) {
            this.state.current = cards.length ? this.keyOf(cards[0]) : null;
        }
        this.state.purpose = this.card ? this.card.purpose || "" : "";
    }

    async load(first = false) {
        this.show(await this.orm.call(ENGAGEMENT, "ea_sampling_page", [[this.engagementId]]), first);
    }

    async run(model, method, ids, args) {
        this.state.busy = true;
        try {
            return await this.orm.call(model, method, [ids, ...args]);
        } finally {
            this.state.busy = false;
        }
    }

    // ---- reading -----------------------------------------------------------

    keyOf(card) {
        return `${card.kind}:${card.id}`;
    }

    get cards() {
        return this.state.tab === "toc" ? this.p.toc : this.p.tod;
    }

    get card() {
        return this.cards.find((card) => this.keyOf(card) === this.state.current) || null;
    }

    get progressText() {
        const { evaluated, total, above } = this.p.progress;
        return _t("%(evaluated)s of %(total)s samples evaluated · %(above)s projected error(s) above tolerable", { evaluated, total, above });
    }

    barStyle(kind) {
        const { evaluated, total, above } = this.p.progress;
        const share = kind === "done" ? evaluated - above : above;
        return `width: ${Math.round((100 * Math.max(0, share)) / (total || 1))}%`;
    }

    stepLabel(step) {
        const names = {
            population: _t("Pop."),
            size: _t("Size"),
            draw: _t("Draw"),
            test: _t("Test"),
            result: _t("Result"),
        };
        return step.label ? `${names[step.key]} ${step.label}` : names[step.key];
    }

    measureLabel(key) {
        return {
            sample_value: _t("Sample value"),
            sample_misstatement: _t("Misstatement in the sample"),
            key_item_misstatement: _t("Key-item misstatement"),
            remaining_population: _t("Remaining population"),
        }[key] || key;
    }

    resultLabel(result) {
        return { agreed: _t("Agreed"), error: _t("Error"), to_test: _t("To test") }[result];
    }

    attributeLabel(value) {
        return { pass: _t("Pass"), fail: _t("Fail"), na: _t("Not applicable") }[value] || value || "—";
    }

    fmt(value) {
        if (value === null || value === undefined || value === false) {
            return "—";
        }
        return amount(value);
    }

    count(value) {
        return value === null || value === undefined ? "—" : value;
    }

    fileUrl(file) {
        return `/web/content/${file.id}?download=true`;
    }

    // ---- choosing ----------------------------------------------------------

    setTab(tab) {
        this.state.tab = tab;
        const cards = this.cards;
        this.state.current = cards.length ? this.keyOf(cards[0]) : null;
        this.state.purpose = this.card ? this.card.purpose || "" : "";
    }

    select(card) {
        this.state.current = this.keyOf(card);
        this.state.purpose = card.purpose || "";
    }

    async saveItem(row, field, ev) {
        const card = this.card;
        const value = ev.target.value;
        if (this.p.readonly || card.concluded) {
            return;
        }
        const before = field === "audited" ? row.audited : row[field];
        if (String(before ?? "") === value.trim()) {
            return;
        }
        try {
            this.show(await this.run(RUN, "ea_sampling_item", [card.id], [row.rowNo, { [field]: value }]));
        } catch (error) {
            await this.load();
            throw error;
        }
    }

    async savePurpose() {
        const card = this.card;
        if (this.p.readonly || !card || (card.purpose || "") === this.state.purpose.trim()) {
            return;
        }
        this.show(await this.run(RUN, "ea_sampling_purpose", [card.id], [this.state.purpose]));
    }

    async conclude() {
        this.show(await this.run(RUN, "ea_sampling_conclude", [this.card.id], []));
    }

    // the documents of the sample or control opened, in the pane at the right
    get docModel() {
        return this.card.kind === "toc" ? "ea.audit.scot.control" : RUN;
    }

    async attach(files) {
        const card = this.card;
        if (!card || this.p.readonly) {
            return;
        }
        for (const file of files) {
            await this.run(ENGAGEMENT, "ea_ws_attach", [this.engagementId], [this.docModel, card.id, file.name, file.content]);
        }
        await this.load();
    }

    async attachExisting(ids) {
        const card = this.card;
        if (!card || this.p.readonly) {
            return;
        }
        await this.run(ENGAGEMENT, "ea_ws_attach_existing", [this.engagementId], [this.docModel, card.id, ids]);
        await this.load();
    }

    // ---- leaving -----------------------------------------------------------

    async open(method, resId = null) {
        const action = await this.orm.call(ENGAGEMENT, "ea_sampling_open", [[this.engagementId], method, resId]);
        return this.action.doAction(action, { onClose: () => this.load() });
    }
}

registry.category("actions").add("ea_audit_tools.sampling_page", SamplingPage);
