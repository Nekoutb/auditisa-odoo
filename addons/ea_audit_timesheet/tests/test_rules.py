"""The owner's rules, on the ORM's entry points: the deadline, the reopening, who may
charge what, and the bounds on hours."""
from datetime import date, timedelta

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import (
    AT_DEADLINE_LAST_MINUTE,
    AT_LOCK,
    AT_NEXT_MONDAY,
    IN_THE_WEEK,
    MONDAY,
    NEXT_MONDAY,
    SUNDAY,
    TUESDAY,
    TimesheetCase,
)


@tagged("post_install", "-at_install")
class TestDeadline(TimesheetCase):
    def test_monday_of_the_following_week_is_open(self):
        self.at(AT_NEXT_MONDAY)
        self.assertEqual(self.charge(self.staff).unit_amount, 2)

    def test_tuesday_23_59_douala_is_open(self):
        self.at(AT_DEADLINE_LAST_MINUTE)
        self.assertEqual(self.charge(self.staff, SUNDAY).unit_amount, 2)

    def test_wednesday_00_00_douala_is_locked(self):
        self.at(AT_LOCK)
        self.assertCode("ts-week-locked", self.charge, self.staff)
        self.assertCode("ts-week-locked", self.charge, self.staff, SUNDAY)
        # the week that follows is open at that same instant
        self.assertEqual(self.charge(self.staff, NEXT_MONDAY).unit_amount, 2)

    def test_locked_week_refuses_direct_write_and_unlink(self):
        line = self.charge(self.staff)
        self.at(AT_LOCK)
        as_staff = line.with_user(self.staff)
        self.assertCode("ts-week-locked", as_staff.write, {"unit_amount": 3})
        self.assertCode("ts-week-locked", as_staff.write, {"name": "changé"})
        self.assertCode("ts-week-locked", as_staff.unlink)

    def test_moving_a_line_out_of_or_into_a_locked_week_is_refused(self):
        old = self.charge(self.staff)
        self.at(AT_LOCK)
        recent = self.charge(self.staff, NEXT_MONDAY)
        self.assertCode("ts-week-locked", old.with_user(self.staff).write, {"date": NEXT_MONDAY})
        self.assertCode("ts-week-locked", recent.with_user(self.staff).write, {"date": TUESDAY})

    def test_backdated_entry_and_import_are_refused(self):
        self.at(AT_LOCK)
        long_ago = MONDAY - timedelta(days=60)
        self.assertCode("ts-week-locked", self.charge, self.staff, long_ago)
        result = self.Line.with_user(self.staff).with_context(import_file=True).load(
            ["date", "project_id/.id", "unit_amount", "name"],
            [[str(long_ago), str(self.project.id), "2", "import"]],
        )
        self.assertFalse(result["ids"])
        self.assertTrue(result["messages"])

    def test_copying_a_line_into_a_locked_week_is_refused(self):
        line = self.charge(self.staff)
        self.at(AT_LOCK)
        self.assertCode("ts-week-locked", line.with_user(self.staff).copy)

    def test_the_superuser_is_not_exempt_from_the_deadline(self):
        line = self.charge(self.staff)
        self.at(AT_LOCK)
        self.assertCode("ts-week-locked", line.sudo().write, {"unit_amount": 5})
        self.assertCode("ts-week-locked", line.sudo().unlink)
        self.assertCode("ts-week-locked", self.Line.sudo().create, {
            "date": TUESDAY, "project_id": self.project.id, "unit_amount": 1, "name": "/", "user_id": self.staff.id,
        })

    def test_odoo_bookkeeping_still_passes_on_a_locked_line(self):
        line = self.charge(self.staff)
        self.at(AT_LOCK)
        line.sudo().write({"amount": -10.0})
        self.assertEqual(line.sudo().amount, -10.0)

    def test_no_field_of_a_locked_line_is_open_to_its_owner(self):
        line = self.charge(self.staff)
        phase = line.sudo().ea_phase
        self.at(AT_LOCK)
        as_staff = line.with_user(self.staff)
        self.assertCode("ts-week-locked", as_staff.write, {"amount": -99.0})
        self.assertCode("ts-week-locked", as_staff.write, {"ref": "x", "ea_phase": "conclusion"})
        as_staff.write({"ea_phase": "conclusion"})
        self.assertEqual(line.sudo().ea_phase, phase)

    def test_context_does_not_relax_it(self):
        self.at(AT_LOCK)
        loud = self.Line.with_user(self.staff).with_context(install_mode=True, ea_ts_bypass=True, force_lock=True)
        self.assertCode("ts-week-locked", loud.create, {
            "date": TUESDAY, "project_id": self.project.id, "unit_amount": 1, "name": "/",
        })

    def test_future_dates_are_refused(self):
        self.assertCode("ts-future-date", self.charge, self.staff, date(2026, 11, 5))
        self.assertCode("ts-future-date", self.charge, self.staff, date(2027, 1, 4))
        line = self.charge(self.staff)
        self.assertCode("ts-future-date", line.with_user(self.staff).write, {"date": date(2026, 11, 5)})

    def test_today_is_read_in_douala(self):
        # Wednesday 23:30 UTC: already Thursday 00:30 in Douala, on a server clock in UTC
        self.at(IN_THE_WEEK.replace(hour=23, minute=30))
        self.assertEqual(self.charge(self.staff, date(2026, 11, 5)).unit_amount, 2)

    def test_submit_locks_the_week_and_recall_opens_it(self):
        line = self.charge(self.staff)
        sheet = self.sheet(self.staff)
        sheet.ea_ts_submit(str(TUESDAY))
        self.assertEqual(self.Week._ea_ts_status(self.staff, MONDAY), "submitted")
        self.assertCode("ts-week-submitted", line.with_user(self.staff).write, {"unit_amount": 3})
        self.assertCode("ts-week-submitted", self.charge, self.staff, MONDAY)
        sheet.ea_ts_recall(str(TUESDAY))
        line.with_user(self.staff).write({"unit_amount": 3})
        self.assertEqual(line.sudo().unit_amount, 3)

    def test_submission_after_the_deadline_is_refused(self):
        self.at(AT_LOCK)
        self.assertCode("ts-submit-closed", self.sheet(self.staff).ea_ts_submit, str(TUESDAY))

    def test_recall_after_the_deadline_is_refused(self):
        self.sheet(self.staff).ea_ts_submit(str(TUESDAY))
        self.at(AT_LOCK)
        self.assertEqual(self.Week._ea_ts_status(self.staff, MONDAY), "locked_submitted")
        self.assertCode("ts-recall-closed", self.sheet(self.staff).ea_ts_recall, str(TUESDAY))

    def test_a_week_not_begun_cannot_be_submitted(self):
        self.assertCode("ts-submit-future", self.sheet(self.staff).ea_ts_submit, str(NEXT_MONDAY))

    def test_week_rows_are_closed_to_direct_writes(self):
        self.charge(self.staff)
        row = self.Week._ea_ts_row(self.staff, MONDAY).with_user(self.staff)
        with self.assertRaises(Exception):
            row.write({"state": "submitted"})
        with self.assertRaises(Exception):
            row.create({"user_id": self.staff.id, "week_start": NEXT_MONDAY})
        with self.assertRaises(Exception):
            row.unlink()


