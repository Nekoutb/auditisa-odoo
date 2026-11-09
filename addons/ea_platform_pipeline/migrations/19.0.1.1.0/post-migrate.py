"""Records who signed each release that carries an offline attestation (2026-11-10).

ea_platform_admin's migration made the one key of before the signer "Owner". A release whose
attestation holds for a trusted signer's key is recorded as signed by that signer.
"""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["platform.release"]._link_signers()
