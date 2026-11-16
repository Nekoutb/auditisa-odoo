"""The findings page and the SAD page (owner's mock-ups of 2026-11-16).

Findings: totals at the top, the stages as tabs, the selected finding in full beside the list,
with its ISA 265 assessment in place and its documents. SAD: the uncorrected total against the
materiality levels, one grid of differences with their effect, the side topics as tabs.

Every rule stays where it was: a page call goes through the same guarded methods as the forms
(finding writes, save_deficiency_evaluation, clear, the SAD entry and meta writes, action_post).

A finding's documents are evidence files of a task (ea.audit.task.attachment, ea_audit_papers):
versioned, team-only, restorable, and part of what that task's signatures attest. They are filed
on the finding's own paper, else on C5.11 (deficiencies and matters) or C1.1 (misstatements).
"""
from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.signoff_rules import at_least
from odoo.addons.ea_audit_papers.models.errors import paper_error

from ..rules import rule_error
from ..services.sad_view import effective_income_after_tax, fs_caption_amounts
from ..services.worksheet_pages import (
    after_tax,
    finding_stage,
    findings_summary,
    materiality_bar,
    sad_effects,
    sad_totals,
    stage_steps,
)
from .tool_record import free_name, french_date, grouped, is_french

#: What another record may raise: the three routes of the register.
FINDING_KINDS = {"misstatement": "b5", "deficiency": "c1", "matter": "b4"}
#: The paper a finding goes to when its source holds no paper of its own (a journal entry: E3.1).
FINDING_PAPERS = {"ea.audit.je.review": "E3.1"}
#: Where a finding's documents go when the finding names no paper.
DOCUMENT_HOSTS = {"b5": ("C1.1", "C5.11"), "c1": ("C5.11", "C1.1"), "b4": ("C5.11", "C1.1")}
FINDINGS_LINKS = (
    "action_open_finding_wizard", "action_export_findings", "action_tool_sad", "action_tool_deficiencies",
)
SAD_LINKS = ("action_export_sad", "action_tool_findings", "action_open_sad_conclusion")
META_FIELDS = (
    "concl_text", "tax_rate", "turnaround_factual", "turnaround_judgmental", "income_after_tax",
) + tuple("tq_%d" % i for i in range(1, 6)) + tuple("tq_%dc" % i for i in range(1, 6))


class TaskAttachmentFinding(models.Model):
    _inherit = "ea.audit.task.attachment"

    finding_id = fields.Many2one("ea.audit.finding", string="Finding", index=True, ondelete="set null")


