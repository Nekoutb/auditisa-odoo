import { useState } from "@odoo/owl";
import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";

/**
 * Every column title sorts (owner, 2026-11-16). Odoo sorts stored fields on the server; a
 * computed column it cannot sort there is sorted here, on the rows already on screen, and
 * only when all of them are (no grouping, no further page). Nothing is written: the order
 * lives in the screen and a server sort clears it.
 */
const CLIENT_SORTABLE = new Set([
    "char", "text", "integer", "float", "monetary", "date", "datetime", "boolean", "selection", "many2one",
]);

function inShell() {
    return document.body.classList.contains("ea-shell");
}

/** The value a column is sorted on: what the cell shows, empty values last. */
export function sortKey(value, field) {
    if (value === false || value === null || value === undefined || value === "") {
        return null;
    }
    if (field.type === "many2one") {
        return (value.display_name ?? (Array.isArray(value) ? value[1] : "")) || null;
    }
    if (field.type === "selection") {
        const option = (field.selection || []).find(([key]) => key === value);
        return option ? option[1] : String(value);
    }
    if (field.type === "date" || field.type === "datetime") {
        return typeof value.toMillis === "function" ? value.toMillis() : String(value);
    }
    if (field.type === "boolean") {
        return value ? 1 : 0;
    }
    return value;
}

export function compareKeys(a, b) {
    if (a === null || b === null) {
        return a === b ? 0 : a === null ? 1 : -1;
    }
    if (typeof a === "number" && typeof b === "number") {
        return a - b;
    }
    return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        this.eaClientSort = useState({ name: null, asc: true });
    },

    eaAllLoaded(list = this.props.list) {
        return !list.isGrouped && list.records.length >= (list.count ?? list.records.length);
    },

    eaClientSortable(column) {
        if (!inShell() || !column.hasLabel || this.props.list.handleField) {
            return false;
        }
        const field = this.fields[column.name];
        if (!field || field.sortable || !CLIENT_SORTABLE.has(field.type)) {
            return false;
        }
        return this.eaAllLoaded();
    },

    isSortable(column) {
        return super.isSortable(column) || this.eaClientSortable(column);
    },

    getSortableIconClass(column) {
        const sorted = this.eaClientSort.name;
        if (sorted && this.eaAllLoaded()) {
            if (sorted === column.name) {
                return `fa ${this.eaClientSort.asc ? "fa-sort-asc" : "fa-sort-desc"}`;
            }
            return this.isSortable(column) ? "fa fa-sort opacity-0 opacity-100-hover" : "d-none";
        }
        return super.getSortableIconClass(column);
    },

    onClickSortColumn(column) {
        // a column resize ends in a click: Odoo's own guard handles it
        if (this.preventReorder || this.editedRecord) {
            return super.onClickSortColumn(column);
        }
        if (this.eaClientSortable(column)) {
            const same = this.eaClientSort.name === column.name;
            this.eaClientSort.asc = same ? !this.eaClientSort.asc : true;
            this.eaClientSort.name = column.name;
            return;
        }
        if (this.isSortable(column)) {
            this.eaClientSort.name = null;
        }
        return super.onClickSortColumn(column);
    },

    /** The rows of a list, in the order chosen here when a computed column was clicked. */
    eaRows(list) {
        const name = this.eaClientSort?.name;
        if (!name || list !== this.props.list || !this.eaAllLoaded(list)) {
            return list.records;
        }
        const field = this.fields[name];
        const direction = this.eaClientSort.asc ? 1 : -1;
        return list.records
            .map((record, index) => ({ record, index, key: sortKey(record.data[name], field) }))
            .sort((x, y) => {
                const order = compareKeys(x.key, y.key);
                // empty values stay last whichever way the column is sorted
                if (x.key === null || y.key === null) {
                    return order || x.index - y.index;
                }
                return order * direction || x.index - y.index;
            })
            .map((row) => row.record);
    },
});
