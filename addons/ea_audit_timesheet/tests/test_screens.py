"""What the screens read: the weekly sheet, its warnings, budgets, reports, the switcher."""
import io

from openpyxl import load_workbook

from odoo.tests import tagged

from ..services.workbook import report_workbook
from .common import AT_LOCK, AT_NEXT_MONDAY, MONDAY, NEXT_MONDAY, SUNDAY, TUESDAY, TimesheetCase


@tagged("post_install", "-at_install")
class TestSheet(TimesheetCase):
    def test_weekly_view_has_rows_days_and_totals(self):
        sheet = self.sheet(self.staff)
        sheet.ea_ts_charge(str(MONDAY), self.project.id, 3)
        sheet.ea_ts_charge(str(TUESDAY), self.project.id, 2.5, note="Revue")
        sheet.ea_ts_charge(str(TUESDAY), self.project.id, 1)
        sheet.ea_ts_charge(str(TUESDAY), self.internal.id, 4)
        data = sheet.ea_ts_sheet(str(TUESDAY))
        self.assertEqual(data["monday"], "2026-11-02")
        self.assertEqual(len(data["days"]), 7)
        self.assertEqual(data["days"][0]["label"], "Mon 02/11/2026")
        self.assertEqual(data["total"], 10.5)
        self.assertEqual(data["totals"]["2026-11-03"], 7.5)
        row = next(r for r in data["rows"] if r["project_id"] == self.project.id)
        self.assertEqual(row["cells"]["2026-11-03"], 3.5)
        self.assertEqual(row["total"], 6.5)

    def test_only_what_one_may_charge_is_offered(self):
        data = self.sheet(self.staff).ea_ts_sheet()
        offered = {p["id"] for p in data["projects"]}
        self.assertIn(self.project.id, offered)
        self.assertIn(self.internal.id, offered)
        self.assertNotIn(self.other_user_project.id, offered)
        kinds = {p["id"]: p["kind"] for p in data["projects"]}
        self.assertEqual(kinds[self.project.id], "mission")
        self.assertEqual({p["kind"] for p in data["projects"]}, {"mission", "internal"})
        # someone not on the team is offered the internal projects only
        outsider = {p["id"]: p["kind"] for p in self.sheet(self.outsider).ea_ts_sheet()["projects"]}
        self.assertNotIn(self.project.id, outsider)
        self.assertEqual(outsider[self.internal.id], "internal")

    def test_a_cell_sets_the_day_s_figure(self):
        sheet = self.sheet(self.staff)
        sheet.ea_ts_charge(str(TUESDAY), self.project.id, 3)
        sheet.ea_ts_charge(str(TUESDAY), self.project.id, 1)
        sheet.ea_ts_set_cell(str(TUESDAY), self.project.id, False, 5)
        self.assertEqual(sheet.ea_ts_sheet(str(TUESDAY))["total"], 5)
        sheet.ea_ts_set_cell(str(TUESDAY), self.project.id, False, 0)
        data = sheet.ea_ts_sheet(str(TUESDAY))
        self.assertEqual(data["total"], 0)
        self.assertFalse(data["rows"])

    def test_it_warns_in_advance_and_shows_what_is_overdue(self):
        self.env.cr.execute(
            "UPDATE res_users SET create_date = '2026-10-01' WHERE id = %s", [self.staff.id],
        )
        self.env.invalidate_all()
        self.at(AT_NEXT_MONDAY)
        data = self.sheet(self.staff).ea_ts_sheet()
        self.assertEqual(len(data["warnings"]), 1)
        self.assertIn("Tuesday 10/11/2026, 23:59", data["warnings"][0]["text"])
        self.at(AT_LOCK)
        data = self.sheet(self.staff).ea_ts_sheet(str(TUESDAY))
        self.assertFalse(data["can_edit"])
        self.assertEqual(data["status"], "locked")
        self.assertFalse(data["warnings"])
        self.assertIn("2026-11-02", [row["monday"] for row in data["overdue"]])

    def test_a_submitted_week_is_not_overdue(self):
        self.env.cr.execute("UPDATE res_users SET create_date = '2026-11-02' WHERE id = %s", [self.staff.id])
        self.env.invalidate_all()
        self.sheet(self.staff).ea_ts_submit(str(TUESDAY))
        self.at(AT_LOCK)
        self.assertNotIn("2026-11-02", [row["monday"] for row in self.sheet(self.staff).ea_ts_sheet()["overdue"]])

    def test_navigation_stops_at_the_current_week(self):
        data = self.sheet(self.staff).ea_ts_sheet(str(TUESDAY))
        self.assertFalse(data["has_next"])
        self.at(AT_NEXT_MONDAY)
        self.assertTrue(self.sheet(self.staff).ea_ts_sheet(str(TUESDAY))["has_next"])


