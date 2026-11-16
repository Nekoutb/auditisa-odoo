"""The next-year uploads of a file (owner's request of 2026-11-16): the general ledger of the year
after the one audited, and its receivables, payables and inventory listings. What they cover is
worked out when asked and stored nowhere; the procedures of cut-off and the search for unrecorded
liabilities read it here."""
from odoo import models

from ..services.errors import ServiceError
from ..services.subsequent import (
    SUBSEQUENT, SUBSEQUENT_MIN_DAYS, coverage_of, coverage_sentence, coverage_short, coverage_warning, empty_coverage,
    ledger_coverage,
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
        """The next-year upload in use of a kind (receivables, payables, inventory), or an empty record."""
        self.ensure_one()
        return self._ea_current_dataset(kind, SUBSEQUENT)

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
        )

    def ea_subsequent_sentence(self):
        """The plain sentence alone, for a procedure's working paper."""
        self.ensure_one()
        return self.ea_subsequent_overview()["sentence"]
