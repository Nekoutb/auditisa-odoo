import { Component, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * EAGLA, results first (owner's mock-up "eagla-results-first", 18/11/2026). Every word shown here
 * comes from the server already translated (eagla_nav, analytic_items): these widgets only lay out.
 */
const MODEL = "ea.audit.gl.console";

/** The left pane: four lines, a click rolls one down, a second click rolls it up. */
export class EaEaglaNav extends Component {
    static template = "ea_audit_tools.EaEaglaNav";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ open: this.props.record.data.pane === "scot" ? "scot" : "analyses" });
    }

    get nav() {
        return this.props.record.data[this.props.name] || {};
    }

    get analysisList() {
        return this.nav.analysisList || [];
    }

    get scotList() {
        return this.nav.scotList || [];
    }

    isAnalysis(key) {
        const data = this.props.record.data;
        return data.pane === "analyses" && data.analytic_key === key;
    }

    isScot(key) {
        const data = this.props.record.data;
        return data.pane === "scot" && data.scot_class === key;
    }

    toggle(line) {
        this.state.open = this.state.open === line ? "" : line;
    }

    /** Picking an analysis runs it: the server works it out again as the record changes. */
    async pick(key) {
        if (!this.isAnalysis(key)) {
            await this.props.record.update({ analytic_key: key });
        }
    }

    /** Financial analysis and Analytical procedures open their own screens, as before. */
    async openScreen(method) {
        await this.props.record.save();
        const action = await this.orm.call(MODEL, method, [[this.props.record.resId]]);
        if (action) {
            await this.action.doAction(action);
        }
    }

    async scot(key) {
        await this.props.record.save();
        await this.orm.call(MODEL, "action_scot", [[this.props.record.resId]], { context: { ea_scot_class: key } });
        await this.props.record.model.load();
    }
}

registry.category("fields").add("ea_eagla_nav", { component: EaEaglaNav, supportedTypes: ["json"] });

/**
 * An analysis whose result is a list of entries or lines: tick them for testing, look at an entry's
 * lines in place, extract the ticked ones or all of them. What is ticked lives in analytic_ticked,
 * by analysis, for as long as the screen is open.
 */
export class EaEaglaItems extends Component {
    static template = "ea_audit_tools.EaEaglaItems";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ open: {}, lines: {} });
    }

    get items() {
        return this.props.record.data[this.props.name] || { rows: [], columns: [], lineColumns: [], labels: {} };
    }

    get isEntry() {
        return this.items.kind === "entry";
    }

    get ticked() {
        const all = this.props.record.data.analytic_ticked || {};
        return all[this.items.analysis] || [];
    }

    /** The ticked rows among those listed now (a changed setting can list other rows). */
    get tickedCount() {
        const ticked = new Set(this.ticked);
        return this.items.rows.filter((row) => ticked.has(row.key)).length;
    }

    get counter() {
        return (this.items.labels.counter || "")
            .replace("%(ticked)s", this.tickedCount)
            .replace("%(total)s", this.items.rows.length);
    }

    get extractLabel() {
        return (this.items.labels.extractSelection || "").replace("%(count)s", this.tickedCount);
    }

    isTicked(row) {
        return this.ticked.includes(row.key);
    }

    isOpen(row) {
        return !!this.state.open[row.key];
    }

    linesOf(row) {
        return this.state.lines[row.je] || [];
    }

    async setTicked(keys) {
        const all = Object.assign({}, this.props.record.data.analytic_ticked || {});
        all[this.items.analysis] = keys;
        await this.props.record.update({ analytic_ticked: all });
    }

    toggleRow(row) {
        const keys = this.ticked.filter((key) => key !== row.key);
        if (!this.isTicked(row)) {
            keys.push(row.key);
        }
        return this.setTicked(keys);
    }

    tickAll() {
        return this.setTicked(this.items.rows.map((row) => row.key));
    }

    untickAll() {
        return this.setTicked([]);
    }

    async toggleLines(row) {
        if (this.isOpen(row)) {
            this.state.open[row.key] = false;
            return;
        }
        if (!(row.je in this.state.lines)) {
            await this.props.record.save();
            this.state.lines[row.je] = await this.orm.call(MODEL, "eagla_entry_lines", [[this.props.record.resId], row.je]);
        }
        this.state.open[row.key] = true;
    }

    async download(method) {
        await this.props.record.save();
        const action = await this.orm.call(MODEL, method, [[this.props.record.resId]]);
        if (action) {
            await this.action.doAction(action);
        }
    }

    extractSelection() {
        if (this.tickedCount) {
            return this.download("action_export_selection");
        }
    }

    extractAll() {
        return this.download("action_export_analytic");
    }
}

registry.category("fields").add("ea_eagla_items", { component: EaEaglaItems, supportedTypes: ["json"] });
