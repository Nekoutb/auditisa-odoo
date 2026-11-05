import base64

from odoo import fields, models

_RELOAD = {"type": "ir.actions.client", "tag": "soft_reload"}


class PbcWizard(models.TransientModel):
    _name = "ea.audit.pbc.wizard"
    _description = "Request a document"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    title = fields.Char(required=True)
    note = fields.Text()

    def action_add(self):
        self.ensure_one()
        self.engagement_id.add_pbc_item(self.title, self.note or "")
        return _RELOAD


class PbcUploadWizard(models.TransientModel):
    _name = "ea.audit.pbc.upload.wizard"
    _description = "Record a document received"

    item_id = fields.Many2one("ea.audit.pbc.item", required=True)
    file = fields.Binary(required=True)
    filename = fields.Char()

    def action_upload(self):
        self.ensure_one()
        self.item_id.upload_pbc(self.filename, base64.b64decode(self.file or b""))
        return _RELOAD


class PbcAcceptWizard(models.TransientModel):
    _name = "ea.audit.pbc.accept.wizard"
    _description = "File an upload"

    item_id = fields.Many2one("ea.audit.pbc.item", required=True)
    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    file_item_id = fields.Many2one("ea.audit.file.item", string="Task", required=True, domain="[('engagement_id', '=', engagement_id)]")

    def action_file(self):
        self.ensure_one()
        if self.item_id.sudo().status == "accepted":
            self.item_id.attach_accepted(self.file_item_id)
        else:
            self.item_id.accept(self.file_item_id)
        return _RELOAD


class OverrideWizard(models.TransientModel):
    """The two overrides a client can carry: which index an account feeds, which section it belongs to."""

    _name = "ea.audit.override.wizard"
    _description = "Add an override"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    kind = fields.Selection([("index", "Lead index"), ("section", "Section")], default="index", required=True)
    account_prefix = fields.Char(string="Account prefix", required=True)
    index_code = fields.Selection(lambda self: self.env["ea.audit.tool.record"]._lead_index_selection(), string="Lead index")
    match_type = fields.Selection([("prefix", "Prefix"), ("exact", "Exact")], default="prefix")
    section_code = fields.Char(string="Section")
    rationale = fields.Char()

    def action_add(self):
        self.ensure_one()
        if self.kind == "index":
            self.engagement_id.save_lead_index_override(self.account_prefix, self.index_code)
        else:
            self.engagement_id.add_grouping_override(self.match_type, self.account_prefix, self.section_code, self.rationale)
        return _RELOAD


class PotentialWizard(models.TransientModel):
    _name = "ea.audit.potential.wizard"
    _description = "Raise a potential risk"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    description = fields.Text(required=True)
    source_code = fields.Char(string="Raised from", required=True, default="P3.2")

    def action_raise(self):
        self.ensure_one()
        self.engagement_id.raise_potential_risk(self.description, self.source_code)
        return _RELOAD


class WpAssignWizard(models.TransientModel):
    _name = "ea.audit.wp.assign.wizard"
    _description = "Assign a template to a task"

    template_id = fields.Many2one("ea.audit.wp.template", required=True)
    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    file_item_id = fields.Many2one("ea.audit.file.item", string="Task", required=True, domain="[('engagement_id', '=', engagement_id)]")

    def action_assign(self):
        self.ensure_one()
        self.engagement_id.assign_template(self.template_id, self.file_item_id)
        return _RELOAD
