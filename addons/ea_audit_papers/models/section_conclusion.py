from odoo import api, fields, models


class SectionConclusion(models.Model):
    """The conclusion of an execution task (lib/execution.ts). The rules live on the file
    item, where the task's other acts are; the rows are written through them only."""

    _name = "ea.audit.section.conclusion"
    _description = "Section conclusion"
    _rec_name = "file_item_id"

    file_item_id = fields.Many2one("ea.audit.file.item", string="Task", required=True, index=True, ondelete="cascade")
    engagement_id = fields.Many2one(related="file_item_id.engagement_id", store=True, index=True)
    code = fields.Char(related="file_item_id.code", store=True)
    conclusion = fields.Text(required=True)
    objectives_achieved = fields.Boolean()
    no_procedures_rationale = fields.Text()
    prepared_by_id = fields.Many2one("res.users", ondelete="restrict")
    prepared_at = fields.Datetime()
    reviewed_by_id = fields.Many2one("res.users", ondelete="restrict")
    reviewed_at = fields.Datetime()
    partner_reviewed_by_id = fields.Many2one("res.users", ondelete="restrict")
    partner_reviewed_at = fields.Datetime()

    _file_item_uniq = models.Constraint("UNIQUE(file_item_id)", "A task has one section conclusion.")

    @api.model
    def _ea_clear_reviews(self, item):
        row = self.sudo().search([("file_item_id", "=", item.id)], limit=1)
        if not row or not (row.reviewed_by_id or row.partner_reviewed_by_id):
            return False
        row.write({
            "reviewed_by_id": False, "reviewed_at": False,
            "partner_reviewed_by_id": False, "partner_reviewed_at": False,
        })
        return True

    @api.model
    def _ea_payload(self, item):
        if item.section != "E":
            return False
        row = self.sudo().search([("file_item_id", "=", item.id)], limit=1)
        return {
            "conclusion": row.conclusion or "",
            "objectives_achieved": row.objectives_achieved,
            "no_procedures_rationale": row.no_procedures_rationale or "",
            "prepared_by": row.prepared_by_id.name or "",
            "reviewed_by": row.reviewed_by_id.name or "",
            "partner_reviewed_by": row.partner_reviewed_by_id.name or "",
            "exists": bool(row),
        }
