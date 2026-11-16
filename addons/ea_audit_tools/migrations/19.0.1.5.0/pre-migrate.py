"""SCOTs and controls (owner's mock-ups of 2026-11-16).

New columns, created here so that Odoo writes no row (an archived file refuses any row update,
archive trigger):
- on the controls: the frequency as a code of the fixed list, the reason for "other", the reliance
  (normal / heavy) and the size frozen at the first result. The free-text frequency stays as it was.
- on the evidence files of a task: the SCOT, the control and the kind of document they belong to.
Each step does nothing if already done.
"""

import logging

_logger = logging.getLogger(__name__)

COLUMNS = (
    ("ea_audit_scot_control", "frequency_code", "varchar", None),
    ("ea_audit_scot_control", "frequency_other", "varchar", None),
    ("ea_audit_scot_control", "reliance", "varchar", "'normal'"),
    ("ea_audit_scot_control", "frozen_size", "integer", None),
    ("ea_audit_task_attachment", "scot_id", "integer", None),
    ("ea_audit_task_attachment", "control_id", "integer", None),
    ("ea_audit_task_attachment", "doc_type", "varchar", None),
)


def migrate(cr, version):
    for table, column, kind, default in COLUMNS:
        tail = f" DEFAULT {default}" if default else ""
        cr.execute(f'ALTER TABLE IF EXISTS "{table}" ADD COLUMN IF NOT EXISTS "{column}" {kind}{tail}')
    _logger.info("SCOTs and controls: %d column(s) ready, no row written", len(COLUMNS))
