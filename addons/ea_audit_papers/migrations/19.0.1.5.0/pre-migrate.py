"""Roll forward everything (owner's ruling of 2026-11-16): a working paper whose answers were
carried from last year's file is marked with that year. One empty column, no default: no row is
written, so the archive triggers are never asked (an archived file refuses every row change).
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute('ALTER TABLE IF EXISTS "ea_audit_paper" ADD COLUMN IF NOT EXISTS "carried_from_year" integer')
    _logger.info("roll forward: carried_from_year ready on ea_audit_paper")
