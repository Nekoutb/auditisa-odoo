import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";

/** In Missions a row or a card goes to the mission's dashboard, not to a raw form. */
class MissionsListController extends ListController {
    setup() {
        super.setup();
        this.eaContext = useService("ea_audit_context");
    }

    async openRecord(record) {
        return this.eaContext.openDashboard(record.resId);
    }
}

class MissionsKanbanController extends KanbanController {
    setup() {
        super.setup();
        this.eaContext = useService("ea_audit_context");
    }

    async openRecord(record) {
        return this.eaContext.openDashboard(record.resId);
    }
}

registry.category("views").add("ea_missions_list", { ...listView, Controller: MissionsListController });
registry.category("views").add("ea_missions_kanban", { ...kanbanView, Controller: MissionsKanbanController });
