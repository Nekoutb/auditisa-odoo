from odoo import api, fields, models

from ..services import deadlines
from ..services.phases import BUDGET_PHASES, budget_phase
from .common import refuse

# What a person's sheet says. Everything else on a line (amount, accounts, company,
# partner) is Odoo's own bookkeeping, which hr_timesheet writes as superuser.
_GUARDED = {"date", "unit_amount", "user_id", "employee_id", "project_id", "task_id", "name"}


class AccountAnalyticLine(models.Model):
    """The rules hold on the ORM's entry points, so a screen, a direct RPC write and
    an import meet the same refusals. The superuser is not exempt from the deadline:
    no code path or context key relaxes it, only a logged reopening does."""

    _inherit = "account.analytic.line"

    ea_phase = fields.Selection(BUDGET_PHASES, string="Phase", index="btree_not_null", readonly=True, copy=False)

    _ea_timesheet_hours_range = models.Constraint(
        "CHECK(project_id IS NULL OR (unit_amount >= 0 AND unit_amount <= 24))",
        "Les heures doivent être comprises entre 0 et 24.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        users = self.env["res.users"]
        for vals in vals_list:
            if vals.get("project_id") or vals.get("task_id"):
                vals.pop("ea_phase", None)
                # no range check needed first: a refused value fails in _ea_ts_enforce
                if not vals.get("employee_id"):
                    users |= self.env["res.users"].browse(vals.get("user_id") or self._default_user())
                if not self.env.su and vals.get("user_id", self.env.uid) != self.env.uid:
                    raise refuse("ts-own-lines-only")
        users._ea_ts_ensure_employee()
        lines = super().create(vals_list)
        lines.filtered("project_id")._ea_ts_enforce()
        return lines

    def write(self, vals):
        if not _GUARDED & set(vals):
            return super().write(vals)
        vals = {key: value for key, value in vals.items() if key != "ea_phase"}
        before = self.sudo().filtered("project_id")
        before._ea_ts_assert_may_change()
        result = super().write(vals)
        if "project_id" in vals and before.filtered(lambda line: not line.project_id):
            raise refuse("ts-project-required")
        self.filtered("project_id")._ea_ts_enforce()
        return result

    def unlink(self):
        self.sudo().filtered("project_id")._ea_ts_assert_may_change()
        return super().unlink()

    # ------------------------------------------------------------------

    def _ea_ts_assert_may_change(self):
        """On the line as it stands: whose it is, its week, its file."""
        Week = self.env["ea.audit.timesheet.week"]
        for line in self.sudo():
            if not self.env.su and line.user_id != self.env.user:
                raise refuse("ts-own-lines-only")
            if line.project_id.ea_engagement_id._ea_is_archived() if line.project_id.ea_engagement_id else False:
                raise refuse("ts-archived")
            Week._ea_ts_assert_editable(line.user_id, line.date)

    def _ea_ts_chargeable_refusal(self, project, user):
        """The code that refuses ``user`` charging ``project``, None when they may."""
        project = project.sudo()
        engagement = project.ea_engagement_id
        if engagement:
            if engagement._ea_is_archived() or not project.active:
                return "ts-archived"
            seat = self.env["ea.audit.team.member"].sudo().search_count([
                ("engagement_id", "=", engagement.id), ("user_id", "=", user.id), ("state", "=", "accepted"),
            ])
            return None if seat else "ts-not-on-team"
        if project.ea_is_internal and project.active:
            return None
        return "ts-project-not-chargeable"

    def _ea_ts_enforce(self):
        """On the line as it now is. Runs after Odoo's write, in its transaction:
        a refusal undoes the write."""
        Week = self.env["ea.audit.timesheet.week"]
        lines = self.sudo()
        for line in lines:
            if not self.env.su and line.user_id != self.env.user:
                raise refuse("ts-own-lines-only")
            refusal = self._ea_ts_chargeable_refusal(line.project_id, line.user_id)
            if refusal:
                raise refuse(refusal)
            if line.task_id and line.task_id.project_id != line.project_id:
                raise refuse("ts-task-other-project")
            # "not (a <= x <= b)" also refuses NaN
            if not (0 <= line.unit_amount <= 24):
                raise refuse("ts-hours-range")
            Week._ea_ts_assert_editable(line.user_id, line.date)
        for user, monday in sorted({(line.user_id, deadlines.week_start(line.date)) for line in lines}, key=lambda k: (k[0].id, k[1])):
            Week._ea_ts_touch(user, monday)
        self._ea_ts_check_day_totals(lines)
        for line in lines:
            phase = line._ea_ts_phase()
            if line.ea_phase != phase:
                # a stored field outside _GUARDED, on the line just checked
                super(AccountAnalyticLine, line).write({"ea_phase": phase})

    def _ea_ts_check_day_totals(self, lines):
        self.env.flush_all()
        for user, day in {(line.user_id, line.date) for line in lines}:
            rows = self.sudo()._read_group(
                [("project_id", "!=", False), ("user_id", "=", user.id), ("date", "=", day)], [], ["unit_amount:sum"],
            )
            if (rows[0][0] or 0) > 24:
                raise refuse("ts-day-over-24")

    def _ea_ts_phase(self):
        self.ensure_one()
        engagement = self.project_id.ea_engagement_id
        if not engagement:
            return False
        return self.task_id.ea_phase or self.ea_phase or budget_phase(engagement.phase)

    def _ea_ts_week_start(self):
        self.ensure_one()
        return deadlines.week_start(self.date)
