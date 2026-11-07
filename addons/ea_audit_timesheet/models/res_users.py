from odoo import models

# ea_audit_firm_agent's support account (models/support.py SUPPORT_LOGIN), named here so that
# this addon does not depend on the agent.
SUPPORT_VISIT_LOGIN = "auditisa-support"


class ResUsers(models.Model):
    _inherit = "res.users"

    def _ea_ts_ensure_employee(self):
        """hr_timesheet books a line on an employee: a firm member has one, unasked."""
        Employee = self.env["hr.employee"].sudo()
        for user in self.sudo():
            company = user.company_id
            found = Employee.search([("user_id", "=", user.id), ("company_id", "=", company.id)], limit=1)
            if not found:
                Employee.with_context(tracking_disable=True, mail_create_nosubscribe=True, mail_create_nolog=True).create({
                    "name": user.name, "user_id": user.id, "company_id": company.id, "work_email": user.email,
                })

    def _update_last_login(self):
        result = super()._update_last_login()
        # Support's use of a firm is the firm's to read. The read-only support account of a visit
        # (ea_audit_firm_agent) writes nothing here: its visit keeps its own numbered record and trail.
        if self.has_group("base.group_system") and self.login != SUPPORT_VISIT_LOGIN:
            self.env["ea.audit.firm.log"]._ea_append("support_login", actor=self)
        return result
