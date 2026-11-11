import { onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { FormController } from "@web/views/form/form_controller";
import { formView } from "@web/views/form/form_view";

// The screen of a firm being set up reads itself again every few seconds while the set-up is under way,
// so the steps and the progress bar move by themselves. Nothing is asked for once it is finished or
// cancelled, nor while the browser tab is hidden. A reading that fails is ignored: the next one tries again.

const POLL_MS = 5000;

export class ProvisionJobFormController extends FormController {
    setup() {
        super.setup();
        let timer = null;
        let reading = false;
        onMounted(() => {
            timer = setInterval(async () => {
                const root = this.model.root;
                if (reading || document.hidden || !root || root.data.state !== "waiting") {
                    return;
                }
                reading = true;
                try {
                    await this.model.load();
                } catch {
                    // the next tick tries again
                } finally {
                    reading = false;
                }
            }, POLL_MS);
        });
        onWillUnmount(() => clearInterval(timer));
    }
}

registry.category("views").add("ea_provision_job_form", {
    ...formView,
    Controller: ProvisionJobFormController,
});
