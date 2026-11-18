"""The reads of the GL console: lib/gl-analytics.ts, lib/gl-correlation.ts, lib/gl-insights.ts.

Every figure is a SQL aggregate over ea_audit_gl_line, so the ledger is never walked in Python,
except the three insights the source itself folds over the raw rows, read here in batches. Raw
SQL bypasses the record rules: each entry point checks the team first and every statement filters
on the engagement. Nothing here writes, so an archived file answers, and so do read-only and EQR
members.
"""
import json

from odoo import fields, models
from odoo.fields import Domain
from odoo.tools import SQL

from ..rules import rule_error
from ..services import gl_analytics as analytics
from ..services import gl_correlation as correlation
from ..services import gl_insights as insights
from ..services._js import js_round, js_sum
from ..services.dataset_mapping import JE_KEY_JOIN, je_key_columns
from ..services.errors import ServiceError
from ..services.gl_line import BATCH, TOLERANCE
from ..services.subsequent import CURRENT_YEAR_TIMINGS
from .tool_record import is_french

MONTH = correlation.MONTH
SCOPE = "dataset_id = %(dataset)s AND engagement_id = %(engagement)s"
TABLE = "ea_audit_gl_line"
POPULATION = "SELECT count(*)::int AS n FROM %s WHERE %s" % (TABLE, SCOPE)


def _person_sql(column, measure):
    """21, 22, 23. ``column`` and ``measure`` are constants of this module, never input."""
    metric = "count(*)::float8" if measure == "count" else "coalesce(sum(abs(signed)), 0)::float8"
    return {
        "top": """SELECT trim({c}) AS person, {metric} AS v FROM {t}
                   WHERE {scope} AND coalesce(trim({c}), '') <> ''
                   GROUP BY 1 ORDER BY v DESC, 1 LIMIT %(topN)s::int""".format(c=column, metric=metric, t=TABLE, scope=SCOPE),
        "grid": """SELECT {month} AS m, nullif(trim({c}), '') AS person, {metric} AS v FROM {t}
                    WHERE {scope} GROUP BY 1, 2 ORDER BY 1""".format(month=MONTH, c=column, metric=metric, t=TABLE, scope=SCOPE),
        "gap": """SELECT count(*) FILTER (WHERE coalesce(trim({c}), '') = '')::int AS missing, count(*)::int AS lines
                    FROM {t} WHERE {scope}""".format(c=column, t=TABLE, scope=SCOPE),
    }


