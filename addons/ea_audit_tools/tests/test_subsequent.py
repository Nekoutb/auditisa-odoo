"""The next-year uploads (owner's request of 2026-11-16): the general ledger and the receivables,
payables and inventory of the year after the one audited. They are uploaded through the same
screens, say how far they reach, and never stand in for the year audited."""
from odoo.tests import tagged

from ..services.subsequent import SUBSEQUENT_MIN_DAYS
from .common import AR_CSV, AR_MAPPING, BALANCED_CSV, to_bytes
from .test_gl import LEDGER, MAPPING
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

    def test_only_the_ledger_and_the_three_sub_ledgers_may_be_of_the_next_year(self):
        self.assertCode("subsequent-kind", self.read, BALANCED_CSV, kind="trial_balance", timing="subsequent")
        self.assertCode(
            "subsequent-kind", self.as_staff.create_dataset, "fixed_asset_register", "fa.csv", to_bytes(AR_CSV), mapping=AR_MAPPING,
            timing="subsequent",
        )
        self.assertCode("invalid-value", self.as_staff.import_trial_balance, "tb.csv", to_bytes(BALANCED_CSV), timing="subsequent")
        self.as_staff.create_dataset("ar_open_items", "ar.csv", to_bytes(AR_CSV), mapping=AR_MAPPING, timing="subsequent")
        self.assertEqual(self.engagement.sudo()._ea_subsequent_dataset("ar_open_items").timing, "subsequent")

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
