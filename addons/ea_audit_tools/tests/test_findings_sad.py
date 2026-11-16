import io

from openpyxl import load_workbook

from odoo.tests import tagged

from .common import ToolsCase


@tagged("post_install", "-at_install")
class TestFindings(ToolsCase):
    def deficiency(self, actor=None):
        return (actor or self.as_staff).route_finding("c1", "Purchases not segregated", severity="deficiency")["finding"]

    def test_routing_codes(self):
        self.assertCode("title-required", self.as_staff.route_finding, "b4", " ")
        self.assertCode("invalid-severity", self.as_staff.route_finding, "c1", "x")
        self.assertCode("invalid-severity", self.as_staff.route_finding, "c1", "x", severity="other")
        self.assertCode("amount-required", self.as_staff.route_finding, "b5", "x", amount=0)
        self.assertCode("invalid-value", self.as_staff.route_finding, "nowhere", "x")
        self.assertEqual(self.as_staff.route_finding("b4", "A matter")["destination"], "b4")

    def test_numbers_run_per_engagement(self):
        first = self.deficiency()
        second = self.as_staff.route_finding("b4", "Other")["finding"]
        self.assertEqual((first.reference, second.reference), ("F-01", "F-02"))

    def test_guards(self):
        self.assertCode("read-only-role", self.deficiency, actor=self.as_reader)
        self.assertCode("not-on-this-engagement", self.deficiency, actor=self.as_outsider)
        self.assertCode("eqr-read-only", self.deficiency, actor=self.as_eqr)
        self.engagement.sudo().phase = "archived"
        self.assertCode("archived", self.deficiency)

    def test_a_trivial_misstatement_needs_the_confirmation(self):
        self.approve()  # trivial 6 (5 % of 112)
        route = self.as_staff.route_finding
        self.assertCode("trivial-confirm-required", route, "b5", "Rounding", amount=5)
        logged = route("b5", "Rounding", amount=5, trivial_confirmed=True)
        self.assertEqual(logged["destination"], "b5-trivial")
        self.assertTrue(logged["finding"].sudo().misstatement_id.trivial)
        self.assertEqual(route("b5", "Cut-off", amount=7)["destination"], "b5")

    def test_b5_evaluates_uncorrected_against_umt(self):
        self.approve()  # overall 112, perf 84, UMT 28
        self.as_staff.route_finding("b5", "A", amount=20)
        second = self.as_staff.route_finding("b5", "B", amount=10)["finding"].sudo().misstatement_id
        self.as_staff.route_finding("b5", "C", amount=1, trivial_confirmed=True)
        result = self.engagement.sudo()._ea_evaluate_b5()
        self.assertEqual(result["uncorrectedTotal"], 30)
        self.assertEqual(result["finalMateriality"], 28)
        self.assertTrue(result["exceedsMateriality"])
        self.assertEqual(result["trivialCount"], 1)
        second.with_user(self.staff).write({"corrected": True})
        result = self.engagement.sudo()._ea_evaluate_b5()
        self.assertEqual((result["uncorrectedTotal"], result["correctedTotal"]), (20, 10))
        self.assertFalse(result["exceedsMateriality"])
        self.assertCode("invalid-field", second.with_user(self.staff).write, {"amount": 1})

    def test_b5_is_not_evaluable_without_approved_materiality(self):
        self.as_staff.route_finding("b5", "A", amount=20)
        self.assertIsNone(self.engagement.sudo()._ea_evaluate_b5()["exceedsMateriality"])

    def test_clearing(self):
        finding = self.deficiency()
        self.assertCode("response-required", finding.clear, " ")
        finding.clear("Remediated in November")
        self.assertEqual(finding.sudo().status, "cleared")
        self.assertEqual(finding.sudo().cleared_by_id, self.staff)
        self.assertCode("not-found", finding.clear, "again")

    def test_revising_the_approach_adds_a_risk_for_the_partner(self):
        result = self.as_staff.route_finding("revise", "New fraud indicator", significant=True, file_item=self.item(self.engagement, "E4.1"))
        self.assertEqual(result["destination"], "risk")
        self.assertTrue(result["risk"].sudo().added_after_planning)
        self.assertEqual(result["risk"].sudo().section_link_ids.file_item_id.code, "E4.1")

    def test_a_paper_of_another_file_is_refused(self):
        other = self.make_engagement(year=2023)
        self.assertCode("not-found", self.as_staff.route_finding, "b4", "x", file_item=self.item(other, "E4.1"))

    def test_isa_265_evaluation_writes_the_grade_back(self):
        finding = self.deficiency()
        finding.save_deficiency_evaluation(
            "significant_deficiency", likelihood="probable", magnitude="material", accounts_assertions="N: C, E",
        )
        as_root = finding.sudo()
        self.assertEqual(as_root.severity, "significant_deficiency")
        self.assertEqual(as_root.suggested_severity, "significant_deficiency")
        self.assertEqual(self.engagement.sudo()._ea_uncommunicated_significant_count(), 1)
        finding.save_deficiency_evaluation("significant_deficiency", communicated_on="2026-01-15", recipient="Audit committee")
        self.assertEqual(self.engagement.sudo()._ea_uncommunicated_significant_count(), 0)

    def test_isa_265_codes(self):
        finding = self.deficiency()
        save = finding.save_deficiency_evaluation
        self.assertCode("invalid-severity", save, "other")
        self.assertCode("invalid-severity-factor", save, "deficiency", likelihood="never")
        self.assertCode("invalid-severity-factor", save, "deficiency", magnitude="huge")
        self.assertCode("invalid-date", save, "deficiency", communicated_on="15/01/2026")
        self.assertCode("recipient-required", save, "deficiency", communicated_on="2026-01-15", recipient=" ")
        self.assertCode("read-only-role", finding.with_user(self.reader).save_deficiency_evaluation, "deficiency")
        self.assertCode("eqr-read-only", finding.with_user(self.eqr).save_deficiency_evaluation, "deficiency")
        matter = self.as_staff.route_finding("b4", "A matter")["finding"]
        self.assertCode("not-found", matter.save_deficiency_evaluation, "deficiency")
        self.assertCode("related-finding-unknown", save, "deficiency", related_ids=[matter.id])
        related = self.deficiency()
        save("deficiency", related_ids=[related.id, finding.id])
        self.assertEqual(finding.sudo().evaluation_id.related_finding_ids, related.sudo())

    def test_a_graded_significant_with_no_evaluation_counts_as_uncommunicated(self):
        self.as_staff.route_finding("c1", "Grave", severity="significant_deficiency")
        self.assertEqual(self.engagement.sudo()._ea_uncommunicated_significant_count(), 1)

    def test_the_cards(self):
        self.approve()
        self.as_staff.route_finding("c1", "Grave", severity="significant_deficiency")
        self.as_staff.route_finding("b5", "A", amount=20)
        board = self.engagement.with_user(self.staff)
        board.invalidate_recordset()
        self.assertEqual(board.b5_uncorrected_label, "20 FCFA")
        self.assertEqual(board.finding_significant_count, 1)
        self.assertEqual(board.finding_uncommunicated_count, 1)
        self.assertEqual(board.finding_total_count, 2)

    def test_export(self):
        self.deficiency()
        _filename, content = self.as_reader.ea_export_xlsx("findings")
        sheet = load_workbook(io.BytesIO(content)).active
        self.assertEqual(sheet.cell(2, 1).value, "F-01")


