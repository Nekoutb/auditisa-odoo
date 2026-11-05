import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { hours, readHours, refusal } from "./common";

const MODEL = "ea.audit.team.budget";

export class EaBudget extends Component {
    static template = "ea_audit_timesheet.Budget";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.ctx = useService("ea_audit_context");
        this.hours = hours;
        this.resId = this.props.action?.params?.resId || this.props.action?.context?.active_id;
        this.state = useState({ data: null, error: null });
        onWillStart(async () => {
            await this.load();
            const mission = await this.ctx.call("ea_ui_context", "ea.audit.engagement", this.resId);
            if (mission) {
                this.ctx.enterMission(mission);
            }
        });
    }

    async load() {
        this.state.data = await this.orm.call(MODEL, "ea_ts_budget", [this.resId]);
    }

    /** Over budget reads in rose: the overrun is the figure a partner looks for. */
    over(cell) {
        return cell.budget > 0 && cell.actual > cell.budget;
    }

    async setBudget(row, cell, ev) {
        const value = readHours(ev.target.value);
        if (value === cell.budget) {
            return;
        }
        this.state.error = null;
        try {
            await this.orm.call(MODEL, "ea_ts_budget_set", [row.member_id, cell.phase, value]);
        } catch (error) {
            this.state.error = refusal(error);
        }
        await this.load();
    }

    back() {
        return this.ctx.openDashboard(this.resId);
    }
}

registry.category("actions").add("ea_audit_timesheet.budget", EaBudget);
