import { Component, onWillStart, onWillUpdateProps, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";

/**
 * One risk page (owner's mock-up of 2026-11-16): the heat map and a short summary above the
 * risk register. A square filters the register to that likelihood and magnitude; a second
 * click, or the chip, shows every risk again. The words come from the server, translated.
 */

/** The list's domain with, when a square is picked, that likelihood and magnitude. */
export function cellDomain(domain, cell) {
    if (!cell) {
        return domain;
    }
    return [...domain, ["likelihood", "=", cell.likelihood], ["magnitude", "=", cell.magnitude]];
}

export function sameCell(a, b) {
    return Boolean(a && b && a.likelihood === b.likelihood && a.magnitude === b.magnitude);
}

export class RiskHeatPanel extends Component {
    static template = "ea_audit_tools.RiskHeatPanel";
    static props = { engagementId: Number, cell: { optional: true }, onPick: Function };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ data: null });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.data = await this.orm.call("ea.audit.engagement", "ea_risk_overview", [[this.props.engagementId]]);
    }

    isOn(cell) {
        return sameCell(this.props.cell, cell);
    }

    get picked() {
        const { cell } = this.props;
        const data = this.state.data;
        if (!cell || !data) {
            return null;
        }
        const row = data.grid.find((r) => r.likelihood === cell.likelihood);
        const hit = row?.cells.find((c) => c.magnitude === cell.magnitude);
        const magnitude = data.magnitudes.find((m) => m.value === cell.magnitude);
        return hit && { likelihood: row.label, magnitude: magnitude.label, count: hit.count };
    }

    /** "Showing: Likelihood High × Magnitude High (2)" */
    get chipText() {
        const { labels } = this.state.data;
        const p = this.picked;
        return `${labels.showing} ${labels.likelihood} ${p.likelihood} × ${labels.magnitude} ${p.magnitude} (${p.count})`;
    }
}

export class RiskListController extends ListController {
    static template = "ea_audit_tools.RiskListView";
    static components = { ...ListController.components, RiskHeatPanel };

    setup() {
        super.setup();
        this.eaRisk = useState({ cell: null });
        // a new search reloads the list with its own domain: the square no longer applies
        onWillUpdateProps(() => {
            this.eaRisk.cell = null;
        });
    }

    get eaEngagementId() {
        const context = this.props.context || {};
        return context.ea_engagement_id || context.default_engagement_id || 0;
    }

    async eaPick(cell) {
        const next = sameCell(this.eaRisk.cell, cell) ? null : cell;
        this.eaRisk.cell = next;
        await this.model.load({ domain: cellDomain(this.props.domain, next) });
    }
}

registry.category("views").add("ea_risk_list", {
    ...listView,
    Controller: RiskListController,
});
