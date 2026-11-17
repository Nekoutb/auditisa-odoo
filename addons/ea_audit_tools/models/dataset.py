import json
from datetime import date

from dateutil.relativedelta import relativedelta
from markupsafe import Markup

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.errors import AuditRuleError

from ..rules import rule_error
from ..services.amount import parse_amount
from ..services.dataset_mapping import guess_map
from ..services.errors import ServiceError
from ..services._js import format_fr
from ..services.gl_line import BATCH, TOLERANCE, mapped_fields, nf, population_checks, projector
from ..services.import_matching import (
    BALANCE_TOLERANCE, amount_check, apply_reading_options, clean_mapping, far_check, gl_population, missing_fields,
)
from ..services.subledger_kinds import SUB_LEDGER_KINDS, is_sub_ledger_kind
from ..services.subledgers import detect_amount_column
from ..services.subsequent import SUBSEQUENT
from ..tabular import parse_table
from .tool_record import french_date, grouped, is_french, upload_stamp
from .tb import TIMING_SELECTION

MAX_BYTES = 60 * 1024 * 1024
#: Unbalanced entries named on the check screen, and blocking points repeated in a refusal.
GL_UNBALANCED_SHOWN = 20
GL_REFUSAL_SHOWN = 6
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
# every upload, the trial balance too, may be of the year after the one audited (owner's request
# of 2026-11-16): one list of timings for all
DATASET_TIMING_SELECTION = TIMING_SELECTION


