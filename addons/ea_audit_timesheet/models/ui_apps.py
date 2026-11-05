from odoo import api, models


class AuditUi(models.AbstractModel):
    _inherit = "ea.audit.ui"

    @api.model
    def _ea_ui_apps(self):
        apps = super()._ea_ui_apps()
        apps.append({
            "key": "timesheet", "label": "Feuille de temps", "sub": "Saisir et soumettre ses heures",
            "xmlid": "ea_audit_timesheet.action_sheet", "top": True,
        })
        if self.env.user._ea_firm_role() == "firm_admin":
            apps.append({
                "key": "users", "label": "Utilisateurs", "sub": "Inviter, rôles, désactiver",
                "xmlid": "ea_audit_timesheet.action_users", "gear": True,
            })
            apps.append({
                "key": "settings", "label": "Paramètres", "sub": "Messagerie, projets internes",
                "xmlid": "ea_audit_timesheet.action_settings", "gear": True,
            })
        return apps

    @api.model
    def _ea_ui_mission_items(self):
        items = super()._ea_ui_mission_items()
        items.append({"label": "Budget et réalisé", "tag": "ea_audit_timesheet.budget"})
        return items
