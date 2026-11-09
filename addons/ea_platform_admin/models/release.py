import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from ..services.messages import _
from .i18n import t

_SHA = re.compile(r"^[0-9a-f]{12,40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class PlatformRelease(models.Model):
    """A signed bundle built by scripts/provision/build_release.sh, on the owner's machine.

    This record only names it. The private signing key is not on the control plane, so an attacker
    here could ask a firm to take a release but could not make one the firm would accept.
    """

    _name = "platform.release"
    _description = "Release"
    _order = "id desc"
    _rec_name = "sha"

    sha = fields.Char("Commit", required=True, copy=False)
    label = fields.Char("Label")
    bundle_sha256 = fields.Char("Bundle digest (SHA-256)", required=True, copy=False)
    odoo_commit = fields.Char("Odoo commit", readonly=False)
    notes = fields.Text("Notes")
    active = fields.Boolean("Available", default=True)
    # Who signed it: the trusted signer whose key matched, when it was registered. A signer removed later
    # stays here: what they signed while trusted stays valid.
    signer_id = fields.Many2one("platform.signer", "Signed by", readonly=True, ondelete="restrict", index=True,
                                context={"active_test": False})
    firm_count = fields.Integer("Firms on this release", compute="_compute_firm_count")

    _sha_unique = models.Constraint("unique(sha)", "This release is already registered.")

    @api.constrains("sha", "bundle_sha256")
    def _check_format(self):
        for release in self:
            if not _SHA.match(release.sha or ""):
                raise ValidationError(t(self.env, _("The commit must be 12 to 40 hexadecimal characters.")))
            if not _DIGEST.match(release.bundle_sha256 or ""):
                raise ValidationError(t(self.env, _("The bundle digest must be 64 hexadecimal characters.")))

    def _compute_firm_count(self):
        firms = self.env["platform.firm"].sudo()
        for release in self:
            release.firm_count = firms.search_count([("addon_release", "=", release.sha)])

    @api.depends("sha", "label")
    def _compute_display_name(self):
        for release in self:
            short = (release.sha or "")[:12]
            release.display_name = f"{short} - {release.label}" if release.label else short
