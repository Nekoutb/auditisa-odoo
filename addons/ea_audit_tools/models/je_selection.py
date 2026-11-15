"""The journal-entry selection studio (C.7.8): SQL narrows, services/je_selection.py decides."""
import re

from odoo import api, fields, models

from ..rules import rule_error
from ..services.errors import ServiceError
from ..services.gl_line import TOLERANCE
from ..services.je_catalogue import JE_CRITERIA
from ..services.je_selection import (
    CANDIDATE_CEILING, CLASS_PREFIXES, CRITERION_BY_KEY, DEFAULT_SELECTION_LIMIT, PAIRING_BY_KEY, SELECTION_CAP, coverage_of,
    describe_selection_design, filler_regex, normalise_user_rule, resolve_settings, select_from_candidates, t,
)
from ..workbooks import je_workbook
from .tool_record import french_date, is_french

_ISO = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
_STUDIO_KIND = re.compile(r"^je_studio_(\d+)$")
DESCRIPTION_SQL = "coalesce(nullif(trim(l.line_description), ''), nullif(trim(l.je_description), ''), '')"
SCOPE = "l.dataset_id = %(dataset)s AND l.engagement_id = %(engagement)s"


class PublicHoliday(models.Model):
    """The seeded national calendar, read-only. Reference data, no engagement."""

    _name = "ea.audit.public.holiday"
    _description = "Public holiday"
    _order = "holiday_date"

    country = fields.Char(required=True, index=True, readonly=True)
    holiday_date = fields.Date(required=True, readonly=True)
    label_en = fields.Char(required=True, readonly=True)
    label_fr = fields.Char(required=True, readonly=True)
    movable = fields.Boolean(readonly=True)
    source = fields.Char(readonly=True)

    _uniq = models.Constraint("UNIQUE(country, holiday_date, label_en)", "This holiday is already in the calendar.")


class FirmHoliday(models.Model):
    """A date the seeded calendar does not carry, such as the Eid dates declared each year. No
    engagement: it applies to the whole firm. Tied to a file, it follows that file's team."""

    _name = "ea.audit.firm.holiday"
    _description = "Firm holiday"
    _order = "holiday_date"

    engagement_id = fields.Many2one("ea.audit.engagement", index=True, ondelete="cascade")
    country = fields.Char(required=True)
    holiday_date = fields.Date(required=True)
    label_en = fields.Char(required=True)
    label_fr = fields.Char(required=True)

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

    def remove(self):
        """removeFirmHoliday. The seeded national calendar is not writable from here."""
        self.ensure_one()
        as_root = self.sudo()
        if as_root.engagement_id:
            as_root.engagement_id.with_env(self.env)._ea_tool_guard()
        else:
            self.env["ea.audit.engagement"]._ea_require_write()
        as_root.unlink()
        return True


class JeDesign(models.Model):
    """The S5.4 selection design. Only the explicit instruction records one (UAT run 2 B16); the
    design it replaces stays as dated history. Append-only."""

    _name = "ea.audit.je.design"
    _inherit = ["ea.audit.tool.record"]
    _description = "Journal-entry selection design"
    _order = "id desc"
    _rec_name = "recorded_at"

    dataset_id = fields.Many2one("ea.audit.dataset", ondelete="set null")
    design = fields.Json(required=True)
    recorded_by_id = fields.Many2one("res.users", string="Recorded by", ondelete="restrict")
    recorded_at = fields.Datetime(string="Recorded on", required=True)
    selected_lines = fields.Integer()
    population_lines = fields.Integer()
    is_current = fields.Boolean(string="Current", compute="_compute_current", compute_sudo=True)
    summary = fields.Text(compute="_compute_summary", compute_sudo=True)

    def _compute_current(self):
        for record in self:
            latest = self.sudo().search([("engagement_id", "=", record.engagement_id.id)], order="id desc", limit=1)
            record.is_current = latest == record

    @api.depends_context("lang")
    def _compute_summary(self):
        locale = "fr" if is_french(self.env) else "en"
        for record in self:
            design = dict(record.design or {}, recordedBy=record.recorded_by_id.name)
            record.summary = describe_selection_design(design, locale, french_date(record.recorded_at))