@tagged("post_install", "-at_install")
class TestReopen(TimesheetCase):
    REASON = "Mission de terrain sans réseau"

    def test_firm_admin_reopens_with_a_reason_for_a_limited_time(self):
        line = self.charge(self.staff)
        self.at(AT_LOCK)
        result = self.sheet(self.admin).ea_ts_reopen(self.staff.id, str(TUESDAY), self.REASON)
        self.assertEqual(result["until"], "13/11/2026 00:00")
        self.assertEqual(self.Week._ea_ts_status(self.staff, MONDAY), "reopened")
        line.with_user(self.staff).write({"unit_amount": 4})
        self.assertEqual(line.sudo().unit_amount, 4)
        record = self.Reopen.sudo().search([("user_id", "=", self.staff.id)])
        self.assertEqual(record.opened_by_id, self.admin)
        self.assertEqual(record.reason, self.REASON)
        self.assertTrue(self.Log.search_count([("kind", "=", "week_reopened"), ("target_id", "=", self.staff.id)]))

    def test_it_closes_when_the_time_is_up(self):
        line = self.charge(self.staff)
        self.at(AT_LOCK)
        self.sheet(self.admin).ea_ts_reopen(self.staff.id, str(TUESDAY), self.REASON)
        self.at(AT_LOCK + timedelta(hours=48))
        self.assertEqual(self.Week._ea_ts_status(self.staff, MONDAY), "locked")
        self.assertCode("ts-week-locked", line.with_user(self.staff).write, {"unit_amount": 1})

    def test_it_reopens_only_that_person_s_week(self):
        self.charge(self.senior)
        self.at(AT_LOCK)
        self.sheet(self.admin).ea_ts_reopen(self.staff.id, str(TUESDAY), self.REASON)
        self.assertEqual(self.Week._ea_ts_status(self.senior, MONDAY), "locked")
        self.assertCode("ts-week-locked", self.charge, self.senior)
        self.assertCode("ts-week-locked", self.charge, self.staff, MONDAY - timedelta(days=7))

    def test_resubmitting_ends_the_reopening(self):
        self.charge(self.staff)
        self.sheet(self.staff).ea_ts_submit(str(TUESDAY))
        self.at(AT_LOCK)
        self.sheet(self.admin).ea_ts_reopen(self.staff.id, str(TUESDAY), self.REASON)
        self.sheet(self.staff).ea_ts_submit(str(TUESDAY))
        self.assertEqual(self.Week._ea_ts_status(self.staff, MONDAY), "locked_submitted")
        self.assertCode("ts-week-locked", self.charge, self.staff)
        self.assertTrue(self.Reopen.sudo().search([("user_id", "=", self.staff.id)]).closed_at)

    def test_who_may_reopen(self):
        self.at(AT_LOCK)
        reopen = lambda actor: self.attempt(self.sheet(actor).ea_ts_reopen, self.staff.id, str(TUESDAY), self.REASON)
        self.assertEqual(reopen(self.staff), "ts-reopen-self")
        for actor in (self.senior, self.manager, self.reader, self.eqr):
            self.assertEqual(reopen(actor), "ts-reopen-forbidden")
        # a partner of the firm with no file in common with this person
        self.assertEqual(reopen(self.partner2), "ts-reopen-forbidden")
        self.assertEqual(reopen(self.partner), "ok")

    def test_a_reason_is_required(self):
        self.at(AT_LOCK)
        for reason in ("", "   ", "court"):
            self.assertCode("ts-reopen-reason", self.sheet(self.admin).ea_ts_reopen, self.staff.id, str(TUESDAY), reason)

    def test_an_open_week_is_not_reopened(self):
        self.assertCode("ts-reopen-not-locked", self.sheet(self.admin).ea_ts_reopen, self.staff.id, str(TUESDAY), self.REASON)

    def test_twice_is_refused(self):
        self.at(AT_LOCK)
        self.sheet(self.admin).ea_ts_reopen(self.staff.id, str(TUESDAY), self.REASON)
        self.assertCode("ts-reopen-active", self.sheet(self.admin).ea_ts_reopen, self.staff.id, str(TUESDAY), self.REASON)

    def test_the_record_is_kept_as_written(self):
        self.at(AT_LOCK)
        self.sheet(self.admin).ea_ts_reopen(self.staff.id, str(TUESDAY), self.REASON)
        record = self.Reopen.sudo().search([("user_id", "=", self.staff.id)])
        self.assertCode("ts-reopen-forbidden", record.write, {"reason": "autre chose encore"})
        self.assertCode("ts-reopen-forbidden", record.write, {"expires_at": AT_LOCK + timedelta(days=90)})
        self.assertCode("ts-reopen-forbidden", record.unlink)
        self.assertCode("ts-reopen-forbidden", self.Reopen.with_user(self.staff).create, {
            "user_id": self.staff.id, "week_start": MONDAY, "reason": "je me rouvre", "opened_by_id": self.staff.id,
            "opened_at": AT_LOCK, "expires_at": AT_LOCK + timedelta(days=90),
        })


