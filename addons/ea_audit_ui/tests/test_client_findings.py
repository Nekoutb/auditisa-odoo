"""The client's findings on the shell: search (F079), bell (F082), progress (F080), words (M-14)."""
import re

from odoo.tests import tagged
from odoo.tools import file_open

from odoo.addons.ea_audit_core.tests.common import EaAuditCase


@tagged("post_install", "-at_install")
class TestSearchReachesContent(EaAuditCase):
    def setUp(self):
        super().setUp()
        self.engagement = self.make_engagement(2025, partner=self.partner, nature="statutory_audit")
        self.seat(self.engagement, self.staff, "staff")
        self.ui = self.env["ea.audit.ui"].with_user(self.staff)

    def codes(self, term):
        return {row["code"] for row in self.ui.ea_ui_search(term)["methodology"]}

    def test_f079_dsf_and_505_find_the_papers_that_hold_them(self):
        self.assertIn("E6.10", self.codes("DSF"))
        self.assertTrue(self.codes("505"), "ISA 505 is cited in the confirmations papers")
        self.assertTrue(self.codes("ISA 240"))

    def test_f079_a_hit_shows_where_the_word_is(self):
        row = next(row for row in self.ui.ea_ui_search("DSF")["methodology"] if row["code"] == "E6.10")
        self.assertIn("DSF", row["snippet"])
        self.assertLessEqual(len(row["snippet"]), 180)
        self.assertEqual(row["id"], self.item(self.engagement, "E6.10").id)

    def test_f079_one_row_per_paper_on_the_open_mission(self):
        newer = self.make_engagement(2026, partner=self.partner, nature="statutory_audit")
        self.seat(newer, self.staff, "staff")
        rows = [row for row in self.ui.ea_ui_search("DSF")["methodology"] if row["code"] == "E6.10"]
        self.assertEqual([row["id"] for row in rows], [self.item(newer, "E6.10").id])
        rows = [row for row in self.ui.ea_ui_search("DSF", self.engagement.id)["methodology"] if row["code"] == "E6.10"]
        self.assertEqual([row["id"] for row in rows], [self.item(self.engagement, "E6.10").id])

    def test_f079_whole_words_not_parts(self):
        self.assertFalse(self.codes("DSFX"))

    def test_f079_french_finds_the_french_text(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        results = self.ui.with_context(lang="fr_FR").ea_ui_search("DSF")["methodology"]
        self.assertIn("E6.10", {row["code"] for row in results})

    def test_f079_nothing_from_a_file_off_the_team(self):
        for term in ("DSF", "505"):
            self.assertEqual(self.env["ea.audit.ui"].with_user(self.outsider).ea_ui_search(term)["methodology"], [])

    def test_f079_answers_are_searched_under_the_rules(self):
        item = self.item(self.engagement, "E6.2").sudo()
        item.with_user(self.staff).get_paper_payload()
        paper = self.env["ea.audit.paper"].sudo().search([("file_item_id", "=", item.id)], limit=1)
        self.env["ea.audit.paper.answer"].sudo().with_context(ea_audit_answer_door=True).create({
            "paper_id": paper.id, "field_key": "search_note", "value": "Le contrat Zebulon est signé hors exercice.",
        })
        rows = self.ui.ea_ui_search("zebulon")["answers"]
        self.assertEqual([row["code"] for row in rows], ["E6.2"])
        self.assertIn("Zebulon", rows[0]["snippet"])
        self.assertEqual(self.env["ea.audit.ui"].with_user(self.outsider).ea_ui_search("zebulon")["answers"], [])


@tagged("post_install", "-at_install")
class TestBell(EaAuditCase):
    def setUp(self):
        super().setUp()
        self.engagement = self.make_engagement(2025, partner=self.partner)
        self.seat(self.engagement, self.staff, "staff")
        self.Note = self.env["ea.audit.notification"].sudo()
        self.ui = self.env["ea.audit.ui"].with_user(self.staff)

    def note(self, **vals):
        return self.Note.create({"user_id": self.staff.id, "title": "T", "engagement_id": self.engagement.id, **vals})

    def test_f082_rows_are_real_addresses(self):
        item = self.item(self.engagement, "E6.2")
        task = self.note(kind="task", file_item_id=item.id)
        mission = self.note(kind="mission")
        invitation = self.note(kind="invitation")
        urls = {row["id"]: row["url"] for row in self.ui.ea_ui_notifications()["rows"]}
        self.assertEqual(urls[task.id], "/odoo/%d/ea_audit_paper" % item.id)
        self.assertEqual(urls[mission.id], "/odoo/ea.audit.engagement/%d" % self.engagement.id)
        self.assertEqual(urls[invitation.id], "/odoo/action-ea_audit_core.action_my_invitations")

    def test_f082_the_footer_counts_all_of_them(self):
        for _index in range(34):
            self.note()
        data = self.ui.ea_ui_notifications()
        self.assertEqual((len(data["rows"]), data["total"]), (20, 34))
        with file_open("ea_audit_ui/static/src/xml/shell.xml") as handle:
            shell = handle.read()
        self.assertIn('t-att-href="row.url"', shell)
        self.assertNotIn('ea-note" href="#"', shell)
        self.assertIn("action_notifications", shell)

    def test_f082_the_full_list_opens_a_row_and_marks_it_read(self):
        row = self.note(kind="mission")
        action = self.Note.with_user(self.staff).browse(row.id).action_open_row()
        self.assertEqual(action["url"], "/odoo/ea.audit.engagement/%d" % self.engagement.id)
        self.assertTrue(row.read_at)
        self.assertEqual(self.env.ref("ea_audit_ui.action_notifications").res_model, "ea.audit.notification")


@tagged("post_install", "-at_install")
class TestProgressAndWords(EaAuditCase):
    def test_f080_the_bar_sits_clear_of_the_band(self):
        with file_open("ea_audit_ui/static/src/js/progress_bar.js") as handle:
            script = handle.read()
        self.assertIn("RPC:REQUEST", script)
        self.assertIn('add("ea_audit_progress"', script)
        with file_open("ea_audit_ui/static/src/scss/shell.scss") as handle:
            style = handle.read()
        bar = re.search(r"\.ea-progress \{(.*?)\n\}", style, re.S).group(1)
        self.assertIn("top: 0", bar)
        self.assertIn(".o_loading_indicator { bottom: 24px; }", style)

    def test_m14_one_french_word_for_the_level(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        self.env["ir.module.module"].search([("name", "in", ("ea_audit_core", "ea_audit_ui", "ea_audit_timesheet"))])._update_translations(["fr_FR"], overwrite=True)
        french = self.env(context=dict(self.env.context, lang="fr_FR"))
        self.assertEqual(self.env.ref("ea_audit_core.group_staff").with_env(french).name, "Assistant audit")
        session = self.env["ea.audit.ui"].with_user(self.staff).with_context(lang="fr_FR")._ea_ui_shell_session()
        self.assertEqual(session["role"], "Assistant audit")
        roles = dict(self.env["ea.audit.team.member"]._fields["team_role"]._description_selection(french))
        self.assertEqual(roles["staff"], "Assistant audit")
        for addon in ("ea_audit_ui", "ea_audit_timesheet"):
            with file_open("%s/i18n/fr.po" % addon) as handle:
                self.assertNotIn('msgid "Staff"\nmsgstr "Collaborateur"', handle.read().replace("\r\n", "\n"))
