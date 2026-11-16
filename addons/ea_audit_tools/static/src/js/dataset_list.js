import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";

/**
 * The upload lists (owner's request of 2026-11-16): one line above the list says how far the
 * next-year general ledger reaches, and warns when it is too short for the cut-off tests.
 * The words come from the server, translated.
 */
export class SubsequentCoverageLine extends Component {
    static template = "ea_audit_tools.SubsequentCoverageLine";
    static props = { engagementId: Number };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ data: null });
        onWillStart(async () => {
            this.state.data = await this.orm.call("ea.audit.engagement", "ea_subsequent_overview", [[this.props.engagementId]]);
        });
    }
}

export class DatasetListController extends ListController {
    static template = "ea_audit_tools.DatasetListView";
    static components = { ...ListController.components, SubsequentCoverageLine };

    get eaEngagementId() {
        const context = this.props.context || {};
        return context.ea_engagement_id || context.default_engagement_id || 0;
    }
}

registry.category("views").add("ea_dataset_list", {
    ...listView,
    Controller: DatasetListController,
});
