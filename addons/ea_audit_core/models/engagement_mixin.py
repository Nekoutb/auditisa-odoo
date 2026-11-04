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
