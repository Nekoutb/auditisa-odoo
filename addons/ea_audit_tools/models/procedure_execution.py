"""Execution of the substantive procedures (owner's mock-ups of 2026-11-16, mock-proc-exec-*).

The "Substantive procedures" page shows only what Procedure design selected, one card per account
with its progress; an account whose design is not finished (a High combined risk without an
alternative) is flagged. Each procedure opens its working paper: the steps from the library, the
sample drawn for it, its evidence, its conclusion, and the findings raised from it.

Four procedures are partly done by the tool:

* a reconciliation (E, N, F): the sub-ledger upload against the ledger accounts of the trial
  balance (else the general ledger); the auditor explains the difference and concludes;
* a cut-off test: the ledger entries of the last days of the year and, from the next-year ledger,
  of the first days of the next one, above a threshold; kept as a sample of the Sampling page,
  frozen once one entry has an answer;
* the search for unrecorded liabilities: next-year payments and expenses above the threshold;
* third-party confirmations: the requests, the replies and their differences.

Where the work is stored
------------------------
``ea.audit.designed.procedure.work_data`` (one JSON column): the steps ticked, the reconciliation's
explanations, whether a confirmations block was added. The selection is an
ea.audit.automation.run (engine "sampling", method "cutoff" or "unrecorded") whose
``item_results`` hold the answer per entry. Evidence files are ea.audit.task.attachment rows of the
account's E4.x task, tagged with the procedure. Confirmations are ea.audit.confirmation rows.
"""
from odoo import api, fields, models

from odoo.addons.ea_audit_papers.models.errors import paper_error

from ..rules import rule_error
from ..services.errors import ServiceError
from ..services.gl_line import projector
from ..services.lead_classes import INDEX_SECTION, LEAD_INDEX_BY_CODE, lead_index_label
from ..services.procedure_design import design_state, sample_mode
from ..services.procedure_execution import (
    CONCLUSIONS, CONFIRMATION_STATUSES, CUTOFF_DAYS, CUTOFF_FAMILIES, RECON, UNRECORDED_DAYS, clean_cutoff_patch,
    clean_explanation, clean_selection_params, confirmation_difference, confirmation_state, cutoff_select,
    default_threshold, gl_accounts, largest_parties, progress, recon_compare, selection_counts,
    split_steps, unrecorded_select,
)
from ..services.procedure_tools import (
    COUNT_CHECK_KEYS, COUNT_PHASES, COUNT_SIZE, FLOOR_MAX, account_state, clean_count_patch, clean_count_size,
    clean_floor_item, clean_rollforward, confirmation_pick, count_item, count_left, count_sample, far_number, far_recon,
    rollforward, working_order,
)
from ..services.ws_pages import sample_items
from .tool_record import free_name, french_date, grouped, is_french
from .worksheet_pages import FINDING_KINDS

SELECTION_METHODS = ("cutoff", "unrecorded")
#: The test counts sheet to floor of F-M1: a run answered on the working paper, as the selections.
COUNT_METHOD = "count"
PAPER_METHODS = SELECTION_METHODS + (COUNT_METHOD,)
#: the kinds of misstatement a working paper's conclusion records (ISA 450 A6)
PAPER_MTYPES = ("factual", "judgmental", "projected")
PROC_MODEL = "ea.audit.designed.procedure"


class DesignedProcedureWork(models.Model):
    _inherit = "ea.audit.designed.procedure"

    work_data = fields.Json(string="Work done", help="Steps ticked, explanations, blocks added: see procedure_execution.py.")
    file_item_id = fields.Many2one(
        "ea.audit.file.item", string="Paper", compute="_compute_file_item", compute_sudo=True,
        help="The account's E4.x task: where the evidence is filed and the findings point.",
    )
    confirmation_ids = fields.One2many("ea.audit.confirmation", "designed_procedure_id", string="Confirmations")

    @api.depends("index_code", "engagement_id")
    def _compute_file_item(self):
        Item = self.env["ea.audit.file.item"].sudo()
        for proc in self:
            code = INDEX_SECTION.get(proc.index_code)
            proc.file_item_id = Item.search([("engagement_id", "=", proc.engagement_id.id), ("code", "=", code)], limit=1) if code else False

    def _ea_mode(self):
        """What the tool does on this procedure: recon, cutoff, unrecorded, sample or plain."""
        self.ensure_one()
        item = self.library_id
        if item and item.automatable == "confirmation":
            return "confirm"
        if item and item.automatable == "count_attendance":
            return "count"
        if item and item.automatable == "reconciliation" and self.index_code == "K":
            return "far"
        if item and item.automatable == "reconciliation" and self.index_code in RECON:
            return "recon"
        if item and item.automatable == "cutoff_selection" and self.index_code in CUTOFF_FAMILIES:
            return "cutoff"
        if item and "unrecorded" in (item.title_en or "").lower():
            return "unrecorded"
        if item and sample_mode(item._ea_rule()) == "draw":
            return "sample"
        return "plain"

    def _ea_confirmations_on(self):
        """Confirmations are their own procedures (E customers, N suppliers; owner, 2026-11-16).
        Requests recorded earlier on another procedure stay visible there, read only."""
        self.ensure_one()
        return self._ea_mode() == "confirm" or bool(self.confirmation_ids)

    def _ea_count_run(self):
        self.ensure_one()
        return self.sudo().run_ids.filtered(lambda r: r.method == COUNT_METHOD).sorted("id", reverse=True)[:1]

    def _ea_selection_run(self):
        self.ensure_one()
        return self.sudo().run_ids.filtered(lambda r: r.method in SELECTION_METHODS).sorted("id", reverse=True)[:1]


