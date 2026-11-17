import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { EaCrumbs } from "./page_kit";

const ENGAGEMENT = "ea.audit.engagement";
const LADDER = ["staff", "senior", "manager", "senior_manager", "director", "partner"];

/**
 * Work allocation (owner's mock-up of 2026-11-18): who prepares and who reviews each task, grouped
 * by phase, with the workload of each team member beside it. The boxes change on the screen only;
 * Save sends the changes to the server, which applies the rules again (ea_allocate_tasks). A
 * reviewer who is also the preparer cannot be saved; a person below the task's minimum role is a
 * warning only. Partner approval is set by the server, never here.
 */
export class WorkAllocationPage extends Component {
    static template = "ea_audit_tools.WorkAllocationPage";
    static props = ["*"];
    static components = { EaCrumbs };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        const { params = {}, context = {} } = this.props.action || {};
        this.engagementId = Number(params.engagement_id || context.active_id || context.ea_engagement_id);
        this.state = useState({
            p: null, edits: {}, filter: "all", person: null, selected: {}, bulkPreparer: "", bulkReviewer: "", busy: false,
        });
        onWillStart(() => this.load());
    }

    get p() {
        return this.state.p;
    }

    async load() {
        this.state.p = await this.orm.call(ENGAGEMENT, "ea_work_allocation_page", [[this.engagementId]]);
        this.state.edits = {};
        this.state.selected = {};
    }

    // ---- reading -------------------------------------------------------------

    value(row, box) {
        const edit = this.state.edits[row.id];
        return edit && box in edit ? edit[box] : row[box];
    }

    member(id) {
        return this.p.members.find((m) => m.id === id) || null;
    }

    rank(role) {
        return LADDER.indexOf(role);
    }

    /** The red lines under a box: [{text, blocking}]. Mirrors services/work_allocation.check_row. */
    problems(row, box) {
        const preparer = this.value(row, "preparer");
        const reviewer = this.value(row, "reviewer");
        const out = [];
        if (box === "reviewer" && reviewer && (reviewer === preparer || reviewer === row.assignee)) {
            out.push({ text: _t("The reviewer cannot be the preparer."), blocking: true });
        }
        const person = this.member(box === "preparer" ? preparer : reviewer);
        const minimum = box === "preparer" ? row.minPreparer : row.minReviewer;
        if (person && this.rank(person.role) < this.rank(minimum)) {
            const word = this.p.roleWords[minimum];
            out.push({
                text: box === "preparer"
                    ? _t("Below the minimum role: a %s or above must prepare this task.", word)
                    : _t("Below the minimum role: a %s or above must review this task.", word),
                blocking: false,
            });
        }
        return out;
    }

    isAllocated(row) {
        return Boolean(this.value(row, "preparer") && this.value(row, "reviewer"));
    }

    involves(row, userId) {
        return (
            this.value(row, "preparer") === userId ||
            this.value(row, "reviewer") === userId ||
            (row.partnerRequired && this.p.partner && this.p.partner.id === userId)
        );
    }

    get counts() {
        const rows = this.p.rows;
        return {
            all: rows.length,
            unallocated: rows.filter((r) => !this.isAllocated(r)).length,
            partner: rows.filter((r) => r.partnerRequired).length,
        };
    }

    get filters() {
        const c = this.counts;
        return [
            { key: "all", label: _t("All tasks"), count: c.all },
            { key: "unallocated", label: _t("Not allocated"), count: c.unallocated },
            { key: "partner", label: _t("Needs partner approval"), count: c.partner },
            { key: "mine", label: _t("Mine"), count: null },
        ];
    }

    get visible() {
        let rows = this.p.rows;
        const filter = this.state.filter;
        if (filter === "unallocated") {
            rows = rows.filter((r) => !this.isAllocated(r));
        } else if (filter === "partner") {
            rows = rows.filter((r) => r.partnerRequired);
        } else if (filter === "mine") {
            rows = rows.filter((r) => this.involves(r, this.p.uid));
        }
        if (this.state.person) {
            rows = rows.filter((r) => this.involves(r, this.state.person));
        }
        return rows;
    }

    get groups() {
        const labels = {
            planning: _t("Planning"),
            strategy: _t("Strategy and risks"),
            execution: _t("Execution"),
            conclusion: _t("Conclusion"),
        };
        const visible = this.visible;
        return Object.keys(labels)
            .map((key) => {
                const all = this.p.rows.filter((r) => r.phase === key);
                return {
                    key,
                    label: labels[key],
                    summary: _t("%s tasks · %s not allocated", all.length, all.filter((r) => !this.isAllocated(r)).length),
                    rows: visible.filter((r) => r.phase === key),
                };
            })
            .filter((group) => group.rows.length);
    }

    get workload() {
        const rows = this.p.rows;
        const partnerId = this.p.partner && this.p.partner.id;
        const lines = this.p.members.map((m) => {
            const prepare = rows.filter((r) => this.value(r, "preparer") === m.id).length;
            const review = rows.filter((r) => this.value(r, "reviewer") === m.id).length;
            const approve = m.id === partnerId ? rows.filter((r) => r.partnerRequired).length : 0;
            return {
                ...m,
                total: prepare + review + approve,
                text: _t("%s to prepare · %s to review", prepare, review),
                partnerText: m.id === partnerId ? _t("%s to approve · automatic", approve) : "",
            };
        });
        const most = Math.max(1, ...lines.map((l) => l.total));
        for (const line of lines) {
            line.bar = `width: ${Math.round((line.total * 100) / most)}%`;
        }
        return lines;
    }

    get selectedIds() {
        return Object.keys(this.state.selected).filter((id) => this.state.selected[id]).map(Number);
    }

    get selectedText() {
        return _t("%s tasks selected", this.selectedIds.length);
    }

    get changes() {
        const out = [];
        for (const row of this.p.rows) {
            const change = { id: row.id };
            for (const [box, field] of [["preparer", "preparer_id"], ["reviewer", "approver_id"]]) {
                if (this.value(row, box) !== row[box]) {
                    change[field] = this.value(row, box) || false;
                }
            }
            if (Object.keys(change).length > 1) {
                out.push(change);
            }
        }
        return out;
    }

    get blocked() {
        return this.p.rows.some((row) => this.problems(row, "reviewer").some((x) => x.blocking));
    }

    // ---- changing the boxes (nothing saved) ----------------------------------

    set(row, box, userId) {
        this.state.edits[row.id] = { ...(this.state.edits[row.id] || {}), [box]: userId || false };
    }

    onSelect(row, box, ev) {
        this.set(row, box, Number(ev.target.value) || false);
    }

    toggle(row, ev) {
        this.state.selected[row.id] = ev.target.checked;
    }

    applyBulk() {
        const preparer = Number(this.state.bulkPreparer) || null;
        const reviewer = Number(this.state.bulkReviewer) || null;
        for (const row of this.p.rows.filter((r) => this.state.selected[r.id])) {
            if (preparer) {
                this.set(row, "preparer", preparer);
            }
            if (reviewer) {
                this.set(row, "reviewer", reviewer);
            }
        }
        this.state.selected = {};
        this.state.bulkPreparer = "";
        this.state.bulkReviewer = "";
    }

    setFilter(key) {
        this.state.filter = key;
        this.state.person = null;
    }

    pickPerson(member) {
        this.state.person = this.state.person === member.id ? null : member.id;
    }

    async suggest() {
        const current = this.p.rows.map((r) => ({ id: r.id, preparer: this.value(r, "preparer"), reviewer: this.value(r, "reviewer") }));
        const proposal = await this.orm.call(ENGAGEMENT, "ea_work_allocation_suggest", [[this.engagementId], current]);
        let filled = 0;
        for (const row of this.p.rows) {
            const boxes = proposal[String(row.id)] || {};
            for (const box of ["preparer", "reviewer"]) {
                if (boxes[box] && !this.value(row, box)) {
                    this.set(row, box, boxes[box]);
                    filled++;
                }
            }
        }
        this.notification.add(_t("%s boxes filled. Nothing is saved until you click Save.", filled), { type: "info" });
    }

    async save() {
        if (this.p.readonly || this.blocked || this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            const result = await this.orm.call(ENGAGEMENT, "ea_work_allocation_save", [[this.engagementId], this.changes]);
            this.state.p = result.page;
            this.state.edits = {};
            this.state.selected = {};
            this.notification.add(_t("The allocation is saved."), { type: "success" });
        } finally {
            this.state.busy = false;
        }
    }

    async exportExcel() {
        const action = await this.orm.call(ENGAGEMENT, "action_export_work_allocation", [[this.engagementId]]);
        return this.action.doAction(action);
    }
}

registry.category("actions").add("ea_audit_tools.work_allocation_page", WorkAllocationPage);
