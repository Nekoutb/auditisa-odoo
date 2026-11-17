"""Working-paper layout of 2026-11-17: a review note can be raised on one task of the paper.
One empty column, no default: no row is written, so the archive triggers are never asked.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute('ALTER TABLE IF EXISTS "ea_audit_review_note" ADD COLUMN IF NOT EXISTS "task_key" varchar')
    _logger.info("paper layout: task_key ready on ea_audit_review_note")
