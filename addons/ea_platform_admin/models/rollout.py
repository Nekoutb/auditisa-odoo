from datetime import datetime

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services import rollout as engine
from ..services.heartbeat import format_instant
from ..services.messages import _, dumps_list
from .i18n import read, t

ROLLOUT_STATES = [
    ("draft", "Draft"),
    ("running", "Running"),
    ("stopped", "Stopped on failure"),
    ("done", "Finished"),
]
LINE_STATES = [
    ("pending", "Waiting"),
    ("requested", "Requested"),
    ("healthy", "Succeeded"),
    ("failed", "Failed"),
    ("rolled_back", "Rolled back"),
    ("timed_out", "No answer"),
    ("cancelled", "Cancelled"),
]
# The same, for stored messages.
LINE_LABELS = {
    "healthy": _("Succeeded"),
    "failed": _("Failed"),
    "rolled_back": _("Rolled back"),
    "timed_out": _("No answer"),
}


class PlatformRollout(models.Model):
    """A release going out: a canary firm, then batches, stopping at the first failure.

    Firms pull. Asking means naming the release in the firm's next heartbeat answer. The firm backs
    up, updates, checks itself and rolls itself back on failure: see deploy/firm/firm-update.sh.
    """

    _name = "platform.rollout"
    _description = "Rollout"
    _order = "id desc"
    _rec_name = "release_id"

    release_id = fields.Many2one("platform.release", "Release", required=True, ondelete="restrict")
    canary_firm_id = fields.Many2one("platform.firm", "Canary firm", required=True, ondelete="restrict",
                                     domain=[("state", "=", "active")])
    firm_ids = fields.Many2many("platform.firm", string="Firms", domain=[("state", "=", "active")])
    batch_size = fields.Integer("Batch size", default=2, required=True)
    state = fields.Selection(ROLLOUT_STATES, "State", default="draft", readonly=True, required=True)
    line_ids = fields.One2many("platform.rollout.line", "rollout_id", "Progress", readonly=True)
    stop_reason_raw = fields.Text("Reason for stopping (source)", readonly=True)
    stop_reason = fields.Char("Reason for stopping", compute="_compute_text")
    skipped_raw = fields.Text("Firms set aside (source)", readonly=True)
    skipped = fields.Text("Firms set aside", compute="_compute_text")
    started_at = fields.Datetime("Started on", readonly=True)
    finished_at = fields.Datetime("Finished on", readonly=True)

    @api.depends("stop_reason_raw", "skipped_raw")
    @api.depends_context("lang")
    def _compute_text(self):
        for rollout in self:
            rollout.stop_reason = read(self.env, rollout.stop_reason_raw)
            rollout.skipped = read(self.env, rollout.skipped_raw)

    def _eligibility(self, firm):
        return engine.ineligible_reason({
            "state": firm.state,
            "health_color": firm.health_color,
            "release_locked": firm.release_locked,
            "last_backup_at": firm.last_backup_at,
            "last_backup_ok": firm.last_backup_ok if firm.last_backup_at else None,
        })

    def action_start(self):
        self.ensure_one()
        if self.state != "draft":
            raise UserError(t(self.env, _("This rollout has already started.")))
        if self.batch_size < 1:
            raise UserError(t(self.env, _("The batch size must be at least 1.")))
        running = self.search([("state", "=", "running"), ("id", "!=", self.id)], limit=1)
        if running:
            raise UserError(t(self.env, _("Another rollout is running: only one at a time.")))
        reason = self._eligibility(self.canary_firm_id)
        if reason:
            raise UserError(t(self.env, _("The canary firm is not suitable: %(reason)s.", reason=reason)))
        firms = (self.firm_ids | self.canary_firm_id).sudo()
        kept, skipped = [], []
        for firm in firms:
            reason = self._eligibility(firm)
            if reason:
                skipped.append(_("%(firm)s: %(reason)s", firm=firm.name, reason=reason))
            elif firm.addon_release == self.release_id.sha:
                skipped.append(_("%(firm)s: %(reason)s", firm=firm.name, reason=_("already on this release")))
            else:
                kept.append(firm)
        if self.canary_firm_id not in kept:
            raise UserError(t(self.env, _("The canary firm is already on this release: choose another.")))
        plan = engine.plan_batches([firm.id for firm in kept], self.canary_firm_id.id, self.batch_size)
        self.env["platform.rollout.line"].sudo().create([
            {"rollout_id": self.id, "firm_id": firm_id, "batch": batch} for firm_id, batch in plan
        ])
        self.sudo().write({
            "state": "running",
            "started_at": fields.Datetime.now(),
            "skipped_raw": dumps_list(skipped) if skipped else False,
        })
        self.env["platform.log"]._record(
            _("Rollout started"), self.canary_firm_id,
            _("Release %(release)s, canary %(canary)s, %(count)s firm(s)",
              release=self.release_id.sha[:12], canary=self.canary_firm_id.slug, count=len(plan)),
        )
        self._advance()
        return True

    def _advance(self):
        now = fields.Datetime.now()
        for rollout in self.sudo():
            if rollout.state != "running":
                continue
            target = rollout.release_id.sha
            for line in rollout.line_ids.filtered(lambda l: l.state == "requested"):
                firm = line.firm_id
                outcome = engine.line_outcome(line.requested_at, target, {
                    "last_heartbeat_at": firm.last_heartbeat_at,
                    "update_release": firm.update_release,
                    "update_state": firm.update_state,
                    "release": firm.addon_release,
                    "last_backup_at": firm.last_backup_at,
                    "health_color": firm.health_color,
                }, now)
                if outcome != engine.REQUESTED:
                    line._close(outcome)
            decision, line_ids = engine.next_step([
                {"id": line.id, "batch": line.batch, "state": line.state} for line in rollout.line_ids
            ])
            if decision == "request":
                rollout.line_ids.browse(line_ids)._request(rollout.release_id)
            elif decision == "stopped":
                rollout.line_ids.browse(line_ids).write({"state": "cancelled"})
                bad = rollout.line_ids.filtered(lambda l: l.state in engine.BAD_STATES)[:1]
                reason = _("%(firm)s: %(reason)s", firm=bad.firm_id.name, reason=LINE_LABELS[bad.state])
                rollout.write({"state": "stopped", "stop_reason_raw": dumps_list([reason]), "finished_at": now})
                self.env["platform.log"]._record(_("Rollout STOPPED on failure"), bad.firm_id, reason)
                bad.firm_id._alert([_("Rollout stopped: %(reason)s", reason=reason)])
            elif decision == "done":
                rollout.write({"state": "done", "finished_at": now})
                self.env["platform.log"]._record(_("Rollout finished"), rollout.canary_firm_id,
                                                 _("Release %(release)s", release=target[:12]))

    @api.model
    def _on_firm_figures(self, firm):
        lines = self.env["platform.rollout.line"].sudo().search([
            ("firm_id", "=", firm.id), ("state", "=", "requested"), ("rollout_id.state", "=", "running"),
        ])
        lines.rollout_id._advance()

    @api.model
    def _cron_advance(self):
        self.search([("state", "=", "running")])._advance()

    def action_simulate_answers(self):
        """Simulated firms answer. Firms named in the context `fail_slugs` report a failed update."""
        self.ensure_one()
        fail = self.env.context.get("fail_slugs") or []
        now = format_instant(datetime.utcnow().replace(microsecond=0))
        target = self.release_id.sha
        for line in self.line_ids.filtered(lambda l: l.state == "requested"):
            firm = line.firm_id
            if not firm.is_simulation:
                raise UserError(t(self.env, _("Only for simulation firms.")))
            if firm.slug in fail:
                firm._simulate_heartbeat(
                    release=firm.sudo().addon_release, update_state="rolled_back",
                    update_release=target, last_backup_at=now,
                )
            else:
                firm._simulate_heartbeat(release=target, update_state="ok", update_release=target, last_backup_at=now)
        return True


