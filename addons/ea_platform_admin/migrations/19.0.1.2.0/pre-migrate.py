"""No more release signatures (owner's decision of 2026-11-10): the console's sign-in is the security.

Removes what the signing held, before the new code loads: the trusted signers (platform.signer, with its
one row), the versions waiting for a signature (platform.release.pending) and their uploaded files, the
"signed by" of each release, the catalogue's signature flag, the 7-day holding period of each release,
and the signer list number the firms reported. Odoo then removes the screens, menus and access rules of
those models by itself, at the end of the update, because they are no longer in the code.

The releases themselves stay, with their commit and SHA-256: that fingerprint is what a server checks now.
Each step does nothing if it was already done, so a second run is harmless.
"""

import logging

_logger = logging.getLogger(__name__)

TABLES = ("platform_release_pending", "platform_signer")
COLUMNS = {
    "platform_release": ("signer_id", "catalogue_signed", "practice_hold_days"),
    "platform_firm": ("signers_serial",),
}
PARAMS = ("ea_platform.signers_serial", "ea_platform.release_signing_public_key")
# Views that extend a screen with a field removed here. Odoo checks a screen together with the views that
# extend it, before those are reloaded: they would name a field that no longer exists and stop the update.
# They are deleted (with anything that extends them), and the update makes them again from the new code.
STALE_VIEWS = (
    ("ea_platform_admin", "view_release_form_catalogue"),
    ("ea_platform_admin", "view_release_form_practice"),
    ("ea_platform_admin", "view_practice_release_form"),
    ("ea_platform_pipeline", "view_release_form_attestation"),
    ("ea_platform_pipeline", "view_practice_release_form_confirm"),
    ("ea_platform_pipeline", "view_promotion_form_hold"),
)


def _drop_views(cr):
    ids = set()
    for module, name in STALE_VIEWS:
        cr.execute("SELECT res_id FROM ir_model_data WHERE module = %s AND name = %s AND model = 'ir.ui.view'", [module, name])
        ids.update(row[0] for row in cr.fetchall())
    if not ids:
        return 0
    # Everything that extends them goes too (ON DELETE CASCADE does the same in the database).
    cr.execute("""
        WITH RECURSIVE tree(id) AS (
            SELECT id FROM ir_ui_view WHERE id = ANY(%s)
            UNION SELECT v.id FROM ir_ui_view v JOIN tree t ON v.inherit_id = t.id
        ) SELECT id FROM tree""", [list(ids)])
    every = [row[0] for row in cr.fetchall()]
    cr.execute("DELETE FROM ir_model_data WHERE model = 'ir.ui.view' AND res_id = ANY(%s)", [every])
    cr.execute("DELETE FROM ir_ui_view WHERE id = ANY(%s)", [every])
    return len(every)


def migrate(cr, version):
    _logger.info("signing removed: %s screen extension(s) deleted, made again by the update", _drop_views(cr))
    cr.execute(
        "DELETE FROM ir_attachment WHERE res_model IN ('platform.release.pending', 'platform.signer')"
    )
    _logger.info("signing removed: %s attachment(s) of the signing screens deleted", cr.rowcount)
    for table, columns in COLUMNS.items():
        for column in columns:
            cr.execute(f'ALTER TABLE IF EXISTS "{table}" DROP COLUMN IF EXISTS "{column}" CASCADE')
    for table in TABLES:
        cr.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    cr.execute("DELETE FROM ir_config_parameter WHERE key IN %s", [PARAMS])
    _logger.info("signing removed: tables %s dropped, release and firm columns dropped", ", ".join(TABLES))
