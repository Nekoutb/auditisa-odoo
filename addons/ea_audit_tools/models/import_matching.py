"""The matching of an import: the fields a kind of file offers, the matching a client's files are
remembered by, and what the import wizard asks of the engagement (read, check, import)."""
from odoo import api, fields, models

from ..rules import rule_error
from ..services.import_matching import (
    IMPORT_KINDS, SKIP_LABEL, TB_KIND, amount_columns, analysis_keys, date_columns, detect_mapping, fields_of,
    found_date_format, found_decimal, remember_payload, starred_keys,
)
from ..services.dataset_mapping import ANALYSIS_HINT
from ..tabular import found_delimiter, sheet_names
from .dataset import KIND_SELECTION
from .tool_record import is_french

IMPORT_KIND_SELECTION = [(TB_KIND, "Trial balance")] + KIND_SELECTION
assert [kind for kind, _label in IMPORT_KIND_SELECTION] == IMPORT_KINDS

#: The key of the choice that leaves a column out. No field of a file is called so.
SKIP_KEY = "-"


class ImportField(models.Model):
    """One choice of the matching screen: a field of a kind of file, or "Do not import".
    Reference data, no engagement: written from the services' catalogue each time the addon
    loads, never by a person."""

    _name = "ea.audit.import.field"
    _description = "Field of an imported file"
    _order = "kind, sequence, id"
    _rec_name = "label_en"

    kind = fields.Selection(IMPORT_KIND_SELECTION, required=True, index=True, readonly=True)
    key = fields.Char(required=True, readonly=True)
    sequence = fields.Integer(default=10, readonly=True)
    label_en = fields.Char(required=True, readonly=True)
    label_fr = fields.Char(required=True, readonly=True)
    starred = fields.Boolean(readonly=True)
    skip = fields.Boolean(readonly=True)
    #: an optional column the analysis uses: marked "Improves the analysis" (owner, 2026-11-17)
    improves_analysis = fields.Boolean(string="Improves the analysis", readonly=True)

    _kind_key_uniq = models.Constraint("UNIQUE(kind, key)", "A field is listed once for a kind of file.")

    @api.depends("label_en", "label_fr", "starred", "improves_analysis")
    @api.depends_context("lang")
    def _compute_display_name(self):
        french = is_french(self.env)
        hint = ANALYSIS_HINT["fr" if french else "en"]
        for field in self:
            label = field.label_fr if french else field.label_en
            if field.starred:
                label = "%s *" % label
            elif field.improves_analysis:
                label = "%s (%s)" % (label, hint)
            field.display_name = label

    def init(self):
        """The catalogue of the services, as rows a dropdown can list."""
        cr = self.env.cr
        wanted = {}
        for kind in IMPORT_KINDS:
            starred, hinted = starred_keys(kind), set(analysis_keys(kind))
            wanted[(kind, SKIP_KEY)] = (0, SKIP_LABEL["en"], SKIP_LABEL["fr"], False, True, False)
            for position, field in enumerate(fields_of(kind), start=1):
                key = field["key"]
                wanted[(kind, key)] = (position, field["en"], field["fr"], key in starred, False, key in hinted)
        cr.execute("SELECT id, kind, key FROM ea_audit_import_field")
        known = {(kind, key): record_id for record_id, kind, key in cr.fetchall()}
        for (kind, key), values in wanted.items():
            values = list(values)
            if (kind, key) in known:
                cr.execute(
                    """UPDATE ea_audit_import_field SET sequence = %s, label_en = %s, label_fr = %s, starred = %s, skip = %s,
                              improves_analysis = %s, write_date = now() at time zone 'UTC' WHERE id = %s""",
                    values + [known[(kind, key)]],
                )
            else:
                cr.execute(
                    """INSERT INTO ea_audit_import_field (kind, key, sequence, label_en, label_fr, starred, skip, improves_analysis,
                                                         create_date, write_date)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now() at time zone 'UTC', now() at time zone 'UTC')""",
                    [kind, key] + values,
                )
        gone = [record_id for pair, record_id in known.items() if pair not in wanted]
        if gone:
            cr.execute("DELETE FROM ea_audit_import_field WHERE id = ANY(%s)", [gone])
        self.invalidate_model()

    @api.model
    def _ea_of(self, kind, key=SKIP_KEY):
        return self.sudo().search([("kind", "=", kind), ("key", "=", key or SKIP_KEY)], limit=1)


