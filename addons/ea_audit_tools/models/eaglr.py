"""EAGLR, Elite Advisors GL Review (owner's mock-up "eaglr", approved 20/11/2026).

One page per engagement, on the general ledger in use (the one EAGLA opens on). A row tagged
Linked reads its result from the tool that already has it: EAGLA's analytics through
gl_run_analytic, the sub-ledger agreements through recon_preview as the Data bank shows them, the
public holidays through journal entry testing's calendar. A row tagged New is worked out here,
by services/eaglr.py, on every line of the ledger: no line limit. Nothing here writes to the
engagement's tables, so an archived file answers too.
"""
import base64

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.fields import Domain
from odoo.tools import SQL

from ..rules import rule_error
from ..services import eaglr as e
from ..services.amount import parse_amount
from ..services.engines import RECON_PREFIXES, recon_preview
from ..services.gl_line import mapped_fields
from .gl_console import LAG, SCOPE, TABLE, lag_entries_sql
from .tool_record import is_french, upload_stamp

#: Lines read per batch: the whole ledger is read, a batch at a time.
READ_BATCH = 20000
#: A sheet of Excel holds 1 048 576 rows: the flagged lines stop short of it, title and header included.
EXCEL_ROWS = 1048570
_TIMING_EN = {"pre_audit": "Pre-audit", "post_audit": "Final", "prior_year": "Prior year", "subsequent": "Next year"}
_TIMING_FR = {"pre_audit": "Pré-audit", "post_audit": "Définitif", "prior_year": "Exercice précédent", "subsequent": "Exercice suivant"}


def _whole(value):
    return "{:,.0f}".format(value or 0).replace(",", " ")


class GlLineEaglr(models.Model):
    _inherit = "ea.audit.gl.line"

    eaglr_flag = fields.Char(
        compute="_compute_eaglr_flag", search="_search_eaglr_flag",
        help="Search-only: the lines an EAGLR check flagged, as \"page id:check\".",
    )

    def _compute_eaglr_flag(self):
        self.eaglr_flag = False

    def _search_eaglr_flag(self, operator, value):
        """The lines behind an EAGLR row, read from the page that found them (one row per visit,
        its owner's only), so the list, its search and its pivot show exactly those lines."""
        if operator == "in" and len(value) == 1:
            value = next(iter(value))
        elif operator != "=":
            return Domain.FALSE
        page_id, _sep, key = str(value or "").partition(":")
        page = self.env["ea.audit.eaglr"].browse(int(page_id)) if page_id.isdigit() else self.env["ea.audit.eaglr"]
        if not page.exists():
            return Domain.FALSE
        page.check_access("read")
        ids = [int(line_id) for line_id in (page.sudo().flagged or {}).get(key) or []]

        def to_sql(_model, alias, _query):
            return SQL('"%s"."id" = ANY(%%s)' % alias, ids)

        return Domain.custom(to_sql=to_sql)


