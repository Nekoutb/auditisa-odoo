from odoo import api, fields, models

from ..services import bespoke_codes, default_definition, digest, load_definition


class PaperDefinition(models.Model):
    """A paper's text as a task code carries it, unresolved. Read-only for every group:
    a load changes the text by adding a row and retiring the old one, so a signed paper
    can still show what it was signed on (Q1)."""

    _name = "ea.audit.paper.def"
    _description = "Working paper definition"
    _order = "code, id desc"
    _rec_name = "code"

    code = fields.Char(required=True, index=True, readonly=True)
    definition = fields.Json(required=True, readonly=True)
    definition_hash = fields.Char(required=True, index=True, readonly=True)
    is_current = fields.Boolean(default=True, readonly=True)
    is_default = fields.Boolean(string="Group default", readonly=True, help="The task has no paper of its own.")

    # Not unique on the hash alone as DESIGN has it: some codes share one text, and every
    # task on the same group default does.
    _code_hash_uniq = models.Constraint("UNIQUE(code, definition_hash)", "This text is already loaded for this code.")
    _current_uniq = models.UniqueIndex("(code) WHERE is_current", "A code has one current definition.")

    @api.model
    def _ea_load_definitions(self):
        """Install and upgrade. Task codes without a bespoke text load their group default,
        so that every paper has a row to pin a signature to."""
        templates = self.env["ea.audit.task.template"].sudo().search([]).mapped("code")
        wanted = {code: (load_definition(code), False) for code in bespoke_codes()}
        for code in templates:
            wanted.setdefault(code, (default_definition(code), True))
        for code, (definition, is_default) in wanted.items():
            self._ea_load_one(code, definition, is_default)

    def _ea_load_one(self, code, definition, is_default=False):
        hashed = digest(definition)
        Def = self.sudo()
        current = Def.search([("code", "=", code), ("is_current", "=", True)], limit=1)
        if current.definition_hash == hashed:
            return current
        current.is_current = False
        self.env.flush_all()
        known = Def.search([("code", "=", code), ("definition_hash", "=", hashed)], limit=1)
        if known:
            known.is_current = True
            return known
        return Def.create({
            "code": code, "definition": definition, "definition_hash": hashed,
            "is_current": True, "is_default": is_default,
        })

    @api.model
    def _ea_current(self, code):
        return self.sudo().search([("code", "=", code), ("is_current", "=", True)], limit=1)
