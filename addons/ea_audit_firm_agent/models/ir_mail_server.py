from odoo import models
from odoo.addons.base.models.ir_mail_server import MailDeliveryException

from .firm_agent import PARAM_MAIL_TESTED

PARAM_MAIL_GATE = "ea_firm_agent.mail_gate"
# Changing one of these means the mail settings have to prove themselves again.
_SMTP_FIELDS = frozenset({
    "smtp_host", "smtp_port", "smtp_user", "smtp_pass", "smtp_encryption", "smtp_authentication",
    "from_filter", "active",
})
_MAIL_CRONS = ("mail.ir_cron_mail_scheduler_action", "mail.ir_cron_mail_gateway_action")


class IrMailServer(models.Model):
    """On a firm's server, nothing leaves until the firm's own mail settings have passed a test.

    The gate is set by the install script (`ea_firm_agent.mail_gate` = 1). Staging and the other
    databases do not have the parameter, and nothing changes for them.
    """

    _inherit = "ir.mail_server"

    def _ea_mail_gate_closed(self):
        get_param = self.env["ir.config_parameter"].sudo().get_param
        return get_param(PARAM_MAIL_GATE) == "1" and get_param(PARAM_MAIL_TESTED) != "1"

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
        return super().send_email(message, *args, **kwargs)

    def test_smtp_connection(self, autodetect_max_email_size=False):
        result = super(IrMailServer, self.with_context(ea_mail_gate_testing=True)).test_smtp_connection(
            autodetect_max_email_size,
        )
        params = self.env["ir.config_parameter"].sudo()
        if params.get_param(PARAM_MAIL_GATE) == "1" and params.get_param(PARAM_MAIL_TESTED) != "1":
            params.set_param(PARAM_MAIL_TESTED, "1")
            for xmlid in _MAIL_CRONS:
                cron = self.env.ref(xmlid, raise_if_not_found=False)
                if cron:
                    cron.sudo().write({"active": True})
        return result

    def write(self, vals):
        result = super().write(vals)
        if _SMTP_FIELDS & set(vals):
            params = self.env["ir.config_parameter"].sudo()
            if params.get_param(PARAM_MAIL_GATE) == "1" and params.get_param(PARAM_MAIL_TESTED) == "1":
                params.set_param(PARAM_MAIL_TESTED, "0")
        return result
