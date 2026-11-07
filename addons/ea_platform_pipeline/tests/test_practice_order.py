"""Promote follows the release order: the practice computer first, the firms after the holding period."""

from datetime import timedelta

from odoo import fields
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
        self._green()
        return canary

    def _practice_line(self, promotion):
        return [line for line in promotion.checks_text.split("\n") if "practice computer" in line.lower()]

    def test_without_a_practice_computer_the_check_says_so_and_passes(self):
        promotion = self._promotion(self._ready())
        promotion.action_run_checks()
        self.assertTrue(promotion.checks_ok, promotion.checks_text)
        self.assertIn("OK No practice computer yet", promotion.checks_text)

    def test_a_release_not_held_on_the_practice_computer_is_not_promoted(self):
        canary = self._ready()
        self.env["platform.practice.computer"]._enrol("practice-1", token_path=None, simulation=True)
        promotion = self._promotion(canary)
        promotion.action_run_checks()
        self.assertFalse(promotion.checks_ok)
        self.assertTrue(any(line.startswith("NO Not yet on the practice computer") for line in self._practice_line(promotion)))
        self.release2.sudo().practice_since = fields.Datetime.now() - timedelta(days=8)
        promotion.action_run_checks()
        self.assertTrue(promotion.checks_ok, promotion.checks_text)
