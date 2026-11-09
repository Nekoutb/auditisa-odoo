import json
import base64
from datetime import datetime, timedelta

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from ..services.addons import SWITCH_GRACE
from .common import PlatformCase

SAMPLE = "ea_client_addon_sample"
BASE = "ea_audit_reports"


def catalogue_bytes(sha, extra=()):
    addons = [
        {"code": BASE, "name": "AuditISA Reports", "summary": "Reports", "version": "19.0.1.0.0", "optional": False, "sample": False},
        {"code": SAMPLE, "name": "SAMPLE: Client notes", "summary": "Sample", "version": "19.0.1.0.0", "optional": True, "sample": True},
        *extra,
    ]
    return json.dumps({"schema": 1, "release": sha, "addons": addons}).encode()


class AddonCase(PlatformCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.release.with_user(cls.owner)._load_catalogue(catalogue_bytes(cls.release.sha))
        cls.sample = cls.env["platform.addon"].search([("code", "=", SAMPLE)])
        cls.base = cls.env["platform.addon"].search([("code", "=", BASE)])

    def _on(self, firm, reason="The firm asked"):
        firm.with_user(self.operator)._set_addon(self.sample, True, reason)
        firm.invalidate_recordset()

    def _line(self, firm):
        return firm.sudo().addon_line_ids.filtered(lambda line: line.addon_id == self.sample)

    def _answer(self, firm):
        return firm.sudo()._heartbeat_answer()


@tagged("post_install", "-at_install")
class TestCatalogue(AddonCase):
    def test_it_lists_base_and_optional_with_their_kind(self):
        self.assertEqual(self.base.kind, "base")
        self.assertEqual(self.sample.kind, "sample")
        self.assertEqual(self.release.optional_addon_count, 1)
        self.assertEqual(self.release._optional_codes(), [SAMPLE])

    def test_which_firms_have_it(self):
        firm = self._active_firm("cabinet-a")
        other = self._active_firm("cabinet-b")
        self._on(firm)
        self.assertEqual(self.sample.firm_ids, firm)
        self.assertEqual(self.sample.firm_count, 1)
        self.assertEqual(self.base.firm_ids, firm | other)

    def test_a_catalogue_for_another_release_or_changed_later_is_refused(self):
        with self.assertRaisesRegex(UserError, "another release"):
            self.release2._load_catalogue(catalogue_bytes(self.release.sha))
        changed = catalogue_bytes(self.release.sha, extra=[
            {"code": "ea_client_y", "name": "Y", "summary": "", "version": "1", "optional": True, "sample": False},
        ])
        with self.assertRaisesRegex(UserError, "does not change"):
            self.release._load_catalogue(changed)

    def test_nobody_writes_a_catalogue_row_by_hand(self):
        for user in (self.viewer, self.operator, self.owner):
            with self.assertRaises(AccessError):
                self.sample.with_user(user).write({"is_optional": False})
            with self.assertRaises(AccessError):
                self.env["platform.addon"].with_user(user).create({"code": "ea_client_z", "name": "Z"})

    def test_a_signature_is_checked_when_given(self):
        private = Ed25519PrivateKey.generate()
        pem = private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
        self.env["platform.signer"].sudo().create({"name": "Owner", "email": "contact@cm-ea.com", "public_pem": pem})
        raw = catalogue_bytes(self.release2.sha)
        with self.assertRaisesRegex(UserError, "signature does not hold"):
            self.release2._load_catalogue(raw, private.sign(raw + b"x"))
        self.assertFalse(self.release2.catalogue_loaded_at)
        self.release2._load_catalogue(raw, private.sign(raw))
        self.assertTrue(self.release2.catalogue_signed)

    def test_a_real_platform_refuses_a_catalogue_without_a_signature(self):
        services = type(self.env["platform.services"])
        self.patch(services, "_is_simulation", lambda _self: False)
        with self.assertRaisesRegex(UserError, "signature file"):
            self.release2._load_catalogue(catalogue_bytes(self.release2.sha))
        with self.assertRaisesRegex(UserError, "signed file"):
            self.release2.with_user(self.owner).action_read_catalogue_here()

    def test_only_the_owner_reads_a_catalogue_from_the_code_or_uses_the_upload(self):
        with self.assertRaises(AccessError):
            self.release2.with_user(self.operator).action_read_catalogue_here()
        with self.assertRaises(AccessError):
            self.env["platform.catalogue.wizard"].with_user(self.operator).create({
                "release_id": self.release2.id, "catalogue_file": base64.b64encode(b"{}"),
            })

    def test_reading_it_from_the_code_finds_the_real_addons(self):
        from odoo.modules.module import get_module_path
        if not get_module_path("ea_audit_core", display_warning=False):
            # The console's own addons path holds the platform's addons only, by design: there is no
            # firm code here to read. CI, with the whole repository on the path, runs this test.
            self.skipTest("no ea_audit_* addon on this addons path (the console)")
        self.release2.with_user(self.owner).action_read_catalogue_here()
        codes = self.release2.addon_line_ids.mapped("code")
        self.assertIn("ea_audit_reports", codes)
        self.assertIn("ea_audit_core", codes)
        self.assertNotIn("ea_platform_admin", codes)
        self.assertEqual(self.release2._optional_codes(), [SAMPLE])
        self.assertFalse(self.release2.catalogue_signed)


@tagged("post_install", "-at_install")
class TestToggle(AddonCase):
    def test_switching_logs_who_when_and_why(self):
        firm = self._active_firm()
        self._on(firm, "Cabinet asked on the 3rd")
        row = firm.log_ids.filtered(lambda r: r.action == "Add-on switched on")
        self.assertEqual(row.user_id, self.operator)
        self.assertTrue(row.logged_at)
        self.assertIn(SAMPLE, row.detail_text)
        self.assertIn("Cabinet asked on the 3rd", row.detail_text)
        self.assertEqual(self._line(firm).changed_by, self.operator)

    def test_the_wizard_needs_a_reason_and_logs_off_as_hidden(self):
        firm = self._active_firm()
        self._on(firm)
        wizard = self.env["platform.addon.toggle.wizard"].with_user(self.operator).create({
            "firm_id": firm.id, "addon_id": self.sample.id, "target": "off", "reason": "   ",
        })
        with self.assertRaisesRegex(UserError, "Say why"):
            wizard.action_confirm()
        wizard.reason = "No longer needed"
        wizard.action_confirm()
        self.assertFalse(self._line(firm).desired)
        self.assertTrue(firm.log_ids.filtered(lambda r: r.action == "Add-on switched off (hidden, data kept)"))

    def test_a_viewer_cannot_switch(self):
        firm = self._active_firm()
        with self.assertRaises(AccessError):
            self.env["platform.addon.toggle.wizard"].with_user(self.viewer).create({
                "firm_id": firm.id, "addon_id": self.sample.id, "target": "on", "reason": "x",
            })

    def test_a_base_feature_cannot_be_switched_in_either_direction(self):
        firm = self._active_firm()
        for on in (True, False):
            with self.assertRaisesRegex(UserError, "base feature"):
                firm.with_user(self.operator)._set_addon(self.base, on, "Try")
        self.assertFalse(firm.sudo().addon_line_ids.filtered(lambda line: line.addon_id == self.base))

    def test_an_add_on_outside_the_running_release_cannot_be_asked_for(self):
        firm = self._active_firm()
        other = self.env["platform.addon"].sudo().create({"code": "ea_client_other", "name": "O", "is_optional": True})
        with self.assertRaisesRegex(UserError, "not in the release"):
            firm.with_user(self.operator)._set_addon(other, True, "Try")

    def test_a_firm_leaving_no_longer_changes(self):
        firm = self._active_firm()
        firm.sudo().state = "offboarding"
        with self.assertRaisesRegex(UserError, "leaving"):
            firm.with_user(self.operator)._set_addon(self.sample, True, "Try")

    def test_the_same_toggle_twice_logs_once(self):
        firm = self._active_firm()
        self._on(firm)
        self._on(firm)
        self.assertEqual(len(firm.log_ids.filtered(lambda r: r.action == "Add-on switched on")), 1)


@tagged("post_install", "-at_install")
class TestWizardStep(AddonCase):
    def _at_addons(self, slug="cabinet-a", **changes):
        wizard = self._wizard(slug, **changes)
        wizard.action_next()
        wizard.action_next()
        self.assertEqual(wizard.step, "addons")
        return wizard

    def test_the_screen_offers_the_optional_add_ons_of_the_release_only(self):
        wizard = self._at_addons()
        self.assertEqual(wizard.addon_line_ids.addon_id, self.sample)
        self.assertIn(self.base, wizard.sudo().base_addon_ids)
        self.assertNotIn(self.base, wizard.addon_line_ids.addon_id)
        self.assertFalse(wizard.catalogue_missing)

    def test_a_release_without_a_catalogue_says_so_and_goes_on(self):
        wizard = self._at_addons(release_id=self.release2.id)
        self.assertTrue(wizard.catalogue_missing)
        self.assertFalse(wizard.addon_line_ids)
        wizard.action_next()
        self.assertEqual(wizard.step, "preflight")

    def test_choosing_needs_a_reason_then_it_reaches_the_firm(self):
        wizard = self._at_addons()
        wizard.addon_line_ids.enabled = True
        with self.assertRaisesRegex(UserError, "Say why"):
            wizard.action_next()
        wizard.addons_reason = "In the contract"
        wizard.action_next()
        self.assertEqual(wizard.preview_addons, "SAMPLE: Client notes")
        wizard.confirmed = True
        result = wizard.action_confirm()
        firm = self.env["platform.provision.job"].browse(result["res_id"]).firm_id
        self.assertTrue(self._line(firm).desired)
        row = firm.log_ids.filtered(lambda r: r.action == "Add-on switched on")
        self.assertEqual(row.user_id, self.operator)
        self.assertIn("In the contract", row.detail_text)
        self.assertEqual(self._answer(firm)["desired_addons"], [SAMPLE])

    def test_back_and_forth_keeps_the_choice(self):
        wizard = self._at_addons()
        wizard.addon_line_ids.enabled = True
        wizard.addons_reason = "Why"
        wizard.action_next()
        wizard.action_back()
        wizard.action_back()
        wizard.action_next()
        self.assertTrue(wizard.addon_line_ids.enabled)

    def test_changing_to_a_release_without_it_drops_the_choice(self):
        wizard = self._at_addons()
        wizard.addon_line_ids.enabled = True
        wizard.addons_reason = "Why"
        wizard.action_back()
        wizard.release_id = self.release2
        wizard.action_next()
        self.assertFalse(wizard.addon_line_ids)

    def test_nothing_chosen_needs_no_reason(self):
        firm, _job = self._onboard()
        self.assertFalse(self._line(firm).desired)
        self.assertEqual(self._answer(firm)["desired_addons"], [])


@tagged("post_install", "-at_install")
class TestHeartbeatPath(AddonCase):
    def test_the_answer_holds_only_optional_add_ons_of_the_running_release(self):
        firm = self._active_firm()
        self._on(firm)
        self.assertEqual(self._answer(firm)["desired_addons"], [SAMPLE])

    def test_a_base_module_forced_in_the_table_is_never_asked(self):
        firm = self._active_firm()
        self.env["platform.firm.addon"].sudo().create({"firm_id": firm.id, "addon_id": self.base.id, "desired": True})
        self.assertNotIn(BASE, self._answer(firm)["desired_addons"])

    def test_an_add_on_the_running_release_lacks_is_not_asked_and_shows(self):
        firm = self._active_firm()
        self._on(firm)
        firm._simulate_heartbeat(release=self.release2.sha)
        firm.invalidate_recordset()
        self.assertEqual(firm.addon_release, self.release2.sha)
        self.assertNotIn("desired_addons", self._answer(firm))  # no catalogue for it: no request at all
        self.release2._load_catalogue(json.dumps({"schema": 1, "release": self.release2.sha, "addons": [
            {"code": BASE, "name": "R", "summary": "", "version": "1", "optional": False, "sample": False},
        ]}).encode())
        self.assertEqual(self._answer(firm)["desired_addons"], [])
        self.assertEqual(self._line(firm).status, "not_in_release")
        firm._evaluate_health()
        self.assertEqual(firm.addons_differ_count, 1)
        self.assertTrue(firm.needs_attention)

    def test_a_firm_not_live_is_not_asked(self):
        firm = self._active_firm()
        self._on(firm)
        firm.sudo().state = "suspended"
        self.assertNotIn("desired_addons", self._answer(firm))

    def test_a_release_without_a_catalogue_asks_nothing(self):
        firm = self._active_firm()
        firm.sudo().addon_release = self.release2.sha
        self.assertNotIn("desired_addons", self._answer(firm))

    def test_desired_against_actual(self):
        firm = self._active_firm()
        firm._simulate_heartbeat()
        self.assertEqual(self._line(firm).status, "off")
        self._on(firm)
        self.assertEqual(self._line(firm).status, "switching_on")
        firm._evaluate_health()
        self.assertEqual(firm.health_color, "green")  # the firm has an hour to act
        firm._simulate_heartbeat()
        firm.invalidate_recordset()
        self.assertEqual(self._line(firm).status, "on")
        self.assertEqual(firm.addons_on_summary, "SAMPLE: Client notes")

    def test_a_mismatch_past_the_grace_is_an_attention_reason(self):
        firm = self._active_firm()
        self._on(firm)
        firm._simulate_heartbeat(addons_on=[])
        firm.invalidate_recordset()
        self.assertEqual(self._line(firm).status, "switching_on")
        self._line(firm).write({"changed_at": fields.Datetime.now() - SWITCH_GRACE - timedelta(minutes=1)})
        firm.invalidate_recordset()
        self.assertEqual(self._line(firm).status, "differs_on")
        firm._evaluate_health()
        self.assertEqual(firm.addons_differ_count, 1)
        self.assertEqual(firm.health_color, "amber")
        self.assertTrue(firm.needs_attention)
        self.assertIn("not as asked", firm.health_reason)
        firm._simulate_heartbeat()
        firm.invalidate_recordset()
        self.assertEqual(firm.addons_differ_count, 0)
        self.assertEqual(firm.health_color, "green")

    def test_an_add_on_the_firm_keeps_on_after_off_shows(self):
        firm = self._active_firm()
        self._on(firm)
        firm._simulate_heartbeat()
        firm.with_user(self.operator)._set_addon(self.sample, False, "Off")
        self._line(firm).write({"changed_at": fields.Datetime.now() - SWITCH_GRACE - timedelta(minutes=1)})
        firm._simulate_heartbeat(addons_on=[SAMPLE])
        firm.invalidate_recordset()
        self.assertEqual(self._line(firm).status, "differs_off")
        self.assertTrue(firm.needs_attention)

    def test_a_refusal_by_the_server_is_an_attention_reason(self):
        firm = self._active_firm()
        firm._simulate_heartbeat(addons_refused=2)
        firm.invalidate_recordset()
        self.assertEqual(firm.addons_refused_count, 2)
        self.assertIn("refused 2", firm.health_reason)
        self.assertEqual(firm.health_color, "amber")

    def test_a_reported_code_outside_the_catalogue_is_counted_and_its_text_kept_nowhere(self):
        firm = self._active_firm()
        firm._simulate_heartbeat(addons_on=["ea_client_acme_sarl_notes", SAMPLE])
        firm.invalidate_recordset()
        self.assertEqual(firm.addons_unknown_count, 1)
        self.assertTrue(self._line(firm).reported)
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT table_name, column_name FROM information_schema.columns
             WHERE table_schema = 'public' AND data_type IN ('text', 'character varying')
               AND table_name LIKE 'platform\\_%%'
        """)
        for table, column in self.env.cr.fetchall():
            self.env.cr.execute(f'SELECT count(*) FROM "{table}" WHERE "{column}" LIKE %s', ["%acme_sarl%"])  # noqa: S608
            self.assertEqual(self.env.cr.fetchone()[0], 0, f"{table}.{column}")

    def test_a_firm_on_an_older_release_is_left_alone_until_it_reports(self):
        firm = self._active_firm()
        firm.sudo().write({"addons_reported_at": False})
        self.assertEqual(self._line(firm).status, "off")
        firm._evaluate_health()
        self.assertEqual(firm.addons_differ_count, 0)

    def test_the_answer_reaches_a_real_signed_heartbeat(self):
        firm = self._active_firm()
        self._on(firm)
        from ..services.simulator import healthy_figures, signed_request

        token = firm.sudo().heartbeat_token
        now = datetime.utcnow().replace(microsecond=0)
        figures = {**healthy_figures(now, self.release.sha), "addons_on": [SAMPLE], "addons_refused": 0}
        import time
        headers, body = signed_request(token, firm.slug, int(time.time()) + 60, figures)
        answer, signature = self.env["platform.firm"]._receive_heartbeat(headers, body)
        self.assertEqual(json.loads(answer)["desired_addons"], [SAMPLE])
        self.assertTrue(signature)
        self.assertTrue(self._line(firm).reported)
