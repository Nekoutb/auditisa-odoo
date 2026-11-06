"""The client's findings on the tools: one test per fix, a computed example for each number."""
import base64
import io

from lxml import etree
from openpyxl import load_workbook

from odoo.tests import tagged
from odoo.tools import file_open

from odoo.addons.ea_audit_tools.models.tool_record import decimal_label, fcfa
from odoo.addons.ea_audit_tools.services.tb import infer_tb_mapping

from .common import ToolsCase, UNBALANCED_CSV, to_bytes
from .test_gl import GlCase

PRIOR_2024 = """Compte;Libellé;Solde ouverture débit;Solde ouverture crédit;Mouvement débit;Mouvement crédit
101000;Capital;0;0;0;50000000
121000;Report;0;0;0;8000000
521000;Banque;0;0;58000000;0
601000;Achats;0;0;128000000;0
701000;Ventes;0;0;0;150000000
521001;Banque 2;0;0;22000000;0
"""
#: 2025: the 2024 balance sheet carried, 22M of result now in 121000.
CURRENT_2025 = """Compte;Libellé;Solde ouverture débit;Solde ouverture crédit;Mouvement débit;Mouvement crédit
101000;Capital;0;50000000;0;0
121000;Report;0;30000000;0;0
521000;Banque;80000000;0;28000000;0
601000;Achats;0;0;147000000;0
701000;Ventes;0;0;0;175000000
"""
NO_OPENINGS = """Compte;Libellé;Mouvement débit;Mouvement crédit
101000;Capital;0;1000
521000;Banque;1000;0
"""


@tagged("post_install", "-at_install")
class TestComparatives(ToolsCase):
    """F012, against the figures of the source."""

    def setUp(self):
        super().setUp()
        self.prior = self.make_engagement(year=2024)
        self.seat(self.prior, self.staff, "staff")
        self.prior.with_user(self.staff).import_trial_balance("b24.csv", to_bytes(PRIOR_2024))
        self.import_tb(CURRENT_2025)
        self.schedules = {s.index_code: s for s in self.env["ea.audit.lead.schedule"].sudo().search([("engagement_id", "=", self.engagement.id)])}

    def test_lead_reads_the_prior_file_closing(self):
        revenue = next(s for s in self.schedules.values() if "701000" in s.line_ids.mapped("account_code"))
        self.assertEqual(revenue.prior, -150000000)
        self.assertEqual(revenue.prior_source, "prior_file")
        lines = self.env["ea.audit.lead.line"].sudo().search([("engagement_id", "=", self.engagement.id)])
        by_account = {line.account_code: line.prior for line in lines}
        # 50M + 8M: the 22M of last year's result sat in classes 6 and 7, as the source's own closing shows
        self.assertEqual(by_account["101000"] + by_account["121000"], -58000000)

    def test_lead_and_analytical_review_agree_on_every_total(self):
        review = self.as_staff.analytical_review()
        self.assertTrue(review["hasPrior"])
        lines = self.env["ea.audit.lead.line"].sudo().search([("engagement_id", "=", self.engagement.id)])
        self.assertEqual(sum(lines.mapped("prior")), sum(line["prior"] for line in review["lines"]))
        self.assertEqual(sum(line["prior"] for line in review["lines"]), 0)  # a balanced year balances
        ratios = {row["key"]: row for row in review["ratios"]}
        self.assertEqual(ratios["revenue"]["prior"], 150000000)
        self.assertIn("2024", self.engagement.sudo().lead_prior_label)

    def test_financial_analysis_uses_the_same_year(self):
        rows = {row["key"]: row for row in self.as_staff.financial_analysis_view()["rows"]}
        self.assertEqual(rows["net"]["prior"], 14.67)  # 22M / 150M: blank before, from openings
        self.assertEqual(rows["gross"]["prior"], 14.67)
        self.assertEqual(rows["equity_ratio"]["prior"], 100)  # 80M of equity, 80M of assets

    def test_uploaded_prior_year_tb_still_wins(self):
        self.import_tb(PRIOR_2024.replace("150000000", "160000000").replace("128000000", "138000000"), timing="prior_year")
        self.assertEqual(self.engagement.sudo()._ea_comparatives()[0], "prior_year_tb")
        self.assertEqual(self.as_staff.analytical_review()["ratios"][0]["prior"], 160000000)

    def test_an_account_closed_since_keeps_its_comparative(self):
        lines = self.env["ea.audit.lead.line"].sudo().search([("engagement_id", "=", self.engagement.id)])
        gone = lines.filtered(lambda line: line.account_code == "521001")
        self.assertEqual((gone.closing, gone.prior), (0, 22000000))

    def test_schedules_built_before_the_rule_refresh_on_opening(self):
        self.env["ea.audit.lead.schedule"].sudo().search([("engagement_id", "=", self.engagement.id)]).write({"prior": 0, "prior_source": "opening"})
        self.as_staff.action_tool_lead()
        schedules = self.env["ea.audit.lead.schedule"].sudo().search([("engagement_id", "=", self.engagement.id)])
        self.assertEqual(set(schedules.mapped("prior_source")), {"prior_file"})


