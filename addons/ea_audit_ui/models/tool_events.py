"""The bell's other events: what the tools and the papers hand over to someone. Each row
comes from the real method that carries the event, never from the screen."""
from odoo import models

from ..services.presentation import short_name


class Engagement(models.Model):
    _inherit = "ea.audit.engagement"

    def _ea_ui_notify_seniors(self, words, item=None):
        """The partner and the file's managers, not the one who acted. ``words`` gets the
        environment of each addressee and returns (title, detail) in their language."""
        as_root = self.sudo()
        managers = as_root.team_member_ids.filtered(
            lambda member: member.state == "accepted" and member.team_role in ("manager", "director")
        ).user_id
        for user in (as_root.engagement_partner_id | managers) - self.env.user:
            title, detail = words(self.with_context(lang=user.lang or self.env.lang).env)
            self.env["ea.audit.notification"].sudo().create({
                "user_id": user.id,
                "kind": "task" if item else "mission",
                "title": title,
                "detail": detail,
                "engagement_id": self.id,
                "file_item_id": item.id if item else False,
            })

    def route_finding(self, *args, **kwargs):
        result = super().route_finding(*args, **kwargs)
        finding = result.get("finding")
        if finding:
            as_root = finding.sudo()
            actor = short_name(self.env.user.name)
            self._ea_ui_notify_seniors(
                lambda env: (
                    env._("Finding %(reference)s: %(title)s", reference=as_root.reference, title=as_root.title),
                    env._("%(name)s raised this finding", name=actor),
                ),
                as_root.file_item_id or None,
            )
        return result

    def create_materiality_version(self, *args, **kwargs):
        version = super().create_materiality_version(*args, **kwargs)
        actor = short_name(self.env.user.name)
        number = version.sudo().version_no
        self._ea_ui_notify_seniors(lambda env: (
            env._("Materiality to approve: version %(number)s", number=number),
            env._("%(name)s created this version", name=actor),
        ))
        return version


class FileItem(models.Model):
    _inherit = "ea.audit.file.item"

    def add_review_note(self, body, task_key=False):
        note_id = super().add_review_note(body, task_key)
        note = self.env["ea.audit.review.note"].sudo().browse(note_id)
        if note.assignee_id:
            reader = self._ea_ui_for_reader(note.assignee_id)
            self._ea_ui_notify(
                note.assignee_id,
                reader.env._("Review note: %(label)s", label=reader.sudo()._ea_ui_label()),
                reader.env._("%(name)s wrote a note", name=short_name(self.env.user.name)),
            )
        return note_id
