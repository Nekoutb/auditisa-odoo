"""Engagement profile questionnaire (owner's rulings of 2026-11-15).

The engagement gets one column, the first day of the audit period, created here empty, with no
default: an empty column is written by no row update,
so the archive triggers are never asked (an archived file refuses every row change, the lesson of
2026-11-15 on demo-akwa). Odoo then finds the column made and writes nothing.
The nature of the service in words, tried on the way and dropped by the owner's ruling, is removed
where a test database got it; DROP COLUMN writes no row either.

Nothing else changes for the files opened before: their level, their first-year box, their fixed
nature and their tasks stay as they are. Their questionnaire is empty and holds nothing up. The
questionnaire itself is a new table, which Odoo creates; it only ever receives new rows.
"""

import logging

_logger = logging.getLogger(__name__)

COLUMNS = (
    ("period_start", "date"),
)


def migrate(cr, version):
    for column, kind in COLUMNS:
        cr.execute(f'ALTER TABLE IF EXISTS "ea_audit_engagement" ADD COLUMN IF NOT EXISTS "{column}" {kind}')
    cr.execute('ALTER TABLE IF EXISTS "ea_audit_engagement" DROP COLUMN IF EXISTS "nature_text"')
    _logger.info("engagement profile: columns %s ready on ea_audit_engagement", ", ".join(c for c, _k in COLUMNS))
