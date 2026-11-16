"""Procedure design (owner's mock-ups of 2026-11-16): a sample drawn for a test of details points at
the designed procedure it feeds.

One nullable column on the engine runs, added empty, with no default and no row written: an archived
file refuses any row update (archive trigger). The library and the designed procedures are new tables,
created by Odoo itself. Does nothing if already done.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute('ALTER TABLE IF EXISTS "ea_audit_automation_run" ADD COLUMN IF NOT EXISTS "designed_procedure_id" integer')
    _logger.info("procedure design: designed_procedure_id ready on ea_audit_automation_run, no row written")
