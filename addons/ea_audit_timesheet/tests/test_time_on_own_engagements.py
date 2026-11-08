"""Owner, 2026-11-08: time goes on an engagement if and only if the person is on it. Every firm
user still opens the timesheet, and reaches it from any engagement they can open."""
from odoo.tests import HttpCase, tagged

from .common import MONDAY, TUESDAY, TimesheetCase


@tagged("post_install", "-at_install")
class TestTimeOnOwnEngagements(TimesheetCase):
    def setUp(self):
        super().setUp()
        # Y: the outsider is on it. X (self.engagement): they are not.
        self.other = self.make_engagement(2024, partner=self.partner2, nature="statutory_audit")
        self.seat(self.other, self.outsider, "staff")
        self.other_project = self.other._ea_ts_project()

    def test_a_staff_member_logs_on_their_engagement_and_is_refused_on_another(self):
        sheet = self.sheet(self.outsider)
        offered = {p["id"]: p for p in sheet.ea_ts_sheet()["projects"]}
        self.assertIn(self.other_project.id, offered)
        self.assertNotIn(self.project.id, offered)
        self.assertEqual({p["kind"] for p in offered.values()}, {"mission", "internal"})
        sheet.ea_ts_charge(str(TUESDAY), self.other_project.id, 2.5)
        sheet.ea_ts_set_cell(str(MONDAY), self.other_project.id, False, 1.5)
        self.assertEqual(sheet.ea_ts_sheet(str(TUESDAY))["total"], 4)
        # the engagement they are not on: refused through the screen, the cell and the ORM
        self.assertCode("ts-not-on-team", sheet.ea_ts_charge, str(TUESDAY), self.project.id, 1)
        self.assertCode("ts-not-on-team", sheet.ea_ts_set_cell, str(MONDAY), self.project.id, False, 1)
        self.assertCode("ts-not-on-team", self.charge, self.outsider, MONDAY)
        self.assertEqual(sheet.ea_ts_sheet(str(TUESDAY))["total"], 4)

    def test_every_firm_user_opens_the_timesheet_and_reaches_it_from_an_engagement(self):
        for user in (self.staff, self.senior, self.manager, self.partner, self.admin, self.reader, self.eqr):
            apps = self.env["ea.audit.ui"].with_user(user)._ea_ui_shell_session()["apps"]
            self.assertIn("timesheet", [app["key"] for app in apps])
            self.assertTrue(self.sheet(user).ea_ts_sheet()["days"])
        items = self.env["ea.audit.ui"].with_user(self.staff)._ea_ui_shell_session()["mission_items"]
        self.assertIn("ea_audit_timesheet.sheet", [item["tag"] for item in items])
        action = self.engagement.with_user(self.staff).action_open_ea_timesheet()
        self.assertEqual((action["tag"], action["params"]), ("ea_audit_timesheet.sheet", {"resId": self.engagement.id}))
        # the engagement it was opened from is in the picker, with its id, to come chosen
        offered = {p["engagement_id"]: p["id"] for p in self.sheet(self.staff).ea_ts_sheet()["projects"]}
        self.assertEqual(offered[self.engagement.id], self.project.id)

    def test_the_eqr_logs_time_on_the_engagement_they_review(self):
        self.seat(self.engagement, self.eqr, "eqr_reviewer")
        offered = {p["id"] for p in self.sheet(self.eqr).ea_ts_sheet()["projects"]}
        self.assertIn(self.project.id, offered)
        self.assertTrue(self.sheet(self.eqr).ea_ts_charge(str(TUESDAY), self.project.id, 1))


@tagged("post_install", "-at_install")
class TestFirmSignupClosed(HttpCase):
    def test_nobody_signs_up_uninvited_on_a_firm(self):
        scope = self.env["ir.config_parameter"].sudo().get_param("auth_signup.invitation_scope")
        self.assertEqual(scope, "b2b")
        self.assertEqual(self.url_open("/web/signup", allow_redirects=False).status_code, 404)
