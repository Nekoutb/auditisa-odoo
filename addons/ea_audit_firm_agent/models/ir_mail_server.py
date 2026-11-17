import logging

from odoo import api, models
from odoo.addons.base.models.ir_mail_server import MailDeliveryException

from ..services import recipients
from .firm_agent import PARAM_MAIL_REPLY_TO, PARAM_MAIL_TESTED

_logger = logging.getLogger(__name__)

PARAM_MAIL_GATE = "ea_firm_agent.mail_gate"
# Changing one of these means the mail settings have to prove themselves again. Switching the
# server off closes the gate too; switching it on does not reopen it, and does not close it either:
# root's firm-mail-server switches the server on right after the test passed, and until 2026-11-17
# that very write closed the gate again, so a firm's mail never opened (and no "Forgot your password?").
_SMTP_FIELDS = frozenset({
    "smtp_host", "smtp_port", "smtp_user", "smtp_pass", "smtp_encryption", "smtp_authentication",
    "from_filter",
})
_MAIL_CRONS = ("mail.ir_cron_mail_scheduler_action", "mail.ir_cron_mail_gateway_action")
# "Forgot your password?" sends a mail: offered only while mail is open (test-firm run, 2026-11-09).
PARAM_RESET_PASSWORD = "auth_signup.reset_password"
# A practice space: emails go only to the allowed addresses (services/recipients.py). Set by deploy/practice.
PARAM_RECIPIENT_GATE = "ea_firm_agent.recipient_gate"
PARAM_RECIPIENT_ALLOWLIST = "ea_firm_agent.recipient_allowlist"


class IrMailServer(models.Model):
    """On a firm's server, nothing leaves until the firm's own mail settings have passed a test.

    The gate is set by the install script (`ea_firm_agent.mail_gate` = 1). Staging and the other
    databases do not have the parameter, and nothing changes for them.
    """

    _inherit = "ir.mail_server"

    def _ea_mail_gate_closed(self):
        get_param = self.env["ir.config_parameter"].sudo().get_param
        return get_param(PARAM_MAIL_GATE) == "1" and get_param(PARAM_MAIL_TESTED) != "1"

    @api.model
    def _ea_keep_reset_closed(self):
        """While the gate is closed, no "Forgot your password?": it could send nothing.

        The install sets this on a new firm, but a firm updated from an older release kept the link
        (update test, 2026-11-09). The heartbeat cron calls this, so every firm converges.
        """
        params = self.env["ir.config_parameter"].sudo()
        if self._ea_mail_gate_closed() and params.get_param(PARAM_RESET_PASSWORD) != "False":
            params.set_param(PARAM_RESET_PASSWORD, "False")
            return True
        return False

    def _ea_mail_closed(self):
        return MailDeliveryException(
            self.env._("Mail closed"),
            self.env._(
                "This firm's mail is not open: enter a mail server and pass the connection test."
            ),
        )

    def _connect__(self, *args, **kwargs):  # noqa: PLW3201
        # Odoo 19 connects before it sends: closed, not even a connection is opened (on the first
        # real firm, 2026-11-09, each notice tried localhost:25 first). The connection test may.
        if self._ea_mail_gate_closed() and not self.env.context.get("ea_mail_gate_testing"):
            raise self._ea_mail_closed()
        return super()._connect__(*args, **kwargs)

    def send_email(self, message, *args, **kwargs):
        if self._ea_mail_gate_closed():
            raise self._ea_mail_closed()
        params = self.env["ir.config_parameter"].sudo()
        if params.get_param(PARAM_RECIPIENT_GATE) == "1":
            allowlist = recipients.parse_allowlist(params.get_param(PARAM_RECIPIENT_ALLOWLIST) or "")
            kept, dropped = recipients.filter_message(message, allowlist)
            if dropped:
                _logger.warning(
                    "Practice space: %s recipient(s) dropped, not on the allowed list: %s",
                    len(dropped), ", ".join(recipients.mask(address) for address in dropped),
                )
            if not kept:
                _logger.warning("Practice space: email not sent, no allowed recipient")
                return message["Message-Id"]
        return super().send_email(message, *args, **kwargs)

    @api.model
    def _build_email__(self, email_from, email_to, subject, body, *args, **kwargs):  # noqa: PLW3201
        """With the console's platform address, replies go to the firm's contact email (owner, 2026-11-18),
        unless the email already names another reply address."""
        reply_to = self.env["ir.config_parameter"].sudo().get_param(PARAM_MAIL_REPLY_TO)
        if reply_to:
            args = list(args)
            current = args[2] if len(args) > 2 else kwargs.get("reply_to")
            if not current or current == email_from:
                if len(args) > 2:
                    args[2] = reply_to
                else:
                    kwargs["reply_to"] = reply_to
        return super()._build_email__(email_from, email_to, subject, body, *args, **kwargs)

    def test_smtp_connection(self, autodetect_max_email_size=False):
        result = super(IrMailServer, self.with_context(ea_mail_gate_testing=True)).test_smtp_connection(
            autodetect_max_email_size,
        )
        params = self.env["ir.config_parameter"].sudo()
        if params.get_param(PARAM_MAIL_GATE) == "1" and params.get_param(PARAM_MAIL_TESTED) != "1":
            params.set_param(PARAM_MAIL_TESTED, "1")
            params.set_param(PARAM_RESET_PASSWORD, "True")
            for xmlid in _MAIL_CRONS:
                cron = self.env.ref(xmlid, raise_if_not_found=False)
                if cron:
                    cron.sudo().write({"active": True})
        return result

    def write(self, vals):
        result = super().write(vals)
        if _SMTP_FIELDS & set(vals) or ("active" in vals and not vals["active"]):
            params = self.env["ir.config_parameter"].sudo()
            if params.get_param(PARAM_MAIL_GATE) == "1" and params.get_param(PARAM_MAIL_TESTED) == "1":
                params.set_param(PARAM_MAIL_TESTED, "0")
                params.set_param(PARAM_RESET_PASSWORD, "False")
        return result
