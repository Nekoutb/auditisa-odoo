"""The journal-entry and sampling worksheets (owner's mock-ups of 2026-11-16, mock-ws-je and
mock-ws-sampling). Each page is one client action fed by one read (ea_je_page, ea_sampling_page);
every change goes through a guarded method and the page is read again. The selection, the sizes,
the draws and the projection are the existing ones: this file only lays them out, records what
the auditor concluded on each entry or item, and files the support."""
import base64

from odoo import api, fields, models

from ..rules import rule_error
from ..services.errors import ServiceError
from ..services.je_catalogue import JE_CRITERIA
from ..services.je_selection import SELECTION_CAP
from ..services.upload_safety import check_upload
from ..services.ws_pages import (
    card_state, clean_item_patch, exceeds_tolerable, group_entries, je_progress, sample_items, toc_steps, tod_result_steps,
    tod_steps,
)
from .tool_record import grouped, is_french

MAX_SUPPORT_BYTES = 25 * 1024 * 1024
REVIEW_SELECTION = [("to_clear", "To clear"), ("cleared", "Cleared"), ("problem", "Problem")]
# the records a support file may be filed on, and the paper a finding raised from them goes to
SUPPORT_MODELS = ("ea.audit.je.review", "ea.audit.automation.run", "ea.audit.scot.control")
FINDING_SOURCES = {"ea.audit.je.review": "E3.1", "ea.audit.automation.run": None, "ea.audit.scot.control": None}
_CRITERIA = [c for c in JE_CRITERIA if c["key"] != "user-defined"]


def _field_name(key):
    return "use_%s" % key.replace("-", "_")


class JeReview(models.Model):
    """What the auditor concluded on one selected journal entry: cleared with a note, or a
    problem, with the finding raised from it. One per entry of a ledger."""

    _name = "ea.audit.je.review"
    _inherit = ["ea.audit.tool.record"]
    _description = "Journal entry reviewed"
    _order = "id"
    _rec_name = "je_number"

    dataset_id = fields.Many2one("ea.audit.dataset", string="Ledger", ondelete="cascade", index=True)
    je_number = fields.Char(string="Entry", required=True)
    status = fields.Selection(REVIEW_SELECTION, default="to_clear", required=True)
    note = fields.Text()
    finding_id = fields.Many2one("ea.audit.finding", string="Finding", ondelete="set null")
    reviewed_by_id = fields.Many2one("res.users", string="Reviewed by", ondelete="restrict")
    reviewed_at = fields.Datetime(string="Reviewed on")

    _entry_uniq = models.Constraint("UNIQUE(engagement_id, dataset_id, je_number)", "This entry is already reviewed.")


class AutomationRunSample(models.Model):
    _inherit = "ea.audit.automation.run"

    # Next phase: a test-of-details sample is tied to the substantive procedure it serves.
    purpose = fields.Char(string="Procedure or purpose", help="The substantive procedure this sample serves, in a few words.")
    item_results = fields.Json(string="Items tested")

    def _ea_own(self):
        """This run, as superuser, after the write guard of its file; a sampling run only."""
        self.ensure_one()
        as_root = self.sudo()
        if not as_root.exists() or as_root.engine != "sampling":
            raise rule_error(self.env, "not-found")
        self._ea_guard()
        return as_root

    def ea_sampling_item(self, row_no, patch):
        """One tested item: the audited value, how it was tested, a note. Refused once concluded."""
        as_root = self._ea_own()
        if as_root.method == "tod-mus" or (as_root.summary or {}).get("projected") is not None:
            raise rule_error(self.env, "sample-concluded")
        drawn = {str(row[0]) for row in as_root.sheet_rows or [] if row}
        if str(row_no) not in drawn:
            raise rule_error(self.env, "not-found")
        clean = clean_item_patch(patch)
        if clean is None:
            raise rule_error(self.env, "invalid-value")
        results = dict(as_root.item_results or {})
        results[str(row_no)] = dict(results.get(str(row_no)) or {}, **clean)
        as_root.write({"item_results": results})
        return as_root.engagement_id.with_env(self.env).ea_sampling_page()

    def ea_sampling_purpose(self, text):
        as_root = self._ea_own()
        as_root.write({"purpose": (text or "").strip()[:200] or False})
        return as_root.engagement_id.with_env(self.env).ea_sampling_page()

    def ea_sampling_conclude(self):
        """The errors found in the items, projected by the existing evaluation (ISA 530 ¶14)."""
        as_root = self._ea_own()
        if as_root.method == "tod-mus" or (as_root.summary or {}).get("projected") is not None:
            raise rule_error(self.env, "sample-concluded")
        engagement = as_root.engagement_id.with_env(self.env)
        rows, totals = sample_items(*engagement._ea_sample_items(as_root))
        if not rows or totals["tested"] < len(rows):
            raise rule_error(self.env, "sample-not-tested")
        self.evaluate(totals["difference"])
        engagement._ea_log("sample_concluded", "Sample %s concluded: errors %s" % (as_root.id, totals["difference"]))
        return engagement.ea_sampling_page()