class EngagementJe(models.Model):
    _inherit = "ea.audit.engagement"

    def _ea_load_holidays(self, country):
        """The national calendar merged with what the firm added. A firm date takes precedence."""
        self.ensure_one()
        holidays = {}
        for row in self.env["ea.audit.public.holiday"].sudo().search([("country", "=", country)]):
            holidays[row.holiday_date.isoformat()] = {"labelEn": row.label_en, "labelFr": row.label_fr, "origin": "national"}
        for row in self.env["ea.audit.firm.holiday"].sudo().search([
            ("country", "=", country), "|", ("engagement_id", "=", False), ("engagement_id", "=", self.id),
        ]):
            holidays[row.holiday_date.isoformat()] = {"labelEn": row.label_en, "labelFr": row.label_fr, "origin": "firm"}
        return holidays

    def list_holidays(self, country="CM"):
        self.ensure_one()
        self._ea_require_read()
        code = country.upper() if re.fullmatch(r"[A-Za-z]{2}", country or "") else "CM"
        holidays = self._ea_load_holidays(code)
        return [{"date": key, **holidays[key]} for key in sorted(holidays)]

    def add_firm_holiday(self, country, holiday_date, label_en, label_fr, engagement_scoped=False):
        """addFirmHoliday. A firm-wide date is a firm setting; one tied to a file follows its team."""
        self.ensure_one()
        country = (country or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{2}", country):
            raise rule_error(self.env, "invalid-country")
        date = str(holiday_date or "").strip()
        if not _ISO.match(date):
            raise rule_error(self.env, "invalid-date")
        label_en, label_fr = (label_en or "").strip()[:120], (label_fr or "").strip()[:120]
        if not label_en or not label_fr:
            raise rule_error(self.env, "label-required")
        if engagement_scoped:
            self._ea_tool_guard()
        else:
            self._ea_require_write()
        return self.env["ea.audit.firm.holiday"].sudo().create({
            "engagement_id": self.id if engagement_scoped else False, "country": country, "holiday_date": date,
            "label_en": label_en, "label_fr": label_fr,
        })

    def _ea_je_candidates(self, dataset, criteria, rules, settings, holidays, mode):
        """The narrowing query: one OR-clause per criterion. Classification is done once per distinct
        account (UAT B77), and the entry CTE is materialised so the aggregate is not inlined."""
        params = {"dataset": dataset.id, "engagement": self.id}

        def add(value):
            key = "p%d" % len(params)
            params[key] = value
            return "%%(%s)s" % key

        wants_pairing = "unusual-pairing" in criteria
        wants_year_end = "year-end-volume" in criteria
        date_column = "entry_date" if settings["dateBasis"] == "entry" else "journal_date"
        ctes = []
        if wants_pairing:
            ctes.append(
                "account_class AS (SELECT a.account, (SELECT c.klass FROM unnest(%s::text[], %s::text[]) AS c(prefix, klass) "
                "WHERE a.account LIKE c.prefix || '%%%%' ORDER BY length(c.prefix) DESC LIMIT 1) AS klass "
                "FROM (SELECT DISTINCT l.account FROM ea_audit_gl_line l WHERE %s) a)" % (
                    add([row["prefix"] for row in CLASS_PREFIXES]), add([row["klass"] for row in CLASS_PREFIXES]), SCOPE,
                )
            )
        ctes.append(
            "base AS (SELECT l.je_number, l.journal_date, l.signed, %s AS klass FROM ea_audit_gl_line l %s WHERE %s)" % (
                "ac.klass" if wants_pairing else "NULL::text",
                "LEFT JOIN account_class ac ON ac.account = l.account" if wants_pairing else "", SCOPE,
            )
        )
        ctes.append(
            "entry AS MATERIALIZED (SELECT je_number, count(*)::int AS lines, coalesce(sum(abs(signed)), 0)::float8 AS gross, "
            "min(journal_date) AS jd, coalesce(array_agg(DISTINCT klass) FILTER (WHERE klass IS NOT NULL), ARRAY[]::text[]) AS classes "
            "FROM base GROUP BY je_number)"
        )
        if wants_year_end:
            measure = "gross" if settings["volumeBasis"] == "value" else "lines"
            ctes.append(
                "top_entry AS (SELECT je_number, row_number() OVER (ORDER BY %(m)s DESC, je_number)::int AS rank "
                "FROM entry, (SELECT period_end AS pe FROM ea_audit_engagement WHERE id = %%(engagement)s) p "
                "WHERE jd IS NOT NULL AND jd > p.pe - %(days)s::int AND jd <= p.pe ORDER BY %(m)s DESC, je_number LIMIT %(top)s)" % {
                    "m": measure, "days": add(settings["yearEndDays"]), "top": add(settings["topEntries"]),
                }
            )
        clauses = []
        for key in criteria:
            if key == "weekend-posting":
                clauses.append("extract(isodow FROM l.%s) IN (6, 7)" % date_column)
            elif key == "no-description":
                clauses.append("%s = ''" % DESCRIPTION_SQL)
            elif key == "public-holiday":
                # an empty calendar must not degrade into "every date matches"
                if holidays:
                    clauses.append("l.%s = ANY(%s::date[])" % (date_column, add(list(holidays))))
            elif key == "round-amount":
                clauses.append("(abs(l.signed) >= %s::numeric AND mod(abs(l.signed), %s::numeric) = 0)" % (add(settings["roundMin"]), add(settings["roundStep"])))
            elif key == "unusual-pairing":
                pairs = ["e.classes @> %s::text[]" % add([PAIRING_BY_KEY[p]["left"], PAIRING_BY_KEY[p]["right"]]) for p in settings["pairings"]]
                if pairs:
                    clauses.append("(%s)" % " OR ".join(pairs))
            elif key == "year-end-volume":
                clauses.append("te.rank IS NOT NULL")
            elif key == "incomplete-description":
                clauses.append(
                    "(%(d)s <> '' AND (char_length(%(d)s) < %(c)s::int "
                    "OR coalesce(array_length(regexp_split_to_array(%(d)s, '\\s+'), 1), 0) < %(w)s::int "
                    "OR %(d)s !~ '[[:alpha:]]' OR %(d)s ~* %(f)s))" % {
                        "d": DESCRIPTION_SQL, "c": add(settings["minDescriptionChars"]), "w": add(settings["minDescriptionWords"]),
                        "f": add(filler_regex(settings["uninformativeTerms"])),
                    }
                )
            elif key in ("preparer-is-reviewer", "preparer-is-approver"):
                other = "reviewer" if key == "preparer-is-reviewer" else "approver"
                clauses.append("(nullif(lower(trim(l.preparer)), '') IS NOT NULL AND lower(trim(l.preparer)) = lower(trim(l.%s)))" % other)
        if mode == "all" and rules:
            clauses.append("(%s)" % " AND ".join(_rule_sql(rule, add) for rule in rules))
        else:
            clauses.extend(_rule_sql(rule, add) for rule in rules)
        if not clauses:
            return []
        sql = """WITH {ctes}
            SELECT l.id, l.line_no, l.je_number, l.journal_code, to_char(l.journal_date, 'YYYY-MM-DD'), to_char(l.entry_date, 'YYYY-MM-DD'),
                   l.account, l.account_name, l.je_description, l.line_description, l.debit::float8, l.credit::float8, l.signed::float8,
                   l.preparer, l.reviewer, l.approver, l.reference, l.third_party_code, l.third_party_name, l.cost_center,
                   e.lines, e.gross, e.classes, {rank}
              FROM ea_audit_gl_line l JOIN entry e ON e.je_number = l.je_number {join}
             WHERE {scope} AND ({clauses})
             ORDER BY l.journal_date NULLS LAST, l.je_number, l.line_no
             LIMIT {ceiling}""".format(
            ctes=",\n".join(ctes), rank="te.rank" if wants_year_end else "NULL::int",
            join="LEFT JOIN top_entry te ON te.je_number = l.je_number" if wants_year_end else "",
            scope=SCOPE, clauses=" OR ".join(clauses), ceiling=CANDIDATE_CEILING,
        )
        self.env.cr.execute(sql, params)

        def round2(value):
            return int(value * 100 + (0.5 if value >= 0 else -0.5)) / 100

        out = []
        for row in self.env.cr.fetchall():
            out.append({
                "id": row[0], "lineNo": row[1], "jeNumber": row[2], "journalCode": row[3], "journalDate": row[4], "entryDate": row[5],
                "account": row[6], "accountName": row[7], "jeDescription": row[8], "lineDescription": row[9],
                "debit": round2(row[10]), "credit": round2(row[11]), "signed": round2(row[12]), "preparer": row[13], "reviewer": row[14],
                "approver": row[15], "reference": row[16], "thirdPartyCode": row[17], "thirdPartyName": row[18], "costCenter": row[19],
                "entry": {"lines": row[20], "grossValue": round2(row[21]), "classes": row[22] or [], "yearEndRank": row[23]},
            })
        return out

    def je_run_selection(self, dataset_id, request=None):
        """runSelection. Reads only, so an archived file answers it."""
        self.ensure_one()
        self._ea_require_read()
        dataset = self._ea_gl_dataset(dataset_id)
        request = request or {}
        params = request.get("params") or {}
        locale = params.get("locale") or ("fr" if is_french(self.env) else "en")
        settings = resolve_settings(params)
        criteria = [key for key in (request.get("criteria") or []) if key in CRITERION_BY_KEY and key != "user-defined"]
        try:
            rules = [normalise_user_rule(rule, index) for index, rule in enumerate((request.get("userRules") or [])[:20])]
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error
        if not criteria and not rules:
            raise rule_error(self.env, "no-criteria")
        try:
            requested = int(float(request.get("limit") or DEFAULT_SELECTION_LIMIT))
        except (TypeError, ValueError):
            requested = DEFAULT_SELECTION_LIMIT
        limit = min(SELECTION_CAP, max(1, requested or DEFAULT_SELECTION_LIMIT))
        offset = max(0, int(request.get("offset") or 0))
        holidays = self._ea_load_holidays(settings["country"]) if "public-holiday" in criteria else {}
        column = "entry_date" if settings["dateBasis"] == "entry" else "journal_date"
        self.env.cr.execute(
            "SELECT count(*), count(DISTINCT je_number), count(*) FILTER (WHERE %s IS NOT NULL) FROM ea_audit_gl_line "
            "WHERE dataset_id = %%s AND engagement_id = %%s" % column, [dataset.id, self.id],
        )
        lines, entries, dated = self.env.cr.fetchone()
        mode = "all" if request.get("userRulesMode") == "all" else "any"
        candidates = self._ea_je_candidates(dataset, criteria, rules, settings, holidays, mode)
        core = select_from_candidates(candidates, {
            "locale": locale, "settings": settings, "criteria": criteria, "userRules": rules, "userRulesMode": mode, "holidays": holidays,
        })
        notes = []
        if "public-holiday" in criteria and not holidays:
            notes.append(t(
                locale,
                "No public holiday is recorded for %s. The criterion selected nothing because the calendar is empty, not because the ledger is clean." % settings["country"],
                "Aucun jour férié n'est enregistré pour %s. Le critère n'a rien retenu parce que le calendrier est vide, non parce que le grand livre l'est." % settings["country"],
            ))
        ceiling = len(candidates) >= CANDIDATE_CEILING
        if ceiling:
            notes.append(t(
                locale,
                "The criteria flagged at least %d lines, the ceiling this engine reasons about. Tighten the thresholds before citing coverage: the counts below are floors, not totals." % CANDIDATE_CEILING,
                "Les critères ont retenu au moins %d lignes, plafond que ce moteur traite. Resserrez les seuils avant de citer une couverture : les nombres ci-dessous sont des minorants, non des totaux." % CANDIDATE_CEILING,
            ))
        notes.append(t(
            locale,
            "Selection is risk-directed, not random. International Audit Methodology 321.03 and ISA 240 rule out a random sample of 25 entries for journal-entry testing; every line below was chosen by a stated criterion and carries the reason it was chosen.",
            "La sélection est orientée par le risque, non aléatoire. La méthodologie d'audit internationale 321.03 et la norme ISA 240 excluent un échantillon aléatoire de 25 écritures pour le test des écritures ; chaque ligne ci-dessous a été retenue par un critère énoncé et porte le motif de sa sélection.",
        ))
        return {
            "criteria": coverage_of(criteria, rules, settings, core, locale),
            "population": {"lines": lines, "entries": entries, "datedLines": dated},
            "selectedLines": core["selectedLines"], "selectedEntries": core["selectedEntries"],
            "lines": core["lines"][offset:offset + limit], "limit": limit, "offset": offset,
            "truncated": core["selectedLines"] > offset + limit, "ceilingHit": ceiling, "notes": notes,
        }

    def je_record_design(self, dataset_id, request):
        """recordSelectionDesign: on the explicit instruction only, by a writer, on an open file. A run
        that selected nothing is not recorded. S5.4 signatures given over the old design are voided."""
        self.ensure_one()
        self._ea_tool_guard()
        result = self.je_run_selection(dataset_id, dict(request, limit=1, offset=0))
        if not result["population"]["lines"] or not result["selectedLines"]:
            raise rule_error(self.env, "je-design-empty")
        design = {
            "datasetId": int(dataset_id), "criteria": request.get("criteria") or [], "params": request.get("params") or {},
            "userRules": request.get("userRules") or [], "userRulesMode": "all" if request.get("userRulesMode") == "all" else "any",
            "selectedLines": result["selectedLines"], "populationLines": result["population"]["lines"],
        }
        record = self.env["ea.audit.je.design"].sudo().create({
            "engagement_id": self.id, "dataset_id": int(dataset_id), "design": design, "recorded_by_id": self.env.user.id,
            "recorded_at": fields.Datetime.now(), "selected_lines": result["selectedLines"], "population_lines": result["population"]["lines"],
        })
        self._ea_invalidate_signoffs("S5.4")
        self._ea_log("je_design_recorded", "S5.4 selection design recorded: %d of %d lines" % (result["selectedLines"], result["population"]["lines"]))
        return record.with_env(self.env)

    def action_tool_je(self):
        """The studio: criteria, rules, the run. Opens on the file's most recent ledger."""
        self.ensure_one()
        self._ea_require_read()
        dataset = self._ea_current_dataset("journal_entries")
        wizard = self.env["ea.audit.je.studio"].create({"engagement_id": self.id, "dataset_id": dataset.id or False})
        return wizard._ea_reopen()

    def action_open_je_designs(self):
        return self._ea_list(
            "ea.audit.je.design", self.env._("S5.4 designs"), [("ea_audit_tools.view_je_design_list", "list")],
            {"context": {"ea_engagement_id": self.id, "create": False}},
        )

    def _ea_export_dynamic_method(self, kind):
        found = super()._ea_export_dynamic_method(kind)
        if found:
            return found
        match = _STUDIO_KIND.match(kind or "")
        if match:
            return lambda fr: self._ea_export_je(fr, self.env["ea.audit.je.studio"].browse(int(match[1])))
        return None

    def _ea_export_je_default(self, fr):
        """GET: every built-in criterion at its defaults. A missing ledger is not an error."""
        return self._ea_export_je(fr, None)

    def _ea_export_je(self, fr, studio):
        """The selection is re-run at export: nothing is stored, so the parameters and the ledger
        it read are written on the workbook, which can then be checked against the file."""
        as_root = self.sudo()
        dataset = (studio.exists().sudo().dataset_id if studio else None) or self._ea_current_dataset("journal_entries")
        locale = "fr" if fr else "en"
        request = {"criteria": [item["key"] for item in JE_CRITERIA if item["key"] != "user-defined"], "params": {"locale": locale}, "limit": SELECTION_CAP}
        if studio and studio.exists():
            request = dict(studio.exists()._ea_request(), limit=SELECTION_CAP)
            request["params"] = dict(request["params"], locale=locale)
        checks, result = [], None
        if dataset:
            checks = self.gl_validate_population(dataset.id)["checks"] if dataset.gl_line_count else []
            if dataset.gl_line_count:
                result = self.je_run_selection(dataset.id, request)
        client = re.sub(r"[^\w-]+", "_", as_root.client_id.name)
        return "E3.1-journal-entries-%s-%s.xlsx" % (client, as_root.fiscal_year), je_workbook({
            "clientName": as_root.client_id.name, "fiscalYear": as_root.fiscal_year, "periodEnd": french_date(as_root.period_end),
            "preparer": self.env.user.name, "ledger": dataset and {
                "filename": dataset.source_filename, "rows": dataset.row_count, "lines": dataset.gl_line_count,
            } or None, "checks": checks, "result": result,
        }, fr)


def _rule_sql(rule, add):
    column, operator, kind = rule["field"]["column"], rule["operator"], rule["field"]["type"]
    if operator == "isEmpty":
        return "coalesce(trim(%s::text), '') = ''" % column
    if operator == "isNotEmpty":
        return "coalesce(trim(%s::text), '') <> ''" % column
    if kind == "number":
        value = add(rule["value"])
        simple = {"greaterThan": ">", "greaterOrEqual": ">=", "lessThan": "<", "lessOrEqual": "<="}
        if operator == "equals":
            return "abs(%s - %s::numeric) <= %s::numeric" % (column, value, add(TOLERANCE))
        if operator == "notEquals":
            return "abs(%s - %s::numeric) > %s::numeric" % (column, value, add(TOLERANCE))
        if operator in simple:
            return "%s %s %s::numeric" % (column, simple[operator], value)
        other = add(rule["value2"])
        return "%s BETWEEN least(%s::numeric, %s::numeric) AND greatest(%s::numeric, %s::numeric)" % (column, value, other, value, other)
    if kind == "date":
        value = add(rule["value"])
        simple = {"equals": "=", "before": "<", "after": ">"}
        if operator in simple:
            return "%s %s %s::date" % (column, simple[operator], value)
        other = add(rule["value2"])
        return "%s BETWEEN least(%s::date, %s::date) AND greatest(%s::date, %s::date)" % (column, value, other, value, other)
    # case-insensitive on both sides; % and _ are meant literally
    literal = re.sub(r"([%_\\])", r"\\\1", str(rule["value"] or ""))
    actual = "lower(trim(coalesce(%s::text, '')))" % column
    if operator == "equals":
        return "%s = %s" % (actual, add(rule["value"]))
    if operator == "notEquals":
        return "%s <> %s" % (actual, add(rule["value"]))
    escape = " ESCAPE '\\'"
    if operator == "contains":
        return "%s LIKE '%%%%' || %s || '%%%%'%s" % (actual, add(literal), escape)
    if operator == "notContains":
        return "%s NOT LIKE '%%%%' || %s || '%%%%'%s" % (actual, add(literal), escape)
    if operator == "startsWith":
        return "%s LIKE %s || '%%%%'%s" % (actual, add(literal), escape)
    return "%s LIKE '%%%%' || %s%s" % (actual, add(literal), escape)

