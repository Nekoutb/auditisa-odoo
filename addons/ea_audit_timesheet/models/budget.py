from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.errors import rule_error

from ..services.phases import BUDGET_PHASES
from . import labels
from .common import refuse

_LEADS = ("partner", "manager")


class TeamBudget(models.Model):
    """Budget hours of a team seat in a phase. Written only by ea_ts_budget_set,
    under the team manager's rule of the engagement."""

    _name = "ea.audit.team.budget"
    _description = "Budget hours per team member and phase"

    member_id = fields.Many2one("ea.audit.team.member", required=True, index=True, ondelete="cascade")
    engagement_id = fields.Many2one(related="member_id.engagement_id", store=True, index=True)
    phase = fields.Selection(BUDGET_PHASES, required=True)
    hours = fields.Float(required=True, default=0)

    _member_phase_uniq = models.Constraint("UNIQUE(member_id, phase)", "One budget per team member and phase.")
    _hours_positive = models.Constraint("CHECK(hours >= 0)", "A budget is a positive number of hours.")

    @api.model
    def ea_ts_budget(self, engagement_id):
        """Budget against actual, per person and phase. A partner or manager seat
        reads the whole team, anyone else on the team their own row: the same
        reach as the lines themselves."""
        engagement = self.env["ea.audit.engagement"].browse(int(engagement_id)).exists()
        if not engagement:
            raise rule_error(self.env, "not-found")
        engagement._ea_require_read()
        as_root = engagement.sudo()
        mine = as_root._ea_member(self.env.user)
        look_only = as_root._ea_look_only(self.env.user)
        # the firm administrator off the team reads the whole team, look-only (owner, 2026-11-15)
        lead = mine.team_role in _LEADS or look_only
        members = as_root.team_member_ids.filtered(lambda m: m.state == "accepted")
        if not lead:
            members = mine
        project = as_root._ea_ts_project()
        actuals = {}
        for user, phase, hours in self.env["account.analytic.line"].sudo()._read_group(
            [("project_id", "=", project.id), ("user_id", "in", members.user_id.ids)],
            ["user_id", "ea_phase"], ["unit_amount:sum"],
        ):
            actuals[(user.id, phase)] = hours or 0
        budgets = {
            (row.member_id.id, row.phase): row.hours
            for row in self.sudo().search([("member_id", "in", members.ids)])
        }
        rows = []
        for member in members:
            cells = []
            for key, _label in BUDGET_PHASES:
                cells.append({
                    "phase": key,
                    "budget": budgets.get((member.id, key), 0.0),
                    "actual": actuals.get((member.user_id.id, key), 0.0),
                })
            rows.append({
                "member_id": member.id,
                "name": member.user_id.name,
                "team_role": dict(member._fields["team_role"]._description_selection(self.env)).get(member.team_role),
                "cells": cells,
                "budget": sum(c["budget"] for c in cells),
                "actual": sum(c["actual"] for c in cells),
            })
        totals = [
            {
                "phase": key,
                "budget": sum(r["cells"][i]["budget"] for r in rows),
                "actual": sum(r["cells"][i]["actual"] for r in rows),
            }
            for i, (key, _label) in enumerate(BUDGET_PHASES)
        ]
        return {
            "engagement": engagement.display_name,
            "engagement_id": engagement.id,
            "phases": [{"key": key, "label": label} for key, label in labels.phase_labels(self.env)],
            "rows": rows,
            "totals": totals,
            "budget": sum(t["budget"] for t in totals),
            "actual": sum(t["actual"] for t in totals),
            "can_edit": lead and not look_only and not engagement._ea_is_archived(),
            "lead": lead,
        }

    @api.model
    def ea_ts_budget_set(self, member_id, phase, hours):
        member = self.env["ea.audit.team.member"].sudo().browse(int(member_id)).exists()
        if not member:
            raise rule_error(self.env, "not-found")
        engagement = member.engagement_id.with_env(self.env)
        engagement._ea_require_team_manager()
        engagement._ea_assert_mutable()
        if phase not in dict(BUDGET_PHASES):
            raise refuse(self.env, "ts-budget-range")
        try:
            hours = float(hours)
        except (TypeError, ValueError):
            raise refuse(self.env, "ts-budget-range") from None
        if not (0 <= hours <= 100000):
            raise refuse(self.env, "ts-budget-range")
        row = self.sudo().search([("member_id", "=", member.id), ("phase", "=", phase)], limit=1)
        if row:
            row.hours = hours
        else:
            self.sudo().create({"member_id": member.id, "phase": phase, "hours": hours})
        return True
