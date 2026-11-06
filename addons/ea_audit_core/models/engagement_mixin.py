from odoo import fields, models


class EngagementMixin(models.AbstractModel):
    """What every engagement-scoped model inherits. Each such model also carries
    the two lines of security/ea_audit_rules.xml: the team-only rule is global,
    with no exception for any firm role."""

    _name = "ea.audit.engagement.mixin"
    _description = "Engagement-scoped record"

    engagement_id = fields.Many2one(
        "ea.audit.engagement", string="Engagement", required=True, index=True, ondelete="cascade",
    )


class Base(models.AbstractModel):
    _inherit = "base"

    def _compute_display_name(self):
        """A record of ours with no name field reads as what it is, not as "ea.audit.je.studio,5"."""
        if self._rec_name or not self._name.startswith("ea."):
            return super()._compute_display_name()
        label = self.env["ir.model"].sudo()._get(self._name).name
        for record in self:
            record.display_name = label
