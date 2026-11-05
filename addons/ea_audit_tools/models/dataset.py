import hashlib
import json

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import api, fields, models

from ..rules import rule_error
from ..services.amount import parse_amount
from ..services.dataset_mapping import auto_map
from ..services.errors import ServiceError
from ..services.gl_line import BATCH, TOLERANCE, mapped_fields, population_checks, projector
from ..services.subledger_kinds import SUB_LEDGER_KINDS, is_sub_ledger_kind
from ..services.subledgers import detect_amount_column
from ..tabular import parse_table
from .tool_record import french_date, is_french
from .tb import TIMING_SELECTION

MAX_BYTES = 60 * 1024 * 1024
INGEST_BATCH = 5000

KIND_SELECTION = [
    ("ar_open_items", "Receivables"),
    ("ap_open_items", "Payables"),
    ("fixed_asset_register", "Fixed assets"),
    ("inventory_listing", "Inventory"),
    ("payroll_register", "Payroll"),
    ("bank_statement", "Bank statements"),
    ("journal_entries", "General ledger"),
    ("supplier_statements", "Supplier statements"),
]
assert [kind for kind, _label in KIND_SELECTION] == SUB_LEDGER_KINDS


class Dataset(models.Model):
    """sub_ledger_dataset. One per kind and timing: a new upload replaces the previous one,
    its rows and its projection going with it."""

    _name = "ea.audit.dataset"
    _inherit = ["ea.audit.tool.record"]
    _description = "Imported dataset"
    _order = "create_date desc, id desc"

    kind = fields.Selection(KIND_SELECTION, required=True, index=True)
    timing = fields.Selection(TIMING_SELECTION, default="pre_audit", required=True)
    name = fields.Char(required=True)
    source_filename = fields.Char(string="File")
    source_sha256 = fields.Char(string="SHA-256")
    row_count = fields.Integer(string="Rows")
    total_amount = fields.Float(digits=(18, 2))
    has_total = fields.Boolean()
    amount_column = fields.Char()
    mapping = fields.Json()
    gl_line_count = fields.Integer(string="Projected lines")
    gl_rejected = fields.Integer(string="Rejected lines")
    gl_built_at = fields.Datetime(string="Projected on")
    validation = fields.Json()
    validation_status = fields.Selection(
        [("passed", "Passed"), ("warning", "Warning"), ("failed", "Failed")], string="Population",
    )
    population_html = fields.Html(string="Population checks", compute="_compute_population_html", sanitize=False, compute_sudo=True)

    @api.depends("validation")
    @api.depends_context("lang")
    def _compute_population_html(self):
        french = is_french(self.env)
        chips = {
            "passed": ("o_ea_chip o_ea_chip_good", self.env._("Passed")),
            "warning": ("o_ea_chip o_ea_chip_warn", self.env._("Warning")),
            "failed": ("o_ea_chip o_ea_chip_bad", self.env._("Failed")),
        }
        for dataset in self:
            rows = Markup("").join(
                Markup("<tr><td>{label}</td><td><span class='{css}'>{status}</span></td><td>{detail}</td></tr>").format(
                    label=check["labelFr" if french else "labelEn"], css=chips[check["status"]][0],
                    status=chips[check["status"]][1], detail=check["detailFr" if french else "detailEn"],
                )
                for check in (dataset.validation or {}).get("checks", [])
            )
            dataset.population_html = rows and Markup("<table class='table table-sm o_ea_table'><tbody>{}</tbody></table>").format(rows)

    def action_build_projection(self):
        self.ensure_one()
        self.sudo().engagement_id.with_env(self.env).gl_build_projection(self.id)
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def action_open_lines(self):
        self.ensure_one()
        return self.sudo().engagement_id.with_env(self.env)._ea_list(
            "ea.audit.gl.line", self.env._("Ledger lines"),
            [("ea_audit_tools.view_gl_line_list", "list"), ("ea_audit_tools.view_gl_line_pivot", "pivot")],
            {"domain": [("dataset_id", "=", self.id)], "search_view_id": self.env.ref("ea_audit_tools.view_gl_line_search").id},
        )

    def action_list_import_dataset(self):
        engagement = self._ea_context_engagement()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Import a dataset"),
            "res_model": "ea.audit.dataset.import.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_engagement_id": engagement.id,
                "default_kind": self.env.context.get("ea_dataset_kind") or "journal_entries",
            },
        }


