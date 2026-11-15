"""The presumed revenue-fraud risk is linked to revenue (UA) on every open file (owner's ruling of
2026-11-15), as a new file gets it when its risks are seeded. A rebutted risk is left alone, and
an archived file is never written (archive trigger): only link rows of open files are created.
Running twice adds nothing.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    linked = 0
    for engagement in env["ea.audit.engagement"].search([("archived_at", "=", False), ("phase", "!=", "archived")]):
        if engagement._ea_link_revenue_fraud():
            linked += 1
    _logger.info("revenue-fraud risk: linked to revenue (UA) on %d open file(s)", linked)