class Eaglr(models.TransientModel):
    """The page: one record a visit, its results worked out when it opens."""

    _name = "ea.audit.eaglr"
    _description = "EAGLR"
    _rec_name = "dataset_id"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True, ondelete="cascade")
    dataset_id = fields.Many2one("ea.audit.dataset", string="Ledger", ondelete="cascade")
    report = fields.Json(string="GL review", readonly=True)
    # {row key: [line ids]}: what "See the lines" and the extract read
    flagged = fields.Json(readonly=True)
    export_file = fields.Binary(attachment=False, readonly=True)
    export_filename = fields.Char(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self.env["ea.audit.engagement"].browse(vals.get("engagement_id"))._ea_require_access()
        return super().create(vals_list)

    def _ea_reopen(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form",
            "views": [(self.env.ref("ea_audit_tools.view_eaglr_form").id, "form")],
            "target": "current", "name": "EAGLR",
            "context": {"ea_engagement_id": self.engagement_id.id},
        }

    def eaglr_open(self, key):
        """Open on a row: the EAGLA analysis, the sub-ledger, the lines behind it, or the journal types."""
        self.ensure_one()
        engagement = self.engagement_id
        row = next((row for row in (self.report or {}).get("rows", []) if row["key"] == key), None)
        if not row:
            raise rule_error(self.env, "not-found")
        target = row.get("open")
        if target == "eagla":
            console = self.env["ea.audit.gl.console"].create({
                "engagement_id": engagement.id, "dataset_id": self.dataset_id.id, "analytic_key": e.EAGLA_OF[key],
            })
            return console._ea_reopen()
        if target == "sub_ledger":
            return engagement._ea_analyzer(e.SUB_LEDGER_OF.get(key, "fixed_asset_register"), row["label"])
        if target == "journal_types":
            return self.env["ea.audit.journal.type.wizard"]._ea_open(engagement, self.dataset_id, then_eaglr=True)
        if target == "lines":
            return engagement._ea_list(
                "ea.audit.gl.line", row["label"],
                [("ea_audit_tools.view_gl_line_list", "list"), ("ea_audit_tools.view_gl_line_pivot", "pivot")],
                {
                    "domain": [("dataset_id", "=", self.dataset_id.id), ("eaglr_flag", "=", "%d:%s" % (self.id, key))],
                    "search_view_id": self.env.ref("ea_audit_tools.view_gl_line_search").id,
                    "context": {"default_engagement_id": engagement.id, "ea_engagement_id": engagement.id, "create": False},
                },
            )
        raise rule_error(self.env, "not-found")

    def action_export(self):
        """Every flagged line, check by check, in one workbook: as EAGLA's "Extract all to Excel"."""
        self.ensure_one()
        filename, content = self.engagement_id.with_context(ea_eaglr_page=self.id).ea_export_xlsx("eaglr")
        self.write({"export_file": base64.b64encode(content), "export_filename": filename})
        return {
            "type": "ir.actions.act_url", "target": "self",
            "url": "/web/content?model=%s&id=%d&field=export_file&filename_field=export_filename&download=true" % (self._name, self.id),
        }


class EngagementEaglr(models.Model):
    _inherit = "ea.audit.engagement"

    def action_tool_eaglr(self):
        """The EAGLR tile: the page on the general ledger in use, analysed if it was not yet."""
        self.ensure_one()
        self._ea_require_access()
        dataset = self._ea_gl_ready(self._ea_current_dataset("journal_entries"))
        report, flagged = self.eaglr_compute(dataset)
        page = self.env["ea.audit.eaglr"].create({
            "engagement_id": self.id, "dataset_id": dataset.id or False, "report": report, "flagged": flagged,
        })
        return page._ea_reopen()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def _ea_gl_journal_codes(self, dataset):
        """[{code, lines, example}]: every journal code of a ledger, its lines and one description."""
        self.env.cr.execute(
            f"""SELECT trim(journal_code) AS code, count(*)::int AS lines,
                       (array_agg(coalesce(nullif(trim(line_description), ''), je_description) ORDER BY line_no)
                          FILTER (WHERE coalesce(nullif(trim(line_description), ''), je_description) IS NOT NULL))[1] AS example
                  FROM {TABLE} WHERE {SCOPE} AND coalesce(trim(journal_code), '') <> ''
                 GROUP BY 1 ORDER BY 1""",
            {"dataset": dataset.id, "engagement": self.id},
        )
        return self.env.cr.dictfetchall()

    def _ea_eaglr_rows(self, query, args):
        self.env.cr.execute(query, args)
        return self.env.cr.dictfetchall()

    def eaglr_compute(self, dataset):
        """(report, flagged): the rows of the page and the line ids behind each New row."""
        self.ensure_one()
        self._ea_require_access()
        locale = "fr" if is_french(self.env) else "en"
        rows, flagged = {}, {}

        def put(key, status, count=None, unit="lines", value=None, text=None, accuracy=None, open_=None):
            rows[key] = {"status": status, "count": count, "unit": unit, "value": value, "text": text,
                         "accuracy": accuracy, "open": open_}

        source = None
        if dataset and dataset.gl_built_at:
            source = self._ea_eaglr_ledger(dataset, locale, put, flagged)
        self._ea_eaglr_sub_ledgers(locale, put)
        if not dataset or not dataset.gl_built_at:
            for key, section, _source, _ref in e.ROWS:
                if key not in rows:
                    put(key, e.NOT_RUN, text=None)
        out = []
        for key, section, kind, reference in e.ROWS:
            row = dict(rows[key], key=key, section=section, source=kind, label=e.label(key, locale))
            row["sourceLabel"] = {"linked": e.word("linked", locale), "new": e.word("new", locale), "info": e.word("new", locale)}[kind]
            if reference:
                row["sourceLabel"] += " · " + (e.word("ref_" + reference, locale) if "ref_" + reference in e.WORDS else reference)
            if row["status"] == e.INFORMATION or kind == "info":
                row["status"] = row["status"] if row["status"] == e.NOT_RUN else e.INFORMATION
            out.append(row)
        summary = e.score_summary(out)
        report = {"rows": out, "summary": summary, "source": source, "locale": locale}
        report["view"] = self._ea_eaglr_view(report, locale)
        return report, flagged

    def _ea_eaglr_view(self, report, locale):
        """What the page shows, every word and figure already written in the reader's language."""
        def word(key):
            return e.word(key, locale)

        def percent(value):
            return None if value is None else ("%.1f %%" % value).replace(".", ",") if locale == "fr" else "%.1f%%" % value

        links = {"eagla": "open_eagla", "sub_ledger": "open", "lines": "see_lines", "journal_types": "map_types"}
        tones = {e.PASSED: "good", e.EXCEPTIONS: "warn", e.NOT_RUN: "bad", e.INFORMATION: "info", e.NOT_APPLICABLE: "muted"}
        sections = []
        for number in e.SECTION_ORDER:
            rows = []
            for row in report["rows"]:
                if row["section"] != number:
                    continue
                result = "%s %s" % (_whole(row["count"]), word(row["unit"])) if row["count"] is not None else ""
                rows.append({
                    "key": row["key"], "label": row["label"], "source": row["source"], "sourceLabel": row["sourceLabel"],
                    "result": result, "detail": row.get("text") or "",
                    "value": "" if row["value"] is None else _whole(row["value"]),
                    "status": word(row["status"]), "tone": tones[row["status"]],
                    "link": word(links[row["open"]]) if row.get("open") else "",
                })
            sections.append({"key": number, "title": word("section_" + number), "note": word("section_i_note") if number == "i" else "", "rows": rows})
        summary = report["summary"]
        source = report.get("source")
        strip = []
        if source:
            strip = [
                "%s %s (%s) · %s %s" % (word("data"), source["file"], source["timing"], word("uploaded"), source["stamp"]),
                "%s %s · %s %s, %s" % (_whole(source["lines"]), word("lines"), _whole(source["entries"]), word("entries"), word("all_read")),
                "%s %s %s %s" % (word("types_mapped"), source["typed"], word("of"), source["codes"]),
            ]
        verdict = word("no_score") if summary["overall"] is None else word("above") if summary["passed"] else word("below")
        return {
            "strip": strip, "ranItself": word("ran_itself") if source else "",
            "overallLabel": word("overall"), "overall": percent(summary["overall"]) or "—", "passMark": word("pass_mark"),
            "verdict": verdict, "verdictTone": "good" if summary["passed"] else "warn" if summary["passed"] is False else "muted",
            "scores": [{"label": word("short_" + number), "value": percent(summary["sections"][number]) or "—"} for number in e.SECTIONS],
            "head": [word("check"), word("source"), word("result"), word("value"), word("status"), ""],
            "sections": sections,
        }

    def _ea_eaglr_ledger(self, dataset, locale, put, flagged):
        """Sections 2, 3 and 4 and the information rows, on every line of the ledger."""
        args = {"dataset": dataset.id, "engagement": self.id}
        fields_ = mapped_fields(dataset.mapping)
        types = e.clean_journal_types(dataset.journal_types)
        manual_codes = set(e.codes_of(types, "manual"))
        has_text = bool({"jeDescription", "lineDescription"} & fields_)
        has_party = "thirdPartyCode" in fields_
        start, _end, _keys = self._ea_eagla_year(dataset)
        profit_end = start + relativedelta(months=6) if start else None

        # --- linked rows: the tools' own results -------------------------------------------
        def eagla(key):
            return self.gl_run_analytic(dataset.id, key)

        lag = eagla("entry-date-lag")
        if lag.get("unavailable"):
            put("4.1", e.NOT_RUN, text=lag["unavailable"], unit="entries")
        else:
            found = self._ea_eaglr_rows(
                f"""SELECT count(*)::int AS n, coalesce(sum(d), 0)::float8 AS v FROM (
                      SELECT je_number, sum(debit) AS d FROM {TABLE}
                       WHERE {SCOPE} AND je_number IN ({lag_entries_sql(LAG + " > %(lagDays)s::int")})
                       GROUP BY je_number) q""",
                dict(args, lagDays=e.LAG_DAYS),
            )[0]
            put("4.1", e.count_status(found["n"]), found["n"], "entries", found["v"], open_="eagla")
        weekend = eagla("weekend-postings")
        if weekend.get("unavailable"):
            put("4.2", e.NOT_RUN, text=weekend["unavailable"])
        else:
            holidays = [row["date"] for row in self._ea_jet_holidays(self._ea_jet_settings())]
            found = self._ea_eaglr_rows(
                f"""SELECT count(*) FILTER (WHERE extract(isodow FROM journal_date) < 6)::int AS holiday,
                           coalesce(sum(abs(signed)), 0)::float8 AS v
                      FROM {TABLE} WHERE {SCOPE} AND journal_date IS NOT NULL
                       AND (extract(isodow FROM journal_date) >= 6 OR journal_date = ANY(%(holidays)s::date[]))""",
                dict(args, holidays=holidays),
            )[0]
            count = weekend["exceptions"] + found["holiday"]
            put("4.2", e.count_status(count), count, "lines", found["v"], open_="eagla",
                text=e.word("eagla_and_holidays", locale) % _whole(found["holiday"]) if found["holiday"] else None)
        missing = eagla("missing-mandatory-fields")
        if missing.get("unavailable"):
            put("2.1", e.NOT_RUN, text=missing["unavailable"])
        else:
            count = missing["totals"][3]
            put("2.1", e.count_status(count), count, open_="eagla")
        for key, analytic, count_at, value_at in (("2.4", "third-party-attribution", 2, 4), ("2.5", "missing-references", 1, 2)):
            result = eagla(analytic)
            if result.get("unavailable"):
                put(key, e.NOT_RUN, text=result["unavailable"])
            else:
                count = result["totals"][count_at]
                put(key, e.count_status(count), count, "lines", result["totals"][value_at], open_="eagla")

        # --- new rows: every line, a batch at a time ---------------------------------------
        keys = list(e.DESCRIPTION_CHECKS) + ["3.1", "3.2", "3.3", "3.4", "3.5", "3.7", "3.8"] + [
            "i.currency", "i.languages", "i.party", "i.tax", "i.profit",
        ]
        ids = {key: [] for key in keys}
        values = {key: 0.0 for key in keys}
        transit = loans = interest = 0.0
        party_texts, party_lines = {}, {}
        after = 0
        while True:
            batch = self._ea_eaglr_rows(
                f"""SELECT id, account, trim(coalesce(journal_code, '')) AS jc, journal_date, line_description,
                           je_description, signed::float8 AS signed, trim(coalesce(third_party_code, '')) AS party
                      FROM {TABLE} WHERE {SCOPE} AND id > %(after)s ORDER BY id LIMIT {READ_BATCH}""",
                dict(args, after=after),
            )
            if not batch:
                break
            after = batch[-1]["id"]
            for line in batch:
                account, amount, line_id = line["account"] or "", abs(line["signed"] or 0), line["id"]

                def flag(key):
                    ids[key].append(line_id)
                    values[key] += amount

                text = e.description(line["line_description"], line["je_description"])
                if has_text:
                    for key in e.description_flags(text, line["journal_date"]):
                        flag(key)
                    if e.tax_without_period(account, text):
                        flag("i.tax")
                    if has_party and line["party"] and account[:2] in ("40", "41"):
                        party_texts.setdefault(line["party"], set()).add(e.normalised(text))
                        party_lines.setdefault(line["party"], []).append((line_id, amount))
                if account.startswith("58"):
                    transit += line["signed"] or 0
                    flag("3.1")
                if account.startswith("16"):
                    loans += line["signed"] or 0
                    flag("3.7")
                elif account.startswith("67"):
                    interest += line["signed"] or 0
                    flag("3.7")
                if line["jc"] in manual_codes:
                    bucket = e.manual_check(account)
                    if bucket:
                        flag(bucket)
                if (profit_end and line["journal_date"] and account[:2] in ("11", "12", "13")
                        and start <= line["journal_date"] < profit_end):
                    flag("i.profit")
            if len(batch) < READ_BATCH:
                break

        # provisions: the entries touching 19/29/39/49/59, with all their lines
        provision_lines = self._ea_eaglr_rows(
            f"""SELECT id, je_number AS je, account, debit::float8 AS debit, credit::float8 AS credit FROM {TABLE}
                 WHERE {SCOPE} AND je_number IN (
                   SELECT je_number FROM {TABLE} WHERE {SCOPE} AND left(account, 2) = ANY(%(prefixes)s::text[]))""",
            dict(args, prefixes=list(e.PROVISION_PREFIXES)),
        )
        amounts = {line["id"]: abs((line["debit"] or 0) - (line["credit"] or 0)) for line in provision_lines}
        for line_id in e.provision_exceptions(provision_lines):
            ids["3.8"].append(line_id)
            values["3.8"] += amounts[line_id]
        for party, texts in party_texts.items():
            if len(texts) > e.PARTY_VARIANTS:
                for line_id, amount in party_lines[party]:
                    ids["i.party"].append(line_id)
                    values["i.party"] += amount

        def new(key, status=None, text=None):
            count = len(ids[key])
            flagged[key] = ids[key]
            put(key, status or e.count_status(count), count, "lines", values[key], text=text, open_="lines")

        for key in e.DESCRIPTION_CHECKS:
            if has_text:
                new(key)
            else:
                put(key, e.NOT_RUN, text=e.word("no_description", locale))
        # 3.1 is about the balance, its lines are the ones that make it
        new("3.1", e.EXCEPTIONS if abs(transit) > 0.01 else e.PASSED,
            "%s %s" % (e.word("balance", locale), _whole(transit)))
        for key in ("3.2", "3.3", "3.4", "3.5"):
            if types:
                new(key)
            else:
                put(key, e.NOT_RUN, text=e.word("no_types", locale), open_="journal_types")
        if abs(loans) <= 0.01:
            flagged["3.7"] = ids["3.7"]
            put("3.7", e.NOT_APPLICABLE, len(ids["3.7"]), "lines", values["3.7"], text=e.word("no_loans", locale), open_="lines")
        else:
            rate = e.implied_rate(loans, interest)
            text = "%s %s · %s %s · %s %s %%" % (
                e.word("loans", locale), _whole(abs(loans)), e.word("interest", locale), _whole(interest),
                e.word("rate", locale), ("%.2f" % rate).replace(".", "," if locale == "fr" else "."),
            )
            new("3.7", e.EXCEPTIONS if interest <= 0.01 else e.PASSED, text)
        new("3.8")
        for key in ("i.currency", "i.languages", "i.tax"):
            if has_text:
                new(key, e.INFORMATION)
            else:
                put(key, e.NOT_RUN, text=e.word("no_description", locale))
        if has_text and has_party:
            new("i.party", e.INFORMATION)
        else:
            put("i.party", e.NOT_RUN, text=e.word("no_party" if has_text else "no_description", locale))
        new("i.profit", e.INFORMATION)

        codes = self._ea_gl_journal_codes(dataset)
        timing = (_TIMING_FR if locale == "fr" else _TIMING_EN).get(dataset.timing, dataset.timing)
        return {
            "file": dataset.source_filename or dataset.name, "timing": timing, "stamp": upload_stamp(self, dataset.create_date),
            "lines": dataset.gl_line_count, "entries": self.gl_run_analytic(dataset.id, "unbalanced-entries")["population"],
            "codes": len(codes), "typed": len([row for row in codes if row["code"] in types]),
        }

    def _ea_eaglr_sub_ledgers(self, locale, put):
        """Section 1: the agreement of each sub-ledger with the trial balance, as its Data bank
        page shows it (recon_preview), and the register's net book value."""
        root = self.sudo()
        has_tb = bool(root._ea_tb_balances())
        for key, kind in e.SUB_LEDGER_OF.items():
            dataset = root._ea_current_dataset(kind)
            if not dataset or not has_tb:
                put(key, e.NOT_RUN, text=e.word("no_sub_ledger" if not dataset else "no_tb", locale), open_="sub_ledger")
                continue
            preview = recon_preview(kind, root._ea_dataset_rows(dataset), root._ea_tb_closing_for_prefixes(RECON_PREFIXES[kind]))
            self._ea_eaglr_agreement(key, preview["datasetTotal"], preview["tbTotal"], locale, put)
        register = root._ea_current_dataset("fixed_asset_register")
        mapping = register.mapping or {} if register else {}
        if not register or not has_tb:
            put("1.5", e.NOT_RUN, text=e.word("no_sub_ledger" if not register else "no_tb", locale), open_="sub_ledger")
            return
        if not mapping.get("nbv") and not mapping.get("depreciation"):
            put("1.5", e.NOT_RUN, text=e.word("no_nbv", locale), open_="sub_ledger")
            return
        nbv = 0.0
        for row in root._ea_dataset_rows(register):
            data = row["data"] or {}
            if mapping.get("nbv"):
                nbv += parse_amount(data.get(mapping["nbv"])) or 0
            else:
                nbv += (parse_amount(data.get(mapping.get("amount"))) or 0) - abs(parse_amount(data.get(mapping["depreciation"])) or 0)
        book = 0.0
        for balance in root._ea_tb_balances():
            account = balance["account"] or ""
            if account.startswith("2") and not account.startswith(("25", "26", "27", "29")):
                book += balance["value"] or 0
        self._ea_eaglr_agreement("1.5", nbv, book, locale, put, open_="sub_ledger")

    def _ea_eaglr_agreement(self, key, left, right, locale, put, open_="sub_ledger"):
        difference = (left or 0) - (right or 0)
        accuracy = e.accuracy(left, right)
        text = "%s %s · %s %s · %s %s" % (
            e.word("register", locale), _whole(left), e.word("tb", locale), _whole(right),
            e.word("accuracy", locale), ("%.2f %%" % accuracy).replace(".", "," if locale == "fr" else "."),
        )
        put(key, e.PASSED if abs(difference) <= 0.5 else e.EXCEPTIONS, value=difference, text=text, accuracy=accuracy, open_=open_)

    # ------------------------------------------------------------------
    # The extract
    # ------------------------------------------------------------------

    def _ea_export_eaglr(self, fr):
        """The page's rows, then every flagged line with the check that flagged it (no line limit
        but Excel's own)."""
        from ..exports import registers_workbook

        page = self.env["ea.audit.eaglr"].browse(int(self.env.context.get("ea_eaglr_page") or 0))
        if not page.exists() or page.engagement_id != self:
            raise rule_error(self.env, "not-found")
        locale = "fr" if fr else "en"
        report, flagged = page.report or {}, page.flagged or {}
        head = [e.word(word, locale).capitalize() for word in ("check", "source", "result", "value", "status")]
        summary = [
            [e.label(row["key"], locale), row["sourceLabel"],
             ("%s %s" % (row["count"], e.word(row["unit"], locale)) if row["count"] is not None else "") + (" · " + row["text"] if row.get("text") else ""),
             row["value"], e.word(row["status"], locale)]
            for row in report.get("rows", [])
        ]
        line_head = (
            ["Contrôle", "N° écriture", "Date", "Journal", "Compte", "Intitulé du compte", "Libellé", "Débit", "Crédit"]
            if fr else ["Check", "Entry", "Date", "Journal", "Account", "Account name", "Description", "Debit", "Credit"]
        )
        lines = []
        for key, _section, _source, _ref in e.ROWS:
            wanted = flagged.get(key) or []
            if not wanted or len(lines) >= EXCEL_ROWS:
                continue
            for start in range(0, len(wanted), READ_BATCH):
                chunk = self._ea_eaglr_rows(
                    f"""SELECT je_number, to_char(journal_date, 'DD/MM/YYYY') AS day, journal_code, account, account_name,
                               coalesce(nullif(trim(line_description), ''), je_description) AS description,
                               debit::float8 AS debit, credit::float8 AS credit
                          FROM {TABLE} WHERE {SCOPE} AND id = ANY(%(ids)s::int[]) ORDER BY journal_date NULLS LAST, je_number, line_no""",
                    {"dataset": page.dataset_id.id, "engagement": self.id, "ids": wanted[start:start + READ_BATCH]},
                )
                label = e.label(key, locale)
                for line in chunk:
                    lines.append([label, line["je_number"], line["day"], line["journal_code"], line["account"], line["account_name"],
                                  line["description"], line["debit"], line["credit"]])
                if len(lines) >= EXCEL_ROWS:
                    del lines[EXCEL_ROWS:]
                    break
        sheets = [
            ("EAGLR", head, summary, "EAGLR — %s" % ((report.get("source") or {}).get("file") or "")),
            ("Lignes signalées" if fr else "Flagged lines", line_head, lines, "EAGLR"),
        ]
        return "eaglr-%s.xlsx" % self._ea_export_slug(), registers_workbook(sheets)
