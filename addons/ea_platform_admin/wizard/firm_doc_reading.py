"""The "Document reading" form of a firm's page (owner's ruling of 2026-11-20, Opening Balance Testing).

The key field is not a database column: as with the mail password (wizard/firm_mail.py), the key is taken
out of what the screen sent before anything is written, kept encrypted in a file outside the database until
the operator sends it or the form is closed, and never shown again.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.i18n import t
from ..services import mail_handoff
from ..services.messages import _


class PlatformFirmDocReadingWizard(models.TransientModel):
    _name = "platform.firm.docr.wizard"
    _description = "Document reading key for this firm"

    firm_id = fields.Many2one("platform.firm", "Firm", required=True, readonly=True)
    docr_key = fields.Char(
        "Key", compute="_compute_docr_key", inverse="_inverse_docr_key", store=False,
        help="The firm's key for reading documents. It goes to the firm's server once, and is never kept or shown by the console.",
    )
    docr_key_kept = fields.Boolean("A key is kept for this form", readonly=True)
    current_state = fields.Selection(related="firm_id.docr_state", string="Now")
    current_last4 = fields.Char(related="firm_id.docr_last4", string="Key ending")
    current_at = fields.Datetime(related="firm_id.docr_at", string="Asked on")
    current_answered_at = fields.Datetime(related="firm_id.docr_answered_at", string="Answer received on")
    current_documents = fields.Integer(related="firm_id.docr_documents", string="Documents read this month")
    current_pages = fields.Integer(related="firm_id.docr_pages", string="Pages read this month")

    def _compute_docr_key(self):
        for form in self:
            form.docr_key = False

    def _inverse_docr_key(self):
        """Never reached: create and write take the key out first."""

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        keys = [vals.pop("docr_key", None) for vals in vals_list]
        for vals, key in zip(vals_list, keys):
            if key:
                vals["docr_key_kept"] = True
        records = super().create(vals_list)
        for record, key in zip(records, keys):
            if key:
                record._docr_keep(key)
        return records

    def write(self, vals):
        vals = dict(vals)
        key = vals.pop("docr_key", None)
        if key:
            vals["docr_key_kept"] = True
        result = super().write(vals)
        if key:
            for form in self:
                form._docr_keep(key)
        return result

    def unlink(self):
        self._docr_forget()
        return super().unlink()

    def _docr_file(self):
        self.ensure_one()
        return mail_handoff.form_name(self._table, self.id)

    def _docr_keep(self, key):
        self.env["platform.firm"]._mail_seal(self._docr_file(), {"key": key})

    def _docr_kept(self):
        firms = self.env["platform.firm"]
        data = firms._mail_unseal(mail_handoff.read(firms._mail_folder(), self._docr_file()))
        return (data or {}).get("key") or ""

    def _docr_forget(self):
        folder = self.env["platform.firm"]._mail_folder()
        for form in self:
            if form.id and isinstance(form.id, int):
                mail_handoff.discard(folder, form._docr_file())

    def action_send(self):
        """Save and send to the firm's server."""
        self.ensure_one()
        key = self._docr_kept()
        if not key:
            raise UserError(t(self.env, _("Paste the key first.")))
        self.firm_id._docr_send_key(key, user=self.env.user)
        self._docr_forget()
        self.sudo().write({"docr_key_kept": False})
        self.firm_id._docr_simulate_answer()
        return {"type": "ir.actions.act_window_close"}

    def action_test(self):
        self.ensure_one()
        self.firm_id.action_docr_test()
        return {"type": "ir.actions.act_window_close"}

    def action_remove(self):
        self.ensure_one()
        self.firm_id.action_docr_remove()
        return {"type": "ir.actions.act_window_close"}