@tagged("post_install", "-at_install")
class TestFinancialAnalysisScreen(ToolsCase):
    def setUp(self):
        super().setUp()
        self.env["res.lang"]._activate_lang("fr_FR")
        self.env["ir.module.module"].search([("name", "=", "ea_audit_tools")])._update_translations(["fr_FR"], overwrite=True)

    def test_f064_group_rows_add_nothing_together(self):
        self.import_tb()
        self.as_staff.action_tool_financial()
        Ratio = self.env["ea.audit.fa.ratio"].with_user(self.staff)
        for name in ("current", "prior", "variance"):
            self.assertFalse(Ratio._fields[name].aggregator, name)
        groups = Ratio.formatted_read_group([("engagement_id", "=", self.engagement.id)], ["group"], ["__count"])
        self.assertEqual(sum(row["__count"] for row in groups), 20)

    def test_f064_groups_and_units_read_in_french(self):
        self.import_tb()
        self.as_staff.with_context(lang="fr_FR").action_tool_financial()
        Ratio = self.env["ea.audit.fa.ratio"].sudo().with_context(lang="fr_FR")
        labels = dict(Ratio._fields["group"]._description_selection(Ratio.env))
        self.assertEqual(labels["Liquidity"], "Liquidité")
        self.assertEqual(labels["Investment"], "Rentabilité des investissements")
        dso = Ratio.search([("engagement_id", "=", self.engagement.id), ("key", "=", "dso")])
        self.assertEqual(dso.unit, "jours")
        self.assertIn("grand livre", dso.note)
        roe = Ratio.search([("engagement_id", "=", self.engagement.id), ("key", "=", "roe")])
        self.assertIn("après impôt", roe.label)
        self.assertIn("89", roe.formula)


@tagged("post_install", "-at_install")
class TestSadHeader(ToolsCase):
    def test_f019_result_from_the_tb_overridable(self):
        self.import_tb(CURRENT_2025)  # 175M - 147M = 28M
        engagement = self.engagement.sudo()
        self.assertEqual(engagement.sad_income_label, fcfa(28000000, "en"))
        self.assertIn("trial balance", engagement.sad_income_note)
        self.assertEqual(engagement._ea_sad_view()["meta"]["income_after_tax"], 28000000)
        meta = engagement._ea_sad_meta()
        self.assertEqual(meta.income_after_tax_tb, 28000000)
        meta.income_after_tax = 30000000
        engagement.invalidate_recordset(["sad_income_label", "sad_income_note"])
        self.assertEqual(engagement.sad_income_label, fcfa(30000000, "en"))
        self.assertIn(fcfa(28000000, "en"), engagement.sad_income_note)

    def test_f019_a_dash_gives_its_reason(self):
        engagement = self.engagement.sudo()
        self.assertEqual(engagement.sad_income_label, "—")
        self.assertIn("No trial balance", engagement.sad_income_note)
        self.assertEqual(engagement.mat_overall_label, "—")
        self.assertIn("P6.1", engagement.mat_overall_note)

    def test_f019_threshold_is_explained_with_its_sum(self):
        # 2% of 5 800 total assets = 116 overall; 75% = 87 performance; 116 - 87 = 29.
        self.approve()
        engagement = self.engagement.sudo()
        materiality = engagement._ea_materiality_dict()
        threshold = materiality["overall"] - materiality["performance"]
        note = engagement.b5_threshold_note
        for amount in (materiality["overall"], materiality["performance"], threshold):
            self.assertIn(fcfa(amount, "en"), note)
        self.assertTrue(engagement.mat_performance_label != "—")

    def test_f019_no_minus_zero(self):
        self.assertEqual(fcfa(-0.4, "fr_FR"), "0 FCFA")
        self.assertEqual(fcfa(-1000, "fr_FR"), "-1 000 FCFA")