class Dataset(models.Model):
    """sub_ledger_dataset. Every upload is kept, as a version a person knows by the date and time
    of its upload. The latest of a kind and timing is the one in use; a new upload supersedes it
    and takes its projection away, which is rebuilt from the rows should it be in use again.
    A member who may import may delete one (Engagement.delete_dataset)."""

    _name = "ea.audit.dataset"
    _inherit = ["ea.audit.tool.record"]
    _description = "Imported dataset"
    _order = "create_date desc, id desc"

    kind = fields.Selection(KIND_SELECTION, required=True, index=True)
    timing = fields.Selection(DATASET_TIMING_SELECTION, default="pre_audit", required=True)
    name = fields.Char(required=True)
    source_filename = fields.Char(string="File")
    superseded_at = fields.Datetime(index=True)
    is_current = fields.Boolean(string="In use", compute="_compute_is_current", compute_sudo=True)
    row_count = fields.Integer(string="Rows")
    total_amount = fields.Float(digits=(18, 2))
    has_total = fields.Boolean()
    display_total = fields.Float(string="Total amount", digits=(18, 2), compute="_compute_display_total", compute_sudo=True)
    display_total_note = fields.Char(compute="_compute_display_total", compute_sudo=True)
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

    @api.depends("superseded_at")
    def _compute_is_current(self):
        for dataset in self:
            dataset.is_current = not dataset.superseded_at

    @api.depends("source_filename", "create_date")
    @api.depends_context("tz")
    def _compute_display_name(self):
        for dataset in self:
            dataset.display_name = "%s · %s" % (upload_stamp(dataset, dataset.create_date), dataset.source_filename or dataset.name or "")

    def action_delete(self):
        """The bin of a line: the confirmation first, which says what goes and what takes over."""
        self.ensure_one()
        return self.env["ea.audit.import.delete.wizard"]._ea_open(self.sudo().engagement_id.with_env(self.env), dataset=self)

    def _ea_supersede(self):
        """A later upload takes over. The rows stay, they are the upload; the projection goes,
        it is rebuilt from them if this upload is ever in use again."""
        if not self:
            return
        self.env.cr.execute("DELETE FROM ea_audit_gl_line WHERE dataset_id IN %s", [tuple(self.ids)])
        self.env["ea.audit.gl.line"].invalidate_model()
        self.write({
            "superseded_at": fields.Datetime.now(), "gl_line_count": 0, "gl_rejected": 0, "gl_built_at": False,
            "validation": False, "validation_status": False,
        })

    @api.depends("total_amount", "mapping", "amount_column")
    @api.depends_context("lang")
    def _compute_display_total(self):
        """M-10: a ledger stated as a debit/credit pair nets to nil by construction, so its total
        is the sum of its debits. Every other file keeps the sum of its amount column."""
        for dataset in self:
            mapping = dataset.mapping or {}
            if mapping.get("debit") and mapping.get("credit") and not mapping.get("amount"):
                self.env.cr.execute(
                    "SELECT coalesce(sum(amount) FILTER (WHERE amount > 0), 0) FROM ea_audit_dataset_row WHERE dataset_id = %s",
                    [dataset.id],
                )
                dataset.display_total = self.env.cr.fetchone()[0]
                dataset.display_total_note = self.env._("Total of the debits")
            else:
                dataset.display_total = dataset.total_amount
                dataset.display_total_note = dataset.amount_column or False

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
            # read afresh, so a ledger built before a wording change shows the current text
            validation = dataset.validation
            if validation and dataset.gl_built_at and dataset.engagement_id._ea_member(self.env.user).state == "accepted":
                validation = dataset.engagement_id.gl_validate_population(dataset.id)
            rows = Markup("").join(
                Markup("<tr><td>{label}</td><td><span class='{css}'>{status}</span></td><td>{detail}</td></tr>").format(
                    label=check["labelFr" if french else "labelEn"], css=chips[check["status"]][0],
                    status=chips[check["status"]][1], detail=check["detailFr" if french else "detailEn"],
                )
                for check in (validation or {}).get("checks", [])
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

    def action_list_gl_catalogue(self):
        return self._ea_context_engagement().action_tool_gl_catalogue()

    def action_list_import_dataset(self):
        engagement = self._ea_context_engagement()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Import data"),
            "res_model": "ea.audit.import.wizard",
            "view_mode": "form", "views": [(False, "form")],
            "target": "new",
            "context": {
                "default_engagement_id": engagement.id,
                "default_kind": self.env.context.get("ea_dataset_kind") or "journal_entries",
                "dialog_size": "extra-large",
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
    je_number = fields.Char(string="Journal entry number", required=True, index=True)
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

    def _ea_parse(self, filename, content, header_row, options=None):
        """The file as a table. ``options`` holds a person's choices over the reader's own guesses:
        sheet (Excel) and delimiter (CSV) here, decimal and date_format once the columns are matched."""
        if not content:
            raise rule_error(self.env, "empty-file")
        if len(content) > MAX_BYTES:
            raise rule_error(self.env, "file-too-large")
        options = options or {}
        try:
            return parse_table(filename, content, header_row, sheet=options.get("sheet"), delimiter=options.get("delimiter"))
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
            "mapping": guess_map(kind, table["headers"]),
        }

    def _ea_dataset_read(self, kind, filename, content, mapping, header_row, options):
        """The file as the import will take it: (table, mapping). Refuses a matching that leaves a
        mandatory field out, here and not only on the screen. Writes nothing."""
        table = self._ea_parse(filename, content, header_row, options)
        mapping = mapping or guess_map(kind, table["headers"])
        if missing_fields(kind, clean_mapping(kind, mapping, table["headers"])):
            raise rule_error(self.env, "mapping-incomplete")
        apply_reading_options(table, kind, mapping, (options or {}).get("decimal"), (options or {}).get("date_format"))
        return table, mapping

    def _ea_gl_period(self, timing=None):
        """(first day, last day) of the period the ledger's dates are checked against: the year
        audited, or the year after it for a next-year ledger."""
        period_end = self.sudo().period_end
        if period_end and timing == SUBSEQUENT:
            return period_end + relativedelta(days=1), period_end + relativedelta(years=1)
        start = (period_end - relativedelta(years=1) + relativedelta(days=1)) if period_end else None
        return start, period_end

    def _ea_gl_found(self, table, mapping, timing=None):
        """The ledger as the import reads it: gl_population over this file's period."""
        start, end = self._ea_gl_period(timing)
        try:
            return gl_population(table, mapping, start.isoformat() if start else None, end.isoformat() if end else None)
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error

    def _ea_gl_blocking(self, found):
        """What stops a ledger at the check (owner's ruling of 2026-11-15): no line that belongs to
        an entry, debits that differ from credits, or an entry that does not balance. The first
        GL_UNBALANCED_SHOWN entries are named; the others are counted."""
        def amount(value):
            return format_fr(value) if is_french(self.env) else nf(value)

        if not found["lines"]:
            return [{"effect": "blocking", "rows": [], "text": self.env._(
                "No line of the file carries both an account and an entry number: there is nothing to import.",
            )}]
        issues = []
        difference = found["totalDebit"] - found["totalCredit"]
        if abs(difference) > BALANCE_TOLERANCE:
            issues.append({"effect": "blocking", "rows": [], "text": self.env._(
                "Total debit %(debit)s and total credit %(credit)s differ by %(difference)s: a general ledger must balance.",
                debit=amount(found["totalDebit"]), credit=amount(found["totalCredit"]), difference=amount(difference),
            )})
        entries = found["unbalancedEntries"]
        for entry in entries[:GL_UNBALANCED_SHOWN]:
            values = {
                "entry": entry["entry"], "debit": amount(entry["debit"]), "credit": amount(entry["credit"]),
                "difference": amount(entry["difference"]),
            }
            if entry["date"]:
                text = self.env._(
                    "Entry %(entry)s of %(date)s does not balance: debit %(debit)s, credit %(credit)s, difference %(difference)s.",
                    date=french_date(fields.Date.to_date(entry["date"])), **values,
                )
            else:
                text = self.env._(
                    "Entry %(entry)s, with no readable date, does not balance: debit %(debit)s, credit %(credit)s, difference %(difference)s.",
                    **values,
                )
            issues.append({"effect": "blocking", "rows": entry["rows"], "text": text})
        if len(entries) > GL_UNBALANCED_SHOWN:
            issues.append({"effect": "blocking", "rows": [], "text": self.env._(
                "%(count)s more entries do not balance.", count=len(entries) - GL_UNBALANCED_SHOWN,
            )})
        return issues

    def _ea_dataset_check(self, kind, filename, content, mapping, header_row, options, timing=None):
        """The check screen of a dataset. A ledger gets its population checks, read from the file
        as the projection will read it, and is stopped when it does not balance; the other kinds
        get their rows and the total of their amounts, and what is found is shown without stopping
        the file, as it always was."""
        table, mapping = self._ea_dataset_read(kind, filename, content, mapping, header_row, options)
        fr = is_french(self.env)
        issues = []
        if kind == "journal_entries":
            found = self._ea_gl_found(table, mapping, timing)
            blocking = self._ea_gl_blocking(found)
            if found["leftOut"]:
                issues.append({"effect": "left_out", "rows": found["leftOut"], "text": self.env._(
                    "Lines with no account or no entry number. They belong to no entry.",
                )})
            # the count of lines left out is the list above; the balance, the blocking points
            skipped = {"row-count"} | ({"debit-credit-reconcile", "entries-balance"} if blocking else set())
            for check in found["validation"]["checks"]:
                if check["status"] != "passed" and check["key"] not in skipped:
                    issues.append({"effect": "warning", "rows": [], "text": "%s. %s" % (
                        check["labelFr" if fr else "labelEn"], check["detailFr" if fr else "detailEn"],
                    )})
            return {
                "kind": kind, "fileRows": found["fileRows"], "rows": found["lines"], "leftOut": len(found["leftOut"]),
                "totalDebit": found["totalDebit"], "totalCredit": found["totalCredit"],
                "balanced": found["balanced"], "difference": found["totalDebit"] - found["totalCredit"],
                "issues": blocking + issues, "blocking": bool(blocking),
            }
        found = amount_check(table, mapping)
        if found["unreadable"]:
            issues.append({"effect": "warning", "rows": [row["row"] for row in found["unreadable"]], "text": self.env._(
                "The column \"%(column)s\" holds something that is not an amount, for instance \"%(value)s\". These lines count for nothing in the total.",
                column=found["header"], value=found["unreadable"][0]["value"],
            )})
        if kind == "fixed_asset_register":
            issues += self._ea_far_issues(table, mapping)
        return {
            "kind": kind, "fileRows": found["fileRows"], "rows": found["fileRows"], "leftOut": 0,
            "total": found["total"] or 0, "balanced": None, "issues": issues, "blocking": False,
        }

    def _ea_far_issues(self, table, mapping):
        """The register's mandatory values, row by row, shown without stopping the file like the
        other checks of a sub-ledger (owner's request of 2026-11-16)."""
        period_end = self.sudo().period_end
        found = far_check(table, mapping, period_end.isoformat() if period_end else None)
        issues = []

        def add(key, text):
            if found[key]:
                issues.append({"effect": "warning", "rows": [row["row"] for row in found[key]], "text": text})

        add("noCategory", self.env._("%(count)s lines have no category.", count=len(found["noCategory"])))
        if found["badDate"]:
            add("badDate", self.env._(
                "%(count)s lines have no readable acquisition date, for instance \"%(value)s\".",
                count=len(found["badDate"]), value=found["badDate"][0]["value"],
            ))
        if found["futureDate"]:
            add("futureDate", self.env._(
                "%(count)s lines have an acquisition date after the year end, for instance %(value)s.",
                count=len(found["futureDate"]), value=french_date(date.fromisoformat(found["futureDate"][0]["value"])),
            ))
        if found["badRate"]:
            add("badRate", self.env._(
                "%(count)s lines have no readable depreciation rate between 0 and 100%%, for instance \"%(value)s\".",
                count=len(found["badRate"]), value=found["badRate"][0]["value"],
            ))
        if found["fractionRate"]:
            add("fractionRate", self.env._(
                "%(count)s rates are written as a fraction, for instance \"%(value)s\": they are read as a percentage (0.2 reads 20%%).",
                count=len(found["fractionRate"]), value=found["fractionRate"][0]["value"],
            ))
        return issues

    def create_dataset(self, kind, filename, content, mapping=None, timing="pre_audit", header_row=True, options=None, remember=False):
        """createDataset. The confirmed amount column wins over the guess; a ledger stating value
        as a debit/credit pair has no single amount column, so the row amount is debit − credit.
        The upload before it, of the same kind and timing, is kept and superseded."""
        self.ensure_one()
        self._ea_tool_guard()
        if not is_sub_ledger_kind(kind) or timing not in dict(DATASET_TIMING_SELECTION):
            raise rule_error(self.env, "fields-required")
        table, mapping = self._ea_dataset_read(kind, filename, content, mapping, header_row, options)
        if kind == "journal_entries":
            # the check screen's own refusal, here too: the screen is not the control
            blocking = self._ea_gl_blocking(self._ea_gl_found(table, mapping, timing))
            if blocking:
                reasons = [issue["text"] for issue in blocking[:GL_REFUSAL_SHOWN]]
                if len(blocking) > GL_REFUSAL_SHOWN:
                    reasons.append(self.env._("%(count)s more points stop the file.", count=len(blocking) - GL_REFUSAL_SHOWN))
                raise rule_error(self.env, "import-refused", reasons=" ".join(reasons))
        debit_col, credit_col = mapping.get("debit"), mapping.get("credit")
        amount_mapped = mapping.get("amount")
        signed_pair = bool(debit_col and credit_col) and not amount_mapped
        amount_col = amount_mapped or (debit_col if signed_pair else detect_amount_column(table))

        Dataset = self.env["ea.audit.dataset"].sudo()
        self._ea_lock()
        Dataset.search([
            ("engagement_id", "=", self.id), ("kind", "=", kind), ("timing", "=", timing), ("superseded_at", "=", False),
        ])._ea_supersede()
        name = filename.rsplit(".", 1)[0] if "." in filename else filename
        dataset = Dataset.create({
            "engagement_id": self.id, "kind": kind, "timing": timing, "name": name, "source_filename": filename,
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
        if remember:
            self._ea_remember_matching(kind, table["headers"], mapping)
        if kind == "journal_entries":
            self._ea_refresh_significance_activity()
        return {"datasetId": dataset.id, "rowCount": len(rows)}

    def _ea_current_dataset(self, kind, timing=None):
        """The upload in use of a kind: of that timing, else the newest of the year audited. A
        next-year upload is had only by asking for it: it never stands in for this year's."""
        self.ensure_one()
        domain = [("engagement_id", "=", self.id), ("kind", "=", kind), ("superseded_at", "=", False)]
        if timing:
            domain.append(("timing", "=", timing))
        else:
            domain.append(("timing", "!=", SUBSEQUENT))
        return self.env["ea.audit.dataset"].sudo().search(domain, limit=1)

    def _ea_dataset_successor(self, dataset):
        """The upload in use again when this one is deleted: the latest other one of its kind and
        timing. Empty when this one is not in use, or when none remains."""
        if dataset.superseded_at:
            return self.env["ea.audit.dataset"].sudo()
        return self.env["ea.audit.dataset"].sudo().search([
            ("engagement_id", "=", self.id), ("kind", "=", dataset.kind), ("timing", "=", dataset.timing), ("id", "!=", dataset.id),
        ], limit=1)

    def delete_dataset(self, dataset_id):
        """Whoever may import may delete (owner's ruling of 2026-11-15), as for a trial balance.
        A sampling run or a selection design drawn from the upload stays, without its link to it.
        When the upload in use goes, the one before it is in use again, and a ledger gets its
        projection back if the deleted one had its own. The trail keeps what was deleted."""
        self.ensure_one()
        self._ea_tool_guard()
        dataset = self.env["ea.audit.dataset"].sudo().search([
            ("id", "=", int(dataset_id or 0)), ("engagement_id", "=", self.id),
        ], limit=1)
        if not dataset:
            raise rule_error(self.env, "no-dataset")
        self._ea_lock()
        successor = self._ea_dataset_successor(dataset)
        had_projection = bool(dataset.gl_built_at)
        facts = (
            dataset.source_filename, dataset.kind, dataset.timing, upload_stamp(self, dataset.create_date),
            dataset.row_count, grouped(dataset.display_total, "en"),
        )
        dataset.unlink()
        self._ea_log("dataset_deleted", "%s deleted (%s, %s, imported on %s, %d rows, total %s)" % facts)
        if successor:
            successor.superseded_at = False
            if successor.kind == "journal_entries" and had_projection:
                try:
                    self.gl_build_projection(successor.id)
                except AuditRuleError:
                    # an upload from before the matching was mandatory: it waits for a person to build it
                    pass
        if facts[1] == "journal_entries":
            self._ea_refresh_significance_activity()
        return {"successorId": successor.id or False}

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
        if dataset.superseded_at:
            raise rule_error(self.env, "dataset-superseded")
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
        start, period_end = self._ea_gl_period(dataset.timing)
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
        """The ledgers of the file. The console (C.7.5) opens from a ledger's form."""
        return self._ea_list(
            "ea.audit.dataset", self.env._("General ledger"),
            [("ea_audit_tools.view_gl_dataset_list", "list"), ("ea_audit_tools.view_dataset_form", "form")],
            {
                "domain": [("engagement_id", "=", self.id), ("kind", "=", "journal_entries")],
                "context": {"ea_engagement_id": self.id, "ea_dataset_kind": "journal_entries", "create": False},
                "help": Markup("<p>{}</p><p>{}</p>").format(
                    self.env._("No general ledger on this file yet."),
                    self.env._("Import one to run the analytics. The thirty analytics can be read without it: use the button above."),
                ),
            },
        )

    gl_catalogue_html = fields.Html(string="The thirty analytics", compute="_compute_gl_catalogue_html", sanitize=False, compute_sudo=True)

    @api.depends_context("lang")
    def _compute_gl_catalogue_html(self):
        """F065: what each analytic looks for, with no dataset behind it: nothing here reads the file."""
        from ..services.gl_analytics import catalogue
        from ..wizards.gl_console_wizard import table

        rows = [
            [entry["id"], entry["title"], entry["objective"], ", ".join(entry["assertions"]), entry["exception"]]
            for entry in catalogue({}, "fr" if is_french(self.env) else "en")
        ]
        html = table(["#", self.env._("Analytic"), self.env._("Objective"), self.env._("Assertions"), self.env._("Exception")], rows, numeric_from=99)
        for engagement in self:
            engagement.gl_catalogue_html = html

    def action_tool_gl_catalogue(self):
        return self._ea_board("ea_audit_tools.view_engagement_gl_catalogue", self.env._("The thirty analytics"))

    def _ea_export_gl_population(self, fr):
        from ..exports import simple_workbook

        dataset = self._ea_current_dataset("journal_entries")
        if not dataset:
            raise rule_error(self.env, "no-dataset")
        checks = self.gl_validate_population(dataset.id)["checks"]
        rows = [[
            check["labelFr" if fr else "labelEn"], check["status"], check["detailFr" if fr else "detailEn"],
        ] for check in checks]
        head = ["Contrôle", "Statut", "Détail"] if fr else ["Check", "Status", "Detail"]
        return "gl-population-%s.xlsx" % self._ea_export_slug(), simple_workbook("Population", head, rows, title=french_date(self.sudo().period_end))
