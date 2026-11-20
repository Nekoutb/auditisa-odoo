import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * EAGLR (owner's mock-up "eaglr", 20/11/2026): the source strip, the score and the four sections
 * with the information rows. Every word and figure comes from the server already written in the
 * reader's language (report.view): this widget only lays them out and opens what a row links to.
 */
export class EaEaglrReport extends Component {
    static template = "ea_audit_tools.EaEaglrReport";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
    }

    get view() {
        const report = this.props.record.data[this.props.name] || {};
        return report.view || { strip: [], scores: [], head: [], sections: [] };
    }

    async open(row) {
        const action = await this.orm.call("ea.audit.eaglr", "eaglr_open", [[this.props.record.resId], row.key]);
        if (action) {
            await this.action.doAction(action);
        }
    }
}

registry.category("fields").add("ea_eaglr_report", { component: EaEaglrReport, supportedTypes: ["json"] });
