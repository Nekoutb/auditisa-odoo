from odoo.tests import tagged

from odoo.addons.ea_audit_tools.services.cra_model import CR_DEFICIENT_BASIS

from .common import AR_CSV, AR_MAPPING, ToolsCase, to_bytes


class ProcedureDesignCase(ToolsCase):
    """Receivables (E) significant, existence and valuation relevant."""

    def setUp(self):
        super().setUp()
        self.approve()
        record = self.env["ea.audit.significance"].sudo().search([("engagement_id", "=", self.engagement.id), ("index_code", "=", "E")], limit=1)
        record.with_user(self.staff)._ea_save({
            "status": "significant", "justification": "Créances importantes",
            "assertion_ids": [(6, 0, self.env["ea.audit.assertion"]._ea_from_codes(["E", "V"]).ids)],
        })
        self.engagement.sudo()._ea_sync_cra()

    def cell(self, assertion):
        return self.engagement.sudo()._ea_cra_cell("E", assertion)

    def assess(self, assertion, ir, cr):
        self.cell(assertion).with_user(self.staff).write({"ir": ir, "cr": cr})

    def page(self, actor=None):
        return (actor or self.as_staff).ea_procedure_design_page()

    def account(self, page=None):
        return next(a for a in (page or self.page())["accounts"] if a["code"] == "E")

    def row(self, code, page=None):
        return next(r for r in self.account(page)["rows"] if r["code"] == code)

    def proc(self, code):
        return self.env["ea.audit.designed.procedure"].sudo().search([
            ("engagement_id", "=", self.engagement.id), ("index_code", "=", "E"), ("code", "=", code),
        ])


@tagged("post_install", "-at_install")
class TestProcedureLibrary(ProcedureDesignCase):
    def test_the_library_is_loaded_in_both_languages(self):
        Library = self.env["ea.audit.procedure.library"].sudo()
        self.assertEqual(Library.search_count([]), 58)
        self.assertEqual(Library.search_count([("kind", "=", "MSP")]), 25)
        item = Library.search([("code", "=", "E-M1")])
        self.assertEqual(item.with_context(lang="en_US").title, "Sub-ledger and aged balance agree to the general ledger")
        self.assertIn("balance âgée", item.title_fr)
        self.assertEqual(Library._ea_load_library(), 58)  # idempotent
        self.assertEqual(Library.search_count([]), 58)

    def test_the_tile_is_renamed(self):
        self.assertEqual(self.env.ref("ea_audit_tools.tile_dsp").name, "Procedure design")
        action = self.as_staff.action_tool_dsp()
        self.assertEqual(action["tag"], "ea_audit_tools.procedure_design")


