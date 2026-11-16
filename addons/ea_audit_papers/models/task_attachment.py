from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.signoff_rules import at_least

from .errors import paper_error

RESTORE_WINDOW_DAYS = 30


class TaskAttachment(models.Model):
    """One version of an evidence file on a task (lib/attachments.ts). The bytes are in the
    linked ir.attachment, whose access follows this record: the team-only rule, and a
    removed file reads as gone. Removal is a soft delete and is restorable for 30 days."""

    _name = "ea.audit.task.attachment"
    _description = "Task attachment"
    _order = "name, version desc"

    file_item_id = fields.Many2one("ea.audit.file.item", string="Task", required=True, index=True, ondelete="cascade")
    engagement_id = fields.Many2one(related="file_item_id.engagement_id", store=True, index=True)
    code = fields.Char(related="file_item_id.code", store=True)
    name = fields.Char(required=True)
    mime = fields.Char()
    size_bytes = fields.Integer()
    version = fields.Integer(required=True, default=1)
    attachment_id = fields.Many2one("ir.attachment", required=True, ondelete="restrict")
    checksum = fields.Char(related="attachment_id.checksum")
    uploaded_by_id = fields.Many2one("res.users", required=True, ondelete="restrict")
    uploaded_at = fields.Datetime(required=True, default=fields.Datetime.now)
    deleted_at = fields.Datetime(index=True)
    deleted_by_id = fields.Many2one("res.users", ondelete="restrict")
    # Roll forward (owner's ruling of 2026-11-16): last year's evidence copied to the new file, the
    # same bytes, marked until someone of the team has reviewed it.
    carried_from_year = fields.Integer(string="Carried forward from", readonly=True, copy=False)
    carried_reviewed_by_id = fields.Many2one("res.users", string="Prior-year document reviewed by", ondelete="restrict", readonly=True, copy=False)
    carried_reviewed_at = fields.Datetime(string="Prior-year document reviewed on", readonly=True, copy=False)

    _item_name_version_uniq = models.Constraint(
        "UNIQUE(file_item_id, name, version)", "This version of the file already exists.",
    )

    def _ea_guard(self, minimum):
        """Who may touch evidence, on a live record reached through its engagement."""
        self.ensure_one()
        row = self.sudo()
        if not row.exists():
            raise paper_error(self.env, "not-found")
        row.file_item_id.with_env(self.env)._ea_guard_evidence(minimum)
        return row

    def _ea_live_chain(self):
        return self.sudo().search([
            ("file_item_id", "=", self.file_item_id.id), ("name", "=", self.name), ("deleted_at", "=", False),
        ])

    def rename(self, new_name):
        row = self._ea_guard("staff")
        if row.deleted_at:
            raise paper_error(self.env, "not-found")
        cleaned = "".join(ch for ch in (new_name or "").strip() if ch not in '/:*?"<>|')[:120]
        if not cleaned:
            raise paper_error(self.env, "name-required")
        extension = row.name[row.name.rfind("."):] if "." in row.name else ""
        if extension and not cleaned.lower().endswith(extension.lower()):
            cleaned += extension
        if cleaned == row.name:
            return cleaned
        taken = row.search_count([
            ("file_item_id", "=", row.file_item_id.id), ("name", "=", cleaned), ("deleted_at", "=", False),
        ])
        if taken:
            raise paper_error(self.env, "name-taken")
        old = row.name
        chain = row._ea_live_chain()
        chain.write({"name": cleaned})
        chain.attachment_id.write({"name": cleaned})
        row.file_item_id._ea_after_evidence_change(self.env, "renamed", "%s renamed to %s" % (old, cleaned))
        return cleaned

    def remove(self):
        row = self._ea_guard("manager")
        if row.deleted_at:
            raise paper_error(self.env, "not-found")
        chain = row._ea_live_chain()
        name = row.name
        chain.write({"deleted_at": fields.Datetime.now(), "deleted_by_id": self.env.user.id})
        row.file_item_id._ea_after_evidence_change(
            self.env, "deleted", "Deleted: %s (restorable for %s days)" % (name, RESTORE_WINDOW_DAYS),
        )
        return True

    def restore(self):
        row = self._ea_guard("manager")
        if not row.deleted_at:
            raise paper_error(self.env, "not-found")
        floor = fields.Datetime.now() - timedelta(days=RESTORE_WINDOW_DAYS)
        if row.deleted_at < floor:
            raise paper_error(self.env, "restore-window-expired")
        chain = row.search([
            ("file_item_id", "=", row.file_item_id.id), ("name", "=", row.name), ("deleted_at", ">=", floor),
        ])
        chain.write({"deleted_at": False, "deleted_by_id": False})
        row.file_item_id._ea_after_evidence_change(self.env, "restored", "Restored: %s" % row.name)
        return True

    def _ea_carry_info(self):
        """What a list of documents shows of a carried file: the mark, and who reviewed it."""
        self.ensure_one()
        row = self.sudo()
        if not row.carried_from_year:
            return {"carried": False, "carriedReviewed": False}
        reviewed = False
        if row.carried_reviewed_at:
            reviewed = self.env._(
                "Reviewed by %(name)s on %(date)s", name=row.carried_reviewed_by_id.name or "",
                date=fields.Date.context_today(self, row.carried_reviewed_at).strftime("%d/%m/%Y"),
            )
        return {
            "carried": self.env._(
                "Prior year (%(year)s), carried forward — review before relying on it", year=row.carried_from_year,
            ),
            "carriedReviewed": reviewed,
        }

    def mark_carried_reviewed(self):
        """A member of the team has read last year's file again: it may be relied on this year."""
        row = self._ea_guard("staff")
        if row.deleted_at or not row.carried_from_year:
            raise paper_error(self.env, "not-found")
        if not row.carried_reviewed_at:
            row.write({"carried_reviewed_by_id": self.env.user.id, "carried_reviewed_at": fields.Datetime.now()})
            row.engagement_id._ea_log(
                "attachment_reviewed", "%s: Prior-year document reviewed: %s" % (row.code, row.name),
            )
        return row._ea_carry_info()

    @api.model
    def _ea_payload(self, item):
        rows = self.sudo().search([("file_item_id", "=", item.id)])
        latest = {}
        for row in rows.filtered(lambda r: not r.deleted_at):
            entry = latest.setdefault(row.name, {
                "id": row.id, "name": row.name, "version": row.version, "size": row.size_bytes,
                "attachment_id": row.attachment_id.id, "by": row.uploaded_by_id.name,
                "date": row.uploaded_at.strftime("%d/%m/%Y"), "history": [],
                **row._ea_carry_info(),
            })
            if entry["id"] != row.id:
                entry["history"].append({"id": row.id, "version": row.version, "attachment_id": row.attachment_id.id})
        floor = fields.Datetime.now() - timedelta(days=RESTORE_WINDOW_DAYS)
        removed = {}
        for row in rows.filtered(lambda r: r.deleted_at and r.deleted_at >= floor):
            removed.setdefault(row.name, {"id": row.id, "name": row.name, "by": row.deleted_by_id.name or ""})
        role = self.env.user._ea_firm_role()
        return {
            "live": list(latest.values()),
            "removed": list(removed.values()),
            "can_upload": at_least(role, "staff"),
            "can_remove": at_least(role, "manager"),
        }
