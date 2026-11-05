from odoo import api, fields, models

from .errors import paper_error

ANSWER_DOOR = "ea_audit_answer_door"


class PaperAnswer(models.Model):
    """One answer per key of a paper. Written only through ea.audit.paper.save_answers
    and the named carry-forward method, which set the door flag: sudo alone is refused."""

    _name = "ea.audit.paper.answer"
    _description = "Working paper answer"
    _order = "paper_id, field_key"
    _rec_name = "field_key"

    paper_id = fields.Many2one("ea.audit.paper", required=True, index=True, ondelete="cascade")
    engagement_id = fields.Many2one(related="paper_id.engagement_id", store=True, index=True)
    code = fields.Char(related="paper_id.code", store=True, index=True)
    field_key = fields.Char(required=True)
    value = fields.Text()
    carried_forward = fields.Boolean(help="Written by roll-forward: such a write leaves no history.")

    _paper_key_uniq = models.Constraint("UNIQUE(paper_id, field_key)", "A paper holds one answer per key.")

    def _ea_door(self):
        if not self.env.context.get(ANSWER_DOOR):
            raise paper_error(self.env, "forbidden")

    @api.model_create_multi
    def create(self, vals_list):
        self._ea_door()
        return super().create(vals_list)

    def write(self, vals):
        self._ea_door()
        return super().write(vals)

    def unlink(self):
        self._ea_door()
        return super().unlink()


class PaperAnswerHistory(models.Model):
    """Append-only (F027): every change of an answer, one row per field per save."""

    _name = "ea.audit.paper.answer.history"
    _description = "Working paper answer history"
    _order = "changed_at desc, id desc"
    _rec_name = "field_key"

    paper_id = fields.Many2one("ea.audit.paper", required=True, index=True, ondelete="restrict", readonly=True)
    engagement_id = fields.Many2one(related="paper_id.engagement_id", store=True, index=True)
    code = fields.Char(related="paper_id.code", store=True)
    field_key = fields.Char(required=True, readonly=True)
    before = fields.Text(readonly=True)
    after = fields.Text(readonly=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="restrict", readonly=True)
    changed_at = fields.Datetime(required=True, default=fields.Datetime.now, readonly=True)

    def write(self, vals):
        raise paper_error(self.env, "forbidden")

    def unlink(self):
        raise paper_error(self.env, "forbidden")
