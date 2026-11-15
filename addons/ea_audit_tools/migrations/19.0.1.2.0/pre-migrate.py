"""Significant accounts: the general ledger's activity per lead index (owner's request of 2026-11-15).

Six columns go on the significant-account rows: the ledger upload counted, the number of journal
entries, of preparers and of reviewers, and whether the ledger had a column for each. They are
created here, empty, so that Odoo writes no row: an archived file refuses any row update (archive
trigger, the lesson of 2026-11-15 on demo-akwa). An empty count shows as empty. An open file gets
its counts the next time its list of significant accounts is opened or its ledger or trial
balance changes; an archived file keeps them empty. Each step does nothing if it was already done.
"""

import logging

_logger = logging.getLogger(__name__)

COLUMNS = (
    ("activity_dataset", "integer"),
    ("tx_count", "integer"),
    ("preparer_count", "integer"),
    ("reviewer_count", "integer"),
    ("preparer_known", "boolean"),
    ("reviewer_known", "boolean"),
)


def migrate(cr, version):
    for column, kind in COLUMNS:
        cr.execute(f'ALTER TABLE IF EXISTS "ea_audit_significance" ADD COLUMN IF NOT EXISTS "{column}" {kind}')
    _logger.info("significance activity: %d column(s) ready on ea_audit_significance, no row written", len(COLUMNS))
