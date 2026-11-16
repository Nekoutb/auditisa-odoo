"""Findings page (owner's mock-up of 2026-11-16): why a finding matters, where it was raised
from, and the documents attached to it.

Four columns, all empty to start with, so that Odoo writes no row: an archived file refuses any
row update (archive trigger). Each step does nothing if already done.
"""

import logging

_logger = logging.getLogger(__name__)

COLUMNS = (
    ("ea_audit_finding", "impact", "text"),
    ("ea_audit_finding", "source_model", "varchar"),
    ("ea_audit_finding", "source_id", "integer"),
    ("ea_audit_task_attachment", "finding_id", "integer"),
)


def migrate(cr, version):
    for table, column, kind in COLUMNS:
        cr.execute(f'ALTER TABLE IF EXISTS "{table}" ADD COLUMN IF NOT EXISTS "{column}" {kind}')
    _logger.info("findings page: %d column(s) ready, no row written", len(COLUMNS))
