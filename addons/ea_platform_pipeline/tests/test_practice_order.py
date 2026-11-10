"""Promote follows the release order: Staging (the practice computer) first, then the firms, with no wait."""

from odoo.tests import tagged

from odoo.addons.ea_platform_admin.tests.common import PlatformCase

from .test_pipeline_flow import PipelineMixin


@tagged("post_install", "-at_install")
class TestPracticeOrder(PipelineMixin, PlatformCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_pipeline()

    def _ready(self):
        canary = self._firm_on("cabinet-a")
        self._staging()
        return canary

    def test_without_a_practice_computer_the_check_says_so_and_passes(self):
        promotion = self._promotion(self._ready())
        promotion.action_run_checks()
        self.assertTrue(promotion.checks_ok, promotion.checks_text)
        self.assertIn("OK No practice computer yet", promotion.checks_text)

    def test_a_release_goes_to_the_firms_as_soon_as_staging_runs_it(self):
        canary = self._ready()
        computer = self.env["platform.practice.computer"]._enrol("practice-1", token_path=None, simulation=True)
        promotion = self._promotion(canary)
        promotion.action_run_checks()
        self.assertFalse(promotion.checks_ok)
        self.assertIn("NO This version is not on Staging yet", promotion.checks_text)
        computer.sudo().write({"desired_release_id": self.release2.id})
        computer._simulate_heartbeat()
        promotion.action_run_checks()
        self.assertTrue(promotion.checks_ok, promotion.checks_text)
        self.assertNotIn("practice_hold_days", self.release2._fields)
