import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";
import { EaCrumbs } from "./page_kit";

const ENGAGEMENT = "ea.audit.engagement";

/**
 * Data quality (IPE) (owner-approved mock-up of 2026-11-17): the kinds of file against their
 * timings, each box with its status and reference; a box opened below the matrix with where the
 * data comes from, the checks and their exceptions, the explanations, the conclusion and the two
 * signatures; at the right, the working papers that rely on the file. Every change goes through
 * the server (ea_ipe_*), which answers with the whole page again.
 */
export class IpePage extends Component {
    static template = "ea_audit_tools.IpePage";
    static props = ["*"];
    static components = { EaCrumbs };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const { params = {}, context = {} } = this.props.action || {};
        this.engagementId = Number(params.engagement_id || context.active_id || context.ea_engagement_id);
        this.state = useState({
            p: null, kind: params.kind || null, timing: params.timing || null, open: {}, busy: false,
        });
        this.queue = Promise.resolve();
        useSetupAction({ beforeLeave: () => this.queue.then(() => true) });
        onWillStart(() => this.load());
    }

    get p() {
        return this.state.p;
    }

    get d() {
        return this.state.p?.detail || null;
    }

    async load() {
        this.state.p = await this.orm.call(ENGAGEMENT, "ea_ipe_page", [[this.engagementId], this.state.kind, this.state.timing]);
    }

    select(cell) {
        this.state.kind = cell.kind;
        this.state.timing = cell.timing;
        this.state.open = {};
        return this.load();
    }

    isSelected(cell) {
        return cell.kind === this.state.kind && cell.timing === this.state.timing;
    }

    toggle(check) {
        this.state.open[check.code] = !this.state.open[check.code];
    }

    run(method, args) {
        const job = this.queue.then(async () => {
            this.state.busy = true;
            try {
                this.state.p = await this.orm.call(ENGAGEMENT, method, [[this.engagementId], this.state.kind, this.state.timing, ...args]);
            } catch (error) {
                // what is on the screen must be what is saved
                await this.load();
                throw error;
            } finally {
                this.state.busy = false;
            }
        });
        this.queue = job.catch(() => {});
        return job;
    }

    onSource(field, ev) {
        const value = ev.target.value || false;
        if (this.p.readonly || value === (this.d.source[field] || false)) {
            return;
        }
        return this.run("ea_ipe_save", [{ [field]: value }]);
    }

    onExplain(check, ev) {
        const value = ev.target.value;
        if (this.p.readonly || value === check.explanation) {
            return;
        }
        return this.run("ea_ipe_explain", [check.code, value]);
    }

    conclude(key) {
        if (this.p.readonly || key === this.d.conclusion) {
            return;
        }
        return this.run("ea_ipe_conclude", [key]);
    }

    rerun() {
        return this.run("ea_ipe_rerun", []);
    }

    sign(role) {
        return this.run("ea_ipe_sign", [role]);
    }

    unsign(role) {
        return this.run("ea_ipe_unsign", [role]);
    }

    download() {
        if (this.d?.exportUrl) {
            return this.action.doAction({ type: "ir.actions.act_url", url: this.d.exportUrl, target: "self" });
        }
    }

    async open(target, value) {
        await this.queue;
        const action = await this.orm.call(ENGAGEMENT, "ea_ipe_open", [[this.engagementId], target, value]);
        return this.action.doAction(action, { onClose: () => this.load() });
    }
}

registry.category("actions").add("ea_audit_tools.ipe_page", IpePage);
