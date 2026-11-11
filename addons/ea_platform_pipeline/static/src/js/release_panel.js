import { Component, markup, onWillUnmount, useEffect, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useRecordObserver } from "@web/model/relational_model/utils";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// The Versions panel at the top of the Status page (models/release_panel.py writes its HTML).
//
// Two things the plain HTML field cannot do:
//   - its two buttons, Promote to Staging and Promote to Production, open the confirmation screen;
//   - while a promotion is going on, the panel is asked for again every few seconds, so the progress bar
//     moves by itself. Nothing is asked for when nothing is going on, nor while the browser tab is hidden.
// Only the panel is fetched and redrawn, and only when it changed: the rest of the page does not flicker.
// When the promotion ends, the page's record is read once more so that the tabs below catch up.

const POLL_MS = 5000;
const MAX_FAILURES = 5;

export class ReleasePanel extends Component {
    static template = "ea_platform_pipeline.ReleasePanel";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ html: "", busy: false });
        this.timer = null;
        this.failures = 0;
        this.alive = true;
        // Each time the page's record is read (the web client may first show what it kept from the last visit,
        // then the fresh answer), the panel takes what the record says.
        useRecordObserver((record, props) => {
            this.state.html = String(record.data[props.name] || "");
            this.state.busy = Boolean(record.data.release_busy);
        });
        useEffect(
            () => {
                this.schedule();
            },
            () => [this.state.busy]
        );
        onWillUnmount(() => {
            this.alive = false;
            this.stop();
        });
    }

    get html() {
        // Written by the server from escaped parts (models/release_panel.py): safe to show as it is.
        return markup(this.state.html);
    }

    stop() {
        if (this.timer) {
            clearTimeout(this.timer);
            this.timer = null;
        }
    }

    schedule() {
        this.stop();
        if (this.alive && this.state.busy) {
            this.timer = setTimeout(() => this.poll(), POLL_MS);
        }
    }

    async poll() {
        this.timer = null;
        if (!this.alive) {
            return;
        }
        if (document.hidden) {
            this.schedule();
            return;
        }
        await this.refresh();
        this.schedule();
    }

    async refresh() {
        const resId = this.props.record.resId;
        if (!resId) {
            return;
        }
        let panel;
        try {
            panel = await this.orm.silent.call("platform.environment", "release_panel", [[resId]]);
        } catch {
            // The network or the session: try a few more times, then stop quietly. "Read again" still works.
            this.failures += 1;
            if (this.failures >= MAX_FAILURES) {
                this.state.busy = false;
            }
            return;
        }
        if (!this.alive) {
            return;
        }
        this.failures = 0;
        const wasBusy = this.state.busy;
        if (panel.html !== this.state.html) {
            this.state.html = panel.html;
        }
        this.state.busy = Boolean(panel.busy);
        if (wasBusy && !this.state.busy) {
            // It ended: the History and Monitor tabs below are read again, once.
            try {
                await this.props.record.load();
            } catch {
                // The panel itself is already up to date.
            }
        }
    }

    async onClick(ev) {
        const button = ev.target.closest("button[data-ea-action]");
        if (!button || button.disabled) {
            return;
        }
        const method = button.dataset.eaAction;
        if (!["action_promote_staging", "action_promote_production"].includes(method)) {
            return;
        }
        button.disabled = true;
        try {
            // As a button of the form would: the server's answer (the confirmation screen) is opened, and the
            // panel is read again when that screen closes.
            const resId = this.props.record.resId;
            await this.action.doActionButton({
                type: "object",
                name: method,
                resModel: "platform.environment",
                resId,
                resIds: [resId],
                context: this.props.record.context,
                onClose: () => this.refresh(),
            });
        } finally {
            button.disabled = false;
        }
    }
}

export const releasePanel = {
    component: ReleasePanel,
    supportedTypes: ["html"],
    fieldDependencies: [{ name: "release_busy", type: "boolean" }],
};

registry.category("fields").add("ea_release_panel", releasePanel);
