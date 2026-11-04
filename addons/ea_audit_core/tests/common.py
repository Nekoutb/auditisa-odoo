from datetime import date

from odoo.tests import TransactionCase

from odoo.addons.ea_audit_core.services.errors import AuditRuleError


class EaAuditCase(TransactionCase):
    """The fixture of the vitest files: one firm, one user per firm role. In the
    port a firm is the test database itself."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Engagement = cls.env["ea.audit.engagement"]
        cls.Team = cls.env["ea.audit.team.member"].sudo()
        cls.Policy = cls.env["ea.audit.signoff.policy"]
        cls.TaskRule = cls.env["ea.audit.signoff.task.rule"]
        cls.admin = cls._user("admin", "group_firm_admin")
        cls.partner = cls._user("partner", "group_partner")
        cls.partner2 = cls._user("partner2", "group_partner")
        cls.partner3 = cls._user("partner3", "group_partner")
        cls.partner4 = cls._user("partner4", "group_partner")
        cls.manager = cls._user("manager", "group_manager")
        cls.senior = cls._user("senior", "group_senior")
        cls.staff = cls._user("staff", "group_staff")
        cls.outsider = cls._user("outsider", "group_staff")
        cls.eqr = cls._user("eqrf", "group_eqr_reviewer")
        cls.reader = cls._user("reader", "group_read_only")
        cls.client = cls.env["ea.audit.client"].create({"name": "Governance SA", "legal_form": "SA"})

    @classmethod
    def _user(cls, login, group):
        return cls.env["res.users"].with_context(no_reset_password=True).create({
            "name": login.title(),
            "login": "%s@gov.example.com" % login,
            "email": "%s@gov.example.com" % login,
            "group_ids": [(6, 0, [cls.env.ref("ea_audit_core.%s" % group).id])],
        })

    def assertCode(self, code, func, *args, **kwargs):
        with self.assertRaises(AuditRuleError) as caught:
            func(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def attempt(self, func, *args, **kwargs):
        """The vitest helper: the refusal code, or "ok". A savepoint undoes the
        attempt's partial writes, as the refused transaction does today."""
        try:
            with self.cr.savepoint():
                func(*args, **kwargs)
        except AuditRuleError as error:
            return error.code
        return "ok"

    def make_engagement(self, year=2025, partner=None, actor=None, client=None, **vals):
        actor = actor or partner or self.partner
        return self.Engagement.with_user(actor).create({
            "client_id": (client or self.client).id,
            "fiscal_year": year,
            "period_end": date(year, 12, 31),
            "engagement_partner_id": (partner or self.partner).id,
            **vals,
        })

    def vacate_team(self, engagement):
        """A file opened before the partner became mandatory: the seat is empty."""
        self.env.flush_all()
        self.cr.execute("DELETE FROM ea_audit_team_member WHERE engagement_id = %s", [engagement.id])
        self.env.invalidate_all()

    def seat(self, engagement, user, role, state="accepted"):
        return self.Team.create({
            "engagement_id": engagement.id, "user_id": user.id, "team_role": role, "state": state,
        })

    def item(self, engagement, code):
        return self.env["ea.audit.file.item"].sudo().search(
            [("engagement_id", "=", engagement.id), ("code", "=", code)], limit=1,
        )

    def set_phase(self, engagement, phase):
        engagement.sudo().phase = phase

    def outputs_exist(self):
        """The TB, materiality and SAD tools live in a later addon."""
        self.patch(type(self.env["ea.audit.file.item"]), "_ea_tool_output_present", lambda _self, _output: True)

    def sign(self, user, engagement, code, role):
        return self.item(engagement, code).with_user(user).action_sign(role)

    def gate(self, engagement, key):
        return next(g["ok"] for g in engagement.sudo()._ea_acceptance_gates() if g["key"] == key)
