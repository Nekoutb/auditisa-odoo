from odoo import api, fields, models

from ..services.lead_classes import INDEX_SECTION, account_class_label, account_type_label


class ApComment(models.Model):
    """Commentary per account or per total. Outlives a rebuild of the derived rows."""

    _name = "ea.audit.ap.comment"
    _inherit = ["ea.audit.tool.record"]
    _description = "Lead schedule commentary"

    index_code = fields.Char(required=True, index=True)
    account = fields.Char(required=True, help="An account number, or 'total' for the schedule's row.")
    body = fields.Text(required=True)

    _uniq = models.Constraint("UNIQUE(engagement_id, index_code, account)", "One commentary per account of a schedule.")


class LeadCommentMixin(models.AbstractModel):
    _name = "ea.audit.lead.comment.mixin"
    _inherit = ["ea.audit.tool.record"]
    _description = "Commented lead row"

    commentary = fields.Text(compute="_compute_commentary", inverse="_inverse_commentary")

    def _ea_comment_key(self):
        raise NotImplementedError

    def _compute_commentary(self):
        Comment = self.env["ea.audit.ap.comment"].sudo()
        for row in self:
            index_code, account = row._ea_comment_key()
            found = Comment.search([
                ("engagement_id", "=", row.sudo().engagement_id.id),
                ("index_code", "=", index_code), ("account", "=", account),
            ], limit=1)
            row.commentary = found.body or False

    def _inverse_commentary(self):
        """The value arrives through _ea_user_write, never through here."""

    def _ea_user_write(self, vals):
        self._ea_only(vals, {"commentary"})
        self._ea_guard()
        Comment = self.env["ea.audit.ap.comment"].sudo()
        body = (vals.get("commentary") or "").strip()
        for row in self.sudo():
            index_code, account = row._ea_comment_key()
            domain = [("engagement_id", "=", row.engagement_id.id), ("index_code", "=", index_code), ("account", "=", account)]
            found = Comment.search(domain, limit=1)
            if not body:
                found.unlink()
            elif found:
                found.body = body
            else:
                Comment.create({"engagement_id": row.engagement_id.id, "index_code": index_code, "account": account, "body": body})
        self.invalidate_recordset(["commentary"])
        return True


class LeadSchedule(models.Model):
    _name = "ea.audit.lead.schedule"
    _inherit = ["ea.audit.lead.comment.mixin"]
    _description = "Lead schedule"
    _order = "id"
    _rec_name = "index_code"

    index_code = fields.Selection(selection="_lead_index_selection", string="Lead index", required=True)
    paper_code = fields.Char(string="Paper", compute="_compute_labels")
    closing = fields.Float(string="Current year", digits=(18, 0))
    prior = fields.Float(string="Prior year", digits=(18, 0))
    movement = fields.Float(digits=(18, 0))
    variance_pct = fields.Float(string="Variance %", digits=(16, 1))
    has_variance_pct = fields.Boolean()
    prior_source = fields.Selection([("prior_year_tb", "Prior-year TB"), ("opening", "Opening balances")], string="Comparative")
    account_type = fields.Char()
    account_class = fields.Char()
    account_type_label = fields.Char(string="Account type", compute="_compute_labels")
    account_class_label = fields.Char(string="Account class", compute="_compute_labels")
    alerts = fields.Text()
    line_ids = fields.One2many("ea.audit.lead.line", "schedule_id", string="Accounts")

    def _ea_comment_key(self):
        return self.index_code, "total"

    @api.depends("account_type", "account_class", "index_code")
    def _compute_labels(self):
        locale = "fr" if (self.env.lang or "").startswith("fr") else "en"
        for row in self:
            row.paper_code = INDEX_SECTION.get(row.index_code) or ""
            row.account_type_label = account_type_label(row.account_type, locale) if row.account_type else ""
            row.account_class_label = account_class_label(row.account_class, locale) if row.account_class else ""


class LeadLine(models.Model):
    _name = "ea.audit.lead.line"
    _inherit = ["ea.audit.lead.comment.mixin"]
    _description = "Lead schedule account"
    _order = "index_code, account_code"
    _rec_name = "account_code"

    schedule_id = fields.Many2one("ea.audit.lead.schedule", required=True, ondelete="cascade", index=True)
    index_code = fields.Selection(selection="_lead_index_selection", string="Lead index", required=True)
    sub_index = fields.Char(string="Sub-index")
    account_code = fields.Char(string="Account", required=True)
    account_name = fields.Char(string="Description")
    closing = fields.Float(string="Current year", digits=(18, 0))
    prior = fields.Float(string="Prior year", digits=(18, 0))
    movement = fields.Float(digits=(18, 0))
    variance_pct = fields.Float(string="Variance %", digits=(16, 1))
    has_variance_pct = fields.Boolean()

    def _ea_comment_key(self):
        return self.index_code, self.account_code


class EngagementLead(models.Model):
    _inherit = "ea.audit.engagement"

    lead_schedule_ids = fields.One2many("ea.audit.lead.schedule", "engagement_id", string="Lead schedules")
    lead_prior_label = fields.Char(string="Comparative", compute="_compute_lead_prior_label", compute_sudo=True)

    def _compute_lead_prior_label(self):
        for engagement in self:
            source = engagement.lead_schedule_ids[:1].prior_source
            if not source:
                engagement.lead_prior_label = ""
            elif source == "prior_year_tb":
                engagement.lead_prior_label = self.env._("Prior year: the valid prior-year trial balance")
            else:
                engagement.lead_prior_label = self.env._("Prior year: the current trial balance's opening balances")

    def action_tool_lead(self):
        return self._ea_board("ea_audit_tools.view_engagement_lead_board", self.env._("Lead schedules"))

    def action_tool_lead_lines(self):
        return self._ea_list(
            "ea.audit.lead.line", self.env._("Lead schedules by account"),
            [("ea_audit_tools.view_lead_line_list", "list")],
            {"context": {
                "default_engagement_id": self.id, "ea_engagement_id": self.id,
                "search_default_group_index": 1,
            }},
        )

    def action_export_lead(self):
        return self._ea_export_action("lead")

