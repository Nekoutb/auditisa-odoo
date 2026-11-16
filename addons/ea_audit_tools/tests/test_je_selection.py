import io

from openpyxl import load_workbook

from odoo.tests import tagged

from .common import ToolsCase, to_bytes

# VE001 revenue against cash (pairing), BQ002 on a Saturday, HO001 on 1 January, RO001 round, SR001
# self-reviewed, NO001 with no description, OD001 filler, YE001 long entry at the close.
LEDGER = """Compte;N° écriture;Libellé;Date;Débit;Crédit;Préparé;Réviseur;Approuvé
521000;VE001;Vente au comptant du mois;15/03/2025;500;;Awa;Ben;Cid
701000;VE001;Vente au comptant du mois;15/03/2025;;500;Awa;Ben;Cid
411000;BQ002;Facture client janvier;11/01/2025;700;;Awa;Ben;Cid
401000;BQ002;Facture client janvier;11/01/2025;;700;Awa;Ben;Cid
411000;HO001;Facture du jour de l'an;01/01/2025;300;;Awa;Ben;Cid
401000;HO001;Facture du jour de l'an;01/01/2025;;300;Awa;Ben;Cid
411000;RO001;Facture importante du mois;12/03/2025;200000;;Awa;Ben;Cid
401000;RO001;Facture importante du mois;12/03/2025;;200000;Awa;Ben;Cid
411000;SR001;Facture revue par auteur;13/03/2025;10;;Dan; DAN ;Cid
401000;SR001;Facture revue par auteur;13/03/2025;;10;Dan; DAN ;Cid
411000;AP001;Facture approuvee par auteur;14/03/2025;20;;Eve;Ben;EVE
401000;AP001;Facture approuvee par auteur;14/03/2025;;20;Eve;Ben;EVE
411000;NO001;;17/03/2025;30;;Awa;Ben;Cid
401000;NO001;;17/03/2025;;30;Awa;Ben;Cid
411000;OD001;Divers 12 OD;18/03/2025;40;;Awa;Ben;Cid
401000;OD001;Divers 12 OD;18/03/2025;;40;Awa;Ben;Cid
411000;YE001;Ajustement de fin d'exercice;30/12/2025;50;;Awa;Ben;Cid
411000;YE001;Ajustement de fin d'exercice;30/12/2025;60;;Awa;Ben;Cid
401000;YE001;Ajustement de fin d'exercice;30/12/2025;;110;Awa;Ben;Cid
"""
MAPPING = {
    "account": "Compte", "jeNumber": "N° écriture", "jeDescription": "Libellé", "journalDate": "Date", "debit": "Débit", "credit": "Crédit",
    "preparedBy": "Préparé", "reviewer": "Réviseur", "approvedBy": "Approuvé",
}


