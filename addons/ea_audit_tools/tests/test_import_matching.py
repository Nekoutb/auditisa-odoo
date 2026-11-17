"""Import matching and versions (owner's rulings of 2026-11-15): the three-step wizard for the nine
kinds of file, the mandatory fields, the remembered matching, the check that saves nothing, a file
that fails and is not kept, and the deletion of a version by whoever may import."""
import base64
import importlib.util
import io
import pathlib

from openpyxl import Workbook, load_workbook

from odoo.exceptions import AccessError
from odoo.tests import Form, tagged

from odoo.addons.ea_audit_core.services.activity_summary import parse_body, translate_summary

from .common import AR_CSV, AR_MAPPING, BALANCED_CSV, UNBALANCED_CSV, ToolsCase, to_bytes
from .test_gl import LEDGER, MAPPING
from .test_scot_sampling import LEDGER as AMOUNT_LEDGER
from .test_scot_sampling import MAPPING as AMOUNT_MAPPING

#: An ERP export with short titles the aliases do not know.
ERP_CSV = """N°;Désignation;Mvt D;Mvt C;Observations
101000;Capital;0;5000;
521000;Banque;5000;0;à lettrer
411000;Clients;700;700;
"""
#: The same balance with other figures, to tell two versions apart.
OTHER_CSV = BALANCED_CSV.replace("411000;Clients;800;0;1000;900", "411000;Clients;800;0;1000;600").replace("521000;Banque;700;0;900;900", "521000;Banque;700;0;600;900")
#: The ledger of test_gl without its line that has no entry number: with the entry identified by
#: journal and number, that line is an entry of its own (" · OD") and does not balance.
KEYED_LEDGER = LEDGER.replace("601000;Achats;;Sans numero;03/03/2025;50,00;;;OD;Awa\n", "")
#: A ledger stated with one signed amount, balanced.
SIGNED_LEDGER = """Compte;N° écriture;Libellé;Date;Montant
411000;VE001;Facture 1;03/04/2025;1000
701000;VE001;Facture 1;03/04/2025;-1000
"""


def xlsx_bytes(sheets):
    """{sheet name: rows} as an .xlsx file."""
    book = Workbook()
    book.remove(book.active)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


class ImportCase(ToolsCase):
    def wizard(self, content, filename="balance.csv", kind="trial_balance", timing="pre_audit", actor=None, engagement=None):
        data = content if isinstance(content, bytes) else to_bytes(content)
        return self.env["ea.audit.import.wizard"].with_user(actor or self.staff).create({
            "engagement_id": (engagement or self.engagement).id, "kind": kind, "timing": timing,
            "file": base64.b64encode(data), "filename": filename,
        })

    def read(self, content, **kwargs):
        wizard = self.wizard(content, **kwargs)
        wizard.action_read()
        return wizard

    def line(self, wizard, header):
        return wizard.column_ids.filtered(lambda line: line.header == header)

    def choose(self, wizard, header, key=None):
        self.line(wizard, header).field_id = self.env["ea.audit.import.field"]._ea_of(wizard.kind, key)

    def versions(self, engagement=None):
        return self.env["ea.audit.tb.version"].sudo().search([("engagement_id", "=", (engagement or self.engagement).id)])

    def datasets(self, kind="journal_entries"):
        return self.env["ea.audit.dataset"].sudo().search([("engagement_id", "=", self.engagement.id), ("kind", "=", kind)])

    def ledger(self, content=LEDGER, timing="pre_audit", mapping=None):
        result = self.as_staff.create_dataset("journal_entries", "ledger.csv", to_bytes(content), mapping=mapping or MAPPING, timing=timing)
        return self.env["ea.audit.dataset"].sudo().browse(result["datasetId"])

    def trail(self):
        return [parse_body(body) for body in self.engagement.sudo().message_ids.mapped("body") if parse_body(body)]


