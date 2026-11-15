"""F008 with the firm administrator's look-only read (owner ruling, 2026-11-15).

The team-only record rules are global, so a group rule cannot widen them. Instead
their domain calls ``ea_team_domain(path)``, which this model puts in the rules'
evaluation context:

- for the firm administrator, and only when the engine computes a READ domain,
  it returns the always-true domain: they see every engagement of the firm and
  everything under it;
- in every other case (any other user, or write / create / unlink for the firm
  administrator too) it returns the usual "accepted member of the team" domain.

The rest of a mixed rule (``deleted_at = False``, ``'|' engagement_id = False``...)
is written next to the call and still applies. The mode is known to
``_compute_domain`` only, so it passes it down in the context; the engine's cache
already keys on the mode, so a read domain never serves a write.
"""
from odoo import api, models
from odoo.exceptions import AccessError

from ..services.errors import rule_error

FIRM_ADMIN_GROUP = "ea_audit_core.group_firm_admin"
_MODE_KEY = "ea_rule_mode"
_TRUE = [(1, "=", 1)]


def team_domain(path, user_id):
    """The F008 domain for the engagement reached through ``path`` ('' = the engagement)."""
    field = "%s.team_member_ids" % path if path else "team_member_ids"
    return [(field, "any", [("user_id", "=", user_id), ("state", "=", "accepted")])]


class IrRule(models.Model):
    _inherit = "ir.rule"

    @api.model
    def _eval_context(self):
        context = super()._eval_context()
        user = self.env.user
        look_all = (
            self.env.context.get(_MODE_KEY) == "read"
            and bool(user) and user.has_group(FIRM_ADMIN_GROUP)
        )
        user_id = user.id

        def ea_team_domain(path=""):
            return list(_TRUE) if look_all else team_domain(path, user_id)

        context["ea_team_domain"] = ea_team_domain
        return context

    @api.model
    def _compute_domain(self, model_name, mode="read"):
        if self.env.context.get(_MODE_KEY) != mode:
            self = self.with_context(**{_MODE_KEY: mode})  # noqa: PLW0642
        return super()._compute_domain(model_name, mode)

    def _get_failing(self, for_records, mode="read"):
        if self.env.context.get(_MODE_KEY) != mode:
            self = self.with_context(**{_MODE_KEY: mode})  # noqa: PLW0642
        return super()._get_failing(for_records, mode=mode)

    def _make_access_error(self, operation, records):
        """A firm administrator who is not on the team gets a plain sentence, not
        Odoo's technical list of rules, when they try to change a file they look at."""
        user = self.env.user
        if operation != "read" and not self.env.su and user.has_group(FIRM_ADMIN_GROUP):
            failing = self._get_failing(records, mode=operation).sudo()
            if any("ea_team_domain" in (rule.domain_force or "") for rule in failing):
                return AccessError(rule_error(self.env, "look-only").args[0])
        return super()._make_access_error(operation, records)
