import { Component } from "@odoo/owl";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useSpecialData } from "@web/views/fields/relational_utils";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

/**
 * Relevant assertions (owner's mock-up of 2026-11-16): a list with a tick box per assertion,
 * its full name and what it means; several may be ticked. Once chosen, the field shows only
 * the codes (C, E, A, V, P, RO), the full names on hover.
 */
export class AssertionPickerField extends Component {
    static template = "ea_audit_tools.AssertionPickerField";
    static components = { Dropdown, DropdownItem };
    static props = { ...standardFieldProps };

    setup() {
        this.options = useSpecialData((orm, props) => {
            const { relation } = props.record.fields[props.name];
            return orm.searchRead(relation, [], ["code", "name", "description"], { order: "sequence, id" });
        });
    }

    get all() {
        return this.options.data || [];
    }

    get list() {
        return this.props.record.data[this.props.name];
    }

    get chosen() {
        const ids = this.list.currentIds;
        return this.all.filter((option) => ids.includes(option.id));
    }

    get hint() {
        const names = this.chosen.map((option) => `${option.code} ${option.name}`);
        return names.length ? names.join(" · ") : _t("Choose the relevant assertions");
    }

    isSelected(option) {
        return this.list.currentIds.includes(option.id);
    }

    toggle(option) {
        const change = this.isSelected(option) ? { remove: [option.id] } : { add: [option.id] };
        return this.list.addAndRemove(change);
    }
}

registry.category("fields").add("ea_assertion_picker", {
    component: AssertionPickerField,
    displayName: _t("Assertion picker"),
    supportedTypes: ["many2many"],
    relatedFields: [{ name: "display_name", type: "char" }],
});
