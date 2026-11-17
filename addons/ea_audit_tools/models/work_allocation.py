from odoo import models

from odoo.addons.ea_audit_core.services.signoff_rules import EQR_PAPER, EQR_ROLE, at_least, team_rank
from odoo.addons.ea_audit_core.services.work_allocation import phase_of_code, suggest

from ..exports import simple_workbook
from ..rules import rule_error
from .tool_record import french_date

STATUS_TONES = {
    "not_started": "grey", "in_progress": "amber", "prepared": "blue", "reviewed": "blue", "signed": "green",
    "not_applicable": "grey",
}


class EngagementWorkAllocation(models.Model):
    """Work allocation (owner's mock-up of 2026-11-18): who prepares and who reviews each task of
    the file, on one page. It took the tile of the client's overrides. The rules live in the core
    (ea_allocate_tasks, _ea_sync_partner_approval); this is the page and its Excel."""

    _inherit = "ea.audit.engagement"

    def action_tool_work_allocation(self):
        self.ensure_one()
        self._ea_require_access()
        return {
            "type": "ir.actions.client", "tag": "ea_audit_tools.work_allocation_page", "target": "current",
            "name": self.env._("Work allocation"), "params": {"engagement_id": self.id},
            "context": {"active_id": self.id, "ea_engagement_id": self.id},
        }

    def _ea_wa_items(self):
        """The active tasks of the file, as the task lists show them: not a task waiting for its
        fact, not an E4 task S5.5 left out, not C4.2 (the quality reviewer's own record)."""
        self.ensure_one()
        items = self.env["ea.audit.file.item"].sudo().search([
            ("engagement_id", "=", self.id), ("conditional", "=", False), ("code", "!=", EQR_PAPER),
        ])
        return items - self.sudo()._ea_e4_out_of_scope()

    def _ea_wa_may_edit(self):
        """The engagement partner and the managers of the team (the team's own rule: a manager or
        above, the firm administrator included); nobody on an archived file."""
        self.ensure_one()
        user = self.env.user
        role = user._ea_firm_role()
        if self._ea_is_archived() or role == EQR_ROLE or not at_least(role, "manager"):
            return False
        return not self.sudo()._ea_acts_as_eqr(user)

    def _ea_wa_members(self):
        as_root = self.sudo()
        return as_root.team_member_ids.filtered(lambda m: m.state == "accepted" and m.team_role != EQR_ROLE)

    def _ea_wa_deadline(self, item):
        """The task's own deadline. ea_audit_ui gives the phase's when it has none (F011)."""
        return french_date(item.due_date)

    def ea_work_allocation_page(self):
        self.ensure_one()
        self._ea_require_access()
        as_root = self.sudo()
        Item = self.env["ea.audit.file.item"]
        Policy = self.env["ea.audit.signoff.policy"]
        items = self._ea_wa_items()
        rules = as_root._ea_allocation_rules(items)
        partner = as_root._ea_allocation_partner()
        role_labels = dict(self.env["ea.audit.team.member"]._fields["team_role"]._description_selection(self.env))
        states = dict(Item._fields["state"]._description_selection(self.env))
        members = self._ea_wa_members().sorted(lambda m: (-team_rank(m.team_role), m.user_id.name or ""))
        rows = []
        for item in items:
            rule = rules[item.id]
            status = "not_applicable" if item.not_applicable else item.state
            rows.append({
                "id": item.id,
                "code": item.code,
                "title": item.title or "",
                "phase": phase_of_code(item.code),
                "rule": Policy._ea_rule_words(rule),
                "minPreparer": rule["min_preparer"],
                "minReviewer": rule["min_reviewer"],
                "partnerRequired": bool(rule["partner_required"]),
                "preparer": item.preparer_id.id or False,
                "reviewer": item.approver_id.id or False,
                "assignee": item.assignee_id.id or False,
                "deadline": self._ea_wa_deadline(item),
                "status": self.env._("Not applicable") if item.not_applicable else states.get(item.state, item.state),
                "tone": STATUS_TONES.get(status, "grey"),
            })
        return {
            "engagement": as_root.display_name,
            "readonly": not self._ea_wa_may_edit(),
            "archived": self._ea_is_archived(),
            "uid": self.env.uid,
            "partner": {"id": partner.id, "name": partner.name} if partner else False,
            "members": [{
                "id": member.user_id.id,
                "name": member.user_id.name,
                "role": member.team_role,
                "roleLabel": role_labels.get(member.team_role, member.team_role),
                "rank": team_rank(member.team_role),
            } for member in members],
            "roleWords": Policy._ea_sentence_role_words(),
            "rows": rows,
        }

    def ea_work_allocation_suggest(self, current):
        """"Suggest by role" for the boxes still empty on the screen. ``current``: [{id, preparer,
        reviewer}] as the screen holds them. Nothing is saved: {task id: {preparer, reviewer}}."""
        self.ensure_one()
        self._ea_require_access()
        if not self._ea_wa_may_edit():
            raise rule_error(self.env, "team-manager-only")
        items = self._ea_wa_items()
        rules = self.sudo()._ea_allocation_rules(items)
        screen = {int(row["id"]): row for row in current or [] if row.get("id")}
        rows = []
        for item in items:
            held = screen.get(item.id, {})
            rows.append({
                "id": item.id,
                "min_preparer": rules[item.id]["min_preparer"],
                "min_reviewer": rules[item.id]["min_reviewer"],
                "preparer": held.get("preparer", item.preparer_id.id) or None,
                "reviewer": held.get("reviewer", item.approver_id.id) or None,
                "assignee": item.assignee_id.id or None,
            })
        members = [{"user_id": m.user_id.id, "role": m.team_role} for m in self._ea_wa_members()]
        return {str(key): value for key, value in suggest(rows, members).items()}

    def ea_work_allocation_save(self, changes):
        """Save: the core's rules, then the page again."""
        self.ensure_one()
        result = self.ea_allocate_tasks(changes)
        return {"page": self.ea_work_allocation_page(), "warnings": len(result["warnings"])}

    def action_export_work_allocation(self):
        return self._ea_export_action("work_allocation")

    def _ea_export_work_allocation(self, fr):
        page = self.ea_work_allocation_page()
        names = {member["id"]: member["name"] for member in page["members"]}
        partner = page["partner"]["name"] if page["partner"] else ""
        phases = {
            "planning": "Planification" if fr else "Planning",
            "strategy": "Stratégie et risques" if fr else "Strategy and risks",
            "execution": "Exécution" if fr else "Execution",
            "conclusion": "Conclusion",
        }
        not_needed = "Non requise" if fr else "Not needed"
        rows = [[
            row["code"], row["title"], phases[row["phase"]], row["rule"],
            names.get(row["preparer"], ""), names.get(row["reviewer"], ""),
            (partner if row["partnerRequired"] else not_needed), row["deadline"], row["status"],
        ] for row in page["rows"]]
        head = (
            ["Code", "Tâche", "Phase", "Règle de la politique de signature", "Préparateur", "Réviseur",
             "Approbation de l'associé", "Échéance", "Statut"]
            if fr else
            ["Code", "Task", "Phase", "Rule from the sign-off policy", "Preparer", "Reviewer",
             "Partner approval", "Deadline", "Status"]
        )
        name = "repartition-travaux" if fr else "work-allocation"
        return "%s-%s.xlsx" % (name, self._ea_export_slug()), simple_workbook(
            "Répartition" if fr else "Allocation", head, rows,
        )
