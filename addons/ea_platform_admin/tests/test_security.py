from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from .common import PlatformCase, ssh_key


@tagged("post_install", "-at_install")
class TestRights(PlatformCase):
    def test_a_viewer_reads_and_changes_nothing(self):
        firm = self._active_firm()
        as_viewer = firm.with_user(self.viewer)
        self.assertEqual(as_viewer.name, firm.name)
        with self.assertRaises(AccessError):
            as_viewer.write({"note": "x"})

    def test_an_operator_edits_details_but_no_figure_by_hand(self):
        firm = self._active_firm()
        firm.with_user(self.operator).write({"legal_name": "Cabinet SARL"})
        self.assertEqual(firm.legal_name, "Cabinet SARL")

    def test_no_one_but_odoo_administrators_reads_a_token(self):
        firm = self._active_firm()
        for user in (self.viewer, self.operator, self.owner):
            with self.assertRaises(AccessError):
                firm.with_user(user).read(["heartbeat_token"])
            with self.assertRaises(AccessError):
                firm.with_user(user).read(["first_admin_token"])

    def test_nobody_creates_a_firm_except_through_the_wizard(self):
        for user in (self.viewer, self.operator, self.owner):
            with self.assertRaises(AccessError):
                self.env["platform.firm"].with_user(user).create({
                    "name": "x", "slug": "cabinet-x", "contact_name": "x", "contact_email": "a@b.cm",
                    "region": "cdg", "size": "small", "allowed_email_domains": "b.cm", "ssh_public_key": ssh_key(9),
                })

    def test_settings_are_for_the_owner(self):
        with self.assertRaises(AccessError):
            self.env["platform.settings"].with_user(self.operator).create({"provider": "dry_run", "base_domain": "x.y"})


@tagged("post_install", "-at_install")
class TestSettings(PlatformCase):
    def _settings(self, **values):
        data = {"provider": "dry_run", "base_domain": "auditisa.com"}
        data.update(values)
        return self.env["platform.settings"].with_user(self.owner).create(data)

    def test_real_mode_needs_a_tick_every_setting_and_the_token_files(self):
        with self.assertRaisesRegex(UserError, "confirmation"):
            self._settings(provider="vultr").action_save()
        with self.assertRaisesRegex(UserError, "To fill in"):
            self._settings(provider="vultr", confirm_real=True).action_save()
        with self.assertRaisesRegex(UserError, "trusted signer"):
            self._settings(
                provider="vultr", confirm_real=True,
                heartbeat_url="https://hb.example.invalid/platform/heartbeat",
                releases_bucket="auditisa-releases-0123abcd4567",
                ssh_allowlist="8.8.8.8", vultr_os_id="1", dns_zone_id="z",
            ).action_save()
        self.env["platform.signer"].sudo().create({
            "name": "Owner", "email": "contact@cm-ea.com",
            "public_pem": "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAZ9Gxf9CGeg8INOv/2l1p9YG2lWSpZqmsPnCglkTNoW8=\n-----END PUBLIC KEY-----\n",
        })
        with self.assertRaisesRegex(UserError, "token"):
            self._settings(
                provider="vultr", confirm_real=True,
                heartbeat_url="https://hb.example.invalid/platform/heartbeat",
                releases_bucket="auditisa-releases-0123abcd4567",
                ssh_allowlist="8.8.8.8", vultr_os_id="1", dns_zone_id="z",
            ).action_save()
        self.assertEqual(self.env["ir.config_parameter"].sudo().get_param("ea_platform.provider"), "dry_run")

    def test_port_22_cannot_be_opened_wide(self):
        with self.assertRaisesRegex(UserError, "too wide"):
            self._settings(ssh_allowlist="0.0.0.0/0").action_save()

    def test_addresses_must_be_https(self):
        with self.assertRaisesRegex(UserError, "https"):
            self._settings(heartbeat_url="http://hb.example.invalid/x").action_save()

    def test_wasabi_settings_are_checked(self):
        with self.assertRaisesRegex(UserError, "region"):
            self._settings(wasabi_region="Amsterdam").action_save()
        with self.assertRaisesRegex(UserError, "releases bucket"):
            self._settings(releases_bucket="my-photos").action_save()
        with self.assertRaisesRegex(UserError, "host name"):
            self._settings(wasabi_endpoint="https://s3.example/x").action_save()
        self._settings(wasabi_region="eu-central-1", releases_bucket="auditisa-releases-0123abcd4567").action_save()
        get_param = self.env["ir.config_parameter"].sudo().get_param
        self.assertEqual(get_param("ea_platform.releases_bucket"), "auditisa-releases-0123abcd4567")
        self.assertEqual(get_param("ea_platform.wasabi_region"), "eu-central-1")

    def test_a_change_is_logged(self):
        self._settings(base_domain="auditisa.com", ssh_allowlist="8.8.8.8").action_save()
        self.assertTrue(self.env["platform.log"].search_count([("action", "=", "Settings changed")]))
        self.assertEqual(self.env["ir.config_parameter"].sudo().get_param("ea_platform.ssh_allowlist"), "8.8.8.8")

    def test_the_answer_carries_the_operator_addresses(self):
        firm = self._active_firm()
        self.env["ir.config_parameter"].sudo().set_param("ea_platform.ssh_allowlist", "8.8.8.8")
        self.assertEqual(firm._heartbeat_answer()["ssh_allowlist"], ["8.8.8.8/32"])
