import base64

from odoo.tests import tagged

from .common import ToolsCase


@tagged("post_install", "-at_install")
class TestFindingsPage(ToolsCase):
    def deficiency(self, title="Credit notes issued without approval"):
        return self.as_staff.route_finding("c1", title, severity="deficiency")["finding"]

    def page(self, actor=None):
        return (actor or self.as_staff).ea_findings_page()

    def row(self, page, finding):
        return next(f for f in page["findings"] if f["id"] == finding.id)

    def test_the_tools_open_their_pages(self):
        action = self.as_staff.action_tool_findings()
        self.assertEqual((action["type"], action["tag"]), ("ir.actions.client", "ea_audit_tools.findings_page"))
        action = self.as_staff.action_tool_sad()
        self.assertEqual((action["type"], action["tag"]), ("ir.actions.client", "ea_audit_tools.sad_page"))
        self.assertCode("not-on-this-engagement", self.as_outsider.action_tool_findings)
        self.assertCode("not-on-this-engagement", self.as_outsider.ea_sad_page)

    def test_a_finding_moves_through_the_stages(self):
        finding = self.deficiency()
        page = self.page()
        self.assertEqual(self.row(page, finding)["stage"], "raised")
        self.assertEqual(page["summary"]["stages"]["raised"], 1)
        page = self.as_staff.ea_findings_page_evaluate(finding.id, {"likelihood": "probable"})
        self.assertEqual(self.row(page, finding)["stage"], "assessed")
        page = self.as_staff.ea_findings_page_evaluate(finding.id, {"magnitude": "material"})
        row = self.row(page, finding)
        self.assertEqual(row["evaluation"]["likelihood"], "probable")  # the first choice is kept
        self.assertEqual(row["evaluation"]["suggested"], "significant_deficiency")
        self.assertEqual(page["summary"]["waiting"], 1)
        page = self.as_staff.ea_findings_page_save(finding.id, {
            "impact": "Revenue could be reduced without anyone noticing.", "management_response": "Agreed.",
        })
        row = self.row(page, finding)
        self.assertEqual((row["stage"], row["impact"]), ("discussed", "Revenue could be reduced without anyone noticing."))
        self.assertCode("recipient-required", self.as_staff.ea_findings_page_evaluate, finding.id, {"communicated_on": "2026-11-04"})
        self.as_staff.ea_findings_page_evaluate(finding.id, {"recipient": "CFO"})
        page = self.as_staff.ea_findings_page_evaluate(finding.id, {"communicated_on": "2026-11-04"})
        self.assertEqual(self.row(page, finding)["stage"], "reported")
        page = self.as_staff.ea_findings_page_clear(finding.id, "Approval workflow in place.")
        self.assertEqual(self.row(page, finding)["stage"], "closed")
        self.assertEqual(page["summary"]["closed"], 1)

    def test_the_page_keeps_the_rules(self):
        finding = self.deficiency()
        self.assertCode("invalid-field", self.as_staff.ea_findings_page_save, finding.id, {"title": "x"})
        self.assertCode("invalid-field", self.as_staff.ea_findings_page_evaluate, finding.id, {"finding_id": 1})
        self.assertCode("read-only-role", self.as_reader.ea_findings_page_save, finding.id, {"detail": "x"})
        self.assertTrue(self.page(self.as_reader)["readonly"])
        self.assertCode("response-required", self.as_staff.ea_findings_page_clear, finding.id, " ")
        self.assertCode("forbidden", self.as_staff.ea_findings_page_open, "unlink")
        self.assertCode("not-found", self.as_staff.ea_findings_page_save, 999999, {"detail": "x"})

    def test_documents_are_evidence_files_of_the_task(self):
        finding = self.deficiency()
        content = base64.b64encode(b"credit notes").decode()
        self.as_staff.ea_findings_page_upload(finding.id, "credit-notes.txt", content)
        docs = self.as_staff.ea_findings_page_documents(finding.id)
        self.assertEqual([d["name"] for d in docs], ["credit-notes.txt"])
        row = self.env["ea.audit.task.attachment"].sudo().browse(docs[0]["id"])
        self.assertEqual(row.finding_id, finding.sudo())
        self.assertIn(row.file_item_id.code, ("C5.11", "C1.1"))
        self.assertEqual(self.row(self.page(), finding)["docs"], 1)
        # the same name on another finding of the same task is refused, not mixed in
        second = self.deficiency("Shared administrator password")
        self.assertCode("name-taken", self.as_staff.ea_findings_page_upload, second.id, "credit-notes.txt", content)
        self.assertCode("forbidden", self.as_staff.ea_findings_page_remove, finding.id, docs[0]["id"])
        self.as_manager.ea_findings_page_remove(finding.id, docs[0]["id"])
        self.assertFalse(self.as_staff.ea_findings_page_documents(finding.id))
        self.assertCode("read-only-role", self.as_reader.ea_findings_page_upload, finding.id, "a.txt", content)

    def test_a_misstatement_from_another_record_lands_on_the_sad(self):
        item = self.item(self.engagement, "C1.1")
        finding = self.as_staff.ea_raise_finding(
            "ea.audit.file.item", item.id, "Unsupported year-end accrual", amount=125000, finding_type="misstatement",
        )
        self.assertEqual((finding.route, finding.sudo().source_model, finding.sudo().source_id), ("b5", "ea.audit.file.item", item.id))
        self.assertEqual(finding.sudo().file_item_id, item)
        self.assertEqual(finding.sudo().source_label, "C1.1")
        sad = self.as_staff.ea_sad_page()
        row = sad["rows"]["uncorrected"][0]
        self.assertEqual((row["source"], row["sourceFindingId"]), (finding.reference, finding.id))
        page_row = self.row(self.page(), finding)
        self.assertEqual((page_row["sad"], page_row["stage"]), (row["no"], "assessed"))
        self.assertEqual(self.page()["summary"]["linked"], 1)
        deficiency = self.as_staff.ea_raise_finding("ea.audit.file.item", item.id, "No review", finding_type="deficiency")
        self.assertEqual((deficiency.route, deficiency.severity), ("c1", "deficiency"))
        self.assertCode("invalid-value", self.as_staff.ea_raise_finding, "ea.audit.file.item", item.id, "x", finding_type="other")
        self.assertCode("not-found", self.as_staff.ea_raise_finding, "res.partner", 1, "x")
        self.assertCode("read-only-role", self.as_reader.ea_raise_finding, "ea.audit.file.item", item.id, "x", amount=5)


