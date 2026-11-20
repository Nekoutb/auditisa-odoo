"""Journal types (optional), the step after the columns of a general ledger (owner's mock-up
"gl-journal-types", 20/11/2026): every journal code of the file, its lines, one description and
the type it is used for, suggested from the code. Save or Skip: the checks run straight after
either button. The same screen opens later from the Data bank, on the ledger's form."""
from odoo import Command, api, fields, models

from ..services.eaglr import JOURNAL_TYPES, suggest_type

_RELOAD = {"type": "ir.actions.client", "tag": "soft_reload"}


class JournalTypeWizard(models.TransientModel):
    _name = "ea.audit.journal.type.wizard"
    _description = "Journal types"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    dataset_id = fields.Many2one("ea.audit.dataset", string="General ledger", required=True)
    line_ids = fields.One2many("ea.audit.journal.type.wizard.line", "wizard_id", string="Journal codes")
    # where Save and Skip go: back to the screen that opened it, or to EAGLR afresh
    then_eaglr = fields.Boolean()
    summary = fields.Char(compute="_compute_summary")

    @api.depends("dataset_id", "line_ids")
    def _compute_summary(self):
        for wizard in self:
            dataset = wizard.dataset_id.sudo()
            wizard.summary = self.env._(
                "%(file)s · %(lines)s lines · %(codes)s journal codes",
                file=dataset.source_filename or dataset.name or "", lines=dataset.gl_line_count, codes=len(wizard.line_ids),
            )

    @api.model
    def _ea_open(self, engagement, dataset, then_eaglr=False):
        """The screen on a ledger, each code with its saved type, else the suggested one."""
        engagement._ea_tool_guard()
        dataset = engagement._ea_gl_ready(engagement._ea_gl_dataset(dataset.id))
        saved = dataset.journal_types or {}
        lines = [
            Command.create({
                "code": row["code"], "lines": row["lines"], "example": row["example"] or "",
                "journal_type": saved.get(row["code"]) or suggest_type(row["code"]) or False,
            })
            for row in engagement._ea_gl_journal_codes(dataset)
        ]
        wizard = self.create({
            "engagement_id": engagement.id, "dataset_id": dataset.id, "line_ids": lines, "then_eaglr": then_eaglr,
        })
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": wizard.id, "view_mode": "form",
            "views": [(self.env.ref("ea_audit_tools.view_journal_type_wizard_form").id, "form")],
            "target": "new", "name": self.env._("Journal types (optional)"), "context": {"dialog_size": "large"},
        }

    def _ea_next(self):
        if self.then_eaglr:
            return self.engagement_id.action_tool_eaglr()
        return _RELOAD

    def action_save(self):
        self.ensure_one()
        types = {line.code: line.journal_type for line in self.line_ids if line.journal_type}
        self.engagement_id.gl_set_journal_types(self.dataset_id.id, types)
        return self._ea_next()

    def action_skip(self):
        self.ensure_one()
        return self._ea_next()


class JournalTypeWizardLine(models.TransientModel):
    _name = "ea.audit.journal.type.wizard.line"
    _description = "Journal code"
    _order = "code"

    wizard_id = fields.Many2one("ea.audit.journal.type.wizard", required=True, ondelete="cascade")
    code = fields.Char(string="Journal code in the file", readonly=True)
    lines = fields.Integer(string="Lines", readonly=True)
    example = fields.Char(string="Example description", readonly=True)
    journal_type = fields.Selection([(key, english) for key, english, _french, _class in JOURNAL_TYPES], string="Journal type")
