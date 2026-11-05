import hashlib

from odoo import fields, models

from ..rules import rule_error

# Tables that keep moving after a file closes: points forward are written for next year's file,
# a hold is placed on an archived file, the bell is not evidence.
ARCHIVE_EXEMPT = (
    "ea_audit_completion_record", "ea_audit_legal_hold", "ea_audit_archive_manifest",
    "ea_audit_notice", "ea_audit_notification",
    # the state of a screen, one row a person: reading an archived ledger still needs it
    "ea_audit_gl_console",
)
_FILE_ITEM_WORK = "state, conditional, not_applicable, na_reason, preparer_id, approver_id, assignee_id, due_date"


def install_archive_trigger(cr, table):
    """ISA 230 ¶15-16, the database's refusal behind the Python guards (I-4): no row of an
    archived file changes, whichever path reached it."""
    cr.execute("DROP TRIGGER IF EXISTS ea_audit_archive_lock ON %s" % table)
    # A task's section and order follow its template: a data update may move them on a closed file.
    update = "UPDATE OF %s" % _FILE_ITEM_WORK if table == "ea_audit_file_item" else "UPDATE"
    cr.execute(
        "CREATE TRIGGER ea_audit_archive_lock BEFORE INSERT OR %s OR DELETE ON %s "
        "FOR EACH ROW EXECUTE FUNCTION ea_audit_assert_open()" % (update, table)
    )


def install_archive_triggers(cr):
    """Every engagement-scoped table present now. Called on install and on update. A wizard's table
    is no evidence: a legal hold placed on an archived file goes through one."""
    cr.execute(
        """SELECT c.table_name FROM information_schema.columns c
             JOIN information_schema.tables t ON t.table_name = c.table_name AND t.table_schema = c.table_schema
            WHERE c.column_name = 'engagement_id' AND c.table_name LIKE 'ea_audit_%%'
              AND t.table_type = 'BASE TABLE' AND c.table_schema = current_schema()"""
    )
    tables = [row[0] for row in cr.fetchall()]
    cr.execute("SELECT replace(model, '.', '_') FROM ir_model WHERE transient")
    transient = {row[0] for row in cr.fetchall()}
    for table in tables:
        if table in ARCHIVE_EXEMPT or table in transient or table.endswith("_wizard"):
            cr.execute("DROP TRIGGER IF EXISTS ea_audit_archive_lock ON %s" % table)
        else:
            install_archive_trigger(cr, table)


class Notice(models.Model):
    """A notification of the source that has no place in the bell's fixed kinds: statutory
    deadline overdue, equity breach, PBC events, file archived. Written by the engine; read by its
    addressee. Nothing here sends an email."""

    _name = "ea.audit.notice"
    _description = "Audit notice"
    _order = "id desc"

    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")
    engagement_id = fields.Many2one("ea.audit.engagement", index=True, ondelete="cascade")
    kind = fields.Char(required=True, index=True)
    title = fields.Char(required=True)
    body = fields.Text()


class CompletionRecord(models.Model):
    """completion_record: one row per key of a file. Four keys are completion gates. Written only
    through Engagement.record_completion."""

    _name = "ea.audit.completion.record"
    _inherit = ["ea.audit.tool.record"]
    _description = "Completion record"
    _rec_name = "key"
    _order = "engagement_id, key"

    key = fields.Char(required=True, index=True)
    data = fields.Json()
    done = fields.Boolean(default=True)
    done_by_id = fields.Many2one("res.users", string="Done by", ondelete="restrict")
    done_at = fields.Datetime(default=fields.Datetime.now)
    version = fields.Integer(default=1, help="Moves with each save: the form's optimistic lock (UAT B104).")

    _engagement_key_uniq = models.Constraint("UNIQUE(engagement_id, key)", "A file has one record per key.")


