"""EAGLR and the journal types of a general ledger (owner's mock-ups "eaglr" and
"gl-journal-types", 2026-11-20).

One nullable column, added empty, with no default and no row written: an archived file refuses
any row update (archive trigger ea_audit_assert_open). A ledger uploaded before this version has
no journal types until a person gives them from the Data bank. Does nothing if already done.
"""

import logging

_logger = logging.getLogger(__name__)

COLUMNS = {
    "ea_audit_dataset": [("journal_types", "jsonb")],
}


def migrate(cr, version):
    for table, columns in COLUMNS.items():
        for name, kind in columns:
            cr.execute('ALTER TABLE IF EXISTS "%s" ADD COLUMN IF NOT EXISTS "%s" %s' % (table, name, kind))
    _logger.info("eaglr: journal types column ready, no row written")
