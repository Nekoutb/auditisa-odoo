from fnmatch import fnmatchcase

from odoo import fields, models

from odoo.addons.ea_audit_core.services.file_scope import RETIRED_CODES

from ..services import acceptance_verdict, document_library, is_blank, paper_for
from ..services.completeness import eqr_decided


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
        """P7.1 and S6.2 are merged into P1.4 and S6.1 (owner's decision of 2026-11-16). On the
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
            })
        return found

    def ea_document_library(self, search=None):
        """The picker of "Attach a document": this engagement's documents, latest versions, searched
        in the name, type, task code, uploader and date. A team member only (team-only files)."""
        self.ensure_one()
        self._ea_require_access()
        return document_library.library(self.sudo()._ea_document_rows(), search)
