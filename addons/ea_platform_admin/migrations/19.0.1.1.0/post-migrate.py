"""From one release signing key to a list of trusted signers (2026-11-10).

The one key of Platform > Settings becomes the signer "Owner" (contact@cm-ea.com), list number 1.
The releases whose catalogue the console checked with that key are recorded as signed by it.
The old parameter is left in place, unread by the console, for the release tools that still read it.
"""

from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env["platform.signer"]._migrate_single_key()
