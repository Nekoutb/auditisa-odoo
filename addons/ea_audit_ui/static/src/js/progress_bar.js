import { rpcBus } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { shellSession } from "./context_service";

// F080: the wait is visible at the top of every screen, where no band covers it. A call quicker
// than this delay shows nothing, and a silent one (the bell's count, a background read) never does.
const SHOW_AFTER_MS = 200;

export const progressBarService = {
    start() {
        if (!shellSession) {
            return;
        }
        const bar = document.createElement("div");
        bar.className = "ea-progress";
        bar.setAttribute("role", "progressbar");
        bar.setAttribute("data-ea-progress", "");
        document.body.append(bar);
        let pending = 0;
        let timer = null;
        rpcBus.addEventListener("RPC:REQUEST", ({ detail }) => {
            if (detail?.settings?.silent) {
                return;
            }
            pending += 1;
            if (!timer) {
                timer = setTimeout(() => bar.classList.add("is-on"), SHOW_AFTER_MS);
            }
        });
        rpcBus.addEventListener("RPC:RESPONSE", ({ detail }) => {
            if (detail?.settings?.silent) {
                return;
            }
            pending = Math.max(0, pending - 1);
            if (!pending) {
                clearTimeout(timer);
                timer = null;
                bar.classList.remove("is-on");
            }
        });
    },
};

registry.category("services").add("ea_audit_progress", progressBarService);
