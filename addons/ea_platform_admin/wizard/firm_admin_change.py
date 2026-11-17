from odoo import fields, models
from odoo.exceptions import UserError

from ..models.i18n import t
from ..services import admin_change
from ..services.messages import _


class PlatformFirmAdminChangeWizard(models.TransientModel):
    """The small form of "Add a firm administrator" and "Replace the firm administrator"."""

    _name = "platform.firm.admin.change.wizard"
    _description = "Change the firm administrator"

    firm_id = fields.Many2one("platform.firm", required=True, readonly=True)
    change_action = fields.Selection(admin_change.ACTION_CHOICES, "Request", required=True, readonly=True)
    allowed_email_domains = fields.Text(related="firm_id.allowed_email_domains")
    name = fields.Char("Name", required=True)
    email = fields.Char("Email address", required=True)

    def action_confirm(self):
        self.ensure_one()
        self.firm_id._admin_change_request(self.change_action, self.name, self.email, self.env.user)
        return {"type": "ir.actions.act_window_close"}


class PlatformFirmAdminLink(models.TransientModel):
    """Shows the new firm administrator's one-time link once. The stored copy is erased as it is shown."""

    _name = "platform.firm.admin.link"
    _description = "Administrator's link"

    firm_id = fields.Many2one("platform.firm", required=True, readonly=True)
    person = fields.Char(related="firm_id.admin_change_name", string="For")
    revealed = fields.Boolean(readonly=True)
    link = fields.Char("One-time link", readonly=True)
    expires_at = fields.Datetime("Expires on", readonly=True)

    def action_reveal(self):
        self.ensure_one()
        firm = self.firm_id.sudo()
        if not firm.admin_link_ready or not firm.admin_link_token:
            raise UserError(t(self.env, _(
                "This link is no longer available: it has already been shown or it has expired. The firm "
                "administrator can make a new invitation link on the firm's Users screen."
            )))
        self.write({"revealed": True, "link": firm.admin_link_token, "expires_at": firm.admin_link_expires_at})
        firm.write({"admin_link_token": False, "admin_link_revealed_at": fields.Datetime.now()})
        self.env["platform.log"]._record(_("Administrator's link shown"), firm, user=self.env.user)
        return {
            "type": "ir.actions.act_window",
            "name": self.env["ir.model"]._get(self._name).name,
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form", "views": [(False, "form")],
            "target": "new",
        }

    def action_close(self):
        """Nothing of the link outlives the screen."""
        self.write({"link": False})
        return {"type": "ir.actions.act_window_close"}
