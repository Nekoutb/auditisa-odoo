from odoo.tests import tagged

from .common import ToolsCase


class DesignCase(ToolsCase):
    def setUp(self):
        super().setUp()
        self.approve()
        record = self.env["ea.audit.significance"].sudo().search([("engagement_id", "=", self.engagement.id), ("index_code", "=", "C")], limit=1)
        record.with_user(self.staff)._ea_save({
            "status": "significant", "justification": "Trésorerie importante",
            "assertion_ids": [(6, 0, self.env["ea.audit.assertion"]._ea_from_codes(["E", "V"]).ids)],
        })

    def design(self, assertion="E", code="C"):
        designs = self.engagement.sudo()._ea_sync_dsp()
        return designs.filtered(lambda d: d.index_code == code and d.assertion == assertion)


@tagged("post_install", "-at_install")
class TestDesign(DesignCase):
    def test_rows_follow_the_key_assertions(self):
        designs = self.engagement.sudo()._ea_sync_dsp().filtered(lambda d: d.index_code == "C")
        self.assertEqual(sorted(designs.mapped("assertion")), ["E", "V"])
        self.assertTrue(self.design().choice_ids)

    def test_refusals(self):
        with self.assertRaisesRegex(Exception, "invalid-field"):
            self.as_staff.save_dsp("C", "nonsense", "x")
        with self.assertRaisesRegex(Exception, "invalid-index"):
            self.as_staff.save_dsp("bad", "E_nature", "tod_led")
        with self.assertRaisesRegex(Exception, "invalid-value"):
            self.as_staff.save_dsp("C", "E_nature", "nonsense")
        with self.assertRaisesRegex(Exception, "invalid-selection"):
            self.as_staff.save_dsp("C", "sel_E", [99])
        with self.assertRaisesRegex(Exception, "read-only-role"):
            self.as_reader.save_dsp("C", "E_nature", "tod_led")

    def test_timing_follows_the_cra(self):
        design = self.design()
        allowed_interim = design.tod_level in ("minimal", "low")
        if not allowed_interim:
            with self.assertRaisesRegex(Exception, "timing-not-permitted"):
                self.as_staff.save_dsp("C", "E_timing", "interim_6")
        self.as_staff.save_dsp("C", "E_timing", "period_end")
        self.assertEqual(design.timing, "period_end")
        self.as_staff.save_dsp("C", "E_timing", "")
        self.assertFalse(design.timing)

    def test_analytics_led_barred_on_a_significant_risk(self):
        cell = self.engagement.sudo()._ea_cra_cell("C", "E")
        risk = self.as_staff.add_risk("Détournement de fonds", significant=True, index="C", assertions=["E"])
        self.assertTrue(risk)
        cell.invalidate_recordset()
        self.assertTrue(self.design().significant)
        with self.assertRaisesRegex(Exception, "nature-not-permitted"):
            self.as_staff.save_dsp("C", "E_nature", "sap_led")

    def test_screen_writes_are_routed(self):
        design = self.design().with_user(self.staff)
        design.write({"nature": "tod_led"})
        self.assertEqual(design.sudo().nature, "tod_led")
        with self.assertRaisesRegex(Exception, "invalid-field"):
            design.write({"significant": False})
        choice = design.sudo().choice_ids[0].with_user(self.staff)
        choice.write({"selected": True})
        self.assertEqual(design.sudo().selected_count, 1)
        self.assertNotIn("C", self.engagement.sudo()._ea_dsp_gaps())
        choice.write({"selected": False})
        self.assertEqual(design.sudo().selected_count, 0)
        self.assertIn("C", self.engagement.sudo()._ea_dsp_gaps())

    def test_a_design_puts_the_paper_on_the_file_and_generates_steps(self):
        design = self.design()
        self.as_staff.save_dsp("C", "sel_E", [design.choice_ids[0].position])
        self.assertTrue(self.item(self.engagement, "E4.8") or self.engagement.sudo().file_item_ids)
        from odoo.addons.ea_audit_tools.services.lead_classes import INDEX_SECTION

        task = INDEX_SECTION["C"]
        created = self.as_staff.generate_psp(task)
        self.assertEqual(created, 1)
        self.assertEqual(self.as_staff.generate_psp(task), 0)
        self.as_staff.add_dsp_osp("C", "Vérifier les comptes dormants", ["E"])
        self.assertEqual(self.as_staff.generate_psp(task), 1)
        self.assertEqual(self.as_staff.generate_psp(task), 0)

    def test_osp_refusals(self):
        with self.assertRaisesRegex(Exception, "invalid-osp"):
            self.as_staff.add_dsp_osp("C", " ")
        with self.assertRaisesRegex(Exception, "invalid-osp"):
            self.as_staff.add_dsp_osp("C", "x", nature="nope")

    def test_excel_round_trip(self):
        self.as_staff.save_dsp("C", "E_nature", "tod_led")
        _name, content = self.as_staff.ea_export_xlsx("dsp")
        self.as_staff.ea_import_xlsx("dsp", "s55.xlsx", content)
        self.assertEqual(self.design().nature, "tod_led")

    def test_outsider(self):
        self.engagement.sudo()._ea_sync_dsp()
        for model in ("ea.audit.dsp.design", "ea.audit.dsp.choice", "ea.audit.dsp.osp", "ea.audit.sap.procedure"):
            self.assertFalse(self.env[model].with_user(self.outsider).search([]), model)


