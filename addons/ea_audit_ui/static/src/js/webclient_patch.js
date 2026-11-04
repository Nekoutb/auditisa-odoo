import { patch } from "@web/core/utils/patch";
import { WebClient } from "@web/webclient/webclient";
import { shellSession } from "./context_service";
import { EaTopBar } from "./top_bar";

WebClient.components = { ...WebClient.components, EaTopBar };

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