#: One entry per computed analytic: the named queries its body reads.
SQL_BY_KEY = {
    "ledger-reconciliation": {"rows": f"""
        SELECT {MONTH} AS m, count(*)::int AS lines,
               coalesce(sum(debit), 0)::float8 AS d,
               coalesce(sum(credit), 0)::float8 AS c,
               coalesce(sum(debit) - sum(credit), 0)::float8 AS diff
          FROM {TABLE} WHERE {SCOPE} GROUP BY 1 ORDER BY 1"""},
    "unbalanced-entries": {"rows": f"""
        WITH je AS (
          SELECT je_number, min(journal_date) AS jd, sum(signed) AS net
            FROM {TABLE} WHERE {SCOPE} GROUP BY je_number)
        SELECT coalesce(to_char(jd, 'YYYY-MM'), 'n/a') AS m,
               count(*)::int AS entries,
               count(*) FILTER (WHERE abs(net) > %(tolerance)s::numeric)::int AS unbalanced,
               coalesce(sum(abs(net)) FILTER (WHERE abs(net) > %(tolerance)s::numeric), 0)::float8 AS diff
          FROM je GROUP BY 1 ORDER BY 1"""},
    "exact-duplicates": {"rows": f"""
        WITH d AS (
          SELECT {MONTH} AS m, count(*) AS n, sum(abs(signed)) AS v
            FROM {TABLE} WHERE {SCOPE}
           GROUP BY {MONTH}, account, je_number, journal_date,
                    coalesce(reference, ''), signed, coalesce(je_description, '')
          HAVING count(*) > 1)
        SELECT m, count(*)::int AS groups, sum(n)::int AS lines,
               sum(n - 1)::int AS extra, coalesce(sum(v), 0)::float8 AS value
          FROM d GROUP BY 1 ORDER BY 1""", "population": POPULATION},
    "zero-value": {"rows": f"""
        SELECT {MONTH} AS m, count(*)::int AS lines,
               count(*) FILTER (WHERE debit = 0 AND credit = 0)::int AS nil
          FROM {TABLE} WHERE {SCOPE} GROUP BY 1 ORDER BY 1"""},
    "invalid-debit-credit": {"rows": f"""
        SELECT {MONTH} AS m, count(*)::int AS lines,
               count(*) FILTER (WHERE debit <> 0 AND credit <> 0)::int AS both,
               count(*) FILTER (WHERE debit < 0 OR credit < 0)::int AS negative,
               count(*) FILTER (WHERE debit = 0 AND credit = 0)::int AS neither
          FROM {TABLE} WHERE {SCOPE} GROUP BY 1 ORDER BY 1"""},
    "weekend-postings": {"rows": f"""
        SELECT {MONTH} AS m,
               count(*) FILTER (WHERE extract(isodow FROM journal_date) = 1)::int AS d1,
               count(*) FILTER (WHERE extract(isodow FROM journal_date) = 2)::int AS d2,
               count(*) FILTER (WHERE extract(isodow FROM journal_date) = 3)::int AS d3,
               count(*) FILTER (WHERE extract(isodow FROM journal_date) = 4)::int AS d4,
               count(*) FILTER (WHERE extract(isodow FROM journal_date) = 5)::int AS d5,
               count(*) FILTER (WHERE extract(isodow FROM journal_date) = 6)::int AS d6,
               count(*) FILTER (WHERE extract(isodow FROM journal_date) = 7)::int AS d7,
               count(*)::int AS lines
          FROM {TABLE} WHERE {SCOPE} GROUP BY 1 ORDER BY 1"""},
    "entry-date-lag": {"rows": f"""
        WITH je AS (
          SELECT je_number, min(journal_date) AS jd, min(entry_date) AS ed
            FROM {TABLE}
           WHERE {SCOPE} AND journal_date IS NOT NULL AND entry_date IS NOT NULL
           GROUP BY je_number)
        SELECT to_char(jd, 'YYYY-MM') AS m, count(*)::int AS entries,
               count(*) FILTER (WHERE ed - jd = 0)::int AS same,
               count(*) FILTER (WHERE ed - jd = 1)::int AS one,
               count(*) FILTER (WHERE ed - jd BETWEEN 2 AND 3)::int AS short,
               count(*) FILTER (WHERE ed - jd > 3)::int AS long,
               count(*) FILTER (WHERE ed - jd < 0)::int AS negative,
               avg(ed - jd)::float8 AS avg, max(ed - jd)::float8 AS max
          FROM je GROUP BY 1 ORDER BY 1"""},
    "year-end-concentration": {"rows": f"""
        WITH p AS (SELECT period_end AS pe FROM ea_audit_engagement WHERE id = %(engagement)s),
        scoped AS (
          SELECT {MONTH} AS m, l.signed,
                 (l.journal_date IS NOT NULL
                  AND l.journal_date > p.pe - (%(days)s::int)
                  AND l.journal_date <= p.pe) AS in_window
            FROM {TABLE} l CROSS JOIN p
           WHERE l.dataset_id = %(dataset)s AND l.engagement_id = %(engagement)s)
        SELECT m, count(*)::int AS lines,
               coalesce(sum(abs(signed)), 0)::float8 AS value,
               count(*) FILTER (WHERE in_window)::int AS wlines,
               coalesce(sum(abs(signed)) FILTER (WHERE in_window), 0)::float8 AS wvalue
          FROM scoped GROUP BY 1 ORDER BY 1"""},
    "monthly-spikes": {"rows": f"""
        WITH mth AS (
          SELECT to_char(journal_date, 'YYYY-MM') AS m, count(*)::int AS lines,
                 coalesce(sum(abs(signed)), 0)::float8 AS value
            FROM {TABLE} WHERE {SCOPE} AND journal_date IS NOT NULL GROUP BY 1),
        s AS (SELECT avg(value)::float8 AS mu, coalesce(stddev_samp(value), 0)::float8 AS sd FROM mth)
        SELECT mth.m, mth.lines, mth.value, s.mu, s.sd FROM mth, s ORDER BY mth.m"""},
    "top-value": {"rows": f"""
        WITH thr AS (
          SELECT coalesce(percentile_cont(%(percentile)s::float8) WITHIN GROUP (ORDER BY abs(signed)::float8), 0)::float8 AS p
            FROM {TABLE} WHERE {SCOPE}),
        scoped AS (
          SELECT {MONTH} AS m, abs(l.signed)::float8 AS a, thr.p
            FROM {TABLE} l CROSS JOIN thr
           WHERE l.dataset_id = %(dataset)s AND l.engagement_id = %(engagement)s)
        SELECT m, count(*)::int AS lines,
               coalesce(sum(a), 0)::float8 AS value,
               count(*) FILTER (WHERE a >= p)::int AS "hits",
               coalesce(sum(a) FILTER (WHERE a >= p), 0)::float8 AS "hitValue",
               min(p)::float8 AS threshold
          FROM scoped GROUP BY 1 ORDER BY 1"""},
    "round-numbers": {"rows": f"""
        SELECT {MONTH} AS m, count(*)::int AS lines,
               count(*) FILTER (WHERE abs(signed) >= %(min)s::numeric AND mod(abs(signed), %(step)s::numeric) = 0)::int AS hits,
               coalesce(sum(abs(signed)) FILTER (WHERE abs(signed) >= %(min)s::numeric AND mod(abs(signed), %(step)s::numeric) = 0), 0)::float8 AS value
          FROM {TABLE} WHERE {SCOPE} GROUP BY 1 ORDER BY 1"""},
    "benford": {"rows": f"""
        SELECT {MONTH} AS m,
               substring(regexp_replace(abs(signed)::text, '[^1-9]', '', 'g') FROM 1 FOR 1) AS digit,
               count(*)::int AS n
          FROM {TABLE} WHERE {SCOPE} AND signed <> 0
         GROUP BY 1, 2 ORDER BY 1, 2"""},
    "repeated-amounts": {"rows": f"""
        WITH rep AS (
          SELECT abs(signed) AS a FROM {TABLE}
           WHERE {SCOPE} AND signed <> 0
           GROUP BY 1 HAVING count(*) >= %(minOcc)s::int)
        SELECT {MONTH} AS m, count(DISTINCT abs(l.signed))::int AS amounts,
               count(*)::int AS lines, coalesce(sum(abs(l.signed)), 0)::float8 AS value
          FROM {TABLE} l JOIN rep ON rep.a = abs(l.signed)
         WHERE l.dataset_id = %(dataset)s AND l.engagement_id = %(engagement)s
         GROUP BY 1 ORDER BY 1""", "population": POPULATION},
    "rare-accounts": {"rows": f"""
        WITH rare AS (
          SELECT account FROM {TABLE} WHERE {SCOPE}
           GROUP BY account HAVING count(*) <= %(rareMax)s::int)
        SELECT {MONTH} AS m, count(DISTINCT l.account)::int AS accounts,
               count(*)::int AS lines, coalesce(sum(abs(l.signed)), 0)::float8 AS value
          FROM {TABLE} l JOIN rare ON rare.account = l.account
         WHERE l.dataset_id = %(dataset)s AND l.engagement_id = %(engagement)s
         GROUP BY 1 ORDER BY 1""", "population": POPULATION},
    "normal-side-exceptions": {"rows": f"""
        WITH sided AS (
          SELECT {MONTH} AS m, signed,
                 CASE WHEN left(account, 2) IN ('28','29','39','49','59') THEN -1
                      WHEN left(account, 1) IN ('2','3','6') THEN 1
                      WHEN left(account, 1) IN ('1','7') THEN -1
                      ELSE 0 END AS side
            FROM {TABLE} WHERE {SCOPE})
        SELECT m, count(*) FILTER (WHERE side <> 0)::int AS "inScope",
               count(*) FILTER (WHERE side = 1 AND signed < 0)::int AS credited,
               count(*) FILTER (WHERE side = -1 AND signed > 0)::int AS debited,
               coalesce(sum(abs(signed)) FILTER (
                 WHERE (side = 1 AND signed < 0) OR (side = -1 AND signed > 0)), 0)::float8 AS value
          FROM sided GROUP BY 1 ORDER BY 1"""},
    "unusual-account-combinations": {"rows": f"""
        WITH ent AS (
          SELECT je_number, min(journal_date) AS jd, array_agg(DISTINCT account) AS accounts
            FROM {TABLE} WHERE {SCOPE} GROUP BY je_number),
        scoped AS (
          SELECT * FROM ent
           WHERE coalesce(array_length(accounts, 1), 0) BETWEEN 2 AND {analytics.PAIR_ACCOUNT_CAP}),
        pair AS (
          SELECT s.je_number, s.jd, a.account AS a1, b.account AS a2
            FROM scoped s
            CROSS JOIN LATERAL unnest(s.accounts) AS a(account)
            CROSS JOIN LATERAL unnest(s.accounts) AS b(account)
           WHERE a.account < b.account),
        freq AS (
          SELECT a1, a2, count(DISTINCT je_number) AS n FROM pair GROUP BY 1, 2),
        scored AS (
          SELECT p.je_number, p.jd, count(*)::int AS pairs,
                 count(*) FILTER (WHERE f.n <= %(pairMax)s::int)::int AS rare
            FROM pair p JOIN freq f ON f.a1 = p.a1 AND f.a2 = p.a2
           GROUP BY 1, 2)
        SELECT coalesce(to_char(jd, 'YYYY-MM'), 'n/a') AS m,
               count(*)::int AS entries,
               count(*) FILTER (WHERE rare > 0)::int AS hits,
               coalesce(sum(pairs), 0)::int AS pairs,
               coalesce(sum(rare), 0)::int AS rare
          FROM scored GROUP BY 1 ORDER BY 1"""},
    "missing-mandatory-fields": {"rows": f"""
        SELECT {MONTH} AS m, count(*)::int AS lines,
               count(*) FILTER (WHERE coalesce(trim(account), '') = '')::int        AS "noAccount",
               count(*) FILTER (WHERE coalesce(trim(je_number), '') = '')::int      AS "noJe",
               count(*) FILTER (WHERE coalesce(trim(je_description), '') = '')::int AS "noDesc",
               count(*) FILTER (WHERE journal_date IS NULL)::int                    AS "noDate",
               count(*) FILTER (WHERE debit = 0 AND credit = 0)::int                AS "noAmount"
          FROM {TABLE} WHERE {SCOPE} GROUP BY 1 ORDER BY 1"""},
    "missing-references": {"rows": f"""
        SELECT {MONTH} AS m, count(*)::int AS lines,
               count(*) FILTER (WHERE coalesce(trim(reference), '') = '')::int AS missing,
               coalesce(sum(abs(signed)) FILTER (WHERE coalesce(trim(reference), '') = ''), 0)::float8 AS value
          FROM {TABLE} WHERE {SCOPE} GROUP BY 1 ORDER BY 1"""},
    "third-party-attribution": {"rows": f"""
        WITH scoped AS (
          SELECT {MONTH} AS m, signed, third_party_code
            FROM {TABLE}
           WHERE {SCOPE}
             AND EXISTS (SELECT 1 FROM unnest(%(prefixes)s::text[]) p WHERE account LIKE p || '%%'))
        SELECT m, count(*)::int AS "inScope",
               count(*) FILTER (WHERE coalesce(trim(third_party_code), '') <> '')::int AS attributed,
               coalesce(sum(abs(signed)), 0)::float8 AS value,
               coalesce(sum(abs(signed)) FILTER (WHERE coalesce(trim(third_party_code), '') = ''), 0)::float8 AS "unattributedValue"
          FROM scoped GROUP BY 1 ORDER BY 1"""},
    "preparer-volume": _person_sql("preparer", "count"),
    "preparer-value": _person_sql("preparer", "value"),
    "reviewer-workload": _person_sql("reviewer", "count"),
    "self-review": {"rows": f"""
        WITH scoped AS (
          SELECT {MONTH} AS m, je_number, abs(signed) AS gross,
                 nullif(lower(trim(preparer)), '') AS prep,
                 nullif(lower(trim(approver)), '') AS appr
            FROM {TABLE} WHERE {SCOPE}),
        je AS (
          SELECT je_number, min(m) AS m, coalesce(sum(gross), 0)::float8 AS value,
                 count(*) FILTER (WHERE prep IS NOT NULL AND appr IS NOT NULL)::int AS named,
                 count(*) FILTER (WHERE prep IS NOT NULL AND appr IS NOT NULL AND prep = appr)::int AS self
            FROM scoped GROUP BY je_number)
        SELECT m, count(*)::int AS entries,
               count(*) FILTER (WHERE named > 0)::int AS attributed,
               count(*) FILTER (WHERE self > 0)::int AS same,
               count(*) FILTER (WHERE named = 0)::int AS none,
               coalesce(sum(value) FILTER (WHERE self > 0), 0)::float8 AS value
          FROM je GROUP BY 1 ORDER BY 1"""},
    "debit-credit-correlation": {"rows": f"""
        SELECT {MONTH} AS m, coalesce(sum(debit), 0)::float8 AS d, coalesce(sum(credit), 0)::float8 AS c
          FROM {TABLE} WHERE {SCOPE} GROUP BY 1 ORDER BY 1"""},
    "account-frequency-value": {"rows": f"""
        SELECT {MONTH} AS m, count(DISTINCT account)::int AS accounts,
               count(DISTINCT je_number)::int AS entries, count(*)::int AS lines,
               coalesce(sum(abs(signed)), 0)::float8 AS value
          FROM {TABLE} WHERE {SCOPE} GROUP BY 1 ORDER BY 1"""},
}
assert set(SQL_BY_KEY) == set(analytics.BODIES)

