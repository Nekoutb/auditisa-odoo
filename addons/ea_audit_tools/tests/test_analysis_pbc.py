import base64
import io
import zipfile

from openpyxl import load_workbook

from odoo.tests import tagged

from odoo.addons.ea_audit_tools.services.document_requests import PARAM

from .common import ToolsCase

PDF = b"%PDF-1.4 test"


def switch_document_requests(env, on):
    """The firm's switch (owner ruling 2026-11-17: off for now, back later)."""
    env["ir.config_parameter"].sudo().set_param(PARAM, "True" if on else "False")


@tagged("post_install", "-at_install")
class TestPbc(ToolsCase):
    """Everything as before once the firm switches document requests on."""

    def setUp(self):
        super().setUp()
        switch_document_requests(self.env, True)

    def item(self, title="Relevés bancaires"):
        return self.as_staff.add_pbc_item(title, "Tous les comptes")

    def task(self):
        return self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.engagement.id)], limit=1)

    def test_a_request_is_on_the_trail(self):
        item = self.item()
        self.assertEqual(item.sudo().status, "requested")
        with self.assertRaisesRegex(Exception, "fields-required"):
            self.as_staff.add_pbc_item(" ")
        with self.assertRaisesRegex(Exception, "read-only-role"):
            self.as_reader.add_pbc_item("x")
        self.assertFalse(self.env["ea.audit.pbc.item"].with_user(self.outsider).search([]))

    def test_a_chase_needs_someone_to_receive_it(self):
        item = self.item()
        with self.assertRaisesRegex(Exception, "no-portal-contact"):
            item.chase()
        self.engagement.with_user(self.manager).add_portal_contact("Paul", "paul@client.example.com")
        item.chase()
        self.assertEqual(item.sudo().chase_count, 1)
        item.upload_pbc("releves.pdf", PDF)
        with self.assertRaisesRegex(Exception, "wrong-status"):
            item.chase()

    def test_contact_refusals(self):
        with self.assertRaises(Exception):
            self.as_staff.add_portal_contact("Paul", "p@client.example.com")
        manager = self.engagement.with_user(self.manager)
        manager.add_portal_contact("Paul", "p@client.example.com")
        with self.assertRaisesRegex(Exception, "email-taken"):
            manager.add_portal_contact("Paul", "P@client.example.com")
        with self.assertRaisesRegex(Exception, "fields-required"):
            manager.add_portal_contact("", "x@client.example.com")

    def test_upload_safety(self):
        item = self.item()
        with self.assertRaisesRegex(Exception, "file-type"):
            item.upload_pbc("virus.exe", b"MZ")
        with self.assertRaisesRegex(Exception, "file-type"):
            item.upload_pbc("faux.pdf", b"not a pdf")
        with self.assertRaisesRegex(Exception, "empty-file"):
            item.upload_pbc("vide.pdf", b"")
        item.upload_pbc("../../bon.pdf", PDF)
        self.assertEqual(item.sudo().filename, "bon.pdf")
        self.assertEqual(item.sudo().mime, "application/pdf")

    def test_accept_files_on_a_task(self):
        item = self.item()
        task = self.task()
        as_senior = item.with_user(self.senior)
        with self.assertRaisesRegex(Exception, "wrong-status"):
            as_senior.accept(task)
        item.upload_pbc("bon.pdf", PDF)
        with self.assertRaisesRegex(Exception, "attach-required"):
            as_senior.accept(self.env["ea.audit.file.item"])
        with self.assertRaisesRegex(Exception, "forbidden"):
            item.accept(task)
        filed = as_senior.accept(task)
        self.assertEqual(item.sudo().status, "accepted")
        self.assertEqual(item.sudo().file_item_id, task.sudo())
        if "document_id" in item._fields:  # ea_audit_portal files it as a versioned document
            self.assertEqual(filed.sudo().current_version_id.attachment_id.raw, PDF)
        else:
            self.assertEqual(filed.res_id, task.id)
            self.assertEqual(base64.b64decode(filed.datas), PDF)
        with self.assertRaisesRegex(Exception, "wrong-status"):
            as_senior.attach_accepted(task)

    def test_age_turns_red_after_fourteen_days(self):
        item = self.item()
        self.assertFalse(item.sudo().overdue)
        self.env.cr.execute("UPDATE ea_audit_pbc_item SET create_date = now() - interval '20 days' WHERE id = %s", [item.id])
        item.invalidate_recordset()
        self.assertGreaterEqual(item.sudo().age_days, 19)
        self.assertTrue(item.sudo().overdue)

    def test_excel(self):
        self.item()
        name, content = self.as_staff.ea_export_xlsx("pbc")
        self.assertIn("pbc", name)
        self.as_staff.ea_import_xlsx("pbc", "p.xlsx", content)
        self.assertEqual(self.env["ea.audit.pbc.item"].sudo().search_count([("engagement_id", "=", self.engagement.id)]), 2)


