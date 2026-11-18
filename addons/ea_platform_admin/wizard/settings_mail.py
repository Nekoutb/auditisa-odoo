"""Platform settings: "Sending service for firms" (MailerSend and the parent domain's Cloudflare zone),
and the practice spaces' recipient list.

Like every other token of the console, the two tokens are not settings: there is no field for them. They
are files only root can read on the console's server, which systemd hands to Odoo (LoadCredential),
written with deploy/control-plane/set-mail-token.sh. This screen only says whether each was received, and
"Test the connection" checks both with read-only calls. See docs/runbook/PLATFORM-EMAIL.md.
"""

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..models.i18n import t
from ..models.platform_services import (
    CREDENTIAL_CLOUDFLARE_MAIL,
    CREDENTIAL_MAILERSEND,
    PARAM_MAIL_LOCAL,
    PARAM_MAIL_PARENT,
    PARAM_MAIL_ZONE,
    PARAM_MAIL_ZONE_ID,
    PARAM_PRACTICE_ALLOWLIST,
)
from ..services import platform_mail
from ..services.messages import _
from ..services.provider import ProviderError


class PlatformSettings(models.TransientModel):
    _inherit = "platform.settings"

    mail_parent_domain = fields.Char(
        "Parent domain", default=lambda self: self._param(PARAM_MAIL_PARENT, platform_mail.DEFAULT_PARENT),
        help="Each firm gets the address support@<the firm's slug>.<this domain>.",
    )
    mail_zone_name = fields.Char(
        "Cloudflare zone", default=lambda self: self._param(PARAM_MAIL_ZONE) or self._param(
            PARAM_MAIL_PARENT, platform_mail.DEFAULT_PARENT),
        help="The domain as Cloudflare names it, usually the parent domain itself. Its id is looked up by "
             "\"Test the connection\".",
    )
    mail_zone_ref = fields.Char("Cloudflare zone id (looked up)", readonly=True,
                                default=lambda self: self._param(PARAM_MAIL_ZONE_ID))
    mail_local_part = fields.Char(
        "Sender name", default=lambda self: self._param(PARAM_MAIL_LOCAL, platform_mail.DEFAULT_LOCAL_PART),
        help="What comes before the @ in every firm's address. Usually support.",
    )
    mailersend_received = fields.Boolean("MailerSend token received", compute="_compute_mail_received")
    cloudflare_mail_received = fields.Boolean("Cloudflare token received", compute="_compute_mail_received")
    mail_check_result = fields.Text("Connection test", readonly=True)
    practice_mail_allowlist = fields.Text(
        "Practice spaces may email only these addresses",
        default=lambda self: self._param(PARAM_PRACTICE_ALLOWLIST),
        help="One address per line. A practice space sends to these addresses only; every other recipient is "
             "dropped and logged. Empty: practice spaces send no email at all (the default).",
    )

    @api.depends_context("uid")
    def _compute_mail_received(self):
        services = self.env["platform.services"]
        mailersend = services._mail_credential_present(CREDENTIAL_MAILERSEND)
        cloudflare = services._mail_credential_present(CREDENTIAL_CLOUDFLARE_MAIL)
        for settings in self:
            settings.mailersend_received = mailersend
            settings.cloudflare_mail_received = cloudflare

    def _mail_check_values(self):
        problems = platform_mail.parent_errors(self.mail_parent_domain)
        problems += [_("Cloudflare zone: %(problem)s", problem=p) for p in platform_mail.parent_errors(self.mail_zone_name)]
        problems += platform_mail.local_part_errors(self.mail_local_part)
        problems += platform_mail.parse_allowlist(self.practice_mail_allowlist)[1]
        parent = platform_mail.clean_parent(self.mail_parent_domain)
        zone = platform_mail.clean_parent(self.mail_zone_name)
        if not problems and not (parent == zone or parent.endswith("." + zone)):
            problems.append(_("The parent domain must be inside the Cloudflare zone."))
        if problems:
            raise UserError("\n".join(t(self.env, problem) for problem in problems))

    def action_save(self):
        self.ensure_one()
        self._mail_check_values()
        params = self.env["ir.config_parameter"].sudo()
        zone = platform_mail.clean_parent(self.mail_zone_name)
        if zone != (params.get_param(PARAM_MAIL_ZONE) or ""):
            # Another zone: its id is looked up again by "Test the connection".
            params.set_param(PARAM_MAIL_ZONE_ID, False)
        addresses = platform_mail.parse_allowlist(self.practice_mail_allowlist)[0]
        before = platform_mail.parse_allowlist(params.get_param(PARAM_PRACTICE_ALLOWLIST) or "")[0]
        params.set_param(PARAM_MAIL_PARENT, platform_mail.clean_parent(self.mail_parent_domain))
        params.set_param(PARAM_MAIL_ZONE, zone)
        params.set_param(PARAM_MAIL_LOCAL, (self.mail_local_part or "").strip().lower())
        params.set_param(PARAM_PRACTICE_ALLOWLIST, "\n".join(addresses) or False)
        if addresses != before:
            self.env["platform.log"]._record(
                _("Practice spaces' email list changed"),
                detail=_("%(count)s address(es) allowed", count=len(addresses)),
            )
        return super().action_save()

    def action_mail_test(self):
        """Read-only calls to both services. Says in plain words what works, and keeps the zone's id."""
        self.ensure_one()
        self._mail_check_values()
        services = self.env["platform.services"]
        params = self.env["ir.config_parameter"].sudo()
        lines = []
        if services._is_simulation():
            lines.append(_("Simulation: no real call was made. Both services answer as if all were right."))
        try:
            mailersend, zone = services._mail_outside(zone_id="")
        except ProviderError as error:
            lines.append(_("Not tested: %(reason)s", reason=error.message))
            mailersend = zone = None
        if mailersend is not None:
            try:
                mailersend.check()
                lines.append(_("MailerSend: connected. The token can read the sending domains."))
            except ProviderError as error:
                lines.append(_("MailerSend: %(reason)s", reason=error.message))
            try:
                zone.check()
                name = platform_mail.clean_parent(self.mail_zone_name)
                zone_id = zone.find_zone(name)
                if zone_id:
                    params.set_param(PARAM_MAIL_ZONE, name)
                    params.set_param(PARAM_MAIL_ZONE_ID, zone_id)
                    self.mail_zone_ref = zone_id
                    lines.append(_("Cloudflare: connected. The zone %(zone)s was found.", zone=name))
                else:
                    lines.append(_("Cloudflare: connected, but this token cannot see the zone %(zone)s. Give the "
                                   "token the permission Zone, DNS, Edit on that zone.", zone=name))
            except ProviderError as error:
                lines.append(_("Cloudflare: %(reason)s", reason=error.message))
        self.mail_check_result = "\n".join(t(self.env, line) for line in lines)
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
            "view_mode": "form", "views": [(False, "form")], "target": "current",
        }
