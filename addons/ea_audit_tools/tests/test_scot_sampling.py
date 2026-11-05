import io

from openpyxl import load_workbook

from odoo.tests import tagged

from odoo.addons.ea_audit_tools.services.engines import seeded_random
from odoo.addons.ea_audit_tools.services.toc_sampling import draw_toc_sample, seeded_rng

from .common import ToolsCase, to_bytes


LEDGER = """Compte;N° écriture;Libellé;Date;Montant
411000;VE001;Facture 1;15/01/2025;1000
701000;VE001;Facture 1;15/01/2025;-1000
411000;VE002;Facture 2;16/01/2025;400
701000;VE002;Facture 2;16/01/2025;-400
601000;AC001;Achat;20/02/2025;300
521000;AC001;Achat;20/02/2025;-300
"""
MAPPING = {"account": "Compte", "jeNumber": "N° écriture", "jeDescription": "Libellé", "journalDate": "Date", "amount": "Montant"}


class ScotCase(ToolsCase):
    def setUp(self):
        super().setUp()
        self.scot = self.as_staff.create_scot("Ventes", "routine", "controls", "Sage X3 (GL, AR); Odoo")
        self.wcgw = self.scot.add_wcgw("Facture non enregistrée", ["C"])
        self.control = self.scot.add_control("Rapprochement", control_type="manual", frequency="monthly", wcgws=self.wcgw)

    def select(self):
        self.control.update_control({"selected_for_testing": True})