class ImportMatching(models.Model):
    """"Remember this matching": how a client's last file of a kind was matched, proposed again
    for the next one. Client-scoped, as the client's mapping overrides: read by a member of one
    of the client's teams, written only by the import."""

    _name = "ea.audit.import.matching"
    _description = "Remembered matching of a client's file"
    _rec_name = "kind"

    client_id = fields.Many2one("ea.audit.client", required=True, index=True, ondelete="cascade")
    kind = fields.Selection(IMPORT_KIND_SELECTION, required=True)
    matching = fields.Json()

    _client_kind_uniq = models.Constraint("UNIQUE(client_id, kind)", "A client has one remembered matching per kind of file.")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            raise rule_error(self.env, "forbidden")
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            raise rule_error(self.env, "forbidden")
        return super().write(vals)

    def unlink(self):
        if not self.env.su:
            raise rule_error(self.env, "forbidden")
        return super().unlink()


class EngagementImport(models.Model):
    _inherit = "ea.audit.engagement"

    def _ea_remembered_matching(self, kind):
        self.ensure_one()
        found = self.env["ea.audit.import.matching"].sudo().search([
            ("client_id", "=", self.sudo().client_id.id), ("kind", "=", kind),
        ], limit=1)
        return found.matching or None

    def _ea_remember_matching(self, kind, headers, mapping):
        """Kept at the import, never before: a matching that was only tried is not remembered."""
        self.ensure_one()
        Matching = self.env["ea.audit.import.matching"].sudo()
        client = self.sudo().client_id
        payload = remember_payload(headers, mapping)
        found = Matching.search([("client_id", "=", client.id), ("kind", "=", kind)], limit=1)
        if found:
            found.matching = payload
        else:
            Matching.create({"client_id": client.id, "kind": kind, "matching": payload})

    def ea_import_read(self, kind, filename, content, header_row=True, options=None):
        """The file opened for the matching screen: its columns with their first values, and the
        matching proposed. Writes nothing."""
        self.ensure_one()
        self._ea_tool_guard()
        if kind not in IMPORT_KINDS:
            raise rule_error(self.env, "fields-required")
        table = self._ea_parse(filename, content, header_row, options)
        mapping, sources = detect_mapping(kind, table, self._ea_remembered_matching(kind))
        headers = list(dict.fromkeys(table["headers"]))
        samples = {}
        for header in headers:
            values = []
            for row in table["rows"]:
                value = str(row.get(header) or "").strip()
                if value:
                    values.append(value)
                if len(values) >= 3:
                    break
            samples[header] = values
        return {
            "headers": headers, "headerSamples": samples, "rowCount": len(table["rows"]),
            "mapping": mapping, "sources": sources, "sheets": sheet_names(filename, content),
            "found": {
                "delimiter": found_delimiter(filename, content),
                "decimal": found_decimal(table, amount_columns(kind, mapping)),
                "date": found_date_format(table, date_columns(kind, mapping)),
            },
        }

    def ea_import_check(self, kind, filename, content, mapping, header_row=True, options=None, timing=None):
        """The check screen: what the import would keep and what it would say, nothing kept.
        Refuses, as the import does, a matching that leaves a mandatory field out."""
        self.ensure_one()
        self._ea_tool_guard()
        if kind not in IMPORT_KINDS:
            raise rule_error(self.env, "fields-required")
        if kind == TB_KIND:
            return self._ea_tb_check(filename, content, mapping, header_row, options)
        return self._ea_dataset_check(kind, filename, content, mapping, header_row, options, timing=timing)

    def ea_import_file(self, kind, filename, content, mapping, timing="pre_audit", header_row=True, options=None, remember=False):
        """The import of any of the nine kinds, each by its own rule-bearing method."""
        self.ensure_one()
        if kind == TB_KIND:
            return self.import_trial_balance(
                filename, content, mapping=mapping, timing=timing, header_row=header_row, options=options, remember=remember,
            )
        return self.create_dataset(
            kind, filename, content, mapping=mapping, timing=timing, header_row=header_row, options=options, remember=remember,
        )

    def _ea_import_replaced(self, kind, timing):
        """The upload a new one of this kind and timing would supersede: a trial balance version
        or a dataset. Empty when there is none."""
        self.ensure_one()
        if kind == TB_KIND:
            return self.env["ea.audit.tb.version"].sudo().search([
                ("engagement_id", "=", self.id), ("timing", "=", timing), ("superseded_at", "=", False),
                ("validation_status", "=", "valid"),
            ], order="version_no desc", limit=1)
        return self._ea_current_dataset(kind, timing)
