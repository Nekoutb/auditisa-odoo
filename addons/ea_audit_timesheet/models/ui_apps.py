from odoo import api, models


class AuditUi(models.AbstractModel):
    _inherit = "ea.audit.ui"

    @api.model
    def _ea_ui_apps(self):
        apps = super()._ea_ui_apps()
        apps.append({
            "key": "timesheet", "label": self.env._("Timesheet"), "sub": self.env._("Enter and submit your hours"),
            "xmlid": "ea_audit_timesheet.action_sheet", "top": True,
        })
        if self.env.user._ea_firm_role() == "firm_admin":
            apps.append({
                "key": "users", "label": self.env._("Users"), "sub": self.env._("Invite, roles, deactivate"),
                "xmlid": "ea_audit_timesheet.action_users", "gear": True,
            })
            apps.append({
                "key": "settings", "label": self.env._("Settings"), "sub": self.env._("Mail, internal projects"),
                "xmlid": "ea_audit_timesheet.action_settings", "gear": True,
            })
        return apps

    @api.model
    def _ea_ui_mission_items(self):
        items = super()._ea_ui_mission_items()
        items.append({"label": self.env._("Log time on this engagement"), "tag": "ea_audit_timesheet.sheet"})
        items.append({"label": self.env._("Budget and actual"), "tag": "ea_audit_timesheet.budget"})
        return items
