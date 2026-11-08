import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { hours, readHours, refusal, showDate } from "./common";

const MODEL = "ea.audit.timesheet.sheet";

export class EaTimesheet extends Component {
    static template = "ea_audit_timesheet.Sheet";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        // an app opened by its address leaves any mission, and no audit tab is lit
        const shell = useService("ea_audit_context").state;
        // opened from an engagement (its gear, its form, the top bar): that engagement comes chosen
        const from = this.props.action?.params?.resId || this.props.action?.context?.active_id || shell.fromMission;
        this.fromEngagement = from ? Number(from) : null;
        shell.fromMission = null;
        shell.mission = null;
        shell.openSection = null;
        shell.screen = "timesheet";
        this.action = useService("action");
        this.ctx = useService("ea_audit_context");
        this.hours = hours;
        this.showDate = showDate;
        this.state = useState({
            data: null,
            error: null,
            notice: null,
            form: { day: "", project: "", task: "", hours: "", note: "" },
        });
        onWillStart(() => this.load(this.props.action?.params?.day || false));
    }

    get data() {
        return this.state.data;
    }

    get tasks() {
        const project = this.data.projects.find((p) => String(p.id) === this.state.form.project);
        return project ? project.tasks : [];
    }

    get missions() {
        return this.data.projects.filter((p) => p.kind === "mission");
    }

    /** The select's own value is set before its options exist: each option says whether it is the one. */
    isChosen(project) {
        return String(project.id) === this.state.form.project;
    }

    get internal() {
        return this.data.projects.filter((p) => p.kind === "internal");
    }

    get selectableDays() {
        return this.data.days.filter((day) => !day.future);
    }

    get statusClass() {
        return `ea-ts-pill ea-ts-${this.data.status}`;
    }

    get deadlineLine() {
        return _t("Deadline: %(deadline)s, Douala time", { deadline: this.data.deadline_label });
    }

    get reopenLine() {
        return _t("Reopened until %(until)s. Reason: %(reason)s", this.data.reopen);
    }

    get submittedLine() {
        return _t("Submitted on %(at)s", { at: this.data.submitted_at });
    }

    overdueLine(row) {
        return _t("%(week)s, %(hours)s h entered", { week: row.label, hours: hours(row.hours) });
    }

    async load(day) {
        this.state.data = await this.orm.call(MODEL, "ea_ts_sheet", [day]);
        const form = this.state.form;
        const days = this.selectableDays.map((d) => d.date);
        if (!days.includes(form.day)) {
            form.day = days.includes(this.data.today) ? this.data.today : days[days.length - 1] || "";
        }
        if (this.fromEngagement) {
            const project = this.data.projects.find((p) => p.engagement_id === this.fromEngagement);
            if (project) {
                form.project = String(project.id);
                form.task = "";
            }
            this.fromEngagement = null;
        }
    }

    async run(work, notice = null) {
        this.state.error = null;
        this.state.notice = null;
        try {
            await work();
            this.state.notice = notice;
        } catch (error) {
            this.state.error = refusal(error);
        }
        await this.load(this.data.monday);
    }

    onProject() {
        this.state.form.task = "";
    }

    charge() {
        const form = this.state.form;
        if (!form.project) {
            this.state.error = _t("Choose an engagement or a project.");
            return;
        }
        const value = readHours(form.hours);
        return this.run(async () => {
            await this.orm.call(MODEL, "ea_ts_charge", [
                form.day, Number(form.project), value, Number(form.task) || false, form.note,
            ]);
            form.hours = "";
            form.note = "";
        }, _t("Hours charged."));
    }

    setCell(row, day, ev) {
        const value = readHours(ev.target.value);
        if (value === (row.cells[day.date] || 0)) {
            return;
        }
        return this.run(() => this.orm.call(MODEL, "ea_ts_set_cell", [day.date, row.project_id, row.task_id, value]));
    }

    submit() {
        return this.run(() => this.orm.call(MODEL, "ea_ts_submit", [this.data.monday]), _t("Week submitted."));
    }

    recall() {
        return this.run(() => this.orm.call(MODEL, "ea_ts_recall", [this.data.monday]), _t("Week taken back."));
    }

    goWeek(day) {
        this.state.error = null;
        this.state.notice = null;
        return this.load(day);
    }

    openReports() {
        return this.action.doAction("ea_audit_timesheet.action_reports");
    }

    backToAudit() {
        return this.ctx.openHome();
    }
}

registry.category("actions").add("ea_audit_timesheet.sheet", EaTimesheet);
