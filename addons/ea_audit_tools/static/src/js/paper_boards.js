import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/** What a tool holds for the paper in hand, and the way into the tool. One component, one payload. */
export class ToolBoard extends Component {
    static template = "ea_audit_tools.ToolBoard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ board: null });
        onWillStart(async () => {
            this.state.board = await this.orm.call("ea.audit.file.item", "ea_paper_board", [[this.props.fileItemId]]);
        });
    }

    open(link) {
        return this.action.doAction(link.action);
    }
}

const boards = registry.category("ea_audit_paper_boards");
const entry = (fr, en) => ({ Component: ToolBoard, label: { fr, en } });

boards.add("P6.1", entry("Outil de matérialité", "Materiality tool"));
boards.add("P6.2", entry("Comptes significatifs", "Significant accounts"));
boards.add("S3.1", entry("Risques et CRA", "Risks and CRA"));
boards.add("C1.1", entry("Anomalies (SAD)", "Differences (SAD)"));
for (let index = 1; index <= 34; index++) {
    boards.add(`E4.${index}`, entry("Feuille maîtresse", "Lead schedule"));
}
