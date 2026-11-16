"""Roll forward (owner's mock-up of 2026-11-16): what a new file carried from last year is marked
with that year, and the engagement keeps last year's materiality basis (no amounts). Empty
columns, no default: no row is written, so the archive triggers are never asked (an archived file
refuses every row change). Odoo then finds the columns made and writes nothing.
"""

import logging

_logger = logging.getLogger(__name__)

COLUMNS = (
    ("ea_audit_engagement", "ea_carried_basis", "jsonb"),
    ("ea_audit_scot", "carried_from_year", "integer"),
    ("ea_audit_scot_control", "carried_from_year", "integer"),
    ("ea_audit_risk", "carried_from_year", "integer"),
    ("ea_audit_designed_procedure", "carried_from_year", "integer"),
    ("ea_audit_significance", "carried_from_year", "integer"),
)


def migrate(cr, version):
    for table, column, kind in COLUMNS:
        cr.execute(f'ALTER TABLE IF EXISTS "{table}" ADD COLUMN IF NOT EXISTS "{column}" {kind}')
    _logger.info("roll forward: %d carried-forward columns ready", len(COLUMNS))