class LegalHold(models.Model):
    """lib/retention.ts. A hold is history as soon as it is placed: released rows stay, and the
    database refuses any other change (migration trg_legal_hold_append_only)."""

    _name = "ea.audit.legal.hold"
    _inherit = ["ea.audit.tool.record"]
    _description = "Legal hold"
    _order = "placed_at desc, id desc"
    _rec_name = "reason"

    reason = fields.Text(required=True, readonly=True)
    placed_by_id = fields.Many2one("res.users", string="Placed by", required=True, ondelete="restrict", readonly=True)
    placed_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)
    released_at = fields.Datetime(readonly=True)
    released_by_id = fields.Many2one("res.users", string="Released by", ondelete="restrict", readonly=True)
    release_reason = fields.Text(readonly=True)

    def init(self):
        self.env.cr.execute(
            """
            CREATE OR REPLACE FUNCTION ea_audit_hold_append_only() RETURNS trigger AS $$
            BEGIN
              IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'legal-hold: a hold is history and is never deleted';
              END IF;
              IF OLD.released_at IS NOT NULL OR NEW.reason IS DISTINCT FROM OLD.reason
                 OR NEW.placed_by_id IS DISTINCT FROM OLD.placed_by_id OR NEW.placed_at IS DISTINCT FROM OLD.placed_at THEN
                RAISE EXCEPTION 'legal-hold: only the release of an active hold may be recorded';
              END IF;
              RETURN NEW;
            END $$ LANGUAGE plpgsql;
            DROP TRIGGER IF EXISTS ea_audit_hold_append_only ON ea_audit_legal_hold;
            CREATE TRIGGER ea_audit_hold_append_only BEFORE UPDATE OR DELETE ON ea_audit_legal_hold
              FOR EACH ROW EXECUTE FUNCTION ea_audit_hold_append_only();

            CREATE OR REPLACE FUNCTION ea_audit_refuse_held_delete() RETURNS trigger AS $$
            BEGIN
              IF EXISTS (SELECT 1 FROM ea_audit_legal_hold h WHERE h.engagement_id = OLD.id AND h.released_at IS NULL) THEN
                RAISE EXCEPTION 'legal-hold: this file is under a legal hold';
              END IF;
              RETURN OLD;
            END $$ LANGUAGE plpgsql;
            DROP TRIGGER IF EXISTS ea_audit_refuse_held_delete ON ea_audit_engagement;
            CREATE TRIGGER ea_audit_refuse_held_delete BEFORE DELETE ON ea_audit_engagement
              FOR EACH ROW EXECUTE FUNCTION ea_audit_refuse_held_delete();
            """
        )


