"""Trusted signers on the console: who may sign, the move from one key, and versions waiting for a signature."""

import base64
import hashlib
import io
import json
import tarfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged

from ..models.signer import PARAM_LEGACY_KEY, PARAM_SERIAL
from ..services import signers as trust
from .common import PlatformCase
from .test_addons import catalogue_bytes

SHA = "1234567890abcdef1234567890abcdef12345678"


def new_key():
    private = Ed25519PrivateKey.generate()
    return private, private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()


def bundle_bytes(extra=None):
    """A small .tar.gz, as build_release.sh makes, optionally carrying a list of signers."""
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        files = {"addons/ea_audit_core/__manifest__.py": b"{}"}
        files.update(extra or {})
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return out.getvalue()


class SignerCase(PlatformCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.alice, cls.alice_pem = new_key()
        cls.signer = cls.env["platform.signer"].with_user(cls.owner).create({
            "name": "Owner", "email": "contact@cm-ea.com", "public_pem": cls.alice_pem,
        })

    def _add(self, name="Marie Ngono", email="marie@example.com"):
        private, pem = new_key()
        signer = self.env["platform.signer"].with_user(self.owner).create({"name": name, "email": email, "public_pem": pem})
        return private, signer


@tagged("post_install", "-at_install")
class TestSigners(SignerCase):
    def test_only_the_owner_adds_or_removes_a_signer_and_the_log_keeps_it(self):
        _private, pem = new_key()
        for user in (self.viewer, self.operator):
            with self.assertRaises(AccessError):
                self.env["platform.signer"].with_user(user).create({"name": "X", "email": "x@example.com", "public_pem": pem})
            with self.assertRaises(AccessError):
                self.signer.with_user(user).action_remove()
        before = self.env["platform.signer"]._serial()
        _p, marie = self._add()
        self.assertEqual(self.env["platform.signer"]._serial(), before + 1)
        self.assertEqual(marie.fingerprint, trust.fingerprint(marie.public_pem))
        self.assertEqual(marie.added_by_id, self.owner)
        marie.with_user(self.owner).action_remove()
        self.assertFalse(marie.active)
        self.assertEqual(marie.removed_by_id, self.owner)
        actions = self.env["platform.log"].search([], limit=5).mapped("action")
        self.assertIn("Signer added", actions)
        self.assertIn("Signer removed", actions)

    def test_a_key_is_checked_never_changes_and_a_signer_is_never_deleted(self):
        with self.assertRaisesRegex(UserError, "PRIVATE"):
            self.env["platform.signer"].with_user(self.owner).create({
                "name": "X", "email": "x@example.com",
                "public_pem": "-----BEGIN PRIVATE KEY-----\nMC4CAQAwBQYDK2VwBCIEIA==\n-----END PRIVATE KEY-----"})
        with self.assertRaisesRegex(UserError, "already in the list"):
            self.env["platform.signer"].with_user(self.owner).create({
                "name": "Again", "email": "a@example.com", "public_pem": self.alice_pem})
        with self.assertRaises(UserError):
            self.signer.with_user(self.owner).write({"public_pem": new_key()[1]})
        with self.assertRaises(UserError):
            self.signer.with_user(self.owner).write({"active": False})
        with self.assertRaises(UserError):
            self.signer.with_user(self.owner).unlink()

    def test_the_signer_screens_speak_french(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        with self.assertRaisesRegex(AccessError, "Seul le propri"):
            self.signer.with_user(self.operator).with_context(lang="fr_FR").action_remove()
        with self.assertRaisesRegex(UserError, "Il doit rester au moins un signataire"):
            self.signer.with_user(self.owner).with_context(lang="fr_FR").action_remove()
        fr = self.env(context={"lang": "fr_FR"})
        self.assertEqual(fr["ir.model"]._get("platform.signer").name, "Signataire de confiance")
        self.assertEqual(fr.ref("ea_platform_admin.menu_release_pending").name, "En attente de signature")

    def test_the_last_signer_cannot_be_removed(self):
        with self.assertRaisesRegex(UserError, "At least one signer"):
            self.signer.with_user(self.owner).action_remove()

    def test_the_console_refuses_a_catalogue_from_an_unknown_signer(self):
        stranger, _pem = new_key()
        raw = catalogue_bytes(self.release2.sha)
        with self.assertRaisesRegex(UserError, "trusted signer"):
            self.release2._load_catalogue(raw, stranger.sign(raw))
        self.assertFalse(self.release2.catalogue_loaded_at)
        self.release2._load_catalogue(raw, self.alice.sign(raw))
        self.assertTrue(self.release2.catalogue_signed)
        self.assertEqual(self.release2.signer_id, self.signer)

    def test_a_removed_signer_is_refused_and_what_they_signed_stays(self):
        marie_key, marie = self._add()
        raw = catalogue_bytes(self.release.sha)
        self.release._load_catalogue(raw, marie_key.sign(raw))
        self.assertEqual(self.release.signer_id, marie)
        marie.with_user(self.owner).action_remove()
        self.assertEqual(self.release.signer_id, marie, "what they signed stays theirs")
        later = catalogue_bytes(self.release2.sha)
        with self.assertRaisesRegex(UserError, "trusted signer"):
            self.release2._load_catalogue(later, marie_key.sign(later))
        # The list a new firm or the next release gets: Marie is retired, valid for her release only.
        parsed = trust.parse(self.env["platform.signer"]._document())
        self.assertEqual([row["name"] for row in parsed["signers"]], ["Owner"])
        self.assertEqual(parsed["retired"][0]["valid_for"], [self.release.bundle_sha256])

    def test_a_new_firm_gets_the_whole_list_at_first_boot(self):
        _p, marie = self._add()
        firm, job = self._onboard("cabinet-s")
        provider = self.env["platform.services"]._outside()[0]
        text = job._user_data(provider.storage_credentials(firm.storage_id))
        for signer in (self.signer, marie):
            self.assertIn(f"/etc/auditisa-firm/trusted-signers/{signer.fingerprint}.pub", text)
        self.assertIn("trusted-signers/serial", text)

    def test_the_list_file_for_the_repository(self):
        action = self.signer.with_user(self.operator).action_download_list()
        attachment = self.env["ir.attachment"].browse(int(action["url"].split("/")[3].split("?")[0]))
        self.assertEqual(trust.parse(attachment.raw)["signers"][0]["fingerprint"], self.signer.fingerprint)
        with self.assertRaises(AccessError):
            self.signer.with_user(self.viewer).action_download_list()


@tagged("post_install", "-at_install")
class TestMigration(PlatformCase):
    def test_the_one_key_of_before_becomes_the_owner(self):
        _private, pem = new_key()
        self.env["ir.config_parameter"].sudo().set_param(PARAM_LEGACY_KEY, pem)
        self.env["ir.config_parameter"].sudo().set_param(PARAM_SERIAL, "0")
        self.release.sudo().catalogue_signed = True
        signer = self.env["platform.signer"]._migrate_single_key()
        self.assertEqual((signer.name, signer.email), ("Owner", "contact@cm-ea.com"))
        self.assertEqual(signer.fingerprint, trust.fingerprint(pem))
        self.assertTrue(signer.active)
        self.assertEqual(self.env["platform.signer"]._serial(), 1)
        self.assertEqual(self.release.signer_id, signer, "a release whose catalogue that key signed")
        self.assertFalse(self.release2.signer_id, "an unsigned release stays unsigned")
        self.assertEqual(self.env["ir.config_parameter"].sudo().get_param(PARAM_LEGACY_KEY), pem, "left for older tools")
        self.assertIn("Signer added", self.env["platform.log"].search([], limit=1).action)
        # Once only.
        self.assertFalse(self.env["platform.signer"]._migrate_single_key())
        self.assertEqual(self.env["platform.signer"].search_count([]), 1)

    def test_no_key_no_signer(self):
        self.env["ir.config_parameter"].sudo().set_param(PARAM_LEGACY_KEY, "")
        self.assertFalse(self.env["platform.signer"]._migrate_single_key())

    def test_settings_show_the_signers_and_no_longer_write_the_old_key(self):
        _private, pem = new_key()
        params = self.env["ir.config_parameter"].sudo()
        params.set_param(PARAM_LEGACY_KEY, pem)
        self.env["platform.signer"]._migrate_single_key()
        settings = self.env["platform.settings"].with_user(self.owner).create({"provider": "dry_run", "base_domain": "auditisa.com"})
        self.assertEqual(settings.signer_count, 1)
        self.assertIn("Owner", settings.signer_names)
        settings.action_save()
        self.assertEqual(params.get_param(PARAM_LEGACY_KEY), pem)


@tagged("post_install", "-at_install")
class TestWaitingForSignature(SignerCase):
    def _pending(self, user=None, bundle=None):
        bundle = bundle or bundle_bytes()
        return self.env["platform.release.pending"].with_user(user or self.operator).create({
            "label": "Fixes of November",
            "bundle_file": base64.b64encode(bundle), "bundle_filename": f"{SHA}.tar.gz",
            "catalogue_file": base64.b64encode(catalogue_bytes(SHA)), "catalogue_filename": f"{SHA}.catalogue.json",
            "changes_file": base64.b64encode(b"Version 1234567890ab, made on 2026-11-10\n- Fix the backup\n"),
            "changes_filename": f"{SHA}.changes.txt",
        }), bundle

    def _sign(self, pending, private, bundle):
        digest = hashlib.sha256(bundle).hexdigest()
        pending.write({
            "bundle_sig": base64.b64encode(private.sign(bundle)), "bundle_sig_filename": f"{SHA}.tar.gz.sig",
            "catalogue_sig": base64.b64encode(private.sign(catalogue_bytes(SHA))),
            "catalogue_sig_filename": f"{SHA}.catalogue.json.sig",
            "attestation_file": base64.b64encode(base64.b64encode(private.sign(trust.attestation_message(SHA, digest))) + b"\n"),
            "attestation_filename": f"{SHA}.attestation",
        })

    def test_an_operator_uploads_any_trusted_signer_signs_and_it_is_published(self):
        marie_key, marie = self._add()
        pending, bundle = self._pending()
        self.assertEqual(pending.sha, SHA)
        self.assertEqual(pending.bundle_sha256, hashlib.sha256(bundle).hexdigest())
        self.assertIn("Fix the backup", pending.changes)
        self._sign(pending, marie_key, bundle)
        pending.action_publish()
        self.assertEqual(pending.state, "published")
        self.assertEqual(pending.signer_id, marie)
        release = pending.release_id
        self.assertEqual((release.sha, release.signer_id, release.label), (SHA, marie, "Fixes of November"))
        self.assertTrue(release.catalogue_signed)
        log = self.env["platform.log"].search([("action", "=", "Version signed and published")], limit=1)
        self.assertIn("Marie Ngono", log.detail_text)

    def test_an_unknown_or_removed_signer_is_refused_and_nothing_is_kept(self):
        stranger, _pem = new_key()
        pending, bundle = self._pending()
        self._sign(pending, stranger, bundle)
        with self.assertRaisesRegex(UserError, "not signed by a trusted signer"):
            pending.action_publish()
        self.assertEqual(pending.state, "waiting")
        self.assertFalse(self.env["platform.release"].search_count([("sha", "=", SHA)]))
        marie_key, marie = self._add()
        marie.with_user(self.owner).action_remove()
        self._sign(pending, marie_key, bundle)
        with self.assertRaisesRegex(UserError, "not signed by a trusted signer"):
            pending.action_publish()

    def test_mixed_signers_or_a_wrong_attestation_are_refused(self):
        marie_key, _marie = self._add()
        pending, bundle = self._pending()
        self._sign(pending, self.alice, bundle)
        pending.write({"catalogue_sig": base64.b64encode(marie_key.sign(catalogue_bytes(SHA)))})
        with self.assertRaisesRegex(UserError, "same signer"):
            pending.action_publish()
        self._sign(pending, self.alice, bundle)
        pending.write({"attestation_file": base64.b64encode(base64.b64encode(self.alice.sign(b"something else")))})
        with self.assertRaisesRegex(UserError, "attestation"):
            pending.action_publish()

    def test_an_upload_is_checked_and_shows_the_list_it_carries(self):
        with self.assertRaises(AccessError):
            self._pending(user=self.viewer)
        with self.assertRaisesRegex(UserError, "console's own addon"):
            self._pending(bundle=bundle_bytes({"addons/ea_platform_admin/__init__.py": b""}))
        _p, marie = self._add()
        carried = self.env["platform.signer"]._document()
        pending, _bundle = self._pending(bundle=bundle_bytes({"deploy/trust/signers.json": carried}))
        self.assertIn("Marie Ngono", pending.carried_signers)
        self.assertEqual(pending.carried_serial, self.env["platform.signer"]._serial())
        self.assertFalse(pending.carried_differs)
        with self.assertRaises(UserError):
            pending.write({"bundle_file": base64.b64encode(b"x")})
        with self.assertRaises(AccessError):
            pending.with_user(self.operator).unlink()
        pending.with_user(self.owner).unlink()

    def test_the_unsigned_files_are_downloadable_by_operators_only(self):
        pending, _bundle = self._pending()
        self.assertTrue(pending.with_user(self.operator).bundle_file)
        with self.assertRaises(AccessError):
            pending.with_user(self.viewer).read(["bundle_file"])
        json.dumps(pending.with_user(self.operator).read(["sha", "state", "changes"]))
