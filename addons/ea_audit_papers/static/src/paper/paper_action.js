import { Component, onWillStart, useState } from "@odoo/owl";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";

import { AUTO_SOURCES, CHIP_LETTER, LABELS } from "./labels";

const NA = "na";
const SAVED_AT_WINDOW_MS = 10 * 60 * 1000;
const PART_TITLE = /^(?:Partie|Part)\s+(\S+)\s+—\s+(.*)$/;
const PAPER_CODE = /^[A-Z]\d+(?:\.\d+)+$/;

/** A tab's short name: the part's letter and first word. Several sections of one part open
 *  with the same paper code (E6.10.1 Checklist A, B...): the words after it tell them apart. */
function partLabel(letter, rest) {
    const words = rest.split(/\s+/);
    if (PAPER_CODE.test(words[0]) && words.length > 2) {
        return `${letter} ${words[1]} ${words[2].replace(/:$/, "")}`;
    }
    return `${letter} ${words[0]}`;
}

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
        const { params = {}, context = {} } = this.props.action || {};
        this.fileItemId = Number(params.file_item_id || params.active_id || context.active_id);
        this.state = useState({
            payload: null,
            values: {},
            tab: "status",
            saving: false,
            error: false,
            notice: false,
            conflicts: {},
            undo: false,
            noteDraft: "",
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

    get def() {
        return this.state.payload.definition;
    }

    get parts() {
        const parts = [];
        if (this.state.payload.embed_only) {
            return parts;
        }
        (this.def.sections || []).forEach((section, index) => {
            const title = this.pick(section, "title");
            const match = PART_TITLE.exec(title);
            const letter = match ? match[1] : "";
            const label = match ? partLabel(letter, match[2]) : title;
            const prefix = letter ? `${letter}.` : "";
            let items = [];
            if (section.kind === "proc") {
                items = section.procs.map((proc, i) => ({
                    kind: "proc",
                    id: `p:${proc.key}`,
                    num: `${prefix}${i + 1}`,
                    text: this.fr ? proc.fr : proc.en,
                    src: this.pick(proc, "src"),
                    tip: this.pick(proc, "tip"),
                    resKey: `p_${proc.key}`,
                    naKey: `p_${proc.key}_na`,
                    whyKey: `p_${proc.key}_x`,
                }));
            } else if (section.kind === "yn") {
                items = section.items.map((item, i) => ({
                    kind: "yn",
                    id: `q:${item.key}`,
                    num: `${prefix}${i + 1}`,
                    text: this.fr ? item.fr : item.en,
                    tip: this.pick(item, "tip"),
                    ansKey: `q_${item.key}`,
                    whyKey: `q_${item.key}_x`,
                }));
            } else {
                // an auto field marked hideEmpty (P1.5's reminder and conclusion) shows only with a value
                items = section.fields
                    .filter((field) => !(field.hideEmpty && !this.state.payload.auto_values[field.key]))
                    .map((field) => this.fieldItem(field));
            }
            parts.push({
                id: `s${index}`,
                label: label.length > 26 ? `${label.slice(0, 24)}…` : label,
                title,
                intro: this.pick(section, "intro"),
                items,
            });
        });
        if (this.def.fields?.length) {
            parts.push({
                id: "fields",
                label: this.t("work"),
                title: this.t("work"),
                intro: false,
                items: this.def.fields.map((field) => this.fieldItem(field)),
            });
        }
        return parts;
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
            return v(item.naKey) === NA ? filled(v(item.whyKey)) : filled(v(item.resKey));
        }
        if (item.kind === "yn") {
            const answer = v(item.ansKey);
            return answer === NA || answer === "no" ? filled(v(item.whyKey)) : filled(answer);
        }
        return item.field.kind === "auto" || !this.asked(item.field) || filled(v(item.field.key));
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

    get hasBoardTab() {
        return Boolean(this.board) || this.state.payload.embed_only;
    }

    get tabs() {
        const tabs = [{ id: "status", label: this.t("status"), title: this.t("statusTitle"), done: true }];
        if (this.hasBoardTab) {
            const label = this.board?.label ? String(this.board.label) : this.t("work");
            tabs.push({ id: "board", label, title: label, done: false });
        }
        for (const part of this.parts) {
            tabs.push({
                id: part.id,
                label: part.label,
                title: part.title,
                done: part.items.every((item) => this.answered(item)),
            });
        }
        if (!this.state.payload.embed_only) {
            const conclusions = this.conclusions;
            tabs.push({
                id: "conclusion",
                label: this.t("conclusion"),
                title: this.t("conclusion"),
                done:
                    conclusions.length > 0 &&
                    conclusions.every(({ key, whyKey }) => {
                        const answer = this.state.values[key];
                        return filled(answer) && (answer !== "no" || filled(this.state.values[whyKey]));
                    }),
            });
        }
        return tabs;
    }

    get currentPart() {
        return this.parts.find((part) => part.id === this.state.tab) || null;
    }

    get tabIndex() {
        return this.tabs.findIndex((tab) => tab.id === this.state.tab);
    }

    go(delta) {
        const next = this.tabs[this.tabIndex + delta];
        if (next) {
            this.state.tab = next.id;
        }
    }

    get tips() {
        const part = this.currentPart;
        if (!part) {
            return [];
        }
        const tips = part.items.filter((item) => item.tip).map((item) => ({ id: item.id, text: item.tip }));
        if (tips.length) {
            return tips.slice(0, 4);
        }
        // papers without bespoke tips fall back to their procedures' expected sources
        return part.items
            .filter((item) => item.src)
            .slice(0, 4)
            .map((item) => ({ id: item.id, text: `${item.num} ${item.src}` }));
    }

    // ---- answers -------------------------------------------------------

    val(key) {
        return this.state.values[key] ?? "";
    }

    set(key, value) {
        this.state.values[key] = value;
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
            return Object.keys(conflicts).length === 0;
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
        return `${this.t("savedAt")}${clock} (WAT)`;
    }

    // ---- signatures ----------------------------------------------------

    get chips() {
        return this.state.payload.signing.chips;
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

    async addNote() {
        const done = await this.guarded(() => this.callItem("add_review_note", [this.state.noteDraft]));
        if (done.ok) {
            this.state.noteDraft = "";
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
