from markupsafe import Markup

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..services.ap_schedules import index_resolver
from ..services.fs_captions import bilan_totals
from ..services.lead_classes import INDEX_SECTION, LEAD_INDEXES, account_class_label, account_type_label, lead_schedule_alerts
from ..rules import rule_error
from .tool_record import fcfa


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
    # Not stored: whether this reader may type a commentary here. Archived files, read-only
    # roles and the EQR see the cell read-only; the write path refuses them all the same.
    ea_comment_locked = fields.Boolean(string="Commentary read-only", compute="_compute_ea_comment_locked")

    def _ea_comment_key(self):
        raise NotImplementedError

    @api.depends_context("uid")
    def _compute_ea_comment_locked(self):
        verdicts = {}
        for row in self:
            engagement = row.sudo().engagement_id
            if engagement.id not in verdicts:
                try:
                    engagement.with_env(self.env)._ea_tool_guard()
                    verdicts[engagement.id] = False
                except (UserError, AccessError):
                    verdicts[engagement.id] = True
            row.ea_comment_locked = verdicts[engagement.id]

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
    prior_source = fields.Selection([("prior_year_tb", "Prior-year TB"), ("prior_file", "Prior-year file"), ("opening", "Opening balances")], string="Comparative")
    account_type = fields.Char()
    account_class = fields.Char()
    account_type_label = fields.Char(string="Account type", compute="_compute_labels")
    account_class_label = fields.Char(string="Account class", compute="_compute_labels")
    alerts = fields.Text()
    alerts_label = fields.Text(string="Alerts", compute="_compute_alerts_label", compute_sudo=True)
    line_ids = fields.One2many("ea.audit.lead.line", "schedule_id", string="Accounts")

    def _ea_comment_key(self):
        return self.index_code, "total"

    def _ea_user_write(self, vals):
        """The schedule's form saves its accounts' commentaries with it: only an update of a
        line's commentary is accepted from line_ids, and each goes through the line's own rules."""
        vals = dict(vals)
        commands = vals.pop("line_ids", None) or []
        for command in commands:
            if command[0] == Command.UPDATE:
                line = self.env["ea.audit.lead.line"].browse(command[1])
                if line.sudo().schedule_id not in self.sudo():
                    raise rule_error(self.env, "forbidden")
                line.write(command[2])
            elif command[0] != Command.LINK:
                raise rule_error(self.env, "invalid-field")
        return super()._ea_user_write(vals) if vals else True

    @api.depends("alerts", "line_ids.closing")
    @api.depends_context("lang")
    def _compute_alerts_label(self):
        locale = "fr" if (self.env.lang or "").startswith("fr") else "en"
        for row in self:
            accounts = [{"account": line.account_code, "closing": line.closing} for line in row.line_ids]
            row.alerts_label = chr(10).join(alert[locale] for alert in lead_schedule_alerts(accounts)) or False

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
    lead_checks_html = fields.Html(string="Checks", compute="_compute_lead_checks", sanitize=False, compute_sudo=True)
    lead_hidden_note = fields.Char(string="Indexes not shown", compute="_compute_lead_checks", compute_sudo=True)

    @api.depends_context("lang")
    def _compute_lead_checks(self):
        """F018: does the balance balance, do assets equal liabilities, is every account placed,
        and which indexes have nothing to show."""
        for engagement in self:
            version = engagement._ea_current_tb_version()
            if not version:
                engagement.lead_checks_html = Markup("<span class='o_ea_chip o_ea_chip_warn me-2'>{}</span>").format(self.env._("No trial balance in force"))
                engagement.lead_hidden_note = False
                continue
            checks = (version.validation_summary or {}).get("checks") or {}
            balanced = checks.get("balanced") or {}
            bilan = bilan_totals(engagement._ea_tb_balances())
            gap = bilan["totalAssets"] - bilan["totalLiabilitiesAndEquity"]
            index_of = index_resolver(engagement._ea_lead_overrides())
            unplaced = [line.account_code for line in version.line_ids if not index_of(line.account_code)]
            shown = set(engagement.lead_schedule_ids.mapped("index_code"))
            hidden = [d["code"] for d in LEAD_INDEXES if d["code"] not in shown]
            items = [
                (balanced.get("ok", False), self.env._("Trial balance balances: debits %(amount)s", amount=fcfa(balanced.get("totalDebit", 0)))
                    if balanced.get("ok") else self.env._("Trial balance does not balance: debits %(debit)s, credits %(credit)s", debit=fcfa(balanced.get("totalDebit", 0)), credit=fcfa(balanced.get("totalCredit", 0)))),
                (abs(gap) < 1, self.env._("Assets = equity and liabilities: %(amount)s", amount=fcfa(bilan["totalAssets"]))
                    if abs(gap) < 1 else self.env._("Assets differ from equity and liabilities by %(amount)s", amount=fcfa(gap))),
                (not unplaced, self.env._("Every account is on a lead index")
                    if not unplaced else self.env._("%(count)s account(s) on no lead index: %(accounts)s", count=len(unplaced), accounts=", ".join(unplaced[:8]))),
            ]
            engagement.lead_checks_html = Markup("").join(
                Markup("<span class='o_ea_chip {css} me-2'>{label}</span>").format(css="o_ea_chip_good" if ok else "o_ea_chip_bad", label=label)
                for ok, label in items
            )
            engagement.lead_hidden_note = self.env._(
                "%(count)s indexes with no balance on this trial balance are not shown: %(codes)s", count=len(hidden), codes=", ".join(hidden),
            ) if hidden else False

    def _compute_lead_prior_label(self):
        for engagement in self:
            engagement.lead_prior_label = engagement._ea_comparative_label() if engagement.lead_schedule_ids else ""

    def action_tool_lead(self):
        self.ensure_one()
        self._ea_require_access()
        self.sudo()._ea_refresh_lead_schedules()
        return self._ea_board("ea_audit_tools.view_engagement_lead_board", self.env._("Lead schedules"))

    def action_tool_lead_lines(self):
        self.ensure_one()
        self._ea_require_access()
        self.sudo()._ea_refresh_lead_schedules()
        return self._ea_list(
            "ea.audit.lead.line", self.env._("Lead schedules"),
            [("ea_audit_tools.view_lead_line_list", "list")],
            {"context": {
                "default_engagement_id": self.id, "ea_engagement_id": self.id,
                "search_default_group_index": 1,
            }},
        )

    def action_export_lead(self):
        return self._ea_export_action("lead")

