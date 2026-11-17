"""Adjustments by heading and the review of the summary of audit differences (owner's mock-up of
2026-11-17, "wp-finding-sad").

Nullable columns only, added empty, with no default and no row written: an archived file refuses
any row update (archive trigger ea_audit_assert_open). An adjustment line typed before this
version keeps its account and reads "to classify" (no heading); a summary line reads "To review"
(no review state). Does nothing if already done.
"""

import logging

_logger = logging.getLogger(__name__)

COLUMNS = {
    "ea_audit_finding_adjustment": [("heading", "varchar")],
    "ea_audit_sad_entry": [
        ("review_state", "varchar"),
        ("reviewed_by_id", "integer"),
        ("reviewed_at", "timestamp without time zone"),
        ("review_note_id", "integer"),
        ("prepared_by_id", "integer"),
    ],
}


def migrate(cr, version):
    for table, columns in COLUMNS.items():
        for name, kind in columns:
            cr.execute('ALTER TABLE IF EXISTS "%s" ADD COLUMN IF NOT EXISTS "%s" %s' % (table, name, kind))
    _logger.info("sad review: heading and review columns ready, no row written")
