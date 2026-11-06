import base64

from odoo import fields, models


class SignoffMatrixImport(models.TransientModel):
    _name = "ea.audit.signoff.matrix.import"
    _description = "Import the sign-off matrix"

    file = fields.Binary(string="Workbook", required=True)
    filename = fields.Char()

    def action_import(self):
        self.ensure_one()
        changed = self.env["ea.audit.signoff.task.rule"]._ea_matrix_import(base64.b64decode(self.file or b""))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Sign-off matrix imported"),
                "message": self.env._("%(count)s rule(s) changed.", count=changed),
                "type": "success",
                "next": {"type": "ir.actions.client", "tag": "soft_reload"},
            },
        }