@tagged("post_install", "-at_install")
class TestMatching(ImportCase):
    def test_one_line_per_column_with_its_first_values_and_the_field_proposed(self):
        wizard = self.read(BALANCED_CSV.replace("Mouvement crédit\n", "Mouvement crédit;Observations\n"))
        self.assertEqual(wizard.step, "match")
        self.assertEqual(wizard.column_ids.mapped("header"), [
            "Compte", "Libellé", "Solde ouverture débit", "Solde ouverture crédit", "Mouvement débit", "Mouvement crédit", "Observations",
        ])
        account = self.line(wizard, "Compte")
        self.assertEqual(account.sample, "101000 · 231000 · 411000")
        self.assertEqual((account.field_id.key, account.match_state, account.mandatory), ("account", "auto", "mandatory"))
        self.assertEqual(self.line(wizard, "Mouvement débit").mandatory, "mandatory")
        self.assertFalse(self.line(wizard, "Solde ouverture débit").mandatory)
        unknown = self.line(wizard, "Observations")
        self.assertTrue(unknown.field_id.skip)
        self.assertEqual(unknown.match_state, "none")
        self.assertEqual(wizard.missing_count, 0)
        self.assertEqual(wizard.row_count, 7)
        self.assertIn("All mandatory fields are matched", str(wizard.match_html))
        self.assertFalse(self.versions())

    def test_the_list_of_choices_is_the_kinds_own_with_do_not_import(self):
        Field = self.env["ea.audit.import.field"].with_user(self.staff)
        balance = Field.search([("kind", "=", "trial_balance")])
        self.assertEqual(balance.mapped("display_name")[:3], ["Do not import", "Account *", "Description"])
        self.assertIn("Debit (movements) *", balance.mapped("display_name"))
        self.assertIn("Closing (signed)", balance.mapped("display_name"))
        ledger = Field.search([("kind", "=", "journal_entries")]).mapped("display_name")
        self.assertIn("Journal entry number *", ledger)
        self.assertIn("Amount *", ledger)
        self.assertIn("Debit", ledger)
        self.assertEqual(len(ledger), 19)
        self.assertIn("Ne pas importer", Field.with_context(lang="fr_FR").search([("kind", "=", "bank_statement")]).mapped("display_name"))
        self.assertCode("forbidden", self.env["ea.audit.import.matching"].with_user(self.staff).create, [{"client_id": self.client.id, "kind": "trial_balance"}])
        with self.assertRaises(AccessError):
            balance[0].write({"label_en": "x"})

    def test_titles_nobody_knows_block_until_a_person_chooses(self):
        wizard = self.read(ERP_CSV, filename="erp.csv")
        # the account and the description are recognised by what their columns hold, the amounts are not guessed
        self.assertEqual((self.line(wizard, "N°").field_id.key, self.line(wizard, "N°").match_state), ("account", "auto"))
        self.assertEqual(self.line(wizard, "Désignation").field_id.key, "label")
        self.assertTrue(self.line(wizard, "Mvt D").field_id.skip)
        self.assertEqual(wizard.missing_count, 1)
        self.assertIn("Amounts", str(wizard.match_html))
        self.assertIn("Debit (movements) + Credit (movements) or Closing debit + Closing credit or Closing (signed)", str(wizard.match_html))
        self.assertCode("mapping-incomplete", wizard.action_check)
        self.assertEqual(wizard.step, "match")
        self.choose(wizard, "Mvt D", "debit")
        self.choose(wizard, "Mvt C", "credit")
        self.assertEqual(self.line(wizard, "Mvt D").match_state, "you")
        self.assertEqual(self.line(wizard, "Mvt D").mandatory, "mandatory")
        self.assertEqual(wizard.missing_count, 0)
        wizard.action_check()
        self.assertFalse(wizard.blocking)
        wizard.action_import()
        lines = self.engagement.sudo()._ea_current_tb_version().line_ids
        self.assertEqual({line.account_code: (line.debit, line.credit) for line in lines}, {"101000": (0, 5000), "521000": (5000, 0), "411000": (700, 700)})

    def test_do_not_import_leaves_a_recognised_column_out(self):
        wizard = self.read(BALANCED_CSV)
        self.choose(wizard, "Libellé")
        self.assertEqual(self.line(wizard, "Libellé").match_state, "you")
        wizard.action_check()
        wizard.action_import()
        self.assertFalse(any(self.engagement.sudo()._ea_current_tb_version().line_ids.mapped("account_name")))

    def test_a_field_is_fed_by_one_column(self):
        wizard = self.read(BALANCED_CSV)
        self.choose(wizard, "Solde ouverture débit", "debit")
        self.assertEqual(wizard.missing_count, 1)
        self.assertIn("more than one column", str(wizard.match_html))
        self.assertCode("field-matched-twice", wizard.action_check)
        self.assertCode("field-matched-twice", wizard.action_import)

    def test_back_to_matching_keeps_the_choices_and_back_to_upload_reads_again(self):
        wizard = self.read(ERP_CSV, filename="erp.csv")
        self.choose(wizard, "Mvt D", "debit")
        self.choose(wizard, "Mvt C", "credit")
        wizard.action_check()
        wizard.action_back_to_matching()
        self.assertEqual(wizard.step, "match")
        self.assertEqual(self.line(wizard, "Mvt D").field_id.key, "debit")
        wizard.action_back_to_upload()
        self.assertEqual(wizard.step, "upload")
        wizard.action_read()
        self.assertTrue(self.line(wizard, "Mvt D").field_id.skip)

    def test_the_same_wizard_for_a_ledger_and_a_sub_ledger(self):
        wizard = self.read(LEDGER, filename="ledger.csv", kind="journal_entries")
        keys = {line.header: line.field_id.key for line in wizard.column_ids}
        self.assertEqual((keys["Compte"], keys["N° écriture"], keys["Libellé"], keys["Date"], keys["Débit"], keys["Crédit"]),
                         ("account", "jeNumber", "jeDescription", "journalDate", "debit", "credit"))
        self.assertEqual(wizard.missing_count, 0)
        self.assertEqual(self.line(wizard, "Débit").mandatory, "mandatory")
        wizard.action_check()
        wizard.action_import()
        dataset = self.datasets()
        self.assertEqual((dataset.row_count, dataset.mapping["jeNumber"]), (5, "N° écriture"))
        receivables = self.read(AR_CSV, filename="ar.csv", kind="ar_open_items")
        self.assertEqual(receivables.missing_count, 0)
        receivables.action_check()
        self.assertIn("Total amount", str(receivables.check_html))
        receivables.action_import()
        self.assertEqual(self.datasets("ar_open_items").total_amount, 350)

    def test_an_entry_identified_by_several_columns(self):
        wizard = self.read(KEYED_LEDGER, filename="ledger.csv", kind="journal_entries")
        self.choose(wizard, "N° écriture")
        self.assertEqual(wizard.missing_count, 1)
        wizard.je_key_column_ids = self.line(wizard, "Journal") | self.line(wizard, "N° écriture")
        self.assertEqual(wizard.missing_count, 0)
        wizard.action_check()
        wizard.action_import()
        dataset = self.datasets()
        self.as_staff.gl_build_projection(dataset.id)
        numbers = self.env["ea.audit.gl.line"].sudo().search([("dataset_id", "=", dataset.id)]).mapped("je_number")
        self.assertIn("VE001 · VE", numbers)

    def test_the_template_follows_the_kind_and_a_reader_has_no_wizard(self):
        wizard = self.wizard(BALANCED_CSV)
        self.assertIn("/ea_audit_tools/export/tb_template/%d" % self.engagement.id, str(wizard.template_html))
        wizard.kind = "journal_entries"
        self.assertIn("/ea_audit_tools/export/template_journal_entries/%d" % self.engagement.id, str(wizard.template_html))
        with self.assertRaises(AccessError):
            self.wizard(BALANCED_CSV, actor=self.reader)
        self.assertCode("not-on-this-engagement", self.wizard(BALANCED_CSV, actor=self.outsider).action_read)
        self.assertEqual(self.as_staff.action_open_tb_import()["res_model"], "ea.audit.import.wizard")
        action = self.env["ea.audit.dataset"].with_user(self.staff).with_context(ea_engagement_id=self.engagement.id, ea_dataset_kind="bank_statement").action_list_import_dataset()
        self.assertEqual((action["res_model"], action["context"]["default_kind"]), ("ea.audit.import.wizard", "bank_statement"))


@tagged("post_install", "-at_install")
class TestMandatory(ImportCase):
    def test_a_trial_balance_needs_its_account_and_one_way_of_stating_amounts(self):
        closing_only = "Compte;Solde\n521000;500\n101000;-500\n"
        wizard = self.read(closing_only)
        self.assertEqual(wizard.missing_count, 0)
        self.assertEqual(self.line(wizard, "Solde").mandatory, "mandatory")
        half = self.read("Compte;Solde débit;Autre\n521000;500;0\n101000;0;500\n")
        self.assertEqual(half.missing_count, 1)
        self.assertCode("missing-amount-columns", self.as_staff.ea_import_check, "trial_balance", "b.csv", to_bytes(closing_only), {"account": "Compte"})
        self.assertCode("missing-amount-columns", self.as_staff.import_trial_balance, "b.csv", to_bytes(closing_only), mapping={"account": "Compte"})
        # a field matched to a column the file does not hold is not matched
        self.assertCode("missing-account-column", self.as_staff.import_trial_balance, "b.csv", to_bytes(closing_only), mapping={"account": "Nowhere", "closing": "Solde"})
        self.assertFalse(self.versions())

    def test_a_ledger_needs_its_five_and_the_amount_one_way_or_the_other(self):
        full = {"account": "Compte", "jeNumber": "N° écriture", "jeDescription": "Libellé", "journalDate": "Date"}
        for mapping in (dict(full, debit="Débit", credit="Crédit"), dict(full, amount="Débit")):
            self.assertEqual(self.as_staff.ea_import_check("journal_entries", "l.csv", to_bytes(LEDGER), mapping)["fileRows"], 5)
        for missing in ("account", "jeNumber", "jeDescription", "journalDate"):
            mapping = dict(full, debit="Débit", credit="Crédit")
            del mapping[missing]
            self.assertCode("mapping-incomplete", self.as_staff.ea_import_check, "journal_entries", "l.csv", to_bytes(LEDGER), mapping)
            self.assertCode("mapping-incomplete", self.as_staff.create_dataset, "journal_entries", "l.csv", to_bytes(LEDGER), mapping=mapping)
        self.assertCode("mapping-incomplete", self.as_staff.create_dataset, "journal_entries", "l.csv", to_bytes(LEDGER), mapping=dict(full, debit="Débit"))
        self.assertCode("mapping-incomplete", self.as_staff.create_dataset, "journal_entries", "l.csv", to_bytes(LEDGER), mapping=dict(full, amount="Nowhere"))
        self.assertFalse(self.datasets())

    def test_the_other_kinds_follow_their_catalogue(self):
        self.assertCode("mapping-incomplete", self.as_staff.create_dataset, "ar_open_items", "ar.csv", to_bytes(AR_CSV), mapping={"amount": "Montant"})
        self.assertCode("mapping-incomplete", self.as_staff.create_dataset, "bank_statement", "b.csv", to_bytes("Date;Montant\n15/01/2025;10\n"))
        self.assertFalse(self.datasets("ar_open_items") | self.datasets("bank_statement"))
        # nothing given: the titles are read as the wizard reads them, and a complete file comes in
        self.as_staff.create_dataset("bank_statement", "b.csv", to_bytes("Date;Libellé;Montant\n15/01/2025;Virement;10\n"))
        self.assertEqual(self.datasets("bank_statement").mapping, {"date": "Date", "description": "Libellé", "amount": "Montant"})


