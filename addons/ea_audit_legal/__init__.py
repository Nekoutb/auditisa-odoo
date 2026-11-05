from . import models
from . import wizards
from odoo.addons.ea_audit_reports.models.records import install_archive_triggers


def post_init_hook(env):
    install_archive_triggers(env.cr)
