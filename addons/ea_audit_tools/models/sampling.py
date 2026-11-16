"""The Sampling screen (C.7.19): tests of controls, tests of details, results and projection."""
import re
import secrets

from markupsafe import Markup

from odoo import fields, models

from ..rules import rule_error
from ..services.amount import amount_or
from ..services.ap_schedules import index_resolver
from ..services.dataset_mapping import je_identity, je_key_columns
from ..services.engines import evaluate_sampling, record_tod_result, select_sample
from ..services.errors import EngineError, ServiceError
from ..services.lead_classes import INDEX_SECTION, LEAD_INDEXES, lead_index_label
from ..services.sampling_params import attribute_plan, evaluate_attribute, mus_plan
from ..services.subsequent import CURRENT_YEAR_TIMINGS
from ..services.tod_plan import TOD_ASSURANCES, TOD_CRAS, plan_tod, stable_start_fraction
from ..workbooks import CRA_LABEL, toc_sample_workbook, tod_workbook
from .tool_record import decimal_label, fcfa, french_date, is_french

DEFAULT_CRA = "moderate"
_TOD_KIND = re.compile(r"^tod_(bs|is)_(little|some|corroborative|persuasive)$")
_RUN_KIND = re.compile(r"^run_(\d+)$")
METHOD_SELECTION = [("random", "Random"), ("systematic", "Systematic"), ("mus", "Monetary unit (MUS)"), ("criteria", "Key items + random")]


def indexes_of_side(side):
    """Which indexes belong to which side of the statements."""
    kinds = ("Assets", "Liabilities", "Equity") if side == "bs" else ("Revenues", "Expenses")
    return [definition for definition in LEAD_INDEXES if definition["accountType"] in kinds]


class AutomationRun(models.Model):
    """automation_run: what an engine did, with its worksheet. The run keeps its summary when the
    dataset is replaced. The source files the worksheet as a document on the paper; see QUESTIONS.md."""

    _name = "ea.audit.automation.run"
    _inherit = ["ea.audit.tool.record"]
    _description = "Engine run"
    _order = "create_date desc, id desc"
    _rec_name = "title"

    title = fields.Char(required=True)
    engine = fields.Char(required=True, index=True)
    file_item_id = fields.Many2one("ea.audit.file.item", string="Paper", ondelete="set null")
    dataset_id = fields.Many2one("ea.audit.dataset", ondelete="set null")
    params = fields.Json()
    summary = fields.Json()
    sheet_header = fields.Json()
    sheet_rows = fields.Json()
    method = fields.Char(index=True)
    index_code = fields.Char(string="Lead index")
    sample_value = fields.Float(string="Sample value", digits=(18, 0))
    sample_misstatement = fields.Float(string="Misstatement in the sample", digits=(18, 0))
    key_misstatement = fields.Float(string="Key-item misstatement", digits=(18, 0))
    remaining_value = fields.Float(string="Remaining population", digits=(18, 0))
    projected = fields.Float(string="Projected misstatement", digits=(18, 0))
    raised_to_b5 = fields.Boolean(string="On C1.1")
    total_likely = fields.Float(string="Total likely", digits=(18, 0))
    exceeds_te = fields.Boolean(string="Exceeds performance materiality")

    def action_export(self):
        self.ensure_one()
        return self.sudo().engagement_id.with_env(self.env)._ea_export_action("run_%d" % self.id)

    def evaluate(self, misstatement_found):
        """evaluateSampling on a run: the projection, raised to C1.1 when not trivial."""
        self.ensure_one()
        self._ea_guard()
        as_root = self.sudo()
        if as_root.engine != "sampling":
            raise rule_error(self.env, "not-found")
        engagement = as_root.engagement_id.with_env(self.env)
        summary = dict(as_root.summary or {})
        approved = engagement._ea_approved_materiality()
        locale = "fr" if is_french(self.env) else "en"
        try:
            result = evaluate_sampling(
                summary.get("sampledValue"), summary.get("populationTotal") or 0, misstatement_found,
                approved.trivial if approved else None, str(as_root.id), locale,
            )
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error
        summary.update({"misstatementFound": misstatement_found, "projected": result["projected"]})
        as_root.write({"summary": summary, "projected": result["projected"], "raised_to_b5": result["raisedToB5"]})
        if result["finding"]:
            finding = result["finding"]
            engagement.route_finding(
                "b5", finding["title"], amount=finding["amount"], mtype=finding["mtype"], file_item=as_root.file_item_id or None,
            )
        return {"projected": result["projected"], "raisedToB5": result["raisedToB5"]}


