from odoo.tests import tagged

from odoo.addons.ea_audit_core.services.file_scope import RETIRED_CODES

from .common import PaperCase


@tagged("post_install", "-at_install")
class TestMergedPapers(PaperCase):
    """P7.1 into P1.4 Part D, S6.2 into S6.1 Part E (owner's decision of 2026-11-16)."""

    def put_back(self, engagement, code):
        """A task an older file still carries: created as the file index did before the merge."""
        template = self.env["ea.audit.task.template"].sudo().search([("code", "=", code)], limit=1)
        return self.env["ea.audit.file.item"].sudo().create({
            "engagement_id": engagement.id, "template_id": template.id, "conditional": False,
        })

    def payload(self, code, user=None):
        return self.paper(code).with_user(user or self.manager).get_payload()

    def test_a_new_file_has_neither_task(self):
        codes = set(self.engagement.sudo().file_item_ids.mapped("code"))
        self.assertFalse(codes & RETIRED_CODES)
        self.assertIn("P1.4", codes)
        self.assertIn("S6.1", codes)

    def test_p14_shows_the_governance_block(self):
        payload = self.payload("P1.4")
        part_d = payload["definition"]["sections"][-1]
        self.assertEqual(part_d["collapse"]["key"], "tcwg_is_mgmt")
        keys = [f["key"] for f in part_d["fields"]]
        self.assertEqual(keys[:3], ["tcwg_is_mgmt", "tcwg_who", "tcwg_planned"])
        self.assertIn("tcwg_response", payload["missing"])

    def test_management_as_governance_folds_the_block_to_one_line(self):
        self.save(self.manager, "P1.4", {"tcwg_is_mgmt": "yes"})
        payload = self.payload("P1.4")
        self.assertFalse({"tcwg_who", "tcwg_planned", "tcwg_independence", "tcwg_form", "tcwg_when", "tcwg_response"}
                         & set(payload["missing"]))
        self.save(self.manager, "P1.4", {"tcwg_is_mgmt": "no"})
        self.assertIn("tcwg_who", self.payload("P1.4")["missing"])

    def test_s61_shows_the_direction_block(self):
        payload = self.payload("S6.1")
        part_e = payload["definition"]["sections"][-1]
        self.assertEqual(part_e["collapse"]["key"], "dir_sole")
        self.assertEqual(payload["auto_values"]["dir_sole"], "no")
        self.assertIn("dir_review_areas", payload["missing"])
        self.assertNotIn("dir_briefing", payload["missing"])

    def test_briefing_attendance_is_read_from_p52(self):
        self.save(self.manager, "P5.2", {"q_partner": "yes"})
        self.assertIn("P5.2", self.payload("S6.1")["auto_values"]["dir_briefing"])

    def test_a_sole_practitioner_sees_not_applicable(self):
        alone = self.make_engagement(2024)
        self.set_phase(alone, "execution")
        members = alone.sudo().team_member_ids.filtered(lambda m: m.team_role != "eqr_reviewer")
        self.assertEqual(len(members.user_id), 1)
        paper = self.paper("S6.1", alone).with_user(self.partner)
        payload = paper.get_payload()
        self.assertEqual(payload["auto_values"]["dir_sole"], "yes")
        self.assertFalse({"dir_review_areas", "dir_supervision", "dir_consult"} & set(payload["missing"]))

    def test_existing_tasks_with_work_stay_and_empty_ones_leave(self):
        worked = self.put_back(self.engagement, "P7.1")
        empty = self.put_back(self.engagement, "S6.2")
        self.save(self.manager, "P7.1", {"addressees": "Board of directors"})
        retired = self.env["ea.audit.engagement"]._ea_retire_merged_tasks()
        self.assertGreaterEqual(retired, 1)
        self.assertFalse(worked.conditional)
        self.assertTrue(empty.conditional)
        self.assertTrue(empty.conditional_trigger)
        self.assertEqual(self.env["ea.audit.engagement"]._ea_retire_merged_tasks(), 0)

    def test_an_archived_file_is_left_untouched(self):
        old = self.make_engagement(2022)
        item = self.put_back(old, "P7.1")
        old.sudo().archived_at = "2026-01-01 00:00:00"
        self.env.flush_all()
        self.env["ea.audit.engagement"]._ea_retire_merged_tasks()
        item.invalidate_recordset(["conditional"])
        self.assertFalse(item.conditional)
