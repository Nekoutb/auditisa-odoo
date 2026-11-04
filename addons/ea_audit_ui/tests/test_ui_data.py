"""The screens' read methods, under real users: counts from real records, and the
team-only rule of F008 holding on every one of them."""
from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import tagged

from odoo.addons.ea_audit_core.tests.common import EaAuditCase

from ..models.ui_data import DEMO_DIRECT_HASH


@tagged("post_install", "-at_install")
class TestUiData(EaAuditCase):
    def setUp(self):
        super().setUp()
        self.engagement = self.make_engagement(2025, partner=self.partner, nature="statutory_audit")
        self.set_phase(self.engagement, "execution")
        self.seat(self.engagement, self.manager, "manager")
        self.seat(self.engagement, self.senior, "senior")
        self.seat(self.engagement, self.staff, "staff")
        self.Ui = self.env["ea.audit.ui"]

    def ui(self, user):
        return self.Ui.with_user(user)

    def ring(self, data, key):
        return next(r for r in data["rings"] if r["key"] == key)

    def group(self, ring, group_id):
        return next(g for g in ring["groups"] if g["id"] == group_id)

    def active_count(self, prefixes):
        items = self.engagement.sudo().file_item_ids.filtered(lambda i: not i.conditional)
        return len(items.filtered(lambda i: i.code.startswith(prefixes)))

    # ------------------------------------------------------------------
    # counts
    # ------------------------------------------------------------------

    def test_a_new_file_reads_zero_with_real_totals(self):
        data = self.ui(self.partner).ea_ui_dashboard(self.engagement.id)
        self.assertEqual(data["pct"], 0)
        self.assertEqual(data["total"], self.active_count(("P", "S", "E", "C")))
        self.assertEqual(self.ring(data, "execution")["total"], self.active_count(("E",)))
        self.assertEqual(self.ring(data, "acceptance")["total"], self.active_count(("P",)))
        self.assertEqual(sum(r["total"] for r in data["rings"]), data["total"])

    def test_conditional_tasks_do_not_count(self):
        data = self.ui(self.partner).ea_ui_dashboard(self.engagement.id)
        e4 = self.group(self.ring(data, "execution"), "e4")
        self.item(self.engagement, "E4.2").conditional = True
        self.env.flush_all()
        again = self.ui(self.partner).ea_ui_dashboard(self.engagement.id)
        self.assertEqual(self.group(self.ring(again, "execution"), "e4")["total"], e4["total"] - 1)

    def test_a_preparer_signature_alone_moves_nothing(self):
        self.sign(self.staff, self.engagement, "E6.2", "preparer")
        data = self.ui(self.partner).ea_ui_dashboard(self.engagement.id)
        self.assertEqual(self.group(self.ring(data, "execution"), "e5")["done"], 0)

    def test_a_review_signature_counts_on_ring_group_and_overall(self):
        before = self.ui(self.partner).ea_ui_dashboard(self.engagement.id)
        self.sign(self.staff, self.engagement, "E6.2", "preparer")
        self.sign(self.senior, self.engagement, "E6.2", "reviewer")
        data = self.ui(self.partner).ea_ui_dashboard(self.engagement.id)
        execution = self.ring(data, "execution")
        self.assertEqual(self.group(execution, "e5")["done"], 1)
        self.assertEqual(execution["done"], 1)
        self.assertEqual(execution["pct"], round(100 / execution["total"]))
        self.assertEqual(data["done"], 1)
        self.assertEqual(data["total"], before["total"])
        self.assertEqual(data["pct"], round(100 / data["total"]))

    def test_a_voided_signature_stops_counting(self):
        self.sign(self.staff, self.engagement, "E6.2", "preparer")
        self.sign(self.senior, self.engagement, "E6.2", "reviewer")
        signoff = self.env["ea.audit.signoff"].sudo().search([
            ("engagement_id", "=", self.engagement.id), ("code", "=", "E6.2"), ("role", "=", "reviewer"),
        ])
        signoff.voided_at = fields.Datetime.now()
        data = self.ui(self.partner).ea_ui_dashboard(self.engagement.id)
        self.assertEqual(self.group(self.ring(data, "execution"), "e5")["done"], 0)

    def test_not_applicable_counts_as_done(self):
        self.item(self.engagement, "E6.2").not_applicable = True
        data = self.ui(self.partner).ea_ui_dashboard(self.engagement.id)
        self.assertEqual(self.group(self.ring(data, "execution"), "e5")["done"], 1)

    def test_tasks_with_no_preparer_are_counted(self):
        data = self.ui(self.partner).ea_ui_dashboard(self.engagement.id)
        self.assertEqual(len(data["unassigned_ids"]), data["total"])
        self.item(self.engagement, "E6.2").with_user(self.partner).assign_tasks(self.staff.id, "preparer")
        self.item(self.engagement, "E6.1").with_user(self.partner).assign_tasks(self.staff.id, "assignee")
        data = self.ui(self.partner).ea_ui_dashboard(self.engagement.id)
        self.assertEqual(len(data["unassigned_ids"]), data["total"] - 2)
        self.assertNotIn(self.item(self.engagement, "E6.2").id, data["unassigned_ids"])

    def test_an_archived_file_hands_nothing_out_and_nothing_is_late(self):
        self.engagement.sudo().write({"phase": "archived", "archived_at": fields.Datetime.now()})
        data = self.ui(self.partner).ea_ui_dashboard(self.engagement.id)
        self.assertEqual(data["unassigned_ids"], [])
        self.assertEqual(data["calendar"]["late"], 0)
        self.assertTrue(data["archived"])

    def test_late_tasks_read_from_the_task_or_its_phase(self):
        today = fields.Date.context_today(self.env["ea.audit.ui"])
        self.engagement.sudo().file_item_ids.write({"due_date": today + timedelta(days=20)})
        self.item(self.engagement, "E6.3").write({"due_date": today - timedelta(days=5)})
        data = self.ui(self.partner).ea_ui_dashboard(self.engagement.id)
        self.assertEqual(data["calendar"]["late"], 1)
        self.assertEqual(data["calendar"]["rows"][0]["code"], "E6.3")
        self.assertEqual(data["calendar"]["rows"][0]["late_days"], 5)
        self.assertEqual(data["attention"][0]["code"], "E6.3")
        self.assertEqual(data["attention"][0]["tone"], "r")

    def test_owner_data_of_later_addons_is_absent_not_invented(self):
        data = self.ui(self.partner).ea_ui_dashboard(self.engagement.id)
        self.assertEqual(set(data["notes"].values()), {None})

    def test_my_tasks(self):
        item = self.item(self.engagement, "E6.2")
        item.with_user(self.partner).assign_tasks(self.staff.id, "preparer")
        item.with_user(self.partner).assign_tasks(self.senior.id, "approver")
        mine = self.ui(self.staff).ea_ui_dashboard(self.engagement.id)["my_tasks"]
        self.assertEqual((mine["count"], mine["rows"][0]["code"], mine["rows"][0]["word"]), (1, "E6.2", "À préparer"))
        self.assertEqual(self.ui(self.senior).ea_ui_dashboard(self.engagement.id)["my_tasks"]["count"], 0)
        item.with_user(self.staff).action_sign("preparer")
        self.assertEqual(self.ui(self.staff).ea_ui_dashboard(self.engagement.id)["my_tasks"]["count"], 0)
        mine = self.ui(self.senior).ea_ui_dashboard(self.engagement.id)["my_tasks"]
        self.assertEqual((mine["count"], mine["rows"][0]["word"]), (1, "À réviser"))

    # ------------------------------------------------------------------
    # home
    # ------------------------------------------------------------------

    def test_home_row(self):
        self.sign(self.staff, self.engagement, "E6.2", "preparer")
        self.sign(self.senior, self.engagement, "E6.2", "reviewer")
        home = self.ui(self.partner).ea_ui_home()
        row = next(m for m in home["missions"] if m["id"] == self.engagement.id)
        self.assertEqual(row["report_due"], "30/06/2026")
        self.assertEqual(row["phase_deadline"], "31/03/2026")
        self.assertEqual(row["phase_label"], "Exécution")
        self.assertEqual(row["partner"], "Partner")
        self.assertEqual(row["nature"], "commissariat aux comptes")
        self.assertFalse(row["acceptance_signed"])
        self.assertEqual(row["done"], 1)
        self.assertEqual(row["pct"], round(100 / row["total"]))

    def test_home_todo_counts_what_waits_for_me(self):
        item = self.item(self.engagement, "E6.2")
        item.with_user(self.partner).assign_tasks(self.staff.id, "preparer")
        item.with_user(self.partner).assign_tasks(self.senior.id, "approver")
        item.with_user(self.staff).action_sign("preparer")
        todo = self.ui(self.senior).ea_ui_home()["todo"]
        self.assertEqual([(t["title"], t["count"]) for t in todo], [("Feuilles de travail en attente de revue", 1)])
        self.assertEqual(self.ui(self.manager).ea_ui_home()["todo"], [])

    def test_home_todo_acceptance_is_the_partners(self):
        fresh = self.make_engagement(2026, partner=self.partner)
        titles = [t["title"] for t in self.ui(self.partner).ea_ui_home()["todo"] if t["engagement_id"] == fresh.id]
        self.assertIn("Acceptation en attente de la signature de l'associé", titles)

    def test_home_todo_does_not_list_the_acceptance_twice(self):
        fresh = self.make_engagement(2026, partner=self.partner)
        self.seat(fresh, self.manager, "manager")
        p11 = self.item(fresh, "P1.1")
        p11.with_user(self.manager).assign_tasks(self.manager.id, "preparer")
        p11.with_user(self.manager).assign_tasks(self.partner.id, "approver")
        p11.with_user(self.manager).action_sign("preparer")
        titles = [t["title"] for t in self.ui(self.partner).ea_ui_home()["todo"] if t["engagement_id"] == fresh.id]
        self.assertEqual(titles, ["Acceptation en attente de la signature de l'associé"])

    def test_home_todo_shows_an_invitation_without_opening_the_file(self):
        self.engagement.with_user(self.partner)._ea_invite_user(self.outsider, "staff")
        home = self.ui(self.outsider).ea_ui_home()
        self.assertEqual(home["missions"], [])
        self.assertEqual([t["title"] for t in home["todo"]], ["Invitation à répondre"])

    # ------------------------------------------------------------------
    # the task list
    # ------------------------------------------------------------------

    def test_task_rows(self):
        item = self.item(self.engagement, "E6.2")
        item.with_user(self.partner).assign_tasks(self.staff.id, "preparer")
        item.with_user(self.partner).assign_tasks(self.senior.id, "approver")
        item.with_user(self.staff).action_sign("preparer")
        data = self.ui(self.partner).ea_ui_tasks(self.engagement.id, "e5")
        self.assertEqual(data["group"]["code"], "E5")
        self.assertEqual(data["total"], 8)
        row = next(r for r in data["rows"] if r["code"] == "E6.2")
        self.assertEqual(row["preparer"]["name"], "Staff")
        self.assertTrue(row["preparer"]["signed"])
        self.assertRegex(row["preparer"]["detail"], r"^Signé le \d\d/\d\d/\d{4}$")
        self.assertEqual(row["reviewer"]["name"], "Senior")
        self.assertFalse(row["reviewer"]["signed"])
        self.assertEqual(row["reviewer"]["detail"], "En attente de révision")
        self.assertIsNone(row["partner"])
        self.assertEqual(row["pill"], "EN RÉVISION")
        unassigned = next(r for r in data["rows"] if r["code"] == "E6.1")
        self.assertEqual(unassigned["preparer"]["name"], "Non assigné")
        # no approver: the engagement's partner reviews by default
        self.assertEqual(unassigned["reviewer"]["name"], "Partner")

    def test_partner_gated_tasks_carry_the_partner_cell(self):
        rows = self.ui(self.partner).ea_ui_tasks(self.engagement.id, "p5")["rows"]
        self.assertIsNone(next(r for r in rows if r["code"] == "P5.1")["partner"])
        gated = next(r for r in rows if r["code"] == "P5.2")["partner"]
        self.assertEqual(gated["name"], "Partner")
        self.assertFalse(gated["signed"])

    def test_a_partner_signature_shows_in_its_column(self):
        self.sign(self.senior, self.engagement, "P5.2", "preparer")
        self.sign(self.partner, self.engagement, "P5.2", "partner")
        rows = self.ui(self.staff).ea_ui_tasks(self.engagement.id, "p5")["rows"]
        row = next(r for r in rows if r["code"] == "P5.2")
        self.assertTrue(row["partner"]["signed"])
        self.assertFalse(row["reviewer"]["signed"])
        self.assertEqual(row["pill"], "TERMINÉE")

    def test_a_directly_written_demo_signature_is_labelled(self):
        item = self.item(self.engagement, "E4.1")
        self.env["ea.audit.signoff"].sudo().create({
            "file_item_id": item.id, "role": "preparer", "user_id": self.staff.id, "content_hash": DEMO_DIRECT_HASH,
        })
        rows = self.ui(self.partner).ea_ui_tasks(self.engagement.id, "e4")["rows"]
        self.assertTrue(next(r for r in rows if r["code"] == "E4.1")["preparer"]["demo"])

    def test_an_unknown_group_is_refused(self):
        self.assertEqual(self.ui(self.partner).ea_ui_tasks(self.engagement.id, "zz"), {"denied": True})

    # ------------------------------------------------------------------
    # team-only access
    # ------------------------------------------------------------------

    def assertSeesNoFile(self, user):
        ui = self.ui(user)
        home = ui.ea_ui_home()
        self.assertEqual(home["missions"], [])
        self.assertEqual(home["todo"], [])
        self.assertEqual(ui.ea_ui_dashboard(self.engagement.id), {"denied": True})
        self.assertEqual(ui.ea_ui_tasks(self.engagement.id, "e4"), {"denied": True})
        self.assertEqual(ui.ea_ui_shell()["recent"], [])
        self.assertFalse(ui.ea_ui_context("ea.audit.engagement", self.engagement.id))
        self.assertFalse(ui.ea_ui_context("ea.audit.file.item", self.item(self.engagement, "E4.1").id))
        results = ui.ea_ui_search("Governance")
        self.assertEqual(results["missions"], [])
        self.assertEqual(ui.ea_ui_search("E4.1")["tasks"], [])

    def test_a_system_administrator_off_the_team_sees_no_mission(self):
        self.admin.group_ids = [(4, self.env.ref("base.group_system").id)]
        self.assertSeesNoFile(self.admin)

    def test_a_firm_administrator_off_the_team_sees_no_mission(self):
        self.assertSeesNoFile(self.admin)

    def test_a_partner_off_the_team_sees_no_mission(self):
        self.assertSeesNoFile(self.partner2)

    def test_a_colleague_off_the_team_sees_no_mission(self):
        self.assertSeesNoFile(self.outsider)

    def test_an_invited_member_sees_no_file_until_accepting(self):
        member = self.engagement.with_user(self.partner)._ea_invite_user(self.outsider, "staff")
        self.assertEqual(self.ui(self.outsider).ea_ui_dashboard(self.engagement.id), {"denied": True})
        member.with_user(self.outsider).action_accept()
        self.assertEqual(self.ui(self.outsider).ea_ui_dashboard(self.engagement.id)["mission"]["id"], self.engagement.id)

    def test_a_member_sees_their_mission_everywhere(self):
        ui = self.ui(self.staff)
        self.assertEqual([m["id"] for m in ui.ea_ui_home()["missions"]], [self.engagement.id])
        self.assertEqual([m["id"] for m in ui.ea_ui_shell()["recent"]], [self.engagement.id])
        self.assertEqual([m["id"] for m in ui.ea_ui_search("Governance")["missions"]], [self.engagement.id])
        tasks = ui.ea_ui_search("E4.1")["tasks"]
        self.assertTrue(all(t["code"].startswith("E4.1") for t in tasks) and tasks)
        self.assertEqual(ui.ea_ui_context("ea.audit.file.item", self.item(self.engagement, "E4.1").id)["id"], self.engagement.id)

    def test_two_files_stay_apart(self):
        other = self.make_engagement(2025, partner=self.partner2, client=self.env["ea.audit.client"].create({"name": "Autre SA"}))
        self.assertNotIn(other.id, [m["id"] for m in self.ui(self.partner).ea_ui_home()["missions"]])
        self.assertEqual(self.ui(self.partner).ea_ui_search("Autre")["missions"], [])

    # ------------------------------------------------------------------
    # the bell
    # ------------------------------------------------------------------

    def test_a_preparer_signature_notifies_the_reviewer(self):
        item = self.item(self.engagement, "E6.2")
        item.with_user(self.manager).assign_tasks(self.staff.id, "preparer")
        item.with_user(self.manager).assign_tasks(self.senior.id, "approver")
        item.with_user(self.staff).action_sign("preparer")
        rows = self.ui(self.senior).ea_ui_notifications()
        self.assertEqual(rows["unread"], 2)
        self.assertIn("À réviser : E6.2", rows["rows"][0]["title"])

    def test_nobody_is_notified_of_their_own_act(self):
        item = self.item(self.engagement, "E6.2")
        item.with_user(self.staff).assign_tasks(self.staff.id, "preparer")
        self.assertEqual(self.ui(self.staff).ea_ui_notifications()["rows"], [])

    def test_opening_a_row_marks_it_read_and_leads_to_the_task(self):
        item = self.item(self.engagement, "E6.2")
        item.with_user(self.manager).assign_tasks(self.staff.id, "preparer")
        row = self.ui(self.staff).ea_ui_notifications()["rows"][0]
        link = self.ui(self.staff).ea_ui_notification_open(row["id"])
        self.assertEqual(link["file_item_id"], item.id)
        self.assertEqual(self.ui(self.staff).ea_ui_notifications()["unread"], 0)

    def test_notifications_are_private(self):
        item = self.item(self.engagement, "E6.2")
        item.with_user(self.manager).assign_tasks(self.staff.id, "preparer")
        row = self.ui(self.staff).ea_ui_notifications()["rows"][0]
        self.assertFalse(self.ui(self.senior).ea_ui_notification_open(row["id"]))
        self.assertEqual(self.ui(self.staff).ea_ui_notifications()["unread"], 1)
        notification = self.env["ea.audit.notification"].browse(row["id"])
        with self.assertRaises(AccessError):
            notification.with_user(self.senior).read(["title"])
        with self.assertRaises(AccessError):
            notification.with_user(self.staff).write({"title": "x"})

    def test_a_removed_member_loses_the_rows_of_that_file(self):
        item = self.item(self.engagement, "E6.2")
        item.with_user(self.manager).assign_tasks(self.staff.id, "preparer")
        self.engagement.with_user(self.partner).remove_team_member(self.staff.id)
        self.assertEqual(self.ui(self.staff).ea_ui_notifications()["rows"], [])

    def test_an_invitation_reaches_someone_not_on_the_team(self):
        self.engagement.with_user(self.partner)._ea_invite_user(self.outsider, "staff")
        rows = self.ui(self.outsider).ea_ui_notifications()["rows"]
        self.assertEqual(rows[0]["kind"], "invitation")

    # ------------------------------------------------------------------
    # the shell
    # ------------------------------------------------------------------

    def test_the_shell_facts(self):
        self.partner.name = "Jean-Pierre Mbarga"
        shell = self.ui(self.partner)._ea_ui_shell_session()
        self.assertEqual(shell["name"], "J.-P. Mbarga")
        self.assertEqual(shell["first_name"], "Jean-Pierre")
        self.assertEqual(shell["initials"], "JM")
        self.assertEqual(shell["role"], "Associé")
        self.assertTrue(shell["can_write"])

    def test_someone_outside_the_firm_keeps_odoos_navbar(self):
        user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Interne", "login": "interne@gov.example.com",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })
        self.assertFalse(self.ui(user)._ea_ui_shell_session())

    def test_a_read_only_member_cannot_write(self):
        self.assertFalse(self.ui(self.reader)._ea_ui_shell_session()["can_write"])

    def test_dates_are_day_month_year_in_any_language(self):
        self.assertEqual(self.engagement.period_end, date(2025, 12, 31))
        data = self.ui(self.partner).with_context(lang="en_US").ea_ui_dashboard(self.engagement.id)
        self.assertEqual(data["period_end"], "31/12/2025")