@tagged("post_install", "-at_install")
class TestSad(ToolsCase):
    def entry(self, actor=None, **vals):
        values = {
            "engagement_id": self.engagement.id, "finding": "Cut-off", "dr_account": "411000", "dr_amount": 100,
            "cr_account": "701000", "cr_amount": 100,
        }
        values.update(vals)
        return self.env["ea.audit.sad.entry"].with_user(actor or self.staff).create(values)

    def test_captions_are_suggested_and_overridable(self):
        entry = self.entry()
        self.assertEqual(entry.dr_caption_effective, "current_asset")
        self.assertEqual(entry.cr_caption_effective, "income")
        entry.write({"cr_caption": "expense"})
        self.assertEqual(entry.cr_caption_effective, "expense")

    def test_guards_and_field_limits(self):
        self.assertCode("read-only-role", self.entry, actor=self.reader)
        self.assertCode("not-on-this-engagement", self.entry, actor=self.outsider)
        self.assertCode("eqr-read-only", self.entry, actor=self.eqr)
        self.assertCode("invalid-field", self.entry, posted=True)
        entry = self.entry()
        self.assertCode("invalid-field", entry.write, {"posted": True})
        self.assertCode("amount-required", self.entry, dr_account=False, dr_amount=0, cr_account=False, cr_amount=0)

    def test_post_upserts_the_schedule_with_the_magnitude(self):
        self.approve()
        entry = self.entry(dr_amount=100, cr_amount=90)
        entry.action_post()
        item = entry.sudo().misstatement_id
        self.assertEqual(item.amount, 100)
        self.assertTrue(item.accounts.startswith("Dr 411000 ("))
        self.assertIn(" / Cr 701000 (", item.accounts)
        self.assertFalse(item.trivial)
        self.assertTrue(entry.posted)
        self.assertFalse(entry.stale)
        entry.write({"dr_amount": 150})
        self.assertEqual(entry.sudo().misstatement_id.amount, 150)
        self.assertEqual(len(self.env["ea.audit.misstatement"].sudo().search([("engagement_id", "=", self.engagement.id)])), 1)

    def test_a_row_from_the_b5_route_stands_on_the_sad_and_edits_in_place(self):
        result = self.as_staff.route_finding("b5", "Projection", amount=500, mtype="projected")
        entry = self.env["ea.audit.sad.entry"].with_user(self.staff).search([("misstatement_id", "=", result["finding"].sudo().misstatement_id.id)])
        self.assertTrue(entry.register_only)
        self.assertEqual(entry.dr_caption_effective, "expense")
        self.assertCode("invalid-field", entry.write, {"dr_amount": 1})
        entry.write({"corrected": True})
        entry.action_post()
        self.assertTrue(entry.sudo().misstatement_id.corrected)
        self.assertCode("forbidden", entry.unlink)

    def test_a_draft_entry_can_go_and_a_posted_one_cannot(self):
        draft = self.entry()
        draft.unlink()
        posted = self.entry()
        posted.action_post()
        self.assertCode("forbidden", posted.unlink)

    def test_conclusion_and_tax_rate(self):
        meta = self.engagement.sudo()._ea_sad_meta().with_user(self.staff)
        self.assertCode("invalid-value", meta.write, {"tax_rate": 120})
        self.assertCode("invalid-field", meta.write, {"engagement_id": 1})
        meta.write({"tax_rate": 30, "tq_1": "yes", "tq_1c": "Close to covenant"})
        self.assertCode("read-only-role", self.as_reader.save_sad_conclusion, "x")
        self.as_staff.save_sad_conclusion("The uncorrected differences are not material.")
        self.assertEqual(meta.concl_text, "The uncorrected differences are not material.")

    def test_the_tabs_rows_are_saved_through_the_form(self):
        meta = self.engagement.sudo()._ea_sad_meta().with_user(self.staff)
        meta.write({
            "cf_row_ids": [(0, 0, {"no": "1", "line": "Operating cash", "operating": 50})],
            "disc_row_ids": [(0, 0, {"no": "1", "description": "Missing note", "corrected": True})],
        })
        self.assertEqual(meta.cf_row_ids.engagement_id, self.engagement)
        self.assertEqual(meta.disc_row_ids.description, "Missing note")
        self.assertCode("forbidden", meta.cf_row_ids[0].write, {"no": "2"})

    def test_workbook_has_six_tabs_and_the_screens_arithmetic(self):
        self.approve()  # trivial 6
        self.entry(dr_amount=100, cr_amount=100)
        self.entry(finding="Tiny", dr_amount=1, cr_amount=1)
        self.entry(finding="Fixed", dr_amount=50, cr_amount=50, corrected=True, rationale="Booked")
        self.entry(finding="Move", mtype="classification", dr_amount=30, cr_amount=30)
        meta = self.engagement.sudo()._ea_sad_meta()
        meta.write({"tax_rate": 33, "concl_text": "Below UMT.", "tq_3": "no"})
        filename, content = self.as_reader.ea_export_xlsx("sad")
        self.assertTrue(filename.startswith("SAD-Governance_SA-2025-12-31"))
        book = load_workbook(io.BytesIO(content))
        self.assertEqual(book.sheetnames, [
            "SAD uncorrected", "SAD corrected", "SAD conclusion", "Reclassification missts", "Cash flow missts", "Missts in disclosures",
        ])
        uncorrected = book["SAD uncorrected"]
        values = [[cell.value for cell in row] for row in uncorrected.iter_rows()]
        total = next(row for row in values if row[0] == "Total")
        self.assertEqual(total[3], 100)  # Dr 411 current asset
        self.assertEqual(total[8], -100)  # Cr 701 income statement
        self.assertTrue(any(row[0] and "Clearly trivial" in str(row[0]) for row in values))
        self.assertTrue(any(row[0] == "Less: tax effect of misstatements (33%)" and row[3] == 33 for row in values))
        conclusion = [[cell.value for cell in row] for row in book["SAD conclusion"].iter_rows()]
        verdict = next(row for row in conclusion if row[0] and "exceed" in str(row[0]))
        self.assertEqual(verdict[1], "Yes")  # |-100| above UMT 28
        self.assertTrue(any(row[0] == "Team conclusion" and row[1] == "Below UMT." for row in conclusion))

    def test_workbook_in_french(self):
        self.import_tb()
        self.env["res.lang"]._activate_lang("fr_FR")
        self.engagement.sudo().report_language = "fr"
        _filename, content = self.engagement.with_user(self.staff).ea_export_xlsx("sad")
        book = load_workbook(io.BytesIO(content))
        self.assertEqual(book.sheetnames[0], "SAD non corrigées")

    def test_caption_columns_come_from_the_bilan(self):
        self.import_tb()
        view = self.engagement.sudo()._ea_sad_view()
        self.assertEqual(view["fsCaptions"][0], 900 + 700)
        self.assertEqual(view["fsCaptions"][1], 4000)
        self.assertEqual(view["fsCaptions"][2], 600)
        self.assertEqual(view["fsCaptions"][4], 5000)
        self.assertEqual(view["incomeBeforeTax"], 0)


