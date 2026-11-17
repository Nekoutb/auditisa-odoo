from odoo import api, fields, models


class Signoff(models.Model):
    """What a signature attests to (DESIGN section 5). core's action_sign stores the hash;
    the scheme and the text it was given over are added here as the row is created."""

    _inherit = "ea.audit.signoff"

    content_scheme = fields.Integer(
        default=2,
        help="1: a migrated hash Odoo cannot recompute, reported rather than voided. 2: Odoo's own.",
    )
    definition_hash = fields.Char(help="The paper text this signature was given over.")
    invalidated_reason = fields.Char()

    @api.model_create_multi
    def create(self, vals_list):
        Item = self.env["ea.audit.file.item"].sudo()
        Def = self.env["ea.audit.paper.def"]
        for vals in vals_list:
            if "definition_hash" not in vals and vals.get("file_item_id"):
                vals["definition_hash"] = Def._ea_current(Item.browse(vals["file_item_id"]).code).definition_hash
        return super().create(vals_list)
