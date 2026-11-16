"""The archived file's own registers (owner's mock-ups of 2026-11-16, ISA 230 ¶14-16):

- the sealed copy made when the file is archived: one ZIP, its fingerprint, never changed;
- the addenda written after archiving: they add, they never change what was archived;
- the access log: every opening of an archived file's pages and every download of its sealed copy;
- the late-work notes: audit work recorded after the report date, each with its reason.

An addendum and an access line are written on an archived file, so their tables are left out of
the archive lock (records.ARCHIVE_EXEMPT) and carry their own trigger instead: insert only."""
from odoo import fields, models

from .records import install_archive_triggers


def _append_only(cr, table):
    cr.execute(
        """
        CREATE OR REPLACE FUNCTION ea_audit_append_only() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'append-only: % rows are never changed or deleted', TG_TABLE_NAME;
        END $$ LANGUAGE plpgsql;
        DROP TRIGGER IF EXISTS ea_audit_append_only ON {table};
        CREATE TRIGGER ea_audit_append_only BEFORE UPDATE OR DELETE ON {table}
          FOR EACH ROW EXECUTE FUNCTION ea_audit_append_only();
        """.format(table=table)
    )


class _AttachedBytes(models.AbstractModel):
    """The bytes hang on the row (res_model, res_id), written once after it: the row itself is
    never updated to point at them."""

    _name = "ea.audit.attached.bytes"
    _description = "Row with its file"

    def _compute_attachment(self):
        Attachment = self.env["ir.attachment"].sudo()
        for row in self:
            row.attachment_id = Attachment.search([("res_model", "=", self._name), ("res_id", "=", row.id)], limit=1)


class ArchiveSeal(models.Model):
    """The sealed copy: a ZIP with every paper, every live evidence file at its latest version,
    every letter and report, manifest.json / manifest.csv with one SHA-256 a file, and SHA256SUMS.
    The overall fingerprint is the SHA-256 of SHA256SUMS. Made inside the archiving transaction,
    before the lock; the database refuses any later change."""

    _name = "ea.audit.archive.seal"
    _inherit = ["ea.audit.tool.record", "ea.audit.attached.bytes"]
    _description = "Sealed copy of an archived file"
    _rec_name = "sha256"

    sha256 = fields.Char(string="Fingerprint (SHA-256)", required=True, readonly=True)
    zip_sha256 = fields.Char(string="SHA-256 of the ZIP", readonly=True)
    file_count = fields.Integer(readonly=True)
    byte_size = fields.Integer(readonly=True)
    render = fields.Selection([("pdf", "PDF"), ("html", "HTML")], string="Papers rendered as", readonly=True)
    filename = fields.Char(readonly=True)
    attachment_id = fields.Many2one("ir.attachment", compute="_compute_attachment", compute_sudo=True)
    sealed_by_id = fields.Many2one("res.users", string="Archived by", readonly=True, ondelete="restrict")
    sealed_at = fields.Datetime(string="Archived on", readonly=True, default=fields.Datetime.now)

    _engagement_uniq = models.Constraint("UNIQUE(engagement_id)", "A file is sealed once.")

    def init(self):
        _append_only(self.env.cr, "ea_audit_archive_seal")


class ArchiveAddendum(models.Model):
    """ISA 230 ¶16: a change after the file was assembled says what, when, who and why. Created
    on an archived file; never changed; the archived rows themselves stay untouched."""

    _name = "ea.audit.archive.addendum"
    _inherit = ["ea.audit.tool.record", "ea.audit.attached.bytes"]
    _description = "Addendum to an archived file"
    _order = "added_at desc, id desc"
    _rec_name = "reason"

    added_at = fields.Datetime(string="Date", required=True, readonly=True, default=fields.Datetime.now)
    user_id = fields.Many2one("res.users", string="By", required=True, readonly=True, ondelete="restrict")
    reason = fields.Text(string="Why", required=True, readonly=True)
    attachment_id = fields.Many2one("ir.attachment", string="Document", compute="_compute_attachment", compute_sudo=True)
    filename = fields.Char(readonly=True)
    sha256 = fields.Char(string="SHA-256", readonly=True)

    def init(self):
        _append_only(self.env.cr, "ea_audit_archive_addendum")


class ArchiveAccess(models.Model):
    """Who opened what of an archived file, and who took its sealed copy. Insert only."""

    _name = "ea.audit.archive.access"
    _inherit = ["ea.audit.tool.record"]
    _description = "Access to an archived file"
    _order = "accessed_at desc, id desc"
    _rec_name = "what"

    accessed_at = fields.Datetime(string="Date", required=True, readonly=True, default=fields.Datetime.now)
    user_id = fields.Many2one("res.users", string="Who", required=True, readonly=True, ondelete="restrict")
    kind = fields.Selection([("open", "Opened"), ("download", "Downloaded the sealed copy")], required=True, readonly=True)
    what = fields.Char(readonly=True)

    def init(self):
        _append_only(self.env.cr, "ea_audit_archive_access")
        # the tables above exist now: every engagement-scoped table gets its lock, these their exemption
        install_archive_triggers(self.env.cr)


class LateWork(models.Model):
    """ISA 230 A21-A24: after the report date only assembly work is done. A finding, a
    misstatement or a procedure conclusion recorded after it needs a late-work note open, with
    its reason; each such record is named in the trail."""

    _name = "ea.audit.late.work"
    _inherit = ["ea.audit.tool.record"]
    _description = "Work recorded after the report date"
    _order = "opened_at desc, id desc"
    _rec_name = "reason"

    reason = fields.Text(required=True, readonly=True)
    opened_by_id = fields.Many2one("res.users", string="Opened by", required=True, readonly=True, ondelete="restrict")
    opened_at = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)
    closed_at = fields.Datetime(readonly=True)
    closed_by_id = fields.Many2one("res.users", string="Closed by", readonly=True, ondelete="restrict")
