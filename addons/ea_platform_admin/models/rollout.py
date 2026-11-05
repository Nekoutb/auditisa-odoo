from datetime import datetime

from odoo import api, fields, models
from odoo.exceptions import UserError

from ..services import rollout as engine
from ..services.heartbeat import format_instant

ROLLOUT_STATES = [
    ("draft", "Brouillon"),
    ("running", "En cours"),
    ("stopped", "Arrêtée sur échec"),
    ("done", "Terminée"),
]
LINE_STATES = [
    ("pending", "En attente"),
    ("requested", "Demandée"),
    ("healthy", "Réussie"),
    ("failed", "Échec"),
    ("rolled_back", "Retour arrière"),
    ("timed_out", "Sans réponse"),
    ("cancelled", "Annulée"),
]


class PlatformRollout(models.Model):
    """A release going out: a canary firm, then batches, stopping at the first failure.

    Firms pull. Asking means naming the release in the firm's next heartbeat answer. The firm backs
    up, updates, checks itself and rolls itself back on failure: see deploy/firm/firm-update.sh.
    """

    _name = "platform.rollout"
    _description = "Mise à jour"
    _order = "id desc"
    _rec_name = "release_id"

    release_id = fields.Many2one("platform.release", "Version", required=True, ondelete="restrict")
    canary_firm_id = fields.Many2one("platform.firm", "Cabinet témoin", required=True, ondelete="restrict",
                                     domain=[("state", "=", "active")])
    firm_ids = fields.Many2many("platform.firm", string="Cabinets", domain=[("state", "=", "active")])
    batch_size = fields.Integer("Taille des lots", default=2, required=True)
    state = fields.Selection(ROLLOUT_STATES, "État", default="draft", readonly=True, required=True)
    line_ids = fields.One2many("platform.rollout.line", "rollout_id", "Déroulement", readonly=True)
    stop_reason = fields.Char("Motif de l'arrêt", readonly=True)
    skipped = fields.Text("Cabinets écartés", readonly=True)
    started_at = fields.Datetime("Lancée le", readonly=True)
    finished_at = fields.Datetime("Finie le", readonly=True)

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
            raise UserError("Cette mise à jour est déjà lancée.")
        if self.batch_size < 1:
            raise UserError("La taille des lots doit être d'au moins 1.")
        running = self.search([("state", "=", "running"), ("id", "!=", self.id)], limit=1)
        if running:
            raise UserError("Une autre mise à jour est en cours : une seule à la fois.")
        reason = self._eligibility(self.canary_firm_id)
        if reason:
            raise UserError(f"Le cabinet témoin ne convient pas : {reason}.")
        firms = (self.firm_ids | self.canary_firm_id).sudo()
        kept, skipped = [], []
        for firm in firms:
            reason = self._eligibility(firm)
            if reason:
                skipped.append(f"{firm.name} : {reason}")
            elif firm.addon_release == self.release_id.sha:
                skipped.append(f"{firm.name} : déjà sur cette version")
            else:
                kept.append(firm)
        if self.canary_firm_id not in kept:
            raise UserError("Le cabinet témoin est déjà sur cette version : choisissez-en un autre.")
        plan = engine.plan_batches([firm.id for firm in kept], self.canary_firm_id.id, self.batch_size)
        self.env["platform.rollout.line"].sudo().create([
            {"rollout_id": self.id, "firm_id": firm_id, "batch": batch} for firm_id, batch in plan
        ])
        self.sudo().write({
            "state": "running",
            "started_at": fields.Datetime.now(),
            "skipped": "\n".join(skipped) or False,
        })
        self.env["platform.log"]._record(
            "Mise à jour lancée", self.canary_firm_id,
            f"Version {self.release_id.sha[:12]}, témoin {self.canary_firm_id.slug}, {len(plan)} cabinet(s)",
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
                reason = f"{bad.firm_id.name} : {dict(LINE_STATES)[bad.state]}"
                rollout.write({"state": "stopped", "stop_reason": reason, "finished_at": now})
                self.env["platform.log"]._record("Mise à jour ARRÊTÉE sur échec", bad.firm_id, reason)
                bad.firm_id._alert(f"Mise à jour arrêtée : {reason}")
            elif decision == "done":
                rollout.write({"state": "done", "finished_at": now})
                self.env["platform.log"]._record("Mise à jour terminée", rollout.canary_firm_id,
                                                 f"Version {target[:12]}")

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
                raise UserError("Réservé aux cabinets de simulation.")
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
    _description = "Cabinet d'une mise à jour"
    _order = "batch, id"
    _rec_name = "firm_id"

    rollout_id = fields.Many2one("platform.rollout", required=True, ondelete="cascade", index=True)
    firm_id = fields.Many2one("platform.firm", "Cabinet", required=True, ondelete="restrict", readonly=True)
    batch = fields.Integer("Lot", readonly=True, help="Le lot 0 est le cabinet témoin.")
    state = fields.Selection(LINE_STATES, "État", default="pending", readonly=True, required=True)
    previous_release_id = fields.Many2one("platform.release", "Version précédente", readonly=True, ondelete="restrict")
    requested_at = fields.Datetime("Demandée le", readonly=True)
    closed_at = fields.Datetime("Close le", readonly=True)

    def _request(self, release):
        now = fields.Datetime.now()
        for line in self:
            firm = line.firm_id
            line.write({"state": "requested", "requested_at": now, "previous_release_id": firm.desired_release_id.id})
            firm.write({"desired_release_id": release.id})
            self.env["platform.log"]._record("Mise à jour demandée au cabinet", firm, f"Version {release.sha[:12]}")

    def _close(self, outcome):
        self.ensure_one()
        self.write({"state": outcome, "closed_at": fields.Datetime.now()})
        if outcome in engine.BAD_STATES:
            # So the firm is not asked again at its next heartbeat. The firm rolled itself back.
            self.firm_id.write({"desired_release_id": self.previous_release_id.id})
        self.env["platform.log"]._record(
            f"Mise à jour du cabinet : {dict(LINE_STATES)[outcome]}", self.firm_id,
            f"Version {self.rollout_id.release_id.sha[:12]}",
        )
