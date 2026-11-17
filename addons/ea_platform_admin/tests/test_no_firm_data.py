"""The control plane holds no firm's data and no way into a firm's server."""

import ast
import re
from datetime import datetime
from pathlib import Path

from odoo.tests import tagged

from ..services import heartbeat
from .. import refuse_firm_database
from ..services.heartbeat import HeartbeatRejected
from ..services.simulator import healthy_figures, signed_request
from .common import PlatformCase

ADDON = Path(__file__).parents[1]

FORBIDDEN_FIELD_WORDS = re.compile(
    r"password|passwd|pgpass|db_user|db_pass|db_host|dsn|connection_string|private_key|secret_key|access_key|"
    r"s3_|restic|backup_key(?!_escrowed)|master|smtp|client_|engagement_(?!s_active)|trial_balance|signature(?!_)"
)
# The only secrets on the platform, all listed in SECURITY-MODEL.md. None opens a firm's database. The third
# (2026-11-18) is a new firm administrator's one-time link, kept until it is shown once, 72 hours at most.
ALLOWED_SECRET_FIELDS = {"heartbeat_token", "first_admin_token", "admin_link_token"}
# The practice computer's: its heartbeat token, and a practice space's one-time first-login link.
PRACTICE_SECRET_FIELDS = {"platform.practice.computer": {"heartbeat_token"}, "platform.practice.space": {"first_login_token"}}
SECRET_WORDS = re.compile(r"token|secret|key(?!_id|_fingerprint|_escrowed)")
# The one exception, by name: the one-time password of a TEST account on staging or a practice space, on a
# transient wizard, shown once and blanked on close. Never a firm's credential; only its hash leaves the
# console (docs/runbook/ENVIRONMENTS.md).
SHOWN_ONCE_FIELDS = {"platform.environment.account.wizard.password"}
# A firm's mail password, typed on the "Email for this firm" form (owner, 2026-11-17). Not a column: taken
# out of what the screen sends before anything is written, kept encrypted outside the database until the
# firm's heartbeat collects it (services/mail_handoff.py). The flag only says that one is waiting.
_MAIL_FORMS = ("platform.mail.form", "platform.firm.mail.wizard", "platform.onboarding.wizard")
NEVER_STORED_FIELDS = {f"{model}.mail_password" for model in _MAIL_FORMS}
FLAG_FIELDS = {f"{model}.mail_password_kept" for model in _MAIL_FORMS}

FORBIDDEN_IMPORTS = {"paramiko", "fabric", "xmlrpc", "odoorpc", "asyncssh", "subprocess", "socket", "ftplib", "smtplib", "telnetlib"}
FORBIDDEN_CALLS = re.compile(r"psycopg2\.connect|db_connect|sql_db\.|os\.system|os\.popen")

HEARTBEAT_FIELDS = {
    "addon_release", "disk_total_gb", "disk_used_pct", "mem_total_mb", "mem_available_mb", "users_active",
    "engagements_active", "last_backup_at", "last_backup_ok", "last_restore_test_at", "last_restore_test_ok",
    "cert_expires_on", "mail_enabled", "update_state", "update_release", "export_state", "export_at",
    "export_sha256", "ssh_sessions_24h", "last_ssh_at", "odoo_version",
    "addons_reported_at", "addons_refused_count", "addons_unknown_count",
}


