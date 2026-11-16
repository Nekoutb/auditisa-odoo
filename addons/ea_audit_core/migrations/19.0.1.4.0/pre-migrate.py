"""Roll forward everything (owner's ruling of 2026-11-16): the wizard's "Paper answers" box
replaces the permanent-file box. A wizard (transient) table: an empty column, no row written.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute('ALTER TABLE IF EXISTS "ea_audit_rollforward_wizard" ADD COLUMN IF NOT EXISTS "carry_answers" boolean')
    _logger.info("roll forward: carry_answers ready on ea_audit_rollforward_wizard")
