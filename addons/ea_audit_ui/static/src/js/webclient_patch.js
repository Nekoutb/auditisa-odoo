import { patch } from "@web/core/utils/patch";
import { registry } from "@web/core/registry";
import "@web/views/fields/datetime/datetime_field";
import { WebClient } from "@web/webclient/webclient";
import { shellSession } from "./context_service";
import { EaTopBar } from "./top_bar";

WebClient.components = { ...WebClient.components, EaTopBar };

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
