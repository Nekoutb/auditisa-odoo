import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { EaAdjustment } from "./adjustment_editor";
import { EaCrumbs, EaDocsPane } from "./page_kit";

const ENGAGEMENT = "ea.audit.engagement";
// the rows drawn at once; the counts above are always over the whole selection
const SHOWN = 300;

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
 * The entries shown: those found by any ticked criterion; nothing ticked, the whole selection
 * (services/je_testing.py filter_selection, the same rule).
 */
export function filterSelection(rows, ticked) {
    const wanted = new Set(ticked || []);
    if (!wanted.size) {
        return rows;
    }
    return rows.filter((row) => row.reasons.some((key) => wanted.has(key)));
}

/**
 * Journal entry testing, one screen (owner's mock-up approved 18/11, ISA 240): the summary
 * boxes, the criteria with the entries each finds, the selected entries with the test of the
 * one opened, the findings and adjustments raised from them, and the sign-off of E3.1.
 */
export class JePage extends Component {
    static template = "ea_audit_tools.JePage";
    static props = ["*"];
    static components = { EaCrumbs, EaDocsPane, EaAdjustment };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const { params = {}, context = {} } = this.props.action || {};
        this.engagementId = Number(params.engagement_id || context.active_id || context.ea_engagement_id);
        this.state = useState({
            p: null, ticked: [], current: null, busy: false,
            test: null, finding: null, settings: null, holiday: { date: "", label: "" },
        });
        onWillStart(() => this.load());
    }

    get p() {
        return this.state.p;
    }

    async call(method, args = []) {
        this.state.busy = true;
        try {
            return await this.orm.call(ENGAGEMENT, method, [[this.engagementId], ...args]);
        } finally {
            this.state.busy = false;
        }
    }

    show(page) {
        this.state.p = page;
        if (this.state.current) {
            const row = page.rows.find((r) => r.key === this.state.current);
            if (row) {
                this.state.test = this.blankTest(row);
            } else {
                this.state.current = null;
                this.state.test = null;
            }
        }
    }

    async load() {
        this.show(await this.call("ea_jet_page"));
    }

    // ---- the criteria ------------------------------------------------------

    isTicked(key) {
        return this.state.ticked.includes(key);
    }

    tick(key) {
        const ticked = this.state.ticked;
        this.state.ticked = ticked.includes(key) ? ticked.filter((k) => k !== key) : [...ticked, key];
    }

    clearCriteria() {
        this.state.ticked = [];
    }

    get visible() {
        return filterSelection(this.p.rows, this.state.ticked);
    }

    get shown() {
        return this.visible.slice(0, SHOWN);
    }

    get moreText() {
        return _t("The list shows the first %(shown)s of %(total)s entries: tick criteria to narrow it.", {
            shown: SHOWN, total: this.visible.length,
        });
    }

    reasonName(row, key) {
        return `${this.criterionNo(key)} ${row.reasonNames[row.reasons.indexOf(key)]}`;
    }

    criterionNo(key) {
        for (const group of this.p.groups) {
            const found = group.criteria.find((c) => c.key === key);
            if (found) {
                return found.no;
            }
        }
        return "";
    }

    // ---- the settings, set once for the engagement --------------------------

    openSettings() {
        const s = this.p.settings;
        this.state.settings = {
            roundStep: String(s.roundStep), approvalLimit: String(s.approvalLimit), approvalBand: String(s.approvalBand),
            cashLimit: String(s.cashLimit), yearEndDays: String(s.yearEndDays), rarePosterShare: String(s.rarePosterShare),
            rareAccountEntries: String(s.rareAccountEntries), vagueMinChars: String(s.vagueMinChars),
            vagueWords: (s.vagueWords || []).join(", "),
            holidays: this.p.holidays.map((h) => ({ date: h.date, label: h.label, text: h.text })),
        };
        this.state.holiday = { date: "", label: "" };
    }

    number(text) {
        return Number(String(text || "").replace(/[\s  ]/g, "").replace(",", "."));
    }

    addHoliday() {
        const { date, label } = this.state.holiday;
        if (!date) {
            return;
        }
        const list = this.state.settings.holidays.filter((h) => h.date !== date);
        list.push({ date, label, text: `${date.slice(8, 10)}/${date.slice(5, 7)}/${date.slice(0, 4)}` });
        list.sort((a, b) => (a.date < b.date ? -1 : 1));
        this.state.settings.holidays = list;
        this.state.holiday = { date: "", label: "" };
    }

    removeHoliday(date) {
        this.state.settings.holidays = this.state.settings.holidays.filter((h) => h.date !== date);
    }

    async saveSettings() {
        const s = this.state.settings;
        const values = {
            roundStep: this.number(s.roundStep), approvalLimit: this.number(s.approvalLimit),
            approvalBand: this.number(s.approvalBand), cashLimit: this.number(s.cashLimit),
            yearEndDays: this.number(s.yearEndDays), rarePosterShare: this.number(s.rarePosterShare),
            rareAccountEntries: this.number(s.rareAccountEntries), vagueMinChars: this.number(s.vagueMinChars),
            vagueWords: s.vagueWords, holidays: s.holidays.map((h) => ({ date: h.date, label: h.label })),
        };
        this.show(await this.call("ea_jet_save_settings", [values]));
        this.state.settings = null;
    }

    // ---- one entry's test ---------------------------------------------------

    testOf(row) {
        return this.p.tests[row.key] || null;
    }

    blankTest(row) {
        const saved = this.testOf(row) || {};
        const test = { work: saved.work || "" };
        for (const attribute of this.p.attributes) {
            test[attribute.key] = saved[attribute.key] || "";
        }
        return test;
    }

    get row() {
        return this.p.rows.find((r) => r.key === this.state.current) || null;
    }

    get saved() {
        const row = this.row;
        return row ? this.testOf(row) : null;
    }

    open(row) {
        if (this.state.current === row.key) {
            this.state.current = null;
            this.state.test = null;
            return;
        }
        this.state.current = row.key;
        this.state.test = this.blankTest(row);
        this.state.finding = null;
    }

    async answer(key, value) {
        if (this.p.readonly) {
            return;
        }
        this.state.test[key] = value;
        await this.saveTest();
    }

    async saveTest() {
        const row = this.row;
        if (!row || this.p.readonly) {
            return;
        }
        const answers = {};
        for (const attribute of this.p.attributes) {
            answers[attribute.key] = this.state.test[attribute.key] || false;
        }
        this.show(await this.call("ea_jet_save_test", [row.key, answers, this.state.test.work]));
    }

    statusLabel(status) {
        return this.p.statusLabels[status] || status;
    }

    startFinding() {
        const row = this.row;
        this.state.finding = {
            type: "misstatement",
            description: this.state.test.work || _t("Journal entry %s", row.je),
            amount: String(row.amount),
            trivial: false,
        };
    }

    async raiseFinding() {
        const row = this.row;
        const form = this.state.finding;
        this.show(await this.call("ea_jet_finding", [
            row.key, form.description, form.type, form.type === "misstatement" ? this.number(form.amount) : false, form.trivial,
        ]));
        this.state.finding = null;
    }

    async startAdjustment() {
        this.show(await this.call("ea_jet_adjustment_start", [this.row.key]));
    }

    async saveAdjustment(lines, nature) {
        this.show(await this.call("ea_jet_adjust", [this.row.key, lines, nature]));
    }

    async attach(files) {
        const row = this.row;
        if (!row || this.p.readonly) {
            return;
        }
        for (const file of files) {
            this.show(await this.call("ea_jet_attach", [row.key, file.name, file.content]));
        }
    }

    async attachExisting(ids) {
        const row = this.row;
        if (!row || this.p.readonly) {
            return;
        }
        this.show(await this.call("ea_jet_attach_existing", [row.key, ids]));
    }

    // ---- leaving and signing ------------------------------------------------

    async exportSelection() {
        const action = await this.call("ea_jet_export_action", [this.state.ticked]);
        return this.action.doAction(action);
    }

    async openLedgers() {
        const action = await this.call("action_tool_gl");
        return this.action.doAction(action);
    }

    async sign(chip) {
        if (chip.state !== "open") {
            return;
        }
        this.show(await this.call("ea_jet_sign", [chip.role]));
    }

    signLabel(chip) {
        return chip.role === "preparer" ? _t("Sign as preparer") : _t("Sign as reviewer");
    }

    signedText(chip) {
        return _t("Signed by %(name)s on %(date)s", { name: chip.by, date: chip.date });
    }
}

registry.category("actions").add("ea_audit_tools.je_page", JePage);
