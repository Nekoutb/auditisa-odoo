"""Work allocation (2026-11-18): the new column "Partner approval" of each task is filled once, from
the sign-off policy and the engagement partner. Quiet: no trail line for a column that did not exist.
Archived files are left as they are (the archive is never rewritten).
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    engagements = env["ea.audit.engagement"].with_context(active_test=False).search([])
    engagements._ea_sync_partner_approval(log=False)
    _logger.info("work allocation: partner approval set on the tasks of %d engagement(s)", len(engagements))
