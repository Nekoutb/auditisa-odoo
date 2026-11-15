"""Import matching (owner's rulings of 2026-11-15).

The file's fingerprint (SHA-256) is removed altogether: its column goes from the trial balance
versions and from the imported datasets. Only the start of a tests-of-details plan worked out on
the screen read it, and that now starts from the ledger's own figures; a plan already stored keeps
the start it stored.

One wizard replaces the two import wizards: their three tables go, with their screens. They held
what a person had in front of them while importing, never an import.

No version, dataset, row, sampling run or selection design is touched. A version saved as invalid
before this release stays, and can now be deleted like any other. Each step does nothing if it was
already done, so a second run is harmless.
"""

import logging

_logger = logging.getLogger(__name__)

COLUMNS = {
    "ea_audit_tb_version": ("source_sha256",),
    "ea_audit_dataset": ("source_sha256",),
}
# Transient tables of the wizards the one import wizard replaces. The map goes before its wizard.
TABLES = ("ea_audit_dataset_import_map", "ea_audit_dataset_import_wizard", "ea_audit_tb_import_wizard")
# Their screens name models that no longer exist: deleted here, and nothing makes them again.
STALE_VIEWS = (
    ("ea_audit_tools", "view_tb_import_wizard"),
    ("ea_audit_tools", "view_dataset_import_wizard"),
)


def _drop_views(cr):
    ids = set()
    for module, name in STALE_VIEWS:
        cr.execute("SELECT res_id FROM ir_model_data WHERE module = %s AND name = %s AND model = 'ir.ui.view'", [module, name])
        ids.update(row[0] for row in cr.fetchall())
    if not ids:
        return 0
    # Anything that extends them goes too (ON DELETE CASCADE does the same in the database).
    cr.execute("""
        WITH RECURSIVE tree(id) AS (
            SELECT id FROM ir_ui_view WHERE id = ANY(%s)
            UNION SELECT v.id FROM ir_ui_view v JOIN tree t ON v.inherit_id = t.id
        ) SELECT id FROM tree""", [list(ids)])
    every = [row[0] for row in cr.fetchall()]
    cr.execute("DELETE FROM ir_model_data WHERE model = 'ir.ui.view' AND res_id = ANY(%s)", [every])
    cr.execute("DELETE FROM ir_ui_view WHERE id = ANY(%s)", [every])
    return len(every)


def migrate(cr, version):
    for table, columns in COLUMNS.items():
        for column in columns:
            cr.execute(f'ALTER TABLE IF EXISTS "{table}" DROP COLUMN IF EXISTS "{column}" CASCADE')
    _logger.info("import matching: fingerprint column dropped from %s", ", ".join(COLUMNS))
    _logger.info("import matching: %s screen(s) of the former import wizards deleted", _drop_views(cr))
    for table in TABLES:
        cr.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    _logger.info("import matching: tables %s dropped", ", ".join(TABLES))
