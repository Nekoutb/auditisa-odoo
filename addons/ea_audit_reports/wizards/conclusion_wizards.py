import base64

from odoo import api, fields, models

from ..services.opinion import decide_opinion


class IssueReportWizard(models.TransientModel):
    """issue-report: four drivers, the opinion follows from them; never a free choice."""

    _name = "ea.audit.issue.report.wizard"
    _description = "Issue the audit report"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True, ondelete="cascade")
    listed = fields.Boolean(compute="_compute_opinion", compute_sudo=True)
    material_misstatement = fields.Boolean(string="Uncorrected misstatements exceed materiality")
    pervasive = fields.Boolean(string="The matter is pervasive to the financial statements")
    scope_limitation = fields.Boolean(string="Sufficient appropriate evidence could not be obtained")
    going_concern_uncertainty = fields.Boolean(string="Material uncertainty on going concern, adequately disclosed")
    opinion = fields.Selection(
        [("unmodified", "Unmodified"), ("qualified", "Qualified"), ("adverse", "Adverse"), ("disclaimer", "Disclaimer")],
        compute="_compute_opinion",
    )
    basis = fields.Text(string="Basis of the modification")
    kam = fields.Text(string="Key audit matters")
    kam_none = fields.Boolean(string="No key audit matter to report")
    kam_none_reason = fields.Text(string="Why there is none")
    report_date = fields.Date(string="Report date")

    @api.depends("material_misstatement", "pervasive", "scope_limitation", "going_concern_uncertainty", "engagement_id")
    def _compute_opinion(self):
        for wizard in self:
            wizard.opinion = decide_opinion(
                wizard.material_misstatement, wizard.pervasive, wizard.scope_limitation, wizard.going_concern_uncertainty,
            )[0]
            wizard.listed = wizard.engagement_id.sudo().client_id.listed

    def action_confirm(self):
        self.ensure_one()
        document = self.engagement_id.issue_report_from_form(
            material_misstatement=self.material_misstatement, pervasive=self.pervasive,
            scope_limitation=self.scope_limitation, going_concern_uncertainty=self.going_concern_uncertainty,
            report_date=self.report_date, basis=self.basis, kam=self.kam, kam_none=self.kam_none,
            kam_none_reason=self.kam_none_reason,
        )
        return document.action_download()


class CompletionWizard(models.TransientModel):
    """completion-record-forms: disclosure checklist, subsequent events, points forward, partner
    conclusion. The version travels with the form: a colleague's save in between is refused."""

    _name = "ea.audit.completion.wizard"
    _description = "Completion record"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True, ondelete="cascade")
    key = fields.Selection([
        ("disclosure_checklist", "Disclosure checklist"),
        ("subsequent_events", "Subsequent events"),
        ("points_forward", "Points forward"),
        ("partner_conclusion", "Partner conclusion"),
    ], required=True)
    base_version = fields.Char()
    text = fields.Text(string="Notes")
    reviewed_to = fields.Date(string="Reviewed to")
    all_complete = fields.Boolean(string="All 36 notes reviewed and complete")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        engagement = self.env["ea.audit.engagement"].browse(values.get("engagement_id") or self.env.context.get("default_engagement_id"))
        key = values.get("key") or self.env.context.get("default_key")
        if engagement and key:
            values["base_version"] = engagement.completion_record_version(key)
            data = engagement.sudo()._ea_completion_data(key) or {}
            values["text"] = data.get("notes") or data.get("events") or data.get("points") or data.get("conclusion") or False
            values["reviewed_to"] = data.get("reviewedTo") or False
        return values

    def action_save(self):
        self.ensure_one()
        engagement, text = self.engagement_id, self.text or ""
        if self.key == "disclosure_checklist":
            engagement.record_disclosure_checklist(self.all_complete, text)
        elif self.key == "subsequent_events":
            engagement.record_subsequent_events(self.reviewed_to, text)
        elif self.key == "points_forward":
            engagement.record_completion("points_forward", {"points": text}, self.base_version or "")
        else:
            engagement.record_completion("partner_conclusion", {"conclusion": text}, self.base_version or "")
        return {"type": "ir.actions.act_window_close"}


class HoldWizard(models.TransientModel):
    _name = "ea.audit.hold.wizard"
    _description = "Legal hold"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True, ondelete="cascade")
    mode = fields.Selection([("place", "Place"), ("release", "Release")], required=True, default="place")
    reason = fields.Text()

    def action_confirm(self):
        self.ensure_one()
        if self.mode == "place":
            self.engagement_id.place_legal_hold(self.reason)
        else:
            self.engagement_id.release_legal_hold(self.reason)
        return {"type": "ir.actions.act_window_close"}


class TieoutWizard(models.TransientModel):
    """The client's statements (ref;amount) against the recomputation. Differences stay on the screen;
    only a tie-out that passes is recorded."""

    _name = "ea.audit.tieout.wizard"
    _description = "Tie-out against the client's statements"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True, ondelete="cascade")
    client_file = fields.Binary(string="Client's statements (CSV: ref;amount)")
    client_filename = fields.Char()
    result_html = fields.Html(readonly=True, sanitize=False)

    def action_run(self):
        self.ensure_one()
        engagement = self.engagement_id
        engagement._ea_require_access()
        content = base64.b64decode(self.client_file) if self.client_file else None
        result = engagement._ea_fs_tieout(content)
        if result["pass"]:
            engagement.run_fs_tieout(content)
            return {"type": "ir.actions.client", "tag": "soft_reload"}
        self.result_html = engagement._ea_tieout_html(result)
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form",
            "target": "new", "name": self.env._("Tie-out against the client's statements"),
        }
