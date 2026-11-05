from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.signoff_rules import at_least

from .errors import paper_error


class ReviewNote(models.Model):
    """A review note on a task. The platform keeps two stores, notes on the document and
    notes on the task, read as one (UAT B18); here a paper is one per task, so one store.
    Notes are cleared, never deleted."""

    _name = "ea.audit.review.note"
    _description = "Review note"
    _order = "state desc, create_date desc, id desc"
    _rec_name = "body"

    file_item_id = fields.Many2one("ea.audit.file.item", string="Task", required=True, index=True, ondelete="cascade")
    engagement_id = fields.Many2one(related="file_item_id.engagement_id", store=True, index=True)
    code = fields.Char(related="file_item_id.code", store=True, index=True)
    author_id = fields.Many2one("res.users", required=True, ondelete="restrict")
    assignee_id = fields.Many2one("res.users", string="Addressed to", index=True, ondelete="restrict")
    body = fields.Text(required=True)
    response = fields.Text()
    state = fields.Selection([("open", "Open"), ("cleared", "Cleared")], required=True, default="open", index=True)
    cleared_at = fields.Datetime()
    cleared_by_id = fields.Many2one("res.users", string="Cleared by", ondelete="restrict")

    def _ea_stamp(self, text):
        user = self.env.user
        stamp = fields.Datetime.context_timestamp(self.with_context(tz="Africa/Douala"), fields.Datetime.now())
        return "[%s · %s WAT] %s" % (user.name, stamp.strftime("%d/%m/%Y %H:%M"), text)

    def _ea_guard(self):
        """Through its own engagement, by a member, on a file that is not closed."""
        self.ensure_one()
        note = self.sudo()
        if not note.exists():
            raise paper_error(self.env, "not-found")
        self.env["ea.audit.engagement"]._ea_require_write()
        engagement = note.engagement_id.with_env(self.env)
        engagement._ea_require_access()
        engagement._ea_assert_mutable()
        return note

    def respond(self, text):
        """Reply without clearing (UAT B19): the reviewer decides whether the point is
        resolved. Anyone on the team may reply; the author is told."""
        note = self._ea_guard()
        reply = (text or "").strip()
        if not reply:
            raise paper_error(self.env, "response-required")
        if note.state != "open":
            raise paper_error(self.env, "not-found")
        note.response = "%s\n%s" % (note.response, self._ea_stamp(reply)) if note.response else self._ea_stamp(reply)
        paper = note.file_item_id._ea_paper()
        paper.with_env(self.env)._ea_trail("review_note_answered", "Review note on %s answered" % note.code)
        paper.with_env(self.env)._ea_notify_users(
            note.author_id, "%s: réponse à votre note / reply to your note" % note.code, reply[:400],
        )
        return True

    def _ea_is_preparer(self, user):
        """isPreparerOfNote: the holder of the active preparer sign-off, or the task's owner."""
        item = self.sudo().file_item_id
        if user in (item.preparer_id | item.assignee_id):
            return True
        return user in item._ea_paper()._ea_active_signoffs().filtered(lambda s: s.role == "preparer").user_id

    def clear(self, response=""):
        """ISA 220 (Revised) para. 29 puts the judgement that a point is resolved with the
        reviewer. The author may always withdraw their own; otherwise a manager or above
        who did not prepare the paper (UAT B19)."""
        note = self._ea_guard()
        user = self.env.user
        if note.author_id != user:
            if not at_least(user._ea_firm_role(), "manager"):
                raise paper_error(self.env, "requires-manager-or-author")
            if note._ea_is_preparer(user):
                raise paper_error(self.env, "not-preparer-clears")
        comment = (response or "").strip()
        vals = {"state": "cleared", "cleared_at": fields.Datetime.now(), "cleared_by_id": user.id}
        if comment:
            stamped = self._ea_stamp(comment)
            vals["response"] = "%s\n%s" % (note.response, stamped) if note.response else stamped
        note.write(vals)
        note.file_item_id._ea_paper().with_env(self.env)._ea_trail(
            "review_note_cleared", "Review note on %s cleared" % note.code,
        )
        return True

    @api.model
    def _ea_payload(self, item):
        Note = self.sudo()
        return [
            {
                "id": note.id, "body": note.body, "response": note.response or "", "state": note.state,
                "author": note.author_id.name,
                "assignee": note.assignee_id.name or "",
                "date": fields.Datetime.context_timestamp(self.with_context(tz="Africa/Douala"), note.create_date).strftime("%d/%m/%Y %H:%M"),
                "mine": note.author_id == self.env.user,
            }
            for note in Note.search([("file_item_id", "=", item.id)])
        ]
