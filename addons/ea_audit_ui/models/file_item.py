from odoo import fields, models

from ..services.presentation import fmt_date, short_name


def _lt(text):
    return text


_ROLE_WORDS = {"preparer": _lt("preparer"), "approver": _lt("reviewer"), "assignee": _lt("assignee")}


class FileItem(models.Model):
    _inherit = "ea.audit.file.item"

    def _ea_deadline_payload(self):
        """F011: the one date the group, the dashboard and the paper read."""
        self.ensure_one()
        item = self.sudo()
        Ui = self.env["ea.audit.ui"]
        due = Ui._ea_ui_due(item)
        days = Ui._ea_ui_late_days(item, Ui._ea_ui_today())
        return {
            "date": fmt_date(due),
            "own": fields.Date.to_string(item.due_date) if item.due_date else "",
            "late_text": Ui._ea_ui_late_text(days),
        }

    def _ea_ui_label(self):
        self.ensure_one()
        return "%s %s" % (self.code, self.sudo().title)

    def _ea_ui_for_reader(self, user):
        """The same records in the addressee's language: a notification is read by them."""
        return self.with_context(lang=user.sudo().lang or self.env.lang)

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
        if role == "preparer":
            # the partner signs a partner-only paper; anyone else, the assigned reviewer
            rule = self.env["ea.audit.signoff.policy"]._ea_effective_rule(item.code)
            reviewer = item.approver_id or (engagement.engagement_partner_id if rule["partner_required"] else None)
            if reviewer:
                reader = self._ea_ui_for_reader(reviewer)
                self._ea_ui_notify(
                    reviewer,
                    reader.env._("To review: %(label)s", label=reader._ea_ui_label()),
                    reader.env._("%(name)s signed as preparer", name=signer),
                )
        elif role == "reviewer" and item.state == "reviewed":
            partner = engagement.engagement_partner_id
            reader = self._ea_ui_for_reader(partner)
            self._ea_ui_notify(
                partner,
                reader.env._("To sign: %(label)s", label=reader._ea_ui_label()),
                reader.env._("%(name)s signed as reviewer", name=signer),
            )
        return role

    def _ea_assign_tasks(self, user_id, role="assignee", below_minimum_warns=False):
        count = super()._ea_assign_tasks(user_id, role, below_minimum_warns)
        if user_id and user_id != self.env.uid:
            addressee = self.env["res.users"].sudo().browse(user_id)
            reader = self._ea_ui_for_reader(addressee)
            word = reader.env._(_ROLE_WORDS[role]) if role in _ROLE_WORDS else role
            actor = short_name(self.env.user.name)
            for engagement in self.sudo().engagement_id:
                items = reader.sudo().filtered(lambda i: i.engagement_id == engagement)
                single = len(items) == 1
                self.env["ea.audit.notification"].sudo().create({
                    "user_id": user_id,
                    "kind": "task" if single else "mission",
                    "title": (
                        reader.env._("Task assigned: %(label)s", label=items._ea_ui_label())
                        if single
                        else reader.env._(
                            "%(count)s tasks assigned: %(client)s, %(year)s",
                            count=len(items), client=engagement.client_id.name, year=engagement.fiscal_year,
                        )
                    ),
                    "detail": reader.env._("%(name)s named you as %(role)s", name=actor, role=word),
                    "engagement_id": engagement.id,
                    "file_item_id": items.id if single else False,
                })
        return count