@tagged("post_install", "-at_install")
class TestFinancialAnalysis(ToolsCase):
    def test_no_tb_no_rows(self):
        self.assertIsNone(self.as_staff.financial_analysis_view())

    def test_ratios_and_commentary_outlive_the_rows(self):
        self.import_tb()
        self.as_staff.action_tool_financial()
        Ratio = self.env["ea.audit.fa.ratio"]
        current = Ratio.with_user(self.staff).search([("engagement_id", "=", self.engagement.id), ("key", "=", "current")])
        self.assertTrue(current.has_current)
        current.write({"commentary": "Liquidité stable"})
        self.as_staff.action_tool_financial()
        again = Ratio.with_user(self.staff).search([("engagement_id", "=", self.engagement.id), ("key", "=", "current")])
        self.assertEqual(again.commentary, "Liquidité stable")
        with self.assertRaisesRegex(Exception, "read-only-role"):
            again.with_user(self.reader).write({"commentary": "non"})
        with self.assertRaisesRegex(Exception, "invalid-field"):
            again.write({"current": 3})
        name, _content = self.as_staff.ea_export_xlsx("financial")
        self.assertIn("financial", name)
        self.assertFalse(Ratio.with_user(self.outsider).search([]))


@tagged("post_install", "-at_install")
class TestAnalytics(ToolsCase):
    def test_review_flags_above_performance(self):
        self.approve(overall_pct=0.5)
        review = self.as_staff.analytical_review()
        self.assertTrue(review["hasTb"])
        self.assertFalse(review["hasPrior"])
        self.assertTrue(any(line["flagged"] for line in review["lines"]))
        by_key = {row["key"]: row for row in review["ratios"]}
        self.assertEqual(by_key["revenue"]["current"], 2000)
        self.assertEqual(by_key["purchases_to_revenue"]["current"], 100)
        self.assertIn("table", str(self.engagement.with_user(self.staff).analytics_html))

    def test_the_board_opens(self):
        self.import_tb()
        self.assertEqual(self.as_staff.action_tool_analytics()["res_model"], "ea.audit.engagement")
        self.as_staff.action_open_potential_wizard()