@tagged("post_install", "-at_install")
class TestRemember(ImportCase):
    def remembered(self, kind="trial_balance", client=None):
        return self.env["ea.audit.import.matching"].sudo().search([("client_id", "=", (client or self.client).id), ("kind", "=", kind)])

    def test_the_matching_is_kept_at_the_import_and_proposed_for_the_next_file(self):
        wizard = self.read(ERP_CSV, filename="erp.csv")
        self.choose(wizard, "Mvt D", "debit")
        self.choose(wizard, "Mvt C", "credit")
        self.choose(wizard, "Désignation")
        self.assertTrue(wizard.remember)
        wizard.action_check()
        self.assertFalse(self.remembered())
        wizard.action_import()
        self.assertEqual(self.remembered().matching["fields"], {"account": "N°", "debit": "Mvt D", "credit": "Mvt C"})
        again = self.read(ERP_CSV, filename="erp-next.csv")
        self.assertEqual(again.missing_count, 0)
        self.assertEqual((self.line(again, "Mvt D").field_id.key, self.line(again, "Mvt D").match_state), ("debit", "auto"))
        # a column a person set aside is not matched again by its title
        self.assertTrue(self.line(again, "Désignation").field_id.skip)
        # the next year's file of the same client gets it too, another kind of file does not
        next_year = self.make_engagement(year=2026)
        self.seat(next_year, self.staff, "staff")
        self.assertEqual(self.read(ERP_CSV, engagement=next_year).missing_count, 0)
        self.assertFalse(self.remembered("journal_entries"))

    def test_not_kept_when_the_box_is_off_and_never_for_another_client(self):
        wizard = self.read(ERP_CSV, filename="erp.csv")
        self.choose(wizard, "Mvt D", "debit")
        self.choose(wizard, "Mvt C", "credit")
        wizard.remember = False
        wizard.action_check()
        wizard.action_import()
        self.assertFalse(self.remembered())
        wizard = self.read(ERP_CSV, filename="erp.csv")
        self.choose(wizard, "Mvt D", "debit")
        self.choose(wizard, "Mvt C", "credit")
        wizard.action_check()
        wizard.action_import()
        self.assertTrue(self.remembered())
        other = self.env["ea.audit.client"].create({"name": "Autre SA", "legal_form": "SA"})
        elsewhere = self.make_engagement(year=2025, client=other)
        self.seat(elsewhere, self.staff, "staff")
        self.assertEqual(self.read(ERP_CSV, engagement=elsewhere).missing_count, 1)
        Matching = self.env["ea.audit.import.matching"]
        self.assertEqual(Matching.with_user(self.staff).search_count([("client_id", "=", self.client.id)]), 1)
        self.assertEqual(Matching.with_user(self.outsider).search_count([]), 0)
        self.assertCode("forbidden", self.remembered().with_user(self.staff).write, {"matching": {}})
        self.assertCode("forbidden", self.remembered().with_user(self.staff).unlink)

    def test_a_ledgers_matching_is_remembered_with_its_entry_columns(self):
        wizard = self.read(KEYED_LEDGER, filename="ledger.csv", kind="journal_entries")
        self.choose(wizard, "N° écriture")
        wizard.je_key_column_ids = self.line(wizard, "Journal") | self.line(wizard, "N° écriture")
        wizard.action_check()
        wizard.action_import()
        again = self.read(KEYED_LEDGER, filename="ledger-2.csv", kind="journal_entries")
        self.assertEqual(again.je_key_column_ids.mapped("header"), ["N° écriture", "Journal"])
        self.assertEqual(again.missing_count, 0)


