"""SCOTs and controls, the owner's mock-ups of 2026-11-16: the overview cards, the
"which control answers which risk" grid and the documents of each SCOT.

A SCOT's documents are evidence files of its walkthrough task (S1.3): they reuse the versioned,
team-only, restorable model of ea_audit_papers and only add which SCOT, which control and what
kind of document each one is. So they also show on S1.3, and its signatures follow them."""
import re
from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.signoff_rules import at_least
from odoo.addons.ea_audit_papers.models.task_attachment import RESTORE_WINDOW_DAYS

from ..rules import rule_error
from ..services.lead_classes import LEAD_INDEXES, lead_index_label
from .scot import WALKTHROUGH_KEYS
from .tool_record import is_french

# The walkthrough task (S1.3) holds the documents of every SCOT, and its files are versioned by
# name. The stored name carries the SCOT's tag, so that the same file name in two SCOTs makes two
# files, each with its own versions; the SCOT page shows the name without it.
_SCOT_TAG = "SCOT %d - "


def _shown_name(scot, name):
    tag = _SCOT_TAG % scot.id
    return name[len(tag):] if name.startswith(tag) else name

WALKTHROUGH_TASK = "S1.3"
DOC_TYPE_SELECTION = [
    ("flowchart", "Flowchart"),
    ("narrative", "Process narrative"),
    ("policy", "Policy"),
    ("walkthrough", "Walkthrough evidence"),
    ("test", "Test evidence"),
    ("other", "Other"),
]


class TaskAttachmentScot(models.Model):
    _inherit = "ea.audit.task.attachment"

    scot_id = fields.Many2one("ea.audit.scot", string="SCOT", index=True, ondelete="set null")
    control_id = fields.Many2one("ea.audit.scot.control", string="Control", index=True, ondelete="set null")
    doc_type = fields.Selection(DOC_TYPE_SELECTION, string="Document type")


