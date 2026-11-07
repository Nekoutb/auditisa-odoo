import secrets

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ea_platform_admin.services.messages import _
from ..services import pipeline
from .i18n import t

STATES = [
    ("requested", "Asked of the firm"),
    ("running", "Firm is working"),
    ("exported", "Ready: carry it to staging"),
    ("rebuilt", "Staging rebuilt"),
    ("failed", "Failed at the firm"),
    ("refused", "Refused by the firm"),
    ("cancelled", "Cancelled"),
]
OPEN_STATES = ("requested", "running", "exported")


class PlatformPipelineRebuild(models.Model):
    """Rebuilding staging from a firm's anonymised copy. This record asks and logs: that is all.

    The firm's server makes the copy, anonymises it and keeps it. Here arrive a state and a digest, through
    the same closed heartbeat as any other figure. No row of a firm's data ever reaches this database.
    """

    _name = "platform.pipeline.rebuild"
    _description = "Staging rebuild"
    _inherit = ["platform.pipeline.guard"]
    _order = "id desc"
    _rec_name = "request_ref"

    source_firm_id = fields.Many2one(
        "platform.firm", "Source firm", required=True, ondelete="restrict",
        domain=[("state", "=", "active"), ("pipeline_role", "=", "firm")],
    )
    request_ref = fields.Char("Reference", required=True, readonly=True, copy=False, index=True,
                              default=lambda self: secrets.token_hex(8))
    state = fields.Selection(STATES, "State", default="requested", required=True, readonly=True)
    reason = fields.Text("Reason", readonly=True, copy=False)
    requested_by_id = fields.Many2one("res.users", "Asked by", readonly=True, copy=False)
    requested_at = fields.Datetime("Asked on", readonly=True, copy=False)
    export_sha256 = fields.Char("Digest of the anonymised copy", readonly=True, copy=False)
    exported_at = fields.Datetime("Ready on", readonly=True, copy=False)
    rebuilt_at = fields.Datetime("Staging rebuilt on", readonly=True, copy=False)
    next_step = fields.Text("What you do now", compute="_compute_next_step")

    _ref_unique = models.Constraint("unique(request_ref)", "This reference is already used.")

    @api.depends("state", "request_ref", "export_sha256")
    @api.depends_context("lang")
    def _compute_next_step(self):
        for rebuild in self:
            if rebuild.state == "requested":
                rebuild.next_step = t(self.env, _("The firm's server picks this up at its next heartbeat, in 15 minutes at most."))
            elif rebuild.state == "exported":
                rebuild.next_step = t(self.env, _(
                    "On your computer: scripts/pipeline/relay_anon_dump.sh <firm's address> %(ref)s %(digest)s root@108.61.209.30. "
                    "On staging: staging-rebuild --dump /var/lib/auditisa-staging/incoming/anon-%(ref)s.tar --sha256 %(digest)s. "
                    "Read the dry run, then add --apply. Then Record staging rebuilt.",
                    ref=rebuild.request_ref, digest=rebuild.export_sha256))
            elif rebuild.state in ("failed", "refused"):
                rebuild.next_step = t(self.env, _(
                    "Nothing left the firm. Its log says why. A refusal means the firm has not allowed exports: see docs/runbook/PIPELINE.md."))
            else:
                rebuild.next_step = False

    @api.model
    def _open_request(self, source, reason):
        """After the typed confirmation."""
        self._require_owner()
        source = source.sudo()
        if source.pipeline_role != "firm" or source.state != "active":
            raise UserError(t(self.env, _("Only an active firm can be the source.")))
        if self.sudo().search_count([("state", "in", OPEN_STATES)]):
            raise UserError(t(self.env, _("A rebuild is already open: finish or cancel it first.")))
        rebuild = self.sudo().create({
            "source_firm_id": source.id,
            "reason": reason,
            "requested_by_id": self.env.user.id,
            "requested_at": fields.Datetime.now(),
        })
        self.env["platform.log"]._record(
            _("Staging rebuild asked of the firm"), source,
            _("Reference %(ref)s, reason: %(reason)s", ref=rebuild.request_ref, reason=reason),
        )
        return rebuild

    @api.model
    def _on_firm_figures(self, firm, figures):
        rebuild = self.sudo().search(
            [("source_firm_id", "=", firm.id), ("state", "in", ("requested", "running"))], limit=1,
        )
        if not rebuild:
            return
        new_state = pipeline.rebuild_transition(rebuild.state, figures, rebuild.request_ref)
        if not new_state or new_state == rebuild.state:
            return
        values = {"state": new_state}
        if new_state == "exported":
            values.update({"export_sha256": figures["anon_export_sha256"], "exported_at": fields.Datetime.now()})
        rebuild.write(values)
        self.env["platform.log"]._record(
            {"running": _("Firm is making the anonymised copy"),
             "exported": _("Anonymised copy ready at the firm"),
             "failed": _("Anonymised copy failed at the firm"),
             "refused": _("Firm refused the anonymised copy")}[new_state],
            firm, _("Reference %(ref)s", ref=rebuild.request_ref),
        )

    def action_cancel(self):
        self.ensure_one()
        self._require_owner()
        if self.state not in OPEN_STATES:
            raise UserError(t(self.env, _("This rebuild is closed.")))
        self.write({"state": "cancelled"})
        self.env["platform.log"]._record(
            _("Staging rebuild cancelled"), self.source_firm_id, _("Reference %(ref)s", ref=self.request_ref),
        )

    def action_open_confirm_rebuilt(self):
        self.ensure_one()
        self._require_owner()
        if self.state != "exported":
            raise UserError(t(self.env, _("There is no anonymised copy ready yet.")))
        return self.env["platform.pipeline.confirm"]._open(self, "rebuilt", self.request_ref)

    def _confirmed_rebuilt(self, reason):
        self.ensure_one()
        self._require_owner()
        self.write({"state": "rebuilt", "rebuilt_at": fields.Datetime.now()})
        self.env["platform.log"]._record(
            _("Staging rebuilt from the anonymised copy"), self.source_firm_id,
            _("Reference %(ref)s, digest %(digest)s, note: %(reason)s",
              ref=self.request_ref, digest=self.export_sha256, reason=reason),
        )
