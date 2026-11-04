from odoo import models

from ..services.presentation import short_name

_ROLE_WORDS = {"preparer": "préparateur", "approver": "réviseur", "assignee": "assigné"}


class FileItem(models.Model):
    _inherit = "ea.audit.file.item"

    def _ea_ui_label(self):
        self.ensure_one()
        return "%s %s" % (self.code, self.sudo().with_context(lang="fr_FR").title)

    def _ea_ui_notify(self, user, title, detail):
        if user and user != self.env.user:
            self.env["ea.audit.notification"].sudo().create({
                "user_id": user.id,
                "kind": "task",
                "title": title,
                "detail": detail,
                "engagement_id": self.sudo().engagement_id.id,
                "file_item_id": self.id,
            })

    def action_sign(self, requested):
        role = super().action_sign(requested)
        item = self.sudo()
        engagement = item.engagement_id
        signer = short_name(self.env.user.name)
        label = item._ea_ui_label()
        if role == "preparer":
            # the partner signs a partner-only paper; anyone else, the assigned reviewer
            rule = self.env["ea.audit.signoff.policy"]._ea_effective_rule(item.code)
            reviewer = item.approver_id or (engagement.engagement_partner_id if rule["partner_required"] else None)
            self._ea_ui_notify(reviewer, "À réviser : %s" % label, "%s a signé comme préparateur" % signer)
        elif role == "reviewer" and item.state == "reviewed":
            self._ea_ui_notify(
                engagement.engagement_partner_id, "À signer : %s" % label, "%s a signé comme réviseur" % signer,
            )
        return role

    def assign_tasks(self, user_id, role="assignee"):
        count = super().assign_tasks(user_id, role)
        if user_id and user_id != self.env.uid:
            word = _ROLE_WORDS.get(role, role)
            actor = short_name(self.env.user.name)
            for engagement in self.sudo().engagement_id:
                items = self.sudo().filtered(lambda i: i.engagement_id == engagement)
                single = len(items) == 1
                self.env["ea.audit.notification"].sudo().create({
                    "user_id": user_id,
                    "kind": "task" if single else "mission",
                    "title": (
                        "Tâche affectée : %s" % items._ea_ui_label()
                        if single
                        else "%s tâches affectées : %s, %s" % (len(items), engagement.client_id.name, engagement.fiscal_year)
                    ),
                    "detail": "%s vous a désigné comme %s" % (actor, word),
                    "engagement_id": engagement.id,
                    "file_item_id": items.id if single else False,
                })
        return count