#: How many entries or lines an analytic lists to tick (the extract of the selection reads the same).
ITEM_CAP = 500
#: "Extract all to Excel": every entry or line, within what a workbook reads comfortably.
EXPORT_CAP = 20000


def _lines(where, join=""):
    return f"SELECT l.id FROM {TABLE} l {join} WHERE l.dataset_id = %(dataset)s AND l.engagement_id = %(engagement)s AND ({where})"


#: The analytics whose exceptions are entries or lines: the query of their entry numbers or line ids,
#: each the exception condition of its query in SQL_BY_KEY. The other analytics are summary tables.
ITEM_SQL = {
    "unbalanced-entries": ("entry", f"""
        SELECT je_number FROM {TABLE} WHERE {SCOPE}
         GROUP BY je_number HAVING abs(coalesce(sum(signed), 0)) > %(tolerance)s::numeric"""),
    "entry-date-lag": ("entry", f"""
        SELECT je_number FROM {TABLE}
         WHERE {SCOPE} AND journal_date IS NOT NULL AND entry_date IS NOT NULL
         GROUP BY je_number
        HAVING min(entry_date) - min(journal_date) > 3 OR min(entry_date) - min(journal_date) < 0"""),
    "unusual-account-combinations": ("entry", SQL_BY_KEY["unusual-account-combinations"]["rows"].rsplit(
        "SELECT coalesce(to_char(jd", 1)[0] + "SELECT je_number FROM scored WHERE rare > 0"),
    "self-review": ("entry", f"""
        SELECT je_number FROM {TABLE}
         WHERE {SCOPE} AND coalesce(trim(preparer), '') <> '' AND coalesce(trim(approver), '') <> ''
           AND lower(trim(preparer)) = lower(trim(approver))
         GROUP BY je_number"""),
    "exact-duplicates": ("line", _lines("TRUE", f"""
        JOIN (SELECT account, je_number, journal_date, coalesce(reference, '') AS ref, signed,
                     coalesce(je_description, '') AS des
                FROM {TABLE} WHERE {SCOPE}
               GROUP BY 1, 2, 3, 4, 5, 6 HAVING count(*) > 1) d
          ON d.account = l.account AND d.je_number = l.je_number
         AND d.journal_date IS NOT DISTINCT FROM l.journal_date AND d.ref = coalesce(l.reference, '')
         AND d.signed IS NOT DISTINCT FROM l.signed AND d.des = coalesce(l.je_description, '')""")),
    "zero-value": ("line", _lines("l.debit = 0 AND l.credit = 0")),
    "invalid-debit-credit": ("line", _lines(
        "(l.debit <> 0 AND l.credit <> 0) OR l.debit < 0 OR l.credit < 0 OR (l.debit = 0 AND l.credit = 0)")),
    "year-end-concentration": ("line", _lines(
        "l.journal_date IS NOT NULL AND l.journal_date > p.pe - (%(days)s::int) AND l.journal_date <= p.pe",
        "CROSS JOIN (SELECT period_end AS pe FROM ea_audit_engagement WHERE id = %(engagement)s) p")),
    "top-value": ("line", _lines("abs(l.signed)::float8 >= thr.p", f"""
        CROSS JOIN (SELECT coalesce(percentile_cont(%(percentile)s::float8) WITHIN GROUP (ORDER BY abs(signed)::float8), 0)::float8 AS p
                      FROM {TABLE} WHERE {SCOPE}) thr""")),
    "round-numbers": ("line", _lines("abs(l.signed) >= %(min)s::numeric AND mod(abs(l.signed), %(step)s::numeric) = 0")),
    "repeated-amounts": ("line", _lines("TRUE", f"""
        JOIN (SELECT abs(signed) AS a FROM {TABLE} WHERE {SCOPE} AND signed <> 0
               GROUP BY 1 HAVING count(*) >= %(minOcc)s::int) rep ON rep.a = abs(l.signed)""")),
    "rare-accounts": ("line", _lines("TRUE", f"""
        JOIN (SELECT account FROM {TABLE} WHERE {SCOPE}
               GROUP BY account HAVING count(*) <= %(rareMax)s::int) rare ON rare.account = l.account""")),
    "normal-side-exceptions": ("line", _lines("""
        (CASE WHEN left(l.account, 2) IN ('28','29','39','49','59') THEN -1
              WHEN left(l.account, 1) IN ('2','3','6') THEN 1
              WHEN left(l.account, 1) IN ('1','7') THEN -1
              ELSE 0 END) * sign(l.signed) = -1""")),
    "missing-mandatory-fields": ("line", _lines(
        "coalesce(trim(l.account), '') = '' OR coalesce(trim(l.je_number), '') = '' OR coalesce(trim(l.je_description), '') = ''"
        " OR l.journal_date IS NULL OR (l.debit = 0 AND l.credit = 0)")),
    "missing-references": ("line", _lines("coalesce(trim(l.reference), '') = ''")),
    "third-party-attribution": ("line", _lines(
        "EXISTS (SELECT 1 FROM unnest(%(prefixes)s::text[]) p WHERE l.account LIKE p || '%%')"
        " AND coalesce(trim(l.third_party_code), '') = ''")),
}
assert set(ITEM_SQL) <= set(SQL_BY_KEY)
assert ITEM_SQL["unusual-account-combinations"][1].count("scored AS") == 1

