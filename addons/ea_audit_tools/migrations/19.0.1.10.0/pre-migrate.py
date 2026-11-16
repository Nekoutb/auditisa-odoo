"""Execution of the substantive procedures (owner's mock-ups of 2026-11-16): a designed procedure
keeps the work done on it (steps ticked, explanations) in one JSON column, and an evidence file of
a task can name the procedure it supports.

Two nullable columns, added empty, with no default and no row written: an archived file refuses any
row update (archive trigger). The confirmations are a new table, created by Odoo itself. Does
nothing if already done.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute('ALTER TABLE IF EXISTS "ea_audit_designed_procedure" ADD COLUMN IF NOT EXISTS "work_data" jsonb')
    cr.execute('ALTER TABLE IF EXISTS "ea_audit_task_attachment" ADD COLUMN IF NOT EXISTS "designed_procedure_id" integer')
    _logger.info("procedure execution: work_data and designed_procedure_id ready, no row written")