@tagged("post_install", "-at_install")
class TestScots(ScotCase):
    def test_refusals_keep_their_codes(self):
        with self.assertRaisesRegex(Exception, "name-required"):
            self.as_staff.create_scot(" ")
        with self.assertRaisesRegex(Exception, "duplicate-name"):
            self.as_staff.create_scot("Ventes")
        with self.assertRaisesRegex(Exception, "description-required"):
            self.scot.add_wcgw(" ", ["C"])
        with self.assertRaisesRegex(Exception, "assertion-required"):
            self.scot.add_wcgw("x", ["nope"])
        with self.assertRaisesRegex(Exception, "invalid-index"):
            self.scot.link_index("bad index", ["C"])
        with self.assertRaisesRegex(Exception, "read-only-role"):
            self.as_reader.create_scot("Achats")
        with self.assertRaisesRegex(Exception, "eqr-read-only"):
            self.as_eqr.create_scot("Achats")

    def test_unknown_type_and_strategy_fall_back(self):
        scot = self.as_staff.create_scot("Paie", "nonsense", "nonsense")
        self.assertEqual((scot.sudo().transaction_type, scot.sudo().strategy), ("routine", "substantive"))

    def test_a_control_answering_nothing_cannot_be_selected(self):
        orphan = self.scot.add_control("Orphelin")
        with self.assertRaisesRegex(Exception, "control-without-wcgw"):
            orphan.update_control({"selected_for_testing": True})

    def test_removing_the_last_wcgw_deselects(self):
        self.select()
        self.wcgw.with_user(self.partner).unlink()
        self.assertFalse(self.control.sudo().selected_for_testing)

    def test_deletions_need_a_senior(self):
        with self.assertRaises(Exception):
            self.wcgw.with_user(self.staff).unlink()
        with self.assertRaises(Exception):
            self.control.with_user(self.staff).unlink()

    def test_plain_writes_are_screened(self):
        with self.assertRaisesRegex(Exception, "invalid-field"):
            self.scot.write({"engagement_id": 1})
        self.scot.write({"strategy": "substantive", "flow_initiation": "Le client commande."})
        self.assertEqual(self.scot.sudo().flow_initiation, "Le client commande.")
        self.assertEqual(self.scot.sudo().walkthrough_open, 13)

    def test_effective_needs_the_planned_sample_tested(self):
        self.select()
        with self.assertRaisesRegex(Exception, "toc-no-sample"):
            self.control.update_control({"operating_eval": "effective"})
        self.control.draw_toc_sample(12, 2)
        grid = {"attributes": ["a"], "rows": [{"ref": "1", "date": "", "desc": "", "results": {"a": "pass"}}]}
        self.control.update_control({"toc_grid": grid})
        with self.assertRaisesRegex(Exception, "toc-incomplete"):
            self.control.update_control({"operating_eval": "effective"})
        grid["rows"].append({"ref": "2", "date": "", "desc": "", "results": {"a": "pass"}})
        self.control.update_control({"toc_grid": grid, "operating_eval": "effective"})
        self.assertEqual(self.control.sudo().operating_eval, "effective")

    def test_not_effective_stamps_s31_and_effective_lifts_it(self):
        self.scot.link_index("C", ["C"])
        self.select()
        self.control.update_control({"operating_eval": "not_effective"})
        cell = self.engagement.sudo()._ea_cra_cell("C", "C")
        self.assertEqual(cell.cr, "not_rely")
        self.assertIn("E1.2", cell.cr_basis)
        self.control.sudo().write({"sample_size": 1, "toc_grid": {"attributes": ["a"], "rows": [{"ref": "1", "date": "", "desc": "", "results": {"a": "pass"}}]}})
        self.control.update_control({"operating_eval": "effective"})
        cell.invalidate_recordset()
        self.assertFalse(cell.cr)
        self.assertFalse(cell.cr_basis)

    def test_the_stamp_is_lifted_only_when_no_other_control_fails(self):
        self.scot.link_index("C", ["C"])
        self.select()
        other = self.scot.add_control("Second", wcgws=self.wcgw)
        other.update_control({"selected_for_testing": True, "operating_eval": "not_effective"})
        self.control.update_control({"operating_eval": "not_effective"})
        self.control.sudo().write({"sample_size": 1, "toc_grid": {"attributes": ["a"], "rows": [{"ref": "1", "date": "", "desc": "", "results": {"a": "pass"}}]}})
        self.control.update_control({"operating_eval": "effective"})
        self.assertEqual(self.engagement.sudo()._ea_cra_cell("C", "C").cr, "not_rely")

    def test_coverage_feeds_the_cra_hook(self):
        self.scot.link_index("C", ["C"])
        self.assertEqual(self.engagement.sudo()._ea_control_coverage("C", "C")["covering"], 0)
        self.select()
        self.assertEqual(self.engagement.sudo()._ea_control_coverage("C", "C"), {"covering": 1, "effective": 0, "failed": 0})
        self.assertEqual(self.engagement.sudo()._ea_control_coverage("C", "E")["covering"], 0)

    def test_outsider_reads_nothing(self):
        for model in ("ea.audit.scot", "ea.audit.wcgw", "ea.audit.scot.control", "ea.audit.toc.draw", "ea.audit.it.application"):
            self.assertFalse(self.env[model].with_user(self.outsider).search([]), model)

    def test_applications_split_outside_parentheses_and_stay_removed(self):
        self.as_staff.action_tool_itgc()
        apps = self.env["ea.audit.it.application"].sudo().search([("engagement_id", "=", self.engagement.id)])
        self.assertEqual(sorted(apps.mapped("name")), ["Odoo", "Sage X3 (GL, AR)"])
        apps.filtered(lambda a: a.name == "Odoo").with_user(self.staff).action_remove()
        self.as_staff.action_tool_itgc()
        kept = self.env["ea.audit.it.application"].sudo().search([("engagement_id", "=", self.engagement.id), ("removed", "=", False)])
        self.assertEqual(kept.mapped("name"), ["Sage X3 (GL, AR)"])

    def test_itgc_conclusion_feeds_the_hook(self):
        self.as_staff.save_itgc_conclusion("not_support")
        self.assertEqual(self.engagement.sudo()._ea_itgc_state(), "not_support")
        with self.assertRaisesRegex(Exception, "invalid-value"):
            self.as_staff.save_itgc_conclusion("nonsense")
        with self.assertRaisesRegex(Exception, "invalid-key"):
            self.as_staff.save_it_application("Not A Key", {})
        with self.assertRaisesRegex(Exception, "invalid-strategy"):
            self.as_staff.save_it_application("odoo", {"strategy": "nope"})

    def test_paper_gaps(self):
        for code, refusal in (("S1.3", "walkthrough-incomplete"), ("S2.1", "control-selection-incomplete"), ("S2.3", "itapp-strategy-missing")):
            item = self.item(self.engagement, code)
            if item:
                self.assertEqual(item._ea_paper_refusal("preparer"), refusal, code)
        self.assertEqual(self.engagement.sudo().scot_ids.walkthrough_open, 14)

    def test_the_views_load(self):
        for xmlid in ("view_scot_form", "view_control_form", "view_engagement_itgc_board", "view_engagement_sampling_board"):
            view = self.env.ref("ea_audit_tools.%s" % xmlid)
            self.env[view.model].with_user(self.reader).get_view(view.id)