@tagged("post_install", "-at_install")
class TestLedgerRecord(GlCase):
    def test_m10_a_debit_credit_ledger_shows_its_debits(self):
        # 1 000 + 1 000 + 50 of debits across the file; debit - credit over the same rows nets to the 50 of the line with no entry number
        dataset_id = self.built()
        dataset = self.env["ea.audit.dataset"].sudo().browse(dataset_id)
        self.assertEqual(dataset.display_total, 2050)
        self.assertEqual(dataset.total_amount, 50)
        self.assertIn("debits", dataset.display_total_note)

    def test_m10_a_balanced_ledger_does_not_read_zero(self):
        content = "Compte;N° écriture;Libellé;Date;Débit;Crédit\n411000;V1;Facture;15/01/2025;700;\n701000;V1;Facture;15/01/2025;;700\n"
        mapping = {"account": "Compte", "jeNumber": "N° écriture", "jeDescription": "Libellé", "journalDate": "Date", "debit": "Débit", "credit": "Crédit"}
        dataset = self.env["ea.audit.dataset"].sudo().browse(self.import_ledger(content, mapping)["datasetId"])
        self.assertEqual(dataset.total_amount, 0)
        self.assertEqual(dataset.display_total, 700)

    def test_m10_a_single_amount_column_keeps_its_total(self):
        dataset = self.env["ea.audit.dataset"].sudo().browse(self.as_staff.create_dataset(
            "ar_open_items", "ar.csv", b"Client;Montant\nA;100\nB;250\n", mapping={"amount": "Montant"},
        )["datasetId"])
        self.assertEqual(dataset.display_total, 350)
        self.assertEqual(dataset.display_total_note, "Montant")

    def test_m12_the_checks_group_as_the_language(self):
        dataset_id = self.built()
        html = self.env["ea.audit.dataset"].with_user(self.staff).with_context(lang="fr_FR").browse(dataset_id).population_html
        self.assertRegex(str(html), r"Débits 2\s000 contre crédits")
        self.assertNotIn("2,000", str(html))


