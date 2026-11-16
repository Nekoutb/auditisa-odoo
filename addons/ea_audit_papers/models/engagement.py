from fnmatch import fnmatchcase

from odoo import fields, models

from odoo.addons.ea_audit_core.services.file_scope import RETIRED_CODES

from ..services import acceptance_verdict, document_library, is_blank, paper_for
from odoo.addons.ea_audit_core.services.rollforward_plan import evidence_to_copy

from ..services.completeness import NOT_CARRIED_PAPERS, eqr_decided
from ..services.definitions import carried_paper_keys


class Engagement(models.Model):
    _inherit = "ea.audit.engagement"

    def _ea_paper_values(self, code):
        self.ensure_one()
        paper = self.env["ea.audit.paper"].sudo().search([("engagement_id", "=", self.id), ("code", "=", code)], limit=1)
        return paper._ea_values() if paper else {}

    def _ea_p11_form_state(self):
        """acceptancePaperVerdict. Files on Odoo have no legacy P1.1 form; a migration that
        loads one extends this."""
        self.ensure_one()
        verdict = acceptance_verdict(
            paper_for("P1.1"), paper_for("P1.2"), self._ea_paper_values("P1.1"), self._ea_paper_values("P1.2"),
            predecessor_required=self._ea_predecessor_required(),
        )
        return {
            "complete": verdict["complete"],
            "concluded_accept": verdict["accepted"],
            "checks_passed": verdict["checks_passed"],
        }

    def _ea_predecessor_required(self):
        """P1.2 must be done when it is on the file: active and not marked not applicable."""
        self.ensure_one()
        item = self.env["ea.audit.file.item"].sudo().search(
            [("engagement_id", "=", self.id), ("code", "=", "P1.2")], limit=1,
        )
        return bool(item) and not item.conditional and not item.not_applicable

    def _ea_open_review_notes(self, code_patterns):
        """Open notes on tasks matching the LIKE patterns (P1.% and the like)."""
        self.ensure_one()
        notes = self.env["ea.audit.review.note"].sudo().search(
            [("engagement_id", "=", self.id), ("state", "=", "open")]
        )
        if code_patterns:
            globs = [p.replace("%", "*") for p in code_patterns]
            notes = notes.filtered(lambda n: any(fnmatchcase(n.code or "", g) for g in globs))
        return len(notes), sorted(set(notes.mapped("code")))

    def _ea_eqr_required(self):
        """eqrRequiredTx: the firm decided on P1.5 to appoint a reviewer, or one sits on the team."""
        self.ensure_one()
        if self._ea_eqr_seated():
            return True
        return eqr_decided(self._ea_paper_values("P1.5"))

    def _ea_eqr_seated(self):
        self.ensure_one()
        return bool(self.env["ea.audit.team.member"].sudo().search_count(
            [("engagement_id", "=", self.id), ("team_role", "=", "eqr_reviewer")]
        ))

    def _ea_eqr_task_on_file(self):
        """C4.2 is on the file, active."""
        self.ensure_one()
        return bool(self.env["ea.audit.file.item"].sudo().search_count(
            [("engagement_id", "=", self.id), ("code", "=", "C4.2"), ("conditional", "=", False)]
        ))

    def _ea_set_predecessor_active(self, active):
        """setPredecessorTaskActiveTx: P1.2 follows P1.1's profile. A task that holds work
        stays active."""
        self.ensure_one()
        self._ea_set_task_active("P1.2", active)

    def _ea_retire_merged_tasks(self):
        """P7.1 and S6.2 are merged into P1.4 and S6.1, and C5.2 is no longer a paper of the file
        (owner's decisions of 2026-11-16: file_scope.RETIRED_CODES). On the
        open files among ``self`` (all open files when empty), each of them still active and
        holding no answer, evidence, conclusion or sign-off leaves the file. A task with work
        stays, and an archived file is never read for writing (archive trigger). Returns the
        number of tasks retired; running twice retires nothing more."""
        Engagement = self.env["ea.audit.engagement"].sudo()
        engagements = self.sudo() if self else Engagement.search([])
        engagements = engagements.filtered(lambda e: not e.archived_at and e.phase != "archived")
        items = self.env["ea.audit.file.item"].sudo().search([
            ("engagement_id", "in", engagements.ids), ("code", "in", sorted(RETIRED_CODES)), ("conditional", "=", False),
        ])
        retired = items.filtered(lambda item: not item.engagement_id._ea_task_holds_work(item))
        retired.write({"conditional": True})
        return len(retired)

    def _ea_task_holds_work(self, item):
        paper = item._ea_paper()
        return bool(
            item.signoff_ids
            or (paper and any(not is_blank(v) for v in paper._ea_values().values()))
            or self.env["ea.audit.task.attachment"].sudo().search_count([("file_item_id", "=", item.id)])
            or self.env["ea.audit.section.conclusion"].sudo().search_count([("file_item_id", "=", item.id)])
        )

    # ------------------------------------------------------------------
    # The engagement's own documents, offered when a file is attached elsewhere in it
    # ------------------------------------------------------------------

    def _ea_document_rows(self):
        """Every live evidence file of THIS engagement, as plain rows. Nothing of another file."""
        self.ensure_one()
        rows = self.env["ea.audit.task.attachment"].sudo().search([
            ("engagement_id", "=", self.id), ("deleted_at", "=", False),
        ])
        typed = "doc_type" in rows._fields
        labels = dict(rows._fields["doc_type"]._description_selection(self.env)) if typed else {}
        found = []
        for row in rows:
            name = row.name or ""
            found.append({
                "id": row.id, "item_id": row.file_item_id.id, "name": name, "version": row.version,
                "code": row.code or "", "task": row.file_item_id.display_name or "",
                "type": labels.get(row.doc_type, "") if typed and row.doc_type else "",
                "by": row.uploaded_by_id.name or "",
                "date": fields.Date.context_today(self, row.uploaded_at).strftime("%d/%m/%Y") if row.uploaded_at else "",
                "ext": name.rsplit(".", 1)[-1][:4].upper() if "." in name else "DOC",
                "url": "/web/content/%d?download=true" % row.attachment_id.id,
                **row._ea_carry_info(),
            })
        return found

    def ea_document_library(self, search=None):
        """The picker of "Attach a document": this engagement's documents, latest versions, searched
        in the name, type, task code, uploader and date. A team member only (team-only files)."""
        self.ensure_one()
        self._ea_require_access()
        return document_library.library(self.sudo()._ea_document_rows(), search)

    # ------------------------------------------------------------------
    # Roll forward: last year's evidence (owner's ruling of 2026-11-16)
    # ------------------------------------------------------------------

    def _ea_rollforward_carry(self, source, carry, mapping):
        super()._ea_rollforward_carry(source, carry, mapping)
        self.ensure_one()
        if "answers" in carry:
            self._ea_rf_answers(source)

    def _ea_rf_answers(self, source):
        """Roll forward everything (owner 2026-11-16): every paper's answers, as drafts of the new
        file marked "Carried forward from <year>: to update". Not carried: the record of this
        year's work and its conclusions (procedure ticks, conclusion boxes, the concluding and
        closing papers), sign-offs, section conclusions, completion records and review notes,
        which live elsewhere. Dates and figures come as last year's text, to update. A key the
        new file already holds (the profile carried forward) is left as it is. The source file
        is only read."""
        Paper = self.env["ea.audit.paper"].sudo()
        year = source.fiscal_year
        count = 0
        for paper in Paper.search([("engagement_id", "=", source.id), ("code", "not in", NOT_CARRIED_PAPERS)]):
            answers = {a.field_key: a.value for a in paper.answer_ids if not is_blank(a.value)}
            if not answers:
                continue
            item = self._ea_rf_task(paper.code)
            if not item:
                continue
            item._ea_ensure_papers()
            target = Paper.search([("file_item_id", "=", item.id)], limit=1)
            wanted = carried_paper_keys(target._ea_unresolved())
            have = set(target.answer_ids.mapped("field_key"))
            values = {key: value for key, value in answers.items() if key in wanted and key not in have}
            if not values:
                continue
            target._ea_carry_forward_answers(values)
            target.carried_from_year = year
            count += 1
        if count:
            self._ea_log("answers_carried", "%d working paper(s) carried forward from %d as drafts, to update" % (count, year))
        return count

    def _ea_rollforward_evidence(self, source, carry, mapping):
        """Every live file of last year, its latest version, copied onto the same task of this file
        and marked "prior year, carried forward" until reviewed, from every task (no permanent-file
        restriction, owner 2026-11-16). The bytes are not stored twice: the filestore keeps one
        file per checksum, so the new ir.attachment points to the same stored file. A new
        ir.attachment row it is, all the same: its access answers to its own evidence row (the
        team-only rule of the new file), which last year's row cannot give. The source file is only
        read."""
        self.ensure_one()
        count = super()._ea_rollforward_evidence(source, carry, mapping)
        Attachment = self.env["ea.audit.task.attachment"].sudo()
        rows = Attachment.search([("engagement_id", "=", source.id), ("deleted_at", "=", False)])
        chosen = evidence_to_copy([{
            "id": row.id, "item": row.file_item_id.id, "name": row.name, "version": row.version, "code": row.code,
            "deleted": bool(row.deleted_at),
        } for row in rows], carry)
        for row in Attachment.browse([entry["id"] for entry in chosen]):
            item = self._ea_rf_task(row.code)
            if not item:
                continue
            values = {
                "file_item_id": item.id, "name": row.name, "mime": row.mime, "size_bytes": row.size_bytes,
                "version": 1, "uploaded_by_id": row.uploaded_by_id.id,
                "uploaded_at": row.uploaded_at, "carried_from_year": source.fiscal_year,
            }
            values.update(self._ea_rf_evidence_links(row, mapping))
            original = row.attachment_id
            stored = self.env["ir.attachment"].sudo().create({
                "name": values["name"], "raw": original.raw, "mimetype": original.mimetype or row.mime,
                "res_model": "ea.audit.task.attachment", "res_id": 0,
            })
            copy = Attachment.create(dict(values, attachment_id=stored.id))
            stored.res_id = copy.id
            mapping[("ea.audit.task.attachment", row.id)] = copy
            count += 1
        return count

    def _ea_rf_evidence_links(self, row, mapping):
        """ea_audit_tools: the type and the SCOT, control or procedure the file supports, where
        that record was carried too (and the name, when it carries its SCOT's tag)."""
        return {}

    def _ea_instantiate_file_index(self):
        """A task added hidden by a roll-forward, to hold last year's evidence, comes onto the file
        when the new file's scope takes it in."""
        result = super()._ea_instantiate_file_index()
        for engagement in self:
            hidden = self.env["ea.audit.file.item"].sudo().search([
                ("engagement_id", "=", engagement.id), ("conditional", "=", True),
            ])
            if not hidden:
                continue
            scoped = engagement._ea_scoped_templates().filtered(lambda t: not t.conditional)
            holding = self.env["ea.audit.task.attachment"].sudo().search([
                ("file_item_id", "in", hidden.ids), ("carried_from_year", "!=", False), ("deleted_at", "=", False),
            ]).file_item_id | self.env["ea.audit.paper"].sudo().search([
                ("file_item_id", "in", hidden.ids), ("carried_from_year", "!=", False),
            ]).file_item_id
            holding.filtered(lambda i: i.template_id in scoped).write({"conditional": False})
        return result
