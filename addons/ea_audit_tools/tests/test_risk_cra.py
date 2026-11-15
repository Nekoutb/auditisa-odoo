import io

from openpyxl import Workbook, load_workbook

from odoo.tests import tagged

from .common import ToolsCase


def workbook(rows):
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


@tagged("post_install", "-at_install")
class TestSignificance(ToolsCase):
    def rows(self):
        self.engagement.sudo()._ea_sync_significance()
        return {
            record.index_code: record
            for record in self.env["ea.audit.significance"].with_user(self.staff).search([("engagement_id", "=", self.engagement.id)])
        }

    def test_the_default_follows_tolerable_error(self):
        self.approve()
        rows = self.rows()
        # overall 112, performance 84: every balance above it is significant
        self.assertEqual(rows["E"].default_status, "significant")
        self.assertEqual(rows["E"].status, "significant")
        self.assertEqual(rows["E"].closing, 900)

    def test_without_materiality_nothing_is_significant_until_a_risk_says_so(self):
        self.import_tb()
        rows = self.rows()
        self.assertEqual(rows["E"].status, "not_significant")
        risk = self.as_staff.add_risk("Doubtful receivables", index="E", assertions=["V"])
        rows = self.rows()
        rows["E"].invalidate_recordset()
        self.assertEqual(rows["E"].status, "significant")
        self.assertTrue(rows["E"].has_risk)
        self.assertEqual(rows["E"].risk_assertions, "V")
        self.assertTrue(risk)

    def test_an_override_needs_its_justification_before_p62_is_signed(self):
        self.import_tb()
        row = self.rows()["E"]
        # a departure without its reason is now refused; one stored before (old data) stays, in red
        self.assertCode("significance-reason-required", row.write, {"status": "significant"})
        row.sudo().write({"decision": "significant"})
        row.invalidate_recordset()
        self.assertTrue(row.overridden)
        self.assertTrue(row.unjustified)
        self.assertEqual(self.engagement.sudo().significance_unjustified, 1)
        item = self.item(self.engagement, "P6.2")
        self.assertEqual(item._ea_tool_gap(), "significance-unjustified")
        row.write({"justification": "Key to the covenants."})
        self.engagement.sudo().invalidate_recordset()
        self.assertFalse(item._ea_paper_refusal("preparer"))

    def test_specific_materiality_codes(self):
        self.approve()
        row = self.rows()["E"]
        self.assertCode("specific-above-materiality", row.write, {"specific_te": 112})
        self.assertCode("specific-above-te", row.write, {"specific_te": 84})
        row.write({"specific_te": 40})
        row.invalidate_recordset()
        self.assertEqual(row.specific_te, 40)

    def test_assertions_keep_ro(self):
        self.import_tb()
        row = self.rows()["E"]
        tags = self.env["ea.audit.assertion"]._ea_from_codes(["C", "RO"])
        row.write({"assertion_ids": [(6, 0, tags.ids)]})
        self.assertEqual(sorted(row.assertion_ids.mapped("code")), ["C", "RO"])

    def test_guards_and_field_limits(self):
        self.import_tb()
        row = self.rows()["E"]
        self.assertCode("invalid-field", row.write, {"closing": 1})
        self.assertCode("invalid-value", row.write, {"status": "maybe"})
        self.assertCode("read-only-role", row.with_user(self.reader).write, {"justification": "x"})
        self.assertCode("eqr-read-only", row.with_user(self.eqr).write, {"justification": "x"})

    def test_a_decision_outlives_the_account_leaving_the_tb(self):
        self.import_tb()
        self.rows()["E"].write({"justification": "keep"})
        self.import_tb("Compte;Libellé;Mouvement débit;Mouvement crédit\n521000;Banque;100;0\n701000;Ventes;0;100\n")
        rows = self.rows()
        self.assertEqual(rows["E"].justification, "keep")
        self.assertEqual(rows["E"].closing, 0)
        self.assertNotIn("K", rows)

    def test_excel_round_trip(self):
        self.import_tb()
        self.rows()
        _filename, content = self.as_staff.ea_export_xlsx("significance")
        sheet = load_workbook(io.BytesIO(content)).active
        head = [cell.value for cell in sheet[1]]
        self.assertEqual(head[:6], ["index", "closing", "transactions", "preparers", "reviewers", "status"])
        count = self.as_staff.ea_import_xlsx("significance", "s.xlsx", workbook([
            ["index", "status", "justification", "assertions", "specific_te"],
            ["E", "significant", "Key account", "C,E,RO", ""],
        ]))
        self.assertEqual(count, 1)
        row = self.rows()["E"]
        row.invalidate_recordset()
        self.assertEqual(row.decision, "significant")
        self.assertEqual(sorted(row.assertion_ids.mapped("code")), ["C", "E", "RO"])
        self.assertCode("invalid-index", self.as_staff.ea_import_xlsx, "significance", "s.csv", b"index;status\nZZ;significant\n")
        self.assertCode("read-only-role", self.as_reader.ea_import_xlsx, "significance", "s.csv", b"index;status\nE;significant\n")


