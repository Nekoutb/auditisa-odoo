import { Component, onWillUpdateProps, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";

function blank() {
    return { heading: "", account: "", label: "", debit: "", credit: "" };
}

/**
 * "2. Adjustment to book" (owner's mock-up of 2026-11-17, "wp-finding-sad"): lines of heading,
 * label, debit and credit, balanced, and the nature. Saving sends the entry to the summary of
 * audit differences by itself, where it waits "To review"; once a reviewer has posted it, it is
 * read-only here. Used at the bottom of a procedure's working paper and on the findings page.
 * The server checks everything again (ea_save_adjustment).
 */
export class EaAdjustment extends Component {
    static template = "ea_audit_tools.EaAdjustment";
    static props = {
        adj: Object,
        readonly: { type: Boolean, optional: true },
        onSave: Function,
        onOpenSad: { type: Function, optional: true },
    };

    setup() {
        this.state = useState({ rows: [], nature: "factual", dirty: false, busy: false });
        this.reset(this.props.adj);
        onWillUpdateProps((next) => {
            if (next.adj !== this.props.adj) {
                this.reset(next.adj);
            }
        });
    }

    reset(adj) {
        const rows = (adj.lines || []).map((line) => ({
            heading: line.heading || "", account: line.account || "", label: line.label || "",
            debit: line.debit ? String(line.debit) : "", credit: line.credit ? String(line.credit) : "",
        }));
        while (rows.length < 2) {
            rows.push(blank());
        }
        this.state.rows = rows;
        this.state.nature = adj.nature || "factual";
        this.state.dirty = false;
    }

    get editable() {
        return !this.props.readonly && !this.props.adj.posted;
    }

    get natures() {
        return [
            { key: "factual", label: _t("Factual") },
            { key: "judgmental", label: _t("Judgemental") },
            { key: "projected", label: _t("Projected") },
        ];
    }

    headingLabel(value) {
        const found = (this.props.adj.headings || []).find((h) => h.value === value);
        return found ? found.label : _t("To classify");
    }

    number(value) {
        const text = String(value || "").replace(/[\s  ]/g, "").replace(",", ".");
        if (!text) {
            return 0;
        }
        const out = Number(text);
        return Number.isFinite(out) ? out : NaN;
    }

    fmt(value) {
        return Number.isFinite(value) ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : "—";
    }

    isBlank(row) {
        return !row.heading && !row.label.trim() && !this.number(row.debit) && !this.number(row.credit);
    }

    get totals() {
        let debit = 0;
        let credit = 0;
        for (const row of this.state.rows) {
            debit += this.number(row.debit);
            credit += this.number(row.credit);
        }
        const balanced = Number.isFinite(debit) && Number.isFinite(credit) && debit > 0 && Math.abs(debit - credit) < 0.005;
        return { debit, credit, balanced };
    }

    get ready() {
        const rows = this.state.rows.filter((row) => !this.isBlank(row));
        if (!rows.length || !this.totals.balanced) {
            return false;
        }
        let debits = 0;
        let credits = 0;
        for (const row of rows) {
            const debit = this.number(row.debit);
            const credit = this.number(row.credit);
            if (!row.heading || !(debit > 0) === !(credit > 0) || debit < 0 || credit < 0) {
                return false;
            }
            debits += debit > 0 ? 1 : 0;
            credits += credit > 0 ? 1 : 0;
        }
        return debits > 0 && credits > 0;
    }

    edit(row, field, ev) {
        if (!this.editable) {
            return;
        }
        row[field] = ev.target.value;
        // one amount per line: a debit clears the credit, and the other way round
        if (field === "debit" && ev.target.value) {
            row.credit = "";
        } else if (field === "credit" && ev.target.value) {
            row.debit = "";
        }
        this.state.dirty = true;
    }

    addLine() {
        this.state.rows.push(blank());
    }

    removeLine(index) {
        this.state.rows.splice(index, 1);
        this.state.dirty = true;
    }

    setNature(key) {
        if (!this.editable) {
            return;
        }
        this.state.nature = key;
        this.state.dirty = true;
    }

    async save() {
        if (!this.editable || !this.ready || this.state.busy) {
            return;
        }
        const lines = this.state.rows.filter((row) => !this.isBlank(row)).map((row) => ({
            heading: row.heading, account: row.account, label: row.label,
            debit: this.number(row.debit) || 0, credit: this.number(row.credit) || 0,
        }));
        this.state.busy = true;
        try {
            await this.props.onSave(lines, this.state.nature);
        } finally {
            this.state.busy = false;
        }
    }
}
