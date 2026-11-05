import base64
import struct

from odoo.tests import TransactionCase, new_test_user

from ..services.provider import DryRunDns, DryRunProbe, DryRunProvider


def ssh_key(number):
    algorithm = b"ssh-ed25519"
    blob = struct.pack(">I", len(algorithm)) + algorithm + struct.pack(">I", 32) + bytes([number]) * 32
    return "ssh-ed25519 " + base64.b64encode(blob).decode() + " owner@laptop"


class PlatformMixin:
    """Builds firms the way the screens do: through the wizard, on the dry-run provider."""

    _firm_number = 10

    @classmethod
    def _setup_platform(cls):
        cls.release = cls.env["platform.release"].sudo().create({
            "sha": "abcdef123456", "bundle_sha256": "a" * 64, "label": "Version 1",
        })
        cls.release2 = cls.env["platform.release"].sudo().create({
            "sha": "fedcba654321", "bundle_sha256": "b" * 64, "label": "Version 2",
        })
        cls.viewer = new_test_user(cls.env, login="p_viewer", groups="ea_platform_admin.group_platform_viewer")
        cls.operator = new_test_user(cls.env, login="p_operator", groups="ea_platform_admin.group_platform_operator")
        cls.owner = new_test_user(cls.env, login="p_owner", groups="ea_platform_admin.group_platform_owner")

    @classmethod
    def _request(cls, slug="cabinet-a", **changes):
        cls._firm_number += 1
        values = {
            "name": f"Cabinet {slug}",
            "slug": slug,
            "contact_name": "Awa Ngono",
            "contact_email": "awa@exemple.cm",
            "contact_phone": "+237 600 000 000",
            "allowed_email_domains": "exemple.cm",
            "region": "cdg",
            "size": "standard",
            "lang": "fr_FR",
            "ssh_public_key": ssh_key(cls._firm_number),
            "release_id": cls.release.id,
        }
        values.update(changes)
        return values

    def _wizard(self, slug="cabinet-a", user=None, **changes):
        model = self.env["platform.onboarding.wizard"].with_user(user or self.operator)
        return model.create(self._request(slug, **changes))

    def _through_steps(self, wizard):
        wizard.action_next()
        wizard.action_next()
        wizard.confirmed = True
        return wizard

    def _onboard(self, slug="cabinet-a", user=None, **changes):
        wizard = self._through_steps(self._wizard(slug, user=user, **changes))
        result = wizard.action_confirm()
        job = self.env["platform.provision.job"].browse(result["res_id"])
        return job.firm_id, job

    def _active_firm(self, slug="cabinet-a"):
        firm, _job = self._onboard(slug)
        firm.action_confirm_key_escrow()
        firm._evaluate_health()
        return firm

    def _outside_patched(self, provider=None, dns=None, probe=None):
        """Replaces the outside services for this test, with failures injected."""
        services = type(self.env["platform.services"])
        state = self.env["platform.services"]._dry_state()
        provider = provider if provider is not None else DryRunProvider(state["provider"])
        dns = dns if dns is not None else DryRunDns(state["dns"])
        probe = probe if probe is not None else DryRunProbe()
        self.patch(services, "_outside", lambda _self: (provider, dns, probe))
        return provider, dns, probe


class PlatformCase(PlatformMixin, TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_platform()