@tagged("post_install", "-at_install")
class TestTocDraw(ScotCase):
    def test_the_first_draw_needs_no_reason_and_reproduces_from_its_seed(self):
        self.select()
        draw = self.control.draw_toc_sample(100, 5, "rule")
        as_root = draw.sudo()
        self.assertEqual(as_root.draw_no, 1)
        self.assertEqual(as_root.items, draw_toc_sample(100, 5, seeded_rng(as_root.seed, seeded_random)))
        self.assertEqual(self.control.sudo().toc_sample_items, as_root.items)
        self.assertEqual(self.control.sudo().sample_note, "rule")

    def test_refusals(self):
        with self.assertRaisesRegex(Exception, "toc-population-required"):
            self.control.draw_toc_sample(0, 5)
        with self.assertRaisesRegex(Exception, "toc-size-invalid"):
            self.control.draw_toc_sample(10, 0)
        self.control.draw_toc_sample(10, 2)
        with self.assertRaisesRegex(Exception, "redraw-reason-required"):
            self.control.draw_toc_sample(10, 2, reason="no")

    def test_every_draw_is_kept(self):
        self.control.draw_toc_sample(10, 2)
        self.control.draw_toc_sample(20, 3, reason="population corrected")
        draws = self.control.sudo().draw_ids
        self.assertEqual(sorted(draws.mapped("draw_no")), [1, 2])
        self.assertEqual(len(self.control.sudo().toc_sample_items), 3)
        with self.assertRaises(Exception):
            draws[0].with_user(self.manager).unlink()

    def test_after_testing_only_a_manager_redraws(self):
        self.control.draw_toc_sample(10, 2)
        self.control.sudo().write({"toc_grid": {"attributes": ["a"], "rows": [{"ref": "1", "date": "", "desc": "", "results": {"a": "pass"}}]}})
        with self.assertRaisesRegex(Exception, "redraw-after-testing-manager-only"):
            self.control.draw_toc_sample(10, 2, reason="mistake")
        draw = self.control.sudo().with_user(self.manager).draw_toc_sample(10, 2, reason="mistake")
        self.assertEqual(draw.sudo().draw_no, 2)

    def test_the_minimum_follows_the_frequency_and_the_sole_control(self):
        self.select()
        self.assertEqual(self.control.sudo().suggested_size, 2)
        self.assertTrue(self.control.sudo().sole_control)
        daily = self.scot.add_control("Quotidien", frequency="daily", wcgws=self.wcgw)
        daily.sudo().write({"toc_population": 300})
        self.assertEqual(daily.sudo().suggested_size, 25)

    def test_the_extract(self):
        self.select()
        self.control.draw_toc_sample(10, 2)
        name, content = self.as_staff.ea_export_xlsx("toc_samples")
        self.assertIn("Tests-of-controls-samples", name)
        book = load_workbook(io.BytesIO(content))
        self.assertEqual(len(book.worksheets), 2)


