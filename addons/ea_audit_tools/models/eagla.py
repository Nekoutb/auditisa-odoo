"""EAGLA (Elite Advisors Augmented General Ledger Analysis), owner's mock-ups of 18/11/2026: the
general ledger console renamed, with the correlations (31 and 32) and SCOT identification.

Every figure is a set-based SQL aggregate over ea_audit_gl_line: the correlations read one row
per account and month, SCOT identification one row per entry and account group, so a ledger of
100 000 lines is never walked line by line in Python. The pure services do the rest. Raw SQL
bypasses the record rules: each entry point checks the team first and filters on the engagement.
"""
from datetime import date

from odoo import models

from ..rules import rule_error
from ..services import eagla_correlation as correlation
from ..services import scot_flows as scot
from ..services.errors import ServiceError
from ..services.gl_correlation import PAGE

SCOPE = "dataset_id = %(dataset)s AND engagement_id = %(engagement)s"


class EngagementEagla(models.Model):
    _inherit = "ea.audit.engagement"

    def action_tool_eagla(self):
        """The EAGLA tile: the page opens on the general ledger in use, or without one (financial
        analysis and analytical procedures need none)."""
        self.ensure_one()
        self._ea_require_access()
        dataset = self._ea_current_dataset("journal_entries")
        console = self.env["ea.audit.gl.console"].create({"engagement_id": self.id, "dataset_id": dataset.id or False})
        return console._ea_reopen()

    def _ea_eagla_year(self, dataset):
        """(first day, last day, the twelve (year, month)) of the year audited."""
        start, end = self._ea_gl_period(dataset.timing)
        if not start:
            today = date.today()
            start, end = date(today.year, 1, 1), date(today.year, 12, 31)
        return start, end, correlation.month_keys(start.year, start.month)

    def _ea_eagla_prefixes(self, text):
        try:
            return correlation.read_prefixes(text)
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error

    def _ea_eagla_month_rows(self, dataset, prefixes, start, end):
        """One row per account and calendar month: the movements (debit minus credit)."""
        self.env.cr.execute(
            f"""SELECT account, extract(year FROM journal_date)::int AS y, extract(month FROM journal_date)::int AS m,
                       coalesce(sum(signed), 0)::float8 AS v
                  FROM ea_audit_gl_line
                 WHERE {SCOPE} AND journal_date BETWEEN %(start)s AND %(end)s AND account LIKE ANY(%(likes)s::text[])
                 GROUP BY 1, 2, 3""",
            {"dataset": dataset.id, "engagement": self.id, "start": start, "end": end, "likes": [p + "%" for p in prefixes]},
        )
        return self.env.cr.dictfetchall()

    def eagla_two_way(self, dataset_id, numerator, denominator, tolerance=None):
        """31. Two-way correlation: numerator ÷ denominator in %, month by month."""
        dataset = self._ea_gl_read(dataset_id)
        num, den = self._ea_eagla_prefixes(numerator), self._ea_eagla_prefixes(denominator)
        start, end, keys = self._ea_eagla_year(dataset)
        rows = self._ea_eagla_month_rows(dataset, list(dict.fromkeys(num + den)), start, end)
        result = correlation.two_way(rows, num, den, keys, correlation.DEFAULT_TOLERANCE if tolerance is None else tolerance)
        result["keys"] = keys
        return result

    def eagla_three_way(self, dataset_id, a, b, c):
        """32. Three-way correlation: A, B and C with B ÷ A, A ÷ C and B ÷ C."""
        dataset = self._ea_gl_read(dataset_id)
        sets = [self._ea_eagla_prefixes(text) for text in (a, b, c)]
        start, end, keys = self._ea_eagla_year(dataset)
        rows = self._ea_eagla_month_rows(dataset, list(dict.fromkeys(sets[0] + sets[1] + sets[2])), start, end)
        result = correlation.three_way(rows, sets[0], sets[1], sets[2], keys)
        result["keys"] = keys
        return result

    def eagla_scot(self, dataset_id, class_key):
        """SCOT identification of one class: flows, timing, patterns (and treasury's groups)."""
        dataset = self._ea_gl_read(dataset_id)
        if class_key not in scot.CLASSES:
            raise rule_error(self.env, "invalid-value")
        start, end, keys = self._ea_eagla_year(dataset)
        case_sql, case_params = scot.sql_case(scot.CLASSES[class_key]["groups"], "l.account")
        focus_sql, focus_params = scot.sql_focus(class_key, "f.account")
        args = dict(case_params, **focus_params, dataset=dataset.id, engagement=self.id, start=start, end=end)
        self.env.cr.execute(
            f"""WITH ent AS (
                  SELECT DISTINCT f.je_number FROM ea_audit_gl_line f
                   WHERE f.dataset_id = %(dataset)s AND f.engagement_id = %(engagement)s
                     AND f.journal_date BETWEEN %(start)s AND %(end)s AND {focus_sql})
                SELECT l.je_number AS je, to_char(min(l.journal_date), 'YYYY-MM-DD') AS jd,
                       coalesce(min(nullif(trim(l.journal_code), '')), '') AS jc, {case_sql} AS grp,
                       coalesce(sum(l.debit), 0)::float8 AS d, coalesce(sum(l.credit), 0)::float8 AS c
                  FROM ea_audit_gl_line l JOIN ent ON ent.je_number = l.je_number
                 WHERE l.dataset_id = %(dataset)s AND l.engagement_id = %(engagement)s
                 GROUP BY l.je_number, grp""",
            args,
        )
        rows = self.env.cr.dictfetchall()
        pairs = []
        if class_key != "treasury":
            middle_sql, middle_params = scot.sql_middle(class_key)
            self.env.cr.execute(
                f"""SELECT coalesce(trim(third_party_code), '') AS party, trim(reference) AS ref,
                           to_char(min(journal_date) FILTER (WHERE debit > credit), 'YYYY-MM-DD') AS d_first,
                           to_char(min(journal_date) FILTER (WHERE credit > debit), 'YYYY-MM-DD') AS c_first
                      FROM ea_audit_gl_line
                     WHERE {SCOPE} AND journal_date BETWEEN %(start)s AND %(end)s AND {middle_sql}
                       AND coalesce(trim(reference), '') <> ''
                     GROUP BY 1, 2""",
                dict(middle_params, dataset=dataset.id, engagement=self.id, start=start, end=end),
            )
            pairs = self.env.cr.dictfetchall()
        result = scot.analyse(rows, class_key, keys, pairs)
        result["keys"] = keys
        return result

    def eagla_entries_action(self, dataset_id, je_numbers, name):
        """The journal entries of a pattern, in Odoo's own list of ledger lines."""
        dataset = self._ea_gl_read(dataset_id)
        numbers = [str(number) for number in (je_numbers or [])][: scot.ENTRY_CAP]
        return self._ea_list(
            "ea.audit.gl.line", name,
            [("ea_audit_tools.view_gl_line_list", "list"), ("ea_audit_tools.view_gl_line_pivot", "pivot")],
            {
                "domain": [("dataset_id", "=", dataset.id), ("je_number", "in", numbers)],
                "search_view_id": self.env.ref("ea_audit_tools.view_gl_line_search").id,
                "limit": PAGE,
                "context": {"default_engagement_id": self.id, "ea_engagement_id": self.id, "search_default_group_entry": 1, "create": False},
            },
        )
