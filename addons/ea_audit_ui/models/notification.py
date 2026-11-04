from odoo import api, fields, models


class Notification(models.Model):
    """One line of the bell. Rows come from real events only (a signature that
    hands work over, tasks assigned, a team invitation): the methods that carry
    those events write them as superuser. A user reads and marks their own."""

    _name = "ea.audit.notification"
    _description = "Audit notification"
    _order = "id desc"

    user_id = fields.Many2one("res.users", string="For", required=True, index=True, ondelete="cascade")
    kind = fields.Selection(
        [("task", "Task"), ("mission", "Engagement"), ("invitation", "Invitation")], required=True, default="task",
    )
    title = fields.Char(required=True)
    detail = fields.Char()
    engagement_id = fields.Many2one("ea.audit.engagement", required=True, index=True, ondelete="cascade")
    file_item_id = fields.Many2one("ea.audit.file.item", ondelete="cascade")
    read_at = fields.Datetime(index=True)

    @api.model
    def _ea_ui_visible(self, unread_only=False):
        """The caller's rows, without those of a file they have since left: the
        row's words name the client, and the file's rule decides who sees that.
        An invitation is the exception, it reaches someone not yet on the team."""
        domain = [("user_id", "=", self.env.uid)]
        if unread_only:
            domain.append(("read_at", "=", False))
        rows = self.search(domain).sudo()
        files = self.env["ea.audit.engagement"].search([("id", "in", rows.engagement_id.ids)]).ids
        return rows.filtered(lambda row: row.kind == "invitation" or row.engagement_id.id in files)
