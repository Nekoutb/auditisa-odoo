from odoo import api, models

from ..services.phases import BUDGET_PHASES

_SYNCED = {"phase", "archived_at", "name", "client_id", "fiscal_year"}


class Engagement(models.Model):
    _inherit = "ea.audit.engagement"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._ea_ts_ensure_project()
        return records

    def write(self, vals):
        result = super().write(vals)
        if _SYNCED & set(vals):
            self._ea_ts_ensure_project()
        return result

    def _ea_ts_project(self):
        self.ensure_one()
        return self.env["project.project"].sudo().with_context(active_test=False).search(
            [("ea_engagement_id", "=", self.id)], limit=1,
        )

    def _ea_ts_ensure_project(self):
        """Each engagement has its project and one task per phase. The project
        follows the engagement's name; archiving the engagement archives it."""
        Project = self.env["project.project"]._ea_ts_quiet()
        Task = self.env["project.task"].sudo().with_context(
            tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True,
        )
        for engagement in self.sudo():
            project = engagement._ea_ts_project()
            vals = {"name": engagement.display_name, "active": not engagement._ea_is_archived()}
            if project:
                if project.name != vals["name"] or project.active != vals["active"]:
                    project.write(vals)
                continue
            project = Project.create({
                **vals,
                "ea_engagement_id": engagement.id,
                "allow_timesheets": True,
                "privacy_visibility": "followers",
                "company_id": self.env.company.id,
            })
            Task.create([
                {"name": label, "project_id": project.id, "ea_phase": key}
                for key, label in BUDGET_PHASES
            ])

    def action_open_ea_budget(self):
        self.ensure_one()
        self._ea_require_access()
        return {
            "type": "ir.actions.client",
            "tag": "ea_audit_timesheet.budget",
            "name": self.env._("Budget and actual"),
            "params": {"resId": self.id},
        }
