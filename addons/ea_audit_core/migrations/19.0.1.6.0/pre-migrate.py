"""The task scope of 2026-11-17 ("facts decide whether, complexity decides depth"). Three empty
columns on the engagement: the scope a file was opened with (empty = the older scope: a live file
keeps its tasks until its partner applies the current one) and the two questions that bring C1.3
and C5.9. No row is written: archived files stay as they are (archive trigger).
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute('ALTER TABLE IF EXISTS "ea_audit_engagement" ADD COLUMN IF NOT EXISTS "scope_version" integer')
    cr.execute('ALTER TABLE IF EXISTS "ea_audit_engagement" ADD COLUMN IF NOT EXISTS "consultation_needed" varchar')
    cr.execute('ALTER TABLE IF EXISTS "ea_audit_engagement" ADD COLUMN IF NOT EXISTS "joint_auditors" varchar')
    _logger.info("task scope: scope_version, consultation_needed and joint_auditors ready on ea_audit_engagement")