ENTRY_CTE = f"""
    WITH sel AS (
      SELECT je_number, count(DISTINCT account) FILTER (WHERE account = ANY(%(selected)s::text[])) AS matched
        FROM {TABLE} WHERE {SCOPE}
       GROUP BY je_number),
    ent AS (SELECT je_number FROM sel WHERE matched >= %(need)s::int),
    counter AS (
      SELECT l.* FROM {TABLE} l JOIN ent ON ent.je_number = l.je_number
       WHERE l.dataset_id = %(dataset)s AND l.engagement_id = %(engagement)s
         AND NOT (l.account = ANY(%(selected)s::text[])))"""

PAIR_CTE = f"""
    WITH shared AS (
      SELECT je_number FROM {TABLE}
       WHERE {SCOPE} AND account IN (%(a)s, %(b)s)
       GROUP BY je_number HAVING count(DISTINCT account) = 2),
    lines AS (
      SELECT l.* FROM {TABLE} l JOIN shared ON shared.je_number = l.je_number
       WHERE l.dataset_id = %(dataset)s AND l.engagement_id = %(engagement)s AND l.account IN (%(a)s, %(b)s))"""


class GlLineDrill(models.Model):
    _inherit = "ea.audit.gl.line"

    drill_filter = fields.Char(
        compute="_compute_drill_filter", search="_search_drill_filter",
        help="Search-only: the console's drill filter, so the native list shows exactly the lines it counted.",
    )

    def _compute_drill_filter(self):
        self.drill_filter = False

    def _search_drill_filter(self, operator, value):
        """The same WHERE as gl_drill_down, as a domain: the list, the search and the pivot all
        work on it, and the record rules still apply around it."""
        if operator == "in" and len(value) == 1:
            value = next(iter(value))
        elif operator != "=":
            return Domain.FALSE
        payload = json.loads(value)
        try:
            join, where, _order, params = correlation.drill_where(
                correlation.read_drill_filter(payload["filter"]), int(payload["dataset"]), int(payload["engagement"]),
            )
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error

        def to_sql(_model, alias, _query):
            return SQL(
                '"%s"."id" IN (SELECT l.id FROM ea_audit_gl_line l %s WHERE %s)' % (alias, join, where), **params,
            )

        return Domain.custom(to_sql=to_sql)


class DatasetConsole(models.Model):
    _inherit = "ea.audit.dataset"

    def action_open_console(self):
        self.ensure_one()
        as_root = self.sudo()
        return as_root.engagement_id.with_env(self.env).gl_open_console(dataset=as_root)


