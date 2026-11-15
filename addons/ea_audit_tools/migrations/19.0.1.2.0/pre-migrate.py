"""Significant accounts: the general ledger's activity per lead index (owner's request of 2026-11-15).

Six columns go on the significant-account rows: the ledger upload counted, the number of journal
entries, of preparers and of reviewers, and whether the ledger had a column for each. They are
created here, empty, so that Odoo writes no row: an archived file refuses any row update (archive
trigger, the lesson of 2026-11-15 on demo-akwa). An empty count shows as empty. An open file gets
its counts the next time its list of significant accounts is opened or its ledger or trial
balance changes; an archived file keeps them empty. Each step does nothing if it was already done.

The rebuttal of the presumed revenue-fraud risk becomes two steps (proposed, then approved or
rejected by the engagement partner): its six columns are created here, empty, for the same reason.
A risk rebutted before this release keeps rebutted and its approver; its new columns stay empty.
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


RISK_COLUMNS = (
    ("rebuttal_state", "varchar"),
    ("rebuttal_proposed_by_id", "integer"),
    ("rebuttal_proposed_at", "timestamp"),
    ("rebuttal_decided_at", "timestamp"),
    ("rebuttal_rejected_by_id", "integer"),
    ("rebuttal_rejection", "text"),
)


def migrate(cr, version):
    for column, kind in COLUMNS:
        cr.execute(f'ALTER TABLE IF EXISTS "ea_audit_significance" ADD COLUMN IF NOT EXISTS "{column}" {kind}')
    _logger.info("significance activity: %d column(s) ready on ea_audit_significance, no row written", len(COLUMNS))
    for column, kind in RISK_COLUMNS:
        cr.execute(f'ALTER TABLE IF EXISTS "ea_audit_risk" ADD COLUMN IF NOT EXISTS "{column}" {kind}')
    _logger.info("rebuttal approval: %d column(s) ready on ea_audit_risk, no row written", len(RISK_COLUMNS))
