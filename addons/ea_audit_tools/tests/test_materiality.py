from odoo.tests import tagged

from .common import ToolsCase


@tagged("post_install", "-at_install")
class TestMateriality(ToolsCase):
    def make(self, actor=None, **overrides):
        args = {
            "benchmark": "equity", "benchmark_amount": 1000000, "percentage": 2,
            "justification": "A stable holding: users follow equity.",
        }
        args.update(overrides)
        return (actor or self.as_staff).create_materiality_version(**args)

    def test_figures_and_version_numbers(self):
        version = self.make()
        self.assertEqual((version.version_no, version.state), (1, "draft"))
        self.assertEqual((version.sudo().overall, version.sudo().performance, version.sudo().trivial), (20000, 15000, 1000))
        self.assertEqual(self.make().version_no, 2)

    def test_refusal_codes(self):
        self.assertCode("justification-required", self.make, justification="  ")
        self.assertCode("invalid-materiality", self.make, benchmark_amount=0)
        self.assertCode("invalid-materiality", self.make, percentage=0)
        self.assertCode("invalid-materiality", self.make, performance_pct=59)
        self.assertCode("invalid-materiality", self.make, performance_pct=86)
        self.assertCode("invalid-materiality", self.make, trivial_pct=2.9)
        self.assertCode("invalid-materiality", self.make, trivial_pct=5.5)
        self.assertCode("invalid-materiality", self.make, benchmark="nothing")
        self.assertCode("performance-justification-required", self.make, performance_pct=70)
        self.assertCode("materiality-out-of-range", self.make, percentage=9)

    def test_the_inclusive_bounds_pass(self):
        self.make(performance_pct=60, performance_justification="young entity", trivial_pct=3)
        self.make(performance_pct=85, performance_justification="stable", trivial_pct=5)

    def test_a_deviation_needs_its_own_justification_appended(self):
        version = self.make(percentage=9, override_justification="Regulator's own threshold")
        self.assertEqual(version.sudo().performance_justification, "Regulator's own threshold")
        both = self.make(percentage=9, performance_pct=70, performance_justification="weak controls", override_justification="reg")
        self.assertEqual(both.sudo().performance_justification, "weak controls — reg")

    def test_an_amount_away_from_the_tb_base_needs_a_justification(self):
        self.import_tb()
        self.assertCode("materiality-basis-mismatch", self.make, benchmark="equity", benchmark_amount=999999, percentage=2)
        self.make(benchmark="equity", benchmark_amount=5000, percentage=2)

    def test_guards_on_generate(self):
        self.assertCode("read-only-role", self.make, actor=self.as_reader)
        self.assertCode("not-on-this-engagement", self.make, actor=self.as_outsider)
        self.assertCode("eqr-read-only", self.make, actor=self.as_eqr)
        self.engagement.sudo().phase = "archived"
        self.assertCode("archived", self.make)

    def test_approval_is_a_partners_and_only_the_latest(self):
        first = self.make()
        second = self.make()
        self.assertCode("requires-partner", second.with_user(self.manager).action_approve)
        self.assertCode("stale-version", first.with_user(self.partner).action_approve)
        second.with_user(self.partner).action_approve()
        self.assertEqual(second.sudo().state, "approved")
        self.assertEqual(second.sudo().approved_by_id, self.partner)
        self.assertCode("not-found", second.with_user(self.partner).action_approve)

    def test_a_partner_off_the_team_cannot_approve(self):
        version = self.make()
        self.assertCode("not-on-this-engagement", version.with_user(self.partner2).action_approve)

    def test_a_draft_never_supersedes_and_approval_supersedes_the_old_one(self):
        first = self.make()
        first.with_user(self.partner).action_approve()
        second = self.make()
        self.assertEqual(first.sudo().state, "approved")
        self.assertEqual(self.engagement.sudo()._ea_approved_materiality(), first.sudo())
        self.assertFalse(self.engagement.sudo()._ea_materiality_approved())
        second.with_user(self.partner).action_approve()
        self.assertEqual(first.sudo().state, "superseded")
        self.assertEqual(self.engagement.sudo()._ea_approved_materiality(), second.sudo())
        self.assertTrue(self.engagement.sudo()._ea_materiality_approved())

    def test_no_user_writes_a_version_through_the_orm(self):
        version = self.make()
        self.assertCode("forbidden", version.with_user(self.partner).write, {"state": "approved"})
        self.assertCode("forbidden", version.with_user(self.partner).unlink)

    def test_approval_reflags_misstatements_and_leaves_the_amounts(self):
        self.import_tb()
        low = self.make(benchmark="pbt", benchmark_amount=200000, percentage=5, override_justification="x")
        low.with_user(self.partner).action_approve()
        self.assertEqual(low.sudo().trivial, 500)
        result = self.b5("Cut-off", amount=600, mtype="factual")
        item = result["finding"].sudo().misstatement_id
        self.assertFalse(item.trivial)
        high = self.make(benchmark="pbt", benchmark_amount=2000000, percentage=5, override_justification="x")
        high.with_user(self.partner).action_approve()
        self.assertEqual(high.sudo().trivial, 5000)
        self.assertTrue(item.trivial)
        self.assertEqual(item.amount, 600)

    def test_the_wizard_fills_from_the_tb_and_the_midpoint(self):
        self.import_tb()
        wizard = self.env["ea.audit.materiality.wizard"].with_user(self.staff).new({
            "engagement_id": self.engagement.id, "benchmark": "equity",
        })
        wizard._onchange_benchmark()
        self.assertEqual(wizard.percentage, 3)
        self.assertEqual(wizard.benchmark_amount, 5000)

    def test_the_cards_show_the_mock_ups_figures(self):
        version = self.make(benchmark="pbt", benchmark_amount=1690000000, percentage=5)
        version.with_user(self.partner).action_approve()
        board = self.engagement.with_user(self.staff)
        board.invalidate_recordset()
        self.assertEqual(board.mat_basis_label, "Profit before tax")
        self.assertEqual(board.mat_overall_label, "84,500,000 FCFA")
        self.assertEqual(board.mat_performance_label, "63,375,000 FCFA")
        self.assertEqual(board.mat_trivial_label, "4,225,000 FCFA")
        self.assertIn("Version 1", board.mat_version_label)
        self.assertFalse(board.mat_user_may_approve)

    def test_export(self):
        self.make()
        filename, content = self.as_staff.ea_export_xlsx("materiality")
        self.assertTrue(filename.endswith(".xlsx"))
        self.assertTrue(content.startswith(b"PK"))
