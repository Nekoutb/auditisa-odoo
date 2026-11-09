from odoo import api, fields, models

from odoo.addons.ea_platform_admin.services import signers as trust


class PlatformRelease(models.Model):
    _inherit = "platform.release"

    attestation = fields.Text(
        "Offline attestation",
        help="The <commit>.attestation file the signing tool makes, on the signer's computer. Base64 of an "
             "ed25519 signature over this commit and this digest. It holds nothing secret.",
    )
    attestation_ok = fields.Boolean("Signed offline", compute="_compute_attestation_ok")

    @api.depends("sha", "bundle_sha256", "attestation", "signer_id")
    def _compute_attestation_ok(self):
        """Holds for the signer recorded on the release, trusted when it was registered. A signer removed
        since then keeps what they signed; nobody else's signature counts."""
        for release in self:
            signer = release.sudo().signer_id
            release.attestation_ok = bool(signer) and trust.verifies(
                signer.public_pem, trust.attestation_signature(release.attestation),
                trust.attestation_message(release.sha, release.bundle_sha256),
            )

    def _match_signer(self):
        """Records who signed, from the attestation, among the signers trusted TODAY. A signature by
        an unknown or removed key records nobody, so the release is not signed for the pipeline."""
        for release in self.sudo():
            if not release.attestation or not release.sha or not release.bundle_sha256:
                continue
            signature = trust.attestation_signature(release.attestation)
            message = trust.attestation_message(release.sha, release.bundle_sha256)
            if release.signer_id and trust.verifies(release.signer_id.public_pem, signature, message):
                continue
            release.signer_id = self.env["platform.signer"]._who_signed(signature, message)

    @api.model_create_multi
    def create(self, vals_list):
        releases = super().create(vals_list)
        releases.filtered("attestation")._match_signer()
        return releases

    def write(self, vals):
        result = super().write(vals)
        if {"attestation", "sha", "bundle_sha256"} & set(vals):
            self._match_signer()
        return result

    @api.model
    def _link_signers(self):
        """The migration: every release with an attestation gets the signer it matches."""
        self.sudo().with_context(active_test=False).search([("attestation", "!=", False)])._match_signer()
