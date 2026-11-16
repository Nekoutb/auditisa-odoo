"""The next-year uploads (owner's request of 2026-11-16): every kind of upload, and the trial
balance, of the year after the one audited. They are uploaded through the same screens, say how
far they reach, and never stand in for the year audited."""
from odoo.tests import tagged

from ..services.subsequent import SUBSEQUENT_MIN_DAYS
from .common import AR_CSV, AR_MAPPING, BALANCED_CSV, to_bytes
from .test_gl import LEDGER, MAPPING
from .test_procedure_execution import FAR_CSV, FAR_MAPPING
from .test_import_matching import ImportCase

#: Two balanced entries of the next year, the last on 14/02/2026: 45 days after the year end.
NEXT_LEDGER = """Compte;Intitulé;N° écriture;Libellé;Date;Débit;Crédit;Référence;Journal;Saisi par
401000;Fournisseurs;AC001;Facture achat;10/01/2026;;500,00;A1;AC;Awa
601000;Achats;AC001;Facture achat;10/01/2026;500,00;;A1;AC;Awa
521000;Banque;BQ101;Paiement;14/02/2026;;500,00;P1;BQ;Awa
401000;Fournisseurs;BQ101;Paiement;14/02/2026;500,00;;P1;BQ;Awa
"""
#: The same file stopping on 20/01/2026: 20 days, too short for the cut-off tests.
SHORT_LEDGER = NEXT_LEDGER.replace("14/02/2026", "20/01/2026")
#: A fixed-asset register (the same as the substantive procedures' tests; that module is not
#: imported here: it is not in the test package's list and importing it would run it).
FAR_CSV = """Numero;Designation;Categorie;Compte;Cout;Amortissements;VNC;VNC ouverture;Acquisitions;Cessions;Dotation
I1;Immeuble siege;Batiments;231000;4000;500;3500;3600;0;0;100
"""
FAR_MAPPING = {
    "item": "Numero", "itemDescription": "Designation", "amount": "Cout", "depreciation": "Amortissements", "nbv": "VNC",
    "category": "Categorie", "account": "Compte", "openingNbv": "VNC ouverture", "additions": "Acquisitions",
    "disposals": "Cessions", "charge": "Dotation",
}
#: A next-year trial balance, its receivables different from the year audited's.
NEXT_TB = BALANCED_CSV.replace("411000;Clients;800;0;1000;900", "411000;Clients;900;0;5000;900").replace(
    "701000;Ventes;0;0;0;2000", "701000;Ventes;0;0;0;6000",
).replace("101000;Capital;0;5000;0;0", "101000;Capital;0;5100;0;0")