class DatasetRow(models.Model):
    """sub_ledger_row: the file's own columns, as provenance. Written in bulk by create_dataset."""

    _name = "ea.audit.dataset.row"
    _inherit = ["ea.audit.tool.record"]
    _description = "Imported dataset row"
    _order = "dataset_id, row_no"
    _rec_name = "row_no"

    dataset_id = fields.Many2one("ea.audit.dataset", required=True, ondelete="cascade", index=True)
    row_no = fields.Integer(required=True)
    data = fields.Json()
    amount = fields.Float(digits=(18, 2))

    _dataset_row_uniq = models.Constraint("UNIQUE(dataset_id, row_no)", "A row number is used once in a dataset.")


class GlLine(models.Model):
    """gl_line: one typed, indexed line per ledger row, built once from the imported rows."""

    _name = "ea.audit.gl.line"
    _inherit = ["ea.audit.tool.record"]
    _description = "General ledger line"
    _order = "dataset_id, line_no"
    _rec_name = "je_number"

    dataset_id = fields.Many2one("ea.audit.dataset", required=True, ondelete="cascade", index=True)
    line_no = fields.Integer(required=True)
    account = fields.Char(required=True, index=True)
    account_name = fields.Char()
    je_number = fields.Char(string="JE number", required=True, index=True)
    journal_code = fields.Char(string="Journal")
    je_description = fields.Char(string="Entry description")
    line_description = fields.Char(string="Line description")
    journal_date = fields.Date(index=True)
    entry_date = fields.Date()
    debit = fields.Float(digits=(18, 2))
    credit = fields.Float(digits=(18, 2))
    signed = fields.Float(digits=(18, 2))
    reference = fields.Char()
    third_party_code = fields.Char()
    third_party_name = fields.Char(string="Third party")
    preparer = fields.Char()
    reviewer = fields.Char()
    approver = fields.Char()
    cost_center = fields.Char()

    _dataset_line_uniq = models.Constraint("UNIQUE(dataset_id, line_no)", "A line number is used once in a projection.")


