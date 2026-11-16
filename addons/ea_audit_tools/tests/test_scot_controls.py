"""SCOTs and controls, the owner's mock-ups of 2026-11-16: the fixed frequency list and its sample
table, the freeze, the reason below the suggestion, the backfill, the grid, the documents and the
tiles taken off the Tools page."""
import base64

from odoo.tests import tagged

from .test_scot_sampling import ScotCase

GRID = {"attributes": ["a"], "rows": [{"ref": "1", "date": "", "desc": "", "results": {"a": "pass"}}]}


def b64(content):
    return base64.b64encode(content).decode()


@tagged("post_install", "-at_install")
class TestFrequencyList(ScotCase):
    def test_a_listed_frequency_is_stored_as_its_code(self):
        control = self.control.sudo()
        self.assertEqual((control.frequency_code, control.frequency), ("monthly", False))
        self.assertEqual(control.reliance, "normal")
        self.assertEqual(control.suggested_size, 2)
        self.control.update_control({"reliance": "heavy"})
        self.assertEqual(control.suggested_size, 4)

    def test_the_rules_of_the_list(self):
        with self.assertRaisesRegex(Exception, "frequency-reason-required"):
            self.scot.add_control("Autre", frequency="other", wcgws=self.wcgw)
        other = self.scot.add_control("Autre", frequency="other", frequency_other="At each closing of a site", wcgws=self.wcgw)
        self.assertFalse(other.sudo().suggested_size)
        for code in ("daily", "multiple_daily", "event"):
            with self.assertRaisesRegex(Exception, "occurrences-required"):
                self.scot.add_control("Sans nombre", frequency=code, wcgws=self.wcgw)
        event = self.scot.add_control("Avoirs", frequency="event", occurrences=38, wcgws=self.wcgw, reliance="heavy")
        self.assertEqual(event.sudo().suggested_size, 5)
        self.assertEqual(event.sudo().frequency_display, "Event-driven (each time it happens) · 38")
        automated = self.scot.add_control("Plafond", control_type="automated", frequency="daily", wcgws=self.wcgw)
        self.assertEqual(automated.sudo().suggested_size, 1)
        with self.assertRaisesRegex(Exception, "occurrences-required"):
            self.control.update_control({"frequency_code": "daily"})

    def test_the_legacy_text_is_read_and_unclear_text_asks_to_choose(self):
        legacy = self.scot.add_control("Ancien", frequency="Mensuel", wcgws=self.wcgw).sudo()
        self.assertEqual((legacy.frequency_code, legacy.frequency, legacy.frequency_effective), (False, "Mensuel", "monthly"))
        self.assertEqual(legacy.suggested_size, 2)
        unclear = self.scot.add_control("Flou", frequency="selon les besoins", wcgws=self.wcgw).sudo()
        self.assertFalse(unclear.frequency_effective)
        self.assertEqual(unclear.frequency_display, "Please choose")
        self.assertFalse(unclear.suggested_size)

    def test_the_dialog_shows_the_suggestion(self):
        wizard = self.env["ea.audit.control.wizard"].with_user(self.staff).create({
            "scot_id": self.scot.id, "name": "Rapprochement bancaire", "control_type": "manual", "frequency": "monthly",
            "reliance": "normal", "wcgw_ids": [(6, 0, self.wcgw.ids)],
        })
        self.assertIn("Suggested test: 2", wizard.suggestion)
        self.assertIn(("monthly", "Monthly   (2 · 4)"), wizard._fields["frequency"]._description_selection(wizard.env))
        wizard.reliance = "heavy"
        self.assertIn("Suggested test: 4", wizard.suggestion)
        wizard.action_add()
        added = self.scot.sudo().control_ids.filtered(lambda c: c.name == "Rapprochement bancaire")
        self.assertEqual((added.frequency_code, added.reliance), ("monthly", "heavy"))
        self.assertEqual(added.code, "C2")