@tagged("post_install", "-at_install")
class TestRisks(ToolsCase):
    def presumed(self, kind):
        return self.env["ea.audit.risk"].with_user(self.staff).search([
            ("engagement_id", "=", self.engagement.id), ("presumed_type", "=", kind),
        ])

    def test_two_presumed_risks_are_seeded_and_only_override_has_its_step(self):
        fraud = self.presumed("revenue_fraud")
        override = self.presumed("mgmt_override")
        self.assertTrue(fraud.significant and override.significant)
        self.assertEqual(fraud.inherent_rating, "high")
        self.assertFalse(fraud.program_step_ids)
        self.assertEqual(override.program_step_ids.file_item_id.code, "E3.1")
        self.assertEqual(override.status, "response_planned")
        self.assertIn("ISA 240", override.program_step_ids.description)

    def test_the_seed_runs_once_when_the_file_is_reclassified(self):
        self.engagement.with_user(self.partner).apply_complexity("complex")
        self.assertEqual(self.env["ea.audit.risk"].sudo().search_count([("engagement_id", "=", self.engagement.id)]), 2)

    def test_add_risk_documents_as_it_adds(self):
        risk = self.as_staff.add_risk(
            "Stock obsolescence", category="error", likelihood="high", magnitude="low", index="F",
            assertions=["V", "RO", "nope"], source="Walkthrough", management_missed="no process",
        )
        self.assertIn("Not identified by management", risk.description)
        self.assertEqual(risk.source, "Console (Walkthrough)")
        self.assertEqual(risk.inherent_rating, "medium")
        self.assertEqual(sorted(risk.index_link_ids.assertion_ids.mapped("code")), ["RO", "V"])
        self.assertFalse(risk.added_after_planning)
        self.assertCode("risk-description-required", self.as_staff.add_risk, "ab")

    def test_an_fs_level_risk_carries_its_note_and_no_index(self):
        risk = self.as_staff.add_risk("Going concern", level="fs", fs_note="Pervasive", index="E", assertions=["C"])
        self.assertEqual(risk.fs_note, "Pervasive")
        self.assertFalse(risk.index_link_ids)

    def test_after_planning_the_addition_awaits_the_partner(self):
        self.set_phase(self.engagement, "execution")
        risk = self.as_staff.add_risk("Late fraud indicator")
        self.assertTrue(risk.added_after_planning)
        self.assertCode("forbidden", risk.with_user(self.manager).approve_addition)
        risk.with_user(self.partner).approve_addition()
        self.assertEqual(risk.sudo().addition_approved_by_id, self.partner)
        self.assertCode("not-found", risk.with_user(self.partner).approve_addition)

    def test_a_presumed_risk_cannot_be_deflagged_by_update(self):
        fraud = self.presumed("revenue_fraud")
        self.assertCode("not-rebuttable", fraud.write, {"significant": False})
        fraud.write({"likelihood": "medium"})
        self.assertCode("invalid-field", fraud.write, {"rebutted": True})

    def test_rebuttal_is_proposed_by_the_team_and_approved_by_the_engagement_partner(self):
        fraud = self.presumed("revenue_fraud")
        self.assertCode("justification-required", fraud.with_user(self.manager).propose_rebuttal, " ")
        self.assertCode("rebuttal-not-proposed", fraud.with_user(self.partner).approve_rebuttal)
        fraud.with_user(self.manager).propose_rebuttal("No incentive: fixed-price contracts.")
        self.assertCode("rebuttal-already-proposed", fraud.with_user(self.staff).propose_rebuttal, "again")
        # still live and on revenue while it waits
        self.assertFalse(fraud.sudo().rebutted)
        self.assertEqual(fraud.sudo().rebuttal_state, "proposed")
        self.assertIn("UA", fraud.sudo().index_link_ids.mapped("index_code"))
        self.assertCode("rebut-partner-only", fraud.with_user(self.manager).approve_rebuttal)
        self.seat(self.engagement, self.partner2, "manager")
        self.assertCode("not-engagement-partner", fraud.with_user(self.partner2).approve_rebuttal)
        fraud.with_user(self.partner).approve_rebuttal()
        as_root = fraud.sudo()
        self.assertEqual(as_root.rebuttal_state, "approved")
        self.assertNotIn("UA", as_root.index_link_ids.mapped("index_code"))
        self.assertTrue(as_root.rebutted)
        self.assertFalse(as_root.significant)
        self.assertEqual(as_root.status, "concluded")
        self.assertEqual(as_root.rebuttal_approved_by_id, self.partner)
        self.assertEqual(self.engagement.sudo()._ea_unapproved_rebuttal_count(), 0)

    def test_override_is_never_rebuttable(self):
        self.assertCode("not-rebuttable", self.presumed("mgmt_override").with_user(self.partner).propose_rebuttal, "reason")

    def test_the_partner_does_not_approve_their_own_proposal_and_may_reject(self):
        fraud = self.presumed("revenue_fraud")
        fraud.with_user(self.partner).propose_rebuttal("Simple, predictable revenue.")
        self.assertCode("rebuttal-own-proposal", fraud.with_user(self.partner).approve_rebuttal)
        fraud.sudo().write({"rebuttal_state": False})
        fraud.with_user(self.staff).propose_rebuttal("Simple, predictable revenue.")
        self.assertCode("justification-required", fraud.with_user(self.partner).reject_rebuttal, " ")
        fraud.with_user(self.partner).reject_rebuttal("Bonuses depend on revenue.")
        as_root = fraud.sudo()
        self.assertEqual(as_root.rebuttal_state, "rejected")
        self.assertFalse(as_root.rebutted)
        self.assertIn("UA", as_root.index_link_ids.mapped("index_code"))
        # the team may propose again after a rejection
        fraud.with_user(self.staff).propose_rebuttal("New facts: fixed fees only.")
        self.assertEqual(as_root.rebuttal_state, "proposed")

    def test_the_revenue_link_leaves_only_by_an_approved_rebuttal(self):
        fraud = self.presumed("revenue_fraud")
        override = self.presumed("mgmt_override")
        self.assertEqual(fraud.sudo().index_link_ids.mapped("index_code"), ["UA"])
        self.assertFalse(override.sudo().index_link_ids)
        self.assertCode("revenue-fraud-link-locked", fraud.with_user(self.staff).unlink_index, "UA")

    def test_linking_upserts_and_refuses_unknown_indexes(self):
        risk = self.as_staff.add_risk("Cut-off")
        risk.link_index("E", ["C"])
        risk.link_index("E", ["C", "E"])
        self.assertEqual(len(risk.index_link_ids), 1)
        self.assertEqual(sorted(risk.index_link_ids.assertion_ids.mapped("code")), ["C", "E"])
        self.assertCode("invalid-index", risk.link_index, "ZZZ", ["C"])
        risk.unlink_index("E")
        self.assertFalse(risk.index_link_ids)

    def test_potential_risks(self):
        Potential = self.env["ea.audit.potential.risk"]
        self.assertCode("description-required", self.as_staff.raise_potential_risk, " ", "P5.2")
        raised = self.as_staff.raise_potential_risk("Possible related party", "P5.2")
        self.assertCode("rationale-required", raised.dismiss, " ")
        promoted = raised.promote()
        self.assertEqual(promoted.source, "P5.2 (P5.2)")
        self.assertCode("not-found", raised.promote)
        self.assertCode("not-found", raised.dismiss, "too late")
        other = self.as_staff.raise_potential_risk("Noise", "P5.2")
        other.dismiss("Checked: nothing there")
        self.assertEqual(Potential.sudo().browse(other.id).status, "dismissed")
        self.assertCode("read-only-role", self.as_reader.raise_potential_risk, "x", "P5.2")

    def test_register_export_and_import(self):
        filename, content = self.as_staff.ea_export_xlsx("risks")
        self.assertTrue(filename.startswith("risks-"))
        sheet = load_workbook(io.BytesIO(content)).active
        self.assertEqual(sheet.max_row, 3)
        self.as_staff.ea_import_xlsx("risks", "r.csv", "description;category;level;index;assertions;significant\nStock;error;assertion;F;V;oui\n".encode())
        risk = self.env["ea.audit.risk"].sudo().search([("engagement_id", "=", self.engagement.id), ("description", "=", "Stock")])
        self.assertTrue(risk.significant)
        self.assertEqual(risk.index_link_ids.index_code, "F")


