import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_SHA = re.compile(r"^[0-9a-f]{12,40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class PlatformRelease(models.Model):
    """A signed bundle built by scripts/provision/build_release.sh, on the owner's machine.

    This record only names it. The private signing key is not on the control plane, so an attacker
    here could ask a firm to take a release but could not make one the firm would accept.
    """

    _name = "platform.release"
    _description = "Version"
    _order = "id desc"
    _rec_name = "sha"

    sha = fields.Char("Commit", required=True, copy=False)
    label = fields.Char("Libellé")
    bundle_sha256 = fields.Char("Empreinte du paquet (SHA-256)", required=True, copy=False)
    odoo_commit = fields.Char("Commit d'Odoo", readonly=False)
    notes = fields.Text("Notes")
    active = fields.Boolean("Disponible", default=True)
    firm_count = fields.Integer("Cabinets sur cette version", compute="_compute_firm_count")

    _sha_unique = models.Constraint("unique(sha)", "Cette version est déjà enregistrée.")

    @api.constrains("sha", "bundle_sha256")
    def _check_format(self):
        for release in self:
            if not _SHA.match(release.sha or ""):
                raise ValidationError("Le commit doit faire de 12 à 40 caractères hexadécimaux.")
            if not _DIGEST.match(release.bundle_sha256 or ""):
                raise ValidationError("L'empreinte du paquet doit faire 64 caractères hexadécimaux.")

    def _compute_firm_count(self):
        firms = self.env["platform.firm"].sudo()
        for release in self:
            release.firm_count = firms.search_count([("addon_release", "=", release.sha)])

    @api.depends("sha", "label")
    def _compute_display_name(self):
        for release in self:
            short = (release.sha or "")[:12]
            release.display_name = f"{short} - {release.label}" if release.label else short
