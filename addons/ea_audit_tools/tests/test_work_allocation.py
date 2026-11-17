"""The Work allocation page (owner's mock-up of 2026-11-18): its tile in place of the client's
overrides, what it shows, who may change it, "Suggest by role" saving nothing, and its Excel."""
import io

from openpyxl import load_workbook

from odoo.tests import tagged

from .common import ToolsCase


@tagged("post_install", "-at_install")
class TestWorkAllocationPage(ToolsCase):
    def page(self, actor=None):
        return (actor or self.as_manager).ea_work_allocation_page()

    def row(self, page, code):
        return next(row for row in page["rows"] if row["code"] == code)

    def test_the_tile_opens_the_page(self):
        tile = self.env.ref("ea_audit_tools.tile_work_allocation").with_user(self.staff)
        self.assertTrue(tile.available)
        self.assertEqual(tile.section, "hub")
        action = tile.with_context(ea_engagement_id=self.engagement.id).action_open_tool()
        self.assertEqual(action["tag"], "ea_audit_tools.work_allocation_page")
        self.assertCode("not-on-this-engagement", self.as_outsider.action_tool_work_allocation)

    def test_the_page_shows_the_rule_the_team_and_partner_approval(self):
        page = self.page()
        self.assertFalse(page["readonly"])
        p11 = self.row(page, "P1.1")
        self.assertTrue(p11["partnerRequired"])
        self.assertEqual(p11["rule"], "Prepared by a manager or above; partner approves")
        self.assertEqual(page["partner"]["id"], self.partner.id)
        self.assertFalse(self.row(page, "S1.1")["partnerRequired"])
        self.assertNotIn("C4.2", [row["code"] for row in page["rows"]])
        members = {member["id"] for member in page["members"]}
        self.assertIn(self.staff.id, members)
        self.assertNotIn(self.eqr.id, members)
        self.assertLessEqual({"planning", "strategy", "conclusion"}, {row["phase"] for row in page["rows"]})

    def test_an_empty_field_still_shows_the_partner(self):
        """A file opened before the field existed: no row was rewritten by the upgrade, and the page
        names the engagement partner from the policy until the allocation is saved."""
        p11 = self.item(self.engagement, "P1.1")
        p11.sudo().write({"partner_approver_id": False})
        page = self.page()
        self.assertTrue(self.row(page, "P1.1")["partnerRequired"])
        self.assertEqual(page["partner"]["id"], self.partner.id)
        self.as_manager.ea_work_allocation_save([])
        self.assertEqual(p11.partner_approver_id, self.partner)

    def test_others_read_only(self):
        self.assertTrue(self.page(self.as_staff)["readonly"])
        self.assertTrue(self.page(self.as_eqr)["readonly"])
        self.assertFalse(self.page(self.as_partner)["readonly"])
        self.assertCode("team-manager-only", self.as_staff.ea_work_allocation_suggest, [])

    def test_suggest_fills_empty_boxes_and_saves_nothing(self):
        s11 = self.item(self.engagement, "S1.1")
        current = [{"id": s11.id, "preparer": self.senior.id, "reviewer": False}]
        proposal = self.as_manager.ea_work_allocation_suggest(current)
        self.assertNotIn("preparer", proposal[str(s11.id)])
        self.assertTrue(proposal[str(s11.id)]["reviewer"])
        self.assertNotEqual(proposal[str(s11.id)]["reviewer"], self.senior.id)
        self.assertFalse(self.env["ea.audit.file.item"].sudo().search([
            ("engagement_id", "=", self.engagement.id), "|", ("preparer_id", "!=", False), ("approver_id", "!=", False),
        ]))

    def test_saving_from_the_page(self):
        s11 = self.item(self.engagement, "S1.1")
        result = self.as_manager.ea_work_allocation_save([{"id": s11.id, "preparer_id": self.senior.id, "approver_id": self.manager.id}])
        self.assertEqual(self.row(result["page"], "S1.1")["preparer"], self.senior.id)
        self.assertEqual(result["warnings"], 0)
        name, content = self.as_manager.ea_export_xlsx("work_allocation")
        self.assertTrue(name.endswith(".xlsx"))
        sheet = load_workbook(io.BytesIO(content)).active
        values = [[cell.value for cell in line] for line in sheet.iter_rows()]
        self.assertTrue(any(line[0] == "S1.1" and self.senior.name in line for line in values))
