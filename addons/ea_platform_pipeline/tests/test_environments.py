"""The Status page's environments: pages in English and French, Connect, Promote's guards, test accounts."""

import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from odoo.addons.ea_platform_admin.services.heartbeat import format_instant
from odoo.addons.ea_platform_admin.tests.common import PlatformCase

from ..services import environments as envs
from .test_pipeline_flow import PipelineMixin

NOW = lambda: datetime.utcnow().replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731


def user(login, name, role="staff", active=True, online=False, protected=False):
    return {"login": login, "name": name, "role": role, "active": active, "last_login": NOW(), "online": online,
            "protected": protected}


@tagged("post_install", "-at_install")
class TestEnvironments(PipelineMixin, PlatformCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_pipeline()
        cls.env["res.lang"]._activate_lang("fr_FR")
        cls.env["ir.module.module"]._load_module_terms(["ea_platform_admin", "ea_platform_pipeline"], ["fr_FR"], overwrite=True)
        cls.folder = tempfile.mkdtemp()
        cls.spool = os.path.join(cls.folder, "env-requests")
        os.mkdir(cls.spool, 0o700)
        cls.state_path = os.path.join(cls.folder, "env-state.json")
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("ea_platform_pipeline.env_spool_dir", cls.spool)
        params.set_param("ea_platform_pipeline.env_state_file", cls.state_path)
        params.set_param("ea_platform_pipeline.state_file", os.path.join(cls.folder, "no-pipeline-state.json"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.folder, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        for name in os.listdir(self.spool):
            os.unlink(os.path.join(self.spool, name))
        if os.path.exists(self.state_path):
            os.unlink(self.state_path)

    # ------------------------------------------------------------------ helpers

    def _state(self, requests=None, staging_users=None, staging_revision="24a65a86", practice_users=None):
        data = {
            "schema": 1, "generated": NOW(),
            "staging": {"reachable": True, "service_active": True, "odoo_version": "19.0", "revision": staging_revision,
                        "modules": [["ea_audit_core", "19.0.1.0.0"]], "db_size_mb": 76, "up_since": NOW(), "mail_off": True,
                        "releases": [{"name": staging_revision, "at": NOW(), "result": "running"}],
                        "users": staging_users if staging_users is not None else [
                            user("admin@auditisa.cm", "Owner", "admin", protected=True),
                            user("tester@auditisa.cm", "Test Person", "senior", online=True)]},
            "practice": {"reachable": True, "service_active": True, "odoo_version": "19.0", "revision": "24a65a86e804",
                         "mail_off": True, "releases": [{"name": "24a65a86e804", "at": NOW(), "result": "ok"}],
                         "spaces": [{"slug": "demo-akwa", "db_size_mb": 75, "users": practice_users if practice_users is not None else [
                             user("first@akwa.cm", "First Admin", "admin", protected=True)]}]},
            "requests": requests or [],
        }
        with open(self.state_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        return data

    def _env(self, code, who=None, lang="en_US"):
        record = self.env.ref(f"ea_platform_pipeline.environment_{code}")
        return record.with_user(who or self.viewer).with_context(lang=lang)

    def _spooled(self):
        rows = []
        for name in sorted(os.listdir(self.spool)):
            with open(os.path.join(self.spool, name), encoding="utf-8") as handle:
                rows.append(json.load(handle))
        return rows

    def _create_account(self, who=None, code="staging", **values):
        environment = self._env(code, who or self.operator)
        action = environment.action_new_account()
        wizard = self.env["platform.environment.account.wizard"].with_user(who or self.operator).browse(action["res_id"])
        wizard.write({"name": "Awa Test", "login": "awa.test@auditisa.cm", "role": "manager", **values})
        wizard.action_confirm()
        return wizard

    # ------------------------------------------------------------------ the menu, the page, the tabs, two languages

    def test_the_status_menu_opens_the_environments_page(self):
        menu = self.env.ref("ea_platform_admin.menu_status")
        action = self.env.ref("ea_platform_pipeline.action_environments")
        self.assertEqual(menu.action, action)
        self.assertEqual(action.path, "status")
        self.assertEqual(action.res_id, self.env.ref("ea_platform_pipeline.environment_staging").id)
        self.assertEqual(self.env.ref("ea_platform_pipeline.action_pipeline_board").path, "status-board")
        self.assertEqual(self.env["platform.environment"].search([]).mapped("code"), ["production", "practice", "staging", "development"])

    def test_the_tabs_and_buttons_in_english_and_french(self):
        Environment = self.env["platform.environment"].with_user(self.owner)
        english = Environment.with_context(lang="en_US").get_views([(False, "form")])["views"]["form"]["arch"]
        french = Environment.with_context(lang="fr_FR").get_views([(False, "form")])["views"]["form"]["arch"]
        for word in ("History", "Backups", "Monitor", "Logs", "People", "Connect", "Promote to Staging", "Promote to Production"):
            self.assertIn(word, english)
        for word in ("Historique", "Sauvegardes", "Surveillance", "Journaux", "Personnes", "Se connecter",
                     "Promouvoir vers le staging", "Promouvoir vers la production"):
            self.assertIn(word, french)

    def test_every_page_renders_for_a_viewer_in_both_languages(self):
        self._state()
        for code in ("production", "practice", "staging", "development"):
            for lang in ("en_US", "fr_FR"):
                environment = self._env(code, lang=lang)
                for name in ("sidebar_html", "head_html", "info_html", "rules_html", "deploys_html", "commits_html",
                             "backups_html", "monitor_html", "people_html"):
                    self.assertTrue(environment[name] is not None, (code, lang, name))
                environment.log_ids  # noqa: B018
        sidebar_en = self._env("staging").sidebar_html
        sidebar_fr = self._env("staging", lang="fr_FR").sidebar_html
        for word in ("Production", "Practice", "Staging", "Development"):
            self.assertIn(word, sidebar_en)
        for word in ("Production", "Entraînement", "Développement"):
            self.assertIn(word, sidebar_fr)
        self.assertIn("ea-env-active", sidebar_en)
        self.assertIn("never sends email", self._env("staging").rules_html)
        self.assertIn("jamais", self._env("staging", lang="fr_FR").rules_html)

    def test_the_info_line_reads_staging(self):
        self._state()
        staging = self._env("staging")
        self.assertEqual(staging.color, "green")
        self.assertEqual(staging.revision, "24a65a86")
        for text in ("19.0", "76 MB", "github.com/Nekoutb/auditisa-odoo/commit/24a65a86", "ea_audit_core"):
            self.assertIn(text, staging.info_html)
        self.assertIn("Running now", staging.deploys_html)

    def test_without_env_sync_the_page_says_so(self):
        staging = self._env("staging")
        self.assertIn("env-sync", staging.rules_html)
        self.assertIn("env-sync", staging.people_html)

    def test_a_missing_github_key_is_said_plainly(self):
        state = {"schema": 1, "generated": NOW(), "next": {}, "odoo": {"github": "no_key"}}
        path = os.path.join(self.folder, "pipeline.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        self.env["ir.config_parameter"].sudo().set_param("ea_platform_pipeline.state_file", path)
        self.assertIn("Connect GitHub read-only key", self._env("staging").commits_html)
        self.assertIn("auditisa_odoo_ro", self._env("development").commits_html)

    def test_commits_on_the_branch_with_their_message(self):
        state = {"schema": 1, "generated": NOW(), "next": {}, "odoo": {
            "github": "ok", "branches": {"dev": {"sha": "a" * 40, "author": "Nekoutb", "at": NOW()}},
            "log": {"dev": [{"sha": "a" * 40, "author": "Nekoutb", "at": NOW(), "subject": "Status <b>page</b>"}]}}}
        path = os.path.join(self.folder, "pipeline.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        self.env["ir.config_parameter"].sudo().set_param("ea_platform_pipeline.state_file", path)
        html = self._env("development").commits_html
        self.assertIn("aaaaaaaa", html)
        self.assertIn("Status &lt;b&gt;page&lt;/b&gt;", html)  # escaped, never rendered

    # ------------------------------------------------------------------ production: counts only, Connect is a support visit

    def test_production_shows_counts_only(self):
        firm = self._firm_on("cabinet-a", users_active=7)
        production = self._env("production")
        self.assertIn(firm, production.firm_ids)
        self.assertEqual(production.firm_ids.users_active, 7)
        self.assertIn("counts only", production.people_html)
        self.assertNotIn("awa@exemple.cm", production.people_html + production.monitor_html + production.backups_html)
        self.assertFalse(self.env["platform.environment.account"].search([("environment_id", "=", production.id)]))

    def test_production_connect_starts_the_read_only_support_visit(self):
        firm = self._firm_on("cabinet-a")
        action = self._env("production", self.operator).action_connect()
        wizard = self.env["platform.environment.connect"].with_user(self.operator).browse(action["res_id"])
        wizard.firm_id = firm
        result = wizard.action_open()
        self.assertEqual(result["res_model"], "platform.support.visit.wizard")
        self.assertEqual(result["context"]["default_firm_id"], firm.id)
        with self.assertRaises(UserError):
            self._env("production", self.viewer).action_connect()

    def test_staging_connect_opens_the_site_and_practice_asks_which_space(self):
        self._state()
        result = self._env("staging").action_connect()
        self.assertEqual((result["type"], result["url"], result["target"]), ("ir.actions.act_url", "https://test.auditisa.com", "new"))
        action = self._env("practice").action_connect()
        wizard = self.env["platform.environment.connect"].with_user(self.viewer).browse(action["res_id"])
        wizard.space = "demo-akwa"
        self.assertEqual(wizard.action_open()["url"], "https://test.auditisa.com:8443/practice/demo-akwa")
        with self.assertRaises(UserError):
            self._env("development").action_connect()

    # ------------------------------------------------------------------ test accounts

    def test_an_operator_creates_a_test_account_and_sees_the_password_once(self):
        wizard = self._create_account()
        self.assertTrue(wizard.done)
        password = wizard.password
        self.assertRegex(password, r"^[A-Za-z0-9]{4}(-[A-Za-z0-9]{4}){3}$")
        (payload,) = self._spooled()
        self.assertEqual((payload["action"], payload["target"], payload["login"], payload["role"]),
                         ("create", "staging", "awa.test@auditisa.cm", "manager"))
        self.assertTrue(self.env["res.users"]._crypt_context().verify(password, payload["password_hash"]))
        self.assertNotIn(password, json.dumps(payload))
        request = self.env["platform.environment.request"].search([("ref", "=", payload["id"])])
        self.assertEqual(request.state, "queued")
        logged = self.env["platform.log"].search([], limit=1)
        self.assertEqual(logged.action_text, "Test account creation asked on staging")
        self.assertNotIn(password, logged.detail or "")
        self.assertNotIn("pbkdf2", logged.detail or "")
        wizard.action_close()
        self.assertFalse(wizard.password)

    def test_the_outcome_comes_back_and_is_logged(self):
        wizard = self._create_account()
        (payload,) = self._spooled()
        self._state(requests=[{"id": payload["id"], "state": "done", "code": "", "at": NOW()}],
                    staging_users=[user("awa.test@auditisa.cm", "Awa Test", "manager")])
        self.env["platform.environment"]._cron_sync()
        request = self.env["platform.environment.request"].search([("ref", "=", wizard.request_ref)])
        self.assertEqual(request.state, "done")
        self.assertEqual(self.env["platform.log"].search([], limit=1).action_text, "Test account created on staging")
        account = self._env("staging").account_ids
        self.assertEqual(account.mapped("login"), ["awa.test@auditisa.cm"])
        self.assertEqual(account.role, "manager")

    def test_a_failure_is_said_in_plain_words(self):
        self._create_account()
        (payload,) = self._spooled()
        self._state(requests=[{"id": payload["id"], "state": "failed", "code": "exists", "at": NOW()}])
        self.env["platform.environment"]._cron_sync()
        request = self.env["platform.environment.request"].search([("ref", "=", payload["id"])])
        self.assertEqual(request.state, "failed")
        self.assertIn("already exists", request.message)
        self.assertEqual(self.env["platform.log"].search([], limit=1).action_text, "Test account creation failed on staging")

    def test_disable_and_new_password_are_requested_and_logged(self):
        self._state()
        self.env["platform.environment"]._cron_sync()
        account = self._env("staging", self.operator).account_ids.filtered(lambda a: a.login == "tester@auditisa.cm")
        self.assertTrue(account.online)
        account.action_disable()
        (payload,) = self._spooled()
        self.assertEqual((payload["action"], payload["login"]), ("disable", "tester@auditisa.cm"))
        self.assertNotIn("password_hash", payload)
        self.assertEqual(self.env["platform.log"].search([], limit=1).action_text, "Test account disabling asked on staging")
        self.assertTrue(account.pending)
        with self.assertRaises(UserError):
            account.action_disable()  # one change at a time
        self._state(requests=[{"id": payload["id"], "state": "done", "code": "", "at": NOW()}])
        self.env["platform.environment"]._cron_sync()
        action = account.action_reset_password()
        wizard = self.env["platform.environment.account.wizard"].with_user(self.operator).browse(action["res_id"])
        wizard.action_confirm()
        reset = [row for row in self._spooled() if row["action"] == "reset"]
        self.assertEqual(len(reset), 1)
        self.assertTrue(self.env["res.users"]._crypt_context().verify(wizard.password, reset[0]["password_hash"]))
        self.assertEqual(self.env["platform.log"].search([], limit=1).action_text, "New password asked for a test account on staging")

    def test_a_practice_space_account_names_its_space(self):
        self._state()
        self.env["platform.environment"]._cron_sync()
        self._create_account(code="practice", space="demo-akwa")
        (payload,) = self._spooled()
        self.assertEqual(payload["target"], "practice:demo-akwa")
        self.assertEqual(self.env["platform.log"].search([], limit=1).action_text, "Test account creation asked in a practice space")

    def test_protected_accounts_are_left_alone(self):
        self._state()
        self.env["platform.environment"]._cron_sync()
        for code in ("staging", "practice"):
            protected = self._env(code, self.operator).account_ids.filtered("protected")
            self.assertTrue(protected, code)
            with self.assertRaises(UserError):
                protected[0].action_disable()
            with self.assertRaises(UserError):
                protected[0].action_reset_password()
        self.assertEqual(self._spooled(), [])

    def test_a_viewer_only_looks(self):
        self._state()
        self.env["platform.environment"]._cron_sync()
        staging = self._env("staging", self.viewer)
        self.assertTrue(staging.account_ids)
        with self.assertRaises(UserError):
            staging.action_new_account()
        with self.assertRaises(AccessError):
            self.env["platform.environment.account.wizard"].with_user(self.viewer).create({"environment_id": staging.id})
        with self.assertRaises(UserError):
            staging.account_ids[0].action_disable()
        with self.assertRaises(UserError):
            staging.account_ids[0].action_reset_password()
        with self.assertRaises(UserError):
            self.env["platform.environment.request"].with_user(self.viewer)._submit("disable", "staging", "tester@auditisa.cm")
        self.assertEqual(self._spooled(), [])

    def test_never_on_a_client_firm(self):
        with self.assertRaises(UserError):
            self._env("production", self.operator).action_new_account()
        with self.assertRaises(UserError):
            self.env["platform.environment.request"].with_user(self.operator)._submit("disable", "firm:cabinet-a", "a@b.cm")
        self.assertIn(envs._("Accounts are made only on staging or in a practice space."),
                      envs.request_errors("disable", "cabinet-a", "a@b.cm"))
        self.assertEqual(self._spooled(), [])

    def test_without_env_sync_nothing_is_sent(self):
        self.env["ir.config_parameter"].sudo().set_param("ea_platform_pipeline.env_spool_dir", "/nonexistent/env-requests")
        before = self.env["platform.environment.request"].search_count([])
        with self.assertRaises(UserError):
            self._create_account()
        self.assertEqual(self.env["platform.environment.request"].search_count([]), before)

    def test_a_request_without_an_answer_expires(self):
        self._create_account()
        request = self.env["platform.environment.request"].search([], limit=1)
        self.env.cr.execute("UPDATE platform_environment_request SET create_date = %s WHERE id = %s",
                            [fields.Datetime.now() - timedelta(minutes=20), request.id])
        request.invalidate_recordset()
        self.env["platform.environment"]._cron_sync()
        self.assertEqual((request.state, request.code), ("failed", "expired"))

    # ------------------------------------------------------------------ Promote: the guards

    def _promote(self, target, who=None):
        environment = self._env("staging", who or self.owner)
        action = environment.action_promote_staging() if target == "staging" else environment.action_promote_production()
        self.assertEqual(action["res_model"], "platform.environment.promote")
        return self.env["platform.environment.promote"].with_user(who or self.owner).browse(action["res_id"])

    def _computer(self):
        return self.env["platform.practice.computer"]._enrol("practice-1", token_path=None, simulation=True)

    def test_promote_is_the_owners_alone(self):
        self._computer()
        for who in (self.viewer, self.operator):
            for button in ("action_promote_staging", "action_promote_production"):
                with self.assertRaises(UserError):
                    getattr(self._env("staging", who), button)()

    def test_a_new_version_shows_as_ready_and_promote_to_staging_sends_it_in_one_click(self):
        computer = self._computer()
        page = self._env("staging", self.owner)
        self.assertIn("New version ready:", page.release_html)
        self.assertIn(self.release2.sha[:12], page.release_html)
        wizard = self._promote("staging")
        self.assertEqual(wizard.release_id, self.release2)
        self.assertFalse(wizard.problem)
        self.assertIn("practice spaces", wizard.summary_html)
        self.assertNotIn("signature", wizard.summary_html.lower())
        result = wizard.action_confirm()
        self.assertEqual(result["type"], "ir.actions.act_window_close")
        self.assertEqual(computer.desired_release_id, self.release2)
        self.assertEqual(computer._answer()["release"]["bundle_sha256"], self.release2.bundle_sha256)
        logged = self.env["platform.log"].search([], limit=1)
        self.assertEqual(logged.action_text, "Release sent to the practice computer")
        self.assertIn(self.release2.sha[:12], logged.detail_text)
        self.env.invalidate_all()
        self.assertIn("Being installed on Staging:", self._env("staging", self.owner).release_html)
        computer._simulate_heartbeat()
        self.env.invalidate_all()
        html = self._env("staging", self.owner).release_html
        self.assertNotIn("New version ready:", html)
        self.assertIn(self.release2.sha[:12], html)
        # Nothing newer: the second click says so in plain words and sends nothing.
        again = self._promote("staging")
        self.assertIn("no new version", again.problem or "")
        with self.assertRaises(UserError):
            again.action_confirm()

    def test_promote_to_staging_reads_in_french(self):
        self._computer()
        wizard = self._promote("staging").with_context(lang="fr_FR")
        self.assertIn("Étape suivante", wizard.summary_html)
        self.assertIn("Nouvelle version", self._env("staging", self.owner, lang="fr_FR").release_html)

    def test_promote_to_production_is_refused_until_staging_runs_the_version(self):
        canary = self._firm_on("cabinet-a")
        computer = self._computer()
        wizard = self._promote("production")
        self.assertIn("Staging runs no version yet", wizard.problem)
        with self.assertRaises(UserError):
            wizard.action_confirm()
        # Sent to Staging but not installed there yet: still refused.
        computer.sudo().write({"desired_release_id": self.release2.id})
        computer.sudo().release = self.release.sha
        wizard = self._promote("production")
        self.assertEqual(wizard.release_id, self.release)
        self.assertIn("Every client firm already runs this version", wizard.problem)
        with self.assertRaises(UserError):
            wizard.action_confirm()
        self.assertFalse(self.env["platform.rollout"].search([("release_id", "=", self.release2.id)]))
        self.assertNotEqual(canary.desired_release_id, self.release2)

    def test_promote_to_production_sends_what_staging_runs_in_one_click_with_no_wait(self):
        canary = self._firm_on("cabinet-a")
        other = self._firm_on("cabinet-b")
        self._on_staging()
        wizard = self._promote("production")
        self.assertEqual(wizard.release_id, self.release2)
        self.assertFalse(wizard.problem)
        for text in ("2 client firm(s)", "backup", "puts itself back"):
            self.assertIn(text, wizard.summary_html)
        result = wizard.action_confirm()
        promotion = self.env["platform.pipeline.promotion"].with_user(self.owner).browse(result["res_id"])
        self.assertEqual(promotion.state, "rolling")
        self.assertEqual(promotion.release_id, self.release2)
        self.assertEqual(promotion.rollout_id.line_ids.firm_id, canary | other)
        self.assertEqual(promotion.rollout_line_ids.filtered(lambda line: line.state == "requested").firm_id, canary)
        self.assertEqual(canary.desired_release_id, self.release2)
        self.assertEqual(canary._heartbeat_answer()["desired_bundle_sha256"], self.release2.bundle_sha256)
        self.assertTrue(self.env["platform.log"].search([("action", "ilike", "Promotion started")], limit=1))
        # One update at a time.
        self.assertIn("still running", self._promote("production").problem)
        promotion.rollout_id.action_simulate_answers()
        promotion.rollout_id.action_simulate_answers()
        self.assertEqual(promotion.rollout_id.state, "done")
        self.env.invalidate_all()
        self.assertIn("2 of 2 client firm(s)", self._env("production", self.owner).release_html)
        self.assertIn(self.release2.sha[:12], self._env("production", self.owner).deploys_html)

    def test_a_rollout_started_by_hand_also_waits_for_staging(self):
        canary = self._firm_on("cabinet-a")
        self._computer()
        rollout = self.env["platform.rollout"].with_user(self.owner).create(
            {"release_id": self.release2.id, "canary_firm_id": canary.id, "firm_ids": [(6, 0, canary.ids)]})
        with self.assertRaises(UserError):
            rollout.action_start()
        self._on_staging()
        rollout.action_start()
        self.assertEqual(rollout.state, "running")

    def test_the_confirmation_shows_exactly_what_changes(self):
        canary = self._firm_on("cabinet-a")
        other = self._firm_on("cabinet-b")
        self._staging()
        self._green()
        promotion = self._promotion(canary, canary | other)
        action = promotion.action_open_confirm()
        wizard = self.env["platform.pipeline.confirm"].with_user(self.owner).browse(action["res_id"])
        html = wizard.summary_html
        for text in (self.release.sha[:12], self.release2.sha[:12], canary.name, other.name, "backs itself up", "Staging"):
            self.assertIn(text, html)
        self.assertEqual(wizard.expected, f"PROMOTE {self.release2.sha[:12]}")

    def test_an_update_without_a_fresh_backup_fails_and_stops(self):
        canary = self._firm_on("cabinet-a")
        other = self._firm_on("cabinet-b")
        self._staging()
        self._green()
        promotion = self._promotion(canary, canary | other)
        promotion.action_run_checks()
        self._confirm(promotion.action_open_confirm())
        line = promotion.rollout_line_ids.filtered(lambda l: l.state == "requested")
        self.assertEqual(line.firm_id, canary)
        stale = format_instant(datetime.utcnow().replace(microsecond=0) - timedelta(days=1))
        canary._simulate_heartbeat(release=self.release2.sha, update_state="ok", update_release=self.release2.sha, last_backup_at=stale)
        self.assertEqual(line.state, "failed")
        self.assertEqual(promotion.rollout_id.state, "stopped")
        self.assertEqual(promotion.state, "stopped")
        self.assertNotEqual(other.desired_release_id, self.release2)
        production = self._env("production")
        self.assertIn(canary.name, production.deploys_html)
