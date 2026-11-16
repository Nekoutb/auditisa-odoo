import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";

const MODEL = "ea.audit.engagement.profile";

/**
 * The engagement profile questionnaire (owner's mock-up of 2026-11-15): seven sections, one at a
 * time, a live level panel. Every word and every rule comes from the server; this component only
 * shows what ea_profile_screen returns and sends each answer as it is given.
 */
export class ProfileAction extends Component {
    static template = "ea_audit_core.ProfileAction";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const { params = {}, context = {} } = this.props.action || {};
        this.profileId = Number(params.profile_id || params.active_id || context.active_id);
        this.state = useState({ p: null, section: 0, saving: false, savedOnce: false });
        // answers given and not yet accepted by the server (sent, or held for a sub-question)
        this.pending = {};
        this.queue = Promise.resolve();
        useSetupAction({ beforeLeave: () => this.queue.then(() => true) });
        onWillStart(() => this.load(true));
    }

    get p() {
        return this.state.p;
    }

    get current() {
        return this.p.sections[this.state.section];
    }

    async load(first = false) {
        const payload = await this.orm.call(MODEL, "ea_profile_screen", [[this.profileId]]);
        this.state.p = payload;
        if (first) {
            const open = payload.sections.findIndex((s) => !s.done);
            this.state.section = open < 0 ? 0 : open;
        }
    }

    // ---- reading -----------------------------------------------------------

    value(field) {
        return field in this.pending ? this.pending[field] : this.p.answers[field];
    }

    get progressStyle() {
        const { answered, total } = this.p.progress;
        return `width: ${Math.round((100 * answered) / (total || 1))}%`;
    }

    toggles(question) {
        return question.parts.filter((part) => part.visible && part.kind === "toggle");
    }

    sectionLabel() {
        return this.p.words.section.replace("{n}", String(this.state.section + 1));
    }

    levelClass() {
        return {
            complex: "is-complex",
            non_complex: "is-noncomplex",
            very_simple: "is-simple",
        }[this.p.panel.level] || "is-open";
    }

    // ---- moving ------------------------------------------------------------

    go(index) {
        if (index >= 0 && index < this.p.sections.length) {
            this.state.section = index;
        }
    }

    // ---- answering ---------------------------------------------------------

    answer(field, value) {
        if (this.p.readonly) {
            return;
        }
        this.pending = { ...this.pending, [field]: value };
        // shown at once; the server's answer follows a moment later
        this.state.p = { ...this.p, answers: { ...this.p.answers, [field]: value } };
        const run = this.queue.then(() => this.flush());
        this.queue = run.catch(() => {});
        return run;
    }

    async flush() {
        const sent = { ...this.pending };
        if (!Object.keys(sent).length) {
            return;
        }
        this.state.saving = true;
        try {
            const payload = await this.orm.call(MODEL, "ea_profile_save", [[this.profileId], sent]);
            if (!payload.held) {
                const left = {};
                for (const [field, value] of Object.entries(this.pending)) {
                    if (!(field in sent) || sent[field] !== value) {
                        left[field] = value;
                    }
                }
                this.pending = left;
                this.state.savedOnce = true;
            }
            this.state.p = payload;
        } catch (error) {
            // what is on the screen must be what is saved
            this.pending = {};
            await this.load();
            throw error;
        } finally {
            this.state.saving = false;
        }
    }

    async conclude() {
        await this.queue;
        if (!this.p.conclude.can) {
            return;
        }
        this.state.p = await this.orm.call(MODEL, "ea_profile_conclude", [[this.profileId]]);
    }

    /** Back to where the user came from (owner, 2026-11-16), as Odoo's breadcrumb does; with no
     * trail (a bookmark), to the engagement. The answers are saved already. */
    get backLabel() {
        const crumbs = this.env.config?.breadcrumbs || [];
        return crumbs.length > 1 ? crumbs.at(-2).name : this.p.words.back;
    }

    async back() {
        await this.queue;
        const crumbs = this.env.config?.breadcrumbs || [];
        if (crumbs.length > 1) {
            return crumbs.at(-2).onSelected();
        }
        return this.openAction("action_save_for_later");
    }

    async openAction(method) {
        await this.queue;
        const action = await this.orm.call(MODEL, method, [[this.profileId]]);
        return this.action.doAction(action);
    }
}

registry.category("actions").add("ea_audit_core.profile", ProfileAction);
