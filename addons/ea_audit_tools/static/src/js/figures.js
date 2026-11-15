import { registry } from "@web/core/registry";
import { formatFloat } from "@web/core/utils/numbers";
import { patch } from "@web/core/utils/patch";
import { FloatField, floatField } from "@web/views/fields/float/float_field";

/**
 * Figures as an accountant writes them (owner, 2026-11-15): a negative in brackets,
 * (1 250) not -1 250, and FCFA amounts without decimals. Ratios and percentages keep
 * their decimals. Display only: what a person types is read as before.
 */

/** The text of a negative figure in brackets; a figure that rounds to nothing loses its sign. */
export function bracketed(value, text) {
    if (typeof value !== "number" || typeof text !== "string" || !text.startsWith("-")) {
        return text;
    }
    const digits = text.slice(1);
    if (!/[1-9]/.test(digits)) {
        return digits; // -0 and -0.00 read 0 and 0.00
    }
    return `(${digits})`;
}

/** An FCFA amount: grouped as the language groups, no decimals, negatives in brackets. */
export function amount(value) {
    if (value === false || value === null || value === undefined || value === "") {
        return "";
    }
    return bracketed(value, formatFloat(value, { digits: [false, 0] }));
}

// Every number Odoo writes in a list cell, a group row or a total: negatives in brackets.
const formatters = registry.category("formatters");
for (const name of ["float", "integer"]) {
    if (formatters.contains(name)) {
        const base = formatters.get(name);
        formatters.add(name, (value, options) => bracketed(value, base(value, options)), { force: true });
    }
}
formatters.add("ea_amount", (value) => amount(value), { force: true });

// A figure shown read-only in a form: negatives in brackets too.
patch(FloatField.prototype, {
    get formattedValue() {
        const text = super.formattedValue;
        return this.props.readonly ? bracketed(this.props.record.data[this.props.name], text) : text;
    },
});

/** widget="ea_amount": an FCFA amount. Read-only it shows no decimals and brackets a negative. */
export class EaAmountField extends FloatField {
    get formattedValue() {
        if (this.props.readonly) {
            return amount(this.props.record.data[this.props.name]);
        }
        return super.formattedValue;
    }
}

registry.category("fields").add("ea_amount", {
    ...floatField,
    component: EaAmountField,
    extractProps: (...args) => ({ ...floatField.extractProps(...args), digits: [18, 0] }),
});
