import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { ListRenderer } from "@web/views/list/list_renderer";
import { amount } from "@ea_audit_tools/js/figures";

/**
 * Significant accounts (owner's mock-up of 2026-11-16): a bar above the list sets when a
 * movement is flagged, "more than 10 % and/or more than 10 000 000 FCFA", for the whole file.
 * A writer changes it; everyone else reads it. The list reloads so the flags follow.
 */

/** "10 000 000", "10,5" or "12.5" as a person types it: spaces dropped, a comma read as a point. */
export function typedNumber(text) {
    const cleaned = String(text ?? "").replace(/[\s  ]/g, "").replace(",", ".");
    if (!/^\d+(\.\d+)?$/.test(cleaned)) {
        return null;
    }
    return Number(cleaned);
}

export class SignificanceFlagBar extends Component {
    static template = "ea_audit_tools.SignificanceFlagBar";
    static props = { engagementId: Number, reload: Function };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ loaded: false, mode: "and", pct: 10, amount: 10000000, canEdit: false, flagged: 0, source: "", busy: false });
        onWillStart(() => this.load());
    }

    async load() {
        const data = await this.orm.call("ea.audit.engagement", "ea_significance_flags", [[this.props.engagementId]]);
        Object.assign(this.state, data, { loaded: true });
    }

    get pctText() {
        return String(this.state.pct);
    }

    get amountText() {
        return amount(this.state.amount);
    }

    async save(changes) {
        if (!this.state.canEdit || this.state.busy) {
            return;
        }
        const next = { mode: this.state.mode, pct: this.state.pct, amount: this.state.amount, ...changes };
        if (next.mode === this.state.mode && next.pct === this.state.pct && next.amount === this.state.amount) {
            return;
        }
        this.state.busy = true;
        try {
            const data = await this.orm.call("ea.audit.engagement", "ea_save_significance_flags", [[this.props.engagementId], next.mode, next.pct, next.amount]);
            Object.assign(this.state, data);
            await this.props.reload();
        } finally {
            this.state.busy = false;
        }
    }

    async onPctChange(ev) {
        const value = typedNumber(ev.target.value);
        try {
            if (value !== null) {
                await this.save({ pct: value });
            }
        } finally {
            ev.target.value = this.pctText;
        }
    }

    async onAmountChange(ev) {
        const value = typedNumber(ev.target.value);
        try {
            if (value !== null) {
                await this.save({ amount: value });
            }
        } finally {
            ev.target.value = this.amountText;
        }
    }

    onKeydown(ev) {
        if (ev.key === "Enter") {
            ev.target.blur();
        }
    }
}

export class SignificanceListController extends ListController {
    static template = "ea_audit_tools.SignificanceListView";
    static components = { ...ListController.components, SignificanceFlagBar };

    get eaEngagementId() {
        const context = this.props.context || {};
        return context.ea_engagement_id || context.default_engagement_id || 0;
    }

    async eaReload() {
        await this.model.load();
    }
}

export class SignificanceListRenderer extends ListRenderer {
    getRowClass(record) {
        const classes = [super.getRowClass(record)];
        if (record.data.flagged) {
            classes.push("o_ea_flagged");
        }
        if (record.data.unjustified) {
            classes.push("o_ea_unjustified");
        }
        return classes.filter(Boolean).join(" ");
    }
}

registry.category("views").add("ea_significance_list", {
    ...listView,
    Controller: SignificanceListController,
    Renderer: SignificanceListRenderer,
});