class FindingPage(models.Model):
    _inherit = "ea.audit.finding"

    impact = fields.Text(string="Why it matters")
    source_model = fields.Char(string="Raised from (model)", readonly=True)
    source_id = fields.Integer(string="Raised from (record)", readonly=True)
    source_label = fields.Char(string="Raised from", compute="_compute_source_label", compute_sudo=True)
    document_ids = fields.One2many("ea.audit.task.attachment", "finding_id", string="Documents")

    @api.depends("source_model", "source_id")
    def _compute_source_label(self):
        for finding in self:
            label = False
            if finding.source_model in self.env and finding.source_id:
                record = self.env[finding.source_model].sudo().browse(finding.source_id).exists()
                if record:
                    label = record.code if record._name == "ea.audit.file.item" else record.display_name
            finding.source_label = label

    def _ea_document_host(self):
        """The task the finding's documents are filed on."""
        self.ensure_one()
        root = self.sudo()
        if root.file_item_id:
            return root.file_item_id
        Item = self.env["ea.audit.file.item"].sudo()
        for code in DOCUMENT_HOSTS[root.route]:
            item = Item.search([("engagement_id", "=", root.engagement_id.id), ("code", "=", code)], limit=1)
            if item:
                return item
        raise rule_error(self.env, "not-found")

    def _ea_documents(self):
        """The latest version of each live document."""
        self.ensure_one()
        rows = self.env["ea.audit.task.attachment"].sudo().search(
            [("finding_id", "=", self.id), ("deleted_at", "=", False)], order="name, version desc",
        )
        live = {}
        for row in rows:
            if row.name in live:
                continue
            live[row.name] = {
                "id": row.id, "name": row.name, "version": row.version,
                "by": row.uploaded_by_id.name or "", "date": french_date(row.uploaded_at),
                "url": "/web/content/%d?download=true" % row.attachment_id.id,
                "ext": row.name.rsplit(".", 1)[-1][:4].upper() if "." in row.name else "DOC",
            }
        return list(live.values())

    def ea_upload_document(self, filename, content_b64):
        """A document on this finding: an evidence file of its host task, tagged with the finding."""
        self.ensure_one()
        root = self.sudo()
        root.engagement_id.with_env(self.env)._ea_tool_guard()
        host = root._ea_document_host()
        name = (filename or "").strip()
        clash = self.env["ea.audit.task.attachment"].sudo().search_count([
            ("file_item_id", "=", host.id), ("name", "=", name), ("deleted_at", "=", False),
            ("finding_id", "!=", root.id),
        ])
        if clash:
            raise paper_error(self.env, "name-taken")
        row_id = host.with_env(self.env).upload_attachment(filename, content_b64)
        self.env["ea.audit.task.attachment"].sudo().browse(row_id).finding_id = root.id
        return row_id

    def ea_attach_existing(self, row_ids):
        """Documents already in the engagement, attached to this finding: no new upload. A name
        another finding uses on the same task gets a number, so the two never share a chain."""
        self.ensure_one()
        root = self.sudo()
        root.engagement_id.with_env(self.env)._ea_tool_guard()
        host = root._ea_document_host()
        created = host.with_env(self.env)._ea_attach_existing(
            row_ids, name_of=lambda name: free_name(self.env, host, name, ("finding_id", "!=", root.id)),
        )
        self.env["ea.audit.task.attachment"].sudo().browse(created).write({"finding_id": root.id})
        return created

    def ea_remove_document(self, document_id):
        """Removed as any evidence file is: a manager, restorable for 30 days on the task."""
        self.ensure_one()
        self.sudo().engagement_id.with_env(self.env)._ea_tool_guard()
        row = self.env["ea.audit.task.attachment"].sudo().browse(int(document_id or 0)).exists()
        if not row or row.finding_id != self.sudo():
            raise rule_error(self.env, "not-found")
        return row.with_env(self.env).remove()