@tagged("post_install", "-at_install")
class TestCheck(ImportCase):
    def test_the_check_of_a_trial_balance_is_what_the_import_keeps(self):
        content = BALANCED_CSV + "TOTAL;;5500;5500;4300;4300\n999000;Inconnu;0;0;0;0\n"
        check = self.as_staff.ea_import_check("trial_balance", "b.csv", to_bytes(content), None)
        self.assertFalse(self.engagement.sudo()._ea_tb())
        self.assertEqual((check["rows"], check["leftOut"], check["balanced"], check["blocking"]), (8, 1, True, False))
        effects = {issue["effect"] for issue in check["issues"]}
        self.assertEqual(effects, {"left_out", "warning"})
        self.assertEqual([issue["rows"] for issue in check["issues"] if issue["effect"] == "left_out"], [[9]])
        result = self.as_staff.import_trial_balance("b.csv", to_bytes(content))
        version = self.env["ea.audit.tb.version"].sudo().browse(result["versionId"])
        self.assertEqual((version.row_count, version.total_debit, version.total_credit), (check["rows"], check["totalDebit"], check["totalCredit"]))

    def test_the_check_screen_says_it_in_figures_and_in_words(self):
        self.import_tb()
        wizard = self.read(BALANCED_CSV + "TOTAL;;5500;5500;4300;4300\n")
        wizard.action_check()
        html = str(wizard.check_html)
        for text in ("Rows read", "Total debit", "Total credit", "Balanced", "Yes", "8 lines in the file, 1 left out", "Left out", "Line 9", "It will drive the file", "superseded"):
            self.assertIn(text, html)
        self.assertEqual(len(self.versions()), 1)

    def test_the_check_of_a_ledger_is_what_its_projection_says(self):
        content = LEDGER + "411000;Clients;VE009;Hors periode;15/01/2024;10,00;;;VE;Awa\n701000;Ventes;VE009;Hors periode;15/01/2024;;10,00;;VE;Awa\n"
        check = self.as_staff.ea_import_check("journal_entries", "l.csv", to_bytes(content), MAPPING)
        self.assertFalse(self.datasets())
        self.assertEqual((check["fileRows"], check["rows"], check["leftOut"], check["balanced"], check["blocking"]), (7, 6, 1, True, False))
        dataset = self.ledger(content)
        built = self.as_staff.gl_build_projection(dataset.id)
        self.assertEqual((built["build"]["lines"], built["build"]["rejected"], dataset.row_count), (check["rows"], check["leftOut"], check["fileRows"]))
        self.env.cr.execute("SELECT sum(debit), sum(credit) FROM ea_audit_gl_line WHERE dataset_id = %s", [dataset.id])
        debit, credit = self.env.cr.fetchone()
        self.assertAlmostEqual(float(debit), check["totalDebit"])
        self.assertAlmostEqual(float(credit), check["totalCredit"])

    def test_the_population_checks_read_the_same_before_and_after(self):
        from odoo.addons.ea_audit_tools.services.import_matching import gl_population
        from odoo.addons.ea_audit_tools.tabular import parse_table

        content = LEDGER + (
            "411000;Clients;VE009;Hors periode;15/01/2024;10,00;;;VE;Awa\n701000;Ventes;VE009;Hors periode;15/01/2024;;10,00;;VE;Awa\n"
            "411000;Clients;VE001;Facture 1;15/01/2025;1 000,00;;F1;VE;Awa\n701000;Ventes;VE001;Facture 1;15/01/2025;;1 000,00;F1;VE;Awa\n"
        )
        before = gl_population(parse_table("l.csv", to_bytes(content)), MAPPING, "2025-01-01", "2025-12-31")["validation"]
        dataset = self.ledger(content)
        self.as_staff.gl_build_projection(dataset.id)
        after = self.as_staff.gl_validate_population(dataset.id)
        self.assertEqual({check["key"]: check["status"] for check in before["checks"]}, {check["key"]: check["status"] for check in after["checks"]})
        self.assertEqual([check["detailEn"] for check in before["checks"]], [check["detailEn"] for check in after["checks"]])
        self.assertEqual(before["status"], "warning")

    def test_the_check_of_a_sub_ledger(self):
        content = AR_CSV + "C3;Gamma;F3;15/09/2025;n/d\n"
        check = self.as_staff.ea_import_check("ar_open_items", "ar.csv", to_bytes(content), AR_MAPPING)
        self.assertEqual((check["rows"], check["total"], check["blocking"]), (3, 350, False))
        self.assertEqual([(issue["effect"], issue["rows"]) for issue in check["issues"]], [("warning", [4])])
        result = self.as_staff.create_dataset("ar_open_items", "ar.csv", to_bytes(content), mapping=AR_MAPPING)
        dataset = self.env["ea.audit.dataset"].sudo().browse(result["datasetId"])
        self.assertEqual((dataset.row_count, dataset.total_amount), (check["rows"], check["total"]))


    def test_the_register_needs_its_category_date_and_rate_and_checks_them(self):
        head = "Code;Designation;Categorie;Date d'acquisition;Taux d'amortissement;Cout\n"
        rows = "I1;Siege;Batiments;15/03/2020;5%;4000\nI2;Camion;;31/03/2026;0,2;900\nI3;Poste;Info;n/d;150;300\n"
        base = {"item": "Code", "itemDescription": "Designation", "amount": "Cout"}
        self.assertCode("mapping-incomplete", self.as_staff.create_dataset, "fixed_asset_register", "f.csv", to_bytes(head + rows), mapping=base)
        self.assertCode("mapping-incomplete", self.as_staff.ea_import_check, "fixed_asset_register", "f.csv", to_bytes(head + rows), dict(base, category="Categorie"))
        check = self.as_staff.ea_import_check("fixed_asset_register", "f.csv", to_bytes(head + rows), None)
        self.assertFalse(check["blocking"])
        warned = [issue["rows"] for issue in check["issues"]]
        # file rows (the titles are row 1): no category on row 3, an unreadable date on row 4, a date after
        # the year end on row 3, a rate out of range on row 4, a rate written as a fraction on row 3
        self.assertEqual(warned, [[3], [4], [3], [4], [3]])
        result = self.as_staff.create_dataset("fixed_asset_register", "f.csv", to_bytes(head + rows))
        dataset = self.env["ea.audit.dataset"].sudo().browse(result["datasetId"])
        self.assertEqual((dataset.mapping["acquisitionDate"], dataset.mapping["depreciationRate"]), ("Date d'acquisition", "Taux d'amortissement"))
        _name, content = self.engagement.sudo()._ea_export_dataset_template("fixed_asset_register", False)
        values = [cell.value for row in load_workbook(io.BytesIO(content)).active.iter_rows() for cell in row]
        self.assertTrue({"Category", "Acquisition date", "Depreciation rate (% per year)"} <= set(values))


