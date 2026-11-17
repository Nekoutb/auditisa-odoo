"""The strategy papers read the tools (group "strat", layout of 2026-11-17): S2.1 the controls selected,
S2.2 the design of their tests, S2.3 the IT applications and S2.5 the conclusion on the IT general
controls, each through its card, its tasks done in the tool and its statements checked by the tool."""
from odoo.tests import tagged

from .common import ToolsCase


@tagged("post_install", "-at_install")
class TestStratHooks(ToolsCase):
    def setUp(self):
        super().setUp()
        self.set_phase(self.engagement, "planning")
        for code in ("S2.1", "S2.2", "S2.3", "S2.5"):
            self.engagement.sudo()._ea_ensure_task(code)
        self.scot = self.as_staff.create_scot("Ventes", "routine", "controls", "Sage 100")
        self.wcgw = self.scot.add_wcgw("Facture non enregistrée", ["C"])
        self.control = self.scot.add_control("Contrôle de séquence", control_type="automated", wcgws=self.wcgw)

    def payload(self, code):
        return self.item(self.engagement, code).with_user(self.partner).get_paper_payload()

    @staticmethod
    def done(payload, key):
        return bool((payload["tool_done"].get(key) or {}).get("done"))

    @staticmethod
    def check(payload, key):
        return (payload["checks"].get(key) or {}).get("ok")

    def test_s21_reads_the_controls_selected(self):
        payload = self.payload("S2.1")
        self.assertTrue(payload["layout"]["converted"])
        self.assertFalse(payload["embed_only"])
        self.assertEqual(payload["tool_card"]["rows"][0][0], "Ventes")
        self.assertTrue(payload["tool_card"]["action"])
        self.assertFalse(self.done(payload, "select"))
        self.assertIsNone(self.check(payload, "wcgw_covered"))

        self.control.update_control({"selected_for_testing": True})
        payload = self.payload("S2.1")
        self.assertTrue(self.done(payload, "select"))
        self.assertIs(self.check(payload, "wcgw_covered"), True)
        # an automated control whose application does not rely on the IT processes is flagged
        self.assertFalse(self.done(payload, "itgc_dep"))
        self.assertIs(self.check(payload, "itgc_ok"), False)

        self.as_staff.save_it_application("sage-100", {"strategy": "rely_itgc"})
        payload = self.payload("S2.1")
        self.assertTrue(self.done(payload, "itgc_dep"))
        self.assertIs(self.check(payload, "itgc_ok"), True)

    def test_s22_reads_the_design_of_each_test(self):
        self.control.update_control({"selected_for_testing": True})
        payload = self.payload("S2.2")
        self.assertEqual(payload["tool_card"]["facts"][0]["value"], "0 / 1")
        self.assertFalse(self.done(payload, "attribute"))
        self.assertIs(self.check(payload, "each_control"), False)
        # an automated control is tested once: its extent is known
        self.assertTrue(self.done(payload, "extent"))

        self.control.update_control({"test_design": "Inspecter le paramétrage de la séquence."})
        payload = self.payload("S2.2")
        self.assertTrue(self.done(payload, "attribute"))
        self.assertIs(self.check(payload, "each_control"), True)
        self.assertNotIn("p_attribute", payload["missing"])

    def test_s23_reads_the_applications_and_their_strategy(self):
        payload = self.payload("S2.3")
        self.assertEqual(payload["tool_card"]["rows"][0][0], "Sage 100")
        self.assertTrue(self.done(payload, "apps"))
        self.assertFalse(self.done(payload, "strategy"))
        self.assertIs(self.check(payload, "apps"), False)

        self.as_staff.save_it_application("sage-100", {"strategy": "substantive_only"})
        payload = self.payload("S2.3")
        self.assertTrue(self.done(payload, "strategy"))
        self.assertIs(self.check(payload, "apps"), True)

    def test_s25_reads_the_conclusion_and_warns_when_it_does_not_support(self):
        payload = self.payload("S2.5")
        self.assertFalse(self.done(payload, "aggregate"))
        self.assertIsNone(self.check(payload, "cra"))
        self.assertEqual(payload["warnings"], [])

        self.as_staff.save_itgc_conclusion("not_support")
        payload = self.payload("S2.5")
        self.assertTrue(self.done(payload, "aggregate"))
        self.assertTrue(payload["warnings"])
        self.assertEqual(payload["values"].get("itgc_state"), "not_support")

        self.engagement.sudo().complexity = "non_complex"
        self.assertEqual(self.payload("S2.5")["layout"]["depth_reason"], "warning")