@tagged("post_install", "-at_install")
class TestPrograms(DesignCase):
    def task(self):
        items = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.engagement.id), ("code", "=like", "E4.%")], limit=1)
        return items.code

    def test_generation_is_idempotent_and_reads_the_library(self):
        code = "E3.1" if self.item(self.engagement, "E3.1") else self.task()
        steps = self.env["ea.audit.program.step"].sudo().search([("engagement_id", "=", self.engagement.id), ("file_item_id.code", "=", code)])
        steps.unlink()
        created = self.as_staff.generate_program(code)
        self.assertGreater(created, 0)
        self.assertEqual(self.as_staff.generate_program(code), 0)

    def test_custom_step_and_refusals(self):
        code = self.task()
        step = self.as_staff.add_custom_step(code, "Tester X", ["C"])
        self.assertEqual(step.sudo().source, "custom")
        with self.assertRaisesRegex(Exception, "description-required"):
            self.as_staff.add_custom_step(code, " ")
        with self.assertRaisesRegex(Exception, "not-found"):
            self.as_staff.generate_program("Z9.9")
        self.assertEqual(self.as_staff.section_coverage(code), [])


@tagged("post_install", "-at_install")
class TestSap(DesignCase):
    def save(self, **over):
        values = dict(index_code="C", assertion="E", expectation_model="Solde N-1 + flux", expected_value=800)
        values.update(over)
        return self.as_staff.save_sap(**values).sudo()

    def test_saved_with_a_snapshot_and_the_tb_actual(self):
        procedure = self.save(actual_value=1)
        self.assertEqual(procedure.actual_source, "tb")
        self.assertEqual(procedure.actual_value, 700)
        self.assertEqual(procedure.difference, -100)
        self.assertEqual(procedure.threshold_pct, 25)
        self.assertEqual(procedure.evaluation in ("within", "above"), True)
        self.assertEqual(self.as_staff.sap_counts_by_index()["C"]["total"], 1)

    def test_replaced_on_the_same_key(self):
        first = self.save()
        second = self.save(expected_value=900, conclusion="supported")
        self.assertEqual(first, second)
        self.assertEqual(self.as_staff.sap_counts_by_index()["C"]["concluded"], 1)

    def test_refusals(self):
        for over, code in (
            ({"index_code": "ZZZ"}, "invalid-index"), ({"assertion": "RO"}, "invalid-assertion"), ({"expectation_model": " "}, "sap-expectation-required"),
            ({"expected_value": None}, "sap-expected-value-required"), ({"override_pct": 101, "override_reason": "x"}, "sap-threshold-out-of-range"),
            ({"override_pct": 50}, "sap-override-reason-required"), ({"conclusion": "nope"}, "invalid-conclusion"),
        ):
            with self.assertRaisesRegex(Exception, code):
                self.save(**over)

    def test_an_override_replaces_the_firm_percentage(self):
        procedure = self.save(override_pct=100, override_reason="Compte stable")
        self.assertEqual(procedure.threshold_amount, procedure.performance_materiality)

    def test_firm_thresholds(self):
        Settings = self.env["ea.audit.sap.settings"]
        self.assertEqual(Settings._ea_get(), {"low": 75, "moderate": 50, "high": 25})
        with self.assertRaises(Exception):
            Settings.with_user(self.staff).set_thresholds(70, 40, 20)
        with self.assertRaisesRegex(Exception, "sap-threshold-order"):
            Settings.with_user(self.admin).set_thresholds(20, 40, 70)
        with self.assertRaisesRegex(Exception, "sap-threshold-out-of-range"):
            Settings.with_user(self.admin).set_thresholds(170, 40, 20)
        Settings.with_user(self.admin).set_thresholds(70, 40, 20)
        self.assertEqual(Settings._ea_get()["low"], 70)

    def test_board_and_export(self):
        self.save()
        self.assertIn("Procedures", str(self.engagement.with_user(self.staff).sap_board_html))
        name, _content = self.as_staff.ea_export_xlsx("sap")
        self.assertIn("sap", name)
