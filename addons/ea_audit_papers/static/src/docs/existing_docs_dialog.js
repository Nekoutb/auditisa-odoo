import { Component, onWillStart, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";

/**
 * "Attach a document" from what is already in THIS engagement (owner, 2026-11-16): a searchable
 * list (name, type, task, uploader, date) of the engagement's live files, latest version of each,
 * several at once. The server lists the engagement's own files only and attaches them without a
 * new upload (ea_document_library, attach_existing). The page that opens the dialog says what
 * "attach" means for it through `onAttach(ids)`.
 */
export class ExistingDocsDialog extends Component {
    static template = "ea_audit_papers.ExistingDocsDialog";
    static components = { Dialog };
    static props = {
        engagementId: Number,
        onAttach: Function,
        close: Function,
        title: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({ search: "", rows: null, picked: {}, busy: false });
        this.search = useDebounced(() => this.load(), 250);
        onWillStart(() => this.load());
    }

    get title() {
        return this.props.title || _t("Attach a document of this engagement");
    }

    get pickedIds() {
        return Object.keys(this.state.picked).filter((id) => this.state.picked[id]).map(Number);
    }

    async load() {
        this.state.rows = await this.orm.call("ea.audit.engagement", "ea_document_library", [
            [this.props.engagementId],
            this.state.search,
        ]);
    }

    onSearch(ev) {
        this.state.search = ev.target.value;
        this.search();
    }

    toggle(row) {
        this.state.picked[row.id] = !this.state.picked[row.id];
    }

    async attach() {
        const ids = this.pickedIds;
        if (!ids.length || this.state.busy) {
            return;
        }
        this.state.busy = true;
        try {
            await this.props.onAttach(ids);
            this.props.close();
        } finally {
            this.state.busy = false;
        }
    }
}
