from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services import addons as catalogue
from ..services import health
from ..services.messages import _
from .i18n import t

BACKUP_STATES = [
    ("ok", "Up to date"),
    ("late", "Late"),
    ("missed", "Missed"),
    ("failed", "Failed"),
    ("none", "None yet"),
]
OPEN_STATES = ("provisioning", "active", "suspended")


class PlatformFirm(models.Model):
    """A firm's optional add-ons, and what the supervision page shows. See services/addons.py."""

    _inherit = "platform.firm"

    addon_line_ids = fields.One2many("platform.firm.addon", "firm_id", "Optional add-ons")
    addons_reported_at = fields.Datetime("Add-ons last reported on", readonly=True, copy=False)
    addons_differ_count = fields.Integer("Add-ons not as asked", readonly=True, copy=False, index=True)
    addons_refused_count = fields.Integer("Add-on requests refused by the server", readonly=True, copy=False)
    addons_unknown_count = fields.Integer("Reported codes outside the catalogue", readonly=True, copy=False)
    addons_on_summary = fields.Char("Add-ons on", compute="_compute_addon_summary")
    addons_asked_summary = fields.Char("Add-ons asked", compute="_compute_addon_summary")
    base_feature_count = fields.Integer("Base features", compute="_compute_base_features")
    base_addon_ids = fields.Many2many("platform.addon", string="Base features, always on", compute="_compute_base_features")

    provider_label = fields.Char("Provider", compute="_compute_supervision")
    site_url = fields.Char("Site on the platform address", compute="_compute_supervision")
    own_site_url = fields.Char("Site on the firm's own domain", compute="_compute_supervision")
    server_plan = fields.Char("Server plan", compute="_compute_supervision")
    backup_state = fields.Selection(BACKUP_STATES, "Backup", compute="_compute_supervision")
    restore_state = fields.Selection(BACKUP_STATES, "Restore test", compute="_compute_supervision")

    # ------------------------------------------------------------------ computes

    @api.depends("addon_line_ids.desired", "addon_line_ids.reported")
    def _compute_addon_summary(self):
        for firm in self:
            firm.addons_on_summary = ", ".join(firm.addon_line_ids.filtered("reported").mapped("addon_id.name_text"))
            firm.addons_asked_summary = ", ".join(firm.addon_line_ids.filtered("desired").mapped("addon_id.name_text"))

    def _compute_base_features(self):
        base = self.env["platform.addon"].sudo().search([("is_optional", "=", False)])
        for firm in self:
            firm.base_addon_ids = base
            firm.base_feature_count = len(base)

    @api.depends("platform_host", "custom_domain", "is_simulation", "size", "region", "last_backup_at",
                 "last_backup_ok", "last_restore_test_at", "last_restore_test_ok")
    @api.depends_context("lang")
    def _compute_supervision(self):
        now = fields.Datetime.now()
        for firm in self:
            firm.provider_label = t(self.env, _("Simulation") if firm.is_simulation else _("Vultr"))
            # A simulation firm has no server behind it: its address leads nowhere.
            firm.site_url = f"https://{firm.platform_host}" if firm.platform_host and not firm.is_simulation else False
            firm.own_site_url = f"https://{firm.custom_domain}" if firm.custom_domain and not firm.is_simulation else False
            firm.server_plan = firm.size
            firm.backup_state = health.backup_state(
                firm.last_backup_at, firm.last_backup_ok if firm.last_backup_at else None, now,
            )
            firm.restore_state = _restore_state(firm, now)

    # ------------------------------------------------------------------ the catalogue, on a firm

    def _ensure_addon_lines(self):
        """Every optional add-on of the catalogue has a row on every firm, off until someone asks."""
        optional = self.env["platform.addon"].sudo().search([("is_optional", "=", True)])
        lines = self.env["platform.firm.addon"].sudo()
        for firm in self:
            missing = optional - firm.sudo().addon_line_ids.addon_id
            if missing:
                lines.create([{"firm_id": firm.id, "addon_id": addon.id} for addon in missing])

    @api.model_create_multi
    def create(self, vals_list):
        firms = super().create(vals_list)
        firms._ensure_addon_lines()
        return firms

    def _running_release(self):
        """The release the firm says it runs; before its first heartbeat, the one it was given."""
        self.ensure_one()
        release = self.env["platform.release"].sudo().with_context(active_test=False)
        if self.addon_release:
            return release.search([("sha", "=", self.addon_release)], limit=1)
        return self.sudo().desired_release_id

    def _allowed_addon_codes(self):
        """The optional add-ons of the running release. What this platform will ever ask for."""
        self.ensure_one()
        release = self._running_release()
        return release._optional_codes() if release else []

    def _set_addon(self, addon, on, reason, user=None):
        """The one way to change what is asked. Logged: who, when, why. It never uninstalls."""
        self.ensure_one()
        firm = self.sudo()
        if not addon.is_optional:
            raise UserError(t(self.env, _("%(code)s is a base feature: it is always on, for every firm.", code=addon.code)))
        if firm.state not in OPEN_STATES:
            raise UserError(t(self.env, _("Add-ons no longer change on a firm that is leaving or archived.")))
        if not (reason or "").strip():
            raise UserError(t(self.env, _("Say why: the reason goes in the platform log.")))
        if on and addon.code not in firm._allowed_addon_codes():
            raise UserError(t(self.env, _(
                "%(code)s is not in the release this firm runs: it can be asked for after an update to a release that carries it.",
                code=addon.code,
            )))
        firm._ensure_addon_lines()
        line = firm.addon_line_ids.filtered(lambda row: row.addon_id == addon)
        if line.desired == on:
            return False
        line.write({"desired": on, "changed_at": fields.Datetime.now(), "changed_by": (user or self.env.user).id})
        self.env["platform.log"]._record(
            _("Add-on switched on") if on else _("Add-on switched off (hidden, data kept)"),
            firm,
            _("%(code)s. Reason: %(reason)s", code=addon.code, reason=reason.strip()),
            user=user or self.env.user,
        )
        firm._evaluate_health()
        return True

    # ------------------------------------------------------------------ heartbeat

    def _heartbeat_answer(self):
        """Only add-ons of the running release, only to a live firm, only once that release is listed."""
        answer = super()._heartbeat_answer()
        release = self._running_release()
        if self.state == "active" and release and release.catalogue_loaded_at:
            asked = self.sudo().addon_line_ids.filtered("desired").mapped("code")
            answer["desired_addons"] = catalogue.desired_answer(asked, release._optional_codes())
        return answer

    def _apply_figures(self, figures, timestamp):
        reported = figures.get("addons_on")
        if reported is not None:
            self._apply_addons_reported(reported)
        self.write({"addons_refused_count": figures.get("addons_refused", 0)})
        return super()._apply_figures(figures, timestamp)

    def _apply_addons_reported(self, reported):
        """Only a code the catalogue knows is kept. Any other is counted, and its text is dropped."""
        self.ensure_one()
        known_codes = set(self.env["platform.addon"].sudo().search([("is_optional", "=", True)]).mapped("code"))
        known, unknown = catalogue.split_reported(reported, known_codes)
        self._ensure_addon_lines()
        for line in self.addon_line_ids:
            if line.reported != (line.code in known):
                line.write({"reported": line.code in known})
        self.write({"addons_reported_at": fields.Datetime.now(), "addons_unknown_count": unknown})

    def _addon_lines_differing(self):
        self.ensure_one()
        return self.addon_line_ids.filtered(lambda line: line.status in catalogue.DIFFERENT)

    def _health_input(self):
        result = super()._health_input()
        if self.state == "active":
            result["addons_differ"] = len(self._addon_lines_differing())
            result["addons_refused"] = self.addons_refused_count
            result["addons_unknown"] = self.addons_unknown_count
        return result

    def _evaluate_health(self):
        for firm in self.sudo():
            count = len(firm._addon_lines_differing()) if firm.state == "active" else 0
            if firm.addons_differ_count != count:
                firm.write({"addons_differ_count": count})
        return super()._evaluate_health()

    def _simulate_heartbeat(self, release=None, **changes):
        """A simulated firm obeys what it is asked, unless a test says otherwise."""
        self.ensure_one()
        firm = self.sudo()
        if firm.is_simulation:
            asked = firm.addon_line_ids.filtered("desired").mapped("code")
            changes.setdefault("addons_on", catalogue.desired_answer(asked, firm._allowed_addon_codes()))
            changes.setdefault("addons_refused", 0)
        return super()._simulate_heartbeat(release=release, **changes)

    # ------------------------------------------------------------------ supervision

    @api.model
    def action_export_supervision(self):
        """Selected firms, or all that the current search shows, as an Excel file."""
        firms = self
        if not firms:
            domain = self.env.context.get("active_domain") or []
            firms = self.search(domain)
        ids = ",".join(str(firm_id) for firm_id in firms.ids)
        return {"type": "ir.actions.act_url", "url": f"/platform/supervision/export?ids={ids}", "target": "self"}

    def action_open_firm(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "platform.firm", "res_id": self.id,
            "view_mode": "form", "views": [(False, "form")], "target": "current",
        }

    def action_open_addon_page(self):
        return self.action_open_firm()


def _restore_state(firm, now):
    """Same word list as a backup's, by the limits of the restore test."""
    if not firm.last_restore_test_at:
        return "none"
    if firm.last_restore_test_ok is False:
        return "failed"
    age = now - firm.last_restore_test_at
    if age > health.RESTORE_RED:
        return "missed"
    if age > health.RESTORE_AMBER:
        return "late"
    return "ok"
