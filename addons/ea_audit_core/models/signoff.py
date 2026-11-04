from odoo import fields, models


class Signoff(models.Model):
    """A signature on a task's paper. No group may create, change or delete one
    through the ORM (see the ACLs): file_item.action_sign is the only way in.

    The paper addon adds document_id; until then a signature hangs on the file
    item and its kind, which is what the gates read."""

    _name = "ea.audit.signoff"
    _description = "Sign-off"
    _order = "signed_at, id"

    file_item_id = fields.Many2one(
        "ea.audit.file.item", string="Task", required=True, index=True, ondelete="cascade",
    )
    engagement_id = fields.Many2one(
        "ea.audit.engagement", related="file_item_id.engagement_id", store=True, index=True,
    )
    code = fields.Char(related="file_item_id.code", store=True, index=True)
    kind = fields.Selection([("workpaper", "Working paper"), ("letter", "Letter")], required=True, default="workpaper")
    role = fields.Selection(
        [("preparer", "Preparer"), ("reviewer", "Reviewer"), ("partner", "Partner"), ("eqr", "EQR")], required=True,
    )
    user_id = fields.Many2one("res.users", string="Signed by", required=True, ondelete="restrict")
    version_no = fields.Integer(string="Version", default=0)
    content_hash = fields.Char()
    signed_at = fields.Datetime(default=fields.Datetime.now, required=True)
    voided_at = fields.Datetime()
    voided_by_id = fields.Many2one("res.users", string="Voided by", ondelete="restrict")
    void_reason = fields.Char()
    invalidated_at = fields.Datetime()

    # one active signature per tier: the database closes the double-submit race
    _active_tier_uniq = models.UniqueIndex(
        "(file_item_id, kind, role) WHERE voided_at IS NULL AND invalidated_at IS NULL",
        "This paper already carries that signature.",
    )
