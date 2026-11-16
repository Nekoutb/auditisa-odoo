import { Component, onWillStart, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useSetupAction } from "@web/search/action_hook";

const ENGAGEMENT = "ea.audit.engagement";
const CELL = "ea.audit.cra.assessment";

/**
 * The combined risk assessment on one page (owner's mock-up of 2026-11-16): the significant
 * accounts, each folding open on its relevant assertions only. A click on Lower/Higher or
 * Rely/Not rely saves that one cell at once, through the cell's own rules; the suggestions sit
 * beside the choices in grey and never stand in for them: the level reads "To assess" until
 * both risks are chosen. Every word of data comes from the server (ea_cra_page).
 */
export class CraPage extends Component {
    static template = "ea_audit_tools.CraPage";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        const { params = {}, context = {} } = this.props.action || {};
        this.engagementId = Number(params.engagement_id || context.active_id || context.ea_engagement_id);
        this.state = useState({ p: null, onlyOpen: false, folded: {}, hints: {}, busy: false });
        // what was typed in a basis box since that cell's last choice: the basis or reason a
        // choice needs must be written for it, an older text is no reason (UAT B51)
        this.typed = {};
        this.queue = Promise.resolve();
        useSetupAction({ beforeLeave: () => this.queue.then(() => true) });
        onWillStart(() => this.load());
    }

    get p() {
        return this.state.p;
    }

    async load() {
        this.state.p = await this.orm.call(ENGAGEMENT, "ea_cra_page", [[this.engagementId]]);
    }

    // ---- reading -----------------------------------------------------------

    get progressText() {
        const { done, total } = this.p.progress;
        return _t("%(done)s of %(total)s assessed", { done, total });
    }

    get progressStyle() {
        const { done, total } = this.p.progress;
        return `width: ${Math.round((100 * done) / (total || 1))}%`;
    }

    get accounts() {
        if (!this.state.onlyOpen) {
            return this.p.accounts;
        }
        return this.p.accounts.filter((account) => account.done < account.total);
    }

    cellsOf(account) {
        return this.state.onlyOpen ? account.cells.filter((cell) => cell.level === "to_assess") : account.cells;
    }

    isFolded(account) {
        const own = this.state.folded[account.code];
        if (own !== undefined) {
            return own;
        }
        // an account fully assessed starts folded, as in the mock-up
        return !this.state.onlyOpen && account.total > 0 && account.done === account.total;
    }

    toggle(account) {
        this.state.folded[account.code] = !this.isFolded(account);
    }

    suggested(kind, value) {
        const label = (this.p.choices[kind].find(([key]) => key === value) || [value, value])[1];
        return _t("suggested %s", label);
    }

    risksText(cell) {
        return _t("linked risks: %s", cell.risk_count);
    }

    levelClass(level) {
        return {
            minimal: "is-good",
            low: "is-good",
            low_sr: "is-good",
            moderate: "is-warn",
            high: "is-bad",
            high_sr: "is-bad",
        }[level] || "is-open";
    }

    // ---- choosing ------------------------------------------------------------

    choose(cell, field, value) {
        if (this.p.readonly || cell[field] === value) {
            return;
        }
        const patch = { [field]: value };
        const fresh = (this.typed[cell.id] || "").trim();
        const reassessment = Boolean(cell.ir || cell.cr);
        const relyUnsupported = field === "cr" && value === "rely" && cell.cr !== "rely" && cell.rely_needs_basis;
        if (relyUnsupported || (this.p.locked && reassessment)) {
            if (!fresh) {
                this.state.hints[cell.id] = relyUnsupported
                    ? _t("Write in the box why you rely without a tested control, then click Rely again.")
                    : _t("Planning is closed: write the reason for the change in the box, then click again.");
                return;
            }
        }
        if (relyUnsupported) {
            patch.cr_basis = fresh;
        }
        if (reassessment && fresh) {
            patch.reason = fresh;
        }
        return this.save(cell, patch, true);
    }

    onBasis(cell, ev) {
        if (this.p.readonly) {
            return;
        }
        const text = ev.target.value.trim();
        this.typed[cell.id] = text;
        delete this.state.hints[cell.id];
        return this.save(cell, { ir_basis: text || false, cr_basis: text || false }, false);
    }

    save(cell, patch, choice) {
        const run = this.queue.then(async () => {
            this.state.busy = true;
            try {
                this.state.p = await this.orm.call(CELL, "ea_cra_page_save", [[cell.id], patch]);
                if (choice) {
                    delete this.typed[cell.id];
                    delete this.state.hints[cell.id];
                }
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

    async open(method) {
        await this.queue;
        const action = await this.orm.call(ENGAGEMENT, method, [[this.engagementId]]);
        return this.action.doAction(action);
    }
}

registry.category("actions").add("ea_audit_tools.cra_page", CraPage);