class EngagementGlConsole(models.Model):
    _inherit = "ea.audit.engagement"

    def _ea_gl_read(self, dataset_id):
        """Every read's guard: on the team, and a ledger of this file."""
        self.ensure_one()
        self._ea_require_access()
        return self._ea_gl_dataset(dataset_id)

    def _ea_locale(self):
        return "fr" if is_french(self.env) else "en"

    def _ea_gl_rows(self, query, args):
        self.env.cr.execute(query, args)
        return self.env.cr.dictfetchall()

    # ------------------------------------------------------------------
    # The catalogue (lib/gl-analytics.ts)
    # ------------------------------------------------------------------

    def gl_catalogue(self, dataset_id):
        """All thirty analytics, with their status against this ledger's mapping."""
        dataset = self._ea_gl_read(dataset_id)
        return analytics.catalogue(dataset.mapping, self._ea_locale())

    def gl_run_analytic(self, dataset_id, key, params=None):
        """runAnalytic: an honest `unavailable`, never a partial table."""
        self.ensure_one()
        self._ea_require_access()
        definition = analytics.ANALYTIC_BY_KEY.get(key)
        if not definition:
            raise rule_error(self.env, "unknown-analytic")
        dataset = self._ea_gl_dataset(dataset_id)
        locale = self._ea_locale()
        reason = analytics.status_of(definition, dataset.mapping, locale)
        if reason:
            return analytics.unavailable_result(definition, locale, reason)
        knobs = analytics.clamped(analytics.read_params(params))
        args = self._ea_gl_analytic_args(dataset, knobs)
        results = {name: self._ea_gl_rows(query, args) for name, query in SQL_BY_KEY[key].items()}
        return analytics.build_result(definition, results, locale, knobs)

    def _ea_gl_analytic_args(self, dataset, knobs):
        self.env["ea.audit.engagement"].flush_model(["period_end"])
        return dict(
            dataset=dataset.id, engagement=self.id, tolerance=TOLERANCE,
            days=knobs["days"], percentile=knobs["percentile"], min=knobs["min"], step=knobs["step"],
            minOcc=knobs["minOcc"], rareMax=knobs["rareMax"], pairMax=knobs["pairMax"],
            prefixes=knobs["prefixes"], topN=knobs["topN"],
        )

    def gl_analytic_items(self, dataset_id, key, params=None, picked=None, cap=ITEM_CAP):
        """The entries or lines behind an analytic's exceptions, to tick for testing (owner's mock-up
        "eagla-results-first", 18/11/2026). None for an analytic whose result is a summary table, or
        one that cannot run on this ledger. ``picked`` keeps only those entries (numbers) or lines (ids)."""
        self.ensure_one()
        self._ea_require_access()
        definition = analytics.ANALYTIC_BY_KEY.get(key)
        if not definition or key not in ITEM_SQL:
            return None
        dataset = self._ea_gl_dataset(dataset_id)
        if analytics.status_of(definition, dataset.mapping, self._ea_locale()):
            return None
        kind, ids = ITEM_SQL[key]
        args = self._ea_gl_analytic_args(dataset, analytics.clamped(analytics.read_params(params)))
        scope = "l.dataset_id = %(dataset)s AND l.engagement_id = %(engagement)s"
        if kind == "entry":
            where = f"{scope} AND l.je_number IN ({ids})"
            if picked is not None:
                where += " AND l.je_number = ANY(%(picked)s::text[])"
                args["picked"] = [str(value) for value in picked]
            total = self._ea_gl_rows(f"SELECT count(DISTINCT l.je_number)::int AS n FROM {TABLE} l WHERE {where}", args)[0]["n"]
            rows = self._ea_gl_rows(
                f"""SELECT l.je_number AS key, l.je_number,
                           to_char(min(l.journal_date), 'YYYY-MM-DD') AS journal_date,
                           min(l.journal_code) AS journal,
                           min(coalesce(l.je_description, l.line_description)) AS description,
                           count(*)::int AS lines,
                           coalesce(sum(l.debit), 0)::float8 AS debit, coalesce(sum(l.credit), 0)::float8 AS credit,
                           coalesce(sum(l.signed), 0)::float8 AS difference
                      FROM {TABLE} l WHERE {where}
                     GROUP BY l.je_number ORDER BY min(l.journal_date) NULLS LAST, l.je_number LIMIT {int(cap)}""",
                args,
            )
        else:
            where = f"{scope} AND l.id IN ({ids})"
            if picked is not None:
                where += " AND l.id = ANY(%(picked)s::int[])"
                args["picked"] = [int(value) for value in picked if str(value).isdigit()]
            total = self._ea_gl_rows(f"SELECT count(*)::int AS n FROM {TABLE} l WHERE {where}", args)[0]["n"]
            rows = self._ea_gl_rows(
                f"""SELECT l.id AS key, l.je_number, to_char(l.journal_date, 'YYYY-MM-DD') AS journal_date,
                           l.journal_code AS journal, l.account, l.account_name,
                           coalesce(l.line_description, l.je_description) AS description,
                           l.debit::float8 AS debit, l.credit::float8 AS credit
                      FROM {TABLE} l WHERE {where}
                     ORDER BY l.journal_date NULLS LAST, l.je_number, l.line_no, l.id LIMIT {int(cap)}""",
                args,
            )
        return {"kind": kind, "rows": rows, "total": total, "cap": int(cap)}

    def gl_entry_lines(self, dataset_id, je_numbers, cap=ITEM_CAP):
        """The lines of some journal entries, in their order: "Lines" under an entry to tick."""
        dataset = self._ea_gl_read(dataset_id)
        numbers = [str(number) for number in (je_numbers or [])][:int(cap)]
        rows = self._ea_gl_rows(
            f"""SELECT je_number, line_no, account, account_name,
                       coalesce(line_description, je_description) AS description,
                       debit::float8 AS debit, credit::float8 AS credit
                  FROM {TABLE} WHERE {SCOPE} AND je_number = ANY(%(numbers)s::text[])
                 ORDER BY je_number, line_no, id LIMIT {int(cap) * 20}""",
            {"dataset": dataset.id, "engagement": self.id, "numbers": numbers},
        )
        found = {}
        for row in rows:
            found.setdefault(row["je_number"], []).append(row)
        return found

    # ------------------------------------------------------------------
    # Correlation (lib/gl-correlation.ts)
    # ------------------------------------------------------------------

    def gl_accounts_for(self, dataset_id, search=None):
        """The picker: the accounts with their weight, by a piece of code or name. Capped."""
        dataset = self._ea_gl_read(dataset_id)
        term = correlation.like_term(search)
        args = {"dataset": dataset.id, "engagement": self.id, "term": "%" + term + "%"}
        where = (
            r" AND (account ILIKE %(term)s ESCAPE '\' OR coalesce(account_name, '') ILIKE %(term)s ESCAPE '\')"
            if term else ""
        )
        total = self._ea_gl_rows(f"SELECT count(DISTINCT account)::int AS n FROM {TABLE} WHERE {SCOPE}{where}", args)
        rows = self._ea_gl_rows(
            f"""SELECT account, min(account_name) AS name, count(*)::int AS lines,
                       count(DISTINCT je_number)::int AS entries,
                       coalesce(sum(debit), 0)::float8 AS debit,
                       coalesce(sum(credit), 0)::float8 AS credit,
                       coalesce(sum(signed), 0)::float8 AS signed
                  FROM {TABLE} WHERE {SCOPE}{where}
                 GROUP BY account ORDER BY account LIMIT {correlation.ACCOUNT_CAP}""",
            args,
        )
        return correlation.shape_accounts(rows, total[0]["n"] if total else 0)

    def _ea_service(self, function, *args):
        try:
            return function(*args)
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error

    def gl_entry_analysis(self, dataset_id, accounts, mode="any", rank="abs", limit=20, period="month"):
        """What else the entries touching these accounts posted to. The selected accounts are not
        their own counterparts."""
        dataset = self._ea_gl_read(dataset_id)
        selected = self._ea_service(correlation.read_accounts, accounts, correlation.MAX_ENTRY_ACCOUNTS)
        options = correlation.entry_args(mode, rank, limit, period)
        args = {
            "dataset": dataset.id, "engagement": self.id, "selected": selected,
            "need": len(selected) if options["mode"] == "all" else 1,
        }
        head = self._ea_gl_rows(
            f"""{ENTRY_CTE}
                SELECT (SELECT count(*)::int FROM ent) AS entries, count(DISTINCT account)::int AS accounts,
                       coalesce(sum(debit), 0)::float8 AS debit, coalesce(sum(credit), 0)::float8 AS credit,
                       coalesce(sum(signed), 0)::float8 AS net
                  FROM counter""",
            args,
        )
        tops = self._ea_gl_rows(
            f"""{ENTRY_CTE}
                SELECT account, min(account_name) AS name,
                       coalesce(sum(signed), 0)::float8 AS net, coalesce(sum(abs(signed)), 0)::float8 AS gross,
                       count(*)::int AS postings, count(DISTINCT je_number)::int AS entries
                  FROM counter GROUP BY account
                 ORDER BY {correlation.RANK_SQL[options["rank"]]} LIMIT {options["cap"]}""",
            args,
        )
        shown = [row["account"] for row in tops]
        grid = self._ea_gl_rows(
            f"""{ENTRY_CTE}
                SELECT {correlation.PERIOD_SQL[options["period"]]} AS m, account, coalesce(sum(signed), 0)::float8 AS v
                  FROM counter WHERE account = ANY(%(shown)s::text[]) GROUP BY 1, 2 ORDER BY 1""",
            dict(args, shown=shown),
        ) if shown else []
        return correlation.shape_entry(selected, options, head[0] if head else None, tops, grid)

    def gl_two_account_correlation(self, dataset_id, a, b):
        """Restricted to the entries where the two accounts actually meet: that measures the
        relationship between them, not the client's seasonal rhythm."""
        self.ensure_one()
        self._ea_require_access()
        account_a, account_b = self._ea_service(correlation.read_pair, a, b)
        dataset = self._ea_gl_dataset(dataset_id)
        args = {"dataset": dataset.id, "engagement": self.id, "a": account_a, "b": account_b}
        rows = self._ea_gl_rows(
            f"""{PAIR_CTE}
                SELECT {MONTH} AS m,
                       coalesce(sum(signed) FILTER (WHERE account = %(a)s), 0)::float8 AS a,
                       coalesce(sum(signed) FILTER (WHERE account = %(b)s), 0)::float8 AS b
                  FROM lines GROUP BY 1 ORDER BY 1""",
            args,
        )
        common = self._ea_gl_rows(f"{PAIR_CTE} SELECT (SELECT count(*)::int FROM shared) AS n", args)
        return correlation.shape_correlation(account_a, account_b, rows, common[0]["n"] if common else 0)

    def _ea_drill_sql(self, dataset_id, raw_filter):
        dataset = self._ea_gl_read(dataset_id)
        cleaned = self._ea_service(correlation.read_drill_filter, raw_filter)
        return (dataset, cleaned) + self._ea_service(correlation.drill_where, cleaned, dataset.id, self.id)

    def gl_drill_down(self, dataset_id, raw_filter=None):
        """The lines behind a cell. Paged and capped: evidence to read, not a copy of the ledger."""
        _dataset, cleaned, join, where, order, params = self._ea_drill_sql(dataset_id, raw_filter)
        limit, offset = correlation.drill_page(cleaned)
        total = self._ea_gl_rows(
            f"SELECT count(*)::int AS n, coalesce(sum(l.signed), 0)::float8 AS s FROM {TABLE} l {join} WHERE {where}", params,
        )[0]
        rows = self._ea_gl_rows(
            f"""SELECT l.line_no, l.account, l.account_name, l.je_number, l.journal_code,
                       to_char(l.journal_date, 'YYYY-MM-DD') AS journal_date,
                       to_char(l.entry_date, 'YYYY-MM-DD') AS entry_date,
                       l.reference, coalesce(l.line_description, l.je_description) AS line_description,
                       l.third_party_code, l.third_party_name, l.preparer, l.reviewer,
                       l.debit::float8 AS debit, l.credit::float8 AS credit, l.signed::float8 AS signed
                  FROM {TABLE} l {join} WHERE {where}
                 ORDER BY {order} LIMIT {limit} OFFSET {offset}""",
            params,
        )
        return correlation.shape_drill(rows, total["n"], total["s"], limit, offset)

    def gl_drill_action(self, dataset_id, raw_filter, name=None, grouped=False):
        """The drill as Odoo's own list, on a domain made of the same filter."""
        dataset, _cleaned, _join, _where, _order, _params = self._ea_drill_sql(dataset_id, raw_filter)
        token = json.dumps({"dataset": dataset.id, "engagement": self.id, "filter": raw_filter or {}})
        return self._ea_list(
            "ea.audit.gl.line", name or self.env._("Ledger lines"),
            [("ea_audit_tools.view_gl_line_list", "list"), ("ea_audit_tools.view_gl_line_pivot", "pivot")],
            {
                "domain": [("dataset_id", "=", dataset.id), ("drill_filter", "=", token)],
                "search_view_id": self.env.ref("ea_audit_tools.view_gl_line_search").id,
                "limit": correlation.PAGE,
                "context": dict(
                    {"default_engagement_id": self.id, "ea_engagement_id": self.id},
                    **({"search_default_group_entry": 1} if grouped else {}),
                ),
            },
        )

    def gl_reconcile_figure(self, dataset_id, accounts, opening, closing):
        """UAT run 2 B68: opening + the drilled movements against the lead-schedule figure."""
        drilled = self.gl_drill_down(dataset_id, {"accounts": accounts, "limit": 1})
        return correlation.reconcile_figure(opening, closing, drilled["sumSigned"], drilled["total"])

    # ------------------------------------------------------------------
    # GL insights (lib/gl-insights.ts)
    # ------------------------------------------------------------------

    def _ea_gl_datasets(self):
        """glDatasets: CY is the post-audit ledger, else the pre-audit one. PY the prior-year one."""
        self.ensure_one()
        self._ea_require_access()
        found = self.env["ea.audit.dataset"].sudo().search([
            ("engagement_id", "=", self.id), ("kind", "=", "journal_entries"), ("superseded_at", "=", False),
            ("timing", "in", CURRENT_YEAR_TIMINGS),
        ])

        def latest(timing):
            return found.filtered(lambda dataset: dataset.timing == timing and dataset.mapping)[:1]

        return latest("post_audit") or latest("pre_audit"), latest("prior_year")

    def _ea_distinct_values(self, dataset, column):
        return [row["v"] for row in self._ea_gl_rows(
            """SELECT DISTINCT trim(data->>%(column)s) AS v FROM ea_audit_dataset_row
                WHERE dataset_id = %(dataset)s AND engagement_id = %(engagement)s AND coalesce(trim(data->>%(column)s), '') <> ''
                ORDER BY 1""",
            {"dataset": dataset.id, "engagement": self.id, "column": column},
        )]

    def gl_preparers_reviewers(self):
        cy, py = self._ea_gl_datasets()
        if not cy:
            return None
        roles = []
        for key in insights.ROLE_KEYS:
            cy_column = cy.mapping.get(key)
            py_column = (py.mapping or {}).get(key) if py else None
            roles.append(insights.role_insight(
                key,
                self._ea_distinct_values(cy, cy_column) if cy_column else None,
                self._ea_distinct_values(py, py_column) if py_column else None,
            ))
        return {"roles": roles, "hasPy": bool(py)}

    def _ea_class_totals(self, dataset, account_column):
        return insights.class_totals(self._ea_gl_rows(
            """SELECT left(trim(data->>%(column)s), 1) AS cls, count(*)::int AS lines,
                      coalesce(sum(abs(coalesce(amount, 0))), 0)::text AS gross
                 FROM ea_audit_dataset_row WHERE dataset_id = %(dataset)s AND engagement_id = %(engagement)s
                GROUP BY 1""",
            {"dataset": dataset.id, "engagement": self.id, "column": account_column},
        ))

    def gl_class_volumes(self):
        cy, py = self._ea_gl_datasets()
        if not cy or not cy.mapping.get("account"):
            return None
        py_column = (py.mapping or {}).get("account") if py else None
        return insights.class_volume_rows(
            self._ea_class_totals(cy, cy.mapping["account"]),
            self._ea_class_totals(py, py_column) if py_column else None,
        )

    def _ea_je_expression(self, mapping, args):
        """jeExpr: the entry identity over the raw row, or None."""
        columns = je_key_columns(mapping)
        if columns:
            parts = []
            for position, header in enumerate(columns):
                args["key%d" % position] = header
                parts.append("coalesce(data->>%%(key%d)s, '')" % position)
            args["joiner"] = JE_KEY_JOIN
            return "concat_ws(%%(joiner)s, %s)" % ", ".join(parts)
        if not mapping.get("jeNumber"):
            return None
        args["je_header"] = mapping["jeNumber"]
        return "data->>%(je_header)s"

    def _ea_raw_lines(self, dataset, select, args):
        """Yield tuples from the raw rows, a batch at a time: the source held them all in memory."""
        args = dict(args, dataset=dataset.id, engagement=self.id, batch=BATCH, after=0)
        while True:
            self.env.cr.execute(
                f"""SELECT row_no, {select} FROM ea_audit_dataset_row
                     WHERE dataset_id = %(dataset)s AND engagement_id = %(engagement)s AND row_no > %(after)s
                     ORDER BY row_no LIMIT %(batch)s""",
                args,
            )
            batch = self.env.cr.fetchall()
            if not batch:
                return
            args["after"] = batch[-1][0]
            for row in batch:
                yield row[1:]
            if len(batch) < BATCH:
                return

    def gl_weekday_analysis(self):
        cy, _py = self._ea_gl_datasets()
        if not cy or not cy.mapping.get("journalDate"):
            return None
        args = {"journal_date": cy.mapping["journalDate"]}
        je = self._ea_je_expression(cy.mapping, args)
        if not je:
            return None
        return insights.weekday_analysis(self._ea_raw_lines(
            cy, "data->>%%(journal_date)s, %s, abs(coalesce(amount, 0))::text" % je, args,
        ))

    def gl_entry_lag(self):
        """None when the entry date is not mapped: the screen says so."""
        cy, _py = self._ea_gl_datasets()
        if not cy or not cy.mapping.get("jeDate") or not cy.mapping.get("journalDate"):
            return None
        args = {"journal_date": cy.mapping["journalDate"], "entry_date": cy.mapping["jeDate"]}
        je = self._ea_je_expression(cy.mapping, args)
        if not je:
            return None
        return insights.entry_lag(self._ea_raw_lines(cy, "%s, data->>%%(journal_date)s, data->>%%(entry_date)s" % je, args))

    def gl_account_prefixes(self):
        """The distinct 3-digit prefixes of the CY ledger, for the correlation study's picker."""
        cy, _py = self._ea_gl_datasets()
        if not cy or not cy.mapping.get("account"):
            return []
        args = {"dataset": cy.id, "engagement": self.id, "account": cy.mapping["account"], "name": cy.mapping.get("accountName")}
        name = "min(nullif(trim(data->>%(name)s), ''))" if args["name"] else "NULL"
        return [{"prefix": row["prefix"], "lines": row["lines"], "name": row["name"]} for row in self._ea_gl_rows(
            f"""SELECT left(trim(data->>%(account)s), 3) AS prefix, count(*)::int AS lines, {name} AS name
                  FROM ea_audit_dataset_row
                 WHERE dataset_id = %(dataset)s AND engagement_id = %(engagement)s AND trim(data->>%(account)s) ~ '^[0-9]{{3}}'
                 GROUP BY 1 ORDER BY 1""",
            args,
        )]

    def gl_correlation_matrix(self, accounts):
        """The route answers no-dataset where the lib returns null."""
        cy, _py = self._ea_gl_datasets()
        cleaned = self._ea_service(insights.read_prefixes, accounts)
        if not cy or not cy.mapping.get("account") or not cy.mapping.get("journalDate"):
            raise rule_error(self.env, "no-dataset")
        args = {"account": cy.mapping["account"], "journal_date": cy.mapping["journalDate"]}
        je = self._ea_je_expression(cy.mapping, args)
        if not je:
            raise rule_error(self.env, "no-dataset")
        return insights.correlation_matrix(self._ea_raw_lines(
            cy, "data->>%%(account)s, %s, data->>%%(journal_date)s, abs(coalesce(amount, 0))::text" % je, args,
        ), cleaned)

    # ------------------------------------------------------------------
    # Screens
    # ------------------------------------------------------------------

    def gl_open_console(self, dataset=None, accounts=None, opening=None, closing=None):
        """A ledger's console; from a lead-schedule figure its accounts arrive selected, and the
        figure is there to reconcile to."""
        self.ensure_one()
        self._ea_require_access()
        if not dataset:
            dataset = self._ea_current_dataset("journal_entries")
        self._ea_gl_dataset(dataset.id)
        wanted = correlation.arrival_accounts(accounts or [])
        vals = {"engagement_id": self.id, "dataset_id": dataset.id, "selected_accounts": ", ".join(wanted)}
        if wanted and opening is not None and closing is not None:
            vals.update({
                "figure_accounts": ",".join(wanted), "figure_set": True,
                "figure_opening": opening, "figure_closing": closing,
            })
        console = self.env["ea.audit.gl.console"].create(vals)
        return console._ea_reopen()

    def _ea_gl_item_sheet(self, dataset_id, items, fr):
        """The entries (with all their lines) or the lines an analytic listed, as one register."""
        def day(iso):
            return "%s/%s/%s" % (iso[8:10], iso[5:7], iso[:4]) if iso else ""

        if items["kind"] == "entry":
            head = (
                ["N° écriture", "Date", "Journal", "Libellé de l'écriture", "Compte", "Intitulé du compte", "Libellé de la ligne", "Débit", "Crédit"]
                if fr else ["Entry", "Date", "Journal", "Entry description", "Account", "Account name", "Line description", "Debit", "Credit"]
            )
            lines = self.gl_entry_lines(dataset_id, [row["key"] for row in items["rows"]], cap=max(len(items["rows"]), 1))
            rows = [
                [entry["je_number"], day(entry["journal_date"]), entry["journal"], entry["description"],
                 line["account"], line["account_name"], line["description"], line["debit"], line["credit"]]
                for entry in items["rows"] for line in lines.get(entry["je_number"], [])
            ]
        else:
            head = (
                ["N° écriture", "Date", "Journal", "Compte", "Intitulé du compte", "Libellé", "Débit", "Crédit"]
                if fr else ["Entry", "Date", "Journal", "Account", "Account name", "Description", "Debit", "Credit"]
            )
            rows = [
                [line["je_number"], day(line["journal_date"]), line["journal"], line["account"], line["account_name"],
                 line["description"], line["debit"], line["credit"]]
                for line in items["rows"]
            ]
        return head, rows

    def _ea_export_gl_selection(self, fr):
        """"Extract the selection": only the entries or lines ticked for testing, entries with their lines."""
        from ..exports import simple_workbook

        request_ = self.env.context.get("ea_gl_selection") or {}
        dataset, key = request_.get("dataset"), request_.get("key")
        items = self.gl_analytic_items(dataset, key, request_.get("params"), picked=request_.get("picked") or [])
        if items is None:
            raise rule_error(self.env, "unknown-analytic")
        result_title = analytics.ANALYTIC_BY_KEY[key]["titleFr" if fr else "titleEn"]
        head, rows = self._ea_gl_item_sheet(dataset, items, fr)
        title = "%s — %s" % (result_title, "sélection pour test" if fr else "selected for testing")
        content = simple_workbook(key[:28], head, rows, title=title)
        return "gl-%s-selection-%s.xlsx" % (key, self._ea_export_slug()), content

    def _ea_export_gl_analytic(self, fr):
        """An analytic's rows. The console says which, and with which knobs. An analytic that lists
        entries or lines gives them all on a second sheet ("Extract all to Excel")."""
        from ..exports import registers_workbook

        request_ = self.env.context.get("ea_gl_analytic") or {}
        result = self.gl_run_analytic(request_.get("dataset"), request_.get("key"), request_.get("params"))
        if result.get("unavailable"):
            rows = [[result["unavailable"]]]
            head = [result["title"]]
        else:
            head = ["Mois" if fr else "Month"] + [column["label"] for column in result["columns"]]
            rows = [[row["month"]] + row["cells"] for row in result["rows"]]
            if result.get("totals"):
                rows.append(["Total"] + result["totals"])
            rows.append([])
            rows.append(["%s : %s / %s" % ("Exceptions à examiner" if fr else "Exceptions to consider", result["exceptions"], result["population"])])
            if result.get("note"):
                rows.append([result["note"]])
        sheets = [(result["key"][:28], head, rows, "%s — %s" % (result["title"], result["objective"]))]
        items = None if result.get("unavailable") else self.gl_analytic_items(
            request_.get("dataset"), result["key"], request_.get("params"), cap=EXPORT_CAP,
        )
        if items is not None:
            item_head, item_rows = self._ea_gl_item_sheet(request_.get("dataset"), items, fr)
            sheet_name = ("Écritures" if fr else "Entries") if items["kind"] == "entry" else ("Lignes" if fr else "Lines")
            sheets.append((sheet_name, item_head, item_rows, result["title"]))
        return "gl-%s-%s.xlsx" % (result["key"], self._ea_export_slug()), registers_workbook(sheets)


class LeadFigure(models.AbstractModel):
    """The figure links of ApSchedules: the ledger behind a lead-schedule figure."""

    _inherit = "ea.audit.lead.comment.mixin"

    def _ea_figure_accounts(self):
        raise NotImplementedError

    def action_open_gl_console(self):
        self.ensure_one()
        as_root = self.sudo()
        engagement = as_root.engagement_id.with_env(self.env)
        engagement._ea_require_access()
        accounts, closing = as_root._ea_figure_accounts()
        version = as_root.engagement_id._ea_current_tb_version()
        opening = js_sum(js_round(line.opening) for line in version.line_ids if line.account_code in accounts) if version else 0
        return engagement.gl_open_console(accounts=accounts, opening=opening, closing=closing)


class LeadScheduleFigure(models.Model):
    _inherit = "ea.audit.lead.schedule"

    def _ea_figure_accounts(self):
        return self.line_ids.mapped("account_code"), self.closing


class LeadLineFigure(models.Model):
    _inherit = "ea.audit.lead.line"

    def _ea_figure_accounts(self):
        return [self.account_code], self.closing
