from odoo import fields, models

from ..models.design import NATURE_SELECTION, TIMING_SELECTION
from ..models.sap import CONCLUSION_SELECTION

_RELOAD = {"type": "ir.actions.client", "tag": "soft_reload"}


def _indexes(self):
    return self.env["ea.audit.tool.record"]._lead_index_selection()


class OspWizard(models.TransientModel):
    _name = "ea.audit.osp.wizard"
    _description = "Add another substantive procedure"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    index_code = fields.Selection(_indexes, string="Lead index", required=True)
    text = fields.Text(string="Procedure", required=True)
    assertion_ids = fields.Many2many("ea.audit.assertion", string="Assertions")
    nature = fields.Selection(NATURE_SELECTION)
    timing = fields.Selection(TIMING_SELECTION)
    extent = fields.Char()

    def action_add(self):
        self.ensure_one()
        self.engagement_id.add_dsp_osp(self.index_code, self.text, self.assertion_ids.mapped("code"), self.nature, self.timing, self.extent)
        return _RELOAD


class ProgramWizard(models.TransientModel):
    _name = "ea.audit.program.wizard"
    _description = "Audit programs"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    mode = fields.Selection([("generate", "Generate from the library"), ("design", "Generate what S5.5 designed"), ("custom", "Add a step")], default="generate", required=True)
    file_item_id = fields.Many2one("ea.audit.file.item", string="Task", required=True, domain="[('engagement_id', '=', engagement_id)]")
    description = fields.Text()
    assertion_ids = fields.Many2many("ea.audit.assertion", string="Assertions")

    def action_apply(self):
        self.ensure_one()
        code = self.file_item_id.code
        if self.mode == "custom":
            self.engagement_id.add_custom_step(code, self.description, self.assertion_ids.mapped("code"))
        elif self.mode == "design":
            self.engagement_id.generate_psp(code)
        else:
            self.engagement_id.generate_program(code)
        return _RELOAD


class SapWizard(models.TransientModel):
    _name = "ea.audit.sap.wizard"
    _description = "A substantive analytical procedure"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    index_code = fields.Selection(_indexes, string="Lead index", required=True)
    assertion = fields.Selection([("C", "C"), ("E", "E"), ("A", "A"), ("V", "V"), ("P", "P")], required=True)
    expectation_model = fields.Text(required=True)
    inputs = fields.Text()
    expected_value = fields.Float(digits=(18, 2), required=True)
    data_reliability = fields.Text()
    use_override = fields.Boolean(string="Override the firm percentage")
    override_pct = fields.Integer(string="Override %")
    override_reason = fields.Text(string="Why")
    actual_value = fields.Float(string="Recorded amount, when there is no trial balance", digits=(18, 2))
    investigation = fields.Text()
    corroboration = fields.Text()
    conclusion = fields.Selection(CONCLUSION_SELECTION)

    def action_save(self):
        self.ensure_one()
        self.engagement_id.save_sap(
            self.index_code, self.assertion, self.expectation_model, self.expected_value, inputs=self.inputs, data_reliability=self.data_reliability,
            override_pct=self.override_pct if self.use_override else None, override_reason=self.override_reason,
            actual_value=self.actual_value or None, investigation=self.investigation, corroboration=self.corroboration, conclusion=self.conclusion,
        )
        return _RELOAD