@tagged("post_install", "-at_install")
class TestRefused(ImportCase):
    def test_a_file_that_fails_saves_nothing_and_leaves_no_line_in_the_log(self):
        before = len(self.trail())
        self.assertCode("import-refused", self.import_tb, UNBALANCED_CSV)
        unreadable = BALANCED_CSV.replace("411000;Clients;800;0;1000;900", "411000;Clients;800;0;n/d;900")
        with self.assertRaises(Exception) as refused:
            self.import_tb(unreadable)
        self.assertIn("not readable as an amount", str(refused.exception))
        self.assertFalse(self.versions())
        self.assertFalse(self.env["ea.audit.tb.line"].sudo().search_count([("engagement_id", "=", self.engagement.id)]))
        self.assertFalse(self.env["ea.audit.lead.schedule"].sudo().search_count([("engagement_id", "=", self.engagement.id)]))
        self.assertEqual(len(self.trail()), before)

    def test_the_wizard_stops_at_the_check_and_the_method_refuses_too(self):
        self.import_tb()
        wizard = self.read(UNBALANCED_CSV, filename="bad.csv")
        wizard.action_check()
        self.assertTrue(wizard.blocking)
        html = str(wizard.check_html)
        self.assertIn("The file cannot be imported", html)
        self.assertIn("Blocks the import", html)
        self.assertIn("Movements do not balance", html)
        self.assertCode("import-refused", wizard.action_import)
        versions = self.versions()
        self.assertEqual(len(versions), 1)
        self.assertTrue(versions.is_current)
        self.assertFalse(versions.superseded_at)
        self.assertFalse(self.engagement.sudo().tb_invalid_reason)

    def test_a_ledger_with_no_line_to_use_is_refused(self):
        empty = "Compte;N° écriture;Libellé;Date;Débit;Crédit\n;;Sans compte;15/01/2025;10;\n411000;;Sans numero;15/01/2025;;10\n"
        mapping = {"account": "Compte", "jeNumber": "N° écriture", "jeDescription": "Libellé", "journalDate": "Date", "debit": "Débit", "credit": "Crédit"}
        check = self.as_staff.ea_import_check("journal_entries", "l.csv", to_bytes(empty), mapping)
        self.assertTrue(check["blocking"])
        self.assertCode("import-refused", self.as_staff.create_dataset, "journal_entries", "l.csv", to_bytes(empty), mapping=mapping)
        self.assertFalse(self.datasets())

    def test_an_unbalanced_ledger_is_stopped_at_the_check_and_refused_at_the_import(self):
        """Owner's ruling of 2026-11-15: in total, or entry by entry, a general ledger must balance."""
        content = LEDGER + "411000;Clients;VE009;Hors periode;15/01/2024;10,00;;;VE;Awa\n"
        check = self.as_staff.ea_import_check("journal_entries", "l.csv", to_bytes(content), MAPPING)
        self.assertTrue(check["blocking"])
        self.assertFalse(check["balanced"])
        blocking = [issue for issue in check["issues"] if issue["effect"] == "blocking"]
        self.assertIn("Total debit 2,010 and total credit 2,000 differ by 10", blocking[0]["text"])
        self.assertEqual(blocking[1]["rows"], [7])
        self.assertIn("Entry VE009 of 15/01/2024 does not balance: debit 10, credit 0, difference 10.", blocking[1]["text"])
        # the population check says the same once, as a blocking point, not twice
        self.assertFalse([issue for issue in check["issues"] if "Total debits equal total credits" in issue["text"]])
        with self.assertRaises(Exception) as refused:
            self.as_staff.create_dataset("journal_entries", "l.csv", to_bytes(content), mapping=MAPPING)
        self.assertIn("import-refused", str(refused.exception))
        self.assertIn("Entry VE009", str(refused.exception))
        self.assertFalse(self.datasets())
        wizard = self.read(content, filename="l.csv", kind="journal_entries")
        wizard.action_check()
        self.assertTrue(wizard.blocking)
        html = str(wizard.check_html)
        for text in ("The file cannot be imported", "Blocks the import", "Entry VE009", "Line 7", "No"):
            self.assertIn(text, html)
        self.assertCode("import-refused", wizard.action_import)
        self.assertFalse(self.datasets())

    def test_entries_that_offset_each_other_are_refused_too(self):
        offsetting = "Compte;N° écriture;Libellé;Date;Débit;Crédit\n411000;A1;x;15/01/2025;100;\n701000;A1;x;15/01/2025;;90\n411000;A2;x;16/01/2025;;10\n"
        mapping = {"account": "Compte", "jeNumber": "N° écriture", "jeDescription": "Libellé", "journalDate": "Date", "debit": "Débit", "credit": "Crédit"}
        check = self.as_staff.ea_import_check("journal_entries", "l.csv", to_bytes(offsetting), mapping)
        self.assertEqual((check["totalDebit"], check["totalCredit"], check["blocking"]), (100, 100, True))
        texts = [issue["text"] for issue in check["issues"] if issue["effect"] == "blocking"]
        self.assertEqual(len(texts), 2)
        self.assertIn("Entry A1 of 15/01/2025", texts[0])
        self.assertIn("difference 10.", texts[0])
        self.assertIn("Entry A2 of 16/01/2025", texts[1])
        self.assertIn("difference -10.", texts[1])
        self.assertCode("import-refused", self.as_staff.create_dataset, "journal_entries", "l.csv", to_bytes(offsetting), mapping=mapping)

    def test_twenty_unbalanced_entries_are_named_and_the_others_counted(self):
        lines = ["Compte;N° écriture;Libellé;Date;Montant"]
        for number in range(25):
            lines += ["411000;E%02d;x;15/01/2025;100" % number, "701000;E%02d;x;15/01/2025;-99" % number]
        mapping = {"account": "Compte", "jeNumber": "N° écriture", "jeDescription": "Libellé", "journalDate": "Date", "amount": "Montant"}
        check = self.as_staff.ea_import_check("journal_entries", "l.csv", to_bytes("\n".join(lines) + "\n"), mapping)
        texts = [issue["text"] for issue in check["issues"] if issue["effect"] == "blocking"]
        self.assertEqual(len(texts), 1 + 20 + 1)
        self.assertIn("Entry E19 ", texts[20])
        self.assertEqual(texts[-1], "5 more entries do not balance.")

    def test_a_rounding_difference_within_the_trial_balances_tolerance_passes(self):
        content = "Compte;N° écriture;Libellé;Date;Débit;Crédit\n411000;A1;x;15/01/2025;100,0049;\n701000;A1;x;15/01/2025;;100\n"
        mapping = {"account": "Compte", "jeNumber": "N° écriture", "jeDescription": "Libellé", "journalDate": "Date", "debit": "Débit", "credit": "Crédit"}
        self.assertFalse(self.as_staff.ea_import_check("journal_entries", "l.csv", to_bytes(content), mapping)["blocking"])
        self.as_staff.create_dataset("journal_entries", "l.csv", to_bytes(content), mapping=mapping)
        self.assertEqual(len(self.datasets()), 1)
        over = content.replace("100,0049", "100,02")
        self.assertCode("import-refused", self.as_staff.create_dataset, "journal_entries", "l.csv", to_bytes(over), mapping=mapping)

    def test_a_refusal_reads_in_french(self):
        as_french = self.as_staff.with_context(lang="fr_FR")
        self.env["res.lang"]._activate_lang("fr_FR")
        self.env["ir.module.module"].search([("name", "=", "ea_audit_tools")])._update_translations(["fr_FR"], overwrite=True)
        with self.assertRaises(Exception) as refused:
            as_french.import_trial_balance("b.csv", to_bytes(UNBALANCED_CSV))
        self.assertIn("n'a pas été importé", str(refused.exception))
        self.assertIn("Les mouvements ne s'équilibrent pas", str(refused.exception))


