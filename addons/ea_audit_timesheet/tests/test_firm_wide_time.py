"""Owner, 2026-11-07: every member of the firm logs time on any engagement of the firm, from any
engagement they can open, and that opens nothing of the engagement itself."""
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import MONDAY, TUESDAY, TimesheetCase


@tagged("post_install", "-at_install")
class TestFirmWideTime(TimesheetCase):
    def test_a_staff_member_not_on_the_engagement_logs_time_on_it(self):
        sheet = self.sheet(self.outsider)
        offered = {p["id"]: p for p in sheet.ea_ts_sheet()["projects"]}
        self.assertIn(self.project.id, offered)
        # only what the choice needs: no team, partner, phase, client record or any figure
        self.assertEqual(set(offered[self.project.id]), {"id", "label", "kind", "engagement_id", "tasks"})
        self.assertEqual(offered[self.project.id]["kind"], "firm")
        self.assertEqual(offered[self.project.id]["label"], self.engagement.sudo().display_name)
        line_id = sheet.ea_ts_charge(str(TUESDAY), self.project.id, 2.5, offered[self.project.id]["tasks"][0]["id"])
        sheet.ea_ts_set_cell(str(MONDAY), self.project.id, False, 1.5)
        data = sheet.ea_ts_sheet(str(TUESDAY))
        self.assertEqual(data["total"], 4)
        self.assertEqual({row["project_id"] for row in data["rows"]}, {self.project.id})
        line = self.Line.sudo().browse(line_id)
        self.assertEqual((line.user_id, line.project_id), (self.outsider, self.project))
        # and corrects or removes their own hours there
        sheet.ea_ts_set_cell(str(MONDAY), self.project.id, False, 0)
        self.assertEqual(sheet.ea_ts_sheet(str(TUESDAY))["total"], 2.5)

    def test_logging_time_opens_nothing_of_the_engagement(self):
        self.sheet(self.outsider).ea_ts_charge(str(TUESDAY), self.project.id, 2)
        engagement = self.engagement.with_user(self.outsider)
        Engagement = self.env["ea.audit.engagement"].with_user(self.outsider)
        self.assertFalse(Engagement.search([("id", "=", self.engagement.id)]))
        with mute_logger("odoo.addons.base.models.ir_rule", "odoo.models"):
            with self.assertRaises(AccessError):
                engagement.read(["name"])
            # its file items
            items = self.engagement.sudo().file_item_ids
            self.assertTrue(items)
            self.assertFalse(self.env["ea.audit.file.item"].with_user(self.outsider).search([("engagement_id", "=", self.engagement.id)]))
            with self.assertRaises(AccessError):
                items[:1].with_user(self.outsider).read(["code"])
            # its team
            self.assertFalse(self.env["ea.audit.team.member"].with_user(self.outsider).search([("engagement_id", "=", self.engagement.id)]))
            with self.assertRaises(AccessError):
                self.engagement.sudo().team_member_ids[:1].with_user(self.outsider).read(["user_id"])
            # its papers and documents, where the papers addon is there
            for model in ("ea.audit.paper", "ea.audit.paper.answer", "ea.audit.task.attachment"):
                if model in self.env:
                    self.assertFalse(self.env[model].with_user(self.outsider).search([("engagement_id", "=", self.engagement.id)]))
            # the project behind the picker, and its budget screen
            with self.assertRaises(AccessError):
                self.project.with_user(self.outsider).read(["name"])
        self.assertCode("not-on-this-engagement", engagement.action_open_ea_budget)
        self.assertCode("not-on-this-engagement", self.env["ea.audit.team.budget"].with_user(self.outsider).ea_ts_budget, self.engagement.id)
        self.assertCode("not-on-this-engagement", engagement._ea_require_access)

    def test_an_archived_engagement_is_not_offered_and_takes_no_time(self):
        self.set_phase(self.engagement, "archived")
        offered = {p["id"] for p in self.sheet(self.outsider).ea_ts_sheet()["projects"]}
        self.assertNotIn(self.project.id, offered)
        self.assertCode("ts-archived", self.sheet(self.outsider).ea_ts_charge, str(TUESDAY), self.project.id, 1)

    def test_still_nobody_logs_time_for_someone_else(self):
        line = self.charge(self.staff)
        self.assertCode("ts-own-lines-only", line.with_user(self.outsider).write, {"unit_amount": 5})
        self.assertCode("ts-own-lines-only", self.charge, self.outsider, user_id=self.staff.id)

    def test_every_engagement_screen_leads_to_the_timesheet(self):
        action = self.engagement.with_user(self.staff).action_open_ea_timesheet()
        self.assertEqual((action["tag"], action["params"]), ("ea_audit_timesheet.sheet", {"resId": self.engagement.id}))
        items = self.env["ea.audit.ui"].with_user(self.reader)._ea_ui_shell_session()["mission_items"]
        self.assertIn("ea_audit_timesheet.sheet", [item["tag"] for item in items])
        for user in (self.staff, self.senior, self.manager, self.partner, self.admin, self.reader, self.eqr):
            apps = self.env["ea.audit.ui"].with_user(user)._ea_ui_shell_session()["apps"]
            self.assertIn("timesheet", [app["key"] for app in apps])