@tagged("post_install", "-at_install")
class TestLeadChecks(ToolsCase):
    def test_f018_the_strip_when_all_holds(self):
        self.import_tb()
        html = str(self.engagement.sudo().lead_checks_html)
        self.assertIn("Trial balance balances", html)
        self.assertIn("Assets = equity and liabilities", html)
        self.assertIn("Every account is on a lead index", html)
        self.assertNotIn("o_ea_chip_bad", html)

    def test_f018_hidden_indexes_are_named(self):
        self.import_tb()
        engagement = self.engagement.sudo()
        self.assertIn("are not shown", engagement.lead_hidden_note)
        shown = set(engagement.lead_schedule_ids.mapped("index_code"))
        listed = engagement.lead_hidden_note.split(": ")[1].split(", ")
        self.assertFalse(shown & set(listed))

    def test_f018_an_account_on_no_index_is_counted(self):
        content = "Compte;Libellé;Mouvement débit;Mouvement crédit\n101000;Capital;0;1000\n521000;Banque;900;0\n999999;Inconnu;100;0\n"
        self.import_tb(content)
        html = str(self.engagement.sudo().lead_checks_html)
        self.assertIn("1 account(s) on no lead index: 999999", html)
        self.assertIn("o_ea_chip_bad", html)

    def test_f018_an_invalid_import_says_why(self):
        # 1 000 of debits against 900 of credits: a difference of 100.
        result = self.import_tb(UNBALANCED_CSV)
        self.assertEqual(result["summary"]["status"], "invalid")
        reason = self.engagement.sudo().tb_invalid_reason
        self.assertIn("Movements do not balance", reason)
        self.assertIn("100", reason)
        self.import_tb()
        self.assertFalse(self.engagement.sudo().tb_invalid_reason)

    def test_f018_the_wizard_notifies_the_refusal(self):
        wizard = self.env["ea.audit.tb.import.wizard"].with_user(self.staff).create({
            "engagement_id": self.engagement.id, "file": base64.b64encode(to_bytes(UNBALANCED_CSV)), "filename": "b.csv",
        })
        wizard.action_preview()
        action = wizard.action_import()
        self.assertEqual(action["params"]["type"], "danger")
        self.assertIn("Movements do not balance", action["params"]["message"])


@tagged("post_install", "-at_install")
class TestOpeningsWarning(ToolsCase):
    def test_f016_warned_when_nothing_stands_behind_the_prior_year(self):
        wizard = self.env["ea.audit.tb.import.wizard"].with_user(self.staff).create({
            "engagement_id": self.engagement.id, "file": base64.b64encode(to_bytes(NO_OPENINGS)), "filename": "b.csv",
        })
        wizard.action_preview()
        action = wizard.action_import()
        self.assertEqual(action["params"]["type"], "warning")
        self.assertIn("opening balances", action["params"]["message"].lower())
        self.assertTrue(self.engagement.sudo().tb_openings_warning)

    def test_f016_not_warned_with_openings(self):
        self.import_tb()
        self.assertFalse(self.engagement.sudo().tb_openings_warning)

    def test_f016_not_warned_with_a_prior_file(self):
        prior = self.make_engagement(year=2024)
        self.seat(prior, self.staff, "staff")
        prior.with_user(self.staff).import_trial_balance("b24.csv", to_bytes(NO_OPENINGS))
        self.import_tb(NO_OPENINGS)
        self.assertFalse(self.engagement.sudo().tb_openings_warning)

    def test_f016_the_template_is_read_back_by_the_import(self):
        for fr in (True, False):
            name, content = self.as_staff._ea_export_tb_template(fr)
            self.assertIn("modele" if fr else "template", name)
            headers = [cell.value for cell in load_workbook(io.BytesIO(content)).active[1]]
            mapping = infer_tb_mapping(headers)
            for column, header in {"account": headers[0], "label": headers[1], "openingDebit": headers[2], "openingCredit": headers[3], "debit": headers[4], "credit": headers[5]}.items():
                self.assertEqual(mapping.get(column), header, column)
        self.assertIn("tb_template", self.as_staff.action_export_tb_template()["url"])

    def test_f016_the_dialog_states_the_columns(self):
        arch = self.env.ref("ea_audit_tools.view_tb_import_wizard").arch
        self.assertIn("Accepted: a .csv or .xlsx file", arch)
        self.assertIn("template_html", arch)
        wizard = self.env["ea.audit.tb.import.wizard"].with_user(self.staff).new({"engagement_id": self.engagement.id})
        self.assertIn("/ea_audit_tools/export/tb_template/%d" % self.engagement.id, str(wizard.template_html))


