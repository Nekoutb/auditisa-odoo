from odoo import api, models

from ..services.errors import rule_error

# Highest first: firm_admin implies partner implies manager implies senior implies staff.
_LADDER_GROUPS = (
    ("firm_admin", "ea_audit_core.group_firm_admin"),
    ("partner", "ea_audit_core.group_partner"),
    ("manager", "ea_audit_core.group_manager"),
    ("senior", "ea_audit_core.group_senior"),
    ("staff", "ea_audit_core.group_staff"),
)
_APART_GROUPS = (
    ("eqr_reviewer", "ea_audit_core.group_eqr_reviewer"),
    ("read_only", "ea_audit_core.group_read_only"),
)


class ResUsers(models.Model):
    _inherit = "res.users"

    def _ea_firm_role(self):
        """The firm role (membership.role of the current application), False
        when the user is not a member of the firm."""
        self.ensure_one()
        user = self.sudo()
        for role, xmlid in _LADDER_GROUPS + _APART_GROUPS:
            if user.has_group(xmlid):
                return role
        return False

    @api.constrains("group_ids")
    def _check_ea_single_firm_role(self):
        """A person holds one firm role, as membership.role does today."""
        staff = self.env.ref("ea_audit_core.group_staff", raise_if_not_found=False)
        apart_groups = [self.env.ref(x, raise_if_not_found=False) for _r, x in _APART_GROUPS]
        for user in self.sudo():
            held = user.all_group_ids
            apart = [g for g in apart_groups if g and g in held]
            if len(apart) > 1 or (apart and staff and staff in held):
                raise rule_error(self.env, "firm-role-conflict")
