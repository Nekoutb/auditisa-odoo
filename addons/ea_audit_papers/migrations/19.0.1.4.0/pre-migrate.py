"""Roll forward (owner's ruling of 2026-11-16): an evidence file carried from last year's file is
marked, and who reviewed it is kept. Three empty columns, no default: no row is written, so the
archive triggers are never asked (an archived file refuses every row change). Odoo then finds the
columns made and writes nothing.
"""

import logging

_logger = logging.getLogger(__name__)

COLUMNS = (
    ("carried_from_year", "integer"),
    ("carried_reviewed_by_id", "integer"),
    ("carried_reviewed_at", "timestamp without time zone"),
)


def migrate(cr, version):
    for column, kind in COLUMNS:
        cr.execute(f'ALTER TABLE IF EXISTS "ea_audit_task_attachment" ADD COLUMN IF NOT EXISTS "{column}" {kind}')
    _logger.info("roll forward: columns %s ready on ea_audit_task_attachment", ", ".join(c for c, _k in COLUMNS))
