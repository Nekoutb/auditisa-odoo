"""Significant accounts: the flag thresholds of each file (owner's mock-up of 2026-11-16).

Three columns go on the engagement: flag a movement above a percentage and/or an amount. They are
created here with the owner's defaults (and, 10 %, 10 000 000 FCFA) so that Odoo writes no row: an
archived file refuses any row update (archive trigger). Each step does nothing if already done.
"""

import logging

_logger = logging.getLogger(__name__)

COLUMNS = (
    ("significance_flag_mode", "varchar", "'and'"),
    ("significance_flag_pct", "double precision", "10"),
    ("significance_flag_amount", "double precision", "10000000"),
)


def migrate(cr, version):
    for column, kind, default in COLUMNS:
        cr.execute(
            f'ALTER TABLE IF EXISTS "ea_audit_engagement" ADD COLUMN IF NOT EXISTS "{column}" {kind} DEFAULT {default}'
        )
    _logger.info("significance flags: %d column(s) ready on ea_audit_engagement, no row written", len(COLUMNS))