@tagged("post_install", "-at_install")
class TestToolsWithoutData(ToolsCase):
    def test_f065_the_catalogue_reads_with_no_ledger(self):
        self.assertFalse(self.env["ea.audit.dataset"].sudo().search_count([("engagement_id", "=", self.engagement.id)]))
        html = str(self.as_staff.gl_catalogue_html)
        self.assertEqual(html.count("<tr>"), 31)  # the header and the thirty analytics
        action = self.as_staff.action_tool_gl_catalogue()
        self.assertEqual(action["res_id"], self.engagement.id)
        self.assertIn("thirty analytics", str(self.as_staff.action_tool_gl()["help"]))
        with self.assertRaises(Exception):
            self.as_outsider.action_tool_gl_catalogue()

    def test_f066_no_way_forward_without_a_file(self):
        for xmlid, method in (("view_dataset_import_wizard", "action_preview"), ("view_tb_import_wizard", "action_preview")):
            arch = etree.fromstring(self.env.ref("ea_audit_tools.%s" % xmlid).arch)
            button = arch.xpath("//footer/button[@name='%s']" % method)[0]
            self.assertIn("not file", button.get("invisible"))
            stand_in = arch.xpath("//footer/span[contains(@class, 'disabled')]")[0]
            self.assertEqual(stand_in.get("aria-disabled"), "true")
            self.assertIn("or file", stand_in.get("invisible"))

    def test_f068_the_grid_names_the_first_step_missing(self):
        as_staff = self.as_staff.sudo().with_user(self.staff)
        self.assertEqual(self.engagement.sudo().cra_missing, "tb")
        self.import_tb()
        self.engagement.sudo().invalidate_recordset(["cra_missing"])
        self.assertEqual(self.engagement.sudo().cra_missing, "materiality")
        self.approve()
        self.engagement.sudo().invalidate_recordset(["cra_missing"])
        expected = "significance" if not self.engagement.sudo().cra_row_ids else False
        self.assertEqual(self.engagement.sudo().cra_missing, expected)
        self.assertTrue(as_staff.action_tool_cra())

    def test_f068_the_board_links_each_step(self):
        arch = self.env.ref("ea_audit_tools.view_engagement_cra_board").arch
        for method in ("action_tool_tb", "action_tool_materiality", "action_tool_significance"):
            self.assertIn(method, arch)


