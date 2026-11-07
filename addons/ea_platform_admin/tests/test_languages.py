from odoo.exceptions import UserError
from odoo.tests import tagged

from ..models.i18n import read, t
from ..services.messages import _
from .common import PlatformCase


@tagged("post_install", "-at_install")
class TestLanguages(PlatformCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["res.lang"]._activate_lang("fr_FR")
        cls.fr = cls.env(context={"lang": "fr_FR"})
        cls.en = cls.env(context={"lang": "en_US"})

    def test_a_message_follows_the_readers_language(self):
        message = _("All is normal")
        self.assertEqual(t(self.en, message), "All is normal")
        self.assertEqual(t(self.fr, message), "Tout est normal")

    def test_parameters_and_nested_messages_are_translated(self):
        message = _("No heartbeat for %(age)s", age=_("%(count)s days", count=3))
        self.assertEqual(t(self.en, message), "No heartbeat for 3 days")
        self.assertEqual(t(self.fr, message), "Aucun signal de vie depuis 3 jours")

    def test_one_stored_reason_reads_in_both_languages(self):
        firm = self._active_firm()
        firm.sudo().write({"disk_used_pct": 85})
        firm._evaluate_health()
        self.assertEqual(firm.with_env(self.en).health_summary, "Disk 85% full")
        self.assertEqual(firm.with_env(self.fr).health_summary, "Disque plein à 85 %")

    def test_step_log_reads_in_both_languages(self):
        _firm, job = self._onboard()
        step = job.step_ids.filtered(lambda s: s.code == "server")
        self.assertEqual(step.with_env(self.en).label, "Creating the server")
        self.assertEqual(step.with_env(self.fr).label, "Création du serveur")

    def test_the_log_reads_in_both_languages(self):
        firm, _job = self._onboard()
        row = firm.log_ids.filtered(lambda r: r.action == "Firm went live")
        self.assertEqual(row.with_env(self.en).action_text, "Firm went live")
        self.assertEqual(row.with_env(self.fr).action_text, "Cabinet mis en service")

    def test_what_someone_typed_stays_as_typed(self):
        self.assertEqual(read(self.fr, "Fin de contrat à 100 %"), "Fin de contrat à 100 %")

    def test_errors_follow_the_users_language(self):
        self.operator.lang = "fr_FR"
        self.env.invalidate_all()
        with self.assertRaisesRegex(UserError, "réservé"):
            self._wizard("www").with_context(lang="fr_FR").action_next()
        self.operator.lang = "en_US"
        self.env.invalidate_all()
        with self.assertRaisesRegex(UserError, "reserved"):
            self._wizard("dev").with_context(lang="en_US").action_next()

    def test_the_preflight_follows_the_users_language(self):
        wizard = self._through_steps(self._wizard())
        self.assertIn("SIMULATION", wizard.with_context(lang="en_US").preview_mode)
        self.assertIn("aucun serveur", wizard.with_context(lang="fr_FR").preview_mode)

    def test_the_wizards_language_is_the_firms_default(self):
        firm, job = self._onboard("cabinet-en", lang="en_US")
        self.assertEqual(firm.lang, "en_US")
        provider = self.env["platform.services"]._outside()[0]
        self.assertIn("FIRM_LANG='en_US'", job._user_data(provider.storage_credentials(firm.storage_id)))
        french, job2 = self._onboard("cabinet-fr", lang="fr_FR")
        provider = self.env["platform.services"]._outside()[0]
        self.assertIn("FIRM_LANG='fr_FR'", job2._user_data(provider.storage_credentials(french.storage_id)))
