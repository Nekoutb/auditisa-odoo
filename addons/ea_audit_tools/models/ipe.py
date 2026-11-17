"""Data quality (IPE): information produced by the entity, ISA 500 paragraph 9 (owner-approved
mock-up of 2026-11-17). It replaces the substantive analytics tool.

Every file in use (a dataset of a kind and timing, a trial balance of a timing) has one record:
where the data comes from, the automatic checks run on upload (services/ipe_checks.py) with
the lines of the file behind each exception, an explanation per check with exceptions, the
conclusion and two signatures, preparer then reviewer. A new upload of the same kind and timing
runs the checks again and voids those signatures.

Working papers that rely on a file show it in their right rail; a reviewer signing a paper whose
file is "Not reliable" is warned first, is not stopped, and the warning goes on the trail.
"""
import logging

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.signoff_rules import can_review

from ..rules import rule_error
from ..services import ipe_checks as ipe
from ..services.dataset_mapping import je_key_columns
from .dataset import DATASET_TIMING_SELECTION, KIND_SELECTION
from .tool_record import is_french, upload_stamp

_logger = logging.getLogger(__name__)

IPE_KIND_SELECTION = [("trial_balance", "Trial balance")] + KIND_SELECTION
OBTAINED_SELECTION = [
    ("observed", "Extraction observed by the team"),
    ("received", "Received from the client"),
    ("downloaded", "Downloaded by the team"),
]
CONCLUSION_SELECTION = [
    ("reliable", "Reliable for our purpose"),
    ("limitations", "Reliable with limitations"),
    ("not_reliable", "Not reliable: ask the client for a new extraction"),
]
STATUS_SELECTION = [("passed", "Passed"), ("exceptions", "Exceptions"), ("na", "Not applicable"), ("info", "Information")]
SOURCE_FIELDS = ("system_name", "report_name", "extracted_by", "extraction_date", "parameters", "obtained", "purpose")
#: Lines of one check sent to the page; the Excel download has every stored line.
SHOWN_LINES = 200
FETCH_BATCH = 20000


class Ipe(models.Model):
    _name = "ea.audit.ipe"
    _inherit = ["ea.audit.tool.record"]
    _description = "Data quality record (IPE)"
    _order = "engagement_id, id"
    _rec_name = "reference"

    kind = fields.Selection(IPE_KIND_SELECTION, required=True)
    timing = fields.Selection(DATASET_TIMING_SELECTION, required=True)
    reference = fields.Char(compute="_compute_reference", store=True)
    dataset_id = fields.Many2one("ea.audit.dataset", string="Uploaded file", ondelete="set null", index=True)
    tb_version_id = fields.Many2one("ea.audit.tb.version", string="Trial balance version", ondelete="set null", index=True)
    source_filename = fields.Char(string="File")
    file_uploaded_at = fields.Datetime(string="Uploaded on")
    file_uploaded_by_id = fields.Many2one("res.users", string="Uploaded by")
    line_count = fields.Integer(string="Lines")
    entry_count = fields.Integer(string="Entries")
    checked_at = fields.Datetime(string="Checked on")
    system_name = fields.Char(string="Accounting system")
    report_name = fields.Char(string="Report or query")
    extracted_by = fields.Char(string="Extracted by")
    extraction_date = fields.Date(string="Extraction date")
    parameters = fields.Text(string="Parameters used")
    obtained = fields.Selection(OBTAINED_SELECTION, string="How obtained")
    purpose = fields.Text(string="Purpose in the audit")
    conclusion = fields.Selection(CONCLUSION_SELECTION)
    preparer_id = fields.Many2one("res.users", string="Preparer")
    prepared_at = fields.Datetime(string="Prepared on")
    reviewer_id = fields.Many2one("res.users", string="Reviewer")
    reviewed_at = fields.Datetime(string="Reviewed on")
    check_ids = fields.One2many("ea.audit.ipe.check", "ipe_id", string="Checks")

    _ipe_uniq = models.Constraint("UNIQUE(engagement_id, kind, timing)", "One data quality record per kind of file and timing.")

    @api.depends("kind", "timing")
    def _compute_reference(self):
        for record in self:
            record.reference = ipe.reference(record.kind, record.timing) if record.kind and record.timing else False

    def _ea_file(self):
        self.ensure_one()
        return self.tb_version_id if self.kind == "trial_balance" else self.dataset_id

    def _ea_explained(self):
        return {check.code for check in self.check_ids if check.status == "exceptions" and (check.explanation or "").strip()}

    def _ea_results(self):
        return [{"code": check.code, "status": check.status} for check in self.check_ids]

    def _ea_chip(self):
        self.ensure_one()
        return ipe.chip(self._ea_results(), self.conclusion, bool(self._ea_file()) and bool(self.checked_at), self._ea_explained())


