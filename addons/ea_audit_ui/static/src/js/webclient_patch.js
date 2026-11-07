import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import { DateTimeField } from "@web/views/fields/datetime/datetime_field";
import { Message } from "@mail/core/common/message_model";
import { WebClient } from "@web/webclient/webclient";
import { shellSession } from "./context_service";
import { EaTopBar } from "./top_bar";

WebClient.components = { ...WebClient.components, EaTopBar };

// F029: the firm reads its times on its own clock, with the zone said, whatever the browser's.
if (shellSession?.tz) {
    luxon.Settings.defaultZone = shellSession.tz;
    const label = shellSession.tz_label;
    const formatters = registry.category("formatters");
    const formatDate = formatters.get("date");
    const formatDatetime = formatters.get("datetime");
    // A list column reads through these, a form and a widget through the field below: DD/MM/YYYY on both.
    const numericDate = (value, options = {}) => formatDate(value, { ...options, numeric: true });
    numericDate.extractOptions = formatDate.extractOptions;
    formatters.add("date", numericDate, { force: true });
    const numericDatetime = (value, options = {}) => {
        const text = formatDatetime(value, { ...options, numeric: true });
        return text && options.showTime !== false ? `${text} ${label}` : text;
    };
    numericDatetime.extractOptions = formatDatetime.extractOptions;
    formatters.add("datetime", numericDatetime, { force: true });
    patch(DateTimeField.prototype, {
        getFormattedValue(valueIndex) {
            const text = super.getFormattedValue(valueIndex, true);
            return text && this.field.type === "datetime" && this.props.showTime !== false ? `${text} ${label}` : text;
        },
    });
    patch(Message.prototype, {
        get dateSimple() {
            return `${super.dateSimple} ${label}`;
        },
        get dateSimpleWithDay() {
            return `${super.dateSimpleWithDay} ${label}`;
        },
    });
}

// The firm reads DD/MM/YYYY everywhere: Odoo's date fields default to a short month name
// in lists and forms. A view that sets the option itself keeps its choice.
if (shellSession) {
    for (const name of ["date", "datetime", "daterange"]) {
        const field = registry.category("fields").get(name, null);
        if (field?.extractProps) {
            const extractProps = field.extractProps;
            field.extractProps = (fieldInfo, dynamicInfo) =>
                extractProps(
                    { ...fieldInfo, options: { numeric: true, ...fieldInfo.options } },
                    dynamicInfo
                );
        }
    }
}

// An audit user gets the firm's top bar instead of Odoo's navbar and app grid.
patch(WebClient.prototype, {
    setup() {
        super.setup();
        this.eaShell = Boolean(shellSession);
        if (this.eaShell) {
            document.body.classList.add("ea-shell");
        }
    },
});