@tagged("post_install", "-at_install")
class TestNoFirmData(PlatformCase):
    def _platform_models(self):
        return [name for name in self.env if name.startswith("platform.")]

    def test_no_audit_model_exists_here(self):
        self.assertFalse([name for name in self.env if name.startswith("ea.audit.")])

    def test_the_manifest_depends_on_no_audit_addon(self):
        manifest = ast.literal_eval((ADDON / "__manifest__.py").read_text(encoding="utf-8"))
        self.assertEqual(sorted(manifest["depends"]), ["auth_signup", "base", "mail", "web"])

    def test_it_refuses_to_install_beside_an_audit_addon(self):
        refuse_firm_database(self.env)  # nothing installed: passes
        modules = self.env["ir.module.module"].sudo()
        # The row exists when the audit addons are on the addons path, as in CI.
        module = modules.search([("name", "=", "ea_audit_core")]) or modules.create({"name": "ea_audit_core"})
        module.state = "installed"
        self.env.flush_all()
        with self.assertRaisesRegex(Exception, "does not install"):
            refuse_firm_database(self.env)

    def test_no_field_could_hold_a_firms_credential_or_audit_data(self):
        wrong = []
        for model in self._platform_models():
            for name in self.env[model]._fields:
                exempt = SHOWN_ONCE_FIELDS | NEVER_STORED_FIELDS | FLAG_FIELDS
                if FORBIDDEN_FIELD_WORDS.search(name) and f"{model}.{name}" not in exempt:
                    wrong.append(f"{model}.{name}")
        self.assertEqual(wrong, [])

    def test_the_mail_password_is_never_a_column(self):
        for qualified in NEVER_STORED_FIELDS:
            model, name = qualified.rsplit(".", 1)
            self.assertFalse(self.env[model]._fields[name].store, qualified)
        for qualified in FLAG_FIELDS:
            model, name = qualified.rsplit(".", 1)
            self.assertEqual(self.env[model]._fields[name].type, "boolean", qualified)

    def test_the_only_secret_fields_are_the_ones_declared(self):
        firm_fields = self.env["platform.firm"]._fields
        secrets = {
            name for name in firm_fields
            if SECRET_WORDS.search(name) and name not in ("ssh_public_key",)
        }
        self.assertEqual(secrets, ALLOWED_SECRET_FIELDS)
        for model in self._platform_models():
            if model == "platform.firm":
                continue
            wrong = [
                name for name in self.env[model]._fields
                if SECRET_WORDS.search(name) and name not in ("ssh_public_key", "own_key", "confirm_real",
                                                              "release_signing_public_key", "previous_hash")
                and name not in PRACTICE_SECRET_FIELDS.get(model, ())
            ]
            self.assertEqual(wrong, [], model)

    def test_the_secrets_are_hidden_from_everyone_but_odoo_administrators(self):
        for name in ALLOWED_SECRET_FIELDS:
            self.assertEqual(self.env["platform.firm"]._fields[name].groups, "base.group_system")
        for model, names in PRACTICE_SECRET_FIELDS.items():
            for name in names:
                self.assertEqual(self.env[model]._fields[name].groups, "base.group_system")

    def test_no_view_shows_a_secret(self):
        views = self.env["ir.ui.view"].sudo().search([("model", "like", "platform.%")])
        for view in views:
            for name in ALLOWED_SECRET_FIELDS | {"first_login_token"}:
                self.assertNotIn(f'name="{name}"', view.arch_db, view.name)

    def test_the_code_has_no_way_to_reach_a_firm(self):
        """No SSH library, no remote database, no RPC, no shell: only the provider and DNS interfaces."""
        for path in ADDON.rglob("*.py"):
            if "tests" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    names = [node.module.split(".")[0]]
                self.assertFalse(FORBIDDEN_IMPORTS & set(names), f"{path.name}: {names}")
            self.assertFalse(FORBIDDEN_CALLS.search(source), path.name)

    def test_only_the_provider_module_opens_a_connection(self):
        for path in ADDON.rglob("*.py"):
            if "tests" in path.parts or path.name == "provider_vultr.py":
                continue
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("urllib.request", source, path.name)
            self.assertNotIn("import requests", source, path.name)

    def test_the_firm_record_stores_exactly_the_listed_figures(self):
        """Every key a heartbeat can carry has its field, and no heartbeat figure carries text."""
        names = set(self.env["platform.firm"]._fields)
        self.assertLessEqual(HEARTBEAT_FIELDS, names)
        for key, check in heartbeat.FIGURES.items():
            self.assertFalse(check("Rapport d'audit de la société Agro SA"), key)

    def test_audit_data_in_a_signed_heartbeat_is_refused_and_not_kept(self):
        firm, _job = self._onboard()
        figures = healthy_figures(datetime.utcnow().replace(microsecond=0), self.release.sha)
        figures["client_name"] = "Société Agro SA"
        token = firm.sudo().heartbeat_token
        timestamp = firm.last_heartbeat_timestamp + 1
        headers, body = signed_request(token, firm.slug, timestamp, figures)
        with self.assertRaises(HeartbeatRejected) as caught:
            self.env["platform.firm"]._receive_heartbeat(headers, body)
        self.assertEqual(caught.exception.code, "unknown_key")
        self.env.flush_all()
        self._assert_nowhere("Agro")

    def _assert_nowhere(self, needle):
        """Looks through every text column of every platform table, and the parameters."""
        self.env.flush_all()
        self.env.cr.execute("""
            SELECT table_name, column_name FROM information_schema.columns
             WHERE table_schema = 'public' AND data_type IN ('text', 'character varying', 'jsonb')
               AND (table_name LIKE 'platform\\_%%' OR table_name = 'ir_config_parameter')
        """)
        for table, column in self.env.cr.fetchall():
            self.env.cr.execute(
                f'SELECT count(*) FROM "{table}" WHERE "{column}"::text LIKE %s',  # noqa: S608
                [f"%{needle}%"],
            )
            self.assertEqual(self.env.cr.fetchone()[0], 0, f"{needle[:6]}... found in {table}.{column}")

    def test_storage_credentials_are_kept_nowhere(self):
        firm, _job = self._onboard()
        provider = self.env["platform.services"]._outside()[0]
        credentials = provider.storage_credentials(firm.storage_id)
        self._assert_nowhere(credentials.secret_key)
        self._assert_nowhere(credentials.access_key)

    def test_the_first_boot_text_is_kept_nowhere(self):
        firm, job = self._onboard()
        provider = self.env["platform.services"]._outside()[0]
        text = job._user_data(provider.storage_credentials(firm.storage_id))
        self.assertIn("#cloud-config", text)
        self._assert_nowhere("#cloud-config")

    def test_the_token_never_reaches_the_log_or_the_steps(self):
        firm, job = self._onboard()
        token = firm.sudo().heartbeat_token
        self.assertFalse(self.env["platform.log"].search_count([("detail", "ilike", token)]))
        self.assertFalse(job.step_ids.filtered(lambda s: token in (s.message or "")))

    def test_first_boot_text_holds_no_firm_credential(self):
        firm, job = self._onboard()
        provider = self.env["platform.services"]._outside()[0]
        text = job._user_data(provider.storage_credentials(firm.storage_id))
        for word in ("db_password", "admin_passwd", "PGPASSWORD", "RESTIC_PASSWORD"):
            self.assertNotIn(word, text)

    def test_settings_have_no_token_field(self):
        names = self.env["platform.settings"]._fields
        self.assertFalse([name for name in names if "token" in name])

    def test_no_real_provider_can_be_built_during_tests(self):
        self.env["ir.config_parameter"].sudo().set_param("ea_platform.provider", "vultr")
        provider, dns, probe = self.env["platform.services"]._outside()
        self.assertTrue(provider.is_simulation)
        self.assertTrue(dns.is_simulation)
        self.assertTrue(probe.is_simulation)
