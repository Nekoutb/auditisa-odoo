import base64
import hashlib
import io
import re
import tarfile

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError

from ..services import addons as catalogue
from ..services import signers as trust
from ..services.messages import _
from ..services.provider import ProviderError
from .i18n import t

_SHA = re.compile(r"^[0-9a-f]{40}$")
TRUST_FILE = "deploy/trust/signers.json"
CHANGES_MAX = 20000


def _raw(value):
    return base64.b64decode(value) if value else b""


def bundle_facts(raw):
    """(holds the control plane's addon, the signer list it carries or None). Reads names only."""
    platform, carried = False, None
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
            for member in archive:
                if member.name.startswith("addons/ea_platform_"):
                    platform = True
                if member.name == TRUST_FILE and member.isfile() and member.size < 200000:
                    handle = archive.extractfile(member)
                    carried = handle.read() if handle else None
    except (tarfile.TarError, OSError, EOFError):
        return None, None
    return platform, carried


class PlatformReleasePending(models.Model):
    """A new version built but not signed yet: Platform > Updates > Waiting for signature.

    Any trusted signer can sign it from their own computer, without the owner's: they download the
    files here, sign them with the "Sign new version" desktop tool, and upload the three files it makes.
    The console then checks those against the signers trusted today, puts the release in the releases
    bucket and registers it. Nothing here can sign: the console holds public keys only.
    """

    _name = "platform.release.pending"
    _description = "Version waiting for signature"
    _order = "id desc"
    _rec_name = "sha"

    sha = fields.Char("Commit", required=True, readonly=True)
    label = fields.Char("Label")
    state = fields.Selection([("waiting", "Waiting for signature"), ("published", "Signed and published")],
                             "State", default="waiting", required=True, readonly=True)
    bundle_file = fields.Binary("Bundle (<commit>.tar.gz)", attachment=True, required=True)
    bundle_filename = fields.Char("Bundle file name")
    bundle_sha256 = fields.Char("Fingerprint of the bundle (SHA-256)", readonly=True)
    catalogue_file = fields.Binary("Catalogue (<commit>.catalogue.json)", attachment=True, required=True)
    catalogue_filename = fields.Char("Catalogue file name")
    changes_file = fields.Binary("List of changes (<commit>.changes.txt)", attachment=True)
    changes_filename = fields.Char("Changes file name")
    changes = fields.Text("Changes in this version", readonly=True)
    carried_signers = fields.Text("Signers this version gives to the firms", readonly=True)
    carried_serial = fields.Integer("Number of the signer list it carries", readonly=True)
    carried_differs = fields.Boolean("Differs from the console's list", compute="_compute_carried_differs")
    # The three files the desktop tool makes. Not secret.
    bundle_sig = fields.Binary("<commit>.tar.gz.sig", attachment=True)
    bundle_sig_filename = fields.Char("Bundle signature file name")
    catalogue_sig = fields.Binary("<commit>.catalogue.json.sig", attachment=True)
    catalogue_sig_filename = fields.Char("Catalogue signature file name")
    attestation_file = fields.Binary("<commit>.attestation", attachment=True)
    attestation_filename = fields.Char("Attestation file name")
    release_id = fields.Many2one("platform.release", "Registered release", readonly=True)
    signer_id = fields.Many2one("platform.signer", "Signed by", readonly=True, context={"active_test": False})
    published_at = fields.Datetime("Published on", readonly=True)
    published_by_id = fields.Many2one("res.users", "Published by", readonly=True)

    _sha_unique = models.Constraint("unique(sha)", "This version is already waiting or published.")

    @api.depends("carried_serial")
    def _compute_carried_differs(self):
        serial = self.env["platform.signer"]._serial()
        for pending in self:
            pending.carried_differs = bool(pending.carried_serial) and pending.carried_serial != serial

    @api.depends("sha", "label")
    def _compute_display_name(self):
        for pending in self:
            short = (pending.sha or "")[:12]
            pending.display_name = f"{short} - {pending.label}" if pending.label else short

    def _check_operator(self):
        if not self.env.user.has_group("ea_platform_admin.group_platform_operator"):
            raise AccessError(t(self.env, _("Only the owner and operators handle versions waiting for signature.")))

    @api.model
    def _facts(self, vals):
        """Checks the uploaded unsigned files and fills what the screens show from them."""
        name = vals.get("bundle_filename") or ""
        found = re.match(r"^([0-9a-f]{40})\.tar\.gz$", name)
        if not found:
            raise UserError(t(self.env, _("The bundle is the file named <40-character commit>.tar.gz.")))
        sha = found.group(1)
        if vals.get("catalogue_filename") and vals["catalogue_filename"] != f"{sha}.catalogue.json":
            raise UserError(t(self.env, _("The catalogue must be %(name)s.", name=f"{sha}.catalogue.json")))
        bundle = _raw(vals.get("bundle_file"))
        platform, carried = bundle_facts(bundle)
        if platform is None:
            raise UserError(t(self.env, _("This file is not a release bundle (.tar.gz).")))
        if platform:
            raise UserError(t(self.env, _("This bundle holds the console's own addon: it is refused.")))
        try:
            catalogue.parse_catalogue(_raw(vals.get("catalogue_file")), sha)
        except catalogue.CatalogueRefused as refused:
            raise UserError(t(self.env, refused.message)) from None
        if self.env["platform.release"].sudo().with_context(active_test=False).search_count([("sha", "=", sha)]):
            raise UserError(t(self.env, _("This version is already registered in Releases.")))
        facts = {"sha": sha, "bundle_sha256": hashlib.sha256(bundle).hexdigest()}
        changes = _raw(vals.get("changes_file"))
        if changes:
            facts["changes"] = changes[:CHANGES_MAX].decode("utf-8", "replace")
        if carried:
            try:
                parsed = trust.parse(carried)
            except trust.SignerRefused as refused:
                raise UserError(t(self.env, _("The signer list inside this bundle is refused:")) + " "
                                + t(self.env, refused.message)) from None
            facts["carried_serial"] = parsed["serial"]
            facts["carried_signers"] = "\n".join(
                f"{row['name']} ({row['email']}) {trust.short(row['fingerprint'])}" for row in parsed["signers"])
        return facts

    @api.model_create_multi
    def create(self, vals_list):
        self._check_operator()
        for vals in vals_list:
            vals.update(self._facts(vals))
            for name in ("state", "release_id", "signer_id", "published_at", "published_by_id",
                         "bundle_sig", "catalogue_sig", "attestation_file"):
                vals.pop(name, None)
        records = super().create(vals_list)
        for pending in records:
            self.env["platform.log"]._record(
                _("Version waiting for signature"),
                detail=_("%(sha)s, fingerprint %(digest)s", sha=pending.sha[:12], digest=pending.bundle_sha256),
            )
        return records

    def write(self, vals):
        self._check_operator()
        if {"bundle_file", "catalogue_file", "changes_file", "sha", "bundle_filename", "catalogue_filename"} & set(vals):
            raise UserError(t(self.env, _("The files of a waiting version do not change: discard it and upload again.")))
        if any(p.state != "waiting" for p in self) and not self.env.context.get("ea_pending_publish"):
            raise UserError(t(self.env, _("This version is already published.")))
        return super().write(vals)

    def unlink(self):
        if any(p.state != "waiting" for p in self):
            raise UserError(t(self.env, _("A published version stays: it records who signed it.")))
        if not self.env.user.has_group("ea_platform_admin.group_platform_owner"):
            raise AccessError(t(self.env, _("Only the owner discards a waiting version.")))
        for pending in self:
            self.env["platform.log"]._record(_("Waiting version discarded"), detail=pending.sha[:12])
        return super().unlink()

    def _refuse(self, why):
        raise UserError(t(self.env, _("Refused: nothing was published.")) + "\n" + t(self.env, why))

    def action_publish(self):
        """Checks the three signed files against the signers trusted today, then publishes the release."""
        self.ensure_one()
        self._check_operator()
        if self.state != "waiting":
            raise UserError(t(self.env, _("This version is already published.")))
        sha = self.sha
        expected = {"bundle_sig_filename": f"{sha}.tar.gz.sig", "catalogue_sig_filename": f"{sha}.catalogue.json.sig",
                    "attestation_filename": f"{sha}.attestation"}
        if not (self.bundle_sig and self.catalogue_sig and self.attestation_file):
            self._refuse(_("Upload the three files the signing tool made: %(names)s.", names=", ".join(expected.values())))
        for field, name in expected.items():
            if self[field] and self[field] != name:
                self._refuse(_("This file is for another version: %(name)s. Expected: %(expected)s.",
                               name=self[field], expected=name))
        bundle, catalogue_raw = _raw(self.bundle_file), _raw(self.catalogue_file)
        digest = hashlib.sha256(bundle).hexdigest()
        if digest != self.bundle_sha256:
            self._refuse(_("The bundle changed since it was uploaded."))
        bundle_sig, catalogue_sig = _raw(self.bundle_sig), _raw(self.catalogue_sig)
        attestation_text = _raw(self.attestation_file).decode("ascii", "replace").strip()
        trusted = self.env["platform.signer"]._trusted()
        who = trust.which(trusted, bundle_sig, bundle)
        if not who:
            self._refuse(_("The bundle was not signed by a trusted signer. If a new person signed, the owner must "
                           "first add them in Platform > Updates > Signers."))
        if not trust.verifies(who["pem"], catalogue_sig, catalogue_raw):
            self._refuse(_("The catalogue's signature does not match the same signer."))
        if not trust.verifies(who["pem"], trust.attestation_signature(attestation_text), trust.attestation_message(sha, digest)):
            self._refuse(_("The attestation does not match this version or this signer."))
        signer = self.env["platform.signer"].sudo().browse(who["id"])
        sent = self._send_to_bucket({
            f"{sha}.tar.gz": bundle, f"{sha}.tar.gz.sig": bundle_sig,
            f"{sha}.catalogue.json": catalogue_raw, f"{sha}.catalogue.json.sig": catalogue_sig,
        })
        releases = self.env["platform.release"].sudo().with_context(active_test=False)
        release = releases.search([("sha", "=", sha)], limit=1)
        if release and release.bundle_sha256 != digest:
            self._refuse(_("This commit is already registered with another fingerprint: a release does not change."))
        if not release:
            release = releases.create({"sha": sha, "bundle_sha256": digest, "label": self.label or False,
                                       "notes": self.changes or False, "signer_id": signer.id})
        elif not release.signer_id:
            release.signer_id = signer
        if "attestation" in release._fields:
            release.attestation = attestation_text
        release._load_catalogue(catalogue_raw, catalogue_sig)
        self.with_context(ea_pending_publish=True).write({
            "state": "published", "release_id": release.id, "signer_id": signer.id,
            "published_at": fields.Datetime.now(), "published_by_id": self.env.user.id,
        })
        self.env["platform.log"]._record(
            _("Version signed and published"),
            detail=_("%(sha)s signed by %(name)s (fingerprint %(fingerprint)s). %(where)s",
                     sha=sha[:12], name=signer.name, fingerprint=signer.fingerprint_short,
                     where=_("Files put in the releases bucket.") if sent else _("Simulation: no file was sent.")),
        )
        return {
            "type": "ir.actions.act_window", "res_model": "platform.release", "res_id": release.id,
            "view_mode": "form", "target": "current",
        }

    def _send_to_bucket(self, files):
        """True when sent. In simulation nothing leaves the console."""
        services = self.env["platform.services"]
        if services._is_simulation():
            return False
        try:
            storage = services._storage()
            for name, body in files.items():
                storage.put_release_file(name, body)
        except ProviderError as error:
            raise UserError(t(self.env, _("The releases bucket refused the files: nothing was registered."))
                            + "\n" + t(self.env, error.message)) from None
        return True