@tagged("post_install", "-at_install")
class TestSizeRules(ScotCase):
    def test_a_smaller_test_than_suggested_needs_a_reason(self):
        self.select()
        self.control.update_control({"reliance": "heavy"})
        with self.assertRaisesRegex(Exception, "below-suggestion-reason-required"):
            self.control.draw_toc_sample(12, 2)
        self.control.draw_toc_sample(12, 2, "Manual, monthly → minimum 4", below_reason="Two months of a new system only")
        control = self.control.sudo()
        self.assertEqual(control.sample_size, 2)
        self.assertIn("Two months of a new system only", control.sample_note)
        self.assertIn("Two months of a new system only", control.draw_ids.rule)
        self.control.draw_toc_sample(12, 4, reason="back to the table")  # at the suggestion: no reason needed

    def test_the_size_is_frozen_once_results_exist(self):
        self.select()
        self.control.draw_toc_sample(12, 2)
        self.control.update_control({"toc_grid": GRID})
        control = self.control.sudo()
        self.assertEqual(control.frozen_size, 2)
        self.control.update_control({"reliance": "heavy", "frequency_code": "weekly"})
        self.assertEqual(control.suggested_size, 2)
        self.assertIn("2", control.suggested_rule)

    def test_a_recorded_test_freezes_too(self):
        self.select()
        self.control.record_test("Relevé de janvier", "effective")
        self.assertEqual(self.control.sudo().frozen_size, 2)
        self.control.update_control({"reliance": "heavy"})
        self.assertEqual(self.control.sudo().suggested_size, 2)


@tagged("post_install", "-at_install")
class TestBackfill(ScotCase):
    def test_only_open_files_get_a_code(self):
        open_control = self.scot.add_control("Ouvert", frequency="mensuel", wcgws=self.wcgw)
        unclear = self.scot.add_control("Flou", frequency="mensuel ou trimestriel", wcgws=self.wcgw)
        archived = self.make_engagement(year=2023)
        self.seat(archived, self.staff, "staff")
        old_scot = archived.with_user(self.staff).create_scot("Ventes 2023")
        old_control = old_scot.add_control("Archivé", frequency="mensuel")
        archived.sudo().write({"archived_at": "2026-01-01 00:00:00"})
        done = self.env["ea.audit.scot.control"]._ea_backfill_frequency_codes()
        self.assertGreaterEqual(done, 1)
        self.assertEqual(open_control.sudo().frequency_code, "monthly")
        self.assertFalse(unclear.sudo().frequency_code)
        self.env.cr.execute("SELECT frequency_code, frequency FROM ea_audit_scot_control WHERE id = %s", [old_control.id])
        self.assertEqual(self.env.cr.fetchone(), (None, "mensuel"))
        # read through the parser all the same
        self.assertEqual(old_control.sudo().frequency_effective, "monthly")
        self.assertEqual(self.env["ea.audit.scot.control"]._ea_backfill_frequency_codes(), 0)


@tagged("post_install", "-at_install")
class TestGridAndOverview(ScotCase):
    def test_the_grid_toggles_for_a_senior(self):
        grid = self.scot.with_user(self.senior).ea_grid()
        self.assertEqual(grid["links"], [[self.wcgw.id, self.control.id]])
        self.assertTrue(grid["canEdit"])
        self.assertFalse(self.scot.with_user(self.staff).ea_grid()["canEdit"])
        with self.assertRaises(Exception):
            self.scot.with_user(self.staff).ea_toggle_link(self.wcgw.id, self.control.id)
        grid = self.scot.with_user(self.senior).ea_toggle_link(self.wcgw.id, self.control.id)
        self.assertEqual(grid["links"], [])
        self.assertFalse(grid["wcgws"][0]["answered"])
        grid = self.scot.with_user(self.senior).ea_toggle_link(self.wcgw.id, self.control.id)
        self.assertEqual(grid["links"], [[self.wcgw.id, self.control.id]])
        with self.assertRaisesRegex(Exception, "not-found"):
            self.scot.with_user(self.senior).ea_toggle_link(self.wcgw.id, 0)

    def test_the_cards_and_the_totals(self):
        card = self.scot.sudo().ea_card
        self.assertEqual([step["key"] for step in card["steps"]], ["indexes", "risks", "controls", "walkthrough", "documents"])
        self.assertEqual(card["border"], "amber")
        empty = self.as_staff.create_scot("Trésorerie")
        self.assertEqual(empty.sudo().ea_card["border"], "red")
        self.assertTrue(empty.sudo().ea_card["empty"])
        totals = self.as_staff.ea_scot_totals()
        self.assertEqual((totals["scots"], totals["controls"], totals["toTest"]), (2, 1, 0))
        self.assertTrue(totals["canWrite"])
        self.assertFalse(self.as_reader.ea_scot_totals()["canWrite"])
        self.assertEqual(self.control.sudo().code, "C1")
        action = self.as_staff.action_tool_scot()
        self.assertEqual(action["views"][0][1], "kanban")

    def test_the_views_load(self):
        for xmlid in ("view_scot_kanban", "view_scot_form", "view_control_form", "view_control_wizard", "view_toc_draw_wizard"):
            view = self.env.ref("ea_audit_tools.%s" % xmlid)
            self.env[view.model].with_user(self.staff).get_view(view.id)