@tagged("post_install", "-at_install")
class TestOverridesAndPotential(ToolsCase):
    def test_overrides_screen(self):
        self.as_staff.save_lead_index_override("411", "C")
        self.as_staff.add_grouping_override("prefix", "99", "E4.1", "Compte propre au client")
        board = self.engagement.with_user(self.staff)
        self.assertEqual(board.lead_override_ids.mapped("index_code"), ["C"])
        self.assertEqual(board.grouping_override_ids.mapped("section_code"), ["E4.1"])
        self.assertTrue(board.action_tool_overrides())
        outsider = self.engagement.with_user(self.outsider)
        with self.assertRaisesRegex(Exception, "not-on-this-engagement"):
            outsider.action_tool_overrides()

    def test_wizard_routes_to_the_guarded_methods(self):
        wizard = self.env["ea.audit.override.wizard"].with_user(self.staff).create({
            "engagement_id": self.engagement.id, "kind": "section", "account_prefix": "bad!", "section_code": "E4.1", "rationale": "x",
        })
        with self.assertRaisesRegex(Exception, "invalid-prefix"):
            wizard.action_add()

    def test_potential_risks_screen(self):
        wizard = self.env["ea.audit.potential.wizard"].with_user(self.staff).create({
            "engagement_id": self.engagement.id, "description": "Hausse anormale", "source_code": "P3.2",
        })
        wizard.action_raise()
        records = self.env["ea.audit.potential.risk"].with_user(self.staff).search([("engagement_id", "=", self.engagement.id)])
        self.assertEqual(len(records), 1)
        tile = self.env.ref("ea_audit_tools.tile_potential").with_user(self.staff)
        self.assertEqual(tile.with_context(ea_engagement_id=self.engagement.id).action_open_tool()["res_model"], "ea.audit.potential.risk")


@tagged("post_install", "-at_install")
class TestTemplates(ToolsCase):
    def test_every_template_downloads_as_a_workbook(self):
        self.as_staff.action_tool_templates()
        templates = self.env["ea.audit.wp.template"].with_user(self.staff).search([])
        self.assertTrue(templates.filtered(lambda t: t.key == "sub-trade-receivables"))
        self.assertTrue(templates.filtered(lambda t: t.key.startswith("substantive-generic-")))
        for template in templates:
            name, content = self.as_staff.ea_export_xlsx("wp_%d" % template.id)
            if name.endswith(".docx"):
                self.assertIn("word/document.xml", zipfile.ZipFile(io.BytesIO(content)).namelist(), name)
                continue
            self.assertTrue(name.endswith(".xlsx"), name)
            self.assertTrue(load_workbook(io.BytesIO(content)).worksheets, name)

    def test_the_c31_letter_is_listed_and_follows_the_report_language(self):
        """C3.1: the sample representation letter, English or French with the engagement's report language."""
        self.as_staff.action_tool_templates()
        template = self.env["ea.audit.wp.template"].with_user(self.staff).search([("default_for", "=", "C3.1")])
        self.assertEqual(template.key, "c31-rep-letter")
        self.engagement.sudo().report_language = "en"
        name, english = self.as_staff.ea_export_xlsx("wp_%d" % template.id)
        self.assertEqual(name, "C3.1 Management representation letter (template).docx")
        self.engagement.sudo().report_language = "fr"
        name, french = self.as_staff.ea_export_xlsx("wp_%d" % template.id)
        self.assertEqual(name, "C3.1 Lettre d'affirmation de la direction (modele).docx")
        self.assertNotEqual(english, french)
        for content in (english, french):
            self.assertIn("word/document.xml", zipfile.ZipFile(io.BytesIO(content)).namelist())

    def test_the_c31_paper_offers_the_letter(self):
        paper = self.item(self.engagement, "C3.1")._ea_paper()
        link = paper.with_user(self.staff).get_payload()["tool_links"][-1]
        template = self.env.ref("ea_audit_tools.wp_c31_rep_letter")
        self.assertEqual(link["en"], "Template: management representation letter (Word)")
        self.assertIn("File the signed copy on this task.", link["note_en"])
        self.assertTrue(link["note_fr"])
        self.assertEqual(link["action"]["url"], "/ea_audit_tools/export/wp_%d/%d" % (template.id, self.engagement.id))
        other = self.item(self.engagement, "P3.1")._ea_paper().with_user(self.staff).get_payload()["tool_links"]
        self.assertFalse([entry for entry in other if entry.get("plain")])

    def test_assign_copies_to_the_task(self):
        template = self.env.ref("ea_audit_tools.wp_sub_trade_receivables")
        task = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.engagement.id)], limit=1)
        attachment = self.as_staff.assign_template(template, task)
        self.assertEqual(attachment.res_id, task.id)
        with self.assertRaisesRegex(Exception, "read-only-role"):
            self.as_reader.assign_template(template, task)

    def test_an_outsider_downloads_nothing(self):
        template = self.env.ref("ea_audit_tools.wp_sub_trade_receivables")
        with self.assertRaisesRegex(Exception, "not-on-this-engagement"):
            self.as_outsider.ea_export_xlsx("wp_%d" % template.id)
        with self.assertRaisesRegex(Exception, "not-found"):
            self.as_staff.ea_export_xlsx("wp_999999")