class ScotOverview(models.Model):
    _inherit = "ea.audit.scot"

    document_ids = fields.One2many("ea.audit.task.attachment", "scot_id", string="SCOT documents")
    index_count = fields.Integer(string="Number of lead indexes", compute="_compute_overview", compute_sudo=True)
    document_count = fields.Integer(string="Number of documents", compute="_compute_overview", compute_sudo=True)
    answered_count = fields.Integer(string="Risks answered", compute="_compute_overview", compute_sudo=True)
    completeness = fields.Selection(
        [("complete", "Complete"), ("partial", "To finish"), ("empty", "Not started")],
        string="Progress", compute="_compute_overview", compute_sudo=True,
    )
    ea_card = fields.Json(string="Card", compute="_compute_overview", compute_sudo=True)

    @api.depends(
        "index_ids", "wcgw_ids.control_ids", "control_ids.selected_for_testing", "control_ids.operating_eval",
        "document_ids.deleted_at", "assignee_id", "transaction_type", "strategy", "walkthrough_open",
    )
    @api.depends_context("lang")
    def _compute_overview(self):
        fr = is_french(self.env)
        labels = {d["code"]: lead_index_label(d, "fr" if fr else "en") for d in LEAD_INDEXES}
        types = dict(self._fields["transaction_type"]._description_selection(self.env))
        _ = self.env._
        for scot in self:
            documents = scot.document_ids.filtered(lambda d: not d.deleted_at)
            wcgws, controls = scot.wcgw_ids, scot.control_ids
            answered = len(wcgws.filtered("control_ids"))
            selected = controls.filtered("selected_for_testing")
            effective = selected.filtered(lambda c: c.operating_eval == "effective")
            filled = len(WALKTHROUGH_KEYS) - scot.walkthrough_open
            steps = [
                {"key": "indexes", "label": _("Indexes"), "count": None, "state": "done" if scot.index_ids else "todo"},
                {"key": "risks", "label": _("Risks"), "count": len(wcgws), "state": "done" if wcgws else "todo"},
                {"key": "controls", "label": _("Controls"), "count": len(controls), "state": (
                    "none" if not controls else "done" if wcgws and answered == len(wcgws) else "todo")},
                {"key": "walkthrough", "label": _("Walkthrough"), "count": None, "state": (
                    "done" if not scot.walkthrough_open else "todo" if filled else "none")},
                {"key": "documents", "label": _("Docs"), "count": len(set(documents.mapped("name"))), "state": "done" if documents else "none"},
            ]
            if all(step["state"] == "done" for step in steps):
                completeness = "complete"
            elif not wcgws:
                completeness = "empty"
            else:
                completeness = "partial"
            kpis = []
            if wcgws:
                kpis.append({"value": "%d/%d" % (answered, len(wcgws)), "label": _("risks answered"), "warn": answered < len(wcgws)})
                kpis.append({"value": str(len(selected)), "label": _("to test"), "warn": False})
                if effective:
                    kpis.append({"value": str(len(effective)), "label": _("tested, effective"), "warn": False})
            approach = _("Controls approach") if scot.strategy == "controls" else _("Substantive")
            owner = scot.assignee_id.name or _("not assigned")
            scot.index_count = len(scot.index_ids)
            scot.document_count = steps[4]["count"]
            scot.answered_count = answered
            scot.completeness = completeness
            scot.ea_card = {
                "subtitle": "%s · %s · %s %s" % (types.get(scot.transaction_type, ""), approach, _("Owner:"), owner),
                "tags": [{"code": line.index_code, "label": labels.get(line.index_code, "")} for line in scot.index_ids],
                "steps": steps,
                "kpis": kpis,
                "empty": _("No risk recorded yet") if not wcgws else "",
                "emptyHint": _("start with \"What can go wrong\"") if not wcgws else "",
                "border": {"complete": "green", "partial": "amber", "empty": "red"}[completeness],
            }

    # ------------------------------------------------------------------
    # Which control answers which risk
    # ------------------------------------------------------------------

    def _ea_read_guard(self):
        self.ensure_one()
        engagement = self.sudo().engagement_id
        if not engagement:
            raise rule_error(self.env, "not-found")
        engagement.with_env(self.env)._ea_require_access()
        return engagement

    def _ea_can_edit(self, minimum):
        engagement = self.sudo().engagement_id
        try:
            engagement.with_env(self.env)._ea_tool_guard()
        except Exception:  # noqa: BLE001 - only a yes/no for the screen; the write itself re-checks
            return False
        return at_least(self.env.user._ea_firm_role(), minimum)

    def ea_grid(self):
        """Rows: what can go wrong. Columns: the controls, C1, C2... A dot where they are linked."""
        self._ea_read_guard()
        as_root = self.sudo()
        controls = as_root.control_ids
        return {
            "wcgws": [{"id": w.id, "description": w.description, "answered": bool(w.control_ids)} for w in as_root.wcgw_ids],
            "controls": [{"id": c.id, "code": c.code, "name": c.name} for c in controls],
            "links": [[w.id, c.id] for w in as_root.wcgw_ids for c in w.control_ids],
            "canEdit": self._ea_can_edit("senior"),
        }

    def ea_toggle_link(self, wcgw_id, control_id):
        """A click on a cell: links the control to the risk, or unlinks it (a senior and above)."""
        self.ensure_one()
        as_root = self.sudo()
        wcgw = as_root.wcgw_ids.filtered(lambda w: w.id == wcgw_id)
        control = as_root.control_ids.filtered(lambda c: c.id == control_id)
        if not wcgw or not control:
            raise rule_error(self.env, "not-found")
        linked = control not in wcgw.control_ids
        wcgw.with_env(self.env).toggle_control(control, linked)
        return self.ea_grid()

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    def _ea_walkthrough_task(self):
        item = self.env["ea.audit.file.item"].sudo().search(
            [("engagement_id", "=", self.sudo().engagement_id.id), ("code", "=", WALKTHROUGH_TASK)], limit=1,
        )
        if not item:
            raise rule_error(self.env, "not-found")
        return item

    def _ea_document(self, document_id):
        row = self.env["ea.audit.task.attachment"].sudo().browse(int(document_id or 0)).exists()
        if not row or row.scot_id != self.sudo():
            raise rule_error(self.env, "scot-document-not-found")
        return row

    def _ea_control_of(self, control_id):
        if not control_id:
            return self.env["ea.audit.scot.control"]
        control = self.sudo().control_ids.filtered(lambda c: c.id == int(control_id))
        if not control:
            raise rule_error(self.env, "not-found")
        return control

    def ea_documents(self):
        """The live documents (latest version of each name), and the ones removed in the last 30 days."""
        self._ea_read_guard()
        type_labels = dict(self.env["ea.audit.task.attachment"]._fields["doc_type"]._description_selection(self.env))
        rows = self.env["ea.audit.task.attachment"].sudo().search([("scot_id", "=", self.id)], order="name, version desc")
        live = {}
        for row in rows.filtered(lambda r: not r.deleted_at):
            entry = live.get(row.name)
            if entry:
                entry["versions"] += 1
                continue
            live[row.name] = {
                "id": row.id, "name": _shown_name(self, row.name), "version": row.version, "versions": 1,
                "type": row.doc_type or "other", "typeLabel": type_labels.get(row.doc_type or "other", ""),
                "by": row.uploaded_by_id.name or "", "date": row.uploaded_at.strftime("%d/%m/%Y") if row.uploaded_at else "",
                "controlId": row.control_id.id or False, "controlCode": row.control_id.code or "",
                "url": "/web/content/%d?download=true" % row.attachment_id.id,
                "ext": row.name.rsplit(".", 1)[-1][:4].upper() if "." in row.name else "DOC",
            }
        floor = fields.Datetime.now() - timedelta(days=RESTORE_WINDOW_DAYS)
        removed = {}
        for row in rows.filtered(lambda r: r.deleted_at and r.deleted_at >= floor):
            if row.name not in live:
                removed.setdefault(row.name, {"id": row.id, "name": _shown_name(self, row.name), "by": row.deleted_by_id.name or ""})
        role = self.env.user._ea_firm_role()
        can_write = self._ea_can_edit("staff")
        return {
            "engagementId": self.sudo().engagement_id.id,
            "live": list(live.values()),
            "removed": list(removed.values()),
            "canUpload": can_write,
            "canRemove": can_write and at_least(role, "manager"),
            "types": [[key, type_labels.get(key, key)] for key, _label in DOC_TYPE_SELECTION],
            "controls": [[c.id, "%s %s" % (c.code, c.name)] for c in self.sudo().control_ids],
        }

    def upload_document(self, filename, content_b64, doc_type="other", control_id=False):
        """One file, added to the walkthrough task's evidence: a known name becomes its next version."""
        self.ensure_one()
        self._ea_guard()
        if doc_type not in dict(DOC_TYPE_SELECTION):
            raise rule_error(self.env, "invalid-value")
        control = self._ea_control_of(control_id)
        item = self._ea_walkthrough_task()
        base = re.split(r"[/\\]", filename or "")[-1].strip()
        row_id = item.with_env(self.env).upload_attachment((_SCOT_TAG % self.id) + base, content_b64)
        row = self.env["ea.audit.task.attachment"].sudo().browse(row_id)
        row.write({"scot_id": self.id, "doc_type": doc_type, "control_id": control.id or False})
        return self.ea_documents()

    def attach_existing_documents(self, row_ids, doc_type="other", control_id=False):
        """Documents already in the engagement, attached to this SCOT without a new upload."""
        self.ensure_one()
        self._ea_guard()
        if doc_type not in dict(DOC_TYPE_SELECTION):
            raise rule_error(self.env, "invalid-value")
        control = self._ea_control_of(control_id)
        item = self._ea_walkthrough_task()
        tag = _SCOT_TAG % self.id
        Attachment = self.env["ea.audit.task.attachment"].sudo()

        def name_of(name):
            # a document of another SCOT loses that SCOT's tag and takes this one's
            base = re.sub(r"^SCOT \d+ - ", "", name or "")
            return tag + base

        created = item.with_env(self.env)._ea_attach_existing(row_ids, name_of=name_of)
        Attachment.browse(created).write({"scot_id": self.id, "doc_type": doc_type, "control_id": control.id or False})
        return self.ea_documents()

    def set_document(self, document_id, doc_type=None, control_id=None):
        """Changes the type or the control of a document (every version of it)."""
        self.ensure_one()
        self._ea_guard()
        row = self._ea_document(document_id)
        row.file_item_id.with_env(self.env)._ea_guard_evidence("staff")
        values = {}
        if doc_type is not None:
            if doc_type not in dict(DOC_TYPE_SELECTION):
                raise rule_error(self.env, "invalid-value")
            values["doc_type"] = doc_type
        if control_id is not None:
            values["control_id"] = self._ea_control_of(control_id).id or False
        if values:
            row._ea_live_chain().filtered(lambda r: r.scot_id == row.scot_id).write(values)
        return self.ea_documents()

    def remove_document(self, document_id):
        """A soft delete, restorable for 30 days (a manager and above, as on any task)."""
        self.ensure_one()
        self._ea_document(document_id).with_env(self.env).remove()
        return self.ea_documents()

    def restore_document(self, document_id):
        self.ensure_one()
        self._ea_document(document_id).with_env(self.env).restore()
        return self.ea_documents()


class EngagementScotOverview(models.Model):
    _inherit = "ea.audit.engagement"

    def ea_scot_totals(self):
        """The overview's top line: SCOTs, controls, to test, significant accounts without a SCOT."""
        self.ensure_one()
        self._ea_require_access()
        scots = self.sudo().scot_ids
        uncovered = self._ea_scot_studio()["uncoveredIndexes"]
        return {
            "scots": len(scots),
            "controls": len(scots.control_ids),
            "toTest": len(scots.control_ids.filtered("selected_for_testing")),
            "uncovered": len(uncovered),
            "uncoveredLabel": ", ".join(uncovered),
            "canWrite": self._ea_scot_can_write(),
        }

    def _ea_scot_can_write(self):
        try:
            self._ea_tool_guard()
        except Exception:  # noqa: BLE001 - only a yes/no for the screen; the write itself re-checks
            return False
        return True
