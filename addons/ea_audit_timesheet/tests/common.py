from datetime import date, datetime

from odoo.addons.ea_audit_core.tests.common import EaAuditCase

# The week under test, and the instants that decide it, as naive UTC. Douala is UTC+1.
MONDAY = date(2026, 11, 2)
TUESDAY = date(2026, 11, 3)
SUNDAY = date(2026, 11, 8)
NEXT_MONDAY = date(2026, 11, 9)
IN_THE_WEEK = datetime(2026, 11, 4, 9, 0)  # Wednesday of the week itself
AT_NEXT_MONDAY = datetime(2026, 11, 9, 7, 0)  # Monday 08:00, Douala
AT_DEADLINE_LAST_MINUTE = datetime(2026, 11, 10, 22, 59)  # Tuesday 23:59, Douala
AT_LOCK = datetime(2026, 11, 10, 23, 0)  # Wednesday 00:00, Douala


class TimesheetCase(EaAuditCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Line = cls.env["account.analytic.line"]
        cls.Week = cls.env["ea.audit.timesheet.week"]
        cls.Sheet = cls.env["ea.audit.timesheet.sheet"]
        cls.Reopen = cls.env["ea.audit.timesheet.reopen"]
        cls.Project = cls.env["project.project"].sudo()
        cls.Log = cls.env["ea.audit.firm.log"].sudo()
        cls.FirmAdmin = cls.env["ea.audit.firm.admin"]
        cls.internal = cls.Project._ea_ts_create_internal("Formation test")
        cls.other_user_project = cls.Project.create({"name": "Projet Odoo ordinaire", "allow_timesheets": True})

    def setUp(self):
        super().setUp()
        self.engagement = self.make_engagement(2025, partner=self.partner, nature="statutory_audit")
        self.seat(self.engagement, self.manager, "manager")
        self.seat(self.engagement, self.senior, "senior")
        self.seat(self.engagement, self.staff, "staff")
        self.project = self.engagement._ea_ts_project()
        self.at(IN_THE_WEEK)

    def at(self, instant):
        self.patch(type(self.env["ea.audit.timesheet.week"]), "_ea_ts_now", lambda _self: instant)

    def charge(self, user, day=TUESDAY, hours=2.0, project=None, **vals):
        return self.Line.with_user(user).create({
            "date": day,
            "project_id": (project or self.project).id,
            "unit_amount": hours,
            "name": "/",
            **vals,
        })

    def sheet(self, user):
        return self.Sheet.with_user(user)
