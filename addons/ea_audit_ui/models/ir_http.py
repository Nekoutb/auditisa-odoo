from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        info = super().session_info()
        if info.get("uid"):
            shell = self.env["ea.audit.ui"]._ea_ui_shell_session()
            if shell:
                info["ea_audit_shell"] = shell
                # the audit home is the landing action, unless the user chose one
                if not info.get("home_action_id"):
                    info["home_action_id"] = self.env.ref("ea_audit_ui.action_home").id
        return info