class ArchiveManifest(models.Model):
    """What the file contained at the moment it closed (manifest v2): the JSON, its SHA-256, and an
    attachment of the same bytes to download. The database refuses every change to the row."""

    _name = "ea.audit.archive.manifest"
    _inherit = ["ea.audit.tool.record"]
    _description = "Archive manifest"
    _rec_name = "sha256"

    content = fields.Text(required=True, readonly=True)
    sha256 = fields.Char(string="SHA-256", required=True, readonly=True)
    attachment_id = fields.Many2one("ir.attachment", compute="_compute_attachment", compute_sudo=True)
    archived_by_id = fields.Many2one("res.users", string="Archived by", ondelete="restrict", readonly=True)

    _engagement_uniq = models.Constraint("UNIQUE(engagement_id)", "A file is archived once.")

    def init(self):
        cr = self.env.cr
        cr.execute(
            """
            CREATE OR REPLACE FUNCTION ea_audit_manifest_immutable() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'archived: the archive manifest cannot change';
            END $$ LANGUAGE plpgsql;
            DROP TRIGGER IF EXISTS ea_audit_manifest_immutable ON ea_audit_archive_manifest;
            CREATE TRIGGER ea_audit_manifest_immutable BEFORE UPDATE OR DELETE ON ea_audit_archive_manifest
              FOR EACH ROW EXECUTE FUNCTION ea_audit_manifest_immutable();

            CREATE OR REPLACE FUNCTION ea_audit_assert_open() RETURNS trigger AS $$
            DECLARE
              target integer;
            BEGIN
              IF TG_OP = 'DELETE' THEN target := OLD.engagement_id; ELSE target := NEW.engagement_id; END IF;
              IF EXISTS (SELECT 1 FROM ea_audit_engagement e WHERE e.id = target AND e.archived_at IS NOT NULL) THEN
                RAISE EXCEPTION 'archived: this file is archived and immutable (%)', TG_TABLE_NAME;
              END IF;
              IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
              RETURN NEW;
            END $$ LANGUAGE plpgsql;

            CREATE OR REPLACE FUNCTION ea_audit_engagement_frozen() RETURNS trigger AS $$
            BEGIN
              IF OLD.archived_at IS NOT NULL AND (
                   NEW.archived_at IS DISTINCT FROM OLD.archived_at OR NEW.phase IS DISTINCT FROM OLD.phase
                OR NEW.report_date IS DISTINCT FROM OLD.report_date OR NEW.opinion IS DISTINCT FROM OLD.opinion
                OR NEW.retention_until IS DISTINCT FROM OLD.retention_until OR NEW.client_id IS DISTINCT FROM OLD.client_id
                OR NEW.fiscal_year IS DISTINCT FROM OLD.fiscal_year OR NEW.period_end IS DISTINCT FROM OLD.period_end) THEN
                RAISE EXCEPTION 'archived: this file is archived and immutable';
              END IF;
              RETURN NEW;
            END $$ LANGUAGE plpgsql;
            DROP TRIGGER IF EXISTS ea_audit_engagement_frozen ON ea_audit_engagement;
            CREATE TRIGGER ea_audit_engagement_frozen BEFORE UPDATE ON ea_audit_engagement
              FOR EACH ROW EXECUTE FUNCTION ea_audit_engagement_frozen();
            """
        )
        install_archive_triggers(cr)

    def _compute_attachment(self):
        for manifest in self:
            manifest.attachment_id = self.env["ir.attachment"].sudo().search(
                [("res_model", "=", self._name), ("res_id", "=", manifest.id)], limit=1,
            )

    def action_download(self):
        self.ensure_one()
        self.sudo().engagement_id.with_env(self.env)._ea_require_access()
        return {"type": "ir.actions.act_url", "target": "self", "url": "/web/content/%d?download=true" % self.sudo().attachment_id.id}

    def _ea_verify(self):
        """The bytes still hash to what was recorded."""
        self.ensure_one()
        return hashlib.sha256(self.sudo().content.encode("utf-8")).hexdigest() == self.sudo().sha256


class IrAttachment(models.Model):
    """The bytes of an immutable record are as immutable as the record."""

    _inherit = "ir.attachment"

    def _ea_assert_not_sealed(self):
        for attachment in self.sudo():
            if attachment.res_model == "ea.audit.archive.manifest":
                raise rule_error(self.env, "archived")
            if attachment.res_model == "ea.audit.document.version" and attachment.res_id:
                version = self.env["ea.audit.document.version"].sudo().browse(attachment.res_id).exists()
                if version and version.engagement_id.archived_at:
                    raise rule_error(self.env, "archived")

    def write(self, vals):
        if set(vals) - {"index_content", "store_fname", "db_datas", "file_size", "checksum", "access_token"}:
            self._ea_assert_not_sealed()
        return super().write(vals)

    def unlink(self):
        self._ea_assert_not_sealed()
        return super().unlink()


class ResCompany(models.Model):
    """The firm's letterhead (lib/branding.ts), its retention period, the jurist's validation."""

    _inherit = "res.company"

    ea_retention_years = fields.Integer(string="Retention period (years)", default=10)
    ea_display_name = fields.Char(string="Name on letterhead")
    ea_letterhead1 = fields.Char(string="Letterhead line 1")
    ea_letterhead2 = fields.Char(string="Letterhead line 2")
    ea_letterhead_footer = fields.Char(string="Letterhead footer")
    ea_articles_validated = fields.Boolean(
        string="Article numbers validated by the jurist",
        help="While off, every article number printed or shown carries (à valider).",
    )


class Client(models.Model):
    """The fields of the client record the statutory documents read."""

    _inherit = "ea.audit.client"

    address = fields.Char()
    share_capital = fields.Float(string="Share capital (FCFA)", digits=(18, 0))
    mandate_type = fields.Selection([("statutes", "Statutes (2 fiscal years)"), ("ago", "General meeting (6 fiscal years)")])
    mandate_start_year = fields.Integer()
