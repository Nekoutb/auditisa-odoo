from datetime import timedelta

from odoo import api, fields, models

from ..services import deadlines
from . import labels
from .common import refuse

REOPEN_HOURS = 48
REASON_MIN_LENGTH = 10


class TimesheetWeek(models.Model):
    """A person's week: whether it was submitted. The deadline is not stored, it
    is a function of the week, so that a lock needs no scheduled job to happen.
    The row is also the point where concurrent saves of a week serialise."""

    _name = "ea.audit.timesheet.week"
    _description = "Timesheet week"
    _order = "week_start desc"
    _rec_name = "week_start"

    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")
    week_start = fields.Date(required=True, index=True)
    state = fields.Selection([("draft", "Draft"), ("submitted", "Submitted")], required=True, default="draft")
    submitted_at = fields.Datetime()
    submitted_by_id = fields.Many2one("res.users", ondelete="set null")

    _user_week_uniq = models.Constraint("UNIQUE(user_id, week_start)", "One row per person and week.")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise refuse(self.env, "fa-forbidden")
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            raise refuse(self.env, "fa-forbidden")
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            raise refuse(self.env, "fa-forbidden")
        return super().unlink()

    @api.model
    def _ea_ts_now(self):
        """The clock, naive UTC. One place, so that a test can set it."""
        return fields.Datetime.now()

    @api.model
    def _ea_ts_row(self, user, monday):
        return self.sudo().search([("user_id", "=", user.id), ("week_start", "=", monday)], limit=1)

    @api.model
    def _ea_ts_touch(self, user, monday):
        """Take the week's row: two concurrent saves or a save and a submit on
        the same week cannot both pass under repeatable read, one is retried."""
        self.env.flush_all()
        self.env.cr.execute(
            """
            INSERT INTO ea_audit_timesheet_week
                (user_id, week_start, state, create_date, write_date, create_uid, write_uid)
            VALUES (%(user)s, %(monday)s, 'draft', now() at time zone 'utc', now() at time zone 'utc', %(uid)s, %(uid)s)
            ON CONFLICT (user_id, week_start) DO NOTHING
            """,
            {"user": user.id, "monday": monday, "uid": self.env.uid},
        )
        self.env.cr.execute(
            "UPDATE ea_audit_timesheet_week SET write_date = now() at time zone 'utc' WHERE user_id = %s AND week_start = %s",
            [user.id, monday],
        )
        self.invalidate_model()

    @api.model
    def _ea_ts_status(self, user, monday, now=None):
        now = now or self._ea_ts_now()
        row = self._ea_ts_row(user, monday)
        reopen = self.env["ea.audit.timesheet.reopen"]._ea_ts_active(user, monday, now)
        return deadlines.week_status(monday, now, row.state == "submitted", reopen.expires_at if reopen else None)

    @api.model
    def _ea_ts_assert_editable(self, user, day):
        """The deadline rule itself, whoever writes and by whichever road."""
        now = self._ea_ts_now()
        if day > deadlines.local_today(now):
            raise refuse(self.env, "ts-future-date")
        status = self._ea_ts_status(user, deadlines.week_start(day), now)
        if status in (deadlines.LOCKED, deadlines.LOCKED_SUBMITTED):
            raise refuse(self.env, "ts-week-locked")
        if status == deadlines.SUBMITTED:
            raise refuse(self.env, "ts-week-submitted")

    @api.model
    def _ea_ts_submit(self, user, monday):
        now = self._ea_ts_now()
        status = self._ea_ts_status(user, monday, now)
        if status == deadlines.FUTURE:
            raise refuse(self.env, "ts-submit-future")
        if not deadlines.editable(status):
            raise refuse(self.env, "ts-week-submitted" if status == deadlines.SUBMITTED else "ts-submit-closed")
        self._ea_ts_touch(user, monday)
        self._ea_ts_row(user, monday).write({"state": "submitted", "submitted_at": now, "submitted_by_id": user.id})
        self.env["ea.audit.timesheet.reopen"]._ea_ts_active(user, monday, now).write({"closed_at": now})

    @api.model
    def _ea_ts_recall(self, user, monday):
        """Before the deadline a person may take their submission back."""
        if self._ea_ts_status(user, monday) != deadlines.SUBMITTED:
            raise refuse(self.env, "ts-recall-closed")
        self._ea_ts_row(user, monday).write({"state": "draft", "submitted_at": False, "submitted_by_id": False})


class TimesheetReopen(models.Model):
    """Reopening one person's locked week: written reason, limited time, kept for good."""

    _name = "ea.audit.timesheet.reopen"
    _description = "Reopening of a locked timesheet week"
    _order = "id desc"

    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="restrict")
    week_start = fields.Date(required=True, index=True)
    reason = fields.Text(required=True)
    opened_by_id = fields.Many2one("res.users", required=True, ondelete="restrict")
    opened_at = fields.Datetime(required=True)
    expires_at = fields.Datetime(required=True)
    closed_at = fields.Datetime()

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise refuse(self.env, "ts-reopen-forbidden")
        return super().create(vals_list)

    def write(self, vals):
        # the record stays what it was: only the moment a resubmission closes it is added
        if not self.env.su or set(vals) - {"closed_at"}:
            raise refuse(self.env, "ts-reopen-forbidden")
        return super().write(vals)

    def unlink(self):
        raise refuse(self.env, "ts-reopen-forbidden")

    @api.model
    def _ea_ts_active(self, user, monday, now):
        return self.sudo().search([
            ("user_id", "=", user.id), ("week_start", "=", monday),
            ("closed_at", "=", False), ("expires_at", ">", now),
        ], limit=1)

    @api.model
    def _ea_ts_may_reopen(self, actor, person):
        role = actor._ea_firm_role()
        if role == "firm_admin":
            return True
        if role != "partner":
            return False
        Team = self.env["ea.audit.team.member"].sudo()
        led = Team.search([("user_id", "=", actor.id), ("team_role", "=", "partner"), ("state", "=", "accepted")])
        return bool(Team.search_count([
            ("engagement_id", "in", led.engagement_id.ids), ("user_id", "=", person.id), ("state", "=", "accepted"),
        ]))

    @api.model
    def _ea_ts_reopen(self, person, monday, reason):
        actor = self.env.user
        if actor == person:
            raise refuse(self.env, "ts-reopen-self")
        if not self._ea_ts_may_reopen(actor, person):
            raise refuse(self.env, "ts-reopen-forbidden")
        why = (reason or "").strip()
        if len(why) < REASON_MIN_LENGTH:
            raise refuse(self.env, "ts-reopen-reason")
        Week = self.env["ea.audit.timesheet.week"]
        now = Week._ea_ts_now()
        status = Week._ea_ts_status(person, monday, now)
        if status == deadlines.REOPENED:
            raise refuse(self.env, "ts-reopen-active")
        if status not in (deadlines.LOCKED, deadlines.LOCKED_SUBMITTED):
            raise refuse(self.env, "ts-reopen-not-locked")
        Week._ea_ts_touch(person, monday)
        Week._ea_ts_row(person, monday).write({"state": "draft"})
        record = self.sudo().create({
            "user_id": person.id, "week_start": monday, "reason": why, "opened_by_id": actor.id,
            "opened_at": now, "expires_at": now + timedelta(hours=REOPEN_HOURS),
        })
        self.env["ea.audit.firm.log"]._ea_append(
            "week_reopened", person, "%s: %s" % (labels.week_label(self.env, monday), why),
        )
        return record
