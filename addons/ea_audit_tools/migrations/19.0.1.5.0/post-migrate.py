"""The controls of OPEN files get the code of the fixed frequency list when their free text says
it without doubt ("monthly", "mensuel", "each invoice"...). Archived files are never written
(archive trigger): their controls keep the text alone and are read through the same parser.
Anything unclear is left empty and shows "Please choose". Running twice changes nothing.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    done = env["ea.audit.scot.control"]._ea_backfill_frequency_codes()
    _logger.info("control frequencies: %d control(s) of open files given their code", done)
