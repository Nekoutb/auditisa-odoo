"""Send a test email: one message from a firm's platform address, to an address the operator types.

As a practice space: the address must be on "Practice spaces may email only these addresses"
(Platform > Settings), the rule every practice space follows. The email carries the firm's name only.
"""

from odoo import fields, models

from ..services import platform_mail


class PlatformMailTestWizard(models.TransientModel):
    _name = "platform.mail.test.wizard"
    _description = "Send a test email"

    firm_id = fields.Many2one("platform.firm", "Firm", required=True, readonly=True)
    sender = fields.Char(related="firm_id.pmail_sender", string="From")
    address = fields.Char("Send to", help="One email address, for example your own.")
    practice = fields.Boolean(
        "As a practice space would",
        help="Ticked: the email goes only if the address is on the list \"Practice spaces may email only these "
             "addresses\" (Platform > Settings).",
    )
    allowlist = fields.Text("Addresses practice spaces may email", compute="_compute_allowlist")
    result = fields.Text("Result", readonly=True)

    def _compute_allowlist(self):
        raw = self.env["ir.config_parameter"].sudo().get_param("ea_platform.practice_mail_allowlist") or ""
        addresses = "\n".join(platform_mail.parse_allowlist(raw)[0])
        for wizard in self:
            wizard.allowlist = addresses

    def action_send(self):
        self.ensure_one()
        self.result = self.firm_id._pmail_send_test(self.address, practice=self.practice, user=self.env.user)
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
            "name": self.env["ir.model"]._get(self._name).name,
            "view_mode": "form", "views": [(False, "form")], "target": "new",
        }
