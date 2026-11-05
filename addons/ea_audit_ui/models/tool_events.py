"""The bell's other events: what the tools and the papers hand over to someone. Each row
comes from the real method that carries the event, never from the screen."""
from odoo import models

from ..services.presentation import short_name


class Engagement(models.Model):
    _inherit = "ea.audit.engagement"

    def _ea_ui_notify_seniors(self, title, detail, item=None):
        """The partner and the file's managers, not the one who acted."""
        as_root = self.sudo()
        managers = as_root.team_member_ids.filtered(
            lambda member: member.state == "accepted" and member.team_role in ("manager", "director")
        ).user_id
        for user in (as_root.engagement_partner_id | managers) - self.env.user:
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
            self._ea_ui_notify_seniors(
                "Constat %s : %s" % (as_root.reference, as_root.title),
                "%s a relevé ce constat" % short_name(self.env.user.name),
                as_root.file_item_id or None,
            )
        return result

    def create_materiality_version(self, *args, **kwargs):
        version = super().create_materiality_version(*args, **kwargs)
        self._ea_ui_notify_seniors(
            "Seuil à approuver : version %s" % version.sudo().version_no,
            "%s a créé cette version" % short_name(self.env.user.name),
        )
        return version


class FileItem(models.Model):
    _inherit = "ea.audit.file.item"

    def add_review_note(self, body):
        note_id = super().add_review_note(body)
        note = self.env["ea.audit.review.note"].sudo().browse(note_id)
        self._ea_ui_notify(
            note.assignee_id, "Note de revue : %s" % self.sudo()._ea_ui_label(), "%s a écrit une note" % short_name(self.env.user.name),
        )
        return note_id
