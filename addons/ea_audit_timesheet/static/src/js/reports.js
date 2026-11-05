import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { hours, readDate, refusal, showDate } from "./common";

const MODEL = "ea.audit.timesheet.sheet";

export class EaTimeReports extends Component {
    static template = "ea_audit_timesheet.Reports";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        // an app opened by its address leaves any mission, and no audit tab is lit
        const shell = useService("ea_audit_context").state;
        shell.mission = null;
        shell.openSection = null;
        shell.screen = "reports";
        this.action = useService("action");
        this.hours = hours;
        this.groupings = [
            { key: "person", label: _t("By person") },
            { key: "engagement", label: _t("By engagement") },
            { key: "period", label: _t("By week") },
        ];
        this.state = useState({
            data: null, from: "", to: "", error: null, notice: null,
            reopen: { user: "", day: "", reason: "" },
        });
        onWillStart(() => this.load());
    }

    get groupHeader() {
        return this.groupings.find((g) => g.key === this.state.data.group_by).label;
    }

    async load(groupBy = this.state.data?.group_by || "person") {
        const from = this.state.data ? readDate(this.state.from) : false;
        const to = this.state.data ? readDate(this.state.to) : false;
        if (this.state.data && (!from || !to)) {
            this.state.error = _t("Dates read DD/MM/YYYY.");
            return;
        }
        this.state.error = null;
        const data = await this.orm.call(MODEL, "ea_ts_report", [from, to, groupBy]);
        this.state.data = data;
        this.state.from = showDate(data.date_from);
        this.state.to = showDate(data.date_to);
    }

    async openPivot() {
        const { date_from, date_to } = this.state.data;
        const description = await this.orm.call(MODEL, "ea_ts_pivot_action", [date_from, date_to]);
        return this.action.doAction(description);
    }

    get exportUrl() {
        const { date_from, date_to } = this.state.data;
        return `/ea_audit_timesheet/export?date_from=${date_from}&date_to=${date_to}`;
    }

    async reopen() {
        const form = this.state.reopen;
        const day = readDate(form.day);
        this.state.notice = null;
        if (!form.user || !day) {
            this.state.error = _t("Choose the person and a date of the week, DD/MM/YYYY.");
            return;
        }
        this.state.error = null;
        try {
            const result = await this.orm.call(MODEL, "ea_ts_reopen", [Number(form.user), day, form.reason]);
            this.state.notice = _t("Week reopened until %(until)s.", { until: result.until });
            form.reason = "";
            await this.load();
        } catch (error) {
            this.state.error = refusal(error);
        }
    }
}

registry.category("actions").add("ea_audit_timesheet.reports", EaTimeReports);