class EngagementWorksheetPages(models.Model):
    _inherit = "ea.audit.engagement"

    # ------------------------------------------------------------------
    # Raising a finding from another record
    # ------------------------------------------------------------------

    def _ea_finding_source(self, source_model, source_id):
        if not source_model or source_model not in self.env:
            raise rule_error(self.env, "not-found")
        record = self.env[source_model].sudo().browse(int(source_id or 0)).exists()
        if not record or "engagement_id" not in record._fields or record.engagement_id != self.sudo():
            raise rule_error(self.env, "not-found")
        return record

    def ea_raise_finding(
        self, source_model, source_id, description, amount=None, finding_type="misstatement", detail=None,
        severity=None, recommendation=None, accounts=None, mtype="factual", trivial_confirmed=False,
    ):
        """A finding raised from another record of this engagement (a working paper's step, a
        sample, a journal entry...). ``finding_type``: "misstatement" (it goes onto the SAD and
        the C1.1 schedule with its ``amount``), "deficiency" (an ISA 265 control deficiency,
        graded ``severity``, "deficiency" when none is given) or "matter" (for attention).
        The same rules as a finding entered by hand (routeFinding); the finding keeps where it
        came from, and the source's paper when it has one. Returns the finding."""
        self.ensure_one()
        route = FINDING_KINDS.get(finding_type)
        if not route:
            raise rule_error(self.env, "invalid-value")
        source = self._ea_finding_source(source_model, source_id)
        if source._name == "ea.audit.file.item":
            file_item = source
        elif "file_item_id" in source._fields and source.file_item_id._name == "ea.audit.file.item":
            file_item = source.file_item_id
        else:
            file_item = None
        if not file_item and FINDING_PAPERS.get(source._name):
            file_item = self.env["ea.audit.file.item"].sudo().search(
                [("engagement_id", "=", self.id), ("code", "=", FINDING_PAPERS[source._name])], limit=1,
            )
        result = self.route_finding(
            route, description, detail=detail, recommendation=recommendation,
            severity=severity or ("deficiency" if route == "c1" else None),
            file_item=file_item or None, amount=amount, accounts=accounts, mtype=mtype,
            trivial_confirmed=trivial_confirmed,
        )
        finding = result["finding"]
        finding.sudo().write({"source_model": source._name, "source_id": source.id})
        return finding

    # ------------------------------------------------------------------
    # The findings page
    # ------------------------------------------------------------------

    def action_tool_findings(self):
        """The findings page (owner's mock-up of 2026-11-16)."""
        self.ensure_one()
        self._ea_require_access()
        params = {"engagement_id": self.id}
        if self.env.context.get("ea_finding_id"):
            params["finding_id"] = self.env.context["ea_finding_id"]
        return {
            "type": "ir.actions.client", "tag": "ea_audit_tools.findings_page", "target": "current",
            "name": self.env._("Findings"), "params": params,
            "context": {"active_id": self.id, "ea_engagement_id": self.id},
        }

    def _ea_page_lang(self):
        return "fr_FR" if is_french(self.env) else "en_US"

    def _ea_figure(self, value, lang):
        return "—" if not value or abs(value) < 0.5 else grouped(value, lang)

    def _ea_sad_numbers(self):
        """AD-01, AD-02... in the order the differences were entered."""
        entries = self.env["ea.audit.sad.entry"].sudo().search([("engagement_id", "=", self.id)], order="id")
        return {entry.id: "AD-%02d" % number for number, entry in enumerate(entries, 1)}

    def _ea_page_finding(self, finding_id):
        finding = self.env["ea.audit.finding"].sudo().browse(int(finding_id or 0)).exists()
        if not finding or finding.engagement_id != self.sudo():
            raise rule_error(self.env, "not-found")
        return finding.with_env(self.env)

    def ea_findings_page(self):
        """What the findings page shows, every word in the reader's language."""
        self.ensure_one()
        self._ea_require_access()
        root = self.sudo()
        lang = self._ea_page_lang()
        _ = self.env._
        Finding = self.env["ea.audit.finding"].with_context(lang=lang)
        Evaluation = self.env["ea.audit.deficiency.evaluation"].with_context(lang=lang)
        severities = Finding._fields["severity"]._description_selection(Finding.env)
        severity_label = dict(severities)
        route_label = dict(Finding._fields["route"]._description_selection(Finding.env))
        mtypes = dict(self.env["ea.audit.misstatement"].with_context(lang=lang)._fields["mtype"]._description_selection(Finding.env))
        stage_labels = {
            "raised": _("Raised"), "assessed": _("Assessed"), "discussed": _("Discussed"),
            "reported": _("Reported"), "closed": _("Closed"),
        }
        entries = self.env["ea.audit.sad.entry"].sudo().search([("engagement_id", "=", self.id)])
        numbers = root._ea_sad_numbers()
        sad_of = {entry.misstatement_id.id: numbers[entry.id] for entry in entries if entry.misstatement_id}
        doc_names = {}
        for row in self.env["ea.audit.task.attachment"].sudo().search(
            [("finding_id", "in", root.finding_ids.ids), ("deleted_at", "=", False)],
        ):
            doc_names.setdefault(row.finding_id.id, set()).add(row.name)
        doc_count = {key: len(names) for key, names in doc_names.items()}
        rows, findings = [], []
        for finding in root.finding_ids.sorted("number"):
            evaluation = finding.evaluation_id
            stage = finding_stage(
                finding.route, finding.status, finding.severity, bool(evaluation),
                bool((finding.management_response or "").strip()), bool(evaluation.communicated_on),
            )
            rows.append({"route": finding.route, "severity": finding.severity, "stage": stage})
            if finding.route == "b5":
                severity_text, tone = _("Misstatement"), "grey"
            elif finding.severity:
                severity_text = severity_label[finding.severity]
                tone = {"significant_deficiency": "red", "deficiency": "amber"}.get(finding.severity, "grey")
            else:
                severity_text, tone = _("Other matter"), "grey"
            if stage == "raised":
                stage_text, stage_tone = (_("Not yet assessed") if finding.route == "c1" else _("Raised")), "amber"
            elif stage == "assessed":
                stage_text, stage_tone = _("Waiting for answer"), "amber"
            elif stage == "discussed":
                stage_text, stage_tone = (_("Not yet reported"), "amber") if finding.route == "c1" else (_("Answer received"), "grey")
            elif stage == "reported":
                stage_text, stage_tone = _("Reported %s") % french_date(evaluation.communicated_on)[:5], "green"
            else:
                stage_text, stage_tone = _("Closed"), "green"
            misstatement = finding.misstatement_id
            sad_no = sad_of.get(misstatement.id, "") if misstatement else ""
            subtitle = [route_label.get(finding.route, "")]
            if finding.created_by_id:
                subtitle.append(_("Raised by %(name)s on %(date)s", name=finding.created_by_id.name, date=french_date(finding.create_date)))
            if finding.file_item_id:
                subtitle.append(finding.file_item_id.code)
            if finding.source_label:
                subtitle.append(_("from %s") % finding.source_label)
            if sad_no:
                subtitle.append(_("linked to audit difference %s") % sad_no)
            if misstatement:
                if misstatement.trivial:
                    standing = _("clearly trivial, kept aside")
                elif misstatement.corrected:
                    standing = _("corrected by management")
                else:
                    standing = _("not corrected")
                summary_text = " · ".join(filter(None, [
                    sad_no, mtypes.get(misstatement.mtype, ""), "%s FCFA" % grouped(misstatement.amount, lang), standing,
                ]))
            row = {
                "id": finding.id, "ref": finding.reference, "title": finding.title,
                "paper": finding.file_item_id.code or "", "paperTitle": finding.file_item_id.title or "",
                "route": finding.route, "routeLabel": route_label.get(finding.route, ""),
                "severity": finding.severity or False, "severityLabel": severity_text, "tone": tone,
                "amount": self._ea_figure(misstatement.amount, lang) if misstatement else "—",
                "stage": stage, "stageLabel": stage_text, "stageTone": stage_tone,
                "steps": [dict(step, label=stage_labels[step["key"]]) for step in stage_steps(finding.route, stage)],
                "docs": doc_count.get(finding.id, 0),
                "detail": finding.detail or "", "impact": finding.impact or "",
                "recommendation": finding.recommendation or "", "answer": finding.management_response or "",
                "response": finding.response or "", "closed": finding.status == "cleared",
                "closedBy": finding.cleared_by_id.name or "", "closedOn": french_date(finding.cleared_at),
                "raisedBy": finding.created_by_id.name or "", "raisedOn": french_date(finding.create_date),
                "source": finding.source_label or "",
                "sad": sad_no, "subtitle": " · ".join(subtitle),
                "misstatement": {
                    "type": mtypes.get(misstatement.mtype, ""), "corrected": misstatement.corrected,
                    "trivial": misstatement.trivial, "summary": summary_text,
                } if misstatement else False,
                "evaluation": {
                    "likelihood": evaluation.likelihood or False, "magnitude": evaluation.magnitude or False,
                    "grade": evaluation.grade or finding.severity or False,
                    "suggested": finding.suggested_severity or False,
                    "suggestedLabel": severity_label.get(finding.suggested_severity, "") if finding.suggested_severity else "",
                    "communicatedOn": fields.Date.to_string(evaluation.communicated_on) if evaluation.communicated_on else "",
                    "recipient": evaluation.recipient or "", "aware": bool(evaluation.management_aware),
                    "saved": bool(evaluation),
                } if finding.route == "c1" else False,
            }
            findings.append(row)
        summary = findings_summary(rows)
        reason = self._ea_cra_read_only()
        progress = [_("%(closed)s of %(total)s closed", closed=summary["closed"], total=summary["total"])]
        if summary["waiting"]:
            progress.append(_("%(count)s waiting for management", count=summary["waiting"]))
        if summary["significantNotReported"]:
            progress.append(_("%(count)s significant deficiency not yet reported", count=summary["significantNotReported"]))
        total = summary["total"] or 1
        closed_share = 100.0 * summary["closed"] / total
        waiting_share = 100.0 * summary["waiting"] / total
        # a significant deficiency waiting for its answer shows once, in red
        significant_share = min(100.0 * summary["significantNotReported"] / total, 100.0 - closed_share)
        waiting_share = max(0.0, min(waiting_share, 100.0 - closed_share - significant_share))
        return {
            "engagement": root.display_name,
            "readonly": bool(reason), "archived": reason == "archived",
            "canRemove": at_least(self.env.user._ea_firm_role(), "manager") and not reason,
            "summary": summary,
            "progressText": " · ".join(progress),
            "progress": {
                "closed": closed_share, "waiting": waiting_share, "significant": significant_share,
            },
            "archiveBlock": root._ea_uncommunicated_significant_count(),
            "findings": findings,
            "choices": {
                "likelihood": Evaluation._fields["likelihood"]._description_selection(Evaluation.env),
                "magnitude": Evaluation._fields["magnitude"]._description_selection(Evaluation.env),
                "grade": severities,
            },
        }

    def ea_findings_page_save(self, finding_id, patch):
        """What we found, why it matters, what we recommend, management's answer."""
        self.ensure_one()
        self._ea_page_finding(finding_id).write(dict(patch or {}))
        return self.ea_findings_page()

    def ea_findings_page_evaluate(self, finding_id, patch):
        """The ISA 265 assessment in place: one change merged into what is recorded, then saved
        through save_deficiency_evaluation, its rules and its trail."""
        self.ensure_one()
        finding = self._ea_page_finding(finding_id)
        allowed = {"likelihood", "magnitude", "grade", "communicated_on", "recipient", "management_aware"}
        patch = dict(patch or {})
        if set(patch) - allowed:
            raise rule_error(self.env, "invalid-field")
        evaluation = finding.sudo().evaluation_id
        values = {
            "grade": evaluation.grade or finding.sudo().severity,
            "likelihood": evaluation.likelihood or None, "magnitude": evaluation.magnitude or None,
            "accounts_assertions": evaluation.accounts_assertions, "management_aware": evaluation.management_aware,
            "indicators": evaluation.indicators, "related_ids": evaluation.related_finding_ids.ids,
            "aggregation_note": evaluation.aggregation_note,
            "communicated_on": evaluation.communicated_on or None, "recipient": evaluation.recipient,
        }
        values.update({key: (value or None) if key != "management_aware" else bool(value) for key, value in patch.items()})
        grade = values.pop("grade")
        finding.save_deficiency_evaluation(grade, **values)
        return self.ea_findings_page()

    def ea_findings_page_clear(self, finding_id, response):
        self.ensure_one()
        self._ea_page_finding(finding_id).clear(response)
        return self.ea_findings_page()

    def ea_findings_page_upload(self, finding_id, filename, content_b64):
        self.ensure_one()
        self._ea_page_finding(finding_id).ea_upload_document(filename, content_b64)
        return self.ea_findings_page()

    def ea_findings_page_remove(self, finding_id, document_id):
        self.ensure_one()
        self._ea_page_finding(finding_id).ea_remove_document(document_id)
        return self.ea_findings_page()

    def ea_findings_page_attach(self, finding_id, row_ids):
        self.ensure_one()
        self._ea_page_finding(finding_id).ea_attach_existing(row_ids)
        return self.ea_findings_page()

    def ea_findings_page_reopen(self, finding_id, reason):
        self.ensure_one()
        self._ea_page_finding(finding_id).reopen(reason)
        return self.ea_findings_page()

    def ea_findings_page_documents(self, finding_id):
        self.ensure_one()
        self._ea_require_access()
        return self._ea_page_finding(finding_id).sudo()._ea_documents()

    def ea_findings_page_open(self, method, finding_id=None):
        """The page's buttons that open another screen."""
        self.ensure_one()
        if method == "action_open_evaluation":
            return self._ea_page_finding(finding_id).action_open_evaluation()
        if method not in FINDINGS_LINKS:
            raise rule_error(self.env, "forbidden")
        return getattr(self, method)()

    # ------------------------------------------------------------------
    # The SAD page
    # ------------------------------------------------------------------

    def action_tool_sad(self):
        """The summary of audit differences on one page (owner's mock-up of 2026-11-16)."""
        self.ensure_one()
        self._ea_require_access()
        return {
            "type": "ir.actions.client", "tag": "ea_audit_tools.sad_page", "target": "current",
            "name": self.env._("Summary of audit differences"), "params": {"engagement_id": self.id},
            "context": {"active_id": self.id, "ea_engagement_id": self.id},
        }

    def ea_sad_page(self):
        """What the SAD page shows: the bar, the grid of differences, the side topics."""
        self.ensure_one()
        self._ea_require_access()
        root = self.sudo()
        lang = self._ea_page_lang()
        _ = self.env._
        figure = lambda value: self._ea_figure(value, lang)  # noqa: E731
        Entry = self.env["ea.audit.sad.entry"].with_context(lang=lang)
        Meta = self.env["ea.audit.sad.meta"].with_context(lang=lang)
        types = dict(Entry._fields["mtype"]._description_selection(Entry.env))
        materiality = root._ea_materiality_dict()
        b5 = root._ea_evaluate_b5()
        meta = root._ea_sad_meta(create=False)
        rate = meta.tax_rate if meta else 33
        numbers = root._ea_sad_numbers()
        finding_of = {f.misstatement_id.id: f for f in root.finding_ids if f.misstatement_id}
        buckets = {"uncorrected": [], "corrected": [], "trivial": []}
        effects = []
        for entry in Entry.sudo().search([("engagement_id", "=", self.id)], order="id"):
            data = {
                "drAmount": entry.dr_amount, "crAmount": entry.cr_amount,
                "drCaption": entry.dr_caption_effective, "crCaption": entry.cr_caption_effective,
            }
            effect = sad_effects(data)
            finding = finding_of.get(entry.misstatement_id.id) if entry.misstatement_id else None
            trivial = entry.is_trivial or (entry.register_only and entry.misstatement_id.trivial)
            bucket = "trivial" if trivial else "corrected" if entry.corrected else "uncorrected"
            if bucket == "uncorrected":
                effects.append(effect)
            buckets[bucket].append({
                "id": entry.id, "no": numbers[entry.id], "description": entry.finding or "",
                "type": entry.mtype, "typeLabel": types.get(entry.mtype, ""),
                "drAccount": entry.dr_account or "", "crAccount": entry.cr_account or "",
                "drAmount": figure(entry.dr_amount), "crAmount": figure(entry.cr_amount),
                **{key: figure(value) for key, value in effect.items()},
                "source": finding.reference if finding else (entry.ref or entry.task_code or ""),
                "sourceFindingId": finding.id if finding else False,
                "corrected": entry.corrected, "posted": entry.posted, "stale": entry.stale,
                "registerOnly": entry.register_only,
            })
        totals = sad_totals(effects)
        profit_after_tax = after_tax(totals["profit"], rate)
        fs = fs_caption_amounts(root._ea_tb_balances())
        income = effective_income_after_tax(meta.income_after_tax if meta else 0, fs["netResultAfterTax"] if fs else None)
        bar = materiality_bar(b5["uncorrectedTotal"], materiality, b5["finalMateriality"])
        if not bar:
            status, status_text = "open", _("Not evaluable: materiality is not approved")
        else:
            status = bar["level"]
            words = {
                "over": _("Above the threshold"), "close": _("Close to the threshold"), "under": _("Below the threshold"),
            }
            status_text = _(
                "Uncorrected differences: %(total)s FCFA, %(share)s%% of the threshold (overall - performance = %(threshold)s FCFA, ISA 450)",
                total=grouped(b5["uncorrectedTotal"], lang), share=bar["share"] if bar["share"] is not None else "—",
                threshold=grouped(b5["finalMateriality"], lang),
            )
        Meta_fields = Meta._fields
        answers = Meta_fields["tq_1"]._description_selection(Meta.env)
        factors = [{
            "key": "tq_%d" % i, "label": Meta_fields["tq_%d" % i]._description_string(Meta.env),
            "answer": (meta["tq_%d" % i] or "") if meta else "", "comment": (meta["tq_%dc" % i] or "") if meta else "",
        } for i in range(1, 6)]
        reason = self._ea_cra_read_only()
        cf_rows = meta.cf_row_ids if meta else self.env["ea.audit.sad.cf.row"]
        disc_rows = meta.disc_row_ids if meta else self.env["ea.audit.sad.disc.row"]
        return {
            "engagement": root.display_name,
            "readonly": bool(reason), "archived": reason == "archived",
            "status": status, "statusLabel": words[status] if bar else _("To evaluate"), "statusText": status_text,
            "bar": bar,
            "levels": {
                "uncorrected": grouped(b5["uncorrectedTotal"], lang),
                "trivial": grouped(materiality["trivial"], lang) if materiality else "",
                "threshold": grouped(b5["finalMateriality"], lang) if materiality else "",
                "performance": grouped(materiality["performance"], lang) if materiality else "",
                "overall": grouped(materiality["overall"], lang) if materiality else "",
            },
            "rows": buckets,
            "totals": {key: figure(value) for key, value in totals.items()},
            "afterTax": figure(profit_after_tax),
            "afterTaxLabel": _("After tax at %(rate)s%%", rate=grouped(rate, lang) if rate == int(rate) else rate),
            "income": {
                "before": grouped(income, lang) if income is not None else "—",
                "after": grouped(income + profit_after_tax, lang) if income is not None else "—",
            },
            "toPost": len([r for b in buckets.values() for r in b if not r["posted"] or r["stale"]]),
            "factors": factors, "answers": answers,
            "unanswered": len([f for f in factors if not f["answer"]]),
            "meta": {
                "tax_rate": rate,
                "turnaround_factual": meta.turnaround_factual if meta else 0,
                "turnaround_judgmental": meta.turnaround_judgmental if meta else 0,
                "income_after_tax": meta.income_after_tax if meta else 0,
                "income_tb": grouped(fs["netResultAfterTax"], lang) if fs else "—",
                "concl_text": (meta.concl_text or "") if meta else "",
            },
            "cfRows": [{
                "no": r.no or "", "ref": r.ref or "", "line": r.line or "", "operating": figure(r.operating),
                "investing": figure(r.investing), "financing": figure(r.financing), "evaluation": r.evaluation or "",
            } for r in cf_rows],
            "discRows": [{
                "no": r.no or "", "fn": r.fn or "", "description": r.description or "", "guidance": r.guidance or "",
                "evaluation": r.evaluation or "", "corrected": r.corrected,
            } for r in disc_rows],
        }

    def ea_sad_page_meta_save(self, patch):
        """Other factors, tax and conclusion: through the SAD meta's own guard (saveSadMeta)."""
        self.ensure_one()
        patch = dict(patch or {})
        if set(patch) - set(META_FIELDS):
            raise rule_error(self.env, "invalid-field")
        self._ea_tool_guard()
        self.sudo()._ea_sad_meta().with_env(self.env).write(patch)
        return self.ea_sad_page()

    def ea_sad_page_entry_save(self, entry_id, patch):
        """Corrected or not, in the grid: a posted row re-posts, so the C1.1 schedule follows."""
        self.ensure_one()
        entry = self.env["ea.audit.sad.entry"].sudo().browse(int(entry_id or 0)).exists()
        if not entry or entry.engagement_id != self.sudo():
            raise rule_error(self.env, "not-found")
        entry = entry.with_env(self.env)
        entry.write(dict(patch or {}))
        if entry.sudo().posted:
            entry.action_post()
        return self.ea_sad_page()

    def ea_sad_post_all(self):
        """Post to the C1.1 schedule: every difference not posted yet, or changed since."""
        self.ensure_one()
        self._ea_tool_guard()
        Entry = self.env["ea.audit.sad.entry"]
        for entry in Entry.sudo().search([("engagement_id", "=", self.id)]):
            item = entry.misstatement_id
            behind = entry.register_only and item and (item.mtype != entry.mtype or item.corrected != entry.corrected)
            if not entry.posted or entry.stale or behind:
                entry.with_env(self.env).action_post()
        return self.ea_sad_page()

    def ea_sad_page_open(self, method, entry_id=None):
        """The page's buttons that open another screen: a difference in its form, a new one,
        the export, the findings, the cash-flow and disclosure rows."""
        self.ensure_one()
        self._ea_require_access()
        if method in ("new", "entry"):
            view = self.env.ref("ea_audit_tools.view_sad_entry_form").id
            action = {
                "type": "ir.actions.act_window", "res_model": "ea.audit.sad.entry",
                "name": self.env._("Audit difference"), "view_mode": "form", "views": [(view, "form")],
                "target": "new", "context": {"default_engagement_id": self.id, "ea_engagement_id": self.id},
            }
            if method == "entry":
                entry = self.env["ea.audit.sad.entry"].sudo().browse(int(entry_id or 0)).exists()
                if not entry or entry.engagement_id != self.sudo():
                    raise rule_error(self.env, "not-found")
                action["res_id"] = entry.id
            return action
        if method not in SAD_LINKS:
            raise rule_error(self.env, "forbidden")
        return getattr(self, method)()
