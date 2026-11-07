import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/** F064: a ratio's name, with what it divides by what on hover. */
export class FormulaLabelField extends Component {
    static template = "ea_audit_tools.FormulaLabelField";
    static props = { ...standardFieldProps };

    get label() {
        return this.props.record.data[this.props.name] || "";
    }

    get formula() {
        return this.props.record.data.formula || "";
    }
}

registry.category("fields").add("ea_formula_label", {
    component: FormulaLabelField,
    supportedTypes: ["char"],
});