@tagged("post_install", "-at_install")
class TestCra(ToolsCase):
    def board(self):
        self.approve()
        self.engagement.sudo()._ea_sync_cra()
        return self.engagement.sudo()

    def cell(self, index="E", assertion="C", actor=None):
        return self.env["ea.audit.cra.assessment"].with_user(actor or self.staff).search([
            ("engagement_id", "=", self.engagement.id), ("index_code", "=", index), ("assertion", "=", assertion),
        ])

    def test_six_assertions_per_significant_account(self):
        board = self.board()
        row = board.cra_row_ids.filtered(lambda r: r.index_code == "E")
        self.assertEqual(sorted(row.cell_ids.mapped("assertion")), sorted(["C", "E", "A", "V", "P", "RO"]))
        self.assertEqual(row.task_code, "E4.1")
        self.assertEqual(row.cell_ro, "to_assess")
        self.assertEqual(row.cell_p, "na")  # outside the C, E, A, V default until someone records it

    def test_a_recorded_cell_reads_its_level(self):
        self.board()
        self.cell().write({"ir": "higher", "cr": "not_rely"})
        cell = self.cell()
        self.assertEqual(cell.level, "high")
        self.assertEqual(cell.tod_level, "high")
        self.assertTrue(cell.recorded)
        row = cell.sudo().row_id
        row.invalidate_recordset()
        self.assertEqual(row.cell_c, "high")

    def test_rely_with_no_covering_control_needs_a_written_basis(self):
        self.board()
        self.assertCode("rely-without-controls", self.cell().write, {"cr": "rely"})
        self.assertCode("rely-without-controls", self.cell().write, {"cr": "rely", "cr_basis": " "})
        self.cell().write({"cr": "rely", "cr_basis": "IT dependent control tested in E1.2"})
        self.assertEqual(self.cell().cr, "rely")

    def test_the_old_not_rely_basis_is_no_reason_to_rely(self):
        self.board()
        self.cell().write({"cr": "not_rely", "cr_basis": "No reliance planned"})
        self.assertCode("rely-without-controls", self.cell().write, {"cr": "rely"})

    def test_rely_with_a_tested_control_needs_no_basis(self):
        self.board()
        cls = type(self.env["ea.audit.engagement"])
        self.patch(cls, "_ea_control_coverage", lambda _s, _i, _a: {"covering": 1, "effective": 1, "failed": 0})
        self.cell().write({"cr": "rely"})
        self.assertEqual(self.cell().cr, "rely")
        self.assertEqual(self.cell().suggested_cr, "rely")
        self.patch(cls, "_ea_itgc_state", lambda _s: "not_support")
        self.assertCode("rely-without-controls", self.cell("E", "A").write, {"cr": "rely"})

    def test_reassessment_needs_a_reason_once_materiality_is_approved(self):
        self.board()
        self.cell().write({"ir": "lower", "cr": "not_rely"})
        self.assertCode("reassessment-reason-required", self.cell().write, {"ir": "higher"})
        self.cell().write({"ir": "higher", "reason": "New indicator from the walkthrough"})
        history = self.cell().history_ids
        self.assertEqual(len(history), 1)
        self.assertEqual((history.ir, history.new_ir, history.reason), ("lower", "higher", "New indicator from the walkthrough"))
        self.assertEqual(history.changed_by_id, self.staff)

    def test_before_the_lock_a_revision_is_journaled_without_a_reason(self):
        self.import_tb()
        row = self.env["ea.audit.significance"]
        self.engagement.sudo()._ea_sync_significance()
        row.sudo().search([("engagement_id", "=", self.engagement.id), ("index_code", "=", "E")]).write({"decision": "significant", "justification": "x"})
        self.engagement.sudo()._ea_sync_cra()
        self.cell().write({"ir": "lower"})
        self.cell().write({"ir": "higher"})
        self.assertEqual(len(self.cell().history_ids), 1)

    def test_a_change_voids_the_s31_signatures(self):
        self.board()
        item = self.item(self.engagement, "S3.1")
        signoff = self.env["ea.audit.signoff"].sudo().create({
            "file_item_id": item.id, "role": "preparer", "user_id": self.staff.id,
        })
        self.cell().write({"ir": "lower"})
        self.assertTrue(signoff.invalidated_at)

    def test_guards(self):
        self.board()
        self.assertCode("read-only-role", self.cell(actor=self.reader).write, {"ir": "lower"})
        self.assertCode("eqr-read-only", self.cell(actor=self.eqr).write, {"ir": "lower"})
        self.assertCode("invalid-field", self.cell().write, {"recorded": False})
        self.assertCode("forbidden", self.cell().unlink)
        self.assertFalse(self.cell(actor=self.outsider))

    def test_gates_read_the_board(self):
        self.board()
        self.assertEqual(self.engagement.sudo()._ea_unsupported_rely_count(), 0)
        self.cell().write({"cr": "rely", "cr_basis": "written"})
        self.assertEqual(self.engagement.sudo()._ea_unsupported_rely_count(), 0)
        self.cell().sudo().write({"cr_basis": False})
        self.assertEqual(self.engagement.sudo()._ea_unsupported_rely_count(), 1)

    def test_a_saved_cell_keeps_its_line_when_p62_reclassifies(self):
        self.board()
        self.cell().write({"ir": "lower"})
        record = self.env["ea.audit.significance"].sudo().search([("engagement_id", "=", self.engagement.id), ("index_code", "=", "E")])
        record.write({"decision": "not_significant", "justification": "x"})
        self.engagement.sudo()._ea_sync_cra()
        self.assertIn("E", self.engagement.sudo().cra_row_ids.mapped("index_code"))

    def test_the_counter_and_the_unlinked_banner(self):
        board = self.board()
        board.invalidate_recordset()
        self.assertGreater(board.cra_to_assess_count, 0)
        self.assertIn("ISA 240", board.cra_unlinked_risk_label)

    def test_key_item_threshold(self):
        board = self.board()
        row = board.cra_row_ids.filtered(lambda r: r.index_code == "E").with_user(self.staff)
        self.assertCode("invalid-threshold", row.write, {"key_item_threshold": -1})
        row.write({"key_item_threshold": 70})
        self.assertEqual(row.key_item_threshold, 70)

    def test_excel_round_trip(self):
        self.board()
        _filename, content = self.as_reader.ea_export_xlsx("cra")
        sheet = load_workbook(io.BytesIO(content)).active
        self.assertEqual([cell.value for cell in sheet[1]][:2], ["index", "assertion"])
        self.as_staff.ea_import_xlsx("cra", "c.xlsx", workbook([
            ["index", "assertion", "relevant", "ir", "cr", "cr_basis"],
            ["E", "RO", "yes", "lower", "not_rely", ""],
        ]))
        self.assertEqual(self.cell("E", "RO").level, "moderate")
        self.assertCode("invalid-assertion", self.as_staff.ea_import_xlsx, "cra", "c.csv", b"index;assertion\nE;Z\n")
        self.assertCode("invalid-value", self.as_staff.ea_import_xlsx, "cra", "c.csv", b"index;assertion;ir\nE;C;maybe\n")

    def test_rollup_excludes_the_unassessed_default_ro(self):
        board = self.board()
        rollup = board.cra_rollup_by_index()
        self.assertIn("E", rollup)
