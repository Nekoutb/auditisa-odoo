import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";

const ENGAGEMENT = "ea.audit.engagement";

/**
 * Procedure design on one page (owner's mock-ups of 2026-11-16, "mock-proc-design"). Section 1
 * lists the controls ticked "To test" on the SCOT pages; section 2 the tests of details of each
 * significant account: the mandatory procedures (MSP) ticked and locked, the alternatives (ASP)
 * ticked by the team, with the ones the combined risk suggests marked. A click saves at once,
 * through the server's rules; every word of data comes from the server (ea_procedure_design_page).
 */
export class ProcedureDesignPage extends Component {
    static template = "ea_audit_tools.ProcedureDesignPage";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const { params = {}, context = {} } = this.props.action || {};
        this.engagementId = Number(params.engagement_id || context.active_id || context.ea_engagement_id);
        this.state = useState({
            p: null, tab: params.tab === "toc" ? "toc" : "tod", folded: {}, showMore: {}, adding: null,
            text: "", picked: {}, busy: false,
        });
        this.queue = Promise.resolve();
        useSetupAction({ beforeLeave: () => this.queue.then(() => true) });
        onWillStart(() => this.load());
    }

    get p() {
        return this.state.p;
    }

    async load() {
        this.state.p = await this.orm.call(ENGAGEMENT, "ea_procedure_design_page", [[this.engagementId]]);
        if (!this.p.accounts.length && this.p.controls.length) {
            this.state.tab = "toc";
        }
    }

    // ---- reading -----------------------------------------------------------

    get progressText() {
        const { done, total } = this.p.progress;
        return _t("%(done)s of %(total)s accounts designed", { done, total });
    }

    get progressStyle() {
        const { done, total } = this.p.progress;
        return `width: ${Math.round((100 * done) / (total || 1))}%`;
    }

    levelClass(level) {
        return { minimal: "is-good", low: "is-good", moderate: "is-warn", high: "is-bad" }[level] || "is-open";
    }

    whyClass(tone) {
        return {
            "risk-high": "is-bad", "risk-moderate": "is-warn", "risk-low": "is-good",
            choice: "is-choice", condition: "is-cond",
        }[tone] || "is-plain";
    }

    kindTip(row) {
        if (row.kind === "MSP") {
            return _t("Mandatory substantive procedure: must be performed for this assertion");
        }
        if (row.kind === "ASP") {
            return _t("Alternative substantive procedure: chosen at design for the risk");
        }
        return _t("Own procedure: written by the team for this account");
    }

    kindLabel(row) {
        return row.kind === "custom" ? _t("own") : row.kind;
    }

    rowTip(row) {
        return [row.summary, row.when].filter(Boolean).join("\n");
    }

    lockText(row) {
        if (row.locked) {
            return _t("mandatory");
        }
        if (row.selected && row.started) {
            return row.state === "done" ? _t("performed, cannot be removed") : _t("started, cannot be removed");
        }
        return "";
    }

    dot(row, code) {
        return { covered: "●", would: "○" }[row.dots[code]] || "";
    }

    stateClass(state) {
        return { done: "is-done", started: "is-warn", draft: "is-open" }[state] || "is-open";
    }

    altText(account) {
        if (!account.offered) {
            return "";
        }
        if (!account.chosen) {
            return _t("no alternative chosen yet");
        }
        return _t("%(chosen)s of %(offered)s alternatives chosen", { chosen: account.chosen, offered: account.offered });
    }

    mandatoryText(account) {
        return _t("%s mandatory", account.mandatory);
    }

    moreText(account) {
        const codes = account.more.map((item) => `${item.code} ${item.title}`).join(", ");
        return _t("%(count)s more alternatives (%(codes)s)", { count: account.more.length, codes });
    }

    missingText(account, code) {
        return _t("%s is High: choose at least one alternative (ASP) for it before the design is complete.", code);
    }

    toAssessText(account) {
        return _t("Combined risk still to assess on %s: the design waits for it.", account.to_assess.join(", "));
    }

    legacyText(account) {
        return _t("%s procedure(s) chosen before the library: they stay on the earlier list.", account.legacy);
    }

    isFolded(account) {
        const own = this.state.folded[account.code];
        return own === undefined ? false : own;
    }

    toggle(account) {
        this.state.folded[account.code] = !this.isFolded(account);
    }

    // ---- choosing ------------------------------------------------------------

    canTick(row) {
        return !this.p.readonly && !row.locked && !(row.selected && row.started);
    }

    tick(account, row) {
        if (!this.canTick(row)) {
            return;
        }
        return this.call("ea_procedure_choose", [account.code, row.code, !row.selected]);
    }

    reliance(control, value) {
        if (this.p.readonly || control.reliance === value) {
            return;
        }
        return this.call("ea_procedure_reliance", [control.id, value]);
    }

    startAdding(account) {
        this.state.adding = account.code;
        this.state.text = "";
        this.state.picked = {};
    }

    async addOwn(account) {
        const assertions = account.levels.map((level) => level.assertion).filter((code) => this.state.picked[code]);
        await this.call("ea_procedure_add", [account.code, this.state.text, assertions]);
        this.state.adding = null;
    }

    call(method, args) {
        const run = this.queue.then(async () => {
            this.state.busy = true;
            try {
                this.state.p = await this.orm.call(ENGAGEMENT, method, [[this.engagementId], ...args]);
            } catch (error) {
                // what is on the screen must be what is saved
                await this.load();
                throw error;
            } finally {
                this.state.busy = false;
            }
        });
        this.queue = run.catch(() => {});
        return run;
    }

    // ---- leaving -------------------------------------------------------------

    async draw(row) {
        await this.queue;
        const action = await this.orm.call(ENGAGEMENT, "ea_procedure_draw", [[this.engagementId], row.id]);
        return this.action.doAction(action, { onClose: () => this.load() });
    }

    async open(method, resId = null) {
        await this.queue;
        const action = await this.orm.call(ENGAGEMENT, "ea_procedure_open", [[this.engagementId], method, resId]);
        return this.action.doAction(action);
    }
}

registry.category("actions").add("ea_audit_tools.procedure_design", ProcedureDesignPage);