@tagged("post_install", "-at_install")
class TestSadPage(ToolsCase):
    def entry(self, **vals):
        values = {
            "engagement_id": self.engagement.id, "finding": "Cut-off", "dr_account": "411000", "dr_amount": 1000,
            "cr_account": "701000", "cr_amount": 1000,
        }
        values.update(vals)
        return self.env["ea.audit.sad.entry"].with_user(self.staff).create(values)

    def test_the_grid_the_totals_and_the_bar(self):
        self.approve()
        trivial = self.engagement.sudo()._ea_materiality_dict()["trivial"]
        first = self.entry(dr_amount=trivial * 10, cr_amount=trivial * 10)
        self.entry(finding="Stock count", dr_account="603100", cr_account="321100", dr_amount=trivial * 4, cr_amount=trivial * 4)
        self.entry(finding="Rounding", dr_amount=trivial / 2, cr_amount=trivial / 2)
        page = self.as_staff.ea_sad_page()
        self.assertEqual(len(page["rows"]["uncorrected"]), 2)
        self.assertEqual(len(page["rows"]["trivial"]), 1)
        self.assertEqual(page["rows"]["uncorrected"][0]["no"], "AD-01")
        self.assertEqual(page["toPost"], 3)
        self.assertTrue(page["bar"])
        page = self.as_staff.ea_sad_post_all()
        self.assertEqual(page["toPost"], 0)
        self.assertTrue(first.sudo().misstatement_id)
        page = self.as_staff.ea_sad_page_entry_save(first.id, {"corrected": True})
        self.assertEqual(len(page["rows"]["corrected"]), 1)
        self.assertTrue(first.sudo().misstatement_id.corrected)  # a posted row re-posts
        self.assertCode("invalid-field", self.as_staff.ea_sad_page_entry_save, first.id, {"posted": False})

    def test_the_side_topics_save_through_the_meta(self):
        page = self.as_staff.ea_sad_page()
        self.assertEqual(page["unanswered"], 5)
        page = self.as_staff.ea_sad_page_meta_save({"tq_1": "no", "tq_1c": "Nothing sensitive"})
        self.assertEqual(page["unanswered"], 4)
        page = self.as_staff.ea_sad_page_meta_save({"concl_text": "Not material.", "tax_rate": 30})
        self.assertEqual((page["meta"]["concl_text"], page["meta"]["tax_rate"]), ("Not material.", 30))
        self.assertCode("invalid-value", self.as_staff.ea_sad_page_meta_save, {"tax_rate": 120})
        self.assertCode("invalid-field", self.as_staff.ea_sad_page_meta_save, {"engagement_id": 1})
        self.assertCode("read-only-role", self.as_reader.ea_sad_page_meta_save, {"tq_2": "yes"})
        self.engagement.sudo().phase = "archived"
        self.assertCode("archived", self.as_staff.ea_sad_page_meta_save, {"tq_2": "yes"})
        self.assertTrue(self.as_staff.ea_sad_page()["archived"])

    def test_the_page_opens_a_difference_in_its_form(self):
        entry = self.entry()
        action = self.as_staff.ea_sad_page_open("entry", entry.id)
        self.assertEqual((action["res_model"], action["res_id"], action["target"]), ("ea.audit.sad.entry", entry.id, "new"))
        self.assertEqual(self.as_staff.ea_sad_page_open("new")["context"]["default_engagement_id"], self.engagement.id)
        self.assertCode("forbidden", self.as_staff.ea_sad_page_open, "unlink")


@tagged("post_install", "-at_install")
class TestPagesInFrench(ToolsCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("fr_FR")
        cls.env["ir.module.module"].search([("name", "=", "ea_audit_tools")])._update_translations(["fr_FR"], overwrite=True)

    def test_the_pages_speak_french(self):
        self.as_staff.route_finding("c1", "Pas de revue", severity="deficiency")
        french = self.engagement.with_user(self.staff).with_context(lang="fr_FR")
        page = french.ea_findings_page()
        self.assertEqual(page["findings"][0]["stageLabel"], "Pas encore évalué")
        self.assertIn("sur 1 clôturés", page["progressText"])
        sad = french.ea_sad_page()
        self.assertEqual(sad["statusText"], "Non évaluable : le seuil n'est pas approuvé")
        self.assertTrue(sad["afterTaxLabel"].startswith("Après impôt à 33"))
        label = self.env["ea.audit.finding"].with_context(lang="fr_FR").fields_get(["impact"])["impact"]["string"]
        self.assertEqual(label, "Pourquoi c'est important")
