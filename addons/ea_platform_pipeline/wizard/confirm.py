from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ea_platform_admin.services.messages import _
from ..services import pipeline
from ..models.i18n import t

ACTIONS = [
    ("promote", "Promote"),
    ("rollback", "Roll back"),
    ("main", "Confirm main moved"),
    ("rebuild", "Rebuild staging"),
    ("rebuilt", "Record staging rebuilt"),
]


class PlatformPipelineConfirm(models.TransientModel):
    """The typed confirmation and the reason, in front of every action of the pipeline."""

    _name = "platform.pipeline.confirm"
    _description = "Confirm a pipeline action"
    _inherit = ["platform.pipeline.guard"]

    action = fields.Selection(ACTIONS, "Action", required=True, readonly=True)
    promotion_id = fields.Many2one("platform.pipeline.promotion", "Promotion", readonly=True)
    rebuild_id = fields.Many2one("platform.pipeline.rebuild", "Rebuild", readonly=True)
    source_firm_id = fields.Many2one(
        "platform.firm", "Source firm", domain=[("state", "=", "active"), ("pipeline_role", "=", "firm")],
        help="Its server makes the anonymised copy. Nothing identifiable leaves it, and it must have allowed exports.",
    )
    target = fields.Char("Target", readonly=True)
    expected = fields.Char("Type this", compute="_compute_expected")
    typed = fields.Char("Confirmation")
    reason = fields.Text("Reason")
    warning = fields.Text("What this does", compute="_compute_expected")
    summary_html = fields.Html("What will change", compute="_compute_summary", sanitize=False)

    @api.depends("action", "target", "source_firm_id")
    @api.depends_context("lang")
    def _compute_expected(self):
        for wizard in self:
            target = wizard.source_firm_id.slug if wizard.action == "rebuild" else wizard.target
            wizard.expected = pipeline.phrase(wizard.action, target or "...", self.env.lang) if wizard.action else False
            wizard.warning = t(self.env, {
                "promote": _("Asks the test firm to take this release now, then the other firms in batches. Each firm is cut off during its update."),
                "rollback": _("Asks the firms to go back to this earlier release, in the same order. Code only: an update that changed the database cannot be undone this way."),
                "main": _("Records that you have moved main yourself. It moves nothing."),
                "rebuild": _("Asks this firm's server to make an anonymised copy, which stays there. Nothing changes on staging until you carry it there and run the script."),
                "rebuilt": _("Records that you have rebuilt staging. It changes nothing."),
            }[wizard.action]) if wizard.action else False

    @api.depends("action", "promotion_id")
    @api.depends_context("lang")
    def _compute_summary(self):
        for wizard in self:
            promotion = wizard.promotion_id
            if wizard.action in ("promote", "rollback") and promotion:
                wizard.summary_html = promotion._change_summary()
            else:
                wizard.summary_html = False

    @api.model
    def _open(self, record, action, target):
        values = {"action": action, "target": target}
        values["rebuild_id" if record._name == "platform.pipeline.rebuild" else "promotion_id"] = record.id
        wizard = self.create(values)
        return self._as_action(wizard)

    @api.model
    def _open_new_rebuild(self):
        self._require_owner()
        return self._as_action(self.create({"action": "rebuild"}))

    @api.model
    def _as_action(self, wizard):
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": wizard.id,
            "view_mode": "form", "target": "new", "name": dict(self._fields["action"]._description_selection(self.env)).get(wizard.action),
        }

    def action_confirm(self):
        self.ensure_one()
        self._require_owner()
        errors = pipeline.confirmation_errors(self.expected, self.typed, self.reason)
        if self.action == "rebuild" and not self.source_firm_id:
            errors.append(_("Choose the source firm."))
        if errors:
            raise UserError("\n".join(t(self.env, error) for error in errors))
        reason = self.reason.strip()
        if self.action in ("promote", "rollback"):
            self.promotion_id._confirmed(self.action, reason)
        elif self.action == "main":
            self.promotion_id._confirmed_main(reason)
        elif self.action == "rebuild":
            rebuild = self.env["platform.pipeline.rebuild"]._open_request(self.source_firm_id, reason)
            return {
                "type": "ir.actions.act_window", "res_model": "platform.pipeline.rebuild", "res_id": rebuild.id,
                "view_mode": "form", "target": "current",
            }
        elif self.action == "rebuilt":
            self.rebuild_id._confirmed_rebuilt(reason)
        return {"type": "ir.actions.act_window_close"}
