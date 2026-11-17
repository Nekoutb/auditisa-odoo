from odoo import models


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        info = super().session_info()
        if info.get("uid"):
            # In the person's own language: the session's context can still hold the language of the
            # sign-in after EN/FR was switched, and the top bar would keep "Partner" in English.
            lang = self.env["res.users"].context_get().get("lang") or self.env.lang
            shell = self.env["ea.audit.ui"].with_context(lang=lang)._ea_ui_shell_session()
            if shell:
                info["ea_audit_shell"] = shell
                # the audit home is the landing action, unless the user chose one
                if not info.get("home_action_id"):
                    info["home_action_id"] = self.env.ref("ea_audit_ui.action_home").id
        return info
