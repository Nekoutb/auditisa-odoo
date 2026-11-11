"""The owner supplies no key: the console makes each firm's maintenance key itself, and keeps its private half
in a file only its own system user can open. Never in the database, on a screen or in a log."""

import os
import shutil
import stat
import tempfile
from datetime import timedelta

from cryptography.hazmat.primitives import serialization

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from ..services import firm_keys
from ..services.validation import ssh_key_fingerprint, ssh_public_key_errors
from .common import PlatformCase, ssh_key


@tagged("post_install", "-at_install")
class TestFirmKeys(PlatformCase):
    def setUp(self):
        super().setUp()
        self.folder = os.path.join(tempfile.mkdtemp(), "firm-keys")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.folder), ignore_errors=True)
        self.env["ir.config_parameter"].sudo().set_param(firm_keys.KEYS_DIR_PARAM, self.folder)

    def _private(self, slug):
        with open(os.path.join(self.folder, slug), "rb") as handle:
            return handle.read()

    def test_an_empty_field_passes_the_server_screen(self):
        wizard = self._wizard("cabinet-a", own_key=False, ssh_public_key=False)
        wizard.action_next()
        wizard.action_next()
        self.assertEqual(wizard.step, "addons")

    def test_an_empty_field_makes_a_key_for_the_firm(self):
        firm, job = self._onboard("cabinet-a", own_key=False, ssh_public_key=False)
        self.assertEqual(job.state, "done")
        self.assertTrue(firm.ssh_by_console)
        self.assertTrue(firm.ssh_public_key.startswith("ssh-ed25519 "))
        self.assertTrue(firm.ssh_public_key.endswith(" auditisa-console-cabinet-a"))
        self.assertEqual(ssh_public_key_errors(firm.ssh_public_key), [])
        self.assertTrue(firm.ssh_key_fingerprint.startswith("SHA256:"))
        # The public half is registered at the provider exactly as a pasted one.
        provider = self.env["platform.services"]._dry_state()["provider"]
        self.assertEqual([key["public_key"] for key in provider["ssh_keys"].values()], [firm.ssh_public_key])
        # The private half is the other half of that same key, in a file of the console's own user only.
        private = self._private("cabinet-a")
        self.assertIn(b"BEGIN OPENSSH PRIVATE KEY", private)
        loaded = serialization.load_ssh_private_key(private, password=None)
        public = loaded.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
        self.assertEqual(public, " ".join(firm.ssh_public_key.split()[:2]))
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.folder, "cabinet-a")).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.folder).st_mode), 0o700)
        self.assertEqual(os.listdir(self.folder), ["cabinet-a"])

    def test_a_key_pasted_but_not_asked_for_is_ignored(self):
        """The Advanced box is unticked: what sits in the hidden field does not count."""
        pasted = ssh_key(77)
        firm, _job = self._onboard("cabinet-a", own_key=False, ssh_public_key=pasted)
        self.assertTrue(firm.ssh_by_console)
        self.assertNotEqual(firm.ssh_public_key, pasted)

    def test_each_firm_has_its_own_key(self):
        first, _job = self._onboard("cabinet-a", own_key=False, ssh_public_key=False)
        second, _job = self._onboard("cabinet-b", own_key=False, ssh_public_key=False)
        self.assertNotEqual(first.ssh_public_key, second.ssh_public_key)
        self.assertNotEqual(first.ssh_key_fingerprint, second.ssh_key_fingerprint)
        self.assertNotEqual(self._private("cabinet-a"), self._private("cabinet-b"))
        self.assertEqual(sorted(os.listdir(self.folder)), ["cabinet-a", "cabinet-b"])

    def test_the_private_half_is_nowhere_in_the_database_or_the_log(self):
        firm, job = self._onboard("cabinet-a", own_key=False, ssh_public_key=False)
        private = self._private("cabinet-a").decode()
        body = "".join(private.splitlines()[1:-1])
        self.assertGreater(len(body), 100)
        self.env.flush_all()
        # Nothing the ORM can read holds it: not for an operator, not for the owner, not for an Odoo administrator.
        for who in (self.operator, self.owner, self.env.ref("base.user_admin")):
            for record in (firm, job, firm.log_ids, job.step_ids if "step_ids" in job._fields else job):
                record = record.with_user(who)
                readable = [name for name, field in record._fields.items()
                            if not field.groups or who.has_groups(field.groups)]
                for values in record.read(readable):
                    text = repr(values)
                    self.assertNotIn("PRIVATE KEY", text)
                    self.assertNotIn(body[:60], text)
        # Nor does any column of any platform table.
        self.env.cr.execute("SELECT table_name, column_name FROM information_schema.columns "
                            "WHERE table_name LIKE 'platform_%' AND data_type IN ('text', 'character varying', 'jsonb')")
        for table, column in self.env.cr.fetchall():
            self.env.cr.execute(f'SELECT count(*) FROM "{table}" WHERE "{column}"::text LIKE %s', ["%PRIVATE KEY%"])  # noqa: S608
            self.assertEqual(self.env.cr.fetchone()[0], 0, (table, column))
        # No field of the firm is made to hold it, and the form that made it kept nothing.
        self.assertFalse([name for name in firm._fields if "private" in name])
        wizard = self.env["platform.onboarding.wizard"].sudo().search([("slug", "=", "cabinet-a")])
        self.assertFalse(wizard.ssh_public_key)
        # The log says a key was made, by its public fingerprint.
        made = firm.log_ids.filtered(lambda row: row.action == "Maintenance key made by the console")
        self.assertEqual(made.detail_text, firm.ssh_key_fingerprint)

    def test_a_viewer_cannot_learn_where_the_keys_are_kept(self):
        self._onboard("cabinet-a", own_key=False, ssh_public_key=False)
        with self.assertRaises(Exception):
            self.env["ir.config_parameter"].with_user(self.viewer).get_param(firm_keys.KEYS_DIR_PARAM)

    def test_a_pasted_key_is_still_checked_and_stays_with_its_maker(self):
        wizard = self._wizard("cabinet-c", own_key=True, ssh_public_key="n'importe quoi")
        wizard.action_next()
        with self.assertRaisesRegex(UserError, "ssh-ed25519"):
            wizard.action_next()
        pasted = ssh_key(201)
        firm, _job = self._onboard("cabinet-a", own_key=True, ssh_public_key=pasted)
        self.assertEqual(firm.ssh_public_key, pasted)
        self.assertFalse(firm.ssh_by_console)
        self.assertFalse(os.path.exists(self.folder))
        again = self._wizard("cabinet-b", own_key=True, ssh_public_key=pasted)
        again.action_next()
        with self.assertRaisesRegex(UserError, "another firm"):
            again.action_next()
        # A key the console made cannot be pasted for another firm either.
        made, _job = self._onboard("cabinet-d", own_key=False, ssh_public_key=False)
        reuse = self._wizard("cabinet-e", own_key=True, ssh_public_key=made.ssh_public_key)
        reuse.action_next()
        with self.assertRaisesRegex(UserError, "another firm"):
            reuse.action_next()

    def test_the_advanced_box_ticked_and_left_empty_still_makes_a_key(self):
        firm, _job = self._onboard("cabinet-a", own_key=True, ssh_public_key=False)
        self.assertTrue(firm.ssh_by_console)

    def test_if_the_key_cannot_be_kept_nothing_is_created(self):
        blocker = os.path.join(os.path.dirname(self.folder), "a-file")
        with open(blocker, "w", encoding="ascii") as handle:
            handle.write("x")
        self.env["ir.config_parameter"].sudo().set_param(firm_keys.KEYS_DIR_PARAM, os.path.join(blocker, "keys"))
        wizard = self._through_steps(self._wizard("cabinet-a", own_key=False, ssh_public_key=False))
        with self.assertRaisesRegex(UserError, "could not keep"), self.env.cr.savepoint():
            wizard.action_confirm()
        self.assertFalse(self.env["platform.firm"].search_count([("slug", "=", "cabinet-a")]))

    def test_an_attempt_that_breaks_leaves_no_key_behind(self):
        wizard = self._through_steps(self._wizard("cabinet-a", own_key=False, ssh_public_key=False))

        def broken(_self, _firm):
            raise RuntimeError("made up")

        self.patch(type(self.env["platform.provision.job"]), "_start", broken)
        with self.assertRaises(RuntimeError), self.env.cr.savepoint():
            wizard.action_confirm()
        self.assertEqual(os.listdir(self.folder), [])
        self.assertFalse(self.env["platform.firm"].search_count([("slug", "=", "cabinet-a")]))

    def test_break_glass_names_the_key_the_console_keeps(self):
        firm, _job = self._onboard("cabinet-a", own_key=False, ssh_public_key=False)
        wizard = self.env["platform.breakglass.wizard"].with_user(self.operator).create({"firm_id": firm.id, "reason": "x"})
        self.assertIn(os.path.join(self.folder, "cabinet-a"), wizard.command)
        self.assertIn("root@cabinet-a.auditisa.com", wizard.command)
        self.assertNotIn("PRIVATE", wizard.command)

    def test_destroying_the_firm_erases_its_key(self):
        firm, _job = self._onboard("cabinet-a", own_key=False, ssh_public_key=False)
        other, _job = self._onboard("cabinet-b", own_key=False, ssh_public_key=False)
        firm.action_confirm_key_escrow()
        firm._evaluate_health()
        offboard = self.env["platform.offboard.wizard"].with_user(self.owner).create({
            "firm_id": firm.id, "typed_slug": firm.slug, "retention_days": 90, "reason": "Fin de contrat"})
        offboard.action_confirm()
        firm.action_simulate_export()
        firm.with_user(self.owner).action_confirm_export_received()
        firm.sudo().write({"export_at": fields.Datetime.now() - timedelta(days=91)})
        self.env.invalidate_all()
        self.assertTrue(os.path.exists(os.path.join(self.folder, "cabinet-a")))
        destroy = self.env["platform.destroy.wizard"].with_user(self.owner).create({"firm_id": firm.id})
        destroy.typed_slug = firm.slug
        destroy.action_next()
        destroy.typed_word = "DESTROY"
        destroy.action_destroy()
        self.assertEqual(firm.state, "archived")
        self.assertEqual(os.listdir(self.folder), ["cabinet-b"])
        self.assertIn("The firm's maintenance key erased from the console", firm.log_ids.mapped("action"))
        self.assertTrue(other.ssh_by_console)

    def test_a_slug_can_never_name_another_file(self):
        for slug in ("../etc/passwd", "a/b", "", "A", "ab", "a--b", "x" * 40, ".hidden"):
            with self.assertRaises(ValueError):
                firm_keys.key_path(self.folder, slug)
        self.assertEqual(firm_keys.key_path(self.folder, "cabinet-a"), os.path.join(self.folder, "cabinet-a"))
        self.assertTrue(ssh_key_fingerprint(firm_keys.generate("cabinet-a")[1]).startswith("SHA256:"))
