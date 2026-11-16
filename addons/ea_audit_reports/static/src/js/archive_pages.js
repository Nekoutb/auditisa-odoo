import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { EaCrumbs } from "@ea_audit_tools/js/page_kit";
import { ToolBoard } from "@ea_audit_tools/js/paper_boards";

const ENGAGEMENT = "ea.audit.engagement";

/** What both pages share: the engagement, the payload, one queue of server calls. */
class ArchiveBase extends Component {
    static props = ["*"];
    static components = { EaCrumbs };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const { params = {}, context = {} } = this.props.action || {};
        this.engagementId = Number(params.engagement_id || context.active_id || context.ea_engagement_id);
        this.state = useState({ p: null, busy: false, drafts: {} });
        this.queue = Promise.resolve();
        onWillStart(() => this.load());
    }

    get p() {
        return this.state.p;
    }

    async load() {
        this.state.p = await this.orm.call(ENGAGEMENT, this.pageMethod, [[this.engagementId]]);
    }

    run(method, args = []) {
        const job = this.queue.then(async () => {
            this.state.busy = true;
            try {
                this.state.p = await this.orm.call(ENGAGEMENT, method, [[this.engagementId], ...args]);
            } finally {
                this.state.busy = false;
            }
        });
        this.queue = job.catch(() => {});
        return job;
    }

    async open(kind, value) {
        await this.queue;
        const action = await this.orm.call(ENGAGEMENT, "ea_archive_page_open", [[this.engagementId], kind, value]);
        return this.action.doAction(action, { onClose: () => this.load() });
    }

    draft(row) {
        const saved = { answer: row.answer, note: row.note };
        return this.state.drafts[row.key] || saved;
    }

    choose(row, answer) {
        this.state.drafts[row.key] = { ...this.draft(row), answer };
        return this.saveIfComplete(row);
    }

    onNote(row, ev) {
        this.state.drafts[row.key] = { ...this.draft(row), note: ev.target.value };
    }

    saveIfComplete(row) {
        const d = this.draft(row);
        if (!d.answer || !(d.note || "").trim()) {
            return;
        }
        if (d.answer === row.answer && d.note.trim() === row.note) {
            return;
        }
        return this.run(this.answerMethod, [row.key, d.answer, d.note]).then(() => {
            delete this.state.drafts[row.key];
        });
    }

    needsNote(row) {
        const d = this.draft(row);
        return Boolean(d.answer) && !(d.note || "").trim();
    }
}

/** C6.1, before the report: checked by the tool, confirmed by the team, the partner's sign-off. */
export class ChecklistPage extends ArchiveBase {
    static template = "ea_audit_reports.ChecklistPage";
    pageMethod = "ea_checklist_page";
    answerMethod = "ea_checklist_answer";

    sign() {
        return this.run("ea_sign_ready");
    }

    issue() {
        return this.open("method", "action_open_issue_wizard");
    }

    get status() {
        const p = this.p;
        if (p.reportIssued) {
            return "issued";
        }
        if (p.signed) {
            return "signed";
        }
        return p.ready ? "ready" : "not_ready";
    }
}

/** C6.2, after the report: the 60-day clock, the checks, the archive; then the archived file. */
export class ArchivePage extends ArchiveBase {
    static template = "ea_audit_reports.ArchivePage";
    pageMethod = "ea_archive_page";
    answerMethod = "ea_archive_confirm";

    setup() {
        super.setup();
        Object.assign(this.state, { confirmName: "", lateReason: "", lateWork: "", holdReason: "", addReason: "", showAdd: false, showHold: false });
        this.fileInput = useRef("addendumFile");
    }

    get clockStyle() {
        return `width: ${this.p.clock ? this.p.clock.pct : 0}%`;
    }

    get nameMatches() {
        const norm = (text) => (text || "").trim().replace(/\s+/g, " ").toLowerCase();
        return Boolean(this.p.client) && norm(this.state.confirmName) === norm(this.p.client);
    }

    get canPressArchive() {
        const late = this.p.clock && this.p.clock.overdue;
        return this.p.canArchive && this.nameMatches && (!late || this.state.lateReason.trim()) && !this.state.busy;
    }

    archive() {
        return this.run("ea_archive_from_page", [this.state.confirmName, this.state.lateReason || false]);
    }

    openLateWork() {
        return this.run("ea_late_work_open", [this.state.lateWork]).then(() => {
            this.state.lateWork = "";
        });
    }

    closeLateWork() {
        return this.run("ea_late_work_close");
    }

    download() {
        window.location.href = `/ea_audit/engagement/${this.engagementId}/sealed-copy`;
        setTimeout(() => this.load(), 1500);
    }

    toggleHold() {
        return this.run("ea_hold_from_page", [this.state.holdReason]).then(() => {
            this.state.holdReason = "";
            this.state.showHold = false;
        });
    }

    async addAddendum() {
        const file = this.fileInput.el && this.fileInput.el.files[0];
        let name = false;
        let content = false;
        if (file) {
            name = file.name;
            content = await new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
                reader.onerror = () => reject(reader.error);
                reader.readAsDataURL(file);
            });
        }
        await this.run("ea_addendum_from_page", [this.state.addReason, name, content]);
        this.state.addReason = "";
        this.state.showAdd = false;
    }

    rollForward() {
        return this.open("method", "action_rollforward_next_year");
    }
}

registry.category("actions").add("ea_audit_reports.checklist_page", ChecklistPage);
registry.category("actions").add("ea_audit_reports.archive_page", ArchivePage);

const boards = registry.category("ea_audit_paper_boards");
boards.add("C6.1", { Component: ToolBoard, label: _t("Completion checklist") });
boards.add("C6.2", { Component: ToolBoard, label: _t("Assemble and archive") });