@tagged("post_install", "-at_install")
class TestDeleteVersion(ImportCase):
    def schedule(self, index="E"):
        return self.env["ea.audit.lead.schedule"].sudo().search([("engagement_id", "=", self.engagement.id), ("index_code", "=", index)])

    def test_deleting_a_superseded_version_changes_nothing_else(self):
        first = self.import_tb()
        second = self.import_tb(OTHER_CSV, filename="other.csv")
        self.as_staff.delete_tb_version(first["versionId"])
        versions = self.versions()
        self.assertEqual(versions.ids, [second["versionId"]])
        self.assertTrue(versions.is_current)
        self.assertEqual(self.schedule().closing, 1200)
        # a number is never given again, even the highest
        self.as_staff.delete_tb_version(second["versionId"])
        self.assertEqual(self.import_tb()["versionNo"], 3)

    def test_deleting_the_version_that_drives_the_file_hands_over_to_the_one_before(self):
        first = self.import_tb()
        second = self.import_tb(OTHER_CSV, filename="other.csv")
        earlier = self.env["ea.audit.tb.version"].sudo().browse(first["versionId"])
        self.assertTrue(earlier.superseded_at)
        self.assertEqual(self.schedule().closing, 1200)
        significance = self.env["ea.audit.significance"].sudo().search([("engagement_id", "=", self.engagement.id), ("index_code", "=", "E")])
        self.assertEqual(significance.closing, 1200)
        result = self.as_staff.delete_tb_version(second["versionId"])
        self.assertEqual(result["successorId"], earlier.id)
        self.assertTrue(earlier.is_current)
        self.assertFalse(earlier.superseded_at)
        self.assertEqual(self.engagement.sudo()._ea_current_tb_version(), earlier)
        self.assertEqual(self.schedule().closing, 900)
        significance = self.env["ea.audit.significance"].sudo().search([("engagement_id", "=", self.engagement.id), ("index_code", "=", "E")])
        self.assertEqual(significance.closing, 900)

    def test_deleting_the_only_version_leaves_the_file_without_a_trial_balance(self):
        only = self.import_tb()
        result = self.as_staff.delete_tb_version(only["versionId"])
        self.assertFalse(result["successorId"])
        self.assertFalse(self.engagement.sudo()._ea_current_tb_version())
        self.assertEqual(self.engagement.sudo()._ea_tb().current_version_no, 0)
        self.assertFalse(self.env["ea.audit.lead.schedule"].sudo().search_count([("engagement_id", "=", self.engagement.id)]))
        self.assertFalse(self.env["ea.audit.tb.line"].sudo().search_count([("engagement_id", "=", self.engagement.id)]))
        self.assertCode("no-tb", self.as_staff.ea_export_xlsx, "lead")
        self.assertEqual(self.engagement.sudo().tb_current_label, "—")

    def test_deleting_a_prior_year_version_moves_the_comparative(self):
        self.import_tb()
        older = self.import_tb(timing="prior_year")
        newer = self.import_tb(OTHER_CSV, filename="py.csv", timing="prior_year")
        self.assertEqual((self.schedule().prior_source, self.schedule().prior), ("prior_year_tb", 1200))
        current = self.engagement.sudo()._ea_current_tb_version()
        self.as_staff.delete_tb_version(newer["versionId"])
        # the one before is read again, and the version that drives the file has not moved
        self.assertFalse(self.env["ea.audit.tb.version"].sudo().browse(older["versionId"]).superseded_at)
        self.assertEqual((self.schedule().prior_source, self.schedule().prior), ("prior_year_tb", 900))
        self.assertEqual(self.engagement.sudo()._ea_current_tb_version(), current)
        self.as_staff.delete_tb_version(older["versionId"])
        self.assertEqual((self.schedule().prior_source, self.schedule().prior), ("opening", 800))

    def test_deleting_a_post_audit_version_brings_the_one_before_back(self):
        self.import_tb()
        older = self.import_tb(timing="post_audit")
        newer = self.import_tb(OTHER_CSV, filename="final.csv", timing="post_audit")
        current = self.engagement.sudo()._ea_current_tb_version()
        self.as_staff.delete_tb_version(newer["versionId"])
        self.assertFalse(self.env["ea.audit.tb.version"].sudo().browse(older["versionId"]).superseded_at)
        self.assertEqual(self.engagement.sudo()._ea_current_tb_version(), current)

    def test_an_invalid_version_of_before_is_deleted_like_any_other(self):
        valid = self.import_tb()
        invalid = self.invalid_version()
        self.assertTrue(self.engagement.sudo().tb_invalid_reason)
        self.as_staff.delete_tb_version(invalid.id)
        self.env.invalidate_all()
        self.assertFalse(self.engagement.sudo().tb_invalid_reason)
        kept = self.env["ea.audit.tb.version"].sudo().browse(valid["versionId"])
        self.assertTrue(kept.is_current)
        self.assertFalse(kept.superseded_at)

    def test_the_confirmation_says_what_goes_and_what_takes_over(self):
        self.import_tb()
        second = self.import_tb(OTHER_CSV, filename="other.csv")
        version = self.env["ea.audit.tb.version"].with_user(self.staff).browse(second["versionId"])
        action = version.action_delete()
        self.assertEqual(action["res_model"], "ea.audit.import.delete.wizard")
        self.assertRegex(action["name"], r"^Delete the upload of \d\d/\d\d/\d{4} \d\d:\d\d\?$")
        wizard = self.env["ea.audit.import.delete.wizard"].with_user(self.staff).browse(action["res_id"])
        html = str(wizard.summary_html)
        for text in ("other.csv", "by Staff on", "7 rows", "Pre-audit", "drives the file", "balance.csv", "drives the file again", "A line stays in the engagement log"):
            self.assertIn(text, html)
        self.assertEqual(len(self.versions()), 2)
        wizard.action_confirm()
        self.assertEqual(self.versions().source_filename, "balance.csv")
        last = self.env["ea.audit.tb.version"].with_user(self.staff).browse(self.versions().id).action_delete()
        html = str(self.env["ea.audit.import.delete.wizard"].with_user(self.staff).browse(last["res_id"]).summary_html)
        self.assertIn("the file has no trial balance", html)

    def test_one_line_in_the_log_and_it_reads_in_french(self):
        only = self.import_tb()
        self.as_staff.delete_tb_version(only["versionId"])
        action, summary = self.trail()[0]
        self.assertEqual(action, "tb_deleted")
        self.assertRegex(summary, r"^Trial balance deleted: balance\.csv \(pre_audit, imported on \d\d/\d\d/\d{4} \d\d:\d\d, 7 rows, total debit 4,300, total credit 4,300\)$")
        self.assertEqual(self.engagement.sudo().message_ids[0].author_id, self.staff.partner_id)
        self.env["res.lang"]._ea_setup_languages()
        french = translate_summary(action, summary, "fr_FR")
        self.assertIn("Balance supprimée : balance.csv (avant audit, importée le", french)
        self.assertNotIn("pre_audit", french)
        imported = [line for line in self.trail() if line[0] == "tb_imported"][0]
        self.assertEqual(imported[1], "Trial balance imported: balance.csv (pre_audit, 7 rows)")
        self.assertIn("Balance importée : balance.csv (avant audit, 7 lignes)", translate_summary(*imported, "fr_FR"))

    def test_whoever_may_import_may_delete_and_nobody_else(self):
        earlier = self.import_tb()["versionId"]
        version = self.import_tb()["versionId"]
        # a staff member, with no reason asked
        self.as_staff.delete_tb_version(earlier)
        self.assertFalse(self.env["ea.audit.tb.version"].sudo().browse(earlier).exists())
        self.assertCode("read-only-role", self.as_reader.delete_tb_version, version)
        self.assertCode("not-on-this-engagement", self.as_outsider.delete_tb_version, version)
        self.assertCode("not-on-this-engagement", self.engagement.with_user(self.admin).delete_tb_version, version)
        self.assertCode("eqr-read-only", self.as_eqr.delete_tb_version, version)
        record = self.env["ea.audit.tb.version"].browse(version)
        self.assertCode("forbidden", record.with_user(self.manager).unlink)
        self.assertCode("not-on-this-engagement", record.with_user(self.outsider).action_delete)
        other = self.make_engagement(year=2024)
        self.seat(other, self.staff, "staff")
        self.assertCode("not-found", other.with_user(self.staff).delete_tb_version, version)
        self.engagement.sudo().phase = "archived"
        self.assertCode("archived", self.as_staff.delete_tb_version, version)
        self.assertCode("archived", record.with_user(self.staff).action_delete)
        self.assertTrue(record.sudo().exists())