@tagged("post_install", "-at_install")
class TestProcedureDesign(ProcedureDesignCase):
    def test_mandatory_procedures_are_ticked_and_locked(self):
        page = self.page()
        rows = self.account(page)["rows"]
        mandatory = [r["code"] for r in rows if r["kind"] == "MSP" and r["locked"]]
        self.assertEqual(mandatory, ["E-M1", "E-M2", "E-M3", "E-M4", "E-M5", "E-M6"])
        self.assertTrue(all(r["selected"] for r in rows if r["locked"]))
        self.assertEqual(self.row("E-M1", page)["dots"]["E"], "covered")
        self.assertEqual(self.row("E-M1", page)["sample_mode"], "tool")
        with self.assertRaisesRegex(Exception, "procedure-mandatory"):
            self.as_staff.ea_procedure_choose("E", "E-M1", False)
        self.assertTrue(self.proc("E-M1").selected)

    def test_to_assess_until_the_cra_is_done(self):
        account = self.account()
        self.assertEqual(account["to_assess"], ["E", "V"])
        self.assertFalse(account["complete"])
        # one entry per significant account (the fixture's trial balance makes several)
        progress = self.page()["progress"]
        self.assertEqual(progress["total"], len(self.page()["accounts"]))

    def test_a_high_risk_needs_an_alternative(self):
        self.assess("E", "higher", "not_rely")
        self.assess("V", "lower", "not_rely")
        before = self.page()["progress"]["done"]
        account = self.account()
        self.assertEqual(account["missing"], ["E"])
        self.assertFalse(account["complete"])
        self.assertIn("E", self.row("E-A2")["why"])
        page = self.as_staff.ea_procedure_choose("E", "E-A2", True)
        proc = self.proc("E-A2")
        self.assertTrue(proc.selected)
        self.assertEqual((proc.reason, proc.reason_assertion, proc.reason_level), ("suggested", "E", "high"))
        self.assertEqual(self.account(page)["missing"], [])
        self.assertTrue(self.account(page)["complete"])
        self.assertEqual(page["progress"]["done"], before + 1)
        self.assertIn("E", self.engagement.sudo()._ea_designed_indexes())

    def test_an_alternative_can_be_unticked_until_it_starts(self):
        self.as_staff.ea_procedure_choose("E", "E-A8", True)
        self.assertEqual(self.proc("E-A8").reason, "choice")
        self.as_staff.ea_procedure_choose("E", "E-A8", False)
        self.assertFalse(self.proc("E-A8").selected)
        self.as_staff.ea_procedure_choose("E", "E-A8", True)
        self.proc("E-A8")._ea_mark_started()
        with self.assertRaisesRegex(Exception, "procedure-started"):
            self.as_staff.ea_procedure_choose("E", "E-A8", False)
        self.assertTrue(self.row("E-A8")["started"])

    def test_a_condition_tag(self):
        self.as_staff.ea_procedure_choose("E", "E-A4", True)
        self.assertEqual(self.proc("E-A4").reason, "condition")
        self.assertIn("foreign-currency", self.row("E-A4")["why"])

    def test_an_alternative_that_answers_nothing_relevant_is_not_offered(self):
        more = [item["code"] for item in self.account()["more"]]
        self.assertIn("E-A6", more)  # RO, P only
        with self.assertRaisesRegex(Exception, "procedure-not-offered"):
            self.as_staff.ea_procedure_choose("E", "E-A6", True)

    def test_an_own_procedure_counts_as_an_alternative(self):
        self.assess("E", "higher", "not_rely")
        self.assess("V", "lower", "not_rely")
        page = self.as_staff.ea_procedure_add("E", "Circulariser les dix plus gros clients", ["E", "C"])
        own = self.proc("E-X1")
        self.assertEqual((own.kind, own.assertions, own.selected), ("custom", "E", True))
        self.assertTrue(self.account(page)["complete"])
        with self.assertRaisesRegex(Exception, "invalid-osp"):
            self.as_staff.ea_procedure_add("E", " ", ["E"])

    def test_roles(self):
        with self.assertRaisesRegex(Exception, "read-only-role"):
            self.as_reader.ea_procedure_choose("E", "E-A2", True)
        self.assertTrue(self.page(self.as_reader)["accounts"])
        self.engagement.sudo()._ea_sync_procedures()
        self.assertFalse(self.env["ea.audit.designed.procedure"].with_user(self.outsider).search([]))

    def test_a_sample_drawn_for_a_procedure_feeds_it(self):
        self.as_staff.ea_procedure_choose("E", "E-A2", True)
        proc = self.proc("E-A2")
        dataset = self.as_staff.create_dataset("ar_open_items", "ar.csv", to_bytes(AR_CSV), mapping=AR_MAPPING)["datasetId"]
        action = self.as_staff.ea_procedure_draw(proc.id)
        self.assertEqual(action["res_model"], "ea.audit.sampling.wizard")
        self.assertEqual(action["context"]["default_dataset_id"], dataset)
        self.assertEqual(action["context"]["default_designed_procedure_id"], proc.id)
        run = self.as_staff.run_sampling(dataset, "random", 1, seed="abc", designed_procedure=proc).sudo()
        self.assertEqual(run.designed_procedure_id, proc)
        self.assertTrue(run.purpose.startswith("E-A2"))
        self.assertEqual(proc.state, "started")
        row = self.row("E-A2")
        self.assertEqual(row["sample"]["id"], run.id)
        with self.assertRaisesRegex(Exception, "procedure-started"):
            self.as_staff.ea_procedure_choose("E", "E-A2", False)
        focus = self.as_staff.ea_procedure_open("sample", run.id)
        self.assertEqual(focus["params"]["focus"], "tod:%d" % run.id)

    def test_generated_steps_come_from_the_design(self):
        from odoo.addons.ea_audit_tools.services.lead_classes import INDEX_SECTION

        self.page()
        task = INDEX_SECTION["E"]
        self.as_staff.ea_procedure_choose("E", "E-A2", True)
        created = self.as_staff.generate_psp(task)
        self.assertEqual(created, 7)
        self.assertTrue(self.proc("E-A2").step_id)
        self.assertEqual(self.as_staff.generate_psp(task), 0)

    def test_the_tests_of_controls_section(self):
        scot = self.as_staff.create_scot("Ventes", "routine", "controls")
        scot.link_index("E", ["E"])
        wcgw = scot.add_wcgw("Facture fictive", ["E"])
        control = scot.add_control("Validation du crédit", control_type="manual", frequency="monthly", wcgws=wcgw)
        control.update_control({"selected_for_testing": True})
        page = self.page()
        self.assertEqual([c["name"] for c in page["controls"]], ["Validation du crédit"])
        self.assertEqual(page["controls"][0]["assertions"], ["E"])
        page = self.as_staff.ea_procedure_reliance(control.id, "heavy")
        self.assertEqual(page["controls"][0]["reliance"], "heavy")
        self.assertEqual(control.sudo().reliance, "heavy")


@tagged("post_install", "-at_install")
class TestControlNotEffective(ProcedureDesignCase):
    def test_not_effective_moves_the_cra_to_not_rely_and_suggests(self):
        scot = self.as_staff.create_scot("Ventes", "routine", "controls")
        scot.link_index("E", ["E"])
        wcgw = scot.add_wcgw("Facture fictive", ["E"])
        control = scot.add_control("Validation du crédit", control_type="manual", frequency="monthly", wcgws=wcgw)
        control.update_control({"selected_for_testing": True})
        self.cell("E").with_user(self.staff).write({"ir": "lower", "cr": "rely"})
        self.assertEqual(self.cell("E").level, "minimal")
        self.assertFalse(self.row("E-A2")["why"])
        control.update_control({"operating_eval": "not_effective"})
        cell = self.cell("E")
        cell.invalidate_recordset()
        self.assertEqual(cell.cr, "not_rely")
        self.assertIn(CR_DEFICIENT_BASIS, cell.cr_basis)
        self.assertEqual(cell.history_ids[:1].reason, CR_DEFICIENT_BASIS)
        bodies = self.env["mail.message"].sudo().search([
            ("model", "=", "ea.audit.engagement"), ("res_id", "=", self.engagement.id),
        ]).mapped("body")
        self.assertTrue(any("set to not rely: control Validation du crédit concluded not effective" in str(body) for body in bodies))
        self.assertIn("E", self.row("E-A2")["why"])
        self.as_staff.ea_procedure_choose("E", "E-A2", True)
        self.assertEqual(self.proc("E-A2").reason, "suggested")