class Confirmation(models.Model):
    """One third-party confirmation request of a procedure: a customer, a supplier, a bank, a
    lawyer. The difference is worked out, never typed."""

    _name = "ea.audit.confirmation"
    _inherit = ["ea.audit.tool.record"]
    _description = "Third-party confirmation"
    _order = "designed_procedure_id, sequence, id"
    _rec_name = "party"

    designed_procedure_id = fields.Many2one(PROC_MODEL, string="Procedure", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    party = fields.Char(string="Party", required=True)
    book_amount = fields.Float(string="Book amount", digits=(18, 2))
    sent_on = fields.Date(string="Sent on")
    status = fields.Selection([
        ("to_send", "To send"), ("sent", "Sent"), ("reminder", "Reminder sent"),
        ("received", "Received"), ("no_reply", "No reply"),
    ], default="to_send", required=True)
    confirmed_amount = fields.Float(string="Confirmed amount", digits=(18, 2))
    has_reply_amount = fields.Boolean()
    explanation = fields.Text()
    finding_id = fields.Many2one("ea.audit.finding", string="Finding", ondelete="set null")


class TaskAttachmentProcedure(models.Model):
    _inherit = "ea.audit.task.attachment"

    designed_procedure_id = fields.Many2one(
        PROC_MODEL, string="Procedure", ondelete="set null", index=True,
        help="The substantive procedure this evidence supports.",
    )


class EngagementProcedureExecution(models.Model):
    _inherit = "ea.audit.engagement"

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_tool_substantive(self):
        """The "Substantive procedures" page (owner's mock-up of 2026-11-16)."""
        self.ensure_one()
        self._ea_require_access()
        return {
            "type": "ir.actions.client", "tag": "ea_audit_tools.substantive_page", "target": "current",
            "name": self.env._("Substantive procedures"), "params": {"engagement_id": self.id},
            "context": {"active_id": self.id, "ea_engagement_id": self.id},
        }

    def _ea_paper_action(self, proc):
        return {
            "type": "ir.actions.client", "tag": "ea_audit_tools.procedure_paper", "target": "current",
            "name": proc.code, "params": {"engagement_id": self.id, "procedure_id": proc.id},
            "context": {"active_id": self.id, "ea_engagement_id": self.id},
        }

    def ea_exec_open(self, method, res_id=None):
        """The pages' links: a working paper, a sample on the Sampling page, a finding, the design,
        drawing a sample, the uploads."""
        self.ensure_one()
        self._ea_require_access()
        if method == "paper":
            return self._ea_paper_action(self._ea_exec_proc(res_id, selected=True))
        if method == "account":
            # an account opens on its first procedure not done yet, in working order
            tabs = self._ea_exec_tabs(str(res_id or ""))
            if not tabs:
                return self.action_tool_dsp()
            first = next((t for t in tabs if t["state"] != "done"), tabs[0])
            return self._ea_paper_action(self._ea_exec_proc(first["id"], selected=True))
        if method == "draw":
            return self.ea_procedure_draw(res_id)
        if method == "sample":
            return self.ea_procedure_open("sample", res_id)
        if method == "finding":
            finding = self.env["ea.audit.finding"].sudo().browse(int(res_id or 0)).exists()
            if not finding or finding.engagement_id != self.sudo():
                raise rule_error(self.env, "not-found")
            return self.with_context(ea_finding_id=finding.id).action_tool_findings()
        if method not in ("action_tool_dsp", "action_tool_substantive", "action_tool_findings", "action_tool_sampling", "action_tool_data_analytics", "action_tool_sad"):
            raise rule_error(self.env, "forbidden")
        return getattr(self, method)()

    # ------------------------------------------------------------------
    # The overview
    # ------------------------------------------------------------------

    def _ea_exec_lang(self):
        return "fr_FR" if is_french(self.env) else "en_US"

    def _ea_exec_findings(self, procs):
        """{procedure id: findings raised from it}."""
        out = {}
        if not procs:
            return out
        for finding in self.env["ea.audit.finding"].sudo().search([
            ("engagement_id", "=", self.id), ("source_model", "=", PROC_MODEL), ("source_id", "in", procs.ids),
        ]):
            out.setdefault(finding.source_id, self.env["ea.audit.finding"].sudo())
            out[finding.source_id] |= finding
        return out

    def _ea_exec_tabs(self, index_code, findings=None):
        """The procedures of one account in working order (MSP, ASP, own), for the tabs."""
        procs = self.env[PROC_MODEL].sudo().search([
            ("engagement_id", "=", self.id), ("index_code", "=", index_code), ("selected", "=", True), ("in_scope", "=", True),
        ])
        if findings is None:
            findings = self._ea_exec_findings(procs)
        rows = [{
            "id": p.id, "code": p.code, "kind": p.kind, "title": p.title or "", "state": p.state, "sequence": p.sequence,
            "flag": bool((findings.get(p.id) or self.env["ea.audit.finding"]).filtered(lambda f: f.status == "open")),
        } for p in procs]
        return working_order(rows)

    def _ea_exec_items(self, proc):
        """(done, total) items of the procedure's sample or selection, or (None, None)."""
        count_run = proc._ea_count_run()
        if count_run:
            results = count_run.item_results or {}
            keys = [str(row[0]) for row in count_run.sheet_rows or [] if row]
            return len([k for k in keys if (results.get(k) or {}).get("counted") is not None]), len(keys)
        run = proc._ea_selection_run()
        if run:
            keys = [row[0] for row in run.sheet_rows or [] if row]
            counts = selection_counts(keys, run.item_results)
            return counts["done"], counts["total"]
        run = proc.run_ids.filtered(lambda r: r.engine == "sampling" and r.method not in PAPER_METHODS + ("tod-mus",)).sorted("id", reverse=True)[:1]
        if run:
            keys = [str(row[0]) for row in run.sheet_rows or [] if row]
            results = run.item_results or {}
            done = len([k for k in keys if (results.get(k) or {}).get("audited") is not None])
            return done, len(keys)
        return None, None

    def ea_substantive_page(self):
        """What the "Substantive procedures" page shows: the selected procedures, by account."""
        self.ensure_one()
        self._ea_require_access()
        root = self.sudo()
        root._ea_sync_procedures()
        lang = self._ea_exec_lang()
        fr = lang == "fr_FR"
        reason = self._ea_ws_readonly()
        Cell = self.env["ea.audit.cra.assessment"].with_context(lang=lang)
        levels_label = dict(Cell._fields["level"]._description_selection(Cell.env))
        procs = self.env[PROC_MODEL].sudo().with_context(lang=lang).search([
            ("engagement_id", "=", self.id), ("selected", "=", True), ("in_scope", "=", True),
        ])
        findings = self._ea_exec_findings(procs)
        cards, all_states, finding_count, sad_total = [], [], 0, 0.0
        Library = self.env["ea.audit.procedure.library"].sudo()
        for account in root._ea_design_accounts():
            code = account["code"]
            mine = procs.filtered(lambda p: p.index_code == code)
            chosen = [{"kind": p.kind, "assertions": (p.assertions or "").split(",")} for p in mine]
            status = design_state(account["levels"], account["relevant"], chosen)
            # an account the library does not cover yet: the team's own procedures only
            own_only = not Library.search_count([("cycle", "=", code)])
            if not mine and not status["missing_asp"] and not own_only:
                continue
            chips = []
            for proc in self.env[PROC_MODEL].sudo().browse([t["id"] for t in self._ea_exec_tabs(code, findings)]).with_context(lang=lang):
                done, total = self._ea_exec_items(proc)
                raised = findings.get(proc.id) or self.env["ea.audit.finding"]
                chips.append({
                    "id": proc.id, "code": proc.code, "kind": proc.kind, "title": proc.title or "", "state": proc.state,
                    "items": "%d/%d" % (done, total) if total and proc.state == "started" else "",
                    "flag": bool(raised.filtered(lambda f: f.status == "open")),
                })
                all_states.append(proc.state)
                finding_count += len(raised)
                sad_total += sum(f.amount for f in raised if f.route == "b5")
            count = progress(p.state for p in mine)
            mine_findings = sum(len(findings.get(p.id) or []) for p in mine)
            item = root._ea_exec_task(code)
            definition = LEAD_INDEX_BY_CODE.get(code)
            cards.append({
                "code": code, "label": lead_index_label(definition, "fr" if fr else "en") if definition else code,
                "closing": grouped(account["row"].closing or 0, lang),
                "levels": [{"assertion": c.assertion, "level": c.level, "label": levels_label.get(c.level, c.level or "")} for c in account["cells"]],
                "preparer": (item.preparer_id.name if item and "preparer_id" in item._fields and item.preparer_id else ""),
                "chips": chips, "done": count["done"], "started": count["started"], "total": count["total"],
                "findings": mine_findings, "missing": status["missing_asp"], "complete": status["complete"],
                "ready": bool(count["total"]) and count["done"] == count["total"],
                "state": account_state(count["done"], count["started"], count["total"]),
                "ownOnly": own_only,
                "flag": any(chip["flag"] for chip in chips),
            })
        overall = progress(all_states)
        return {
            "engagement": root.display_name, "engagementId": root.id, "readonly": bool(reason), "archived": reason == "archived",
            "stats": {
                "designed": overall["total"], "done": overall["done"], "started": overall["started"],
                "findings": finding_count, "sad": grouped(sad_total, lang),
            },
            "accounts": cards,
            "missing": False if cards else (root._ea_cra_missing() if not root.cra_row_ids else "design"),
        }

    def _ea_exec_task(self, index_code):
        code = INDEX_SECTION.get(index_code)
        if not code:
            return self.env["ea.audit.file.item"]
        return self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.id), ("code", "=", code)], limit=1)

    def _ea_export_substantive(self, fr):
        from ..exports import simple_workbook

        head = ["Compte", "Procédure", "Type", "Intitulé", "Assertions", "État", "Conclusion"] if fr else [
            "Account", "Procedure", "Type", "Title", "Assertions", "State", "Conclusion"]
        lang = "fr_FR" if fr else "en_US"
        Proc = self.env[PROC_MODEL].sudo().with_context(lang=lang)
        states = dict(Proc._fields["state"]._description_selection(Proc.env))
        conclusions = dict(Proc._fields["conclusion"]._description_selection(Proc.env))
        rows = [[
            proc.index_code, proc.code, proc.kind, proc.title or "", proc.assertions or "", states.get(proc.state, proc.state),
            conclusions.get(proc.conclusion, "") if proc.conclusion else "",
        ] for proc in Proc.search([("engagement_id", "=", self.id), ("selected", "=", True), ("in_scope", "=", True)])]
        return "e4-procedures-%s.xlsx" % self._ea_export_slug(), simple_workbook("E4", head, rows)

    # ------------------------------------------------------------------
    # The working paper
    # ------------------------------------------------------------------

    def _ea_exec_proc(self, proc_id, selected=False):
        proc = self.env[PROC_MODEL].sudo().browse(int(proc_id or 0)).exists()
        if not proc or proc.engagement_id != self.sudo() or (selected and not proc.selected):
            raise rule_error(self.env, "not-found")
        return proc

    def _ea_exec_writable(self, proc_id):
        """The procedure, after the write guard; refused once it is done (reopen it first)."""
        self.ensure_one()
        self._ea_tool_guard()
        proc = self._ea_exec_proc(proc_id, selected=True)
        if proc.state == "done":
            raise rule_error(self.env, "procedure-done")
        return proc

    def _ea_exec_started(self, proc):
        if proc.state == "draft":
            proc._ea_mark_started()

    def ea_procedure_paper(self, proc_id):
        """What a procedure's working paper shows."""
        self.ensure_one()
        self._ea_require_access()
        root = self.sudo()
        proc = self._ea_exec_proc(proc_id, selected=True)
        lang = self._ea_exec_lang()
        fr = lang == "fr_FR"
        proc = proc.with_context(lang=lang)
        reason = self._ea_ws_readonly()
        Cell = self.env["ea.audit.cra.assessment"].with_context(lang=lang)
        levels_label = dict(Cell._fields["level"]._description_selection(Cell.env))
        account = next((a for a in root._ea_design_accounts() if a["code"] == proc.index_code), None)
        levels = account["levels"] if account else {}
        assertions = [a for a in (proc.assertions or "").split(",") if a]
        item = proc.library_id
        summary = ((item.summary_fr if fr else item.summary_en) or "") if item else (proc.custom_text or "")
        work = proc.work_data or {}
        ticks = work.get("steps") or {}
        steps = [{
            "index": i, "text": text, "done": bool(ticks.get(str(i))),
            "by": (ticks.get(str(i)) or {}).get("by", ""), "at": (ticks.get(str(i)) or {}).get("at", ""),
        } for i, text in enumerate(split_steps(summary))]
        mode = proc._ea_mode()
        if mode == "count":
            # the attendance at the count works from its three checklists, not the summary's sentences
            steps = []
        approved = root._ea_approved_materiality()
        Proc = self.env[PROC_MODEL].with_context(lang=lang)
        states = dict(Proc._fields["state"]._description_selection(Proc.env))
        definition = LEAD_INDEX_BY_CODE.get(proc.index_code)
        findings = self._ea_exec_findings(proc).get(proc.id) or self.env["ea.audit.finding"]
        Finding = self.env["ea.audit.finding"].with_context(lang=lang)
        routes = dict(Finding._fields["route"]._description_selection(Finding.env))
        Misstatement = self.env["ea.audit.misstatement"].with_context(lang=lang)
        mtypes = dict(Misstatement._fields["mtype"]._description_selection(Misstatement.env))
        page = {
            "id": proc.id, "code": proc.code, "kind": proc.kind, "title": proc.title or "", "summary": summary,
            "when": ((item.when_fr if fr else item.when_en) or "") if item else "",
            "index": proc.index_code, "indexLabel": lead_index_label(definition, "fr" if fr else "en") if definition else proc.index_code,
            "assertions": [{"code": a, "level": levels.get(a) or "", "label": levels_label.get(levels.get(a), "")} for a in assertions],
            "state": proc.state, "stateLabel": states.get(proc.state, proc.state),
            "conclusion": proc.conclusion or False, "note": proc.conclusion_note or "",
            "doneBy": proc.done_by_id.name or "", "doneAt": french_date(proc.done_at),
            "readonly": bool(reason), "archived": reason == "archived", "locked": proc.state == "done",
            "periodEnd": french_date(root.period_end),
            "steps": steps, "mode": mode,
            "performance": approved.performance if approved else None,
            "trivial": approved.trivial if approved else None,
            "samples": [], "canDraw": mode == "sample",
            "recon": None, "selection": None, "confirm": None, "far": None, "count": None,
            "tabs": self._ea_exec_tabs(proc.index_code),
            "evidence": self._ea_exec_evidence(proc),
            "findings": [{
                "id": f.id, "ref": f.reference or "", "title": f.title, "route": f.route, "routeLabel": routes.get(f.route, f.route),
                "amount": f.amount if f.route == "b5" else None, "status": f.status,
                "accounts": f.misstatement_id.accounts or "" if f.route == "b5" else "",
                "mtypeLabel": mtypes.get(f.misstatement_id.mtype, "") if f.route == "b5" else "",
            } for f in findings],
            "mtypes": [{"value": key, "label": mtypes[key]} for key in PAPER_MTYPES],
        }
        misstated = [f for f in findings if f.route == "b5"]
        page["misstatements"] = {"count": len(misstated), "total": sum(abs(f.misstatement_id.amount) for f in misstated)}
        for run in proc.run_ids.filtered(lambda r: r.engine == "sampling" and r.method not in PAPER_METHODS and r.method != "tod-mus").sorted("id"):
            page["samples"].append(self._ea_exec_sample(run, lang))
        if mode == "recon":
            page["recon"] = self._ea_exec_recon(proc, lang)
        if mode in ("cutoff", "unrecorded"):
            page["selection"] = self._ea_exec_selection_view(proc, mode, lang)
        if mode == "far":
            page["far"] = self._ea_exec_far(proc)
        if mode == "count":
            page["count"] = self._ea_exec_count(proc, lang)
        if proc._ea_confirmations_on():
            page["confirm"] = self._ea_exec_confirm_view(proc, lang)
            page["confirm"]["editable"] = mode == "confirm"
            page["confirm"]["side"] = "suppliers" if proc.index_code == "N" else "customers"
        left = len([s for s in steps if not s["done"]])
        if page["selection"]:
            left_items = page["selection"]["counts"]["total"] - page["selection"]["counts"]["done"]
        else:
            left_items = 0
        explain = False
        if page["count"]:
            left += page["count"]["left"]["checks"]
            left_items += page["count"]["left"]["items"]
        if page["far"]:
            explain = page["far"]["state"] == "difference"
        page["toTick"] = {"steps": left, "items": left_items, "explain": explain}
        return page

    def _ea_exec_sample(self, run, lang):
        picks, book, results = self._ea_sample_items(run)
        rows, totals = sample_items(picks, book, results)
        summary = run.summary or {}
        Wizard = self.env["ea.audit.sampling.wizard"].with_context(lang=lang)
        methods = dict(Wizard._fields["method"]._description_selection(Wizard.env))
        threshold = (run.params or {}).get("threshold")
        rule = methods.get(run.method, run.method or "")
        if threshold:
            rule = "%s · ≥ %s" % (rule, grouped(threshold, lang))
        return {
            "id": run.id, "title": run.purpose or run.title, "dataset": run.dataset_id.source_filename or "",
            "population": summary.get("populationTotal"), "populationRows": summary.get("populationRows"),
            "rule": rule, "size": len(picks), "drawnOn": french_date(run.create_date),
            "rows": rows, "totals": totals, "concluded": summary.get("projected") is not None,
        }

    def _ea_exec_evidence(self, proc):
        rows = self.env["ea.audit.task.attachment"].sudo().search([
            ("designed_procedure_id", "=", proc.id), ("deleted_at", "=", False),
        ], order="version desc, id desc")
        latest = {}
        for row in rows:
            latest.setdefault(row.name, {
                "id": row.id, "name": row.name, "version": row.version, "attachment_id": row.attachment_id.id,
                "by": row.uploaded_by_id.name or "", "date": row.uploaded_at.strftime("%d/%m/%Y") if row.uploaded_at else "",
                "url": "/web/content/%d?download=true" % row.attachment_id.id,
                "ext": row.name.rsplit(".", 1)[-1][:4].upper() if "." in row.name else "DOC",
                **row._ea_carry_info(),
            })
        return sorted(latest.values(), key=lambda r: r["name"].lower())

    # ---- reconciliation ------------------------------------------------

    def _ea_exec_ledger_balances(self):
        """[(account, name, closing)] from the trial balance, else the ledger of the year; (rows, source)."""
        version = self._ea_current_tb_version()
        if version:
            return [(line.account_code, line.account_name, line.closing) for line in version.line_ids], "tb"
        ledger = self._ea_gl_datasets()[0]
        if not ledger:
            return [], None
        totals = {}
        for line in self._ea_exec_lines(ledger, "c"):
            entry = totals.setdefault(line["account"], [line.get("account_name") or "", 0.0])
            entry[1] += float(line["signed"] or 0)
        return [(account, name, value) for account, (name, value) in totals.items()], "gl"

    def _ea_exec_recon(self, proc, lang):
        root = self.sudo()
        config = RECON[proc.index_code]
        balances, source = root._ea_exec_ledger_balances()
        accounts = gl_accounts(balances, config["prefixes"], config["sign"])
        dataset = root._ea_current_dataset(config["kind"])
        sub_total = None
        parties = []
        if dataset:
            sub_total = dataset.total_amount if dataset.has_total else None
            mapping = dataset.mapping or {}
            party_col, name_col = mapping.get("party"), mapping.get("partyName")
            if party_col or name_col:
                self.env.cr.execute(
                    "SELECT data->>%s, data->>%s, amount FROM ea_audit_dataset_row WHERE dataset_id = %s",
                    [party_col or "", name_col or "", dataset.id],
                )
                parties = largest_parties([(p, n, float(a or 0)) for p, n, a in self.env.cr.fetchall()])
        explanations = [e for e in (proc.work_data or {}).get("recon") or [] if isinstance(e, dict)]
        result = recon_compare(accounts, sub_total, explanations)
        return dict(
            result, accounts=accounts, source=source, dataset=(dataset.source_filename or "") if dataset else "",
            datasetDate=french_date(dataset.create_date) if dataset else "", kind=config["kind"],
            parties=parties, explanations=explanations,
        )

    def ea_proc_explain(self, proc_id, op, index=None, values=None):
        """The reconciliation's explanations: add, change or remove one line."""
        proc = self._ea_exec_writable(proc_id)
        if proc._ea_mode() != "recon":
            raise rule_error(self.env, "invalid-value")
        work = dict(proc.work_data or {})
        lines = list(work.get("recon") or [])
        if op == "add":
            clean = clean_explanation(values or {"text": "", "amount": 0})
            if clean is None:
                raise rule_error(self.env, "invalid-value")
            lines.append(clean)
        elif op in ("update", "remove"):
            try:
                position = int(index)
                current = lines[position]
            except (TypeError, ValueError, IndexError):
                raise rule_error(self.env, "not-found") from None
            if op == "remove":
                lines.pop(position)
            else:
                clean = clean_explanation(dict(current, **(values or {})))
                if clean is None:
                    raise rule_error(self.env, "invalid-value")
                lines[position] = clean
        else:
            raise rule_error(self.env, "invalid-value")
        work["recon"] = lines
        proc.write({"work_data": work})
        self._ea_exec_started(proc)
        return self.ea_procedure_paper(proc.id)

    # ---- K-M1: fixed asset register against the ledger ---------------------

    def _ea_exec_dataset_rows(self, dataset):
        """[(row_no, amount, data)] of an upload."""
        self.env.cr.execute("SELECT row_no, amount, data FROM ea_audit_dataset_row WHERE dataset_id = %s ORDER BY row_no", [dataset.id])
        return self.env.cr.fetchall()

    def _ea_exec_far(self, proc):
        """The register by category against classes 21-25 and 28/29 of the ledger (mock-sub2-account)."""
        root = self.sudo()
        balances, source = root._ea_exec_ledger_balances()
        dataset = root._ea_current_dataset("fixed_asset_register")
        mapping = (dataset.mapping or {}) if dataset else {}
        rows = []
        for _row_no, amount, data in (self._ea_exec_dataset_rows(dataset) if dataset else []):
            data = data or {}

            def read(key, data=data):
                column = mapping.get(key)
                return far_number(data.get(column)) if column else None

            closing = read("nbv")
            if closing is None:
                cost = float(amount) if amount is not None else read("amount")
                depreciation = read("depreciation")
                closing = None if cost is None else cost - abs(depreciation or 0)
            rows.append({
                "category": str(data.get(mapping["category"]) or "") if mapping.get("category") else "",
                "account": str(data.get(mapping["account"]) or "") if mapping.get("account") else "",
                "opening": read("openingNbv"), "additions": read("additions"), "disposals": read("disposals"),
                "charge": read("charge"), "closing": closing,
            })
        text = ((proc.work_data or {}).get("far") or {}).get("explanation") or ""
        result = far_recon(rows, balances, text)
        return dict(
            result, explanation=text, source=source, dataset=(dataset.source_filename or "") if dataset else "",
            datasetDate=french_date(dataset.create_date) if dataset else "",
            mapped=sorted(key for key in ("category", "account", "openingNbv", "additions", "disposals", "charge") if mapping.get(key)),
        )

    def ea_proc_far(self, proc_id, explanation):
        """The explanation of what remains between the register and the ledger."""
        proc = self._ea_exec_writable(proc_id)
        if proc._ea_mode() != "far":
            raise rule_error(self.env, "invalid-value")
        work = dict(proc.work_data or {})
        work["far"] = dict(work.get("far") or {}, explanation=str(explanation or "").strip()[:5000])
        proc.write({"work_data": work})
        self._ea_exec_started(proc)
        return self.ea_procedure_paper(proc.id)

    # ---- F-M1: attendance at the physical count ------------------------------

    def _ea_exec_count(self, proc, lang):
        """The three checklists, the test counts both ways and the roll-forward (mock-sub2-count)."""
        root = self.sudo()
        work = (proc.work_data or {}).get("count") or {}
        checks = work.get("checks") or {}
        run = proc._ea_count_run()
        results = (run.item_results or {}) if run else {}
        sheet = []
        for position, row in enumerate((run.sheet_rows or []) if run else [], start=1):
            key = str(row[0])
            found = results.get(key) or {}
            per_sheet = row[6] if len(row) > 6 else None
            per_sheet = float(per_sheet) if isinstance(per_sheet, (int, float)) else None
            counted = found.get("counted")
            difference, state = count_item(per_sheet, counted)
            sheet.append({
                "position": position, "key": key, "reason": row[1], "item": row[3], "location": row[4], "label": row[5],
                "sheet": per_sheet, "amount": row[7] if len(row) > 7 else None, "counted": counted,
                "difference": difference, "state": state, "note": found.get("note") or "", "finding": found.get("finding") or False,
            })
        floor = []
        for index, entry in enumerate(work.get("floor") or []):
            difference, state = count_item(entry.get("sheet"), entry.get("counted"))
            floor.append(dict(entry, index=index, difference=difference, state=state, finding=entry.get("finding") or False))
        dataset = root._ea_current_dataset("inventory_listing")
        roll = work.get("roll") or {}
        final_upload = dataset.total_amount if dataset and dataset.has_total else None
        final = final_upload if final_upload is not None else roll.get("final")
        count_date = roll.get("countDate") or ""
        end = root.period_end.isoformat() if root.period_end else ""
        summary = (run.summary or {}) if run else {}
        return {
            "checks": {key: bool(checks.get(key)) for key in COUNT_CHECK_KEYS},
            "checkedBy": {key: checks[key] for key in COUNT_CHECK_KEYS if isinstance(checks.get(key), dict)},
            "notes": {phase: (work.get("notes") or {}).get(phase) or "" for phase in COUNT_PHASES},
            "runId": run.id if run else False, "size": (run.params or {}).get("size") if run else COUNT_SIZE,
            "drawnOn": french_date(run.create_date) if run else "",
            "population": summary.get("populationRows"), "populationValue": summary.get("populationTotal"),
            "frozen": any((v or {}).get("counted") is not None for v in results.values()),
            "sheet": sheet, "floor": floor, "floorMax": FLOOR_MAX,
            "hasListing": bool(dataset), "listing": (dataset.source_filename or "") if dataset else "",
            "roll": {
                "countDate": count_date, "count": roll.get("count"), "receipts": roll.get("receipts"), "issues": roll.get("issues"),
                "final": final, "finalFromUpload": final_upload is not None,
                "needed": bool(count_date) and bool(end) and count_date != end, "yearEnd": end,
                **rollforward(roll.get("count"), roll.get("receipts"), roll.get("issues"), final),
            },
            "left": count_left(checks, sheet, floor),
        }

    def ea_proc_count(self, proc_id, op, key=None, values=None):
        """The count's working paper: a check ticked, a phase's note, the test counts drawn
        (again, until the first is counted), one counted, an item from the floor, the roll-forward."""
        proc = self._ea_exec_writable(proc_id)
        if proc._ea_mode() != "count":
            raise rule_error(self.env, "invalid-value")
        values = values if isinstance(values, dict) else {}
        if op == "draw":
            self._ea_exec_count_draw(proc, values.get("size"))
            self._ea_exec_started(proc)
            return self.ea_procedure_paper(proc.id)
        if op == "item":
            self._ea_exec_count_item(proc, key, values)
            self._ea_exec_started(proc)
            return self.ea_procedure_paper(proc.id)
        work = dict(proc.work_data or {})
        count = dict(work.get("count") or {})
        if op == "check":
            if key not in COUNT_CHECK_KEYS:
                raise rule_error(self.env, "not-found")
            checks = dict(count.get("checks") or {})
            if values.get("done"):
                checks[key] = {"by": self.env.user.name, "at": french_date(fields.Date.context_today(self))}
            else:
                checks.pop(key, None)
            count["checks"] = checks
        elif op == "note":
            if key not in COUNT_PHASES:
                raise rule_error(self.env, "not-found")
            count["notes"] = dict(count.get("notes") or {}, **{key: str(values.get("text") or "").strip()[:3000]})
        elif op in ("floor_add", "floor_update", "floor_remove"):
            count["floor"] = self._ea_exec_floor(list(count.get("floor") or []), op, key, values)
        elif op == "roll":
            clean = clean_rollforward(values)
            if clean is None:
                raise rule_error(self.env, "invalid-value")
            count["roll"] = dict(count.get("roll") or {}, **clean)
        else:
            raise rule_error(self.env, "invalid-value")
        work["count"] = count
        proc.write({"work_data": work})
        self._ea_exec_started(proc)
        return self.ea_procedure_paper(proc.id)

    def _ea_exec_count_item(self, proc, key, values):
        run = proc._ea_count_run()
        if not run or str(key) not in {str(row[0]) for row in run.sheet_rows or [] if row}:
            raise rule_error(self.env, "not-found")
        clean = clean_count_patch(values)
        if clean is None:
            raise rule_error(self.env, "invalid-value")
        results = dict(run.item_results or {})
        entry = dict(results.get(str(key)) or {}, **clean)
        per_sheet = next((row[6] for row in run.sheet_rows if str(row[0]) == str(key) and len(row) > 6), None)
        _difference, state = count_item(per_sheet if isinstance(per_sheet, (int, float)) else None, entry.get("counted"))
        # the Sampling page reads the answer as the selections' (agreed / error)
        entry["ok"] = {"ok": "yes", "diff": "no", "missing": "no"}.get(state)
        results[str(key)] = entry
        run.write({"item_results": results})

    def _ea_exec_floor(self, floor, op, key, values):
        if op == "floor_add":
            if len(floor) >= FLOOR_MAX:
                raise rule_error(self.env, "invalid-value")
            clean = clean_floor_item(values, adding=True)
            if clean is None:
                raise rule_error(self.env, "invalid-value")
            floor.append(dict({"item": "", "location": "", "sheet": None, "counted": None, "note": ""}, **clean))
            return floor
        try:
            index = int(key)
            current = floor[index]
        except (TypeError, ValueError, IndexError):
            raise rule_error(self.env, "not-found") from None
        if op == "floor_remove":
            if current.get("finding"):
                raise rule_error(self.env, "invalid-value")
            floor.pop(index)
            return floor
        clean = clean_floor_item(values)
        if clean is None or ("item" in clean and not clean["item"]):
            raise rule_error(self.env, "invalid-value")
        floor[index] = dict(current, **clean)
        return floor

    def _ea_exec_count_draw(self, proc, size):
        """The test counts sheet to floor, drawn from the inventory listing: the highest values
        first, then at random. Kept as a run of the procedure; frozen once one item is counted."""
        size = clean_count_size(size if size not in (None, "") else COUNT_SIZE)
        if size is None:
            raise rule_error(self.env, "invalid-value")
        root = self.sudo()
        run = proc._ea_count_run()
        if run and any((v or {}).get("counted") is not None for v in (run.item_results or {}).values()):
            raise rule_error(self.env, "selection-frozen")
        dataset = root._ea_current_dataset("inventory_listing")
        if not dataset:
            raise rule_error(self.env, "no-dataset")
        mapping = dataset.mapping or {}
        rows = self._ea_exec_dataset_rows(dataset)
        by_no = {row_no: (amount, data or {}) for row_no, amount, data in rows}
        seed = "%s-%s" % (proc.id, len(proc.run_ids))
        picks = count_sample([(row_no, float(amount or 0)) for row_no, amount, _data in rows], size, seed)

        def text(data, key):
            column = mapping.get(key)
            return str(data.get(column) or "").strip()[:120] if column else ""

        sheet_rows = []
        for row_no, reason in picks:
            amount, data = by_no[row_no]
            quantity = far_number(data.get(mapping["quantity"])) if mapping.get("quantity") else None
            sheet_rows.append([str(row_no), reason, "", text(data, "item"), text(data, "location"), text(data, "itemDescription"),
                               quantity, float(amount) if amount is not None else None])
        values = {
            "engagement_id": root.id, "title": "Test counts", "engine": "sampling", "method": COUNT_METHOD,
            "dataset_id": dataset.id, "designed_procedure_id": proc.id, "index_code": proc.index_code,
            "purpose": ("%s %s" % (proc.code, proc.title or ""))[:200].strip(),
            "params": {"size": size, "seed": seed},
            "summary": {
                "populationRows": len(rows), "populationTotal": dataset.total_amount if dataset.has_total else None,
                "sampleSize": len(sheet_rows), "sampledValue": sum(abs(r[7] or 0) for r in sheet_rows),
            },
            "sheet_header": ["key", "reason", "date", "item", "location", "label", "quantity", "amount"],
            "sheet_rows": sheet_rows, "item_results": {},
        }
        if run:
            run.write(values)
        else:
            self.env["ea.audit.automation.run"].sudo().create(values)
        self._ea_log("procedure_selection", "Procedure %s %s: %d test counts drawn from the inventory listing" % (
            proc.index_code, proc.code, len(sheet_rows)))

    # ---- ledger lines --------------------------------------------------

    def _ea_exec_lines(self, dataset, prefix, first=None, last=None):
        """The lines of a ledger as the selections read them, between two dates (ISO) when given:
        its projection when built, else its rows read through its matching."""
        if not dataset:
            return []
        out = []
        if dataset.gl_built_at:
            query = """SELECT line_no, account, account_name, je_number, coalesce(journal_date, entry_date), signed,
                              coalesce(nullif(je_description, ''), line_description), third_party_name
                         FROM ea_audit_gl_line WHERE dataset_id = %s AND engagement_id = %s"""
            args = [dataset.id, self.id]
            if first and last:
                query += " AND coalesce(journal_date, entry_date) BETWEEN %s AND %s"
                args += [first, last]
            self.env.cr.execute(query + " ORDER BY line_no", args)
            for line_no, account, name, number, day, signed, label, third in self.env.cr.fetchall():
                out.append({
                    "key": "%s%s" % (prefix, line_no), "account": account or "", "account_name": name or "", "je_number": number or "",
                    "date": day.isoformat() if day else None, "signed": float(signed or 0), "label": label or "", "third": third or "",
                })
            return out
        try:
            project = projector(dataset.mapping)
        except ServiceError:
            return []
        self.env.cr.execute("SELECT row_no, data FROM ea_audit_dataset_row WHERE dataset_id = %s ORDER BY row_no", [dataset.id])
        for row_no, data in self.env.cr.fetchall():
            line = project(data or {})
            if not line:
                continue
            day = line["journal_date"] or line["entry_date"]
            if first and last and (not day or day < first or day > last):
                continue
            out.append({
                "key": "%s%s" % (prefix, row_no), "account": line["account"], "account_name": line.get("account_name") or "",
                "je_number": line["je_number"], "date": day, "signed": float(line["signed"] or 0),
                "label": line.get("je_description") or line.get("line_description") or "", "third": line.get("third_party_name") or "",
            })
        return out

    # ---- cut-off and unrecorded liabilities ------------------------------

    def _ea_exec_selection_params(self, proc, mode):
        run = proc._ea_selection_run()
        params = (run.params or {}) if run else {}
        approved = self.sudo()._ea_approved_materiality()
        threshold = params.get("threshold")
        if threshold is None:
            threshold = default_threshold(approved.performance if approved else None)
        days = params.get("days") or (CUTOFF_DAYS if mode == "cutoff" else UNRECORDED_DAYS)
        return days, threshold

    def _ea_exec_selection_view(self, proc, mode, lang):
        root = self.sudo()
        run = proc._ea_selection_run()
        days, threshold = self._ea_exec_selection_params(proc, mode)
        overview = self.ea_subsequent_overview()
        current = root._ea_gl_datasets()[0]
        items = []
        results = (run.item_results or {}) if run else {}
        for position, row in enumerate((run.sheet_rows or []) if run else [], start=1):
            key = str(row[0])
            found = results.get(key) or {}
            items.append({
                "position": position, "key": key, "side": row[1], "date": french_date(fields.Date.to_date(row[2])) if row[2] else "",
                "entry": row[3], "third": row[4], "label": row[5], "account": row[6], "amount": row[7],
                "period": found.get("period") or None, "doc": bool(found.get("doc")), "when": found.get("when") or "",
                "note": found.get("note") or "", "finding": found.get("finding") or False,
            })
        keys = [i["key"] for i in items]
        counts = selection_counts(keys, results)
        summary = (run.summary or {}) if run else {}
        params = (run.params or {}) if run else {}
        window = params.get("window") or {}
        return {
            "mode": mode, "runId": run.id if run else False, "runTitle": (run.purpose or run.title) if run else "",
            "days": days, "threshold": threshold, "frozen": bool(counts["done"]) or any(bool(v) for v in results.values()),
            "drawnOn": french_date(run.create_date) if run else "",
            "window": {"from": french_date(fields.Date.to_date(window["from"])) if window.get("from") else "",
                       "to": french_date(fields.Date.to_date(window["to"])) if window.get("to") else ""},
            "population": summary.get("populationRows"), "populationValue": summary.get("populationTotal"),
            "sampledValue": summary.get("sampledValue"),
            "items": items, "counts": counts,
            "hasCurrent": bool(current), "currentName": (current.source_filename or "") if current else "",
            "hasNext": bool(overview.get("datasetId")), "sentence": overview.get("sentence"), "warning": overview.get("warning"),
            "short": bool(overview.get("short")),
        }

    def ea_proc_select(self, proc_id, days, threshold):
        """The tool's selection for a cut-off test or the search for unrecorded liabilities, kept
        as a sample of the Sampling page. Run again while no entry has an answer; frozen after."""
        proc = self._ea_exec_writable(proc_id)
        mode = proc._ea_mode()
        if mode not in ("cutoff", "unrecorded"):
            raise rule_error(self.env, "invalid-value")
        clean = clean_selection_params(days, threshold)
        if clean is None:
            raise rule_error(self.env, "invalid-value")
        days, threshold = clean
        root = self.sudo()
        run = proc._ea_selection_run()
        if run and any(bool(value) for value in (run.item_results or {}).values()):
            raise rule_error(self.env, "selection-frozen")
        end = root.period_end
        if not end:
            raise rule_error(self.env, "invalid-value")
        current = root._ea_gl_datasets()[0]
        following = root._ea_subsequent_ledger()
        end_iso = end.isoformat()
        if mode == "cutoff":
            if not current:
                raise rule_error(self.env, "no-dataset")
            first = fields.Date.subtract(end, days=days - 1).isoformat()
            last = fields.Date.add(end, days=days).isoformat()
            result = cutoff_select(
                self._ea_exec_lines(current, "c", first, end_iso), self._ea_exec_lines(following, "s", end_iso, last) if following else [],
                end_iso, days, threshold, CUTOFF_FAMILIES[proc.index_code],
            )
            dataset = current
        else:
            if not following:
                raise rule_error(self.env, "no-dataset")
            last = fields.Date.add(end, days=days).isoformat()
            result = unrecorded_select(self._ea_exec_lines(following, "s", end_iso, last), end_iso, days, threshold)
            dataset = following
        picks = result["picks"]
        values = {
            "engagement_id": root.id, "title": "Cut-off selection" if mode == "cutoff" else "Unrecorded liabilities",
            "engine": "sampling", "method": mode, "dataset_id": dataset.id, "designed_procedure_id": proc.id,
            "index_code": proc.index_code, "purpose": ("%s %s" % (proc.code, proc.title or ""))[:200].strip(),
            "params": {
                "days": days, "threshold": threshold, "window": result["window"], "currentId": current.id or False,
                "subsequentId": following.id or False,
            },
            "summary": {
                "populationRows": result["population"]["total"], "populationTotal": result["population"]["value"],
                "before": result["population"]["before"], "after": result["population"]["after"],
                "sampleSize": len(picks), "sampledValue": sum(abs(p["amount"]) for p in picks),
            },
            "sheet_header": ["key", "side", "date", "entry", "third", "label", "account", "amount"],
            "sheet_rows": [[p["key"], p["side"], p["date"], p["entry"], p["third"], p["label"], p["account"], p["amount"]] for p in picks],
            "item_results": {},
        }
        if run:
            run.write(values)
        else:
            run = self.env["ea.audit.automation.run"].sudo().create(values)
        self._ea_exec_started(proc)
        self._ea_log("procedure_selection", "Procedure %s %s: %d entries selected around year end" % (proc.index_code, proc.code, len(picks)))
        return self.ea_procedure_paper(proc.id)

    def ea_proc_select_item(self, proc_id, key, patch):
        """One selected entry: right period (yes or no), the document seen, the date, a note."""
        proc = self._ea_exec_writable(proc_id)
        run = proc._ea_selection_run()
        if not run or str(key) not in {str(row[0]) for row in run.sheet_rows or [] if row}:
            raise rule_error(self.env, "not-found")
        clean = clean_cutoff_patch(patch)
        if clean is None:
            raise rule_error(self.env, "invalid-value")
        results = dict(run.item_results or {})
        results[str(key)] = dict(results.get(str(key)) or {}, **clean)
        run.write({"item_results": results})
        self._ea_exec_started(proc)
        return self.ea_procedure_paper(proc.id)

    # ---- samples drawn on the Sampling page --------------------------------

    def ea_proc_sample_item(self, proc_id, run_id, row_no, patch):
        """One item of a sample drawn for the procedure, through the Sampling page's own rule."""
        proc = self._ea_exec_writable(proc_id)
        run = proc.run_ids.filtered(lambda r: r.id == int(run_id or 0))
        if not run or run.method in SELECTION_METHODS:
            raise rule_error(self.env, "not-found")
        run.with_env(self.env).ea_sampling_item(row_no, patch)
        self._ea_exec_started(proc)
        return self.ea_procedure_paper(proc.id)

    # ---- steps, conclusion -------------------------------------------------

    def ea_proc_step(self, proc_id, index, done):
        proc = self._ea_exec_writable(proc_id)
        item = proc.library_id
        count = len(split_steps((item.summary_en if item else proc.custom_text) or ""))
        try:
            index = int(index)
        except (TypeError, ValueError):
            raise rule_error(self.env, "invalid-value") from None
        if not 0 <= index < count:
            raise rule_error(self.env, "not-found")
        work = dict(proc.work_data or {})
        ticks = dict(work.get("steps") or {})
        if done:
            ticks[str(index)] = {"by": self.env.user.name, "at": french_date(fields.Date.context_today(self))}
        else:
            ticks.pop(str(index), None)
        work["steps"] = ticks
        proc.write({"work_data": work})
        self._ea_exec_started(proc)
        return self.ea_procedure_paper(proc.id)

    def ea_proc_save(self, proc_id, values):
        """The conclusion while it is written: the result and the note."""
        proc = self._ea_exec_writable(proc_id)
        if not isinstance(values, dict) or set(values) - {"conclusion", "note"}:
            raise rule_error(self.env, "invalid-field")
        out = {}
        if "conclusion" in values:
            if values["conclusion"] not in CONCLUSIONS + (False, None, ""):
                raise rule_error(self.env, "invalid-value")
            out["conclusion"] = values["conclusion"] or False
        if "note" in values:
            out["conclusion_note"] = str(values["note"] or "").strip()[:5000] or False
        proc.write(out)
        self._ea_exec_started(proc)
        return self.ea_procedure_paper(proc.id)

    def ea_proc_done(self, proc_id):
        """Mark as done: a result chosen, a note written, every step ticked, every selected entry answered."""
        proc = self._ea_exec_writable(proc_id)
        page = self.ea_procedure_paper(proc.id)
        left = page["toTick"]
        if not proc.conclusion or not (proc.conclusion_note or "").strip() or left["steps"] or left["items"] or left["explain"]:
            raise rule_error(self.env, "procedure-not-finished")
        proc.write({"state": "done", "done_by_id": self.env.user.id, "done_at": fields.Datetime.now()})
        self._ea_log("procedure_done", "Procedure %s %s done: %s" % (proc.index_code, proc.code, proc.conclusion))
        self._ea_invalidate_signoffs(INDEX_SECTION.get(proc.index_code) or "S5.5")
        return self.ea_procedure_paper(proc.id)

    def ea_proc_reopen(self, proc_id):
        self.ensure_one()
        self._ea_tool_guard()
        proc = self._ea_exec_proc(proc_id, selected=True)
        if proc.state != "done":
            return self.ea_procedure_paper(proc.id)
        proc.write({"state": "started", "done_by_id": False, "done_at": False})
        self._ea_log("procedure_reopened", "Procedure %s %s reopened" % (proc.index_code, proc.code))
        return self.ea_procedure_paper(proc.id)

    # ---- evidence --------------------------------------------------------

    def ea_proc_upload(self, proc_id, filename, content_b64):
        """Evidence of the procedure: a file of the account's E4.x task, tagged with the procedure."""
        proc = self._ea_exec_writable(proc_id)
        code = INDEX_SECTION.get(proc.index_code)
        if code:
            self.sudo()._ea_ensure_task(code)
        host = self._ea_exec_task(proc.index_code)
        if not host:
            raise rule_error(self.env, "not-found")
        name = (filename or "").strip()
        clash = self.env["ea.audit.task.attachment"].sudo().search_count([
            ("file_item_id", "=", host.id), ("name", "=", name), ("deleted_at", "=", False),
            ("designed_procedure_id", "!=", proc.id),
        ])
        if clash:
            raise paper_error(self.env, "name-taken")
        row_id = host.with_env(self.env).upload_attachment(filename, content_b64)
        self.env["ea.audit.task.attachment"].sudo().browse(row_id).designed_procedure_id = proc.id
        self._ea_exec_started(proc)
        return self.ea_procedure_paper(proc.id)

    def ea_proc_attach_existing(self, proc_id, row_ids):
        """Documents already in the engagement, attached as evidence of the procedure: no new upload."""
        proc = self._ea_exec_writable(proc_id)
        code = INDEX_SECTION.get(proc.index_code)
        if code:
            self.sudo()._ea_ensure_task(code)
        host = self._ea_exec_task(proc.index_code)
        if not host:
            raise rule_error(self.env, "not-found")
        Attachment = self.env["ea.audit.task.attachment"].sudo()
        created = host.with_env(self.env)._ea_attach_existing(
            row_ids, name_of=lambda name: free_name(self.env, host, name, ("designed_procedure_id", "!=", proc.id)),
        )
        Attachment.browse(created).write({"designed_procedure_id": proc.id})
        self._ea_exec_started(proc)
        return self.ea_procedure_paper(proc.id)

    def ea_proc_remove_file(self, proc_id, row_id):
        proc = self._ea_exec_writable(proc_id)
        row = self.env["ea.audit.task.attachment"].sudo().browse(int(row_id or 0)).exists()
        if not row or row.designed_procedure_id != proc:
            raise rule_error(self.env, "not-found")
        row.with_env(self.env).remove()
        return self.ea_procedure_paper(proc.id)

    # ---- findings --------------------------------------------------------

    def ea_proc_finding(
        self, proc_id, description, amount=None, finding_type="misstatement", trivial_confirmed=False, item_key=None,
        confirmation_id=None, dr_account=None, cr_account=None, mtype="factual",
    ):
        """A finding raised from the working paper: the one path, ea_raise_finding, with the
        procedure as its source. From a selected entry or a confirmation, it is noted on them.
        A misstatement (amount, accounts, description, type) becomes its line on the summary of
        audit differences, the only way a line gets there (owner's ruling of 2026-11-16)."""
        proc = self._ea_exec_writable(proc_id)
        if finding_type not in FINDING_KINDS:
            raise rule_error(self.env, "invalid-value")
        text = (description or "").strip()
        if not text:
            raise rule_error(self.env, "title-required")
        number = None
        if finding_type == "misstatement":
            if mtype not in PAPER_MTYPES:
                raise rule_error(self.env, "invalid-type")
            number = clean_explanation({"amount": amount})
            number = number["amount"] if number else None
        finding = self.ea_raise_finding(
            PROC_MODEL, proc.id, text[:200], amount=number, finding_type=finding_type,
            detail=text if len(text) > 200 else None, trivial_confirmed=bool(trivial_confirmed),
            mtype=mtype or "factual", dr_account=dr_account, cr_account=cr_account,
        )
        if item_key and str(item_key).startswith(("count:", "floor:")):
            self._ea_exec_count_finding(proc, str(item_key), finding)
        elif item_key:
            run = proc._ea_selection_run()
            if run and str(item_key) in {str(row[0]) for row in run.sheet_rows or [] if row}:
                results = dict(run.item_results or {})
                results[str(item_key)] = dict(results.get(str(item_key)) or {}, finding=finding.id)
                run.write({"item_results": results})
        if confirmation_id:
            request = proc.confirmation_ids.filtered(lambda c: c.id == int(confirmation_id))
            if request:
                request.write({"finding_id": finding.id})
        self._ea_exec_started(proc)
        return self.ea_procedure_paper(proc.id)

    def _ea_exec_count_finding(self, proc, item_key, finding):
        """A finding raised from a test count: noted on the item."""
        side, _sep, key = item_key.partition(":")
        if side == "count":
            run = proc._ea_count_run()
            if run and key in {str(row[0]) for row in run.sheet_rows or [] if row}:
                results = dict(run.item_results or {})
                results[key] = dict(results.get(key) or {}, finding=finding.id)
                run.write({"item_results": results})
            return
        work = dict(proc.work_data or {})
        count = dict(work.get("count") or {})
        floor = list(count.get("floor") or [])
        try:
            index = int(key)
            floor[index] = dict(floor[index], finding=finding.id)
        except (ValueError, IndexError):
            return
        count["floor"] = floor
        work["count"] = count
        proc.write({"work_data": work})

    # ---- confirmations -----------------------------------------------------

    def _ea_exec_parties(self, index_code, limit=50):
        """The parties of the account's sub-ledger, largest balance first (``limit`` 0: all)."""
        config = RECON.get(index_code)
        if not config:
            return []
        dataset = self.sudo()._ea_current_dataset(config["kind"])
        mapping = (dataset.mapping or {}) if dataset else {}
        if not dataset or not (mapping.get("party") or mapping.get("partyName")):
            return []
        self.env.cr.execute(
            "SELECT data->>%s, data->>%s, amount FROM ea_audit_dataset_row WHERE dataset_id = %s",
            [mapping.get("party") or "", mapping.get("partyName") or "", dataset.id],
        )
        return largest_parties([(p, n, float(a or 0)) for p, n, a in self.env.cr.fetchall()], limit=limit)

    def _ea_exec_confirm_view(self, proc, lang):
        Conf = self.env["ea.audit.confirmation"].with_context(lang=lang)
        statuses = dict(Conf._fields["status"]._description_selection(Conf.env))
        rows = []
        for request in proc.confirmation_ids.sorted(lambda c: (c.sequence, c.id)):
            confirmed = request.confirmed_amount if request.has_reply_amount else None
            rows.append({
                "id": request.id, "party": request.party, "book": request.book_amount,
                "sent": request.sent_on.isoformat() if request.sent_on else "", "status": request.status,
                "statusLabel": statuses.get(request.status, request.status), "confirmed": confirmed,
                "difference": confirmation_difference(request.book_amount, confirmed, request.status),
                "state": confirmation_state(request.book_amount, confirmed, request.status, request.explanation),
                "explanation": request.explanation or "", "finding": request.finding_id.id or False,
            })
        return {
            "rows": rows, "statuses": [{"value": key, "label": statuses[key]} for key in CONFIRMATION_STATUSES],
            "parties": self._ea_exec_parties(proc.index_code),
        }

    def ea_proc_confirm(self, proc_id, op, request_id=None, values=None):
        """The confirmations of a confirmation procedure (E customers, N suppliers): the largest
        balances proposed by the tool, a request added by hand, changed or removed. On any other
        procedure, requests recorded earlier are read only."""
        proc = self._ea_exec_writable(proc_id)
        if proc._ea_mode() != "confirm":
            raise rule_error(self.env, "invalid-value")
        values = values or {}
        Conf = self.env["ea.audit.confirmation"].sudo()
        if op == "pick":
            existing = [c.party for c in proc.confirmation_ids]
            parties = self._ea_exec_parties(proc.index_code, limit=0)
            if not parties:
                raise rule_error(self.env, "no-dataset")
            chosen = confirmation_pick(parties, existing, "%s-%s" % (proc.id, len(existing)))
            sequence = len(proc.confirmation_ids)
            for position, party in enumerate(chosen, start=1):
                Conf.create({
                    "engagement_id": self.id, "designed_procedure_id": proc.id, "party": party["name"] or party["party"],
                    "book_amount": party["amount"], "sequence": sequence + position,
                })
        elif op == "add":
            party = str(values.get("party") or "").strip()[:200]
            if not party:
                raise rule_error(self.env, "invalid-value")
            book = clean_explanation({"amount": values.get("book")}) if "book" in values else None
            if book is None and "book" in values:
                raise rule_error(self.env, "invalid-value")
            amount = book["amount"] if book and values.get("book") not in (None, "") else None
            if amount is None:
                lowered = party.lower()
                match = next((p for p in self._ea_exec_parties(proc.index_code) if lowered in (p["party"].lower(), p["name"].lower())), None)
                amount = match["amount"] if match else 0.0
            Conf.create({
                "engagement_id": self.id, "designed_procedure_id": proc.id, "party": party, "book_amount": amount,
                "sequence": len(proc.confirmation_ids) + 1,
            })
        elif op in ("update", "remove"):
            request = proc.confirmation_ids.filtered(lambda c: c.id == int(request_id or 0))
            if not request:
                raise rule_error(self.env, "not-found")
            if op == "remove":
                request.unlink()
            else:
                request.write(self._ea_exec_confirm_values(values))
        else:
            raise rule_error(self.env, "invalid-value")
        self._ea_exec_started(proc)
        return self.ea_procedure_paper(proc.id)

    def _ea_exec_confirm_values(self, values):
        if not isinstance(values, dict) or set(values) - {"party", "book", "sent", "status", "confirmed", "explanation"}:
            raise rule_error(self.env, "invalid-field")
        out = {}
        if "party" in values:
            party = str(values["party"] or "").strip()[:200]
            if not party:
                raise rule_error(self.env, "invalid-value")
            out["party"] = party
        for name, column in (("book", "book_amount"), ("confirmed", "confirmed_amount")):
            if name in values:
                clean = clean_explanation({"amount": values[name]})
                if clean is None:
                    raise rule_error(self.env, "invalid-value")
                out[column] = clean["amount"]
                if name == "confirmed":
                    out["has_reply_amount"] = values[name] not in (None, "", False)
        if "sent" in values:
            try:
                out["sent_on"] = fields.Date.to_date(values["sent"]) if values["sent"] else False
            except ValueError:
                raise rule_error(self.env, "invalid-value") from None
        if "status" in values:
            if values["status"] not in CONFIRMATION_STATUSES:
                raise rule_error(self.env, "invalid-value")
            out["status"] = values["status"]
        if "explanation" in values:
            out["explanation"] = str(values["explanation"] or "").strip()[:2000] or False
        return out

    def ea_proc_confirm_finding(self, proc_id, request_id):
        """One click: an unexplained difference on a reply becomes a misstatement finding."""
        proc = self._ea_exec_writable(proc_id)
        request = proc.confirmation_ids.filtered(lambda c: c.id == int(request_id or 0))
        if not request:
            raise rule_error(self.env, "not-found")
        confirmed = request.confirmed_amount if request.has_reply_amount else None
        difference = confirmation_difference(request.book_amount, confirmed, request.status)
        if confirmation_state(request.book_amount, confirmed, request.status, request.explanation) != "difference" or request.finding_id:
            raise rule_error(self.env, "invalid-value")
        lang = self._ea_exec_lang()
        text = self.env._("Confirmation from %(party)s: difference of %(amount)s not explained", party=request.party, amount=grouped(difference, lang))
        return self.ea_proc_finding(proc.id, text, amount=difference, finding_type="misstatement", trivial_confirmed=True, confirmation_id=request.id)
