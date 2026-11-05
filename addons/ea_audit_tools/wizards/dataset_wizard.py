import base64

from markupsafe import Markup

from odoo import api, fields, models

from ..models.dataset import KIND_SELECTION
from ..models.tb import TIMING_SELECTION
from ..services.dataset_mapping import FIELDS, JE_KEY, JE_KEY_SEP, encode_je_key
from .tool_wizard_helpers import is_french_env

_RELOAD = {"type": "ir.actions.client", "tag": "soft_reload"}


class DatasetImportWizard(models.TransientModel):
    """File, then header and column mapping, then ingest (DatasetAnalyzer). The preview writes nothing."""

    _name = "ea.audit.dataset.import.wizard"
    _description = "Import a dataset"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    kind = fields.Selection(KIND_SELECTION, required=True, default="journal_entries")
    file = fields.Binary(string="File (.csv, .xlsx)", required=True)
    filename = fields.Char()
    timing = fields.Selection(TIMING_SELECTION, default="pre_audit", required=True)
    header_row = fields.Boolean(string="First line is a header", default=True)
    step = fields.Selection([("upload", "Upload"), ("confirm", "Confirm")], default="upload")
    preview_html = fields.Html(sanitize=False, readonly=True)
    map_ids = fields.One2many("ea.audit.dataset.import.map", "wizard_id", string="Column mapping")
    je_key_columns = fields.Char(
        string="Entry identified by several columns",
        help="Optional, for a ledger whose entry is identified by several columns (for instance journal, voucher): headers separated by commas.",
    )

    def _content(self):
        return base64.b64decode(self.file or b"")

    def action_preview(self):
        self.ensure_one()
        preview = self.engagement_id.preview_dataset_file(self.kind, self.filename, self._content(), self.header_row)
        french = is_french_env(self.env)
        lines = [(5, 0, 0)]
        for sequence, field in enumerate(FIELDS[self.kind]):
            header = preview["mapping"].get(field["key"]) or False
            lines.append((0, 0, {
                "sequence": sequence, "field_key": field["key"], "label": field["fr" if french else "en"],
                "required_column": bool(field.get("required")), "header": header,
                "sample": ", ".join(preview["headerSamples"].get(header, [])) if header else False,
            }))
        rows = Markup("").join(
            Markup("<tr><td>{h}</td><td>{s}</td></tr>").format(h=header, s=", ".join(preview["headerSamples"][header]))
            for header in preview["headers"]
        )
        self.write({
            "step": "confirm", "map_ids": lines,
            "preview_html": Markup(
                "<p>{count}</p><table class='table table-sm o_ea_table'><thead><tr><th>{column}</th><th>{sample}</th></tr></thead><tbody>{rows}</tbody></table>"
            ).format(
                count=self.env._("%(count)s rows read", count=preview["rowCount"]),
                column=self.env._("Column"), sample=self.env._("Sample"), rows=rows,
            ),
        })
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
            "view_mode": "form", "target": "new", "name": self.env._("Confirm the column mapping"),
        }

    def _mapping(self):
        mapping = {line.field_key: line.header.strip() for line in self.map_ids if (line.header or "").strip()}
        columns = [part.strip() for part in (self.je_key_columns or "").split(",") if part.strip()]
        if columns:
            mapping[JE_KEY] = encode_je_key(columns)
        return mapping

    def action_import(self):
        self.ensure_one()
        self.engagement_id.create_dataset(
            self.kind, self.filename, self._content(), mapping=self._mapping(), timing=self.timing, header_row=self.header_row,
        )
        return _RELOAD


class DatasetImportMap(models.TransientModel):
    _name = "ea.audit.dataset.import.map"
    _description = "Column of a dataset import"
    _order = "sequence"

    wizard_id = fields.Many2one("ea.audit.dataset.import.wizard", required=True, ondelete="cascade")
    sequence = fields.Integer()
    field_key = fields.Char(readonly=True)
    label = fields.Char(string="Field", readonly=True)
    required_column = fields.Boolean(string="Required", readonly=True)
    header = fields.Char(string="Column of the file")
    sample = fields.Char(readonly=True)