@tagged("post_install", "-at_install")
class TestDocumentRequestsSwitchedOff(ToolsCase):
    """Owner ruling 2026-11-17: document requests off for now. Nothing is deleted; every way in is
    closed, and a request already made stays as it was."""

    def setUp(self):
        super().setUp()
        switch_document_requests(self.env, True)
        self.kept = self.as_staff.add_pbc_item("Relevés bancaires", "Tous les comptes")
        switch_document_requests(self.env, False)
        self.engagement.invalidate_recordset(["document_requests_enabled"])

    def test_off_by_default(self):
        self.env["ir.config_parameter"].sudo().search([("key", "=", PARAM)]).unlink()
        self.engagement.invalidate_recordset(["document_requests_enabled"])
        self.assertFalse(self.as_staff.document_requests_enabled)
        self.assertCode("document-requests-off", self.as_staff.add_pbc_item, "Grand livre")

    def test_every_way_in_is_refused(self):
        self.assertFalse(self.as_staff.document_requests_enabled)
        self.assertCode("document-requests-off", self.as_staff.add_pbc_item, "Grand livre")
        self.assertCode("document-requests-off", self.as_staff.action_tool_pbc)
        self.assertCode("document-requests-off", self.engagement.with_user(self.manager).add_portal_contact, "Paul", "paul@client.example.com")
        item = self.kept.with_user(self.staff)
        self.assertCode("document-requests-off", item.chase)
        self.assertCode("document-requests-off", item.upload_pbc, "bon.pdf", PDF)
        task = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.engagement.id)], limit=1)
        self.assertCode("document-requests-off", item.with_user(self.senior).accept, task)
        self.assertCode("document-requests-off", item.action_open_upload)
        self.assertCode("document-requests-off", item.with_context(ea_engagement_id=self.engagement.id).action_list_add_pbc)
        name, content = self.as_staff.ea_export_xlsx("pbc")  # reading what was asked stays open
        self.assertCode("document-requests-off", self.as_staff.ea_import_xlsx, "pbc", name, content)
        tile = self.env.ref("ea_audit_tools.tile_pbc").with_user(self.staff).with_context(ea_engagement_id=self.engagement.id)
        self.assertCode("document-requests-off", tile.action_open_tool)

    def test_the_request_already_made_is_kept(self):
        row = self.kept.sudo()
        self.assertEqual((row.title, row.note, row.status), ("Relevés bancaires", "Tous les comptes", "requested"))
        self.assertEqual(self.env["ea.audit.pbc.item"].sudo().search_count([("engagement_id", "=", self.engagement.id)]), 1)

    def test_switching_on_again_brings_it_back(self):
        switch_document_requests(self.env, True)
        self.engagement.invalidate_recordset(["document_requests_enabled"])
        self.assertTrue(self.as_staff.document_requests_enabled)
        self.assertEqual(self.as_staff.action_tool_pbc()["type"], "ir.actions.act_window")
        self.as_staff.add_pbc_item("Grand livre")
        self.assertEqual(self.env["ea.audit.pbc.item"].sudo().search_count([("engagement_id", "=", self.engagement.id)]), 2)