@tagged("post_install", "-at_install")
class TestTod(ToolsCase):
    def setUp(self):
        super().setUp()
        self.approve()

    def ledger(self):
        return self.as_staff.create_dataset("journal_entries", "gl.csv", to_bytes(LEDGER), mapping=MAPPING)

    def test_prerequisites(self):
        keys = {item["key"]: item["ok"] for item in self.as_staff._ea_tool_prerequisites()}
        self.assertEqual(keys["gl"], False)
        self.assertEqual(keys["controls"], False)
        self.ledger()
        keys = {item["key"]: item["ok"] for item in self.as_staff._ea_tool_prerequisites()}
        self.assertEqual(keys["gl"], True)

    def test_refusals(self):
        with self.assertRaisesRegex(Exception, "no-gl"):
            self.as_staff.tod_side_view("bs")
        self.as_staff.create_dataset("journal_entries", "gl.csv", to_bytes(LEDGER), mapping={"account": "Compte"})
        with self.assertRaisesRegex(Exception, "no-mapping"):
            self.as_staff.tod_side_view("bs")

    def test_no_materiality_refused(self):
        other = self.make_engagement(year=2026)
        with self.assertRaisesRegex(Exception, "no-materiality"):
            other.with_user(self.partner).tod_side_view("bs")

    def test_the_same_ledger_draws_the_same_sample(self):
        self.ledger()
        first = self.as_staff.tod_side_view("is")
        second = self.as_staff.tod_side_view("is")
        self.assertEqual(first["sheets"][0]["plan"]["sample"], second["sheets"][0]["plan"]["sample"])
        self.assertTrue(first["emptyIndexes"])
        self.assertIn("craFromS31", first["sheets"][0])

    def test_workbook_and_preview(self):
        self.ledger()
        name, content = self.as_staff.ea_export_xlsx("tod_bs_little")
        self.assertIn("Tests-of-details-balance-sheet", name)
        book = load_workbook(io.BytesIO(content))
        self.assertGreaterEqual(len(book.worksheets), 2)
        self.assertIn("table", str(self.as_staff.tod_preview_html("is", "some")))
        with self.assertRaisesRegex(Exception, "not-found"):
            self.as_staff.ea_export_xlsx("tod_xx_little")

    def test_prefix_previews(self):
        self.ledger()
        plan = self.as_staff.tod_preview("41", "low", "little")
        self.assertEqual(plan["populationCount"], 2)
        self.assertEqual(plan["populationValue"], 1400)
        mus = self.as_staff.mus_preview("41", 500)
        self.assertEqual(mus["topStratum"], 1)
        self.assertEqual(mus["sampleSize"], 2)
        with self.assertRaisesRegex(Exception, "empty-population"):
            self.as_staff.mus_preview("99")

    def test_record_result_projects_and_routes(self):
        result = self.as_staff.record_tod_result("C", 1000, 10, 5, 100000)
        self.assertEqual(result["projected"], 1000)
        run = self.env["ea.audit.automation.run"].sudo().browse(result["runId"])
        self.assertEqual(run.index_code, "C")
        self.assertEqual(run.total_likely, 1005)
        findings = self.env["ea.audit.finding"].sudo().search([("engagement_id", "=", self.engagement.id)])
        self.assertEqual(len(findings), 1 + int(result["raisedToB5"]))

    def test_record_result_refusals(self):
        with self.assertRaisesRegex(Exception, "invalid-index"):
            self.as_staff.record_tod_result("bad index", 1000, 0, 0, 10)
        with self.assertRaisesRegex(Exception, "empty-population"):
            self.as_staff.record_tod_result("C", 0, 0, 0, 10)
        with self.assertRaisesRegex(Exception, "invalid-amount"):
            self.as_staff.record_tod_result("C", 10, 0, 0, -1)
        with self.assertRaisesRegex(Exception, "read-only-role"):
            self.as_reader.record_tod_result("C", 10, 0, 0, 10)

    def test_a_dataset_sample_stores_its_seed(self):
        dataset = self.ledger()["datasetId"]
        run = self.as_staff.run_sampling(dataset, "random", 2, seed="abc")
        as_root = run.sudo()
        self.assertEqual(as_root.params["seed"], "abc")
        self.assertEqual(len(as_root.sheet_rows), 2)
        again = self.as_staff.run_sampling(dataset, "random", 2, seed="abc")
        self.assertEqual(again.sudo().sheet_rows, as_root.sheet_rows)
        name, _content = self.as_staff.ea_export_xlsx("run_%d" % run.id)
        self.assertIn("run-", name)
        with self.assertRaisesRegex(Exception, "override-rationale-required"):
            self.as_staff.run_sampling(dataset, "random", 2, override_size=3)
        with self.assertRaisesRegex(Exception, "seed-required|invalid-sample-size"):
            self.as_staff.run_sampling(dataset, "random", 0)

    def test_evaluating_a_run_projects(self):
        run = self.as_staff.run_sampling(self.ledger()["datasetId"], "mus", 2, seed="abc")
        result = run.evaluate(0)
        self.assertEqual(result, {"projected": 0, "raisedToB5": False})