class EngagementSampling(models.Model):
    _inherit = "ea.audit.engagement"

    sampling_prerequisites_html = fields.Html(string="Prerequisites", compute="_compute_sampling_board", sanitize=False, compute_sudo=True)
    sampling_te_label = fields.Char(string="Performance materiality", compute="_compute_sampling_board", compute_sudo=True)
    sampling_selected_count = fields.Integer(string="Controls selected", compute="_compute_sampling_board", compute_sudo=True)
    sampling_drawn_count = fields.Integer(string="Samples drawn", compute="_compute_sampling_board", compute_sudo=True)
    sampling_result_count = fields.Integer(string="Results recorded", compute="_compute_sampling_board", compute_sudo=True)

    def _compute_sampling_board(self):
        Control = self.env["ea.audit.scot.control"].sudo()
        Run = self.env["ea.audit.automation.run"].sudo()
        # first, for all of them: the prerequisites sync the CRA, whose writes would drop a value already
        # assigned here, including one assigned to another engagement of this batch
        prerequisites_of = {engagement.id: engagement._ea_tool_prerequisites() for engagement in self}
        for engagement in self:
            prerequisites = prerequisites_of[engagement.id]
            approved = engagement._ea_approved_materiality()
            selected = Control.search([("engagement_id", "=", engagement.id), ("selected_for_testing", "=", True)])
            engagement.sampling_te_label = fcfa(approved.performance) if approved else "—"
            engagement.sampling_selected_count = len(selected)
            engagement.sampling_drawn_count = len(selected.filtered("toc_sample_drawn_at"))
            engagement.sampling_result_count = Run.search_count([("engagement_id", "=", engagement.id), ("method", "=", "tod-mus")])
            engagement.sampling_prerequisites_html = engagement._ea_prerequisites_html(prerequisites)

    def _ea_prerequisites_html(self, prerequisites=None):
        """The strip of the sampling board and of the journal-entry studio. A paper's chip is its link."""
        self.ensure_one()
        chips = []
        for item in self._ea_tool_prerequisites() if prerequisites is None else prerequisites:
            css = "o_ea_chip_good" if item["ok"] else "o_ea_chip_warn"
            if item.get("href"):
                chips.append(Markup("<a href='{href}' class='o_ea_chip {css} me-2'>{label}</a>").format(href=item["href"], css=css, label=item["label"]))
            else:
                chips.append(Markup("<span class='o_ea_chip {css} me-2'>{label}</span>").format(css=css, label=item["label"]))
        return Markup("").join(chips)

    def _ea_tool_prerequisites(self):
        """toolPrerequisites (F063): what the sampling and journal-entry tools lean on."""
        self.ensure_one()
        fr = is_french(self.env)
        as_root = self.sudo()
        as_root._ea_sync_cra()
        controls = bool(self.env["ea.audit.scot.control"].sudo().search_count([
            ("engagement_id", "=", self.id), ("selected_for_testing", "=", True),
        ]))
        cells = self.env["ea.audit.cra.assessment"].sudo().search([("engagement_id", "=", self.id)])
        cra = bool(cells) and not cells.filtered(lambda cell: cell.relevant and not (cell.ir and cell.cr))
        dataset = self._ea_current_dataset("journal_entries")
        papers = {item.code: "/odoo/%d/ea_audit_paper" % item.id for item in self.env["ea.audit.file.item"].sudo().search([
            ("engagement_id", "=", self.id), ("code", "in", ("S2.1", "S3.1")),
        ])}
        return [
            {"key": "controls", "ok": controls, "label": "S2.1 : contrôles sélectionnés" if fr else "S2.1: controls selected", "href": papers.get("S2.1")},
            {"key": "cra", "ok": cra, "label": "S3.1 : évaluation combinée complète" if fr else "S3.1: combined assessment complete", "href": papers.get("S3.1")},
            {"key": "gl", "ok": bool(dataset.mapping), "label": "Grand livre importé et mappé" if fr else "General ledger imported and mapped"},
        ]

    # ------------------------------------------------------------------
    # Tests of details
    # ------------------------------------------------------------------

    def _ea_ledger(self):
        """The pre-audit ledger, else the newest of the year audited (never the next year's)."""
        self.ensure_one()
        datasets = self.env["ea.audit.dataset"].sudo().search([
            ("engagement_id", "=", self.id), ("kind", "=", "journal_entries"), ("superseded_at", "=", False),
            ("timing", "in", CURRENT_YEAR_TIMINGS),
        ])
        return datasets.sorted(lambda d: (d.timing != "pre_audit", -d.id))[:1]

    def _ea_prior_ledger(self):
        """The prior-year ledger in use, if one was uploaded: it gives the prior year its DSO and DPO."""
        self.ensure_one()
        return self.env["ea.audit.dataset"].sudo().search([
            ("engagement_id", "=", self.id), ("kind", "=", "journal_entries"), ("superseded_at", "=", False),
            ("timing", "=", "prior_year"),
        ], order="id desc", limit=1)

    def _ea_ledger_start_key(self, dataset):
        """What a tests-of-details plan starts from, besides the file and the index: facts of the
        ledger that a second import of the same file gives again (its kind, its number of rows,
        its total in hundredths). Worked out when asked, stored nowhere: it replaces the file's
        fingerprint, which the owner had removed (2026-11-15)."""
        return "%s:%d:%d" % (dataset.kind, dataset.row_count, int(round(dataset.total_amount * 100)))

    def _ea_ledger_lines_by_index(self, dataset):
        """{index: [GlLine]} read from the file's own rows, as todSideView does; zero lines skipped."""
        mapping = dataset.mapping or {}
        use_pair = bool(mapping.get("debit") and mapping.get("credit"))
        key_columns = je_key_columns(mapping)
        je_header = mapping.get("jeNumber") if isinstance(mapping.get("jeNumber"), str) else None

        def text(value):
            return None if value is None else (str(value).strip() or None)

        index_of = index_resolver(self._ea_lead_overrides())
        out = {}
        cr = self.env.cr
        after = 0
        while True:
            cr.execute(
                "SELECT row_no, data FROM ea_audit_dataset_row WHERE dataset_id = %s AND row_no > %s ORDER BY row_no LIMIT 5000",
                [dataset.id, after],
            )
            batch = cr.fetchall()
            if not batch:
                return out
            after = batch[-1][0]
            for _row_no, data in batch:
                account = str(data.get(mapping["account"]) or "").strip()
                if not account:
                    continue
                index = index_of(account)
                if not index:
                    continue
                if use_pair:
                    amount = amount_or(data.get(mapping["debit"]), 0) - amount_or(data.get(mapping["credit"]), 0)
                else:
                    amount = amount_or(data.get(mapping["amount"]), 0)
                if not amount:
                    continue
                out.setdefault(index, []).append({
                    "ref": je_identity(data, key_columns, je_header, text) or account,
                    "account": account, "amount": abs(amount),
                    "description": text(data.get(mapping["jeDescription"])) if mapping.get("jeDescription") else None,
                    "date": text(data.get(mapping["journalDate"])) if mapping.get("journalDate") else None,
                })

    def tod_side_view(self, side, assurance="little", start_fraction=None):
        """todSideView. Nothing invented: an index S3.1 does not assess gets the default CRA and says
        so, an index with no ledger line is named rather than silently absent."""
        self.ensure_one()
        self._ea_require_access()
        if side not in ("bs", "is"):
            raise rule_error(self.env, "invalid-value")
        as_root = self.sudo()
        approved = as_root._ea_approved_materiality()
        if not approved:
            raise rule_error(self.env, "no-materiality")
        te = approved.performance
        assurance = assurance if assurance in TOD_ASSURANCES else "little"
        dataset = as_root._ea_ledger()
        if not dataset:
            raise rule_error(self.env, "no-gl")
        mapping = dataset.mapping or {}
        if not mapping.get("account") or not (mapping.get("amount") or (mapping.get("debit") and mapping.get("credit"))):
            raise rule_error(self.env, "no-mapping")
        as_root._ea_sync_cra()
        rows = self.env["ea.audit.cra.row"].sudo().search([("engagement_id", "=", self.id)])
        cra_by_index, thresholds = {}, {}
        for row in rows:
            worst = row.worst_tod
            if worst in TOD_CRAS:
                cra_by_index[row.index_code] = worst
            if row.key_item_threshold and row.key_item_threshold > 0:
                thresholds[row.index_code] = row.key_item_threshold
        specific = {
            record.index_code: record.specific_te
            for record in self.env["ea.audit.significance"].sudo().search([("engagement_id", "=", self.id)])
            if record.specific_te > 0
        }
        by_index = as_root._ea_ledger_lines_by_index(dataset)
        start_key = as_root._ea_ledger_start_key(dataset)
        sheets, empty = [], []
        for definition in indexes_of_side(side):
            code = definition["code"]
            lines = by_index.get(code, [])
            if not lines:
                empty.append({"indexCode": code, "labelEn": definition["labelEn"], "labelFr": definition["labelFr"]})
                continue
            cra = cra_by_index.get(code)
            threshold = thresholds.get(code)
            own = specific.get(code)
            te_index = min(te, own) if own is not None else te
            # capped at the account's TE: a specific figure never lifts the threshold above it (UAT B43)
            threshold_index = min(threshold if threshold is not None else te_index, te_index) if own is not None else threshold
            sheets.append({
                "indexCode": code, "labelEn": definition["labelEn"], "labelFr": definition["labelFr"],
                "taskCode": INDEX_SECTION.get(code), "cra": cra or DEFAULT_CRA, "craFromS31": cra is not None,
                "thresholdFromS31": threshold is not None, "assurance": assurance,
                "plan": plan_tod({
                    "lines": lines, "te": te_index, "threshold": threshold_index, "cra": cra or DEFAULT_CRA, "assurance": assurance,
                    # B37, owner's ruling pending: the id changes at migration, so a migrated file keeps the
                    # samples it drew as data, and only a plan worked out afterwards starts elsewhere.
                    "startFraction": start_fraction if start_fraction is not None else stable_start_fraction(str(self.id), code, start_key),
                }),
            })
        return {
            "locale": "fr" if is_french(self.env) else "en", "side": side, "clientName": as_root.client_id.name,
            "fiscalYear": as_root.fiscal_year, "periodEnd": french_date(as_root.period_end),
            "currency": (as_root._ea_tb().currency if as_root._ea_tb() else "XAF"), "preparer": self.env.user.name,
            "te": te, "ledgerFilename": dataset.source_filename, "sheets": sheets, "emptyIndexes": empty,
        }

    def tod_preview_html(self, side, assurance):
        """The parameters per index, before export (F063)."""
        view = self.tod_side_view(side, assurance)
        fr = view["locale"] == "fr"
        head = (
            ["Indice", "Population", "Éléments clés", "Seuil de travail", "Évaluation combinée", "Facteur", "Taille", "Intervalle"]
            if fr else
            ["Index", "Population", "Key items", "Performance materiality", "Combined assessment", "Factor", "Size", "Interval"]
        )
        lines = []
        for sheet in view["sheets"]:
            plan = sheet["plan"]
            lines.append(Markup(
                "<tr><td>{a} {b}</td><td class='text-end'>{c}</td><td class='text-end'>{d} ({e})</td><td class='text-end'>{f}</td>"
                "<td>{g}</td><td class='text-end'>{h}</td><td class='text-end'>{i}</td><td class='text-end'>{j}</td></tr>"
            ).format(
                a=sheet["indexCode"], b=sheet["labelFr" if fr else "labelEn"], c=fcfa(plan["populationValue"]),
                d=len(plan["keyItems"]), e=fcfa(plan["keyItemValue"]), f=fcfa(plan["te"]), g=CRA_LABEL[view["locale"]].get(sheet["cra"], sheet["cra"]),
                h=decimal_label(plan["factor"], view["locale"]) if plan["factor"] is not None else "—", i=plan["sampleSize"],
                j=fcfa(plan["interval"]) if plan["interval"] is not None else "—",
            ))
        empty = ", ".join(item["indexCode"] for item in view["emptyIndexes"])
        return Markup(
            "<div class='table-responsive'><table class='table table-sm o_ea_table'><thead><tr>{head}</tr></thead><tbody>{rows}</tbody></table></div>"
            "<p class='o_ea_legend'>{note}</p>"
        ).format(
            head=Markup("").join(Markup("<th>{}</th>").format(label) for label in head),
            rows=Markup("").join(lines),
            note=("Indices sans ligne au grand livre : %s" if fr else "Indexes with no ledger line: %s") % (empty or "—"),
        )

    def tod_preview(self, prefix, cra, assurance, threshold=None):
        """todPreview: the plan for one account prefix. Refusals as the source's ok:false codes."""
        self.ensure_one()
        self._ea_require_access()
        as_root = self.sudo()
        approved = as_root._ea_approved_materiality()
        if not approved:
            raise rule_error(self.env, "no-materiality")
        dataset = as_root._ea_ledger()
        if not dataset:
            raise rule_error(self.env, "no-gl")
        mapping = dataset.mapping or {}
        if not mapping.get("account") or not mapping.get("amount"):
            raise rule_error(self.env, "no-mapping")
        lines = as_root._ea_lines_of_prefix(dataset, prefix)
        if not lines:
            raise rule_error(self.env, "empty-population")
        return plan_tod({
            "lines": lines, "te": approved.performance, "threshold": threshold,
            "cra": cra if cra in TOD_CRAS else "low", "assurance": assurance if assurance in TOD_ASSURANCES else "little",
        })

    def _ea_lines_of_prefix(self, dataset, prefix):
        mapping = dataset.mapping
        clean = re.sub(r"[^0-9]", "", prefix or "")
        lines = []
        self.env.cr.execute("SELECT data FROM ea_audit_dataset_row WHERE dataset_id = %s ORDER BY row_no", [dataset.id])
        key_columns = je_key_columns(mapping)
        je_header = mapping.get("jeNumber") if isinstance(mapping.get("jeNumber"), str) else None
        for (data,) in self.env.cr.fetchall():
            account = str(data.get(mapping["account"]) or "").strip()
            if clean and not account.startswith(clean):
                continue
            amount = amount_or(data.get(mapping["amount"]), 0)
            if amount:
                reference = je_identity(data, key_columns, je_header, lambda v: None if v is None else (str(v).strip() or None))
                lines.append({"ref": reference or account, "account": account, "amount": abs(amount)})
        return lines

    def mus_preview(self, prefix, interval=None):
        """musPreview: interval TE/3 by default; items at or above it are examined in full."""
        self.ensure_one()
        self._ea_require_access()
        as_root = self.sudo()
        dataset = as_root._ea_ledger()
        if not dataset:
            raise rule_error(self.env, "no-gl")
        mapping = dataset.mapping or {}
        if not mapping.get("account") or not mapping.get("amount"):
            raise rule_error(self.env, "no-mapping")
        amounts = [line["amount"] for line in as_root._ea_lines_of_prefix(dataset, prefix)]
        if not amounts:
            raise rule_error(self.env, "empty-population")
        total = 0
        for amount in amounts:
            total += amount
        approved = as_root._ea_approved_materiality()
        default = max(1, int(approved.performance / 3 + 0.5)) if approved else max(1, int(total / 25 + 0.5))
        chosen = int(interval + 0.5) if interval and interval > 0 else default
        top = len([amount for amount in amounts if amount >= chosen])
        remaining = 0
        for amount in amounts:
            if amount < chosen:
                remaining += amount
        ceiling = int(remaining / chosen) + (0 if remaining % chosen == 0 else 1)
        return {
            "populationValue": int(total + 0.5), "populationCount": len(amounts), "interval": chosen, "topStratum": top,
            "sampleSize": top + ceiling,
        }

    def record_tod_result(self, index_code, sample_value, sample_misstatement, key_misstatement, remaining_value):
        """recordTodResult: the run, the projection (ISA 530 ¶14) and what goes to C1.1."""
        self.ensure_one()
        self._ea_tool_guard()
        as_root = self.sudo()
        approved = as_root._ea_approved_materiality()
        Run = self.env["ea.audit.automation.run"].sudo()
        locale = "fr" if is_french(self.env) else "en"
        # the run's own id is in the finding's title, as in the source: reserve it first
        run = Run.create({"engagement_id": self.id, "title": "ToD", "engine": "sampling", "method": "tod-mus"})
        try:
            result = record_tod_result({
                "indexCode": index_code or "", "sampleValue": sample_value, "sampleMisstatement": sample_misstatement or 0,
                "keyMisstatement": key_misstatement or 0, "remainingValue": remaining_value, "locale": locale,
            }, approved.trivial if approved else None, str(run.id))
        except EngineError as error:
            raise rule_error(self.env, error.code) from error
        item = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.id), ("code", "=", result["section"])], limit=1)
        total = result["projected"] + (key_misstatement or 0)
        run.write({
            "title": "ToD results %s" % result["indexCode"], "file_item_id": item.id or False, "index_code": result["indexCode"],
            "params": {"method": "tod-mus", "indexCode": result["indexCode"]},
            "summary": {**result["summary"], "misstatementFound": sample_misstatement or 0, "projected": result["projected"], "raisedToB5": result["raisedToB5"]},
            "sheet_header": ["measure", "amount"],
            "sheet_rows": [
                ["sample_value", sample_value], ["sample_misstatement", sample_misstatement or 0],
                ["key_item_misstatement", key_misstatement or 0], ["remaining_population", remaining_value],
            ],
            "sample_value": sample_value, "sample_misstatement": sample_misstatement or 0, "key_misstatement": key_misstatement or 0,
            "remaining_value": remaining_value, "projected": result["projected"], "raised_to_b5": result["raisedToB5"],
            "total_likely": total, "exceeds_te": bool(approved) and abs(total) > approved.performance,
        })
        for finding in result["findings"]:
            self.route_finding(
                "b5", finding["title"], amount=finding["amount"], mtype=finding["mtype"],
                trivial_confirmed=finding.get("trivialConfirmed", False), file_item=item or None,
            )
        self._ea_log("tod_result", "Tests of details on %s: projected %s" % (result["indexCode"], result["projected"]))
        return {"runId": run.id, "projected": result["projected"], "raisedToB5": result["raisedToB5"]}

    def run_sampling(self, dataset_id, method, sample_size, seed=None, threshold=None, confidence=None, expected=None, override_size=None, override_rationale=None, file_item=None, designed_procedure=None):
        """runSampling (5.2, ISA 530): the MUS extent computed, not typed, when confidence is given and
        materiality is approved; a typed override needs its rationale (R17). The seed is stored."""
        self.ensure_one()
        self._ea_tool_guard()
        dataset = self.env["ea.audit.dataset"].sudo().search([("id", "=", int(dataset_id or 0)), ("engagement_id", "=", self.id)], limit=1)
        if not dataset:
            raise rule_error(self.env, "no-dataset")
        if file_item and file_item.sudo().engagement_id != self.sudo():
            raise rule_error(self.env, "not-found")
        if designed_procedure and (designed_procedure.sudo().engagement_id != self.sudo() or not designed_procedure.sudo().selected):
            raise rule_error(self.env, "not-found")
        approved = self.sudo()._ea_approved_materiality()
        self.env.cr.execute("SELECT row_no, data, amount FROM ea_audit_dataset_row WHERE dataset_id = %s ORDER BY row_no", [dataset.id])
        rows = [{
            "rowNo": row_no, "data": data, "amount": float(amount) if amount is not None else None,
        } for row_no, data, amount in self.env.cr.fetchall()]
        seed = seed or secrets.token_hex(8)
        sampling = {"method": method, "sampleSize": sample_size, "seed": seed}
        if threshold is not None:
            sampling["threshold"] = threshold
        if confidence is not None:
            sampling["confidence"] = confidence
        if expected is not None:
            sampling["expectedMisstatement"] = expected
        if override_size is not None:
            sampling["overrideSize"] = override_size
            sampling["overrideRationale"] = override_rationale
        try:
            result = select_sample(rows, sampling, approved.performance if approved else None)
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error
        summary = dict(result["summary"])
        summary["populationTotal"] = dataset.total_amount if dataset.has_total else None
        headers = list(rows[0]["data"]) if rows else []
        by_no = {row["rowNo"]: row for row in rows}
        run = self.env["ea.audit.automation.run"].sudo().create({
            "engagement_id": self.id, "title": "Sampling worksheet", "engine": "sampling", "method": method,
            "dataset_id": dataset.id, "file_item_id": file_item.id if file_item else False,
            "params": {
                "method": method, "sampleSize": sample_size, "seed": seed, "threshold": threshold, "confidence": confidence,
                "expectedMisstatement": expected, "overrideSize": override_size, "overrideRationale": override_rationale,
            },
            "summary": summary, "sheet_header": ["row_no", "reason"] + headers,
            "sheet_rows": [
                [pick["rowNo"], pick["reason"]] + [str(by_no[pick["rowNo"]]["data"].get(header) or "") for header in headers]
                for pick in result["picks"]
            ],
        })
        if designed_procedure:
            # the sample feeds the test of details it was drawn for (procedure design, 2026-11-16)
            proc = designed_procedure.sudo()
            run.write({
                "designed_procedure_id": proc.id, "index_code": proc.index_code,
                "purpose": ("%s %s" % (proc.code, proc.title or ""))[:200].strip(),
            })
            proc._ea_mark_started()
        self._ea_log("sampling_run", "Sample of %d drawn from %s (%s, seed %s)" % (len(result["picks"]), dataset.source_filename, method, seed))
        return run.with_env(self.env)

    def mus_size_preview(self, population_value, confidence, expected=0):
        """musPlan on the approved tolerable: what the size would be."""
        self.ensure_one()
        self._ea_require_access()
        approved = self.sudo()._ea_approved_materiality()
        if not approved:
            raise rule_error(self.env, "no-materiality")
        try:
            return mus_plan({
                "populationValue": population_value, "tolerable": approved.performance, "expected": expected, "confidence": confidence,
            })
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error

    @staticmethod
    def attribute_size(frequency):
        return attribute_plan(frequency)["sampleSize"]

    @staticmethod
    def attribute_evaluation(sample_size, deviations):
        return evaluate_attribute(sample_size, deviations)

    # ------------------------------------------------------------------
    # Screens and exports
    # ------------------------------------------------------------------

    def action_tool_sampling(self):
        """The sampling page (owner's mock-up of 2026-11-16): one card per sample."""
        self.ensure_one()
        self._ea_require_access()
        return {
            "type": "ir.actions.client", "tag": "ea_audit_tools.sampling_page", "target": "current",
            "name": self.env._("Samples"), "params": {"engagement_id": self.id},
            "context": {"active_id": self.id, "ea_engagement_id": self.id},
        }

    def action_sampling_board(self):
        """The former board, kept for its links."""
        return self._ea_board("ea_audit_tools.view_engagement_sampling_board", self.env._("Sampling"))

    def ea_sampling_open(self, method, res_id=None):
        """The sampling page's links: the existing wizards, lists and exports."""
        self.ensure_one()
        if method in ("action_open_full", "action_open_draw", "action_open_grid_import"):
            control = self.env["ea.audit.scot.control"].browse(int(res_id or 0)).exists()
            if not control or control.sudo().engagement_id != self.sudo():
                raise rule_error(self.env, "not-found")
            return getattr(control, method)()
        if method == "run_export":
            run = self.env["ea.audit.automation.run"].browse(int(res_id or 0)).exists()
            if not run or run.sudo().engagement_id != self.sudo():
                raise rule_error(self.env, "not-found")
            return run.action_export()
        if method not in (
            "action_sampling_controls", "action_open_tod_wizard", "action_open_tod_result_wizard", "action_open_sampling_wizard",
            "action_export_toc_samples", "action_sampling_results", "action_sampling_runs", "action_sampling_board",
        ):
            raise rule_error(self.env, "forbidden")
        return getattr(self, method)()

    def action_sampling_controls(self):
        return self._ea_list(
            "ea.audit.scot.control", self.env._("Tests of controls"),
            [("ea_audit_tools.view_control_sampling_list", "list"), ("ea_audit_tools.view_control_form", "form")],
            {"domain": [("engagement_id", "=", self.id), ("selected_for_testing", "=", True)], "context": {"ea_engagement_id": self.id, "create": False}},
        )

    def action_sampling_results(self):
        return self._ea_list(
            "ea.audit.automation.run", self.env._("Tests of details: results"),
            [("ea_audit_tools.view_tod_result_list", "list")],
            {"domain": [("engagement_id", "=", self.id), ("method", "=", "tod-mus")], "context": {"ea_engagement_id": self.id, "create": False}},
        )

    def action_sampling_runs(self):
        return self._ea_list(
            "ea.audit.automation.run", self.env._("Sampling runs"),
            [("ea_audit_tools.view_sampling_run_list", "list")],
            {"domain": [("engagement_id", "=", self.id), ("engine", "=", "sampling"), ("method", "!=", "tod-mus")], "context": {"ea_engagement_id": self.id, "create": False}},
        )

    def _ea_action_wizard(self, model, name):
        self.ensure_one()
        self._ea_require_access()
        return {"type": "ir.actions.act_window", "name": name, "res_model": model, "view_mode": "form", "target": "new", "context": {"default_engagement_id": self.id}}

    def action_open_tod_wizard(self):
        return self._ea_action_wizard("ea.audit.tod.wizard", self.env._("Tests of details: plan"))

    def action_open_tod_result_wizard(self):
        return self._ea_action_wizard("ea.audit.tod.result.wizard", self.env._("Record a result"))

    def action_open_sampling_wizard(self):
        return self._ea_action_wizard("ea.audit.sampling.wizard", self.env._("Draw a sample from a dataset"))

    def action_export_toc_samples(self):
        return self._ea_export_action("toc_samples")

    def _ea_export_dynamic_method(self, kind):
        if _TOD_KIND.match(kind or "") or _RUN_KIND.match(kind or ""):
            return lambda fr: self._ea_export_dynamic(kind, fr)
        return super()._ea_export_dynamic_method(kind)

    def _ea_export_dynamic(self, kind, fr):
        tod = _TOD_KIND.match(kind)
        if tod:
            view = self.tod_side_view(tod[1], tod[2])
            view["locale"] = "fr" if fr else "en"
            side = "balance-sheet" if tod[1] == "bs" else "income-statement"
            client = re.sub(r"[^\w-]+", "_", view["clientName"])
            return "Tests-of-details-%s-%s-%s.xlsx" % (side, client, view["fiscalYear"]), tod_workbook(view, fr)
        run = self.env["ea.audit.automation.run"].sudo().search([
            ("id", "=", int(_RUN_KIND.match(kind)[1])), ("engagement_id", "=", self.id),
        ], limit=1)
        if not run:
            raise rule_error(self.env, "not-found")
        from ..exports import simple_workbook

        return "run-%d-%s.xlsx" % (run.id, self._ea_export_slug()), simple_workbook(
            run.title, run.sheet_header or ["—"], run.sheet_rows or [],
        )

    def _ea_export_toc_samples(self, fr):
        """Every control selected on S2.1, with the population and the items drawn."""
        as_root = self.sudo()
        controls = []
        for control in self.env["ea.audit.scot.control"].sudo().with_context(lang=self.env.lang).search([
            ("engagement_id", "=", self.id), ("selected_for_testing", "=", True),
        ]):
            controls.append({
                "controlName": control.name, "scotName": control.scot_id.name, "controlType": control.control_type,
                "frequency": control.frequency_effective or control.frequency, "assertions": control._ea_assertions(), "population": control.toc_population or None,
                "sampleSize": control.sample_size or control.suggested_size or None, "rule": control.suggested_rule or None,
                "items": control.toc_sample_items or [], "drawnAt": french_date(control.toc_sample_drawn_at),
            })
        client = re.sub(r"[^\w-]+", "_", as_root.client_id.name)
        return "Tests-of-controls-samples-%s-%s.xlsx" % (client, as_root.fiscal_year), toc_sample_workbook({
            "clientName": as_root.client_id.name, "fiscalYear": as_root.fiscal_year, "periodEnd": french_date(as_root.period_end),
            "preparer": self.env.user.name, "controls": controls,
        }, fr)

    def _ea_index_label(self, code, fr):
        for definition in LEAD_INDEXES:
            if definition["code"] == code:
                return lead_index_label(definition, "fr" if fr else "en")
        return code
