import { Component, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { ExistingDocsDialog } from "@ea_audit_papers/docs/existing_docs_dialog";

/**
 * Pieces every one-page tool shares (owner, 2026-11-16).
 *
 * EaCrumbs: the trail back to where the user came from, as Odoo's lists show it: each earlier
 * step is a link, the page itself is the last word. Opened with no trail (a bookmark, a reload),
 * it still offers the way back to the engagement's dashboard.
 *
 * EaDocsPane: the documents of what is open on the page, in a pane at the right: drop or choose
 * files, or pick documents already in this engagement; type and linked control where the page
 * has them; the list with versions. The page says what each action means through callbacks, so
 * one pane serves findings, journal entries, samples, working papers and SCOTs alike.
 */
export class EaCrumbs extends Component {
    static template = "ea_audit_tools.EaCrumbs";
    static props = {
        engagementId: { type: Number, optional: true },
        title: { type: String, optional: true },
    };

    setup() {
        this.action = useService("action");
    }

    get crumbs() {
        return this.env.config?.breadcrumbs || [];
    }

    get earlier() {
        return this.crumbs.slice(0, -1);
    }

    get current() {
        return this.props.title || this.crumbs.at(-1)?.name || "";
    }

    open(crumb) {
        return crumb.onSelected();
    }

    back() {
        const earlier = this.earlier;
        if (earlier.length) {
            return earlier.at(-1).onSelected();
        }
        const context = this.env.services.ea_audit_context;
        if (context?.openDashboard && this.props.engagementId) {
            return context.openDashboard(this.props.engagementId);
        }
        return this.action.doAction("ea_audit_core.action_engagement", { clearBreadcrumbs: true });
    }

    get backLabel() {
        const earlier = this.earlier;
        return earlier.length ? earlier.at(-1).name : _t("Engagement dashboard");
    }
}

function readBase64(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(",")[1] || "");
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
    });
}

export class EaDocsPane extends Component {
    static template = "ea_audit_tools.EaDocsPane";
    static props = {
        engagementId: Number,
        // the documents of what is open: {id, name, url, ext?, version?, by?, date?, typeLabel?, type?, controlId?, controlCode?,
        // carried?, carriedReviewed?} (carried: the mark of a document carried from last year's file)
        docs: { type: Array, optional: true },
        removed: { type: Array, optional: true },
        title: { type: String, optional: true },
        subject: { type: String, optional: true },
        emptyText: { type: String, optional: true },
        hint: { type: String, optional: true },
        // nothing is open yet: the pane says what to click
        idleText: { type: String, optional: true },
        canUpload: { type: Boolean, optional: true },
        canRemove: { type: Boolean, optional: true },
        types: { type: Array, optional: true },
        controls: { type: Array, optional: true },
        onUpload: { type: Function, optional: true },
        onAttach: { type: Function, optional: true },
        onRemove: { type: Function, optional: true },
        onRestore: { type: Function, optional: true },
        onSetType: { type: Function, optional: true },
        onSetControl: { type: Function, optional: true },
    };

    setup() {
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.orm = useService("orm");
        this.fileInput = useRef("fileInput");
        this.state = useState({ over: false, busy: false, type: "", controlId: false, reviewed: {} });
    }

    /** A document carried from last year's file (roll forward): who reviewed it, once someone has. */
    reviewedLabel(doc) {
        return this.state.reviewed[doc.id] || doc.carriedReviewed || "";
    }

    markReviewed(doc) {
        return this.guard(async () => {
            const info = await this.orm.call("ea.audit.task.attachment", "mark_carried_reviewed", [[doc.id]]);
            this.state.reviewed[doc.id] = info.carriedReviewed;
        });
    }

    get docs() {
        return this.props.docs || [];
    }

    get idle() {
        return Boolean(this.props.idleText) && !this.props.docs;
    }

    get type() {
        return this.state.type || (this.props.types?.[0]?.[0] ?? false);
    }

    get options() {
        return { type: this.type, controlId: this.state.controlId || false };
    }

    async guard(job) {
        this.state.busy = true;
        try {
            await job();
        } finally {
            this.state.busy = false;
        }
    }

    choose() {
        this.fileInput.el?.click();
    }

    async upload(files) {
        if (!files.length || !this.props.canUpload || !this.props.onUpload) {
            return;
        }
        await this.guard(async () => {
            const loaded = [];
            for (const file of files) {
                loaded.push({ name: file.name, content: await readBase64(file) });
            }
            await this.props.onUpload(loaded, this.options);
        });
    }

    onFileChange(ev) {
        const files = [...(ev.target.files || [])];
        ev.target.value = "";
        return this.upload(files);
    }

    onDragOver(ev) {
        if (this.props.canUpload) {
            ev.preventDefault();
            this.state.over = true;
        }
    }

    onDragLeave() {
        this.state.over = false;
    }

    onDrop(ev) {
        ev.preventDefault();
        this.state.over = false;
        return this.upload([...(ev.dataTransfer?.files || [])]);
    }

    pickExisting() {
        const options = this.options;
        this.dialog.add(ExistingDocsDialog, {
            engagementId: this.props.engagementId,
            onAttach: (ids) => this.guard(() => this.props.onAttach(ids, options)),
        });
    }

    onTypeChoice(ev) {
        this.state.type = ev.target.value;
    }

    onControlChoice(ev) {
        this.state.controlId = Number(ev.target.value) || false;
    }

    setType(doc, ev) {
        return this.guard(() => this.props.onSetType(doc, ev.target.value));
    }

    setControl(doc, ev) {
        return this.guard(() => this.props.onSetControl(doc, Number(ev.target.value) || false));
    }

    remove(doc) {
        return this.guard(() => this.props.onRemove(doc));
    }

    restore(doc) {
        return this.guard(() => this.props.onRestore(doc));
    }
}