class IpeCheck(models.Model):
    _name = "ea.audit.ipe.check"
    _inherit = ["ea.audit.tool.record"]
    _description = "Data quality check"
    _order = "ipe_id, sequence, id"
    _rec_name = "code"

    ipe_id = fields.Many2one("ea.audit.ipe", string="Data quality record", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer()
    code = fields.Char(required=True)
    status = fields.Selection(STATUS_SELECTION, required=True)
    exception_count = fields.Integer(string="Exceptions")
    note_en = fields.Char(string="Note (English)")
    note_fr = fields.Char(string="Note (French)")
    explanation = fields.Text()
    line_ids = fields.One2many("ea.audit.ipe.line", "check_id", string="Lines")


class IpeLine(models.Model):
    _name = "ea.audit.ipe.line"
    _inherit = ["ea.audit.tool.record"]
    _description = "Data quality exception line"
    _order = "check_id, sequence, id"

    check_id = fields.Many2one("ea.audit.ipe.check", string="Check", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer()
    file_row = fields.Integer(string="File line")
    ref = fields.Char(string="Reference")
    column_name = fields.Char(string="Column")
    value = fields.Char()
    amount = fields.Float(digits=(18, 2))
    expected = fields.Float(digits=(18, 2))
    has_amount = fields.Boolean(string="Has an amount")
    has_expected = fields.Boolean(string="Has an expected figure")
    text_en = fields.Char(string="Text (English)")
    text_fr = fields.Char(string="Text (French)")


class EngagementIpe(models.Model):
    _inherit = "ea.audit.engagement"

    # ------------------------------------------------------------------
    # The uploads: every new file of a kind and timing is checked
    # ------------------------------------------------------------------

    def create_dataset(self, kind, filename, content, *args, **kwargs):
        result = super().create_dataset(kind, filename, content, *args, **kwargs)
        dataset = self.env["ea.audit.dataset"].sudo().browse(result["datasetId"])
        self._ea_ipe_run(dataset.kind, dataset.timing)
        return result

    def import_trial_balance(self, filename, content, *args, **kwargs):
        result = super().import_trial_balance(filename, content, *args, **kwargs)
        version = self.env["ea.audit.tb.version"].sudo().browse(result["versionId"])
        self._ea_ipe_run("trial_balance", version.timing)
        return result

    def delete_dataset(self, dataset_id):
        dataset = self.env["ea.audit.dataset"].sudo().browse(int(dataset_id or 0)).exists()
        facts = (dataset.kind, dataset.timing) if dataset and dataset.engagement_id == self.sudo() else None
        result = super().delete_dataset(dataset_id)
        if facts:
            self._ea_ipe_run(*facts)
        return result

    def delete_tb_version(self, version_id):
        version = self.env["ea.audit.tb.version"].sudo().browse(int(version_id or 0)).exists()
        timing = version.timing if version and version.engagement_id == self.sudo() else None
        result = super().delete_tb_version(version_id)
        if timing:
            self._ea_ipe_run("trial_balance", timing)
        return result

    # ------------------------------------------------------------------
    # Running the checks
    # ------------------------------------------------------------------

    def _ea_ipe_kinds(self):
        return [kind for kind, _label in IPE_KIND_SELECTION if kind in ipe.KINDS]

    def _ea_ipe_timings(self):
        offered = dict(DATASET_TIMING_SELECTION)
        return [timing for timing in ipe.TIMINGS if timing in offered] + [t for t in offered if t not in ipe.TIMINGS]

    def _ea_ipe_current_file(self, kind, timing):
        """The upload in use of a kind and timing: a dataset, or a valid trial balance version."""
        self.ensure_one()
        if kind == "trial_balance":
            tb = self._ea_tb()
            Version = self.env["ea.audit.tb.version"].sudo()
            if not tb:
                return Version
            return Version.search([
                ("tb_id", "=", tb.id), ("timing", "=", timing), ("superseded_at", "=", False), ("validation_status", "=", "valid"),
            ], order="version_no desc", limit=1)
        return self.env["ea.audit.dataset"].sudo().search([
            ("engagement_id", "=", self.id), ("kind", "=", kind), ("timing", "=", timing), ("superseded_at", "=", False),
        ], limit=1)

    def _ea_ipe_record(self, kind, timing, create=False):
        Ipe = self.env["ea.audit.ipe"].sudo()
        record = Ipe.search([("engagement_id", "=", self.id), ("kind", "=", kind), ("timing", "=", timing)], limit=1)
        if not record and create:
            record = Ipe.create({"engagement_id": self.id, "kind": kind, "timing": timing})
        return record

    def _ea_ipe_void(self, record, why):
        """The signatures go: what they attested to has changed."""
        if record.preparer_id or record.reviewer_id:
            record.write({"preparer_id": False, "prepared_at": False, "reviewer_id": False, "reviewed_at": False})
            if why == "upload":
                self._ea_log("ipe_voided", "%s signatures voided: a new file was uploaded" % record.reference)
            else:
                self._ea_log("ipe_voided", "%s signatures voided after a change" % record.reference)

    def _ea_ipe_run(self, kind, timing):
        """Check the file in use of a kind and timing, and keep what was found. The same file
        checked again keeps its explanations; a new file starts afresh and voids the signatures.
        A failure of the checks never takes the upload down with it."""
        self.ensure_one()
        if kind not in ipe.KINDS:
            return self.env["ea.audit.ipe"]  # bank and supplier statements: no checks any more
        root = self.sudo()
        record = root._ea_ipe_record(kind, timing, create=True)
        current = root._ea_ipe_current_file(kind, timing)
        same = bool(current) and record._ea_file() == current
        explanations = {check.code: check.explanation for check in record.check_ids if check.explanation} if same else {}
        if not same:
            self._ea_ipe_void(record, "upload")
            record.write({"conclusion": False})
        record.check_ids.unlink()
        link = {"tb_version_id": current.id or False} if kind == "trial_balance" else {"dataset_id": current.id or False}
        if not current:
            record.write(dict(link, source_filename=False, file_uploaded_at=False, file_uploaded_by_id=False,
                              line_count=0, entry_count=0, checked_at=False))
            return record
        record.write(dict(
            link, source_filename=current.source_filename, file_uploaded_at=current.create_date,
            file_uploaded_by_id=current.create_uid.id, line_count=current.row_count, checked_at=False,
        ))
        try:
            with self.env.cr.savepoint():
                results, entries = root._ea_ipe_results(record, current)
                root._ea_ipe_store(record, results, explanations)
                record.write({"checked_at": fields.Datetime.now(), "entry_count": entries})
        except Exception:
            _logger.exception("Data quality checks failed on %s", record.reference)
        return record

    def _ea_ipe_period_end(self):
        end = self.sudo().period_end
        return end.isoformat() if end else None

    def _ea_ipe_results(self, record, current):
        """(results, entries) of the checks on one file."""
        period = ipe.period_of(record.timing, self._ea_ipe_period_end())
        context = {
            "period": period, "timing": record.timing,
            "extraction_date": record.extraction_date.isoformat() if record.extraction_date else None,
            "aged_before": ipe.shift_years(period[1], -1) if period[1] else None,
        }
        if record.kind == "trial_balance":
            data, extra = self._ea_ipe_tb_data(current)
        else:
            data, extra = self._ea_ipe_dataset_data(current)
        context.update(extra)
        results = ipe.run(record.kind, data, context)
        entries = 0
        if record.kind == "journal_entries":
            entries = len({value for value in ipe._entry_ids(data) if value})
        return results, entries

    def _ea_ipe_dataset_data(self, dataset):
        """The stored rows of an upload as columns: only the file columns the mapping reads, in
        batches, by SQL (a ledger of 100 000 lines is read this way in a few seconds)."""
        cr = self.env.cr
        mapping = dict(dataset.mapping or {})
        headers = [header for key, header in mapping.items() if key != "jeKey" and isinstance(header, str) and header.strip()]
        if mapping.get("jeKey"):
            headers += je_key_columns(mapping)
        extra = {"rows_read": dataset.row_count}
        headers = list(dict.fromkeys(headers))
        columns = {header: [] for header in headers}
        rows = []
        cells = ", ".join(["data -> (%s::text)"] * len(headers))
        query = (
            "SELECT row_no, file_row, jsonb_build_array(%s) FROM ea_audit_dataset_row "
            "WHERE dataset_id = %%s AND row_no > %%s ORDER BY row_no LIMIT %%s" % cells
        )
        after = 0
        while True:
            cr.execute(query, headers + [dataset.id, after, FETCH_BATCH])
            batch = cr.fetchall()
            for row_no, file_row, values in batch:
                rows.append(file_row or row_no + 1)
                for header, value in zip(headers, values or []):
                    columns[header].append(value)
            if len(batch) < FETCH_BATCH:
                break
            after = batch[-1][0]
        return ipe.Data(columns, rows, mapping), extra

    def _ea_ipe_tb_data(self, version):
        summary = version.validation_summary or {}
        mapping = dict(summary.get("mapping") or {})
        lines = version.line_ids.sorted("row_no")
        columns = {
            "account": [line.account_code or "" for line in lines],
            "label": [line.account_name or "" for line in lines],
            "_od": [line.opening_debit for line in lines], "_oc": [line.opening_credit for line in lines],
            "_d": [line.debit for line in lines], "_c": [line.credit for line in lines],
        }
        for header in {header for header in mapping.values() if isinstance(header, str) and header.strip()}:
            columns.setdefault(header, [(line.raw_data or {}).get(header) for line in lines])
        rows = [line.file_row or line.row_no for line in lines]
        facts = version.file_facts or {}
        read = facts.get("fileRows") or (summary.get("readability") or {}).get("rows")
        extra = {
            "rows_read": read if facts else None,
            "left_out": facts.get("leftOut") or [],
            "prior_closings": self._ea_ipe_prior_closings(version.timing),
        }
        return ipe.Data(columns, rows, mapping), extra

    def _ea_ipe_prior_closings(self, timing):
        """The closings the opening balances must equal: the prior-year trial balance uploaded on
        this file, else last year's file; for the year after, this year's. None when there is none."""
        if timing == "prior_year":
            return None
        wanted = ["post_audit", "final", "pre_audit"] if timing == "subsequent" else ["prior_year"]
        for source in wanted:
            version = self._ea_ipe_current_file("trial_balance", source)
            if version:
                out = {}
                for line in version.line_ids:
                    out[line.account_code] = out.get(line.account_code, 0) + line.closing
                return out
        return None if timing == "subsequent" else self._ea_prior_closings_map()

    def _ea_ipe_store(self, record, results, explanations):
        Check = self.env["ea.audit.ipe.check"].sudo()
        cr = self.env.cr
        for sequence, result in enumerate(results, start=1):
            note = result.get("note") or {}
            check = Check.create({
                "engagement_id": self.id, "ipe_id": record.id, "sequence": sequence, "code": result["code"],
                "status": result["status"], "exception_count": result["count"],
                "note_en": note.get("en") or False, "note_fr": note.get("fr") or False,
                "explanation": explanations.get(result["code"]) if result["status"] == ipe.EXCEPTIONS else False,
            })
            lines = result["lines"]
            if not lines:
                continue
            cr.execute(
                """INSERT INTO ea_audit_ipe_line (engagement_id, check_id, sequence, file_row, ref, column_name, value, amount, expected,
                                                  has_amount, has_expected, text_en, text_fr, create_uid, write_uid, create_date, write_date)
                   SELECT %s, %s, s, r, f, c, v, a, e, ha, he, te, tf, %s, %s, now() at time zone 'UTC', now() at time zone 'UTC'
                     FROM unnest(%s::int[], %s::int[], %s::text[], %s::text[], %s::text[], %s::numeric[], %s::numeric[],
                                 %s::bool[], %s::bool[], %s::text[], %s::text[]) AS t(s, r, f, c, v, a, e, ha, he, te, tf)""",
                [self.id, check.id, self.env.uid, self.env.uid,
                 list(range(1, len(lines) + 1)), [line["row"] for line in lines],
                 [(line["ref"] or "")[:200] for line in lines], [(line["column"] or "")[:200] for line in lines],
                 [(line["value"] or "")[:200] for line in lines],
                 [line["amount"] or 0 for line in lines], [line["expected"] or 0 for line in lines],
                 [line["amount"] is not None for line in lines], [line["expected"] is not None for line in lines],
                 [line["en"] or "" for line in lines], [line["fr"] or "" for line in lines]],
            )
        self.env["ea.audit.ipe.line"].invalidate_model()

    # ------------------------------------------------------------------
    # The page
    # ------------------------------------------------------------------

    def action_tool_ipe(self):
        """Data quality (IPE) (owner-approved mock-up of 2026-11-17)."""
        self.ensure_one()
        self._ea_require_access()
        params = {"engagement_id": self.id}
        for key in ("ea_ipe_kind", "ea_ipe_timing"):
            if self.env.context.get(key):
                params[key[7:]] = self.env.context[key]
        return {
            "type": "ir.actions.client", "tag": "ea_audit_tools.ipe_page", "target": "current",
            "name": self.env._("Data quality (IPE)"), "params": params,
            "context": {"active_id": self.id, "ea_engagement_id": self.id},
        }

    def _ea_ipe_labels(self):
        Ipe = self.env["ea.audit.ipe"].with_context(lang=self._ea_page_lang())
        selection = lambda name: dict(Ipe._fields[name]._description_selection(Ipe.env))  # noqa: E731
        return selection("kind"), selection("timing"), selection("obtained"), selection("conclusion")

    def _ea_ipe_chip_text(self, chip):
        _ = self.env._
        state = chip["state"]
        score = "%d/%d" % (chip["passed"], chip["applicable"])
        if state == "not_uploaded":
            return _("Not uploaded")
        if state == "not_reliable":
            return _("Not reliable")
        if state == "to_explain":
            return _("%(count)s to explain", count=chip["toExplain"])
        if state == "reliable":
            return "%s · %s" % (_("Reliable"), score)
        if state == "limitations":
            return "%s · %s" % (_("Reliable with limitations"), score)
        return "%s · %s" % (_("To conclude"), score)

    def _ea_ipe_readonly(self):
        root = self.sudo()
        if root._ea_is_archived():
            return "archived"
        role = self.env.user._ea_firm_role()
        if not role or role == "read_only" or root._ea_acts_as_eqr(self.env.user):
            return "read-only"
        return False

    def ea_ipe_page(self, kind=None, timing=None):
        """What the page shows: the matrix of kinds and timings, and the box open below it."""
        self.ensure_one()
        self._ea_require_access()
        root = self.sudo()
        kinds, timings, _obtained, _conclusions = self._ea_ipe_labels()
        records = {(r.kind, r.timing): r for r in self.env["ea.audit.ipe"].sudo().search([("engagement_id", "=", self.id)])}
        rows = []
        for kind_key in self._ea_ipe_kinds():
            cells = []
            for timing_key in self._ea_ipe_timings():
                record = records.get((kind_key, timing_key))
                chip = record._ea_chip() if record else ipe.chip([], False, False, set())
                cells.append({
                    "kind": kind_key, "timing": timing_key, "ref": ipe.reference(kind_key, timing_key),
                    "state": chip["state"], "tone": chip["tone"], "text": self._ea_ipe_chip_text(chip),
                    "file": record.source_filename if record and record._ea_file() else "",
                })
            rows.append({"kind": kind_key, "label": kinds.get(kind_key, kind_key), "cells": cells})
        detail = None
        if kind and timing and kind in ipe.KINDS and timing in timings:
            detail = self._ea_ipe_detail(kind, timing)
        readonly = self._ea_ipe_readonly()
        return {
            "engagement": root.name or root.client_id.name,
            "timings": [{"key": key, "label": timings[key]} for key in self._ea_ipe_timings()],
            "rows": rows, "detail": detail, "readonly": bool(readonly), "archived": readonly == "archived",
        }

    def _ea_ipe_status_text(self, status, count):
        _ = self.env._
        return {
            "passed": _("Passed"), "na": _("Not applicable"), "info": _("Information"),
        }.get(status) or _("%(count)s exceptions", count=count)

    def _ea_ipe_amount(self, value, fr):
        return ipe.amount_text(value, "fr" if fr else "en")

    def _ea_ipe_detail(self, kind, timing):
        root = self.sudo()
        fr = self._ea_page_lang() == "fr_FR"
        lang = "fr" if fr else "en"
        kinds, timings, obtained, conclusions = self._ea_ipe_labels()
        record = root._ea_ipe_record(kind, timing)
        current = record._ea_file() if record else None
        titles = {entry["code"]: entry for entry in ipe.catalogue(kind)}
        checks = []
        for check in (record.check_ids if record else []):
            title = titles.get(check.code) or {"en": check.code, "fr": check.code}
            shown = check.line_ids[:SHOWN_LINES]
            checks.append({
                "id": check.id, "code": check.code, "title": title[lang], "status": check.status,
                "statusText": self._ea_ipe_status_text(check.status, check.exception_count),
                "tone": {"passed": "green", "exceptions": "amber", "na": "grey", "info": "blue"}[check.status],
                "count": check.exception_count, "note": (check.note_fr if fr else check.note_en) or "",
                "explanation": check.explanation or "", "needsExplanation": check.status == "exceptions",
                "lines": [{
                    "row": line.file_row or "", "ref": line.ref or "", "column": line.column_name or "", "value": line.value or "",
                    "amount": self._ea_ipe_amount(line.amount, fr) if line.has_amount else "",
                    "expected": self._ea_ipe_amount(line.expected, fr) if line.has_expected else "",
                    "text": (line.text_fr if fr else line.text_en) or "",
                } for line in shown],
                "more": max(len(check.line_ids) - len(shown), 0),
            })
        chip = record._ea_chip() if record else ipe.chip([], False, False, set())
        readonly = bool(self._ea_ipe_readonly())
        user = self.env.user
        signing = {
            "preparer": {"by": record.preparer_id.name, "date": upload_stamp(self, record.prepared_at)} if record and record.preparer_id else False,
            "reviewer": {"by": record.reviewer_id.name, "date": upload_stamp(self, record.reviewed_at)} if record and record.reviewer_id else False,
        }
        signing["canPrepare"] = bool(record) and not readonly and not record.preparer_id and bool(record.conclusion)
        signing["canReview"] = (
            bool(record) and not readonly and bool(record.preparer_id) and not record.reviewer_id
            and record.preparer_id != user and can_review(user._ea_firm_role())
        )
        signing["mine"] = [role for role, signer in (("preparer", record.preparer_id), ("reviewer", record.reviewer_id))
                           if record and signer == user and not readonly]
        codes = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.id)], order="sequence, code")
        papers = [
            {"id": item.id, "code": item.code, "title": item.short_title or item.title}
            for item in codes if kind in ipe.kinds_for_paper(item.code)
        ]
        tools = [
            {"method": method, "label": fr_label if fr else en_label}
            for method, en_label, fr_label in ipe.TOOLS.get(kind, []) if hasattr(self, method)
        ]
        return {
            "id": record.id if record else False, "kind": kind, "timing": timing, "ref": ipe.reference(kind, timing),
            "kindLabel": kinds.get(kind, kind), "timingLabel": timings.get(timing, timing),
            "hasFile": bool(current), "file": record.source_filename if current else "",
            "versionDate": upload_stamp(self, record.file_uploaded_at) if current else "",
            "lines": record.line_count if current else 0, "entries": record.entry_count if current and kind == "journal_entries" else False,
            "uploadedBy": record.file_uploaded_by_id.name if current else "",
            "checkedAt": upload_stamp(self, record.checked_at) if current and record.checked_at else "",
            "source": {
                key: (record[key].isoformat() if key == "extraction_date" and record[key] else (record[key] or ""))
                for key in SOURCE_FIELDS
            } if record else {key: "" for key in SOURCE_FIELDS},
            "obtainedChoices": [[key, label] for key, label in obtained.items()],
            "conclusionChoices": [[key, label] for key, label in conclusions.items()],
            "checks": checks, "chip": dict(chip, text=self._ea_ipe_chip_text(chip)),
            "conclusion": record.conclusion if record else False,
            "signing": signing, "papers": papers, "tools": tools,
            "exportUrl": "/ea_audit_tools/export/ipe_%d/%d" % (record.id, self.id) if record and current else False,
        }

    # ---- changes, each answered with the whole page --------------------------------

    def _ea_ipe_editable(self, kind, timing):
        self.ensure_one()
        self._ea_tool_guard()
        if kind not in ipe.KINDS or timing not in dict(DATASET_TIMING_SELECTION):
            raise rule_error(self.env, "invalid-value")
        record = self.sudo()._ea_ipe_record(kind, timing, create=True)
        self.env.cr.execute("SELECT id FROM ea_audit_ipe WHERE id = %s FOR UPDATE", [record.id])
        return record

    def ea_ipe_save(self, kind, timing, values):
        """Where the data comes from. A new extraction date checks the ledger again (no entry may
        be dated after it)."""
        record = self._ea_ipe_editable(kind, timing)
        values = dict(values or {})
        if set(values) - set(SOURCE_FIELDS):
            raise rule_error(self.env, "invalid-field")
        if "obtained" in values and values["obtained"] and values["obtained"] not in dict(OBTAINED_SELECTION):
            raise rule_error(self.env, "invalid-value")
        values = {key: (value or False) for key, value in values.items()}

        def stored(key):
            value = record[key]
            return value.isoformat() if key == "extraction_date" and value else (value or False)

        changed = {key: value for key, value in values.items() if stored(key) != value}
        if changed:
            record.write(changed)
            self._ea_ipe_void(record, "change")
            if "extraction_date" in changed and record._ea_file():
                self._ea_ipe_run(kind, timing)
        return self.ea_ipe_page(kind, timing)

    def ea_ipe_explain(self, kind, timing, code, text):
        record = self._ea_ipe_editable(kind, timing)
        check = record.check_ids.filtered(lambda c: c.code == code and c.status == "exceptions")[:1]
        if not check:
            raise rule_error(self.env, "not-found")
        text = (text or "").strip() or False
        if (check.explanation or False) != text:
            check.write({"explanation": text})
            self._ea_ipe_void(record, "change")
            if not text and record.conclusion in ("reliable", "limitations"):
                record.write({"conclusion": False})
        return self.ea_ipe_page(kind, timing)

    def ea_ipe_conclude(self, kind, timing, conclusion):
        record = self._ea_ipe_editable(kind, timing)
        if conclusion and conclusion not in dict(CONCLUSION_SELECTION):
            raise rule_error(self.env, "invalid-value")
        if conclusion and not record._ea_file():
            raise rule_error(self.env, "ipe-no-file")
        if conclusion in ("reliable", "limitations"):
            missing = [c.code for c in record.check_ids if c.status == "exceptions" and not (c.explanation or "").strip()]
            if missing:
                raise rule_error(self.env, "ipe-explanation-required", codes=", ".join(missing))
        if (record.conclusion or False) != (conclusion or False):
            record.write({"conclusion": conclusion or False})
            self._ea_ipe_void(record, "change")
        return self.ea_ipe_page(kind, timing)

    def ea_ipe_rerun(self, kind, timing):
        """The "Run the checks again" button."""
        record = self._ea_ipe_editable(kind, timing)
        if not record._ea_file() and not self.sudo()._ea_ipe_current_file(kind, timing):
            raise rule_error(self.env, "ipe-no-file")
        self._ea_ipe_run(kind, timing)
        return self.ea_ipe_page(kind, timing)

    def ea_ipe_sign(self, kind, timing, role):
        """Preparer, then reviewer: a senior or above who is not the preparer (no self-review)."""
        record = self._ea_ipe_editable(kind, timing)
        user = self.env.user
        if role not in ("preparer", "reviewer"):
            raise rule_error(self.env, "invalid-value")
        if not record._ea_file():
            raise rule_error(self.env, "ipe-no-file")
        if not record.conclusion:
            raise rule_error(self.env, "ipe-conclusion-required")
        if role == "preparer":
            if record.preparer_id:
                raise rule_error(self.env, "already-signed")
            record.write({"preparer_id": user.id, "prepared_at": fields.Datetime.now()})
        else:
            if not can_review(user._ea_firm_role()):
                raise rule_error(self.env, "requires-senior")
            if not record.preparer_id:
                raise rule_error(self.env, "ipe-preparer-first")
            if record.preparer_id == user:
                raise rule_error(self.env, "ipe-self-review")
            if record.reviewer_id:
                raise rule_error(self.env, "already-signed")
            record.write({"reviewer_id": user.id, "reviewed_at": fields.Datetime.now()})
        self._ea_log("ipe_signed", "%s signed by %s as %s" % (record.reference, user.name, role))
        return self.ea_ipe_page(kind, timing)

    def ea_ipe_unsign(self, kind, timing, role):
        """Take back one's own signature; the preparer's takes the reviewer's with it."""
        record = self._ea_ipe_editable(kind, timing)
        user = self.env.user
        signer = record.preparer_id if role == "preparer" else record.reviewer_id if role == "reviewer" else None
        if signer is None:
            raise rule_error(self.env, "invalid-value")
        if signer != user:
            raise rule_error(self.env, "forbidden")
        values = {"reviewer_id": False, "reviewed_at": False}
        if role == "preparer":
            values.update({"preparer_id": False, "prepared_at": False})
        record.write(values)
        self._ea_log("ipe_unsigned", "%s sign-off as %s removed by %s" % (record.reference, role, user.name))
        return self.ea_ipe_page(kind, timing)

    def ea_ipe_open(self, target, value=None):
        """Leaving the page: a working paper that relies on the file, or a tool that reads it."""
        self.ensure_one()
        self._ea_require_access()
        if target == "paper":
            item = self.env["ea.audit.file.item"].sudo().search([("id", "=", int(value or 0)), ("engagement_id", "=", self.id)], limit=1)
            if not item:
                raise rule_error(self.env, "not-found")
            return item.with_env(self.env).action_open_paper()
        if target == "tool" and isinstance(value, str) and value.startswith("action_tool_") and hasattr(self, value):
            return getattr(self, value)()
        raise rule_error(self.env, "not-found")

    # ---- the Excel download -------------------------------------------------------

    def _ea_export_dynamic_method(self, kind):
        found = super()._ea_export_dynamic_method(kind)
        if found:
            return found
        if (kind or "").startswith("ipe_") and kind[4:].isdigit():
            return lambda fr: self._ea_export_ipe(int(kind[4:]), fr)
        return None

    def _ea_export_ipe(self, record_id, fr):
        """Download the exceptions (Excel): every stored line of every check, with its file line."""
        from ..exports import simple_workbook

        record = self.env["ea.audit.ipe"].sudo().search([("id", "=", record_id), ("engagement_id", "=", self.id)], limit=1)
        if not record:
            raise rule_error(self.env, "not-found")
        lang = "fr" if fr else "en"
        titles = {entry["code"]: entry[lang] for entry in ipe.catalogue(record.kind)}
        rows = []
        for check in record.check_ids:
            status = self._ea_ipe_status_text(check.status, check.exception_count)
            if not check.line_ids:
                rows.append([check.code, titles.get(check.code, ""), status, "", "", "", "", "", "",
                             (check.note_fr if fr else check.note_en) or "", check.explanation or ""])
            for line in check.line_ids:
                rows.append([
                    check.code, titles.get(check.code, ""), status, line.file_row or "", line.ref or "", line.column_name or "",
                    line.value or "", line.amount if line.has_amount else "", line.expected if line.has_expected else "",
                    (line.text_fr if fr else line.text_en) or "", check.explanation or "",
                ])
        head = {
            "en": ["Check", "Title", "Result", "File line", "Reference", "Column", "Value", "Amount", "Expected", "What was found", "Explanation"],
            "fr": ["Contrôle", "Intitulé", "Résultat", "Ligne du fichier", "Référence", "Colonne", "Valeur", "Montant", "Attendu", "Constat", "Explication"],
        }[lang]
        title = "%s · %s" % (record.reference, record.source_filename or "")
        return "%s-%s.xlsx" % (record.reference, self._ea_export_slug()), simple_workbook(record.reference, head, rows, title=title)

    # ------------------------------------------------------------------
    # The working papers that rely on a file
    # ------------------------------------------------------------------

    def _ea_ipe_relied(self, code):
        """The files a paper relies on: [{ref, kind, timing, file, state, tone, text, record}]."""
        self.ensure_one()
        kinds = ipe.kinds_for_paper(code)
        if not kinds:
            return []
        records = {(r.kind, r.timing): r for r in self.env["ea.audit.ipe"].sudo().search([("engagement_id", "=", self.id), ("kind", "in", kinds)])}
        out = []
        for kind in kinds:
            found = [records[(kind, timing)] for timing in self._ea_ipe_timings() if (kind, timing) in records and records[(kind, timing)]._ea_file()]
            if not found:
                chip = ipe.chip([], False, False, set())
                out.append({"ref": ipe.reference(kind, "pre_audit"), "kind": kind, "timing": "pre_audit", "file": "",
                            "state": chip["state"], "tone": chip["tone"], "text": self._ea_ipe_chip_text(chip), "record": None})
            for record in found:
                chip = record._ea_chip()
                out.append({"ref": record.reference, "kind": kind, "timing": record.timing, "file": record.source_filename or "",
                            "state": chip["state"], "tone": chip["tone"], "text": self._ea_ipe_chip_text(chip), "record": record})
        return out

    def _ea_ipe_unreliable_summary(self, record, lang):
        failing = [check.code for check in record.check_ids if check.status == "exceptions"]
        if not failing:
            return record.reference
        if lang == "fr":
            return "%d contrôle(s) avec des exceptions : %s" % (len(failing), ", ".join(failing))
        return "%d check(s) with exceptions: %s" % (len(failing), ", ".join(failing))

    def _ea_ipe_paper_warning(self, code, lang=None):
        """The plain warning a reviewer reads before signing a paper whose file is "Not reliable"
        (owner's ruling: the reviewer is warned, never stopped). False when there is none."""
        relied = [row for row in self._ea_ipe_relied(code) if row["state"] == "not_reliable"]
        if not relied:
            return False
        if lang is None:
            lang = "fr" if is_french(self.env) else "en"
        env = self.with_context(lang="fr_FR" if lang == "fr" else "en_US").env
        texts = [
            env._("This paper relies on %(file)s, marked Not reliable in IPE: %(summary)s. Conclusions drawn from it may be wrong.",
                  file="%s (%s)" % (row["file"], row["ref"]), summary=self._ea_ipe_unreliable_summary(row["record"], lang))
            for row in relied
        ]
        return " ".join(texts)


