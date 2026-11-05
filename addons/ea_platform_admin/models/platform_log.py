from odoo import api, fields, models
from odoo.exceptions import AccessError

from ..services.loghash import GENESIS, entry_hash, first_break

_LOCK_KEY = 7262001


class PlatformLog(models.Model):
    """Who did what on the platform. Append-only: refused by the model and by the database."""

    _name = "platform.log"
    _description = "Journal de la plateforme"
    _order = "id desc"
    _rec_name = "action"

    logged_at = fields.Datetime("Date", required=True, readonly=True, default=fields.Datetime.now)
    user_id = fields.Many2one("res.users", "Qui", readonly=True, ondelete="restrict")
    firm_id = fields.Many2one("platform.firm", "Cabinet", readonly=True, ondelete="restrict", index=True)
    action = fields.Char("Action", required=True, readonly=True)
    detail = fields.Text("Détail", readonly=True)
    previous_hash = fields.Char("Empreinte précédente", readonly=True, required=True)
    entry_hash = fields.Char("Empreinte", readonly=True, required=True)

    def init(self):
        self.env.cr.execute("""
            CREATE OR REPLACE FUNCTION platform_log_refuse_change() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'platform_log is append-only';
            END;
            $$ LANGUAGE plpgsql;
            DROP TRIGGER IF EXISTS platform_log_append_only ON platform_log;
            CREATE TRIGGER platform_log_append_only
                BEFORE UPDATE OR DELETE ON platform_log
                FOR EACH ROW EXECUTE FUNCTION platform_log_refuse_change();
            DROP TRIGGER IF EXISTS platform_log_no_truncate ON platform_log;
            CREATE TRIGGER platform_log_no_truncate
                BEFORE TRUNCATE ON platform_log
                FOR EACH STATEMENT EXECUTE FUNCTION platform_log_refuse_change();
        """)

    @api.model
    def _hash_fields(self, values):
        return {
            "logged_at": str(values["logged_at"]),
            "user_id": values["user_id"] or 0,
            "firm_id": values["firm_id"] or 0,
            "action": values["action"],
            "detail": values["detail"] or "",
        }

    @api.model
    def _record(self, action, firm=None, detail="", user=None):
        """The one way in. The advisory lock keeps the chain in order under concurrent requests.

        Callers pass fixed text and identifiers: never a token, a key or anything from a request.
        """
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s)", [_LOCK_KEY])
        self.env.cr.execute("SELECT entry_hash FROM platform_log ORDER BY id DESC LIMIT 1")
        row = self.env.cr.fetchone()
        previous = row[0] if row else GENESIS
        values = {
            "logged_at": fields.Datetime.now(),
            "user_id": (user or self.env.user).id,
            "firm_id": firm.id if firm else False,
            "action": action,
            "detail": detail or "",
        }
        values["previous_hash"] = previous
        values["entry_hash"] = entry_hash(previous, self._hash_fields(values))
        return self.sudo().create(values)

    @api.model
    def _chain_break(self):
        """The first row whose hash does not hold, or an empty recordset. Read-only."""
        rows = self.sudo().search([], order="id asc")
        entries = [
            (row.previous_hash, self._hash_fields({
                "logged_at": row.logged_at,
                "user_id": row.user_id.id,
                "firm_id": row.firm_id.id,
                "action": row.action,
                "detail": row.detail,
            }), row.entry_hash)
            for row in rows
        ]
        index = first_break(entries)
        return rows[index] if index is not None else self.browse()

    def write(self, vals):
        raise AccessError("Le journal de la plateforme ne se modifie pas.")

    def unlink(self):
        raise AccessError("Le journal de la plateforme ne se supprime pas.")