@tagged("post_install", "-at_install")
class TestDatasetVersions(ImportCase):
    def test_the_latest_upload_is_the_one_in_use_and_the_others_keep_their_rows(self):
        first = self.ledger()
        self.as_staff.gl_build_projection(first.id)
        self.assertEqual(first.gl_line_count, 4)
        second = self.ledger()
        self.assertEqual(len(self.datasets()), 2)
        self.assertEqual((first.is_current, second.is_current), (False, True))
        self.assertEqual(self.env["ea.audit.dataset.row"].sudo().search_count([("dataset_id", "=", first.id)]), 5)
        # the projection of a superseded upload is not kept: it is rebuilt from the rows if needed
        self.assertFalse(self.env["ea.audit.gl.line"].sudo().search_count([("dataset_id", "=", first.id)]))
        self.assertEqual((first.gl_line_count, first.gl_built_at, first.validation_status), (0, False, False))
        self.assertCode("dataset-superseded", self.as_staff.gl_build_projection, first.id)
        self.assertEqual(self.engagement.sudo()._ea_current_dataset("journal_entries"), second)
        self.assertEqual(self.engagement.sudo()._ea_ledger(), second)
        # another timing is another series
        prior = self.ledger(timing="prior_year")
        self.assertTrue(second.is_current)
        self.assertTrue(prior.is_current)
        self.assertRegex(second.display_name, r"^\d\d/\d\d/\d{4} \d\d:\d\d · ledger\.csv$")

    def test_deleting_the_upload_in_use_brings_the_one_before_back_with_its_projection(self):
        first = self.ledger()
        second = self.ledger()
        self.as_staff.gl_build_projection(second.id)
        result = self.as_staff.delete_dataset(second.id)
        self.assertEqual(result["successorId"], first.id)
        self.assertFalse(second.exists())
        self.assertTrue(first.is_current)
        self.assertEqual(first.gl_line_count, 4)
        self.assertEqual(self.as_staff.gl_validate_population(first.id)["lines"], 4)
        last = self.as_staff.delete_dataset(first.id)
        self.assertFalse(last["successorId"])
        self.assertFalse(self.datasets())
        self.assertFalse(self.env["ea.audit.dataset.row"].sudo().search_count([("engagement_id", "=", self.engagement.id)]))

    def test_deleting_a_superseded_upload_leaves_the_one_in_use(self):
        first = self.ledger()
        second = self.ledger()
        self.as_staff.gl_build_projection(second.id)
        self.as_staff.delete_dataset(first.id)
        self.assertEqual(self.datasets(), second)
        self.assertEqual(second.gl_line_count, 4)

    def test_a_sample_drawn_from_an_upload_outlives_it(self):
        dataset = self.ledger(AMOUNT_LEDGER, mapping=AMOUNT_MAPPING)
        run = self.as_staff.run_sampling(dataset.id, "random", 2, seed="abc").sudo()
        self.ledger(AMOUNT_LEDGER, mapping=AMOUNT_MAPPING)
        self.assertEqual(run.dataset_id, dataset)  # superseded, not deleted: the link holds
        self.as_staff.delete_dataset(dataset.id)
        self.assertTrue(run.exists())
        self.assertFalse(run.dataset_id)
        self.assertEqual(len(run.sheet_rows), 2)

    def test_the_sub_ledgers_have_versions_too(self):
        first = self.as_staff.create_dataset("ar_open_items", "ar.csv", to_bytes(AR_CSV), mapping=AR_MAPPING)["datasetId"]
        second = self.as_staff.create_dataset("ar_open_items", "ar2.csv", to_bytes(AR_CSV.replace("250", "300")), mapping=AR_MAPPING)["datasetId"]
        Dataset = self.env["ea.audit.dataset"].sudo()
        self.assertTrue(Dataset.browse(first).superseded_at)
        self.assertEqual(self.as_staff.aging_for("ar_open_items")["totals"]["total"], 400)
        self.as_staff.delete_dataset(second)
        self.assertFalse(Dataset.browse(first).superseded_at)
        self.assertEqual(self.as_staff.aging_for("ar_open_items")["totals"]["total"], 350)

    def test_the_confirmation_the_log_and_who_may(self):
        first = self.ledger()
        second = self.ledger()
        action = self.env["ea.audit.dataset"].with_user(self.staff).browse(second.id).action_delete()
        wizard = self.env["ea.audit.import.delete.wizard"].with_user(self.staff).browse(action["res_id"])
        html = str(wizard.summary_html)
        for text in ("ledger.csv", "General ledger", "in use", "is in use again", "Samples and selections already drawn"):
            self.assertIn(text, html)
        self.assertCode("read-only-role", self.as_reader.delete_dataset, second.id)
        self.assertCode("not-on-this-engagement", self.as_outsider.delete_dataset, second.id)
        self.assertCode("eqr-read-only", self.as_eqr.delete_dataset, second.id)
        self.assertCode("no-dataset", self.as_staff.delete_dataset, 999999)
        self.assertCode("forbidden", self.env["ea.audit.dataset"].with_user(self.manager).browse(second.id).unlink)
        wizard.action_confirm()
        self.assertEqual(self.datasets(), first)
        action, summary = self.trail()[0]
        self.assertEqual(action, "dataset_deleted")
        self.assertRegex(summary, r"^ledger\.csv deleted \(journal_entries, pre_audit, imported on \d\d/\d\d/\d{4} \d\d:\d\d, 5 rows, total 2,050\)$")
        self.env["res.lang"]._ea_setup_languages()
        self.assertIn("ledger.csv supprimé (journal_entries, avant audit, importé le", translate_summary(action, summary, "fr_FR"))
        self.engagement.sudo().phase = "archived"
        self.assertCode("archived", self.as_staff.delete_dataset, first.id)
        self.assertCode("archived", self.env["ea.audit.dataset"].with_user(self.staff).browse(first.id).action_delete)
        self.assertTrue(first.exists())


@tagged("post_install", "-at_install")
class TestOptions(ImportCase):
    def test_another_sheet_of_the_workbook(self):
        content = xlsx_bytes({
            "Paramètres": [["Clé", "Valeur"], ["Devise", "XAF"]],
            "Balance 2025": [["Compte", "Libellé", "Mouvement débit", "Mouvement crédit"], [521000, "Banque", 500, 0], [101000, "Capital", 0, 500]],
        })
        wizard = self.read(content, filename="balance.xlsx")
        self.assertTrue(wizard.is_excel)
        self.assertEqual(wizard.sheet_ids.mapped("name"), ["Paramètres", "Balance 2025"])
        self.assertEqual(wizard.sheet_id.name, "Paramètres")
        self.assertEqual(wizard.column_ids.mapped("header"), ["Clé", "Valeur"])
        self.assertEqual(wizard.missing_count, 2)
        with Form(wizard) as form:
            form.sheet_id = wizard.sheet_ids[1]
        self.assertEqual(wizard.column_ids.mapped("header"), ["Compte", "Libellé", "Mouvement débit", "Mouvement crédit"])
        self.assertEqual(wizard.missing_count, 0)
        wizard.action_check()
        wizard.action_import()
        self.assertEqual(self.engagement.sudo()._ea_current_tb_version().line_ids.mapped("account_code"), ["521000", "101000"])

    def test_another_separator(self):
        content = "Compte;Libellé,suite;Mouvement débit;Mouvement crédit\n521000;Banque, locale;500;0\n101000;Capital, social;0;500\n"
        wizard = self.read(content)
        self.assertEqual(len(wizard.column_ids), 4)
        self.assertIn("semicolon", wizard.found_note)
        wizard.csv_separator = ","
        wizard._ea_load_columns()
        self.assertEqual(len(wizard.column_ids), 2)
        wizard.csv_separator = "auto"
        wizard._ea_load_columns()
        self.assertEqual(wizard.column_ids.mapped("header"), ["Compte", "Libellé,suite", "Mouvement débit", "Mouvement crédit"])

    def test_the_decimal_separator_a_person_chooses(self):
        content = "Compte;Libellé;Mouvement débit;Mouvement crédit\n521000;Banque;1,500;0\n101000;Capital;0;1,500\n"
        automatic = self.as_staff.ea_import_check("trial_balance", "b.csv", to_bytes(content), None)
        self.assertEqual(automatic["totalDebit"], 1500)
        wizard = self.read(content)
        wizard.decimal_separator = "comma"
        wizard.action_check()
        wizard.action_import()
        self.assertEqual(self.engagement.sudo()._ea_current_tb_version().total_debit, 1.5)
        self.assertEqual(self.as_staff.ea_import_check("trial_balance", "b.csv", to_bytes(content.replace("1,500", "1.500")), None, options={"decimal": "point"})["totalDebit"], 1.5)

    def test_the_date_format_a_person_chooses(self):
        wizard = self.read(SIGNED_LEDGER, filename="l.csv", kind="journal_entries")
        self.assertTrue(wizard.has_dates)
        self.assertIn("day/month/year", wizard.found_note)
        wizard.date_format = "mdy"
        wizard.action_check()
        wizard.action_import()
        dataset = self.datasets()
        self.as_staff.gl_build_projection(dataset.id)
        dates = self.env["ea.audit.gl.line"].sudo().search([("dataset_id", "=", dataset.id)]).mapped("journal_date")
        self.assertEqual({str(day) for day in dates}, {"2025-03-04"})
        automatic = self.ledger(SIGNED_LEDGER, timing="post_audit", mapping={
            "account": "Compte", "jeNumber": "N° écriture", "jeDescription": "Libellé", "journalDate": "Date", "amount": "Montant",
        })
        self.as_staff.gl_build_projection(automatic.id)
        dates = self.env["ea.audit.gl.line"].sudo().search([("dataset_id", "=", automatic.id)]).mapped("journal_date")
        self.assertEqual({str(day) for day in dates}, {"2025-04-03"})
        self.assertFalse(self.wizard(BALANCED_CSV).has_dates)