@tagged("post_install", "-at_install")
class TestScotDocuments(ScotCase):
    def test_upload_version_link_and_s13(self):
        as_staff = self.scot.with_user(self.staff)
        docs = as_staff.upload_document("flux.txt", b64(b"flowchart v1"), "flowchart")
        self.assertEqual([(d["name"], d["version"], d["type"]) for d in docs["live"]], [("flux.txt", 1, "flowchart")])
        docs = as_staff.upload_document("flux.txt", b64(b"flowchart v2"), "flowchart", self.control.id)
        self.assertEqual(len(docs["live"]), 1)
        self.assertEqual((docs["live"][0]["version"], docs["live"][0]["controlCode"]), (2, "C1"))
        row_id = docs["live"][0]["id"]
        docs = as_staff.set_document(row_id, "test", False)
        self.assertEqual((docs["live"][0]["type"], docs["live"][0]["controlId"]), ("test", False))
        # the same files are evidence of the walkthrough task
        item = self.item(self.engagement, "S1.3")
        rows = self.env["ea.audit.task.attachment"].sudo().search([("file_item_id", "=", item.id)])
        self.assertEqual(sorted(rows.mapped("version")), [1, 2])
        self.assertEqual(rows.scot_id, self.scot.sudo())
        self.assertEqual(self.scot.sudo().document_count, 1)

    def test_refusals_removal_and_restore(self):
        with self.assertRaisesRegex(Exception, "invalid-value"):
            self.scot.with_user(self.staff).upload_document("a.txt", b64(b"x"), "nonsense")
        with self.assertRaises(Exception):
            self.scot.with_user(self.reader).upload_document("a.txt", b64(b"x"), "policy")
        docs = self.scot.with_user(self.staff).upload_document("politique.txt", b64(b"policy"), "policy")
        row_id = docs["live"][0]["id"]
        self.assertFalse(docs["canRemove"])
        with self.assertRaises(Exception):
            self.scot.with_user(self.staff).remove_document(row_id)
        docs = self.scot.with_user(self.manager).remove_document(row_id)
        self.assertEqual((docs["live"], [d["name"] for d in docs["removed"]]), ([], ["politique.txt"]))
        docs = self.scot.with_user(self.manager).restore_document(row_id)
        self.assertEqual([d["name"] for d in docs["live"]], ["politique.txt"])
        other = self.as_staff.create_scot("Achats")
        with self.assertRaisesRegex(Exception, "scot-document-not-found"):
            other.with_user(self.manager).remove_document(row_id)
        self.assertFalse(self.env["ea.audit.task.attachment"].with_user(self.outsider).search([("scot_id", "!=", False)]))


@tagged("post_install", "-at_install")
class TestToolsPage(ScotCase):
    def test_three_tiles_are_hidden_and_their_tools_kept(self):
        action = self.as_staff.action_open_tools()
        codes = self.env["ea.audit.tool.tile"].with_user(self.staff).search(action["domain"]).mapped("code")
        for hidden in ("potential", "deficiencies", "pbc"):
            self.assertNotIn(hidden, codes)
            tile = self.env["ea.audit.tool.tile"].sudo().search([("code", "=", hidden)])
            self.assertEqual(tile.section, "retired")
            opened = tile.with_user(self.staff).with_context(ea_engagement_id=self.engagement.id).action_open_tool()
            self.assertEqual(opened["type"], "ir.actions.act_window")
        self.assertIn("scot", codes)