class FindingFromSource(models.Model):
    _inherit = "ea.audit.finding"

    @api.model
    def ea_create_from_source(self, source_model, source_id, description, amount=None, finding_type="b4", mtype="factual", severity=None, trivial_confirmed=False):
        """A finding raised in place from a worksheet line (a journal entry, a sample, a control).
        It goes through routeFinding, so the register, the SAD and their rules are the usual ones.
        Returns {id, reference, destination}."""
        if source_model not in FINDING_SOURCES:
            raise rule_error(self.env, "forbidden")
        source = self.env[source_model].sudo().browse(int(source_id or 0)).exists()
        if not source:
            raise rule_error(self.env, "not-found")
        engagement = source.engagement_id.with_env(self.env)
        code = FINDING_SOURCES[source_model]
        file_item = source.file_item_id if source_model == "ea.audit.automation.run" else False
        if code:
            file_item = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", engagement.id), ("code", "=", code)], limit=1)
        if finding_type not in ("b4", "c1", "b5"):
            raise rule_error(self.env, "invalid-value")
        description = (description or "").strip()
        result = engagement.route_finding(
            finding_type, description[:200], detail=description if len(description) > 200 else None,
            severity=severity or ("deficiency" if finding_type == "c1" else None), file_item=file_item or None,
            amount=amount if finding_type == "b5" else None, mtype=mtype or "factual", trivial_confirmed=bool(trivial_confirmed),
        )
        finding = result["finding"].sudo()
        return {"id": finding.id, "reference": finding.reference, "destination": result["destination"]}


