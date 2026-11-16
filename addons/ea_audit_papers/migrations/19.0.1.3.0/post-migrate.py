"""C5.2 (the OHADA statutory deadlines and whether each was met) is no longer a paper of the
file (owner's decision of 2026-11-16). New files no longer get it (file_scope.RETIRED_CODES).
Here, on every open file, an active C5.2 that holds no answer, evidence, conclusion or sign-off
leaves the file (it becomes a conditional task, shown as "no longer a paper of the file"). A
C5.2 with work stays as it is, and an archived file is never written (archive trigger). The same
step as 19.0.1.2.0, so P7.1 and S6.2 are looked at again: running twice changes nothing. No
column is added: this is a data step only.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    retired = env["ea.audit.engagement"]._ea_retire_merged_tasks()
    _logger.info("C5.2 retired (P7.1 / S6.2 checked again): %d empty task(s) taken off open files", retired)
