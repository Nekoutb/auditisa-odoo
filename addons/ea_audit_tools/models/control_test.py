"""recordControlTest (lib/execution.ts): one operating test of a control selected for testing. Until
E1.2 concludes, the raw outcome is what the CRA's coverage reads; an open row of the archive
checklist is a selected control with no design evaluation or no test."""
from odoo import fields, models

from ..rules import rule_error

RESULT_SELECTION = [("effective", "Effective"), ("deviation", "Deviation")]
DEVIATION_SELECTION = [
    ("extend", "Extend the test"),
    ("abandon", "Abandon reliance: substantive extension"),
    ("deficiency", "Report a control deficiency (C5.11)"),
]


class ControlTest(models.Model):
    _name = "ea.audit.control.test"
    _inherit = ["ea.audit.tool.record"]
    _description = "Operating test of a control"
    _order = "create_date, id"
    _rec_name = "description"

    control_id = fields.Many2one("ea.audit.scot.control", required=True, ondelete="cascade", index=True)
    file_item_id = fields.Many2one("ea.audit.file.item", string="Paper", ondelete="set null")
    description = fields.Char(required=True)
    result = fields.Selection(RESULT_SELECTION, required=True)
    deviation_decision = fields.Selection(DEVIATION_SELECTION)
    note = fields.Text()
    tested_by_id = fields.Many2one("res.users", string="Tested by", readonly=True)


class ScotControlTests(models.Model):
    _inherit = "ea.audit.scot.control"

    test_ids = fields.One2many("ea.audit.control.test", "control_id", string="Operating tests")

    def _ea_test_outcome(self):
        """The raw outcome: None until a test is recorded (scots.ts, `operating`)."""
        self.ensure_one()
        results = self.sudo().test_ids.mapped("result")
        if not results:
            return None
        return "not_effective" if "deviation" in results else "effective"

    def _ea_concluded(self):
        """The E1.2 conclusion is what the board reads; the test outcome stands in until then (cra.ts)."""
        self.ensure_one()
        return self.sudo().operating_eval or self._ea_test_outcome()

    def _ea_is_open(self):
        """Selected and not concluded on: no design evaluation, or nothing tested. An imported grid
        with tested rows is a record of the test, as the E1.2 grid is here (see QUESTIONS.md)."""
        self.ensure_one()
        control = self.sudo()
        if not control.selected_for_testing:
            return False
        return not control.design_eval or not (control.test_ids or control.rows_tested)

    def record_test(self, description, result, deviation_decision=None, note=None):
        """recordControlTest. A deviation needs its decision, and the decision has its consequence:
        an extension step on the paper, reliance abandoned, or a finding for C5.11."""
        self.ensure_one()
        self._ea_guard()
        description = (description or "").strip()
        if not description:
            raise rule_error(self.env, "description-required")
        if result not in dict(RESULT_SELECTION):
            raise rule_error(self.env, "invalid-value")
        if result == "deviation" and deviation_decision not in dict(DEVIATION_SELECTION):
            raise rule_error(self.env, "deviation-decision-required")
        control = self.sudo()
        engagement = control.engagement_id
        item = self.env["ea.audit.file.item"].sudo().search(
            [("engagement_id", "=", engagement.id), ("code", "=", "E1.2")], limit=1,
        )
        test = self.env["ea.audit.control.test"].sudo().create({
            "engagement_id": engagement.id, "control_id": control.id, "file_item_id": item.id or False,
            "description": description, "result": result, "note": note or False,
            "deviation_decision": deviation_decision if result == "deviation" else False,
            "tested_by_id": self.env.user.id,
        })
        if result == "deviation":
            self._ea_deviation_consequence(deviation_decision, description, note, item)
        engagement._ea_invalidate_signoffs("E1.2")
        engagement.with_env(self.env)._ea_log("control_tested", "Control %s tested: %s" % (control.name, result))
        return test.with_env(self.env)

    def _ea_deviation_consequence(self, decision, description, note, item):
        control = self.sudo()
        engagement = control.engagement_id.with_env(self.env)
        if decision == "deficiency":
            engagement.route_finding(
                "c1", "Control deficiency: %s" % description, detail=note, severity="deficiency", file_item=item or None,
            )
            return
        if not item:
            return
        wording = "Extended testing following control deviation: %s" if decision == "extend" else "Reliance abandoned — substantive extension required: %s"
        engagement.add_custom_step("E1.2", wording % description, ("C", "E", "A"))
        if decision == "abandon":
            links = self.env["ea.audit.risk.section"].sudo().search([("file_item_id", "=", item.id)])
            links.risk_id.write({"controls_reliance": False})
            control._ea_stamp_not_rely()

    def action_open_test(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": self.env._("Record a test"), "res_model": "ea.audit.control.test.wizard",
            "view_mode": "form", "target": "new", "context": {"default_control_id": self.id},
        }


class ControlTestWizard(models.TransientModel):
    _name = "ea.audit.control.test.wizard"
    _description = "Record a test of a control"

    control_id = fields.Many2one("ea.audit.scot.control", required=True)
    description = fields.Char(required=True)
    result = fields.Selection(RESULT_SELECTION, default="effective", required=True)
    deviation_decision = fields.Selection(DEVIATION_SELECTION)
    note = fields.Text()

    def action_record(self):
        self.ensure_one()
        self.control_id.record_test(self.description, self.result, self.deviation_decision, self.note)
        return {"type": "ir.actions.client", "tag": "soft_reload"}
