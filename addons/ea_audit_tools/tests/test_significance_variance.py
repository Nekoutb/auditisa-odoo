"""Significant accounts: the prior year, the variance and the flag thresholds (owner's mock-up of 2026-11-16)."""
from odoo.tests import tagged

from .common import ToolsCase


@tagged("post_install", "-at_install")
class TestSignificanceVariance(ToolsCase):
    def rows(self):
        self.engagement.sudo()._ea_sync_significance()
        return {
            record.index_code: record
            for record in self.env["ea.audit.significance"].with_user(self.staff).search([("engagement_id", "=", self.engagement.id)])
        }

    def test_prior_year_from_the_openings_variance_and_new(self):
        self.import_tb()
        rows = self.rows()
        receivables, revenue = rows["E"], rows["UA"]
        # no prior-year trial balance: the openings of this year's stand in
        self.assertEqual((receivables.closing, receivables.prior_closing, receivables.variance), (900, 800, 100))
        self.assertAlmostEqual(receivables.variance_pct, 12.5)
        self.assertEqual(receivables.variance_pct_label, "12.5 %")
        self.assertTrue(revenue.variance_new)
        self.assertEqual((revenue.prior_closing, revenue.variance), (0, -2000))
        self.assertEqual(revenue.variance_pct_label, "new")
        # the owner's defaults: and, 10 %, 10 000 000 FCFA: nothing this small is flagged
        self.assertFalse(receivables.flagged or revenue.flagged)
        flags = self.as_reader.ea_significance_flags()
        self.assertEqual(
            (flags["mode"], flags["pct"], flags["amount"], flags["canEdit"], flags["flagged"]),
            ("and", 10, 10000000, False, 0),
        )
        self.assertIn("opening", flags["source"])

    def test_writers_set_the_thresholds_and_or(self):
        self.import_tb()
        self.rows()
        self.assertTrue(self.as_staff.ea_significance_flags()["canEdit"])
        self.assertCode("read-only-role", self.as_reader.ea_save_significance_flags, "or", 10, 1000)
        self.assertCode("invalid-value", self.as_staff.ea_save_significance_flags, "xor", 10, 1000)
        self.assertCode("invalid-value", self.as_staff.ea_save_significance_flags, "or", -1, 1000)
        # and: 12.5 % on receivables but only 100 FCFA; revenue is new and moved 2 000
        flags = self.as_staff.ea_save_significance_flags("and", 10, 1000)
        rows = self.rows()
        self.assertFalse(rows["E"].flagged)
        self.assertTrue(rows["UA"].flagged)
        self.assertEqual(rows["UA"].variance_pct_label, "⚑ new")
        self.assertEqual(flags["flagged"], len([row for row in rows.values() if row.flagged]))
        # or: either limit
        flags = self.as_staff.ea_save_significance_flags("or", 10, 1000000)
        rows = self.rows()
        self.assertTrue(rows["E"].flagged)
        self.assertEqual(rows["E"].variance_pct_label, "⚑ 12.5 %")
        self.assertEqual((flags["mode"], flags["pct"], flags["amount"]), ("or", 10, 1000000))
        self.assertEqual(flags["flagged"], len([row for row in rows.values() if row.flagged]))
