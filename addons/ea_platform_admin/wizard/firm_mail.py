"""The "Email for this firm" form, on the firm's page and as the New firm form's optional step.

The password field is not a database column. When the form is saved, the password is taken out of
what the screen sent before anything is written, and kept encrypted in a file outside the database
(services/mail_handoff.py) until the operator sends it, or until the form is closed. It is never shown
again: the field always reads empty, and the form says only that a password is kept.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.i18n import t
from ..models.firm_platform_mail import MAIL_CHOICES
from ..services import mail_handoff, mail_settings, platform_mail
from ..services.messages import _
from ..services.validation import normalise_slug


class PlatformMailForm(models.AbstractModel):
    _name = "platform.mail.form"
    _description = "A firm's outgoing mail settings, as typed"

    mail_preset = fields.Selection(
        mail_settings.PRESET_CHOICES, "Email provider",
        help="Choose the firm's email provider: the server, the port and the encryption fill in by themselves.",
    )
    mail_host = fields.Char(
        "Mail server", help="The provider's outgoing mail server (SMTP), for example smtp.office365.com.",
    )
    mail_port = fields.Integer("Port", default=587, help="Usually 587 with STARTTLS, or 465 with SSL.")
    mail_encryption = fields.Selection(
        mail_settings.ENCRYPTION_CHOICES, "Encryption", default="starttls",
        help="How the connection is protected. A password never travels unencrypted.",
    )
    mail_user = fields.Char("Username", help="Usually the full email address of the mailbox.")
    mail_password = fields.Char(
        "Password", compute="_compute_mail_password", inverse="_inverse_mail_password", store=False,
        help="The mailbox's password, or an app password (Microsoft 365 and Google often ask for one). It goes to "
             "the firm's server once, and is never kept or shown by the console.",
    )
    mail_password_kept = fields.Boolean("A password is kept for this form", readonly=True)
    mail_sender = fields.Char(
        "Sender address", help="The address the firm's emails come from: usually the same mailbox, for example "
                               "cabinet@example.com.",
    )

    def _compute_mail_password(self):
        for form in self:
            form.mail_password = False

    def _inverse_mail_password(self):
        """Never reached: create and write take the password out first."""

    @api.onchange("mail_preset")
    def _onchange_mail_preset(self):
        for key, value in mail_settings.preset(self.mail_preset).items():
            self["mail_" + key] = value

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [dict(vals) for vals in vals_list]
        passwords = [vals.pop("mail_password", None) for vals in vals_list]
        for vals, password in zip(vals_list, passwords):
            if password:
                vals["mail_password_kept"] = True
        records = super().create(vals_list)
        for record, password in zip(records, passwords):
            if password:
                record._mail_keep_password(password)
        return records

    def write(self, vals):
        vals = dict(vals)
        password = vals.pop("mail_password", None)
        if password:
            vals["mail_password_kept"] = True
        result = super().write(vals)
        if password:
            for form in self:
                form._mail_keep_password(password)
        return result

    def unlink(self):
        self._mail_forget_password()
        return super().unlink()

    def _mail_file(self):
        self.ensure_one()
        return mail_handoff.form_name(self._table, self.id)

    def _mail_keep_password(self, password):
        self.env["platform.firm"]._mail_seal(self._mail_file(), {"password": password})

    def _mail_kept_password(self):
        firms = self.env["platform.firm"]
        data = firms._mail_unseal(mail_handoff.read(firms._mail_folder(), self._mail_file()))
        return (data or {}).get("password") or ""

    def _mail_forget_password(self):
        folder = self.env["platform.firm"]._mail_folder()
        for form in self:
            if form.id and isinstance(form.id, int):
                mail_handoff.discard(folder, form._mail_file())

    def _mail_values(self):
        self.ensure_one()
        return {
            "host": self.mail_host, "port": self.mail_port, "encryption": self.mail_encryption,
            "user": self.mail_user, "password": self._mail_kept_password(), "sender": self.mail_sender,
        }

    def _mail_raise_errors(self, values):
        problems = mail_settings.errors(values)
        if problems:
            raise UserError("\n".join(t(self.env, message) for messages in problems.values() for message in messages))


class PlatformFirmMailWizard(models.TransientModel):
    """Email for this firm: the operator enters the firm's mailbox, the firm's server tests it."""

    _name = "platform.firm.mail.wizard"
    _inherit = ["platform.mail.form"]
    _description = "Email for this firm"

    firm_id = fields.Many2one("platform.firm", "Firm", required=True, readonly=True)
    current_state = fields.Selection(related="firm_id.mail_request_state", string="Now")
    current_message = fields.Text(related="firm_id.mail_request_message", string="What it means")

    @api.model
    def default_get(self, fields_list):
        """Opens on what was last sent, the password excepted."""
        values = super().default_get(fields_list)
        firm = self.env["platform.firm"].browse(values.get("firm_id") or self.env.context.get("default_firm_id")).exists()
        firm = firm.sudo()
        if firm and firm.mail_request_host:
            values.update({
                "mail_preset": next(
                    (code for code, preset in mail_settings.PRESETS.items() if preset["host"] == firm.mail_request_host),
                    "other",
                ),
                "mail_host": firm.mail_request_host,
                "mail_port": firm.mail_request_port,
                "mail_encryption": firm.mail_request_encryption,
                "mail_user": firm.mail_request_user or False,
                "mail_sender": firm.mail_request_sender,
            })
        return values

    def action_save_and_test(self):
        self.ensure_one()
        firm = self.firm_id
        firm._mail_send_settings(self._mail_values(), user=self.env.user)
        self._mail_forget_password()
        self.sudo().write({"mail_password_kept": False})
        firm._mail_simulate_answer()
        return {"type": "ir.actions.act_window_close"}


class PlatformOnboardingWizard(models.TransientModel):
    """The New firm form's Email step, between the add-ons and the review: the platform address
    (recommended), the firm's own mailbox, or no email for now."""

    _name = "platform.onboarding.wizard"
    _inherit = ["platform.onboarding.wizard", "platform.mail.form"]

    step = fields.Selection(selection_add=[("email", "Email"), ("preflight",)], ondelete={"email": "set default"})
    mail_choice = fields.Selection(
        MAIL_CHOICES, "Email", default=lambda self: self._default_mail_choice(),
        help="Recommended: AuditISA sends for this firm from its own platform address, ready as soon as the firm "
             "is live. Or the firm's own mailbox, or no email for now (it can be set later from the firm's page).",
    )
    preview_mail = fields.Char("Email", compute="_compute_preview_mail")
    preview_platform_address = fields.Char("Platform address", compute="_compute_preview_mail")

    @api.model
    def _default_mail_choice(self):
        return "platform" if self.env["platform.services"]._mail_ready() else "none"

    @api.model_create_multi
    def create(self, vals_list):
        # A form filled with a mailbox (an older screen, a test) means the firm's own mailbox.
        for vals in vals_list:
            if "mail_choice" not in vals and any(vals.get(key) for key in ("mail_host", "mail_user", "mail_sender")):
                vals["mail_choice"] = "own"
        return super().create(vals_list)

    @api.depends("mail_choice", "slug", "mail_host", "mail_port", "mail_encryption", "mail_user", "mail_sender",
                 "mail_password_kept")
    @api.depends_context("lang")
    def _compute_preview_mail(self):
        config = self.env["platform.services"]._mail_config()
        for wizard in self:
            address = platform_mail.sender(
                config["local_part"], platform_mail.subdomain(normalise_slug(wizard.slug) or "slug", config["parent"]))
            wizard.preview_platform_address = address
            values = {
                "host": wizard.mail_host, "port": wizard.mail_port, "encryption": wizard.mail_encryption,
                "user": wizard.mail_user, "sender": wizard.mail_sender,
                "password": "x" if wizard.mail_password_kept else "",
            }
            if wizard.mail_choice == "platform":
                wizard.preview_mail = t(self.env, _(
                    "AuditISA sends for this firm from %(address)s: set up during provisioning", address=address))
            elif wizard.mail_choice == "own" and mail_settings.filled(values):
                wizard.preview_mail = t(self.env, _(
                    "%(settings)s: sent to the firm's server and tested as soon as it is live",
                    settings=mail_settings.summary(values),
                ))
            else:
                wizard.preview_mail = t(self.env, _("Not set: it can be done later from the firm's page"))

    def _mail_filled(self):
        values = self._mail_values()
        if self.mail_choice != "own":
            return False, values
        return mail_settings.filled(values), values

    def action_next(self):
        self.ensure_one()
        if self.step == "email":
            if self.mail_choice == "platform" and not self.env["platform.services"]._mail_ready():
                raise UserError(t(self.env, _(
                    "The sending service for firms is not set up: see Platform > Settings, "
                    "and docs/runbook/PLATFORM-EMAIL.md.")))
            filled, values = self._mail_filled()
            if filled:
                self._mail_raise_errors(values)
            self.write({"step": "preflight", "confirmed": False})
            return self._reopen()
        before = self.step
        result = super().action_next()
        if before == "addons":
            self.write({"step": "email"})
        return result

    def action_back(self):
        self.ensure_one()
        if self.step in ("preflight", "email"):
            self.write({"step": "email" if self.step == "preflight" else "addons", "confirmed": False})
            return self._reopen()
        return super().action_back()

    def _after_firm_created(self, firm):
        super()._after_firm_created(firm)
        filled, values = self._mail_filled()
        if self.mail_choice == "platform":
            # The provisioning step "Set up the firm's email" makes the address.
            firm.sudo().mail_choice = "platform"
        elif filled:
            firm._mail_send_settings(values, user=self.env.user)
        self._mail_forget_password()
