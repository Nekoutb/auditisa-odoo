from odoo import fields, models


class PortalContactWizard(models.TransientModel):
    """New contact: name and email. The auditor never sees a password; the result is the link
    the contact uses to choose one, to pass on by hand while mail stays off."""

    _name = "ea.audit.portal.contact.wizard"
    _description = "New portal contact"

    client_id = fields.Many2one("ea.audit.client", required=True, ondelete="cascade")
    contact_id = fields.Many2one("ea.audit.portal.contact", ondelete="cascade")
    name = fields.Char()
    email = fields.Char()
    invite_link = fields.Char(string="Invitation link", readonly=True)

    def action_invite(self):
        self.ensure_one()
        contact, link = self.client_id.add_portal_contact(self.email, self.name)
        self.write({"contact_id": contact.id, "invite_link": link})
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form", "target": "new",
            "name": self.env._("Invitation link"),
        }


class PbcWizard(models.TransientModel):
    """New request, or the task an accepted upload is filed under."""

    _name = "ea.audit.portal.pbc.wizard"
    _description = "Client-provided document request"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True, ondelete="cascade")
    item_id = fields.Many2one("ea.audit.pbc.item", ondelete="cascade")
    title = fields.Char()
    note = fields.Text()
    file_item_id = fields.Many2one("ea.audit.file.item", string="Filed under", domain="[('engagement_id', '=', engagement_id)]")

    def action_confirm(self):
        self.ensure_one()
        if self.item_id:
            if self.item_id.sudo().status == "accepted":
                self.item_id.attach_accepted(self.file_item_id)
            else:
                self.item_id.accept(self.file_item_id)
        else:
            self.engagement_id.add_pbc_item(self.title, self.note)
        return {"type": "ir.actions.act_window_close"}
