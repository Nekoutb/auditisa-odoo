from odoo import fields, models

SECTION_SELECTION = [
    ("A", "Financial statements"),
    ("B", "Completion"),
    ("C", "Communication"),
    ("D", "Acceptance & planning"),
    ("E", "Execution"),
    ("F", "OHADA statutory"),
]
TIER_SELECTION = [("core", "Core"), ("standard", "Standard"), ("extended", "Extended")]
TASK_PHASE_SELECTION = [
    ("acceptance", "Acceptance"),
    ("planning", "Planning"),
    ("execution", "Execution"),
    ("conclusion", "Conclusion"),
]


class TaskTemplate(models.Model):
    """The default audit file index (lib/file-index.ts), loaded as data. The
    numbering gaps are intentional: do not normalize them."""

    _name = "ea.audit.task.template"
    _description = "Audit file index entry"
    _order = "sequence, id"
    _rec_name = "code"

    code = fields.Char(required=True, index=True)
    section = fields.Selection(SECTION_SELECTION, required=True)
    title = fields.Char(required=True, translate=True)
    short_title = fields.Char(translate=True)
    tier = fields.Selection(TIER_SELECTION, required=True, default="standard")
    conditional = fields.Boolean(help="Instantiated, but only activated when a trigger answers yes.")
    phase = fields.Selection(TASK_PHASE_SELECTION, required=True)
    sequence = fields.Integer(default=10)

    _code_uniq = models.Constraint("UNIQUE(code)", "This task code already exists.")