@tagged("post_install", "-at_install")
class TestBudget(TimesheetCase):
    def member(self, user):
        return self.engagement.sudo()._ea_member(user)

    def budget(self, user):
        return self.env["ea.audit.team.budget"].with_user(user)

    def test_budget_against_actual_per_person_and_phase(self):
        self.set_phase(self.engagement, "execution")
        self.budget(self.manager).ea_ts_budget_set(self.member(self.staff).id, "execution", 40)
        self.charge(self.staff, hours=6)
        self.charge(self.staff, MONDAY, hours=2)
        data = self.budget(self.partner).ea_ts_budget(self.engagement.id)
        row = next(r for r in data["rows"] if r["member_id"] == self.member(self.staff).id)
        cell = next(c for c in row["cells"] if c["phase"] == "execution")
        self.assertEqual((cell["budget"], cell["actual"]), (40, 8))
        self.assertEqual((row["budget"], row["actual"]), (40, 8))
        self.assertTrue(data["can_edit"])

    def test_staff_read_their_own_row_only(self):
        data = self.budget(self.staff).ea_ts_budget(self.engagement.id)
        self.assertEqual([r["member_id"] for r in data["rows"]], [self.member(self.staff).id])
        self.assertFalse(data["can_edit"])

    def test_only_a_team_manager_sets_a_budget(self):
        member = self.member(self.staff).id
        self.assertCode("team-manager-only", self.budget(self.staff).ea_ts_budget_set, member, "execution", 5)
        self.assertCode("team-manager-only", self.budget(self.senior).ea_ts_budget_set, member, "execution", 5)
        self.assertCode("not-on-this-engagement", self.budget(self.admin).ea_ts_budget_set, member, "execution", 5)
        self.assertCode("not-on-this-engagement", self.budget(self.partner2).ea_ts_budget_set, member, "execution", 5)

    def test_bounds(self):
        member = self.member(self.staff).id
        for bad in (-1, "x", float("nan")):
            self.assertCode("ts-budget-range", self.budget(self.manager).ea_ts_budget_set, member, "execution", bad)
        self.assertCode("ts-budget-range", self.budget(self.manager).ea_ts_budget_set, member, "other", 5)

    def test_archived_file_refuses_a_budget(self):
        member = self.member(self.staff).id
        self.set_phase(self.engagement, "archived")
        self.assertCode("archived", self.budget(self.manager).ea_ts_budget_set, member, "execution", 5)


@tagged("post_install", "-at_install")
class TestReports(TimesheetCase):
    def setUp(self):
        super().setUp()
        self.charge(self.staff, hours=3)
        self.charge(self.senior, hours=5)
        self.charge(self.outsider, hours=1, project=self.internal)
        self.period = (str(MONDAY), str(SUNDAY))

    def report(self, user, group_by="person"):
        return self.sheet(user).ea_ts_report(*self.period, group_by)

    def test_by_person_follows_the_reach_of_the_caller(self):
        for lead in (self.admin, self.partner, self.partner2, self.manager):
            self.assertEqual(self.report(lead)["total"], 9)
            self.assertEqual(self.report(lead)["reach"], "The whole firm")
        self.assertEqual(self.report(self.staff)["total"], 3)
        self.assertEqual([r["label"] for r in self.report(self.staff)["rows"]], [self.staff.name])
        self.assertEqual(self.report(self.senior)["total"], 5)
        self.assertEqual(self.report(self.eqr)["total"], 0)

    def test_by_engagement_and_period(self):
        rows = self.report(self.admin, "engagement")["rows"]
        hours = {r["label"]: r["hours"] for r in rows}
        self.assertEqual((hours[self.project.name], hours[self.internal.name]), (8, 1))
        rows = self.report(self.admin, "period")["rows"]
        self.assertEqual([r["label"] for r in rows], ["Week of 02/11/2026 to 08/11/2026"])

    def test_the_workbook_has_real_dates_shown_dd_mm_yyyy(self):
        sheets = self.Sheet.with_user(self.staff)._ea_ts_export(MONDAY, SUNDAY)
        book = load_workbook(io.BytesIO(report_workbook(sheets)))
        self.assertEqual(book.sheetnames, ["Detail", "By person", "By engagement", "By week"])
        row = list(book["Detail"].iter_rows(min_row=2))
        self.assertEqual(len(row), 1)
        self.assertEqual(row[0][0].number_format, "DD/MM/YYYY")
        self.assertEqual(row[0][6].value, 3)

    def test_the_reopening_panel_is_for_partner_and_admin(self):
        self.assertFalse(self.report(self.staff)["can_reopen"])
        self.assertFalse(self.report(self.manager)["can_reopen"])
        data = self.report(self.partner)
        self.assertTrue(data["can_reopen"])
        names = [p["id"] for p in data["people"]]
        self.assertIn(self.staff.id, names)
        self.assertNotIn(self.outsider.id, names)
        self.assertIn(self.outsider.id, [p["id"] for p in self.report(self.admin)["people"]])


@tagged("post_install", "-at_install")
class TestSwitcher(TimesheetCase):
    def apps(self, user):
        return [app["key"] for app in self.env["ea.audit.ui"].with_user(user)._ea_ui_shell_session()["apps"]]

    def test_staff_get_audit_and_the_sheet(self):
        for user in (self.staff, self.senior, self.manager, self.partner, self.reader, self.eqr):
            self.assertEqual(self.apps(user), ["audit", "timesheet"])

    def test_firm_admin_also_gets_users_and_settings(self):
        self.assertEqual(self.apps(self.admin), ["audit", "timesheet", "users", "settings"])

    def test_the_audit_still_opens_first(self):
        apps = self.env["ea.audit.ui"].with_user(self.staff)._ea_ui_shell_session()["apps"]
        self.assertEqual(apps[0]["xmlid"], "ea_audit_ui.action_home")

    def test_every_app_action_exists(self):
        for app in self.env["ea.audit.ui"].with_user(self.admin)._ea_ui_shell_session()["apps"]:
            self.assertTrue(self.env.ref(app["xmlid"]))

    def test_no_time_off_or_sales_apps_are_installed(self):
        Module = self.env["ir.module.module"].sudo()
        installed = Module.search([("state", "=", "installed")]).mapped("name")
        for name in ("hr_holidays", "sale", "sale_timesheet", "account", "project_timesheet_holidays"):
            self.assertNotIn(name, installed)
