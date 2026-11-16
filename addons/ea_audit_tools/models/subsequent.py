"""The next-year uploads of a file (owner's request of 2026-11-16): any upload, and the trial
balance, of the year after the one audited. What the ledger covers is worked out when asked and
stored nowhere; the procedures of cut-off and the search for unrecorded liabilities read it here.
These accessors are the only way to the next year: every reader of the year audited leaves it out."""
from odoo import fields, models

from ..services.errors import ServiceError
from ..services.subsequent import (
    SUBSEQUENT, SUBSEQUENT_MIN_DAYS, coverage_of, coverage_sentence, coverage_short, coverage_warning, empty_coverage,
    ledger_coverage, upload_line,
)
from .tool_record import is_french


class EngagementSubsequent(models.Model):
    _inherit = "ea.audit.engagement"

    def _ea_subsequent_ledger(self):
        """The next-year general ledger in use: the newest one not superseded, or an empty record."""
        self.ensure_one()
        return self.env["ea.audit.dataset"].sudo().search([
            ("engagement_id", "=", self.id), ("kind", "=", "journal_entries"), ("timing", "=", SUBSEQUENT),
            ("superseded_at", "=", False),
        ], order="id desc", limit=1)

    def _ea_subsequent_dataset(self, kind):
        """The next-year upload in use of a kind (any kind), or an empty record."""
        self.ensure_one()
        return self._ea_current_dataset(kind, SUBSEQUENT)

    def _ea_subsequent_tb_version(self):
        """The next-year trial balance in use: the newest valid one not superseded, or an empty record.
        It never drives the file: only a pre-audit import does."""
        self.ensure_one()
        tb = self._ea_tb()
        Version = self.env["ea.audit.tb.version"].sudo()
        if not tb:
            return Version
        return Version.search([
            ("tb_id", "=", tb.id), ("timing", "=", SUBSEQUENT), ("superseded_at", "=", False), ("validation_status", "=", "valid"),
        ], order="version_no desc", limit=1)

    def _ea_subsequent_upload_lines(self):
        """One line per next-year upload in use other than the ledger, whose line is the coverage
        sentence: "Next-year <kind> uploaded on dd/mm/yyyy"."""
        self.ensure_one()
        root = self.sudo()
        fr = is_french(self.env)
        Dataset = self.env["ea.audit.dataset"]
        labels = dict(Dataset._fields["kind"]._description_selection(self.env))
        found = Dataset.sudo().search([
            ("engagement_id", "=", root.id), ("timing", "=", SUBSEQUENT), ("superseded_at", "=", False),
            ("kind", "!=", "journal_entries"),
        ], order="kind, id desc")
        lines, seen = [], set()
        version = root._ea_subsequent_tb_version()
        if version:
            day = fields.Datetime.context_timestamp(self, version.create_date).date()
            lines.append(upload_line(self.env._("Trial balance") if fr else "trial balance", day, fr))
        for dataset in found:
            if dataset.kind in seen:
                continue
            seen.add(dataset.kind)
            day = fields.Datetime.context_timestamp(self, dataset.create_date).date()
            label = labels.get(dataset.kind, dataset.kind)
            lines.append(upload_line(label if fr else label.lower(), day, fr))
        return lines

    def ea_subsequent_coverage(self):
        """{first_date, last_date, days_after_year_end, entries} of the next-year ledger, dates as
        ISO text; empty dates and no entries when none was uploaded. Read from its projected lines
        when built, else from the rows of the file."""
        self.ensure_one()
        self._ea_require_access()
        root = self.sudo()
        ledger = root._ea_subsequent_ledger()
        if not ledger:
            return empty_coverage()
        if ledger.gl_built_at:
            self.env.cr.execute(
                """SELECT min(coalesce(journal_date, entry_date)), max(coalesce(journal_date, entry_date)), count(DISTINCT je_number)
                     FROM ea_audit_gl_line WHERE dataset_id = %s AND engagement_id = %s""",
                [ledger.id, root.id],
            )
            first, last, entries = self.env.cr.fetchone()
            return coverage_of(first, last, entries, root.period_end)
        try:
            return ledger_coverage([row["data"] for row in root._ea_dataset_rows(ledger)], ledger.mapping, root.period_end)
        except ServiceError:
            # an upload whose matching lacks the account or the entry number: no entry can be read
            return empty_coverage()

    def ea_subsequent_overview(self):
        """What the upload pages and the procedures show: the coverage, its plain sentence, and
        the warning when it reaches fewer than SUBSEQUENT_MIN_DAYS after the year end."""
        self.ensure_one()
        coverage = self.ea_subsequent_coverage()
        fr = is_french(self.env)
        return dict(
            coverage,
            datasetId=self.sudo()._ea_subsequent_ledger().id or False,
            sentence=coverage_sentence(coverage, fr),
            warning=coverage_warning(coverage, fr),
            short=coverage_short(coverage),
            minDays=SUBSEQUENT_MIN_DAYS,
            others=self._ea_subsequent_upload_lines(),
        )

    def ea_subsequent_sentence(self):
        """The plain sentence alone, for a procedure's working paper."""
        self.ensure_one()
        return self.ea_subsequent_overview()["sentence"]
