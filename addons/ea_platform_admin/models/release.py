import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from ..services.messages import _
from .i18n import t

_SHA = re.compile(r"^[0-9a-f]{12,40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class PlatformRelease(models.Model):
    """A bundle built by scripts/provision/build_release.sh and put in the private releases bucket.

    This record names it and holds its SHA-256 fingerprint. A firm's server and the practice computer
    download the bundle and install it only if its fingerprint is the one the console gives them over
    their authenticated heartbeat channel. Who may choose a release is who may sign in to the console.
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
