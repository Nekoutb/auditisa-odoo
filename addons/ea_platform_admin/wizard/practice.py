from odoo import fields, models
from odoo.exceptions import UserError

from ..models.i18n import t
from ..services.messages import _


class PlatformPracticeResetWizard(models.TransientModel):
    """Back to fresh demo data: everything the firm typed in its practice space goes."""

    _name = "platform.practice.reset.wizard"
    _description = "Reset a practice space"

    space_id = fields.Many2one("platform.practice.space", "Practice space", required=True, readonly=True)
    slug = fields.Char(related="space_id.slug")
    computer_simulated = fields.Boolean(related="space_id.computer_simulated")
    typed = fields.Char("Type the firm's slug to confirm")
    reason = fields.Text("Why")

    def action_confirm(self):
        self.ensure_one()
        if (self.typed or "").strip() != self.space_id.slug:
            raise UserError(t(self.env, _("Type the slug exactly as shown: nothing was reset.")))
        self.space_id._request_reset(self.reason, user=self.env.user)
        return {"type": "ir.actions.act_window_close"}


class PlatformPracticeFirstLogin(models.TransientModel):
    """Shows a practice space's first login once: address, login and the one-time link."""

    _name = "platform.practice.first.login"
    _description = "First login of a practice space"

    space_id = fields.Many2one("platform.practice.space", "Practice space", required=True, readonly=True)
    address = fields.Char(related="space_id.address")
    login = fields.Char(related="space_id.admin_login", string="Login")
    ready = fields.Boolean(related="space_id.first_login_ready")
    computer_simulated = fields.Boolean(related="space_id.computer_simulated")
    revealed = fields.Boolean(readonly=True)
    link = fields.Char("One-time link", readonly=True)
    expires_at = fields.Datetime("Expires on", readonly=True)

    def action_reveal(self):
        self.ensure_one()
        space = self.space_id.sudo()
        if not space.first_login_ready or not space.first_login_token:
            raise UserError(t(self.env, _(
                "This link is not available: it has already been shown, it has expired, or the practice computer "
                "has not received it yet. Make a new one with the button on the practice space."
            )))
        self.write({
            "revealed": True,
            "link": space._first_login_link(space.first_login_token),
            "expires_at": space.first_login_expires_at,
        })
        space.write({"first_login_token": False, "first_login_revealed_at": fields.Datetime.now()})
        self.env["platform.log"]._record(_("First login of a practice space shown"), space.firm_id, space.slug, user=self.env.user)
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form",
            "target": "new",
        }

    def action_close(self):
        self.write({"link": False})
        return {"type": "ir.actions.act_window_close"}


class PlatformPracticeReleaseWizard(models.TransientModel):
    """A release goes to the practice computer first; the firms' holding period starts when it runs there."""

    _name = "platform.practice.release.wizard"
    _description = "Send a release to the practice computer"

    computer_id = fields.Many2one("platform.practice.computer", "Practice computer", required=True, readonly=True)
    release_id = fields.Many2one("platform.release", "Release", required=True)
    hold_days = fields.Integer(related="release_id.practice_hold_days", readonly=True)

    def action_confirm(self):
        self.ensure_one()
        if not self.env.user.has_group("ea_platform_admin.group_platform_owner"):
            raise UserError(t(self.env, _("Only the owner can send a release.")))
        self.computer_id.sudo().write({"desired_release_id": self.release_id.id})
        self.env["platform.log"]._record(
            _("Release sent to the practice computer"), None,
            _("Release %(release)s; firms after %(days)s day(s) there", release=self.release_id.sha[:12], days=self.hold_days),
        )
        return {"type": "ir.actions.act_window_close"}


class PlatformOnboardingWizard(models.TransientModel):
    """The new firm gets its practice space, with the same add-ons, unless the switch is turned off."""

    _inherit = "platform.onboarding.wizard"

    practice_space = fields.Boolean(
        "Also create its practice space", default=True,
        help="A separate space on the shared practice computer, with made-up data and the same add-ons, "
             "where the firm can try new versions before its own server gets them.",
    )

    def _after_firm_created(self, firm):
        result = super()._after_firm_created(firm)
        if self.practice_space:
            self.env["platform.practice.space"]._create_for(firm)
        return result