class EngagementDataset(models.Model):
    _inherit = "ea.audit.engagement"

    # ------------------------------------------------------------------
    # Upload (lib/subledgers.ts)
    # ------------------------------------------------------------------

    def _ea_parse(self, filename, content, header_row):
        if not content:
            raise rule_error(self.env, "empty-file")
        if len(content) > MAX_BYTES:
            raise rule_error(self.env, "file-too-large")
        try:
            return parse_table(filename, content, header_row)
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error

    def preview_dataset_file(self, kind, filename, content, header_row=True):
        """previewDataset + the mapping guess. Writes nothing."""
        self.ensure_one()
        self._ea_tool_guard()
        if not is_sub_ledger_kind(kind):
            raise rule_error(self.env, "fields-required")
        table = self._ea_parse(filename, content, header_row)
        samples = {}
        for header in table["headers"]:
            values = []
            for row in table["rows"]:
                value = str(row.get(header) or "").strip()
                if value:
                    values.append(value)
                if len(values) >= 3:
                    break
            samples[header] = values
        return {
            "headers": table["headers"], "headerSamples": samples, "rowCount": len(table["rows"]),
            "mapping": auto_map(kind, table["headers"]),
        }

    def create_dataset(self, kind, filename, content, mapping=None, timing="pre_audit", header_row=True):
        """createDataset. The confirmed amount column wins over the guess; a ledger stating value
        as a debit/credit pair has no single amount column, so the row amount is debit − credit."""
        self.ensure_one()
        self._ea_tool_guard()
        if not is_sub_ledger_kind(kind) or timing not in dict(TIMING_SELECTION):
            raise rule_error(self.env, "fields-required")
        table = self._ea_parse(filename, content, header_row)
        mapping = mapping or None
        debit_col, credit_col = (mapping or {}).get("debit"), (mapping or {}).get("credit")
        amount_mapped = (mapping or {}).get("amount")
        signed_pair = bool(debit_col and credit_col) and not amount_mapped
        amount_col = amount_mapped or (debit_col if signed_pair else detect_amount_column(table))

        Dataset = self.env["ea.audit.dataset"].sudo()
        Dataset.search([("engagement_id", "=", self.id), ("kind", "=", kind), ("timing", "=", timing)]).unlink()
        raw = content if isinstance(content, bytes) else content.encode()
        name = filename.rsplit(".", 1)[0] if "." in filename else filename
        dataset = Dataset.create({
            "engagement_id": self.id, "kind": kind, "timing": timing, "name": name,
            "source_filename": filename, "source_sha256": hashlib.sha256(raw).hexdigest(),
            "row_count": len(table["rows"]), "amount_column": amount_col, "mapping": mapping,
        })
        total = None
        rows = table["rows"]
        for start in range(0, len(rows), INGEST_BATCH):
            numbers, datas, amounts = [], [], []
            for offset, row in enumerate(rows[start:start + INGEST_BATCH], start=start + 1):
                if signed_pair:
                    amount = (parse_amount(row.get(debit_col)) or 0) - (parse_amount(row.get(credit_col)) or 0)
                else:
                    amount = parse_amount(row.get(amount_col)) if amount_col else None
                if amount is not None:
                    total = (total or 0) + amount
                numbers.append(offset)
                datas.append(json.dumps(dict(row), ensure_ascii=False))
                amounts.append(amount)
            self.env.cr.execute(
                """INSERT INTO ea_audit_dataset_row (engagement_id, dataset_id, row_no, data, amount, create_uid, write_uid, create_date, write_date)
                   SELECT %s, %s, r, d::jsonb, a, %s, %s, now() at time zone 'UTC', now() at time zone 'UTC'
                     FROM unnest(%s::int[], %s::text[], %s::numeric[]) AS t(r, d, a)""",
                [self.id, dataset.id, self.env.uid, self.env.uid, numbers, datas, amounts],
            )
        dataset.write({"total_amount": total or 0, "has_total": total is not None})
        self._ea_log("dataset_imported", "%s imported (%s, %s, %d rows)" % (filename, kind, timing, len(rows)))
        return {"datasetId": dataset.id, "rowCount": len(rows)}

    # ------------------------------------------------------------------
    # The GL projection (lib/gl-line.ts)
    # ------------------------------------------------------------------

    def _ea_gl_dataset(self, dataset_id):
        """glDataset: this file's ledger, or no-dataset."""
        self.ensure_one()
        dataset = self.env["ea.audit.dataset"].sudo().search([
            ("id", "=", int(dataset_id or 0)), ("engagement_id", "=", self.id), ("kind", "=", "journal_entries"),
        ], limit=1)
        if not dataset:
            raise rule_error(self.env, "no-dataset")
        return dataset

    def gl_build_projection(self, dataset_id):
        """op build: project the imported rows, then validate. Idempotent: a built projection is
        reused (re-import the dataset to rebuild). Memory bounded by the batch size."""
        self.ensure_one()
        self._ea_tool_guard()
        dataset = self._ea_gl_dataset(dataset_id)
        cr = self.env.cr
        cr.execute("SELECT count(*) FROM ea_audit_gl_line WHERE dataset_id = %s", [dataset.id])
        already = cr.fetchone()[0]
        if already:
            return {"build": {"lines": already, "rejected": 0, "reused": True}, "validation": self.gl_validate_population(dataset.id)}
        try:
            project = projector(dataset.mapping)
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error

        columns = [
            ("line_no", "int"), ("account", "text"), ("account_name", "text"), ("je_number", "text"), ("journal_code", "text"),
            ("je_description", "text"), ("line_description", "text"), ("journal_date", "date"), ("entry_date", "date"),
            ("debit", "numeric"), ("credit", "numeric"), ("signed", "numeric"), ("reference", "text"), ("third_party_code", "text"),
            ("third_party_name", "text"), ("preparer", "text"), ("reviewer", "text"), ("approver", "text"), ("cost_center", "text"),
        ]
        names = ", ".join('"%s"' % name for name, _type in columns)
        arrays = ", ".join("%%s::%s[]" % type_ for _name, type_ in columns)
        insert = (
            'INSERT INTO ea_audit_gl_line (engagement_id, dataset_id, create_uid, write_uid, create_date, write_date, %s) '
            "SELECT %%s, %%s, %%s, %%s, now() at time zone 'UTC', now() at time zone 'UTC', t.* FROM unnest(%s) AS t(%s)"
        ) % (names, arrays, names)
        lines = rejected = after = 0
        while True:
            cr.execute(
                "SELECT row_no, data FROM ea_audit_dataset_row WHERE dataset_id = %s AND row_no > %s ORDER BY row_no LIMIT %s",
                [dataset.id, after, BATCH],
            )
            batch = cr.fetchall()
            if not batch:
                break
            after = batch[-1][0]
            arrays_out = {name: [] for name, _type in columns}
            for row_no, data in batch:
                line = project(data)
                if line is None:
                    rejected += 1
                    continue
                line["line_no"] = row_no
                for name, values in arrays_out.items():
                    values.append(line[name])
            if arrays_out["line_no"]:
                cr.execute(insert, [self.id, dataset.id, self.env.uid, self.env.uid] + [arrays_out[name] for name, _type in columns])
                lines += len(arrays_out["line_no"])
            if len(batch) < BATCH:
                break
        validation = self.gl_validate_population(dataset.id)
        dataset.write({
            "gl_line_count": lines, "gl_rejected": rejected, "gl_built_at": fields.Datetime.now(),
            "validation": validation, "validation_status": validation["status"],
        })
        self._ea_log("gl_projected", "%s: %d lines projected, %d rejected" % (dataset.source_filename, lines, rejected))
        return {"build": {"lines": lines, "rejected": rejected, "reused": False}, "validation": validation}

    def gl_validate_population(self, dataset_id):
        """op validate: read-only, so an archived file answers it."""
        self.ensure_one()
        self._ea_require_access()
        dataset = self._ea_gl_dataset(dataset_id)
        cr = self.env.cr
        period_end = self.sudo().period_end
        start = (period_end - relativedelta(years=1) + relativedelta(days=1)) if period_end else None
        cr.execute(
            """SELECT count(*),
                      count(*) FILTER (WHERE coalesce(trim(account), '') = ''),
                      count(*) FILTER (WHERE coalesce(trim(je_number), '') = ''),
                      count(*) FILTER (WHERE journal_date IS NULL),
                      count(*) FILTER (WHERE debit = 0 AND credit = 0),
                      coalesce(sum(debit), 0), coalesce(sum(credit), 0),
                      count(*) FILTER (WHERE journal_date IS NOT NULL
                                       AND (%(start)s::date IS NULL OR journal_date < %(start)s::date OR journal_date > %(end)s::date)),
                      count(DISTINCT je_number)
                 FROM ea_audit_gl_line WHERE dataset_id = %(dataset)s AND engagement_id = %(engagement)s""",
            {"start": start, "end": period_end, "dataset": dataset.id, "engagement": self.id},
        )
        lines, no_account, no_je, no_date, zero, debit, credit, out, entries = cr.fetchone()
        cr.execute(
            """SELECT count(*) FROM (SELECT je_number FROM ea_audit_gl_line WHERE dataset_id = %s AND engagement_id = %s
                                      GROUP BY je_number HAVING abs(sum(signed)) > %s) q""",
            [dataset.id, self.id, TOLERANCE],
        )
        unbalanced = cr.fetchone()[0]
        cr.execute(
            """SELECT count(*), coalesce(sum(n - 1), 0) FROM (
                 SELECT count(*) AS n FROM ea_audit_gl_line WHERE dataset_id = %s AND engagement_id = %s
                  GROUP BY account, je_number, journal_date, coalesce(reference, ''), signed, coalesce(je_description, '')
                 HAVING count(*) > 1) q""",
            [dataset.id, self.id],
        )
        groups, extra = cr.fetchone()
        return population_checks({
            "fields": mapped_fields(dataset.mapping), "mapping": dataset.mapping, "source_rows": dataset.row_count,
            "lines": lines, "entries": entries, "no_account": no_account, "no_je": no_je, "no_date": no_date,
            "zero_amount": zero, "total_debit": float(debit), "total_credit": float(credit), "out_of_period": out,
            "period_start": start.isoformat() if start else None, "period_end": period_end.isoformat() if period_end else None,
            "unbalanced": unbalanced, "dup_groups": groups, "dup_extra": int(extra),
        })

    # ------------------------------------------------------------------
    # Screens
    # ------------------------------------------------------------------

    def action_tool_gl(self):
        """The ledgers of the file. The console (C.7.5) opens from a ledger."""
        return self._ea_list(
            "ea.audit.dataset", self.env._("General ledger"),
            [("ea_audit_tools.view_dataset_list", "list"), ("ea_audit_tools.view_dataset_form", "form")],
            {
                "domain": [("engagement_id", "=", self.id), ("kind", "=", "journal_entries")],
                "context": {"ea_engagement_id": self.id, "ea_dataset_kind": "journal_entries", "create": False},
            },
        )

    def _ea_export_gl_population(self, fr):
        from ..exports import simple_workbook

        dataset = self.env["ea.audit.dataset"].sudo().search(
            [("engagement_id", "=", self.id), ("kind", "=", "journal_entries")], limit=1,
        )
        if not dataset:
            raise rule_error(self.env, "no-dataset")
        checks = self.gl_validate_population(dataset.id)["checks"]
        rows = [[
            check["labelFr" if fr else "labelEn"], check["status"], check["detailFr" if fr else "detailEn"],
        ] for check in checks]
        head = ["Contrôle", "Statut", "Détail"] if fr else ["Check", "Status", "Detail"]
        return "gl-population-%s.xlsx" % self._ea_export_slug(), simple_workbook("Population", head, rows, title=french_date(self.sudo().period_end))
