from collections import defaultdict
from datetime import date, timedelta

from odoo import api, fields, models

from ..services import deadlines
from . import labels
from .common import refuse

OVERDUE_WEEKS = 4
GROUPINGS = ("person", "engagement", "period")


def _day(value, fallback=None):
    if not value:
        return fallback
    return fields.Date.to_date(value)


class TimesheetSheet(models.AbstractModel):
    """The screens' methods. They run under the caller's rights and write through
    the line's own create and write, so they carry no rule of their own."""

    _name = "ea.audit.timesheet.sheet"
    _description = "Timesheet: screen methods"

    # ------------------------------------------------------------------
    # The week
    # ------------------------------------------------------------------

    @api.model
    def _ea_ts_chargeable(self, user):
        Team = self.env["ea.audit.team.member"].sudo()
        seats = Team.search([("user_id", "=", user.id), ("state", "=", "accepted")])
        files = seats.engagement_id.filtered(lambda e: not e._ea_is_archived())
        Project = self.env["project.project"].sudo()
        missions = Project.search([("ea_engagement_id", "in", files.ids), ("allow_timesheets", "=", True)], order="name")
        internal = Project.search([("ea_is_internal", "=", True), ("allow_timesheets", "=", True)], order="name")
        tasks = defaultdict(list)
        phases = dict(labels.phase_labels(self.env))
        for task in self.env["project.task"].sudo().search(
            [("project_id", "in", (missions | internal).ids), ("state", "not in", ["1_canceled", "1_done"])], order="id",
        ):
            tasks[task.project_id.id].append({"id": task.id, "name": phases.get(task.ea_phase) or task.name})
        return [
            {"id": p.id, "label": p.name, "kind": "mission", "tasks": tasks[p.id]} for p in missions
        ] + [
            {"id": p.id, "label": p.name, "kind": "internal", "tasks": tasks[p.id]} for p in internal
        ]

    @api.model
    def _ea_ts_overdue(self, user, now):
        """Weeks past their deadline without a submission, oldest last, since the person joined."""
        Week = self.env["ea.audit.timesheet.week"]
        first = deadlines.week_start(fields.Date.to_date(user.sudo().create_date))
        monday = deadlines.week_start(deadlines.local_today(now))
        rows = []
        for back in range(1, OVERDUE_WEEKS + 2):
            week = monday - timedelta(days=7 * back)
            if week < first:
                break
            if Week._ea_ts_status(user, week, now) == deadlines.LOCKED:
                rows.append({
                    "monday": fields.Date.to_string(week),
                    "label": labels.week_label(self.env, week),
                    "hours": self._ea_ts_week_hours(user, week),
                })
        return rows

    @api.model
    def _ea_ts_week_hours(self, user, monday):
        rows = self.env["account.analytic.line"].sudo()._read_group(
            [("project_id", "!=", False), ("user_id", "=", user.id),
             ("date", ">=", monday), ("date", "<=", monday + timedelta(days=6))],
            [], ["unit_amount:sum"],
        )
        return rows[0][0] or 0.0

    @api.model
    def _ea_ts_warnings(self, user, monday, now):
        """Weeks still open whose deadline is the next thing to happen."""
        Week = self.env["ea.audit.timesheet.week"]
        today = deadlines.local_today(now)
        current = deadlines.week_start(today)
        rows = []
        previous = current - timedelta(days=7)
        if Week._ea_ts_status(user, previous, now) in (deadlines.OPEN, deadlines.REOPENED):
            rows.append({
                "monday": fields.Date.to_string(previous),
                "text": self.env._(
                    "%(week)s: submit by %(deadline)s, Douala time.",
                    week=labels.week_label(self.env, previous),
                    deadline=labels.deadline_label(self.env, previous),
                ),
            })
        return rows

    @api.model
    def ea_ts_sheet(self, day=None):
        user = self.env.user
        Week = self.env["ea.audit.timesheet.week"]
        now = Week._ea_ts_now()
        today = deadlines.local_today(now)
        monday = deadlines.week_start(_day(day, today))
        sunday = monday + timedelta(days=6)
        status = Week._ea_ts_status(user, monday, now)
        days = [monday + timedelta(days=i) for i in range(7)]
        lines = self.env["account.analytic.line"].search(
            [("project_id", "!=", False), ("user_id", "=", user.id), ("date", ">=", monday), ("date", "<=", sunday)],
            order="date, id",
        ).sudo()
        rows = {}
        phases = dict(labels.phase_labels(self.env))
        for line in lines:
            key = (line.project_id.id, line.task_id.id)
            row = rows.setdefault(key, {
                "key": "%s-%s" % key,
                "project_id": line.project_id.id,
                "task_id": line.task_id.id or False,
                "label": line.project_id.name,
                "task": phases.get(line.task_id.ea_phase) or line.task_id.name or "",
                "kind": "mission" if line.project_id.ea_engagement_id else "internal",
                "cells": defaultdict(float),
                "total": 0.0,
            })
            row["cells"][fields.Date.to_string(line.date)] += line.unit_amount
            row["total"] += line.unit_amount
        totals = {fields.Date.to_string(d): 0.0 for d in days}
        for row in rows.values():
            for key, value in row["cells"].items():
                totals[key] += value
            row["cells"] = dict(row["cells"])
        can_edit = deadlines.editable(status)
        reopen = self.env["ea.audit.timesheet.reopen"]._ea_ts_active(user, monday, now)
        submitted = Week._ea_ts_row(user, monday)
        return {
            "monday": fields.Date.to_string(monday),
            "label": labels.week_label(self.env, monday),
            "prev": fields.Date.to_string(monday - timedelta(days=7)),
            "next": fields.Date.to_string(monday + timedelta(days=7)),
            "has_next": monday + timedelta(days=7) <= today,
            "is_current": monday == deadlines.week_start(today),
            "status": status,
            "status_label": labels.status_label(self.env, status),
            "deadline_label": labels.deadline_label(self.env, monday),
            "can_edit": can_edit,
            "can_submit": can_edit,
            "can_recall": status == deadlines.SUBMITTED,
            "submitted_at": deadlines.instant_label(submitted.submitted_at) if submitted.submitted_at else False,
            "reopen": {
                "until": deadlines.instant_label(reopen.expires_at), "reason": reopen.reason,
            } if reopen else False,
            "days": [
                {
                    "date": fields.Date.to_string(d),
                    "label": labels.day_label(self.env, d),
                    "weekend": d.weekday() >= 5,
                    "today": d == today,
                    "future": d > today,
                }
                for d in days
            ],
            "today": fields.Date.to_string(today),
            "rows": list(rows.values()),
            "totals": totals,
            "total": sum(totals.values()),
            "projects": self._ea_ts_chargeable(user),
            "warnings": self._ea_ts_warnings(user, monday, now),
            "overdue": self._ea_ts_overdue(user, now),
            "can_reopen": user._ea_firm_role() in ("firm_admin", "partner"),
        }

    # ------------------------------------------------------------------
    # Charging hours
    # ------------------------------------------------------------------

    @api.model
    def _ea_ts_hours(self, hours):
        try:
            return float(hours)
        except (TypeError, ValueError):
            raise refuse(self.env, "ts-hours-range") from None

    @api.model
    def ea_ts_charge(self, day, project_id, hours, task_id=False, note=""):
        """The entry row: one more line on that day."""
        hours = self._ea_ts_hours(hours)
        if not hours > 0:
            raise refuse(self.env, "ts-hours-range")
        line = self.env["account.analytic.line"].create({
            "date": _day(day),
            "project_id": int(project_id),
            "task_id": int(task_id) if task_id else False,
            "unit_amount": hours,
            "name": (note or "").strip() or "/",
        })
        return line.id

    @api.model
    def ea_ts_set_cell(self, day, project_id, task_id, hours):
        """A cell of the weekly view: the day's hours on that row become this figure."""
        hours = self._ea_ts_hours(hours)
        if not (0 <= hours <= 24):
            raise refuse(self.env, "ts-hours-range")
        Line = self.env["account.analytic.line"]
        lines = Line.search([
            ("user_id", "=", self.env.uid), ("date", "=", _day(day)),
            ("project_id", "=", int(project_id)), ("task_id", "=", int(task_id) if task_id else False),
        ], order="id")
        if not hours:
            lines.unlink()
        elif lines:
            (lines - lines[0]).unlink()
            lines[0].unit_amount = hours
        else:
            self.ea_ts_charge(day, project_id, hours, task_id)
        return True

    @api.model
    def ea_ts_submit(self, day):
        monday = deadlines.week_start(_day(day))
        self.env["ea.audit.timesheet.week"]._ea_ts_submit(self.env.user, monday)
        return True

    @api.model
    def ea_ts_recall(self, day):
        monday = deadlines.week_start(_day(day))
        self.env["ea.audit.timesheet.week"]._ea_ts_recall(self.env.user, monday)
        return True

    @api.model
    def ea_ts_reopen(self, user_id, day, reason):
        person = self.env["res.users"].sudo().browse(int(user_id)).exists()
        if not person:
            raise refuse(self.env, "ts-reopen-forbidden")
        record = self.env["ea.audit.timesheet.reopen"]._ea_ts_reopen(person, deadlines.week_start(_day(day)), reason)
        return {"until": deadlines.instant_label(record.expires_at)}

    # ------------------------------------------------------------------
    # Reports: the search runs under the caller, so the line rules set the reach
    # ------------------------------------------------------------------

    @api.model
    def _ea_ts_report_lines(self, date_from, date_to):
        return self.env["account.analytic.line"].search([
            ("project_id", "!=", False), ("date", ">=", date_from), ("date", "<=", date_to),
        ], order="date desc, id desc").sudo()

    @api.model
    def _ea_ts_group_key(self, line, group_by):
        if group_by == "person":
            return line.user_id.name or ""
        if group_by == "engagement":
            return line.project_id.name or ""
        return labels.week_label(self.env, deadlines.week_start(line.date))

    @api.model
    def _ea_ts_group_rows(self, lines, group_by):
        groups = defaultdict(lambda: {"hours": 0.0, "people": set(), "projects": set(), "first": None})
        for line in lines:
            group = groups[self._ea_ts_group_key(line, group_by)]
            group["hours"] += line.unit_amount
            group["people"].add(line.user_id.id)
            group["projects"].add(line.project_id.id)
            group["first"] = min(group["first"] or line.date, line.date)
        rows = [
            {"label": label, "hours": g["hours"], "people": len(g["people"]), "projects": len(g["projects"]), "first": g["first"]}
            for label, g in groups.items()
        ]
        if group_by == "period":
            rows.sort(key=lambda r: r["first"], reverse=True)
        else:
            rows.sort(key=lambda r: r["label"])
        return rows

    @api.model
    def _ea_ts_reach_label(self):
        user = self.env.user
        if user._ea_firm_role() == "firm_admin":
            return self.env._("The whole firm")
        leads = self.env["ea.audit.team.member"].sudo().search_count([
            ("user_id", "=", user.id), ("state", "=", "accepted"), ("team_role", "in", ["partner", "manager"]),
        ])
        return self.env._("Your hours and those of the engagements you lead") if leads else self.env._("Your hours")

    @api.model
    def ea_ts_report(self, date_from=None, date_to=None, group_by="person"):
        Week = self.env["ea.audit.timesheet.week"]
        today = deadlines.local_today(Week._ea_ts_now())
        first = _day(date_from, date(today.year, today.month, 1))
        last = _day(date_to, today)
        if group_by not in GROUPINGS:
            group_by = "person"
        lines = self._ea_ts_report_lines(first, last)
        rows = self._ea_ts_group_rows(lines, group_by)
        for row in rows:
            row.pop("first")
        result = {
            "date_from": fields.Date.to_string(first),
            "date_to": fields.Date.to_string(last),
            "from_label": deadlines.date_label(first),
            "to_label": deadlines.date_label(last),
            "group_by": group_by,
            "rows": rows,
            "total": sum(r["hours"] for r in rows),
            "reach": self._ea_ts_reach_label(),
            "can_reopen": False,
        }
        role = self.env.user._ea_firm_role()
        if role in ("firm_admin", "partner"):
            result.update(self._ea_ts_reopen_panel())
        return result

    @api.model
    def ea_ts_pivot_action(self, date_from, date_to):
        action = self.env["ir.actions.act_window"]._for_xml_id("ea_audit_timesheet.action_report_pivot")
        action["domain"] = [
            ("project_id", "!=", False), ("date", ">=", _day(date_from)), ("date", "<=", _day(date_to)),
        ]
        return action

    @api.model
    def _ea_ts_reopen_panel(self):
        actor = self.env.user
        Reopen = self.env["ea.audit.timesheet.reopen"]
        people = self.env["res.users"].sudo().search([("share", "=", False), ("id", "!=", actor.id)], order="name")
        people = people.filtered(lambda p: p._ea_firm_role() and Reopen._ea_ts_may_reopen(actor, p))
        now = self.env["ea.audit.timesheet.week"]._ea_ts_now()
        journal = Reopen.search([], limit=10).sudo()
        return {
            "can_reopen": True,
            "people": [{"id": p.id, "name": p.name} for p in people],
            "journal": [
                {
                    "id": r.id,
                    "person": r.user_id.name,
                    "week": labels.week_label(self.env, r.week_start),
                    "by": r.opened_by_id.name,
                    "at": deadlines.instant_label(r.opened_at),
                    "until": deadlines.instant_label(r.expires_at),
                    "reason": r.reason,
                    "state": self.env._("Closed") if r.closed_at else (self.env._("Running") if r.expires_at > now else self.env._("Expired")),
                }
                for r in journal
            ],
        }

    @api.model
    def _ea_ts_export(self, date_from, date_to):
        """The workbook's tabs, under the caller's rights."""
        lines = self._ea_ts_report_lines(date_from, date_to)
        phases = dict(labels.phase_labels(self.env))
        detail = [
            (l.date, l.user_id.name or "", l.project_id.name or "", l.task_id.name or "",
             phases.get(l.ea_phase, ""), "" if l.name == "/" else (l.name or ""), float(l.unit_amount))
            for l in lines
        ]
        group_sheet = []
        for key, title, head in (
            ("person", self.env._("By person"), self.env._("Person")),
            ("engagement", self.env._("By engagement"), self.env._("Engagement or project")),
            ("period", self.env._("By week"), self.env._("Week")),
        ):
            rows = self._ea_ts_group_rows(lines, key)
            group_sheet.append((title, [head, self.env._("Hours")], [(r["label"], float(r["hours"])) for r in rows]))
        return [
            (self.env._("Detail"), [
                self.env._("Date"), self.env._("Person"), self.env._("Engagement or project"), self.env._("Task"),
                self.env._("Phase"), self.env._("Note"), self.env._("Hours"),
            ], detail),
            *group_sheet,
        ]