@tagged("post_install", "-at_install")
class TestRisksAndDesign(ToolsCase):
    def test_f067_cells_count_the_register(self):
        # Two risks high x high, one of them significant; one low x medium: 3 risks over the two presumed ones.
        Risk = self.env["ea.audit.risk"].sudo()
        before = Risk.search_count([("engagement_id", "=", self.engagement.id)])
        common = {"engagement_id": self.engagement.id, "description": "Risk", "level": "fs"}
        Risk.create({**common, "likelihood": "high", "magnitude": "high", "significant": True})
        Risk.create({**common, "likelihood": "high", "magnitude": "high"})
        Risk.create({**common, "likelihood": "low", "magnitude": "medium"})
        high_high = Risk.search_count([("engagement_id", "=", self.engagement.id), ("likelihood", "=", "high"), ("magnitude", "=", "high")])
        tree = etree.fromstring("<div>%s</div>" % self.as_staff.risk_heatmap_html, etree.HTMLParser())
        cell = tree.xpath("//td[@data-ea-cell='high-high']")[0]
        self.assertEqual(int(cell.xpath(".//b/text()")[0]), high_high)
        self.assertTrue(cell.xpath(".//div[contains(text(), 'significant')]"))
        self.assertEqual(int(tree.xpath("//td[@data-ea-cell='low-medium']//b/text()")[0]), 1 + Risk.search_count([("engagement_id", "=", self.engagement.id), ("likelihood", "=", "low"), ("magnitude", "=", "medium"), ("description", "!=", "Risk")]))
        self.assertIn("%s risks" % (before + 3), tree.xpath("//table/@aria-label")[0])

    def test_f067_ticks_and_legend_follow_the_language(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        self.env["ir.module.module"].search([("name", "=", "ea_audit_tools")])._update_translations(["fr_FR"], overwrite=True)
        english = str(self.as_staff.risk_heatmap_html)
        for word in ("Likelihood", "Magnitude", "Inherent rating", "Medium"):
            self.assertIn(word, english)
        french = str(self.as_staff.with_context(lang="fr_FR").risk_heatmap_html)
        for word in ("Probabilité", "Ampleur", "Élevé"):
            self.assertIn(word, french)
        tile = self.env.ref("ea_audit_tools.tile_risk_heatmap").with_user(self.staff)
        self.assertTrue(tile.available)
        action = tile.with_context(ea_engagement_id=self.engagement.id).action_open_tool()
        self.assertEqual(action["res_id"], self.engagement.id)

    def test_f041_a_picker_reads_in_words(self):
        assertion = self.env.ref("ea_audit_tools.assertion_RO")
        self.assertEqual(assertion.display_name, "RO — Rights and obligations")
        self.assertIn("Rights and obligations", self.env.ref("ea_audit_tools.view_risk_wizard").arch)

    def test_f041_m05_design_shows_words_not_codes(self):
        design = self.env["ea.audit.dsp.design"].sudo().create({
            "engagement_id": self.engagement.id, "index_code": "E", "assertion": "RO", "tod_level": "high_sr",
        })
        self.assertEqual(design.tod_level_label, "High +SR")
        self.assertEqual(design.assertion_label, "RO — Rights and obligations")
        moderate = design.copy({"assertion": "C", "tod_level": "moderate"})
        self.assertEqual(moderate.tod_level_label, "Moderate")
        arch = etree.fromstring(self.env.ref("ea_audit_tools.view_dsp_design_list").arch)
        self.assertTrue(arch.xpath("//field[@name='tod_level_label']"))
        self.assertFalse(arch.xpath("//field[@name='tod_level']"))

    def test_f063_journal_entries_show_the_prerequisites(self):
        studio = self.env["ea.audit.je.studio"].with_user(self.staff).create({"engagement_id": self.engagement.id})
        html = str(studio.prerequisites_html)
        self.assertIn("S2.1", html)
        self.assertIn("S3.1", html)
        self.assertIn("General ledger imported", html)
        self.assertEqual(html.count("o_ea_chip_warn"), 3)
        item = self.item(self.engagement, "S3.1")
        self.assertIn("/odoo/%d/ea_audit_paper" % item.id, html)
        self.assertIn("prerequisites_html", self.env.ref("ea_audit_tools.view_je_studio_form").arch)


@tagged("post_install", "-at_install")
class TestFormsAndFormats(ToolsCase):
    def test_f083_every_form_is_listed_and_a_left_out_one_says_why(self):
        domain = self.as_staff.action_tool_forms()["domain"]
        items = self.env["ea.audit.file.item"].with_user(self.staff).search(domain)
        self.assertEqual(len(items), len(self.engagement.sudo().file_item_ids))
        out = self.engagement.sudo()._ea_e4_out_of_scope()
        self.assertTrue(out)
        chip = out[:1].with_user(self.staff)
        self.assertEqual(chip.scope_chip, "Out of scope")
        self.assertIn("S5.5", chip.scope_reason)
        conditional = items.filtered("conditional")[:1]
        if conditional:
            self.assertEqual(conditional.scope_chip, "Out of scope")
            self.assertIn("Conditional", conditional.scope_reason)
        kept = (items - items.filtered("conditional") - out.with_user(self.staff))[:1]
        self.assertFalse(kept.scope_chip)

    def test_f087_one_currency_word_in_the_checklist(self):
        with file_open("ea_audit_papers/data/papers/E6.10.json") as handle:
            self.assertNotIn("F CFA", handle.read())
        self.assertNotIn("F CFA", str(self.env["ea.audit.paper.def"].sudo().search([("code", "=", "E6.10"), ("is_current", "=", True)]).definition))

    def test_f087_decimals_follow_the_language(self):
        self.assertEqual(decimal_label(0.3, "fr"), "0,3")
        self.assertEqual(decimal_label(0.3, "fr_FR"), "0,3")
        self.assertEqual(decimal_label(0.3, "en"), "0.3")