class EngagementWorksheets(models.Model):
    _inherit = "ea.audit.engagement"

    # ------------------------------------------------------------------
    # Support files, on an entry, a sample or a control
    # ------------------------------------------------------------------

    def _ea_ws_record(self, model, res_id):
        self.ensure_one()
        if model not in SUPPORT_MODELS:
            raise rule_error(self.env, "forbidden")
        record = self.env[model].sudo().browse(int(res_id or 0)).exists()
        if not record or record.engagement_id != self.sudo():
            raise rule_error(self.env, "not-found")
        return record

    def ea_ws_attach(self, model, res_id, filename, content_b64):
        """Support filed on a worksheet line. The bytes are checked as every upload is."""
        self.ensure_one()
        self._ea_tool_guard()
        record = self._ea_ws_record(model, res_id)
        content = base64.b64decode(content_b64 or b"")
        if len(content) > MAX_SUPPORT_BYTES:
            raise rule_error(self.env, "file-too-large")
        try:
            name, mime = check_upload(filename, content)
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error
        attachment = self.env["ir.attachment"].sudo().create({
            "name": name, "res_model": model, "res_id": record.id, "datas": base64.b64encode(content), "mimetype": mime,
        })
        self._ea_log("worksheet_support", "Support %s filed on %s %s" % (name, model, record.id))
        return attachment.id

    def _ea_ws_files(self, model, ids):
        """{res_id: [{id, name}]} for the page."""
        out = {}
        if not ids:
            return out
        for attachment in self.env["ir.attachment"].sudo().search([("res_model", "=", model), ("res_id", "in", list(ids))], order="id"):
            out.setdefault(attachment.res_id, []).append({"id": attachment.id, "name": attachment.name})
        return out

    def _ea_ws_readonly(self):
        """None when the user may work on the page; otherwise "archived" or "role"."""
        return self._ea_cra_read_only()

    # ------------------------------------------------------------------
    # Journal entries
    # ------------------------------------------------------------------

    def _ea_je_studio(self, studio_id):
        """The studio that holds the criteria of the page: the one given, else a fresh one on the
        file's ledger (a studio is a transient record and can be gone after a while)."""
        self.ensure_one()
        studio = self.env["ea.audit.je.studio"].browse(int(studio_id or 0)).exists()
        if studio and studio.engagement_id == self:
            return studio
        dataset = self._ea_current_dataset("journal_entries")
        return self.env["ea.audit.je.studio"].create({"engagement_id": self.id, "dataset_id": dataset.id or False})

    def _ea_je_reviews(self, dataset):
        reviews = self.env["ea.audit.je.review"].sudo().search([("engagement_id", "=", self.id), ("dataset_id", "=", dataset.id)])
        files = self._ea_ws_files("ea.audit.je.review", reviews.ids)
        return {
            review.je_number: {
                "id": review.id, "status": review.status, "note": review.note or "",
                "finding": review.finding_id.reference if review.finding_id else False,
                "files": len(files.get(review.id, [])), "fileList": files.get(review.id, []),
            }
            for review in reviews
        }

    def ea_je_page(self, studio_id=None):
        """What the journal-entry page shows: the ledger and its checks, the criteria with the
        entries each one catches, the selected entries with their reasons and what was concluded
        on each, and the conclusion."""
        self.ensure_one()
        self._ea_require_access()
        root = self.sudo()
        fr = is_french(self.env)
        studio = self._ea_je_studio(studio_id)
        reason = self._ea_ws_readonly()
        datasets = self.env["ea.audit.dataset"].sudo().search([
            ("engagement_id", "=", self.id), ("kind", "=", "journal_entries"), ("superseded_at", "=", False),
        ])
        dataset = studio.dataset_id
        request = studio._ea_request()
        on = set(request["criteria"])
        payload = {
            "engagement": root.display_name, "studioId": studio.id,
            "readonly": bool(reason), "archived": reason == "archived",
            "datasets": [{"id": d.id, "name": d.source_filename or d.display_name, "lines": d.gl_line_count} for d in datasets],
            "datasetId": dataset.id or False,
            "prerequisites": [{"label": item["label"], "ok": item["ok"]} for item in self._ea_tool_prerequisites()],
            "criteria": [{
                "key": c["key"], "name": c["nameFr"] if fr else c["nameEn"], "on": c["key"] in on, "entries": None,
            } for c in _CRITERIA],
            "rules": len(request["userRules"]), "ownRules": [],
            "population": {"lines": 0, "entries": 0}, "checks": [], "checksOk": None,
            "selectedEntries": 0, "selectedLines": 0, "truncated": False, "notes": [], "entries": [],
            "progress": je_progress([], 0),
            "designs": self.env["ea.audit.je.design"].sudo().search_count([("engagement_id", "=", self.id)]),
            "missing": False,
        }
        if not dataset:
            payload["missing"] = "ledger"
            return payload
        if not dataset.gl_line_count:
            payload["missing"] = "lines"
            return payload
        checks = self.gl_validate_population(dataset.id)["checks"]
        payload["checks"] = [{
            "label": c["labelFr"] if fr else c["labelEn"], "status": c["status"], "detail": c["detailFr"] if fr else c["detailEn"],
        } for c in checks]
        payload["checksOk"] = not any(c["status"] == "failed" for c in checks)
        if not request["criteria"] and not request["userRules"]:
            self.env.cr.execute(
                "SELECT count(*), count(DISTINCT je_number) FROM ea_audit_gl_line WHERE dataset_id = %s AND engagement_id = %s",
                [dataset.id, self.id],
            )
            lines, entries = self.env.cr.fetchone()
            payload["population"] = {"lines": lines, "entries": entries}
            return payload
        result = self.je_run_selection(dataset.id, dict(request, limit=SELECTION_CAP, offset=0))
        caught = {row["key"]: row["matchedEntries"] for row in result["criteria"]}
        for row in payload["criteria"]:
            row["entries"] = caught.get(row["key"]) if row["on"] else None
        payload["ownRules"] = [
            {"name": row["name"], "entries": row["matchedEntries"]}
            for row in result["criteria"] if row["key"] not in {c["key"] for c in _CRITERIA}
        ]
        reviews = self._ea_je_reviews(dataset)
        entries = group_entries(result["lines"], reviews)
        for entry in entries:
            entry["fileList"] = (reviews.get(entry["je"]) or {}).get("fileList", [])
        payload.update({
            "population": {"lines": result["population"]["lines"], "entries": result["population"]["entries"]},
            "selectedEntries": result["selectedEntries"], "selectedLines": result["selectedLines"],
            "truncated": result["truncated"], "notes": result["notes"], "entries": entries,
            "progress": je_progress(entries, result["selectedEntries"]),
        })
        return payload

    def ea_je_toggle(self, studio_id, key):
        """One criterion on or off. The studio is the person's own working copy."""
        self.ensure_one()
        self._ea_require_access()
        studio = self._ea_je_studio(studio_id)
        if key not in {c["key"] for c in _CRITERIA}:
            raise rule_error(self.env, "invalid-value")
        name = _field_name(key)
        studio.write({name: not studio[name]})
        return self.ea_je_page(studio.id)

    def ea_je_dataset(self, studio_id, dataset_id):
        self.ensure_one()
        self._ea_require_access()
        studio = self._ea_je_studio(studio_id)
        dataset = self._ea_gl_dataset(dataset_id)
        studio.write({"dataset_id": dataset.id})
        return self.ea_je_page(studio.id)

    def _ea_je_review(self, studio, je_number):
        """The review of one selected entry of the studio's ledger, created when first touched."""
        dataset = studio._ea_require_dataset()
        number = (je_number or "").strip()
        self.env.cr.execute(
            "SELECT 1 FROM ea_audit_gl_line WHERE dataset_id = %s AND engagement_id = %s AND je_number = %s LIMIT 1",
            [dataset.id, self.id, number],
        )
        if not number or not self.env.cr.fetchone():
            raise rule_error(self.env, "not-found")
        Review = self.env["ea.audit.je.review"].sudo()
        review = Review.search([("engagement_id", "=", self.id), ("dataset_id", "=", dataset.id), ("je_number", "=", number)], limit=1)
        return review or Review.create({"engagement_id": self.id, "dataset_id": dataset.id, "je_number": number})

    def ea_je_review(self, studio_id, je_number, status, note=None):
        """Mark one entry cleared or a problem, with the note that says why; or back to clear."""
        self.ensure_one()
        self._ea_tool_guard()
        if status not in dict(REVIEW_SELECTION):
            raise rule_error(self.env, "invalid-value")
        studio = self._ea_je_studio(studio_id)
        review = self._ea_je_review(studio, je_number)
        text = (note if note is not None else review.note or "").strip()
        if status != "to_clear" and not text:
            raise rule_error(self.env, "je-note-required")
        review.write({"status": status, "note": text or False, "reviewed_by_id": self.env.user.id, "reviewed_at": fields.Datetime.now()})
        self._ea_log("je_entry_reviewed", "Journal entry %s: %s" % (review.je_number, status))
        return self.ea_je_page(studio.id)

    def ea_je_note(self, studio_id, je_number, note):
        """The note alone, saved as it is typed."""
        self.ensure_one()
        self._ea_tool_guard()
        studio = self._ea_je_studio(studio_id)
        review = self._ea_je_review(studio, je_number)
        text = (note or "").strip()
        if not text and review.status != "to_clear":
            raise rule_error(self.env, "je-note-required")
        review.write({"note": text or False})
        return True

    def ea_je_attach(self, studio_id, je_number, filename, content_b64):
        self.ensure_one()
        self._ea_tool_guard()
        studio = self._ea_je_studio(studio_id)
        review = self._ea_je_review(studio, je_number)
        self.ea_ws_attach("ea.audit.je.review", review.id, filename, content_b64)
        return self.ea_je_page(studio.id)

    def ea_je_finding(self, studio_id, je_number, description, finding_type="b5", amount=None, trivial_confirmed=False):
        """Raise a finding in place from one entry; the entry becomes a problem carrying it."""
        self.ensure_one()
        self._ea_tool_guard()
        studio = self._ea_je_studio(studio_id)
        review = self._ea_je_review(studio, je_number)
        text = (description or "").strip()
        if not text:
            raise rule_error(self.env, "title-required")
        created = self.env["ea.audit.finding"].ea_create_from_source(
            "ea.audit.je.review", review.id, text, amount=amount, finding_type=finding_type, mtype="factual",
            trivial_confirmed=trivial_confirmed,
        )
        review.write({
            "finding_id": created["id"], "status": "problem", "note": review.note or text,
            "reviewed_by_id": self.env.user.id, "reviewed_at": fields.Datetime.now(),
        })
        return self.ea_je_page(studio.id)

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    def _ea_sample_items(self, run):
        """(picks, book values, results) of a run drawn from a dataset, for sample_items."""
        picks = []
        for row in run.sheet_rows or []:
            if not row:
                continue
            values = [str(value).strip() for value in row[2:] if str(value or "").strip()]
            picks.append((row[0], row[1] if len(row) > 1 else "", " · ".join(values[:3])[:90]))
        book = {}
        if run.dataset_id and picks:
            self.env.cr.execute(
                "SELECT row_no, amount FROM ea_audit_dataset_row WHERE dataset_id = %s AND row_no = ANY(%s)",
                [run.dataset_id.id, [int(p[0]) for p in picks]],
            )
            book = {row_no: float(amount) for row_no, amount in self.env.cr.fetchall() if amount is not None}
        return picks, book, run.item_results or {}

    def _ea_toc_card(self, control, fr, evaluations, operating, files):
        grid = control.toc_grid or {}
        attributes = [a for a in grid.get("attributes") or [] if isinstance(a, str)]
        rows = []
        for position, row in enumerate(grid.get("rows") or [], start=1):
            results = row.get("results") or {}
            values = [results.get(a) or "" for a in attributes]
            if "fail" in values:
                outcome = "error"
            elif values and all(v not in ("", None) for v in values):
                outcome = "agreed"
            else:
                outcome = "to_test"
            rows.append({
                "position": position, "ref": row.get("ref") or "", "date": row.get("date") or "", "desc": row.get("desc") or "",
                "results": values, "result": outcome,
            })
        steps = toc_steps(control.toc_population, control.sample_size, control.toc_sample_drawn_at, control.rows_tested, control.toc_evaluation, control.operating_eval)
        frequency = control.frequency or ""
        return {
            "kind": "toc", "id": control.id, "title": control.name,
            "sub": " · ".join(x for x in (control.scot_id.name, frequency, control.suggested_rule or "") if x),
            "steps": steps, "state": card_state(steps),
            "stats": {"items": control.sample_size or None, "errors": control.deviations if control.rows_tested else None,
                      "result": evaluations.get(control.toc_evaluation) or None},
            "population": control.toc_population or 0, "drawnOn": bool(control.toc_sample_drawn_at),
            "itemsLabel": control.items_label or "", "attributes": attributes, "rows": rows,
            "tested": control.rows_tested, "evaluation": control.toc_evaluation or False,
            "evaluationLabel": evaluations.get(control.toc_evaluation) or False,
            "operating": operating.get(control.operating_eval) or False, "operatingBad": control.operating_eval == "not_effective",
            "files": files.get(control.id, []),
        }

    def _ea_tod_card(self, run, fr, tolerable, lang, methods, files):
        summary = run.summary or {}
        method = run.method or ""
        if method == "tod-mus":
            total = run.total_likely
            exceeds = exceeds_tolerable(total, tolerable)
            steps = tod_result_steps(bool(exceeds))
            rows = [{"measure": row[0], "amount": row[1]} for row in run.sheet_rows or [] if len(row) > 1]
            return {
                "kind": "tod-result", "id": run.id, "title": run.title,
                "sub": " · ".join(x for x in (run.index_code or "", self.env._("Tolerable %s", grouped(tolerable, lang)) if tolerable else "") if x),
                "purpose": run.purpose or "", "steps": steps, "state": card_state(steps),
                "stats": {"items": None, "errors": run.sample_misstatement, "projected": run.projected},
                "measures": rows, "projected": run.projected, "key": run.key_misstatement, "total": total,
                "population": run.remaining_value, "sampleValue": run.sample_value,
                "tolerable": tolerable, "exceeds": exceeds, "raised": run.raised_to_b5, "concluded": True,
                "files": files.get(run.id, []),
            }
        picks, book, results = self._ea_sample_items(run)
        rows, totals = sample_items(picks, book, results)
        projected = summary.get("projected")
        exceeds = exceeds_tolerable(projected, tolerable)
        steps = tod_steps(summary.get("populationRows"), summary.get("sampleSize"), bool(picks), totals["tested"], len(picks), projected, bool(exceeds))
        return {
            "kind": "tod", "id": run.id, "title": run.purpose or run.dataset_id.source_filename or run.title,
            "sub": " · ".join(x for x in (
                run.dataset_id.source_filename or "", methods.get(method, method),
                self.env._("Tolerable %s", grouped(tolerable, lang)) if tolerable else "",
            ) if x),
            "purpose": run.purpose or "", "steps": steps, "state": card_state(steps),
            "stats": {"items": len(picks), "errors": totals["errors"] if totals["tested"] else None, "projected": projected},
            "rows": rows, "totals": totals, "population": summary.get("populationTotal"), "populationRows": summary.get("populationRows"),
            "sampleValue": summary.get("sampledValue"), "seed": (run.params or {}).get("seed") or "",
            "projected": projected, "tolerable": tolerable, "exceeds": exceeds, "raised": run.raised_to_b5,
            "concluded": projected is not None, "allTested": bool(rows) and totals["tested"] >= len(rows),
            "files": files.get(run.id, []),
        }

    def ea_sampling_page(self):
        """What the sampling page shows: one card per sample, tests of controls and tests of
        details, each with its five steps; the items tested and the result beside them."""
        self.ensure_one()
        self._ea_require_access()
        root = self.sudo()
        fr = is_french(self.env)
        lang = "fr_FR" if fr else "en_US"
        reason = self._ea_ws_readonly()
        approved = root._ea_approved_materiality()
        tolerable = approved.performance if approved else None
        Control = self.env["ea.audit.scot.control"].sudo().with_context(lang=lang)
        controls = Control.search([("engagement_id", "=", self.id), ("selected_for_testing", "=", True)])
        evaluations = dict(Control._fields["toc_evaluation"]._description_selection(Control.env))
        operating = dict(Control._fields["operating_eval"]._description_selection(Control.env))
        control_files = self._ea_ws_files("ea.audit.scot.control", controls.ids)
        toc = [self._ea_toc_card(control, fr, evaluations, operating, control_files) for control in controls]
        Run = self.env["ea.audit.automation.run"].sudo().with_context(lang=lang)
        runs = Run.search([("engagement_id", "=", self.id), ("engine", "=", "sampling")], order="id")
        Wizard = self.env["ea.audit.sampling.wizard"].with_context(lang=lang)
        methods = dict(Wizard._fields["method"]._description_selection(Wizard.env))
        run_files = self._ea_ws_files("ea.audit.automation.run", runs.ids)
        tod = [self._ea_tod_card(run, fr, tolerable, lang, methods, run_files) for run in runs]
        cards = toc + tod
        evaluated = len([c for c in cards if c["steps"][-1]["state"] in ("done", "bad")])
        above = len([c for c in tod if c.get("exceeds")])
        return {
            "engagement": root.display_name, "readonly": bool(reason), "archived": reason == "archived",
            "tolerable": tolerable, "prerequisites": [{"label": item["label"], "ok": item["ok"]} for item in self._ea_tool_prerequisites()],
            "progress": {"evaluated": evaluated, "total": len(cards), "above": above},
            "toc": toc, "tod": tod,
        }
