from odoo import api, fields, models

from ..services.phases import BUDGET_PHASES


class Project(models.Model):
    _inherit = "project.project"

    ea_engagement_id = fields.Many2one(
        "ea.audit.engagement", string="Mission", copy=False, readonly=True, ondelete="set null", index="btree_not_null",
    )
    ea_is_internal = fields.Boolean(string="Projet interne de la firme", copy=False)

    _ea_one_per_engagement = models.UniqueIndex("(ea_engagement_id) WHERE ea_engagement_id IS NOT NULL")

    @api.model
    def _ea_ts_quiet(self):
        return self.sudo().with_context(tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True)

    @api.model
    def _ea_ts_create_internal(self, name):
        return self._ea_ts_quiet().create({
            "name": name, "ea_is_internal": True, "allow_timesheets": True,
            "privacy_visibility": "employees", "company_id": self.env.company.id,
        })


class ProjectTask(models.Model):
    _inherit = "project.task"

    ea_phase = fields.Selection(BUDGET_PHASES, string="Phase", copy=False)