@tagged("post_install", "-at_install")
class TestHubAndGates(ToolsCase):
    def test_the_hub_lists_the_tools_and_their_papers(self):
        tiles = self.env["ea.audit.tool.tile"].with_user(self.reader).search([])
        by = {tile.code: tile for tile in tiles}
        self.assertEqual(by["materiality"].feeds, "P6.1")
        self.assertEqual(by["sad"].feeds, "C1.1,C3.1")
        self.assertIn("S3.1", by["cra"].feeds)
        self.assertGreaterEqual(len(tiles), 18)

    def test_opening_a_tool_goes_through_the_engagement(self):
        tile = self.env.ref("ea_audit_tools.tile_materiality").with_user(self.staff)
        action = tile.with_context(ea_engagement_id=self.engagement.id).action_open_tool()
        self.assertEqual(action["res_id"], self.engagement.id)
        outsider = self.env.ref("ea_audit_tools.tile_materiality").with_user(self.outsider)
        self.assertCode("not-on-this-engagement", outsider.with_context(ea_engagement_id=self.engagement.id).action_open_tool)
        self.env.ref("ea_audit_tools.tile_legal").sudo().method = "action_tool_not_there"
        coming = self.env.ref("ea_audit_tools.tile_legal").with_user(self.staff)
        self.assertCode("tool-not-available", coming.with_context(ea_engagement_id=self.engagement.id).action_open_tool)

    def test_every_tile_with_a_method_opens(self):  # the hub and the analyzers
        for tile in self.env["ea.audit.tool.tile"].sudo().search([("method", "!=", False)]):
            action = tile.with_user(self.staff).with_context(ea_engagement_id=self.engagement.id).action_open_tool()
            # the CRA, the findings, the SAD, the journal entries and sampling open their one page
            # (2026-11-16), every other tool a window
            pages = ("action_tool_cra", "action_tool_findings", "action_tool_sad", "action_tool_je", "action_tool_sampling", "action_tool_dsp")
            expected = "ir.actions.client" if tile.method in pages else "ir.actions.act_window"
            self.assertEqual(action["type"], expected, tile.code)

    def test_p61_waits_for_an_approved_version(self):
        self.set_phase(self.engagement, "planning")
        self.assertCode("tool-output-missing-materiality", self.sign, self.manager, self.engagement, "P6.1", "preparer")
        version = self.as_staff.create_materiality_version("equity", 1000, 2, "x")
        self.assertCode("tool-output-missing-materiality", self.sign, self.manager, self.engagement, "P6.1", "preparer")
        version.with_user(self.partner).action_approve()
        self.assertFalse(self.item(self.engagement, "P6.1").tool_outputs_missing)

    def test_p62_waits_for_tb_then_materiality(self):
        self.set_phase(self.engagement, "planning")
        self.assertCode("tool-output-missing-tb", self.sign, self.senior, self.engagement, "P6.2", "preparer")
        self.import_tb()
        self.assertCode("tool-output-missing-materiality", self.sign, self.senior, self.engagement, "P6.2", "preparer")
        self.approve()
        self.item(self.engagement, "P6.2").invalidate_recordset()
        self.assertFalse(self.item(self.engagement, "P6.2").tool_outputs_missing)

    def test_c11_waits_for_tb_materiality_and_the_conclusion(self):
        item = self.item(self.engagement, "C1.1")
        self.assertEqual(item._ea_tool_output_missing(), "tool-output-missing-tb")
        self.approve()
        self.assertEqual(item._ea_tool_output_missing(), "tool-output-missing-sad")
        self.as_staff.save_sad_conclusion("  ")
        self.assertEqual(item._ea_tool_output_missing(), "tool-output-missing-sad")
        self.as_staff.save_sad_conclusion("Nothing to correct.")
        self.assertIsNone(item._ea_tool_output_missing())

    def test_e4_needs_a_valid_tb_and_a_refused_reimport_does_not_take_it_away(self):
        unbalanced = "Compte;Libellé;Mouvement débit;Mouvement crédit\n411000;Clients;1000;0\n701000;Ventes;0;900\n"
        item = self.item(self.engagement, "E4.1")
        self.assertEqual(item._ea_tool_output_missing(), "tool-output-missing-tb")
        self.assertCode("import-refused", self.import_tb, unbalanced)
        self.assertEqual(item._ea_tool_output_missing(), "tool-output-missing-tb")
        self.import_tb()
        self.assertIsNone(item._ea_tool_output_missing())
        self.assertCode("import-refused", self.import_tb, unbalanced)
        self.assertIsNone(item._ea_tool_output_missing())

    def test_planning_gates_read_the_tools(self):
        gates = {g["key"]: g["ok"] for g in self.engagement.sudo()._ea_planning_close_gates()}
        self.assertFalse(gates["materiality_approved"])
        self.assertFalse(gates["significant_risks_linked"])  # revenue fraud waits on its programme
        self.assertTrue(gates["tb_mapped"])
        self.assertTrue(gates["rebuttals_approved"])
        self.approve()
        fraud = self.env["ea.audit.risk"].sudo().search([("engagement_id", "=", self.engagement.id), ("presumed_type", "=", "revenue_fraud")])
        step = self.as_staff.add_program_step(self.item(self.engagement, "E4.20"), "Cut-off tests", ["E", "A"])
        fraud.with_user(self.staff).link_step(step)
        gates = {g["key"]: g["ok"] for g in self.engagement.sudo()._ea_planning_close_gates()}
        self.assertTrue(gates["materiality_approved"])
        self.assertTrue(gates["significant_risks_linked"])

    def test_a_material_section_needs_a_step_not_marked_na(self):
        item = self.item(self.engagement, "E4.1")
        item.with_user(self.partner).write({"material": True})
        gate = lambda: next(g["ok"] for g in self.engagement.sudo()._ea_planning_close_gates() if g["key"] == "material_sections_covered")  # noqa: E731
        self.assertFalse(gate())
        step = self.as_staff.add_program_step(item, "Confirm balances")
        self.assertTrue(gate())
        self.assertCode("rationale-required", step.mark_na, " ")
        step.mark_na("No balance")
        self.assertFalse(gate())

    def test_a_late_revision_reopens_the_gate_but_not_the_paper(self):
        self.approve()
        self.as_staff.create_materiality_version("equity", 5000, 2, "Revised")
        gates = {g["key"]: g["ok"] for g in self.engagement.sudo()._ea_planning_close_gates()}
        self.assertFalse(gates["materiality_approved"])
        self.assertFalse(self.item(self.engagement, "P6.1")._ea_tool_output_missing())

    def test_the_snapshot_carries_the_figures(self):
        self.approve()
        data = self.engagement.sudo()._ea_planning_snapshot_data()
        self.assertEqual(data["materiality"]["versionNo"], 1)
        self.assertEqual(len(data["risks"]), 2)
        self.assertEqual(len(data["steps"]), 1)