@tagged("post_install", "-at_install")
class TestJeSelection(ToolsCase):
    def setUp(self):
        super().setUp()
        self.dataset = self.as_staff.create_dataset("journal_entries", "gl.csv", to_bytes(LEDGER), mapping=MAPPING)["datasetId"]
        self.as_staff.gl_build_projection(self.dataset)

    def entries(self, criterion, **request):
        params = request.pop("params", {})
        result = self.as_staff.je_run_selection(self.dataset, {"criteria": [criterion], "params": dict(params, locale="en"), **request})
        return sorted({line["jeNumber"] for line in result["lines"]})

    def test_each_criterion_finds_its_lines(self):
        self.assertEqual(self.entries("weekend-posting"), ["BQ002", "VE001"])
        self.assertEqual(self.entries("no-description"), ["NO001"])
        self.assertEqual(self.entries("public-holiday"), ["HO001"])
        self.assertEqual(self.entries("round-amount"), ["RO001"])
        self.assertEqual(self.entries("unusual-pairing"), ["VE001"])
        self.assertEqual(self.entries("preparer-is-reviewer"), ["SR001"])
        self.assertEqual(self.entries("preparer-is-approver"), ["AP001"])
        self.assertIn("OD001", self.entries("incomplete-description"))
        self.assertEqual(self.entries("year-end-volume"), ["YE001"])

    def test_a_line_appears_once_with_all_its_reasons(self):
        result = self.as_staff.je_run_selection(self.dataset, {"criteria": ["weekend-posting", "unusual-pairing"], "params": {"locale": "en"}})
        line = next(line for line in result["lines"] if line["jeNumber"] == "VE001")
        self.assertEqual(len(line["reasons"]), 2)
        self.assertEqual(len([l for l in result["lines"] if l["lineNo"] == line["lineNo"]]), 1)
        self.assertEqual(result["lines"][0]["jeNumber"], "VE001")
        self.assertEqual(result["criteria"][0]["matchedEntries"], 2)

    def test_thresholds_are_clamped(self):
        result = self.as_staff.je_run_selection(self.dataset, {"criteria": ["year-end-volume"], "params": {"topEntries": 9999, "yearEndDays": 0, "locale": "en"}})
        self.assertEqual(result["criteria"][0]["settings"]["topEntries"], 100)
        self.assertEqual(result["criteria"][0]["settings"]["yearEndDays"], 1)

    def test_rules_and_their_refusals(self):
        def run(rules, mode="any"):
            return self.as_staff.je_run_selection(self.dataset, {"userRules": rules, "userRulesMode": mode, "params": {"locale": "en"}})

        rule = {"field": "jeNumber", "operator": "startsWith", "value": "ve"}
        self.assertEqual({l["jeNumber"] for l in run([rule])["lines"]}, {"VE001"})
        other = {"field": "absAmount", "operator": "greaterOrEqual", "value": "150000"}
        self.assertEqual({l["jeNumber"] for l in run([rule, other])["lines"]}, {"VE001", "RO001"})
        self.assertEqual(run([rule, other], "all")["selectedLines"], 0)
        percent = {"field": "jeDescription", "operator": "contains", "value": "%"}
        self.assertEqual(run([percent])["selectedLines"], 0)
        date = {"field": "journalDate", "operator": "between", "value": "2025-12-01", "value2": "2025-12-31"}
        self.assertEqual({l["jeNumber"] for l in run([date])["lines"]}, {"YE001"})
        with self.assertRaisesRegex(Exception, "invalid-rule-field"):
            run([{"field": "nope", "operator": "equals", "value": "x"}])
        with self.assertRaisesRegex(Exception, "invalid-rule-operator"):
            run([{"field": "debit", "operator": "contains", "value": "x"}])
        with self.assertRaisesRegex(Exception, "invalid-rule-value"):
            run([{"field": "journalDate", "operator": "before", "value": "31/12/2025"}])
        with self.assertRaisesRegex(Exception, "no-criteria"):
            self.as_staff.je_run_selection(self.dataset, {"criteria": ["user-defined"]})

    def test_an_empty_calendar_says_so(self):
        result = self.as_staff.je_run_selection(self.dataset, {"criteria": ["public-holiday"], "params": {"country": "ZZ", "locale": "en"}})
        self.assertEqual(result["selectedLines"], 0)
        self.assertIn("calendar is empty", result["notes"][0])

    def test_a_firm_date_is_read_and_takes_precedence(self):
        with self.assertRaisesRegex(Exception, "invalid-country"):
            self.as_staff.add_firm_holiday("CMR", "2025-03-13", "x", "y")
        with self.assertRaisesRegex(Exception, "invalid-date"):
            self.as_staff.add_firm_holiday("CM", "13/03/2025", "x", "y")
        with self.assertRaisesRegex(Exception, "label-required"):
            self.as_staff.add_firm_holiday("CM", "2025-03-13", "", "y")
        holiday = self.as_staff.add_firm_holiday("CM", "2025-03-13", "Eid", "Ramadan", engagement_scoped=True)
        self.assertIn("SR001", self.entries("public-holiday"))
        self.assertEqual([h for h in self.as_staff.list_holidays() if h["date"] == "2025-03-13"][0]["origin"], "firm")
        holiday.with_user(self.staff).remove()
        self.assertNotIn("SR001", self.entries("public-holiday"))

    def test_recording_the_design_keeps_the_history(self):
        request = {"criteria": ["round-amount"], "params": {"locale": "en"}}
        first = self.as_staff.je_record_design(self.dataset, request).sudo()
        self.assertEqual(first.selected_lines, 2)
        self.assertIn("Round-number amount", first.summary)
        second = self.as_staff.je_record_design(self.dataset, {"criteria": ["no-description"], "params": {}}).sudo()
        self.assertFalse(first.is_current)
        self.assertTrue(second.is_current)
        with self.assertRaisesRegex(Exception, "je-design-empty"):
            self.as_staff.je_record_design(self.dataset, {"userRules": [{"field": "jeNumber", "operator": "equals", "value": "nothing"}]})
        with self.assertRaisesRegex(Exception, "read-only-role"):
            self.as_reader.je_record_design(self.dataset, request)
        with self.assertRaises(Exception):
            first.with_user(self.manager).unlink()

    def test_a_run_writes_nothing_and_answers_a_reader_and_an_archive(self):
        self.as_reader.je_run_selection(self.dataset, {"criteria": ["round-amount"]})
        self.assertFalse(self.env["ea.audit.je.design"].sudo().search_count([("engagement_id", "=", self.engagement.id)]))
        self.engagement.sudo().write({"archived_at": "2026-01-01 00:00:00"})
        self.env.invalidate_all()
        self.as_staff.je_run_selection(self.dataset, {"criteria": ["round-amount"]})
        with self.assertRaisesRegex(Exception, "archived"):
            self.as_staff.je_record_design(self.dataset, {"criteria": ["round-amount"]})

    def test_an_outsider_is_refused(self):
        with self.assertRaisesRegex(Exception, "not-on-this-engagement"):
            self.as_outsider.je_run_selection(self.dataset, {"criteria": ["round-amount"]})
        self.assertFalse(self.env["ea.audit.je.design"].with_user(self.outsider).search([]))

    def test_the_studio_runs_and_exports(self):
        action = self.as_staff.action_tool_je()
        studio = self.env["ea.audit.je.studio"].with_user(self.staff).browse(action["params"]["studio_id"])
        studio.action_run()
        self.assertIn("RO001", str(studio.result_html))
        self.env["ea.audit.je.studio.rule"].with_user(self.staff).create({"studio_id": studio.id, "field": "jeNumber", "operator": "equals", "value": "YE001"})
        studio.action_run()
        self.assertIn("YE001", str(studio.result_html))
        name, content = self.as_staff.ea_export_xlsx("je_studio_%d" % studio.id)
        self.assertIn("E3.1", name)
        book = load_workbook(io.BytesIO(content))
        self.assertEqual(len(book.worksheets), 5)
        selection = book.worksheets[3]
        self.assertTrue(any("RO001" == cell.value for row in selection.iter_rows() for cell in row))

    def test_the_export_with_no_ledger_says_so(self):
        other = self.make_engagement(year=2026)
        name, content = other.with_user(self.partner).ea_export_xlsx("je_default")
        book = load_workbook(io.BytesIO(content))
        self.assertEqual(len(book.worksheets), 5)
        self.assertIn("E3.1", name)

    def test_the_view_loads(self):
        view = self.env.ref("ea_audit_tools.view_je_studio_form")
        self.env["ea.audit.je.studio"].with_user(self.reader).get_view(view.id)