class PlatformRolloutLine(models.Model):
    _name = "platform.rollout.line"
    _description = "Firm in a rollout"
    _order = "batch, id"
    _rec_name = "firm_id"

    rollout_id = fields.Many2one("platform.rollout", required=True, ondelete="cascade", index=True)
    firm_id = fields.Many2one("platform.firm", "Firm", required=True, ondelete="restrict", readonly=True)
    batch = fields.Integer("Batch", readonly=True, help="Batch 0 is the canary firm.")
    state = fields.Selection(LINE_STATES, "State", default="pending", readonly=True, required=True)
    previous_release_id = fields.Many2one("platform.release", "Previous release", readonly=True, ondelete="restrict")
    requested_at = fields.Datetime("Requested on", readonly=True)
    closed_at = fields.Datetime("Closed on", readonly=True)

    def _request(self, release):
        now = fields.Datetime.now()
        for line in self:
            firm = line.firm_id
            line.write({"state": "requested", "requested_at": now, "previous_release_id": firm.desired_release_id.id})
            firm.write({"desired_release_id": release.id})
            self.env["platform.log"]._record(_("Update requested from the firm"), firm, _("Release %(release)s", release=release.sha[:12]))

    def _close(self, outcome):
        self.ensure_one()
        self.write({"state": outcome, "closed_at": fields.Datetime.now()})
        if outcome in engine.BAD_STATES:
            # So the firm is not asked again at its next heartbeat. The firm rolled itself back.
            self.firm_id.write({"desired_release_id": self.previous_release_id.id})
        self.env["platform.log"]._record(
            _("Firm's update: %(outcome)s", outcome=LINE_LABELS[outcome]), self.firm_id,
            _("Release %(release)s", release=self.rollout_id.release_id.sha[:12]),
        )
