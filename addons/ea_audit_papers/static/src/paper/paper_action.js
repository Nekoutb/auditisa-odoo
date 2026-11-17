import { Component, onWillStart, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";

import { ExistingDocsDialog } from "../docs/existing_docs_dialog";
import { AUTO_SOURCES, CHIP_LETTER, LABELS } from "./labels";

const NA = "na";
const SAVED_AT_WINDOW_MS = 10 * 60 * 1000;
const norm = (text) => (text ?? "").replace(/\r\n/g, "\n");
const filled = (text) => Boolean((text ?? "").trim());

function readBlob(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
    });
}

/** One component for all papers. It shows what the server says and decides nothing. */
export class PaperAction extends Component {
    static template = "ea_audit_papers.PaperAction";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        const { params = {}, context = {} } = this.props.action || {};
        this.fileItemId = Number(params.file_item_id || params.active_id || context.active_id);
        this.state = useState({
            payload: null,
            values: {},
            mode: "prepare",
            filter: null,
            open: {},
            tipsClosed: {},
            showReq: false,
            noteDrafts: {},
            noteFor: false,
            saving: false,
            error: false,
            notice: false,
            conflicts: {},
            undo: false,
            replyDrafts: {},
            renaming: false,
            renameDraft: "",
            naDraft: "",
            section: { conclusion: "", objectives_achieved: false, no_procedures_rationale: "" },
        });
        useSetupAction({
            beforeLeave: () => this.confirmLeave(),
            beforeUnload: (ev) => {
                if (this.dirty) {
                    ev.preventDefault();
                    ev.returnValue = "";
                }
            },
        });
        onWillStart(() => this.load());
    }

    // ---- language ------------------------------------------------------

    get fr() {
        // the web client reports BCP-47 (fr-FR), the context Odoo's own form (fr_FR)
        return (user.lang || user.context?.lang || "").startsWith("fr");
    }

    t(key) {
        const label = LABELS[key];
        return label ? String(label) : key;
    }

    pick(obj, name) {
        return obj?.[name + (this.fr ? "Fr" : "En")];
    }

    get kwargs() {
        return {};
    }

    // ---- server --------------------------------------------------------

    async guarded(call) {
        this.state.error = false;
        try {
            return { ok: true, result: await call() };
        } catch (error) {
            const message = error?.data?.message;
            if (!message) {
                throw error;
            }
            this.state.error = message;
            return { ok: false };
        }
    }

    callItem(method, args = []) {
        return this.orm.call("ea.audit.file.item", method, [[this.fileItemId], ...args], this.kwargs);
    }

    async load() {
        const payload = await this.callItem("get_paper_payload");
        this.adopt(payload, {});
    }

    /** The server's state, with what the user has typed and not saved laid over it. */
    adopt(payload, edits) {
        this.state.payload = payload;
        this.state.values = { ...payload.values, ...edits };
        if (payload.section_conclusion) {
            this.state.section = {
                conclusion: payload.section_conclusion.conclusion,
                objectives_achieved: payload.section_conclusion.objectives_achieved,
                no_procedures_rationale: payload.section_conclusion.no_procedures_rationale,
            };
        }
        this.state.naDraft = payload.not_applicable.reason;
        this.env.config?.setDisplayName?.(`${payload.code} ${payload.short_title}`);
    }

    async refresh() {
        const edits = this.edits;
        const payload = await this.callItem("get_paper_payload");
        this.adopt(payload, edits);
    }

    get edits() {
        const { payload, values } = this.state;
        const out = {};
        if (payload) {
            for (const [key, value] of Object.entries(values)) {
                if (norm(value) !== norm(payload.values[key])) {
                    out[key] = value;
                }
            }
        }
        return out;
    }

    get dirty() {
        return Object.keys(this.edits).length > 0;
    }

    async confirmLeave() {
        if (!this.dirty) {
            return true;
        }
        return new Promise((resolve) => {
            this.dialog.add(ConfirmationDialog, {
                title: this.t("leaveTitle"),
                body: this.t("leaveBody"),
                confirmLabel: this.t("leaveConfirm"),
                cancelLabel: this.t("stay"),
                confirm: () => resolve(true),
                cancel: () => resolve(false),
            });
        });
    }

    // ---- the paper's structure -----------------------------------------
    // One scrolling page (owner-approved layout of 2026-11-17): 1 Objective, 2 Tasks required,
    // 3 Conclusion and sign-off. A definition without the new keys reads the same way.

    get def() {
        return this.state.payload.definition;
    }

    get L() {
        return this.state.payload.layout;
    }

    get converted() {
        return Boolean(this.L?.converted);
    }

    get depth() {
        return this.L?.depth || "complex";
    }

    /** Tasks (procedures and, for older papers, blocks of fields), statements and extra boxes. */
    get structure() {
        const tasks = [];
        const statements = [];
        const extras = [];
        if (this.state.payload.embed_only) {
            return { tasks, statements, extras };
        }
        const sections = this.def.sections || [];
        const hasProc = sections.some((section) => section.kind === "proc");
        const owned = {};
        for (const section of sections) {
            for (const proc of section.procs || []) {
                for (const key of proc.fieldKeys || []) {
                    owned[key] = proc.key;
                }
            }
        }
        const fieldsByKey = {};
        for (const section of sections) {
            for (const field of section.fields || []) {
                fieldsByKey[field.key] = field;
            }
        }
        let count = 0;
        sections.forEach((section, index) => {
            const title = this.pick(section, "title");
            if (section.kind === "proc") {
                for (const proc of section.procs) {
                    count += 1;
                    tasks.push(this.procTask(proc, `2.${count}`, fieldsByKey));
                }
            } else if (section.kind === "yn") {
                const items = section.items.map((item, i) => this.statement(item, i));
                if (hasProc || this.converted) {
                    statements.push({ id: `y${index}`, title: sections.filter((s) => s.kind === "yn").length > 1 ? title : "", items });
                } else {
                    count += 1;
                    tasks.push({ kind: "group", id: `s${index}`, key: `s${index}`, num: `2.${count}`, short: title, title, intro: this.pick(section, "intro"), items });
                }
            } else {
                const items = this.sectionItems(section).filter((item) => !(item.kind === "field" && owned[item.field.key]));
                if (this.converted) {
                    extras.push(...items);
                } else if (items.length) {
                    count += 1;
                    tasks.push({ kind: "group", id: `s${index}`, key: `s${index}`, num: `2.${count}`, short: title, title, intro: this.pick(section, "intro"), items });
                }
            }
        });
        if (this.def.fields?.length) {
            count += 1;
            tasks.push({
                kind: "group", id: "fields", key: "fields", num: `2.${count}`, short: this.t("work"), title: this.t("work"), intro: false,
                items: this.def.fields.map((field) => this.fieldItem(field)),
            });
        }
        return { tasks, statements, extras };
    }

    sectionItems(section) {
        if (this.collapsed(section)) {
            // One line (owner's decision of 2026-11-16): the deciding answer, then why the rest is closed.
            const rule = section.collapse;
            const items = section.fields.filter((field) => field.key === rule.key).map((field) => this.fieldItem(field));
            items.push({ kind: "note", id: `n:${rule.key}`, text: this.pick(rule, "note") });
            return items;
        }
        // an auto field marked hideEmpty (P1.5's reminder and conclusion) shows only with a value
        return section.fields
            .filter((field) => !(field.hideEmpty && !this.state.payload.auto_values[field.key]))
            .map((field) => this.fieldItem(field));
    }

    procTask(proc, num, fieldsByKey) {
        const tips = this.pick(proc, "tips") || (this.pick(proc, "tip") ? [this.pick(proc, "tip")] : []);
        const text = this.fr ? proc.fr : proc.en;
        return {
            kind: "proc",
            id: `p:${proc.key}`,
            key: proc.key,
            num,
            short: this.pick(proc, "short") || (text.length > 70 ? `${text.slice(0, 68)}…` : text),
            text,
            isa: proc.isa || "",
            tips: tips.slice(0, 3),
            src: this.pick(proc, "src"),
            std: this.pick(proc, "std") || "",
            sourceHint: proc.sourceHint || "",
            mode: proc._mode || "full",
            tool: proc._tool || "",
            toolPending: Boolean(proc.toolDone) && proc._mode !== "tool",
            resKey: `p_${proc.key}`,
            naKey: `p_${proc.key}_na`,
            whyKey: `p_${proc.key}_x`,
            markKey: `p_${proc.key}_m`,
            srcKey: `p_${proc.key}_src`,
            fields: (proc.fieldKeys || []).filter((key) => fieldsByKey[key]).map((key) => this.fieldItem(fieldsByKey[key])),
        };
    }

    statement(item, index) {
        const check = this.state.payload.checks?.[item.key] || null;
        return {
            kind: "yn",
            id: `q:${item.key}`,
            key: item.key,
            num: String(index + 1),
            text: this.fr ? item.fr : item.en,
            tip: this.pick(item, "tip"),
            ansKey: `q_${item.key}`,
            whyKey: `q_${item.key}_x`,
            allowNa: !this.converted || Boolean(item.na),
            check,
            refs: this.taskRefs(item.tasks || []),
        };
    }

    /** "2.1–2.7" for a run of tasks, "2.2, 2.5" otherwise. */
    taskRefs(keys) {
        if (!keys.length) {
            return "";
        }
        const procs = (this.def.sections || []).filter((s) => s.kind === "proc").flatMap((s) => s.procs);
        const positions = keys.map((key) => procs.findIndex((proc) => proc.key === key)).filter((i) => i >= 0).sort((a, b) => a - b);
        if (!positions.length) {
            return "";
        }
        const run = positions.every((p, i) => i === 0 || p === positions[i - 1] + 1);
        if (run && positions.length > 2) {
            return `2.${positions[0] + 1}–2.${positions.at(-1) + 1}`;
        }
        return positions.map((p) => `2.${p + 1}`).join(", ");
    }

    /** A block folded by an answer, or by a fact the server knows (sent in auto_values). */
    collapsed(section) {
        const rule = section.collapse;
        if (!rule) {
            return false;
        }
        const given = this.state.values[rule.key] ?? this.state.payload.auto_values[rule.key] ?? "";
        return String(given).trim() === rule.value;
    }

    fieldItem(field) {
        return {
            kind: "field",
            id: `f:${field.key}`,
            field,
            label: this.pick(field, "label"),
            tag: this.pick(field, "tag"),
            options: (field.options || []).map((option) => ({
                value: option.value,
                label: this.fr ? option.fr : option.en,
                hint: this.pick(option, "hint"),
            })),
            cards: (field.options || []).some((option) => option.hintEn),
        };
    }

    /** A field asked only when another answer has a given value (P1.5's reviewer). */
    asked(field) {
        return !field.when || this.val(field.when.key) === field.when.value;
    }

    answered(item) {
        const v = (key) => this.state.values[key];
        if (item.kind === "proc") {
            if (v(item.naKey) === NA) {
                return filled(v(item.whyKey));
            }
            if (item.mode === "tool") {
                return true;
            }
            const mark = (v(item.markKey) || "").trim();
            if (item.mode === "tick" && mark === "tick") {
                return true;
            }
            if (mark === "nx" && this.state.payload.warnings.length) {
                return false;
            }
            if (item.mode === "exception" && mark === "nx" && !filled(v(item.srcKey))) {
                return false;
            }
            return filled(v(item.resKey));
        }
        if (item.kind === "group") {
            return item.items.every((sub) => this.answered(sub));
        }
        if (item.kind === "note") {
            return true;
        }
        if (item.kind === "yn") {
            const answer = v(item.ansKey);
            return answer === NA || answer === "no" ? filled(v(item.whyKey)) : filled(answer);
        }
        return item.field.kind === "auto" || !this.asked(item.field) || filled(v(item.field.key));
    }

    /** done, na, tool or open: the dot of the step list and the collapsed line. */
    status(task) {
        if (task.kind === "proc" && this.val(task.naKey) === NA && filled(this.val(task.whyKey))) {
            return "na";
        }
        if (task.kind === "proc" && task.mode === "tool") {
            return "tool";
        }
        return this.answered(task) ? "done" : "open";
    }

    finished(task) {
        return this.status(task) !== "open";
    }

    expanded(task) {
        return !this.finished(task) || Boolean(this.state.open[task.id]);
    }

    toggle(task) {
        this.state.open[task.id] = !this.state.open[task.id];
    }

    get conclusions() {
        return (this.pick(this.def, "concl") || []).map((text, index) => ({
            text,
            index,
            key: `c_${index}`,
            whyKey: `c_${index}_x`,
        }));
    }

    get board() {
        const boards = registry.category("ea_audit_paper_boards");
        return boards.get(this.state.payload.code, null);
    }

    /** The tool's own board (P7.2, C6.1, the E4 lead schedules...) where no card replaces it. */
    get showBoard() {
        return !this.state.payload.tool_card && (Boolean(this.board) || this.state.payload.embed_only);
    }

    // ---- what the page shows -------------------------------------------

    get tasks() {
        return this.structure.tasks;
    }

    get shownTasks() {
        const filter = this.state.filter;
        return this.tasks.filter((task) => {
            if (filter === "open" && this.finished(task)) {
                return false;
            }
            if (filter === "notes" && !this.openNotes(task.key)) {
                return false;
            }
            return true;
        });
    }

    get counts() {
        const tasks = this.tasks;
        const statuses = tasks.map((task) => this.status(task));
        return {
            total: tasks.length,
            done: statuses.filter((s) => s !== "open").length,
            na: statuses.filter((s) => s === "na").length,
            tool: statuses.filter((s) => s === "tool").length,
            exception: tasks.filter((task) => task.kind === "proc" && this.val(task.markKey) === "nx" && this.val(task.naKey) !== NA).length,
            notes: this.state.payload.notes.filter((note) => note.state === "open").length,
        };
    }

    get signedLine() {
        const signed = this.chips.filter((chip) => chip.state === "signed");
        if (!signed.length) {
            return this.t("notSignedYet");
        }
        return `${this.t("signedBy")}${signed.map((chip) => this.t(chip.role).toLowerCase()).join(", ")}`;
    }

    get depthLabel() {
        if (!this.converted) {
            return "";
        }
        return this.t(`depth_${this.L.profile}`);
    }

    get depthNote() {
        if (!this.converted) {
            return "";
        }
        if (this.L.depth_reason) {
            return this.t(`depthReason_${this.L.depth_reason}`);
        }
        return this.t(`depthMode_${this.depth}`);
    }

    get objectiveText() {
        return this.pick(this.def, "objective") || "";
    }

    get requirements() {
        return this.pick(this.def, "req") || [];
    }

    jump(id) {
        const target = document.getElementById(`eap-${id}`);
        if (target) {
            target.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }

    setFilter(filter) {
        this.state.filter = this.state.filter === filter ? null : filter;
    }

    tipsOpen(task) {
        return this.state.mode === "prepare" && this.state.tipsClosed[task.id] !== true;
    }

    // ---- depth: no exceptions / exceptions / tick ------------------------

    mark(task) {
        return (this.val(task.markKey) || "").trim();
    }

    choose(task, choice) {
        if (choice === "na") {
            this.set(task.naKey, NA);
            return;
        }
        this.set(task.naKey, "");
        if (choice === "done") {
            return;
        }
        if (choice === "tick") {
            this.set(task.markKey, this.mark(task) === "tick" ? "" : "tick");
            return;
        }
        if (choice === "nx") {
            this.set(task.markKey, "nx");
            if (!filled(this.val(task.resKey)) || this.mark(task) !== "nx") {
                this.set(task.resKey, task.std || this.t("noExceptionsDefault"));
            }
            return;
        }
        if (choice === "ex") {
            if (this.mark(task) === "nx" && norm(this.val(task.resKey)) === norm(task.std)) {
                this.set(task.resKey, "");
            }
            this.set(task.markKey, "ex");
        }
    }

    exceptionBlocked() {
        return this.state.payload.warnings.length > 0;
    }

    /** What a "No exceptions noted" may cite: the tools, the linked tasks, the attachments. */
    get sourceOptions() {
        const p = this.state.payload;
        const out = [];
        for (const tool of p.tools || []) {
            out.push(this.fr ? tool.fr : tool.en);
        }
        for (const task of p.linked_tasks) {
            out.push(`${task.code} ${task.title}`);
        }
        for (const row of p.attachments.live) {
            out.push(`${row.ref} ${row.name}`);
        }
        return out;
    }

    useStandardConclusion() {
        const text = this.pick(this.def, "conclStd");
        if (text) {
            this.set("conclusion", text);
        }
    }

    // ---- review notes on a task ------------------------------------------

    notesOf(key) {
        return this.state.payload.notes.filter((note) => (note.task_key || "") === key);
    }

    openNotes(key) {
        return this.notesOf(key).filter((note) => note.state === "open").length;
    }

    /** Notes raised before tasks carried notes, or on the conclusion. */
    get paperNotes() {
        const keys = new Set(this.tasks.map((task) => task.key));
        return this.state.payload.notes.filter((note) => !note.task_key || !keys.has(note.task_key));
    }

    async addNote(key = "") {
        const text = this.state.noteDrafts[key] || "";
        const done = await this.guarded(() => this.callItem("add_review_note", [text, key || false]));
        if (done.ok) {
            this.state.noteDrafts[key] = "";
            this.state.noteFor = false;
            await this.refresh();
        }
    }

    // ---- answers -------------------------------------------------------

    val(key) {
        return this.state.values[key] ?? "";
    }

    set(key, value) {
        this.state.values[key] = value;
        const match = /^p_(.+)$/.exec(key);
        if (match && this.state.payload.warnings.length && (this.state.values[`${key}_m`] || "") === "nx") {
            // a warning closed "No exceptions noted": the result written now is the preparer's own
            this.state.values[`${key}_m`] = "";
        }
    }

    ro(key) {
        const { payload } = this.state;
        return payload.readonly || payload.locked_keys.includes(key);
    }

    autoText(field) {
        const given = this.state.payload.auto_values[field.key];
        if (given) {
            return given;
        }
        const source = AUTO_SOURCES[field.source];
        return this.t("autoEmpty") + (source ? String(source) : this.t("autoDefault"));
    }

    procIsDone(item) {
        return this.val(item.naKey) !== NA && filled(this.val(item.resKey));
    }

    async save() {
        if (this.state.saving) {
            return false;
        }
        const edits = this.edits;
        this.state.saving = true;
        this.state.notice = false;
        try {
            const { payload } = this.state;
            const saved = await this.guarded(() =>
                this.orm.call(
                    "ea.audit.paper",
                    "save_answers",
                    [[payload.paper_id], edits, payload.version, payload.digests],
                    this.kwargs,
                ),
            );
            if (!saved.ok) {
                return false; // the typed text stays where it is
            }
            const { conflicts, voided } = saved.result;
            const held = Object.fromEntries(Object.entries(conflicts).map(([key, value]) => [key, value.mine]));
            this.state.conflicts = conflicts;
            const fresh = await this.callItem("get_paper_payload");
            this.adopt(fresh, held);
            if (voided.length) {
                const names = voided.map((role) => this.t(role)).join(", ");
                this.state.notice = this.t("voidedNotice") + names;
            }
            const clean = Object.keys(conflicts).length === 0;
            if (clean) {
                this.notification.add(this.t("savedToast"), { type: "success" });
            }
            return clean;
        } finally {
            this.state.saving = false;
        }
    }

    takeTheirs(key) {
        this.state.values[key] = this.state.conflicts[key].theirs;
        delete this.state.conflicts[key];
    }

    get savedLabel() {
        const at = this.state.payload.saved_at;
        if (!at) {
            return false;
        }
        const date = new Date(`${at.replace(" ", "T")}Z`);
        if (Date.now() - date.getTime() > SAVED_AT_WINDOW_MS) {
            return false;
        }
        const clock = new Intl.DateTimeFormat("en-GB", {
            timeZone: "Africa/Douala",
            hour: "2-digit",
            minute: "2-digit",
            hourCycle: "h23",
        }).format(date);
        return `✓ ${this.t("savedAt")}${clock} (WAT)`;
    }

    // ---- signatures ----------------------------------------------------

    get chips() {
        return this.state.payload.signing.chips;
    }

    /** Very simple: preparer, then partner. A reviewer's signature already given still shows. */
    get signChips() {
        if (this.depth !== "very_simple") {
            return this.chips;
        }
        return this.chips.filter((chip) => chip.role !== "reviewer" || chip.state === "signed");
    }

    get signedRows() {
        return this.chips.filter((chip) => chip.state === "signed");
    }

    letter(role) {
        return CHIP_LETTER[role];
    }

    chipText(chip) {
        if (chip.state === "signed") {
            return `${this.letter(chip.role)} ${chip.by}, ${chip.date}`;
        }
        return `${this.letter(chip.role)} ${this.t(`toSign_${chip.role}`)}`;
    }

    chipTitle(chip) {
        if (chip.state !== "signed") {
            return chip.reason || "";
        }
        return chip.removable ? this.t("unsignHint") : chip.remove_reason || "";
    }

    chipClick(chip) {
        return chip.state === "signed" ? this.unsign(chip) : this.sign(chip);
    }

    /** Take back one's own sign-off, after a small confirmation; the server decides. */
    unsign(chip) {
        if (chip.state !== "signed" || !chip.removable) {
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: this.t(`unsignTitle_${chip.role}`),
            body: this.t("unsignBody").replace("%(state)s", this.t(`toSign_${chip.role}`)),
            confirmLabel: this.t("unsignConfirm"),
            cancelLabel: this.t("cancel"),
            confirm: async () => {
                const done = await this.guarded(() => this.callItem("action_unsign", [chip.role]));
                if (done.ok) {
                    this.state.notice = false;
                    await this.refresh();
                }
            },
            cancel: () => {},
        });
    }

    async sign(chip) {
        if (chip.state !== "open") {
            return;
        }
        // a signature attests to what is stored, so what is on screen is stored first
        if (this.dirty && !(await this.save())) {
            return;
        }
        const signed = await this.guarded(() => this.callItem("action_sign", [chip.role]));
        if (signed.ok) {
            this.state.notice = false;
            await this.refresh();
        }
    }

    get myRoleLine() {
        const { signing } = this.state.payload;
        if (!signing.my_team_role) {
            return false;
        }
        const open = this.chips.filter((chip) => chip.state === "open").map((chip) => this.t(chip.role).toLowerCase());
        return {
            role: this.t(`role_${signing.my_team_role}`),
            can: open.join(", "),
        };
    }

    // ---- the rail ------------------------------------------------------

    openLinked(task) {
        return this.action.doAction({
            type: "ir.actions.client",
            tag: "ea_audit_paper",
            name: `${task.code} ${task.title}`,
            params: { file_item_id: task.id },
            context: { active_id: task.id },
        });
    }

    openTool(link) {
        return link.action ? this.action.doAction(link.action) : undefined;
    }

    back() {
        const crumbs = this.env.config?.breadcrumbs || [];
        if (crumbs.length > 1) {
            return crumbs.at(-2).onSelected();
        }
        return this.action.doAction("ea_audit_core.action_engagement");
    }

    get backLabel() {
        const crumbs = this.env.config?.breadcrumbs || [];
        return crumbs.length > 1 ? crumbs.at(-2).name : this.t("back");
    }

    optionLabel(option) {
        return option.name;
    }

    async setDeadline(value) {
        const done = await this.guarded(() => this.callItem("set_due_date", [value || false]));
        if (done.ok) {
            await this.refresh();
        }
    }

    async assign(role, value) {
        const field = role === "approver" ? "approver_id" : "preparer_id";
        const previous = this.state.payload.assignment[field];
        const next = Number(value) || false;
        const done = await this.guarded(() => this.callItem("assign_tasks", [next, role]));
        if (done.ok) {
            this.state.undo = { role, previous };
        }
        await this.refresh();
    }

    async undoAssign() {
        const { role, previous } = this.state.undo;
        const done = await this.guarded(() => this.callItem("assign_tasks", [previous, role]));
        if (done.ok) {
            this.state.undo = false;
        }
        await this.refresh();
    }

    async setTaskNa(clear) {
        const done = await this.guarded(() =>
            this.callItem("set_not_applicable", [clear ? "" : this.state.naDraft, clear]),
        );
        if (done.ok) {
            await this.refresh();
        }
    }

    async noteAct(note, method) {
        const text = this.state.replyDrafts[note.id] || "";
        const done = await this.guarded(() =>
            this.orm.call("ea.audit.review.note", method, [[note.id], text], this.kwargs),
        );
        if (done.ok) {
            delete this.state.replyDrafts[note.id];
            await this.refresh();
        }
    }

    async upload(ev) {
        const file = ev.target.files[0];
        ev.target.value = "";
        if (!file) {
            return;
        }
        const content = await readBlob(file);
        const done = await this.guarded(() => this.callItem("upload_attachment", [file.name, content]));
        if (done.ok) {
            await this.refresh();
        }
    }

    pickExisting() {
        this.dialog.add(ExistingDocsDialog, {
            engagementId: this.state.payload.engagement_id,
            onAttach: async (ids) => {
                const done = await this.guarded(() => this.callItem("attach_existing", [ids]));
                if (done.ok) {
                    await this.refresh();
                }
            },
        });
    }

    downloadUrl(attachmentId) {
        return `/web/content/${attachmentId}?download=true`;
    }

    attachmentAct(row, method, args = []) {
        return this.guarded(() =>
            this.orm.call("ea.audit.task.attachment", method, [[row.id], ...args], this.kwargs),
        );
    }

    remove(row) {
        this.dialog.add(ConfirmationDialog, {
            title: this.t("removeTitle"),
            body: this.t("removeBody"),
            confirmLabel: this.t("remove"),
            cancelLabel: this.t("stay"),
            confirm: async () => {
                if ((await this.attachmentAct(row, "remove")).ok) {
                    await this.refresh();
                }
            },
            cancel: () => {},
        });
    }

    async markReviewed(row) {
        if ((await this.attachmentAct(row, "mark_carried_reviewed")).ok) {
            await this.refresh();
        }
    }

    async restore(row) {
        if ((await this.attachmentAct(row, "restore")).ok) {
            await this.refresh();
        }
    }

    startRename(row) {
        this.state.renaming = row.id;
        this.state.renameDraft = row.name;
    }

    async finishRename(row) {
        if ((await this.attachmentAct(row, "rename", [this.state.renameDraft])).ok) {
            this.state.renaming = false;
            await this.refresh();
        }
    }

    // ---- section conclusion --------------------------------------------

    async saveSection() {
        const { conclusion, objectives_achieved, no_procedures_rationale } = this.state.section;
        const done = await this.guarded(() =>
            this.callItem("save_section_conclusion", [conclusion, objectives_achieved, no_procedures_rationale]),
        );
        if (done.ok) {
            await this.refresh();
        }
    }

    async reviewSection(asPartner) {
        const done = await this.guarded(() => this.callItem("review_section_conclusion", [asPartner]));
        if (done.ok) {
            await this.refresh();
        }
    }
}

registry.category("actions").add("ea_audit_paper", PaperAction);
