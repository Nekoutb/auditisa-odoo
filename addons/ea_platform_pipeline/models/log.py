from odoo import api, models

from .i18n import read_any


class PlatformLog(models.Model):
    _inherit = "platform.log"

    @api.depends("action", "detail")
    @api.depends_context("lang")
    def _compute_text(self):
        for row in self:
            row.action_text = read_any(self.env, row.action)
            row.detail_text = read_any(self.env, row.detail)
