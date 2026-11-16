"""Sampling worksheet (owner's mock-up of 2026-11-16): two nullable columns on the engine runs.

``purpose`` names the substantive procedure a test-of-details sample serves (next phase links it);
``item_results`` keeps what the auditor found on each item drawn. Both are added empty, with no
default and no row written: an archived file refuses any row update (archive trigger). The new
table of reviewed journal entries is created by Odoo itself. Each step does nothing if already done.
"""

import logging

_logger = logging.getLogger(__name__)

COLUMNS = (
    ("purpose", "varchar"),
    ("item_results", "jsonb"),
)


def migrate(cr, version):
    for column, kind in COLUMNS:
        cr.execute(f'ALTER TABLE IF EXISTS "ea_audit_automation_run" ADD COLUMN IF NOT EXISTS "{column}" {kind}')
    _logger.info("sampling worksheet: %d column(s) ready on ea_audit_automation_run, no row written", len(COLUMNS))