@tagged("post_install", "-at_install")
class TestWhoChargesWhat(TimesheetCase):
    def test_each_engagement_has_its_project_and_phase_tasks(self):
        self.assertEqual(self.project.ea_engagement_id, self.engagement)
        self.assertEqual(self.project.privacy_visibility, "followers")
        self.assertEqual(
            sorted(self.project.task_ids.mapped("ea_phase")), ["acceptance", "conclusion", "execution", "strategy"],
        )

    def test_every_firm_member_charges_any_open_engagement(self):
        """Owner, 2026-11-07: time on any engagement of the firm, on its team or not."""
        self.assertEqual(self.charge(self.staff).project_id, self.project)
        for user in (self.outsider, self.admin, self.partner2, self.reader, self.eqr):
            self.assertEqual(self.charge(user).project_id, self.project)

    def test_invited_and_declined_charge_as_any_member_of_the_firm(self):
        member = self.seat(self.engagement, self.outsider, "staff", state="invited")
        self.assertEqual(self.charge(self.outsider).project_id, self.project)
        member.sudo().state = "declined"
        self.assertEqual(self.charge(self.outsider, MONDAY).project_id, self.project)

    def test_a_portal_user_charges_nothing(self):
        portal = self.env["res.users"].sudo().with_context(no_reset_password=True).create({
            "name": "Client", "login": "client@ailleurs.example.org",
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        self.assertEqual(
            self.Line._ea_ts_chargeable_refusal(self.project, portal), "ts-not-firm-member",
        )

    def test_internal_projects_are_open_to_every_firm_role(self):
        for user in (self.outsider, self.admin, self.reader, self.eqr):
            self.assertEqual(self.charge(user, project=self.internal).project_id, self.internal)

    def test_other_projects_are_refused(self):
        self.assertCode("ts-project-not-chargeable", self.charge, self.staff, project=self.other_user_project)

    def test_a_line_moves_to_another_open_engagement_but_not_an_archived_one(self):
        other = self.make_engagement(2024, partner=self.partner2, nature="statutory_audit")
        line = self.charge(self.staff, project=self.internal)
        line.with_user(self.staff).write({"project_id": other._ea_ts_project().id})
        self.assertEqual(line.sudo().project_id, other._ea_ts_project())
        closed = self.make_engagement(2023, partner=self.partner2, nature="statutory_audit")
        self.set_phase(closed, "archived")
        self.assertCode(
            "ts-archived", line.with_user(self.staff).write, {"project_id": closed._ea_ts_project().id},
        )

    def test_nobody_charges_for_someone_else(self):
        self.assertCode("ts-own-lines-only", self.charge, self.partner, user_id=self.staff.id)
        self.assertCode("ts-own-lines-only", self.charge, self.admin, project=self.internal, user_id=self.staff.id)
        self.staff._ea_ts_ensure_employee()
        employee = self.env["hr.employee"].sudo().search([("user_id", "=", self.staff.id)], limit=1)
        with self.assertRaises(Exception):
            self.charge(self.partner, employee_id=employee.id)

    def test_nobody_edits_someone_else_s_line(self):
        line = self.charge(self.staff)
        for actor in (self.partner, self.manager, self.admin):
            self.assertCode("ts-own-lines-only", line.with_user(actor).write, {"unit_amount": 1})
            self.assertCode("ts-own-lines-only", line.with_user(actor).unlink)
        mine = self.charge(self.senior)
        self.assertCode("ts-own-lines-only", mine.with_user(self.senior).write, {"user_id": self.staff.id})

    def test_archived_engagement_refuses_time(self):
        line = self.charge(self.staff)
        self.set_phase(self.engagement, "archived")
        self.assertFalse(self.project.active)
        self.assertCode("ts-archived", self.charge, self.staff)
        self.assertCode("ts-archived", line.with_user(self.staff).write, {"unit_amount": 1})
        self.assertCode("ts-archived", line.with_user(self.staff).unlink)

    def test_a_task_of_another_file_does_not_open_that_file(self):
        other = self.make_engagement(2024, partner=self.partner, nature="statutory_audit")
        foreign = other._ea_ts_project()
        line = self.charge(self.staff, task_id=foreign.task_ids[0].id)
        self.assertEqual(line.sudo().project_id, self.project)
        self.assertFalse(line.sudo().task_id)
        # moving one's own line onto that file's task moves it to that open file (owner, 2026-11-07),
        # and still opens nothing of it
        self.attempt(line.with_user(self.staff).write, {"task_id": foreign.task_ids[0].id})
        self.assertIn(line.sudo().project_id, self.project | foreign)
        self.assertFalse(self.env["ea.audit.engagement"].with_user(self.staff).search([("id", "=", other.id)]))

    def test_the_phase_comes_from_the_task_or_the_file(self):
        self.set_phase(self.engagement, "execution")
        self.assertEqual(self.charge(self.staff).ea_phase, "execution")
        task = self.project.task_ids.filtered(lambda t: t.ea_phase == "strategy")
        self.assertEqual(self.charge(self.staff, MONDAY, task_id=task.id).ea_phase, "strategy")


@tagged("post_install", "-at_install")
class TestHours(TimesheetCase):
    def test_range(self):
        self.assertCode("ts-hours-range", self.charge, self.staff, hours=-1)
        self.assertCode("ts-hours-range", self.charge, self.staff, hours=24.5)
        self.assertEqual(self.charge(self.staff, hours=24).unit_amount, 24)

    def test_nan_is_refused(self):
        self.assertCode("ts-hours-range", self.charge, self.staff, hours=float("nan"))

    def test_day_total_across_projects(self):
        self.charge(self.staff, hours=20)
        self.assertCode("ts-day-over-24", self.charge, self.staff, hours=4.5, project=self.internal)
        self.assertEqual(self.charge(self.staff, hours=4, project=self.internal).unit_amount, 4)

    def test_day_total_on_a_write_and_on_a_move(self):
        self.charge(self.staff, hours=20)
        other = self.charge(self.staff, hours=4, project=self.internal)
        self.assertCode("ts-day-over-24", other.with_user(self.staff).write, {"unit_amount": 5})
        monday_line = self.charge(self.staff, MONDAY, hours=10)
        self.assertCode("ts-day-over-24", monday_line.with_user(self.staff).write, {"date": TUESDAY})

    def test_the_limit_is_per_person(self):
        self.charge(self.staff, hours=24)
        self.assertEqual(self.charge(self.senior, hours=24).unit_amount, 24)

    def test_the_sheet_refuses_negative_and_non_numbers(self):
        sheet = self.sheet(self.staff)
        self.assertCode("ts-hours-range", sheet.ea_ts_charge, str(TUESDAY), self.project.id, -2)
        self.assertCode("ts-hours-range", sheet.ea_ts_charge, str(TUESDAY), self.project.id, 0)
        self.assertCode("ts-hours-range", sheet.ea_ts_charge, str(TUESDAY), self.project.id, "beaucoup")
        self.assertCode("ts-hours-range", sheet.ea_ts_set_cell, str(TUESDAY), self.project.id, False, 25)


@tagged("post_install", "-at_install")
class TestReach(TimesheetCase):
    def setUp(self):
        super().setUp()
        self.staff_line = self.charge(self.staff)
        self.senior_line = self.charge(self.senior)
        self.training = self.charge(self.outsider, project=self.internal)

    def visible(self, user):
        return self.Line.with_user(user).search([("project_id", "!=", False)])

    def test_a_person_sees_only_their_own_lines(self):
        self.assertEqual(self.visible(self.staff), self.staff_line)
        with self.assertRaises(AccessError):
            self.senior_line.with_user(self.staff).read(["unit_amount"])

    def test_manager_and_above_see_every_line_of_the_firm(self):
        """Owner, 2026-11-07: the firm's time report, for manager, partner and firm administrator."""
        everyone = self.staff_line | self.senior_line | self.training
        for lead in (self.partner, self.manager, self.partner2, self.admin):
            self.assertEqual(self.visible(lead), everyone)

    def test_staff_senior_eqr_and_read_only_see_their_own(self):
        self.assertEqual(self.visible(self.senior), self.senior_line)
        self.assertEqual(self.visible(self.outsider), self.training)
        for user in (self.eqr, self.reader):
            self.assertFalse(self.visible(user))

    def test_a_manager_s_reach_crosses_files_they_are_not_on(self):
        other = self.make_engagement(2024, partner=self.partner2, nature="statutory_audit")
        far = self.charge(self.staff, MONDAY, project=other._ea_ts_project())
        for lead in (self.partner, self.manager):
            self.assertIn(far, self.visible(lead))
        self.assertNotIn(far, self.visible(self.senior))

    def test_firm_admin_gets_no_audit_file_through_it(self):
        Engagement = self.env["ea.audit.engagement"].with_user(self.admin)
        self.assertFalse(Engagement.search([("id", "=", self.engagement.id)]))
        with self.assertRaises(AccessError):
            self.engagement.with_user(self.admin).read(["client_id"])
        files = self.env["ea.audit.file.item"].with_user(self.admin)
        self.assertFalse(files.search([("engagement_id", "=", self.engagement.id)]))
        self.assertCode("not-on-this-engagement", self.engagement.with_user(self.admin).action_open_ea_budget)
        budget = self.env["ea.audit.team.budget"].with_user(self.admin)
        self.assertCode("not-on-this-engagement", budget.ea_ts_budget, self.engagement.id)

    def test_engagement_projects_are_hidden_from_the_rest_of_the_firm(self):
        projects = self.env["project.project"].with_user(self.outsider)
        self.assertFalse(projects.search([("id", "=", self.project.id)]))
        with self.assertRaises(AccessError):
            self.project.with_user(self.outsider).read(["name"])
        self.assertTrue(projects.search([("id", "=", self.internal.id)]))
        self.assertTrue(self.env["project.project"].with_user(self.staff).search([("id", "=", self.project.id)]))

    def test_nobody_in_the_firm_writes_a_project(self):
        for actor in (self.partner, self.admin):
            with self.assertRaises(AccessError):
                self.project.with_user(actor).write({"ea_engagement_id": False})
            with self.assertRaises(AccessError):
                self.env["project.project"].with_user(actor).create({"name": "Non", "ea_is_internal": True})

    def test_a_person_taken_off_the_team_still_charges_as_a_member_of_the_firm(self):
        self.engagement.with_user(self.partner).remove_team_member(self.senior.id)
        self.assertEqual(self.charge(self.senior, MONDAY).project_id, self.project)
