from markupsafe import escape

from odoo import api, fields, models
from odoo.addons.mail.tools.discuss import Store

from ..services.activity_summary import parse_body, translate_summary
from ..services.errors import rule_error

_BACKFILL_DONE = "ea_audit_core.activity_backfilled"


class Activity(models.Model):
    """The firm's audit log (F027): who did what and when, on every engagement and on the firm's
    own settings, with the full text before and after an answer. Append-only. Read by the firm
    administrator alone, whichever team they are on: there is deliberately no team rule here,
    and the access right is on group_firm_admin only."""

    _name = "ea.audit.activity"
    _description = "Firm audit log entry"
    _order = "at desc, id desc"
    _rec_name = "summary_display"

    at = fields.Datetime(string="Date", required=True, default=fields.Datetime.now, readonly=True, index=True)
    user_id = fields.Many2one("res.users", string="User", ondelete="restrict", readonly=True, index=True)
    # Kept in words: the reader need not be on the file, and the line outlives it.
    engagement_id = fields.Many2one("ea.audit.engagement", ondelete="set null", readonly=True, index=True)
    engagement_label = fields.Char(string="Engagement", readonly=True, index=True)
    action = fields.Char(required=True, readonly=True, index=True)
    summary = fields.Char(string="As stored", readonly=True)
    summary_display = fields.Char(string="Summary", compute="_compute_summary_display")
    code = fields.Char(string="Task", readonly=True, index=True)
    field_key = fields.Char(string="Field", readonly=True)
    before = fields.Text(string="Before", readonly=True)
    after = fields.Text(string="After", readonly=True)

    @api.depends_context("lang")
    @api.depends("action", "summary")
    def _compute_summary_display(self):
        lang = self.env.lang or "en_US"
        for row in self:
            row.summary_display = translate_summary(row.action, row.summary, lang)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise rule_error(self.env, "forbidden")
        return super().create(vals_list)

    def write(self, vals):
        raise rule_error(self.env, "forbidden")

    def unlink(self):
        raise rule_error(self.env, "forbidden")

    @api.model
    def _ea_vals(self, engagement, action, summary, **extra):
        code = extra.pop("code", None)
        if not code and summary:
            head = summary.split(" ", 1)[0].rstrip(":")
            code = head if head[:1].isupper() and "." in head and len(head) <= 6 else None
        as_root = engagement.sudo() if engagement else None
        return {
            "user_id": self.env.uid,
            "engagement_id": as_root.id if as_root else False,
            "engagement_label": as_root.display_name if as_root else False,
            "action": action,
            "summary": summary,
            "code": code or False,
            **extra,
        }

    @api.model
    def _ea_record(self, engagement, action, summary, **extra):
        return self.sudo().create(self._ea_vals(engagement, action, summary, **extra))

    @api.model
    def _ea_backfill_trail(self):
        """Once, on the update that brings the log: what the chatter already holds."""
        params = self.env["ir.config_parameter"].sudo()
        if params.get_param(_BACKFILL_DONE):
            return
        params.set_param(_BACKFILL_DONE, "1")
        messages = self.env["mail.message"].sudo().search(
            [("model", "=", "ea.audit.engagement"), ("message_type", "=", "notification")], order="id",
        )
        engagements = self.env["ea.audit.engagement"].sudo().browse(set(messages.mapped("res_id"))).exists()
        by_id = {engagement.id: engagement for engagement in engagements}
        rows = []
        for message in messages:
            parsed = parse_body(message.body)
            if not parsed or message.res_id not in by_id:
                continue
            author = message.author_id.user_ids[:1]
            rows.append({
                **self._ea_vals(by_id[message.res_id], parsed[0], parsed[1]),
                "at": message.date, "user_id": author.id or False,
            })
        if rows:
            self.sudo().create(rows)


class MailMessage(models.Model):
    _inherit = "mail.message"

    def _ea_body_for_reader(self):
        """The stored line, read in the caller's language and without its key."""
        self.ensure_one()
        if self.model == "ea.audit.engagement" and self.message_type == "notification":
            parsed = parse_body(self.body)
            if parsed:
                return escape(translate_summary(parsed[0], parsed[1], self.env.lang))
        return self.body

    def _to_store_defaults(self, target):
        return [
            Store.Attr("body", lambda message: message._ea_body_for_reader()) if name == "body" else name
            for name in super()._to_store_defaults(target)
        ]