@tagged("post_install", "-at_install")
class TestSubsequentUploads(ImportCase):
    def next_ledger(self, content=NEXT_LEDGER):
        return self.ledger(content, timing="subsequent")

    def test_the_next_year_ledger_goes_through_the_same_screens(self):
        wizard = self.read(NEXT_LEDGER, filename="next.csv", kind="journal_entries", timing="subsequent")
        self.assertEqual(wizard.missing_count, 0)
        wizard.action_check()
        self.assertFalse(wizard.blocking)
        wizard.action_import()
        dataset = self.datasets().filtered(lambda d: d.timing == "subsequent")
        self.assertEqual((len(dataset), dataset.row_count, dataset.is_current), (1, 4, True))
        self.assertEqual(self.engagement.sudo()._ea_subsequent_ledger(), dataset)
        # its dates are checked against the next year, not the one audited
        self.as_staff.gl_build_projection(dataset.id)
        details = [check["detailEn"] for check in self.as_staff.gl_validate_population(dataset.id)["checks"]]
        self.assertTrue(any(detail.startswith("All dated lines fall within 2026-01-01 to 2026-12-31") for detail in details), details)

    def test_every_kind_and_the_trial_balance_may_be_of_the_next_year(self):
        wizard = self.read(BALANCED_CSV, kind="trial_balance", timing="subsequent")
        self.assertEqual(wizard.timing, "subsequent")
        self.as_staff.create_dataset("ar_open_items", "ar.csv", to_bytes(AR_CSV), mapping=AR_MAPPING, timing="subsequent")
        self.assertEqual(self.engagement.sudo()._ea_subsequent_dataset("ar_open_items").timing, "subsequent")
        self.as_staff.create_dataset("fixed_asset_register", "far.csv", to_bytes(FAR_CSV), mapping=FAR_MAPPING, timing="subsequent")
        self.assertEqual(self.engagement.sudo()._ea_subsequent_dataset("fixed_asset_register").timing, "subsequent")
        result = self.as_staff.import_trial_balance("tb.csv", to_bytes(BALANCED_CSV), timing="subsequent")
        version = self.env["ea.audit.tb.version"].sudo().browse(result["versionId"])
        self.assertEqual(self.engagement.sudo()._ea_subsequent_tb_version(), version)
        timings = dict(self.env["ea.audit.tb.version"]._fields["timing"]._description_selection(self.env))
        self.assertEqual(set(timings), {"prior_year", "pre_audit", "post_audit", "subsequent"})

    def test_the_year_audited_never_reads_a_next_year_trial_balance(self):
        engagement = self.engagement.sudo()
        # a next-year TB alone: the year audited has none
        self.as_staff.import_trial_balance("next.csv", to_bytes(NEXT_TB), timing="subsequent")
        self.assertFalse(engagement._ea_current_tb_version())
        self.assertEqual(engagement._ea_tb_balances(), [])
        # the year's TB drives the file; a newer next-year one changes nothing
        current = self.as_staff.import_trial_balance("tb.csv", to_bytes(BALANCED_CSV))["versionId"]
        balances = engagement._ea_tb_balances()
        comparatives = engagement._ea_comparatives()
        newer = self.as_staff.import_trial_balance("next2.csv", to_bytes(NEXT_TB), timing="subsequent")["versionId"]
        self.assertEqual(engagement._ea_current_tb_version().id, current)
        self.assertEqual(engagement._ea_tb_balances(), balances)
        self.assertEqual(engagement._ea_comparatives(), comparatives)
        self.assertEqual(engagement._ea_tb_closing_for_prefixes(["411"]), 900)
        self.assertEqual(engagement._ea_subsequent_tb_version().id, newer)

    def test_next_year_sub_ledgers_never_feed_the_year_audited(self):
        engagement = self.engagement.sudo()
        self.as_staff.import_trial_balance("tb.csv", to_bytes(BALANCED_CSV))
        # receivables: the aging and the reconciliation read this year's listing only
        self.as_staff.create_dataset("ar_open_items", "ar-next.csv", to_bytes(AR_CSV), mapping=AR_MAPPING, timing="subsequent")
        following_ar = engagement._ea_subsequent_dataset("ar_open_items")
        self.assertFalse(engagement._ea_current_dataset("ar_open_items"))
        self.assertIsNone(self.as_staff.aging_for("ar_open_items"))
        self.assertFalse(following_ar.has_recon)
        self.assertCode("subsequent-dataset", self.as_staff.run_reconciliation, following_ar.id)
        self.assertCode("subsequent-dataset", self.as_staff.run_sampling, following_ar.id, "random", 2)
        self.as_staff.create_dataset("ar_open_items", "ar.csv", to_bytes(AR_CSV), mapping=AR_MAPPING)
        this_year = engagement._ea_current_dataset("ar_open_items")
        self.assertEqual(this_year.timing, "pre_audit")
        self.assertTrue(this_year.has_recon)
        self.assertIsNotNone(self.as_staff.aging_for("ar_open_items"))
        # fixed assets: the same
        self.as_staff.create_dataset("fixed_asset_register", "far-next.csv", to_bytes(FAR_CSV), mapping=FAR_MAPPING, timing="subsequent")
        following_far = engagement._ea_subsequent_dataset("fixed_asset_register")
        self.assertFalse(engagement._ea_current_dataset("fixed_asset_register"))
        self.assertCode("subsequent-dataset", self.as_staff.run_reconciliation, following_far.id)
        self.as_staff.create_dataset("fixed_asset_register", "far.csv", to_bytes(FAR_CSV), mapping=FAR_MAPPING)
        self.assertEqual(engagement._ea_current_dataset("fixed_asset_register").timing, "pre_audit")
        self.assertEqual(engagement._ea_subsequent_dataset("fixed_asset_register"), following_far)
        # the pickers of the sampling and supplier wizards leave the next year out
        for model, name in (("ea.audit.sampling.wizard", "dataset_id"), ("ea.audit.supplier.recon.wizard", "ledger_id")):
            self.assertIn("subsequent", self.env[model]._fields[name].domain)

    def test_the_year_audited_never_reads_the_next_year_upload(self):
        engagement = self.engagement.sudo()
        # a next-year ledger alone: the year audited has no ledger
        following = self.next_ledger()
        self.assertFalse(engagement._ea_ledger())
        self.assertFalse(engagement._ea_current_dataset("journal_entries"))
        self.assertEqual(engagement._ea_current_dataset("journal_entries", "subsequent"), following)
        self.as_staff.gl_build_projection(following.id)
        self.assertFalse(self.as_staff._ea_gl_datasets()[0])
        # the year's ledger, uploaded after it, is the one read everywhere
        current = self.ledger(LEDGER, mapping=MAPPING)
        self.assertTrue(following.is_current, "another timing is another series")
        self.assertEqual(engagement._ea_ledger(), current)
        self.assertEqual(engagement._ea_current_dataset("journal_entries"), current)
        self.as_staff.gl_build_projection(current.id)
        self.assertEqual(self.as_staff._ea_gl_datasets()[0], current)
        # newer than the year's ledger, the next year's still does not take over
        newer = self.next_ledger()
        self.assertEqual(engagement._ea_ledger(), current)
        self.assertEqual(engagement._ea_current_dataset("journal_entries"), current)
        self.assertEqual(engagement._ea_subsequent_ledger(), newer)
        # the journal-entry page offers the year's ledgers only
        page = self.as_staff.ea_je_page(False)
        self.assertEqual([item["id"] for item in page["datasets"]], [current.id])
        studio_domain = self.env["ea.audit.je.studio"]._fields["dataset_id"].domain
        self.assertIn("subsequent", studio_domain)
        # the receivables analyzer reads this year's listing, not the next year's
        self.as_staff.create_dataset("ar_open_items", "ar.csv", to_bytes(AR_CSV), mapping=AR_MAPPING)
        this_year = engagement._ea_current_dataset("ar_open_items")
        self.as_staff.create_dataset("ar_open_items", "ar-next.csv", to_bytes(AR_CSV), mapping=AR_MAPPING, timing="subsequent")
        self.assertEqual(engagement._ea_current_dataset("ar_open_items"), this_year)

    def test_the_coverage_and_its_sentence(self):
        self.assertEqual(self.as_staff.ea_subsequent_coverage(), {
            "first_date": None, "last_date": None, "days_after_year_end": None, "entries": 0,
        })
        overview = self.as_staff.ea_subsequent_overview()
        self.assertEqual(overview["sentence"], "No next-year general ledger uploaded.")
        self.assertEqual((overview["warning"], overview["short"], overview["datasetId"]), (None, False, False))
        dataset = self.next_ledger()
        expected = {"first_date": "2026-01-10", "last_date": "2026-02-14", "days_after_year_end": 45, "entries": 2}
        self.assertEqual(self.as_staff.ea_subsequent_coverage(), expected)  # read from the rows
        self.as_staff.gl_build_projection(dataset.id)
        self.assertEqual(self.as_staff.ea_subsequent_coverage(), expected)  # read from the projected lines
        self.assertEqual(
            self.as_staff.ea_subsequent_sentence(), "Next-year general ledger provided up to 14/02/2026 (45 days after year end).",
        )
        self.assertIsNone(self.as_staff.ea_subsequent_overview()["warning"])
        # a shorter one takes over and is warned about
        self.next_ledger(SHORT_LEDGER)
        overview = self.as_reader.ea_subsequent_overview()
        self.assertEqual((overview["days_after_year_end"], overview["short"]), (20, True))
        self.assertIn(str(SUBSEQUENT_MIN_DAYS), overview["warning"])
        self.assertEqual(overview["sentence"], "Next-year general ledger provided up to 20/01/2026 (20 days after year end).")

    def test_the_upload_lists_show_the_coverage_line(self):
        arch = self.env.ref("ea_audit_tools.view_dataset_list").arch
        self.assertIn('js_class="ea_dataset_list"', arch)
        timing = dict(self.env["ea.audit.dataset"]._fields["timing"]._description_selection(self.env))
        self.assertEqual(timing["subsequent"], "Subsequent period (next year)")
        self.assertEqual(self.as_staff.ea_subsequent_overview()["others"], [])
        self.as_staff.create_dataset("ar_open_items", "ar-next.csv", to_bytes(AR_CSV), mapping=AR_MAPPING, timing="subsequent")
        self.as_staff.import_trial_balance("tb-next.csv", to_bytes(BALANCED_CSV), timing="subsequent")
        others = self.as_staff.ea_subsequent_overview()["others"]
        self.assertEqual(len(others), 2, others)
        self.assertTrue(others[0].startswith("Next-year trial balance uploaded on "), others)
        self.assertTrue(others[1].startswith("Next-year receivables uploaded on "), others)
