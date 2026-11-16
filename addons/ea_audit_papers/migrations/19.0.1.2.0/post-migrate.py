"""P7.1 (planning communication with those charged with governance) and S6.2 (the partner's
direction, supervision and review) are merged into P1.4 Part D and S6.1 Part E (owner's decision
of 2026-11-16). New files no longer get them (file_scope.RETIRED_CODES). Here, on every open
file, an active P7.1 or S6.2 that holds no answer, evidence, conclusion or sign-off leaves the
file (it becomes a conditional task, shown as "now recorded in P1.4 / S6.1"). A task with work
stays as it is, and an archived file is never written (archive trigger). Running twice changes
nothing. No column is added: this is a data step only.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    retired = env["ea.audit.engagement"]._ea_retire_merged_tasks()
    _logger.info("P7.1 / S6.2 merged: %d empty task(s) taken off open files", retired)
