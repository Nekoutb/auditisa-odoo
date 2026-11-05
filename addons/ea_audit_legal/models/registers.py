from odoo import api, fields, models

from odoo.addons.ea_audit_reports.services.articles import mark_articles
from odoo.addons.ea_audit_tools.models.tool_record import french_date
from odoo.addons.ea_audit_tools.services.alerte import flow_of

from ..services.texts import CAPACITY_SELECTION, STAGE_SELECTION


class LegalDeadline(models.Model):
    """statutory_deadline, the C5.2 calendar: upserted by key, so regeneration follows date changes
    without losing done-marks."""

    _name = "ea.audit.legal.deadline"
    _inherit = ["ea.audit.tool.record"]
    _description = "Statutory deadline"
    _order = "due_date, id"
    _rec_name = "key"

    key = fields.Char(required=True, readonly=True, index=True)
    due_date = fields.Date(required=True, readonly=True)
    basis = fields.Char(readonly=True)
    done = fields.Boolean(readonly=True)
    done_at = fields.Datetime(readonly=True)
    days_left = fields.Integer(compute="_compute_days_left")

    _engagement_key_uniq = models.Constraint("UNIQUE(engagement_id, key)", "A file has one row per deadline.")

    @api.depends("due_date")
    def _compute_days_left(self):
        today = fields.Date.context_today(self)
        for deadline in self:
            deadline.days_left = (deadline.due_date - today).days if deadline.due_date else 0

    def action_mark_done(self):
        for deadline in self:
            deadline.sudo().engagement_id.with_env(self.env).mark_deadline_done(deadline.key)
        return True


class RegulatedAgreement(models.Model):
    """convention, the C5.3 register."""

    _name = "ea.audit.regulated.agreement"
    _inherit = ["ea.audit.tool.record"]
    _description = "Regulated agreement"
    _order = "id"
    _rec_name = "nature"

    parties = fields.Char(required=True, readonly=True)
    interested = fields.Char(string="Interested person", required=True, readonly=True)
    capacity = fields.Selection(CAPACITY_SELECTION, required=True, readonly=True)
    nature = fields.Char(required=True, readonly=True)
    terms = fields.Text(readonly=True)
    amounts_period = fields.Float(string="Amounts of the period (FCFA)", digits=(18, 0), readonly=True)
    continuing = fields.Boolean(readonly=True)
    board_auth_ref = fields.Char(string="Prior authorisation", readonly=True)
    notified_at = fields.Date(string="Notified on", readonly=True)
    created_by_id = fields.Many2one("res.users", string="Recorded by", ondelete="restrict", readonly=True)
    unauthorized = fields.Boolean(
        compute="_compute_unauthorized", compute_sudo=True,
        help="SA only: no prior authorisation, by the board or on an SA_AG by the general meeting: curable nullity.",
    )

    @api.depends("board_auth_ref", "engagement_id")
    def _compute_unauthorized(self):
        for agreement in self:
            form = agreement.engagement_id.client_id.legal_form
            agreement.unauthorized = form in ("SA", "SA_AG") and not agreement.board_auth_ref


class Alerte(models.Model):
    """The alert procedure of one file: its stage and the deadline it set."""

    _name = "ea.audit.alerte"
    _inherit = ["ea.audit.tool.record"]
    _description = "Alert procedure"
    _order = "id desc"
    _rec_name = "stage"

    variant = fields.Selection([("sa", "SA or SAS"), ("non_sa", "Other forms")], required=True, readonly=True)
    stage = fields.Selection(STAGE_SELECTION, required=True, readonly=True)
    stage_deadline = fields.Date(string="Deadline of the stage", readonly=True)
    discontinued_at = fields.Date(readonly=True)
    created_by_id = fields.Many2one("res.users", string="Started by", ondelete="restrict", readonly=True)
    event_ids = fields.One2many("ea.audit.alerte.event", "alerte_id", string="Events")
    stage_basis = fields.Char(string="Basis", compute="_compute_stage_basis", compute_sudo=True)

    @api.depends("stage", "variant")
    @api.depends_context("lang")
    def _compute_stage_basis(self):
        for alerte in self:
            entry = next((e for e in flow_of(alerte.variant) if e["stage"] == alerte.stage), None) if alerte.variant else None
            french = (self.env.lang or "").startswith("fr")
            basis = (entry.get("basisFr", entry["basis"]) if french else entry["basis"]) if entry else False
            alerte.stage_basis = mark_articles(basis, self.env.company.sudo().ea_articles_validated, french) if basis else False


class AlerteEvent(models.Model):
    _name = "ea.audit.alerte.event"
    _inherit = ["ea.audit.tool.record"]
    _description = "Alert procedure event"
    _order = "id"
    _rec_name = "stage"

    alerte_id = fields.Many2one("ea.audit.alerte", required=True, index=True, ondelete="cascade", readonly=True)
    stage = fields.Char(required=True, readonly=True)
    note = fields.Text(readonly=True)
    document_id = fields.Many2one("ea.audit.document", ondelete="set null", readonly=True)
    event_date = fields.Date(readonly=True)
    created_by_id = fields.Many2one("res.users", string="Recorded by", ondelete="restrict", readonly=True)


class CriminalDisclosure(models.Model):
    """fait_delictueux: partner-only, by the ACL as well as by the methods (spec 12.5.6)."""

    _name = "ea.audit.criminal.disclosure"
    _inherit = ["ea.audit.tool.record"]
    _description = "Disclosure of criminal facts"
    _order = "revealed_at, id"
    _rec_name = "revealed_at"

    description = fields.Text(required=True, readonly=True)
    document_id = fields.Many2one("ea.audit.document", ondelete="set null", readonly=True)
    revealed_at = fields.Date(default=fields.Date.context_today, readonly=True)
    created_by_id = fields.Many2one("res.users", string="Revealed by", ondelete="restrict", readonly=True)

    @api.depends("revealed_at")
    def _compute_display_name(self):
        for row in self:
            row.display_name = french_date(row.revealed_at)
