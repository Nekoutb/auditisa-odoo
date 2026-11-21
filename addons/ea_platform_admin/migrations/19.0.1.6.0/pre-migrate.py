"""The console's global reply setting was removed on 2026-11-18 (each firm has its own Replies option since).

A console updated from a version before that still holds the screen extension that showed the setting
(view_settings_form_platform_mail). Odoo checks the settings screen together with its extensions before
they are reloaded, finds a field that no longer exists and stops the update (seen on the console on
2026-11-21, the update was undone). The extension is deleted here, with anything that extends it; the
update makes it again from the new code. Nothing else is touched; a second run does nothing.
"""

import logging

_logger = logging.getLogger(__name__)

STALE_VIEWS = (("ea_platform_admin", "view_settings_form_platform_mail"),)


def migrate(cr, version):
    ids = set()
    for module, name in STALE_VIEWS:
        cr.execute("SELECT res_id FROM ir_model_data WHERE module = %s AND name = %s AND model = 'ir.ui.view'", [module, name])
        ids.update(row[0] for row in cr.fetchall())
    if not ids:
        return
    cr.execute("""
        WITH RECURSIVE tree(id) AS (
            SELECT id FROM ir_ui_view WHERE id = ANY(%s)
            UNION SELECT v.id FROM ir_ui_view v JOIN tree t ON v.inherit_id = t.id
        ) SELECT id FROM tree""", [list(ids)])
    every = [row[0] for row in cr.fetchall()]
    cr.execute("DELETE FROM ir_model_data WHERE model = 'ir.ui.view' AND res_id = ANY(%s)", [every])
    cr.execute("DELETE FROM ir_ui_view WHERE id = ANY(%s)", [every])
    _logger.info("reply setting removed: %s screen extension(s) deleted, made again by the update", len(every))
