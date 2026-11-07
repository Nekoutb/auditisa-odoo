from odoo import api, fields, models

from ..services import pipeline


class PlatformRelease(models.Model):
    _inherit = "platform.release"

    attestation = fields.Text(
        "Offline attestation",
        help="Printed by scripts/pipeline/sign_promotion.sh, on your computer. Base64 of an ed25519 signature "
             "over this commit and this digest. It holds nothing secret.",
    )
    attestation_ok = fields.Boolean("Signed offline", compute="_compute_attestation_ok")

    @api.depends("sha", "bundle_sha256", "attestation")
    def _compute_attestation_ok(self):
        public = self.env["ir.config_parameter"].sudo().get_param("ea_platform.release_signing_public_key")
        for release in self:
            release.attestation_ok = pipeline.attestation_holds(public, release.sha, release.bundle_sha256, release.attestation)