@tagged("post_install", "-at_install")
class TestNoFingerprint(ImportCase):
    def test_no_fingerprint_is_stored_shown_or_printed(self):
        for model in ("ea.audit.tb.version", "ea.audit.dataset"):
            self.assertNotIn("source_sha256", self.env[model]._fields)
        for xmlid in ("view_tb_version_form", "view_tb_version_list", "view_dataset_form", "view_dataset_list"):
            arch = self.env.ref("ea_audit_tools.%s" % xmlid).arch
            self.assertNotIn("sha256", arch.lower())
            self.assertNotIn("SHA-256", arch)
            self.assertNotIn("version_no", arch)
        dataset = self.ledger()
        self.as_staff.gl_build_projection(dataset.id)
        _name, content = self.as_staff.ea_export_xlsx("je_default")
        cells = [str(cell.value) for sheet in load_workbook(io.BytesIO(content)).worksheets for row in sheet.iter_rows() for cell in row if cell.value]
        self.assertFalse([cell for cell in cells if "SHA-256" in cell.upper() or "SHA256" in cell.upper()])
        self.assertIn("ledger.csv", cells)

    def test_a_tests_of_details_plan_starts_where_it_did_after_the_same_file_comes_in_again(self):
        self.approve()
        first = self.ledger(SIGNED_LEDGER.replace("1000", "900000"), mapping={
            "account": "Compte", "jeNumber": "N° écriture", "jeDescription": "Libellé", "journalDate": "Date", "amount": "Montant",
        })
        key = self.engagement.sudo()._ea_ledger_start_key(first)
        self.assertEqual(key, "journal_entries:2:0")
        before = self.as_staff.tod_side_view("bs")
        again = self.ledger(SIGNED_LEDGER.replace("1000", "900000"), mapping=first.mapping)
        self.assertNotEqual(again.id, first.id)
        self.assertEqual(self.engagement.sudo()._ea_ledger_start_key(again), key)
        after = self.as_staff.tod_side_view("bs")
        self.assertEqual([sheet["plan"] for sheet in before["sheets"]], [sheet["plan"] for sheet in after["sheets"]])
        # a start given from a plan already worked out is the one used
        given = self.as_staff.tod_side_view("bs", start_fraction=0.25)
        self.assertEqual([sheet["plan"] for sheet in given["sheets"]], [sheet["plan"] for sheet in self.as_staff.tod_side_view("bs", start_fraction=0.25)["sheets"]])


@tagged("post_install", "-at_install")
class TestMigration(ImportCase):
    def migration(self):
        path = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "19.0.1.1.0" / "pre-migrate.py"
        spec = importlib.util.spec_from_file_location("ea_audit_tools_pre_migrate_19_0_1_1_0", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def columns(self, table):
        self.env.cr.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", [table])
        return {row[0] for row in self.env.cr.fetchall()}

    def test_the_update_drops_the_fingerprint_and_the_old_wizards_and_keeps_the_data(self):
        """On a database as the release before left it: the columns, the wizards' tables, their
        screens, an invalid version and a dataset."""
        cr = self.env.cr
        valid = self.import_tb()["versionId"]
        invalid = self.invalid_version()
        dataset = self.ledger()
        cr.execute("ALTER TABLE ea_audit_tb_version ADD COLUMN source_sha256 varchar")
        cr.execute("ALTER TABLE ea_audit_dataset ADD COLUMN source_sha256 varchar")
        cr.execute("UPDATE ea_audit_tb_version SET source_sha256 = repeat('a', 64)")
        cr.execute("UPDATE ea_audit_dataset SET source_sha256 = repeat('b', 64)")
        cr.execute("CREATE TABLE ea_audit_tb_import_wizard (id serial PRIMARY KEY)")
        cr.execute("CREATE TABLE ea_audit_dataset_import_wizard (id serial PRIMARY KEY)")
        cr.execute("CREATE TABLE ea_audit_dataset_import_map (id serial PRIMARY KEY, wizard_id integer REFERENCES ea_audit_dataset_import_wizard(id))")
        stale = self.env["ir.ui.view"].create({
            "name": "stale", "model": "ea.audit.engagement", "type": "form", "arch": "<form><field name='display_name'/></form>",
        })
        self.env["ir.model.data"].create({"module": "ea_audit_tools", "name": "view_tb_import_wizard", "model": "ir.ui.view", "res_id": stale.id})
        self.env.flush_all()
        migration = self.migration()
        migration.migrate(cr, "19.0.1.0.0")
        migration.migrate(cr, "19.0.1.0.0")  # a second run is harmless
        self.env.invalidate_all()
        self.assertNotIn("source_sha256", self.columns("ea_audit_tb_version"))
        self.assertNotIn("source_sha256", self.columns("ea_audit_dataset"))
        cr.execute("SELECT to_regclass('ea_audit_tb_import_wizard'), to_regclass('ea_audit_dataset_import_wizard'), to_regclass('ea_audit_dataset_import_map')")
        self.assertEqual(cr.fetchone(), (None, None, None))
        self.assertFalse(stale.exists())
        self.assertFalse(self.env["ir.model.data"].search_count([("module", "=", "ea_audit_tools"), ("name", "=", "view_tb_import_wizard")]))
        # what was imported is all there, and the invalid version of before can now be deleted
        versions = self.versions()
        self.assertEqual(set(versions.ids), {valid, invalid.id})
        self.assertEqual(len(versions.line_ids), 9)
        self.assertEqual(self.env["ea.audit.dataset.row"].sudo().search_count([("dataset_id", "=", dataset.id)]), 5)
        self.assertTrue(dataset.is_current)
        self.as_staff.delete_tb_version(invalid.id)
        self.assertEqual(self.versions().ids, [valid])