class PaperIpe(models.Model):
    _inherit = "ea.audit.paper"

    def _ea_data_relied(self):
        """The "Data relied on" card of the rail: the IPE references of the files this paper
        relies on, their status, and the warning a reviewer reads before signing."""
        self.ensure_one()
        engagement = self.sudo().engagement_id.with_env(self.env)
        rows = engagement.sudo()._ea_ipe_relied(self.sudo().code)
        if not rows:
            return False
        first = next((row for row in rows if row["state"] == "not_reliable"), rows[0])
        action = engagement.with_context(ea_ipe_kind=first["kind"], ea_ipe_timing=first["timing"]).action_tool_ipe()
        return {
            "rows": [{key: row[key] for key in ("ref", "file", "state", "tone", "text")} for row in rows],
            "warning": engagement._ea_ipe_paper_warning(self.sudo().code),
            "action": action,
        }


class FileItemIpe(models.Model):
    _inherit = "ea.audit.file.item"

    def action_sign(self, requested):
        """A reviewer (or the partner) signing a paper whose file is "Not reliable" is not
        stopped: the warning they were shown goes on the trail with their signature."""
        role = super().action_sign(requested)
        if self.env.context.get("ea_sign_dry_run") or role not in ("reviewer", "partner"):
            return role
        item = self.sudo()
        engagement = item.engagement_id
        relied = [row for row in engagement._ea_ipe_relied(item.code) if row["state"] == "not_reliable"]
        for row in relied:
            engagement.with_env(self.env)._ea_log("ipe_warning_signed", "%s signed as %s by %s although %s is marked not reliable in IPE: %s" % (
                item.code, role, self.env.user.name, row["ref"], engagement._ea_ipe_unreliable_summary(row["record"], "en"),
            ))
        return role


class DatasetIpe(models.Model):
    _inherit = "ea.audit.dataset"

    def action_open_ipe(self):
        """The upload's data quality, from its form."""
        self.ensure_one()
        engagement = self.sudo().engagement_id.with_env(self.env)
        return engagement.with_context(ea_ipe_kind=self.kind, ea_ipe_timing=self.timing).action_tool_ipe()

    def action_list_ipe(self):
        return self._ea_context_engagement().action_tool_ipe()


class TbVersionIpe(models.Model):
    _inherit = "ea.audit.tb.version"

    def action_open_ipe(self):
        self.ensure_one()
        engagement = self.sudo().engagement_id.with_env(self.env)
        return engagement.with_context(ea_ipe_kind="trial_balance", ea_ipe_timing=self.timing).action_tool_ipe()

