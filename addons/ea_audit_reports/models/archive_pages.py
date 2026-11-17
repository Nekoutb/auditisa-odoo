"""The completion checklist (C6.1), the assemble-and-archive page (C6.2) and the archived file's
view (owner's mock-ups of 2026-11-16). Every figure and verdict is the server's; the pages show
what these methods return and decide nothing."""
import base64
import copy
import hashlib
import json
import logging

from markupsafe import Markup

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.signoff_rules import at_least
from odoo.addons.ea_audit_tools.models.tool_record import french_date

from ..rules import gates_error, rule_error
from ..services.archive_seal import (
    ARCHIVE_CONFIRMS, QUESTIONS, SECTION_ARCHIVE, SECTION_TEAM, answer_key, answers_digest, assembly_status,
    build_seal, destruction_refusal, extra_section, note_key, question_rows, ready_to_sign, retention_end,
    safe_name, validate_answer,
)
from ..services.gates import gate_label

_logger = logging.getLogger(__name__)

CHECKLIST_CODE = "C6.1"
ARCHIVE_CODE = "C6.2"
# Finished after the report: the report itself (C2), the checklist and the archive (C6).
POST_REPORT_PREFIXES = ("C2.", "C6.")

# "Checked by the tool": the mock-up's lines first, then the other completion gates.
_CHECK_LABELS = {
    "tasks_addressed": ("Every task addressed (or marked not applicable)", "Chaque tâche traitée (ou marquée non applicable)"),
    "papers_reviewed": ("Every paper prepared, reviewed and signed", "Chaque papier préparé, revu et signé"),
    "review_notes_cleared": ("Review notes cleared", "Notes de revue levées"),
    "controls_concluded": ("Controls tested and concluded", "Contrôles testés et conclus"),
    "substantive_concluded": ("Substantive procedures concluded, misstatements on the summary", "Procédures substantives conclues, anomalies reportées au récapitulatif"),
    "b5_within_materiality": ("Uncorrected misstatements below materiality or addressed", "Anomalies non corrigées sous le seuil ou traitées"),
    "deficiencies_communicated": ("Deficiencies communicated (C5.11)", "Déficiences communiquées (C5.11)"),
    "eqr_complete": ("Quality review complete, if one was appointed (P1.5)", "Revue qualité achevée, si un réviseur a été désigné (P1.5)"),
    "rep_letters_generated": ("Representation letter on file (C3.1)", "Lettre d'affirmation au dossier (C3.1)"),
    "partner_conclusion": ("Partner's conclusion recorded (C4.1)", "Conclusion de l'associé consignée (C4.1)"),
}
_CHECK_ORDER = tuple(_CHECK_LABELS)
# Where each line is put right: a task's paper, or a screen of the engagement.
_CHECK_OPEN = {
    "tasks_addressed": ("method", "tasks"), "papers_reviewed": ("method", "tasks"),
    "review_notes_cleared": ("method", "action_tool_review_notes"), "controls_concluded": ("method", "action_tool_scot"),
    "substantive_concluded": ("method", "action_tool_substantive"), "b5_within_materiality": ("method", "action_tool_sad"),
    "deficiencies_communicated": ("code", "C5.11"), "eqr_complete": ("code", "C4.2"), "rep_letters_generated": ("code", "C3.1"),
    "partner_conclusion": ("method", "action_open_conclusion"), "sections_concluded": ("method", "action_tool_substantive"),
    "risks_concluded": ("method", "action_tool_risk"), "b4_cleared": ("code", "C1.2"), "c43_cleared": ("code", "C4.3"),
    "checklist_signed": ("method", "action_tool_checklist"), "archive_gates": ("method", "action_open_conclusion"),
}
_OPEN_METHODS = {
    "action_tool_review_notes", "action_tool_scot", "action_tool_substantive", "action_tool_sad", "action_open_conclusion",
    "action_tool_risk", "action_tool_checklist", "action_tool_archive", "action_rollforward_next_year",
    "action_open_issue_wizard", "action_export_bundle",
}
_SEALED_EXEMPT = ("manifest.json", "manifest.csv", "SHA256SUMS")


def _pick(obj, fr, *names):
    for name in names:
        value = obj.get(name + ("Fr" if fr else "En")) or obj.get("fr" if fr else "en")
        if value:
            return value
    return ""


class Paper(models.Model):
    _inherit = "ea.audit.paper"

    def _ea_unresolved(self):
        """C6.1 carries the thirteen questions the team answers before the report; C6.2 the two
        confirmations before the archive. Same shape as the papers' own yes/no sections, so the
        paper shows them too and a save stores them as its answers."""
        definition = super()._ea_unresolved()
        extra = {
            CHECKLIST_CODE: (QUESTIONS, SECTION_TEAM, ("A note is required for each answer.", "Une note est requise pour chaque réponse.")),
            ARCHIVE_CODE: (ARCHIVE_CONFIRMS, SECTION_ARCHIVE, ("A note is required for each answer.", "Une note est requise pour chaque réponse.")),
        }.get(self.code)
        if not extra or not definition:
            return definition
        definition = copy.deepcopy(definition)
        definition.setdefault("sections", []).append(extra_section(*extra))
        return definition

    def get_payload(self):
        payload = super().get_payload()
        engagement = self.sudo().engagement_id
        if engagement._ea_is_archived():
            engagement.with_env(self.env)._ea_log_access("open", self.code)
        return payload


class Finding(models.Model):
    _inherit = "ea.audit.finding"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record.engagement_id._ea_late_work_check("finding", record.title or str(record.number or ""))
        return records


class Misstatement(models.Model):
    _inherit = "ea.audit.misstatement"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record.engagement_id._ea_late_work_check("misstatement", record.description or "")
        return records


class DesignedProcedure(models.Model):
    _inherit = "ea.audit.designed.procedure"

    def write(self, vals):
        result = super().write(vals)
        if vals.get("conclusion"):
            for proc in self:
                proc.engagement_id._ea_late_work_check("procedure", "%s %s" % (proc.index_code or "", proc.code or ""))
        return result


class Engagement(models.Model):
    _inherit = "ea.audit.engagement"

    seal_sha256 = fields.Char(string="Sealed copy fingerprint", compute="_compute_seal", compute_sudo=True)
    seal_id = fields.Many2one("ea.audit.archive.seal", compute="_compute_seal", compute_sudo=True)

    def _compute_seal(self):
        Seal = self.env["ea.audit.archive.seal"].sudo()
        for engagement in self:
            seal = Seal.search([("engagement_id", "=", engagement.id)], limit=1)
            engagement.seal_id = seal
            engagement.seal_sha256 = seal.sha256 or False

    # ------------------------------------------------------------------
    # Shared pieces
    # ------------------------------------------------------------------

    def _ea_today(self):
        return fields.Date.context_today(self)

    def _ea_engagement_partners(self):
        partners, _delegate = self._ea_partner_seat()
        return partners

    def _ea_open_late_work(self):
        self.ensure_one()
        return self.env["ea.audit.late.work"].sudo().search([("engagement_id", "=", self.id), ("closed_at", "=", False)], limit=1)

    def _ea_late_work_check(self, kind, label):
        """ISA 230 A21-A24: after the report date, a finding, a misstatement or a procedure
        conclusion is new audit work. Refused unless a late-work note with its reason is open,
        and then named in the trail with that reason."""
        for engagement in self.sudo():
            if not engagement.report_date or engagement._ea_is_archived():
                continue
            note = engagement._ea_open_late_work()
            if not note:
                raise rule_error(self.env, "after-report-date")
            text = (label or "").strip()[:120] or "-"
            if kind == "finding":
                engagement._ea_log("late_work.recorded", "Finding recorded after the report date: %s. Reason: %s" % (text, note.reason))
            elif kind == "misstatement":
                engagement._ea_log("late_work.recorded", "Misstatement recorded after the report date: %s. Reason: %s" % (text, note.reason))
            else:
                engagement._ea_log("late_work.recorded", "Procedure concluded after the report date: %s. Reason: %s" % (text, note.reason))

    def _ea_log_access(self, kind, what):
        """The access log of an archived file: who, when, what. Insert only."""
        for engagement in self:
            self.env["ea.audit.archive.access"].sudo().create({
                "engagement_id": engagement.id, "user_id": self.env.user.id, "kind": kind, "what": (what or "")[:200],
            })

    def _ea_checklist_paper(self, code):
        self.ensure_one()
        Paper = self.env["ea.audit.paper"].sudo()
        paper = Paper.search([("engagement_id", "=", self.id), ("code", "=", code)], limit=1)
        if not paper and not self._ea_is_archived():
            self.sudo()._ea_ensure_task(code)
            item = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.id), ("code", "=", code)], limit=1)
            item._ea_ensure_papers()
            paper = Paper.search([("engagement_id", "=", self.id), ("code", "=", code)], limit=1)
        return paper

    def _ea_open(self, kind, value):
        """A line's way to where it is put right."""
        self.ensure_one()
        if kind == "code":
            item = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.id), ("code", "=", value)], limit=1)
            if not item:
                raise rule_error(self.env, "not-found")
            return item.with_env(self.env).action_open_paper()
        if value == "tasks":
            return self._ea_open_task_list()
        if value not in _OPEN_METHODS:
            raise rule_error(self.env, "forbidden")
        return getattr(self, value)()

    def ea_archive_page_open(self, kind, value):
        self.ensure_one()
        self._ea_require_access()
        return self._ea_open(kind, value)

    # ------------------------------------------------------------------
    # C6.1: the completion checklist
    # ------------------------------------------------------------------

    def _ea_tool_checks(self, fr):
        """What the tool checks before the report is issued: the completion gates, the work of
        the file outside the report and the archive (C2, C6), and the substantive procedures."""
        self.ensure_one()

        def pre(items):
            return [item for item in items if not (item.code or "").startswith(POST_REPORT_PREFIXES)]

        untouched = pre(self._ea_untouched_tasks())
        unsigned, unreviewed = self._ea_paper_gaps()
        papers = pre(unsigned) + [item for item in pre(unreviewed) if item not in unsigned]
        notes = self.env["ea.audit.review.note"].sudo().search([("engagement_id", "=", self.id), ("state", "=", "open")])
        procs = self.env["ea.audit.designed.procedure"].sudo().search([
            ("engagement_id", "=", self.id), ("selected", "=", True), ("in_scope", "=", True),
        ])
        open_procs = procs.filtered(lambda p: p.state != "done" or not p.conclusion)
        out_of_register = self._ea_sad_out_of_register()
        found = {
            "tasks_addressed": (len(untouched), [item.code for item in untouched]),
            "papers_reviewed": (len(papers), [item.code for item in papers]),
            "review_notes_cleared": (len(notes), sorted(set(notes.mapped("code")))),
            "controls_concluded": (len(self._ea_open_control_rows()), []),
            "substantive_concluded": (len(open_procs) + out_of_register, sorted(set(open_procs.mapped("index_code")))),
            "deficiencies_communicated": (self._ea_uncommunicated_significant_count(), []),
        }
        gates = {gate["key"]: gate for gate in self._ea_completion_gates()}
        checks = []
        keys = [key for key in _CHECK_ORDER if key in found or key in gates] + [key for key in gates if key not in _CHECK_LABELS]
        for key in keys:
            if key in found:
                pending, codes = found[key]
                ok = pending == 0
            else:
                ok, pending, codes = gates[key]["ok"], 0 if gates[key]["ok"] else 1, []
            pair = _CHECK_LABELS.get(key)
            kind, value = _CHECK_OPEN.get(key, ("method", "action_open_conclusion"))
            if key == "c43_cleared":
                value = self._ea_open_points_answer()[0]
            checks.append({
                "key": key, "ok": bool(ok), "pending": pending, "codes": codes[:8],
                "label": (pair[1] if fr else pair[0]) if pair else gate_label(key, fr),
                "openKind": kind, "openValue": value,
            })
        return checks

    def _ea_ready_state(self, fr=False):
        self.ensure_one()
        paper = self._ea_checklist_paper(CHECKLIST_CODE)
        values = paper._ea_values() if paper else {}
        checks = self._ea_tool_checks(fr)
        rows = question_rows(QUESTIONS, values, fr)
        record = self._ea_completion_record("ready_to_issue")
        digest = answers_digest(QUESTIONS, values)
        signed = bool(record)
        stale = signed and (record.data or {}).get("digest") != digest
        return {
            "checks": checks, "rows": rows, "ready": ready_to_sign(checks, rows),
            "signed": signed, "stale": stale, "record": record, "digest": digest,
        }

    def _ea_ready_failed(self):
        """For issue_report: the partner's "ready to issue" stands and still describes the file."""
        state = self._ea_ready_state()
        return [] if state["signed"] and not state["stale"] and state["ready"] else ["ready_to_issue"]

    def ea_checklist_page(self):
        self.ensure_one()
        self._ea_require_access()
        fr = self._ea_fr()
        as_root = self.sudo()
        if as_root._ea_is_archived():
            self._ea_log_access("open", CHECKLIST_CODE)
        state = as_root._ea_ready_state(fr)
        record = state["record"]
        partners = as_root._ea_engagement_partners()
        user = self.env.user
        is_partner = user in partners or (as_root.partner_delegate_id and as_root.partner_delegate_id == user)
        readonly = as_root._ea_is_archived() or not self._ea_can_write_role()
        return {
            "engagement": "%s · %s" % (as_root.client_id.name, as_root.fiscal_year),
            "checks": state["checks"], "rows": state["rows"],
            "checksOk": len([c for c in state["checks"] if c["ok"]]), "checksTotal": len(state["checks"]),
            "answered": len([r for r in state["rows"] if r["answered"]]), "questions": len(state["rows"]),
            "ready": state["ready"], "signed": state["signed"] and not state["stale"], "stale": state["stale"],
            "signedBy": record.done_by_id.name if record else "", "signedAt": french_date(record.done_at) if record else "",
            "reportIssued": bool(as_root.report_date), "reportDate": french_date(as_root.report_date) if as_root.report_date else "",
            "signedText": (
                ("Rapport daté du %s." if fr else "Report dated %s.") % french_date(as_root.report_date) if as_root.report_date
                else (("Signé par %s le %s." if fr else "Signed by %s on %s.") % (record.done_by_id.name, french_date(record.done_at))
                      if record and not state["stale"] else "")
            ),
            "canSign": bool(is_partner) and state["ready"] and not readonly and not as_root.report_date,
            "isPartner": bool(is_partner), "readonly": readonly, "archived": as_root._ea_is_archived(),
        }

    def _ea_can_write_role(self):
        try:
            self._ea_require_write()
        except Exception:  # noqa: BLE001 - the role, not an error, decides what the page offers
            return False
        return True

    def _ea_save_confirmation(self, code, questions, key, answer, note):
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_access()
        self._ea_assert_mutable()
        if key not in {q["key"] for q in questions}:
            raise rule_error(self.env, "invalid-key")
        answer = (answer or "").strip().lower()
        refusal = validate_answer(answer, note)
        if refusal:
            raise rule_error(self.env, refusal)
        paper = self._ea_checklist_paper(code)
        paper.with_env(self.env).save_answers({answer_key(key): answer, note_key(key): note.strip()})

    def ea_checklist_answer(self, key, answer, note):
        """One of the thirteen questions: Yes or No, and a note, always."""
        self._ea_save_confirmation(CHECKLIST_CODE, QUESTIONS, key, answer, note)
        return self.ea_checklist_page()

    def ea_sign_ready(self):
        """The engagement partner's "ready to issue": everything green, then signed. Issuing the
        report requires it, and a later change of an answer voids it."""
        self.ensure_one()
        self._ea_report_guard()
        self._ea_assert_mutable()
        as_root = self.sudo()
        if as_root.report_date:
            raise rule_error(self.env, "already-issued")
        state = as_root._ea_ready_state(self._ea_fr())
        if not state["ready"]:
            failed = [c["key"] for c in state["checks"] if not c["ok"]] + [r["key"] for r in state["rows"] if not r["ok"]]
            labels = [c["label"] for c in state["checks"] if not c["ok"]] + ["%d. %s" % (r["n"], r["label"]) for r in state["rows"] if not r["ok"]]
            raise gates_error(self.env, failed, labels)
        data = {"digest": state["digest"], "at": fields.Datetime.to_string(fields.Datetime.now())}
        vals = {"data": data, "done_by_id": self.env.user.id, "done_at": fields.Datetime.now()}
        record = state["record"]
        if record:
            record.write({**vals, "version": record.version + 1})
        else:
            self.env["ea.audit.completion.record"].sudo().create({"engagement_id": self.id, "key": "ready_to_issue", **vals})
        self._ea_log("ready_to_issue", "Completion checklist signed by the partner: ready to issue")
        return self.ea_checklist_page()

    def action_tool_checklist(self):
        self.ensure_one()
        self._ea_require_access()
        return {
            "type": "ir.actions.client", "tag": "ea_audit_reports.checklist_page", "target": "current",
            "name": self.env._("Completion checklist"), "params": {"engagement_id": self.id},
            "context": {"active_id": self.id, "ea_engagement_id": self.id},
        }

    # ------------------------------------------------------------------
    # C6.2: assemble and archive
    # ------------------------------------------------------------------

    def _ea_archive_confirm_rows(self, fr):
        paper = self._ea_checklist_paper(ARCHIVE_CODE)
        return question_rows(ARCHIVE_CONFIRMS, paper._ea_values() if paper else {}, fr)

    def _ea_assembly_confirmed(self):
        return all(row["ok"] for row in self._ea_archive_confirm_rows(False))

    def ea_archive_confirm(self, key, answer, note):
        self._ea_save_confirmation(ARCHIVE_CODE, ARCHIVE_CONFIRMS, key, answer, note)
        return self.ea_archive_page()

    def _ea_kept_until(self):
        if self.retention_until:
            return self.retention_until
        if not self.report_date:
            return False
        years = self.env.company.sudo().ea_retention_years or 10
        return retention_end(self.report_date, years)

    def ea_archive_page(self):
        """What the C6.2 page shows: the 60-day clock, the checks before archiving, the archive
        button for any team member who may write on the file, and, once archived, the lock, addenda and access log."""
        self.ensure_one()
        self._ea_require_access()
        fr = self._ea_fr()
        as_root = self.sudo()
        archived = as_root._ea_is_archived()
        if archived and not self.env.context.get("ea_no_access_log"):
            self._ea_log_access("open", ARCHIVE_CODE)
        user = self.env.user
        partners = as_root._ea_engagement_partners()
        # Any accepted member with write rights archives (owner, 2026-11-16); the EQR stays read-only.
        may_archive = self._ea_can_write_role() and not self._ea_acts_as_eqr(user)
        clock = assembly_status(as_root.report_date, self._ea_today())
        gates = as_root._ea_archive_gates()
        blocking = [g for g in gates if not g["ok"] and g["key"] not in ("checklist_signed", "assembly_confirmed")]
        late = self.env["ea.audit.late.work"].sudo().search([("engagement_id", "=", self.id)])
        confirms = as_root._ea_archive_confirm_rows(fr)
        checks = [
            {"key": "checklist_signed", "ok": bool(as_root._ea_record_exists("ready_to_issue")), "code": CHECKLIST_CODE,
             "label": "Liste d'achèvement signée par l'associé" if fr else "Completion checklist signed by the partner"},
            {"key": "only_assembly", "ok": True, "code": "",
             "label": ("Seuls des travaux d'assemblage depuis la date du rapport" if fr else "Only assembly work since the report date (no new audit work)")
             if not late else (("%d travaux après la date du rapport, chacun avec son motif" if fr else "%d piece(s) of work after the report date, each with its reason") % len(late))},
            {"key": "archive_gates", "ok": not blocking, "code": "",
             "label": ("Portes d'archivage : %d à lever" % len(blocking) if fr else "Archive gates: %d still open" % len(blocking))
             if blocking else ("Toutes les portes d'archivage au vert" if fr else "Every archive gate green")},
        ]
        seal = self.env["ea.audit.archive.seal"].sudo().search([("engagement_id", "=", self.id)], limit=1)
        manifest = self.env["ea.audit.archive.manifest"].sudo().search([("engagement_id", "=", self.id)], limit=1)
        hold = as_root._ea_active_hold()
        kept = as_root._ea_kept_until()
        ready_all = all(c["ok"] for c in checks) and all(r["ok"] for r in confirms)
        open_note = as_root._ea_open_late_work()
        kept_text = french_date(kept) if kept else "—"
        archived_by = (seal.sealed_by_id or manifest.archived_by_id).name or ""
        banner = ("🔒 Archivé le %s par %s. Lecture seule." if fr else "🔒 Archived on %s by %s. Read-only.") % (
            french_date(as_root.archived_at) if as_root.archived_at else "", archived_by)
        if seal:
            banner += (" Empreinte de la copie scellée %s…%s." if fr else " Sealed copy fingerprint %s…%s.") % (seal.sha256[:4], seal.sha256[-4:])
        banner += (" Conservé jusqu'au %s." if fr else " Kept until %s.") % kept_text
        if hold:
            banner += (" Sous conservation légale : %s" if fr else " Under a legal hold: %s") % hold.reason
        seal_text = ""
        if seal:
            seal_text = ("La copie scellée contient %d fichiers. " if fr else "The sealed copy holds %d files. ") % seal.file_count
            if seal.render == "pdf":
                seal_text += "Papiers en PDF, avec une copie HTML de chacun." if fr else "Papers in PDF, with an HTML copy of each."
            else:
                seal_text += "Papiers en HTML : le rendu PDF n'est pas disponible sur ce serveur." if fr else "Papers in HTML: PDF rendering is not available on this server."
        if clock:
            if clock["overdue"]:
                clock_text = ("En retard de %d jours" if fr else "Overdue by %d days") % -clock["days_left"]
            else:
                clock_text = ("%d jours restants" if fr else "%d days left") % clock["days_left"]
        return {
            "engagement": "%s · %s" % (as_root.client_id.name, as_root.fiscal_year),
            "client": as_root.client_id.name or "",
            "reportDate": french_date(as_root.report_date) if as_root.report_date else "",
            "clock": clock and {
                "deadline": french_date(clock["deadline"]), "daysLeft": clock["days_left"], "overdue": clock["overdue"],
                "tone": clock["tone"], "pct": clock["elapsed_pct"], "text": clock_text,
                "deadlineText": ("Échéance d'assemblage %s" if fr else "Assembly deadline %s") % french_date(clock["deadline"]),
            },
            "subtitle": (("Rapport signé le %s" if fr else "Report signed %s") % french_date(as_root.report_date) if as_root.report_date
                         else ("Rapport pas encore émis" if fr else "Report not issued yet")) + " · ISA 230 ¶14–16 · ISQM 1 ¶31(f)",
            "keptText": ("📅 Conservé jusqu'au %s (10 ans, OHADA) ; rien n'est supprimé de lui-même, jamais avant cette date ni sous conservation légale."
                         if fr else "📅 Kept until %s (10 years, OHADA); nothing is deleted by itself, and never before that date or under a legal hold.") % kept_text,
            "banner": banner, "sealText": seal_text,
            "rollLabel": ("Reporter sur %d" if fr else "Roll forward to %d") % (as_root.fiscal_year + 1),
            "checks": checks, "confirms": confirms, "blocking": [gate_label(g["key"], fr) for g in blocking][:12],
            "keptUntil": french_date(kept) if kept else "",
            "isPartner": user in partners, "readonly": archived or not self._ea_can_write_role(),
            "mayArchive": may_archive,
            "canArchive": may_archive and not archived and bool(as_root.report_date) and ready_all and not blocking,
            "canManage": at_least(user._ea_firm_role(), "manager"),
            "canRelease": at_least(user._ea_firm_role(), "partner"),
            "lateWork": [{
                "open": not n.closed_at,
                "text": "%s · %s · %s · %s" % (
                    french_date(n.opened_at), n.opened_by_id.name, n.reason,
                    (("clos le %s" if fr else "closed %s") % french_date(n.closed_at)) if n.closed_at else ("ouvert" if fr else "open"),
                ),
            } for n in late],
            "lateOpen": bool(open_note),
            "archived": archived,
            "archivedAt": french_date(as_root.archived_at) if as_root.archived_at else "",
            "archivedBy": (seal.sealed_by_id or manifest.archived_by_id).name or "",
            "fingerprint": seal.sha256 or "", "fingerprintShort": ("%s…%s" % (seal.sha256[:4], seal.sha256[-4:])) if seal else "",
            "render": seal.render or "", "fileCount": seal.file_count or 0, "hasSeal": bool(seal),
            "held": bool(hold), "holdReason": hold.reason if hold else "",
            "addenda": [{
                "id": a.id, "at": french_date(a.added_at), "by": a.user_id.name, "reason": a.reason,
                "document": a.filename or "", "url": "/web/content/%d?download=true" % a.attachment_id.id if a.attachment_id else "",
            } for a in self.env["ea.audit.archive.addendum"].sudo().search([("engagement_id", "=", self.id)])],
            "access": [{
                "at": french_date(r.accessed_at), "who": r.user_id.name,
                "what": (("Ouvert : %s" if fr else "Opened %s") % r.what) if r.kind == "open"
                else ("Copie scellée téléchargée" if fr else "Downloaded the sealed copy"),
            } for r in self.env["ea.audit.archive.access"].sudo().search([("engagement_id", "=", self.id)], limit=50)],
            "nextYear": as_root.fiscal_year + 1,
        }

    def ea_archive_from_page(self, confirm_name, late_reason=None):
        """The archive button: the team member types the client's name to confirm."""
        self.ensure_one()
        typed = " ".join((confirm_name or "").split()).casefold()
        if not typed or typed != " ".join((self.sudo().client_id.name or "").split()).casefold():
            raise rule_error(self.env, "confirm-name-mismatch")
        self.archive_engagement(late_reason=late_reason)
        return self.with_context(ea_no_access_log=True).ea_archive_page()

    def ea_late_work_open(self, reason):
        """A manager or above opens a late-work note: why audit work is recorded after the report date."""
        self.ensure_one()
        self._ea_hold_guard("manager", "requires-manager")
        self._ea_assert_mutable()
        text = (reason or "").strip()
        if not text:
            raise rule_error(self.env, "reason-required")
        if not self.sudo().report_date:
            raise rule_error(self.env, "no-report")
        if self.sudo()._ea_open_late_work():
            raise rule_error(self.env, "late-work-open")
        self.env["ea.audit.late.work"].sudo().create({"engagement_id": self.id, "reason": text, "opened_by_id": self.env.user.id})
        self._ea_log("late_work.opened", "Work after the report date opened. Reason: %s" % text)
        return self.ea_archive_page()

    def ea_late_work_close(self):
        self.ensure_one()
        self._ea_hold_guard("manager", "requires-manager")
        self._ea_assert_mutable()
        note = self.sudo()._ea_open_late_work()
        if not note:
            raise rule_error(self.env, "no-late-work")
        note.write({"closed_at": fields.Datetime.now(), "closed_by_id": self.env.user.id})
        self._ea_log("late_work.closed", "Work after the report date closed")
        return self.ea_archive_page()

    def ea_hold_from_page(self, reason):
        self.ensure_one()
        if self._ea_active_hold():
            self.release_legal_hold(reason)
        else:
            self.place_legal_hold(reason)
        return self.with_context(ea_no_access_log=True).ea_archive_page()

    def action_tool_archive(self):
        self.ensure_one()
        self._ea_require_access()
        return {
            "type": "ir.actions.client", "tag": "ea_audit_reports.archive_page", "target": "current",
            "name": self.env._("Assemble and archive"), "params": {"engagement_id": self.id},
            "context": {"active_id": self.id, "ea_engagement_id": self.id},
        }

    # ------------------------------------------------------------------
    # Addenda, the sealed copy, retention
    # ------------------------------------------------------------------

    def add_addendum(self, reason, filename=None, content_b64=None):
        """ISA 230 ¶16: after archiving, a change is an addendum (who, when, why, and the document).
        Any member who may write adds one; the archived rows stay untouched."""
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_access()
        if not self.sudo()._ea_is_archived():
            raise rule_error(self.env, "not-archived")
        text = (reason or "").strip()
        if not text:
            raise rule_error(self.env, "reason-required")
        raw = base64.b64decode(content_b64) if content_b64 else b""
        name = safe_name(filename, "addendum") if raw else False
        addendum = self.env["ea.audit.archive.addendum"].sudo().create({
            "engagement_id": self.id, "user_id": self.env.user.id, "reason": text,
            "filename": name, "sha256": hashlib.sha256(raw).hexdigest() if raw else False,
        })
        if raw:
            self.env["ir.attachment"].sudo().create({
                "name": name, "raw": raw, "res_model": "ea.audit.archive.addendum", "res_id": addendum.id,
            })
        self._ea_log("addendum", "Addendum added after archiving: %s" % text)
        return addendum

    def ea_addendum_from_page(self, reason, filename=None, content_b64=None):
        self.add_addendum(reason, filename, content_b64)
        return self.with_context(ea_no_access_log=True).ea_archive_page()

    def download_sealed_copy(self):
        """(filename, bytes) of the sealed copy, for a member of the team; each download is logged."""
        self.ensure_one()
        self._ea_require_access()
        seal = self.env["ea.audit.archive.seal"].sudo().search([("engagement_id", "=", self.id)], limit=1)
        if not seal or not seal.attachment_id:
            raise rule_error(self.env, "not-archived")
        self._ea_log_access("download", seal.filename or "")
        self._ea_log("sealed_copy.downloaded", "Sealed copy downloaded")
        return seal.filename, seal.attachment_id.raw

    def unlink(self):
        """Nothing is deleted by itself at the end of retention; before that date, and under a
        legal hold, deletion is refused."""
        today = fields.Date.context_today(self)
        for engagement in self.sudo():
            if engagement.archived_at:
                refusal = destruction_refusal(engagement.retention_until, bool(engagement._ea_active_hold()), today)
                if refusal:
                    raise rule_error(self.env, refusal)
        return super().unlink()

    # ------------------------------------------------------------------
    # Building the sealed copy (inside archive_engagement, before the lock)
    # ------------------------------------------------------------------

    def _ea_paper_html(self, paper, fr):
        """One paper as a page of its own: its questions and answers, its conclusion, its signatures."""
        definition = paper._ea_resolved()
        values = paper._ea_values()
        labels = {}
        for section in definition.get("sections") or []:
            for item in (section.get("procs") or []) + (section.get("items") or []):
                text = _pick(item, fr)
                for key in ("p_%s" % item["key"], "q_%s" % item["key"]):
                    labels[key] = text
                    labels[key + "_x"] = text + " — note"
                    labels[key + "_na"] = text + (" — sans objet" if fr else " — not applicable")
            for field in section.get("fields") or []:
                if field.get("key"):
                    labels[field["key"]] = _pick(field, fr, "label")
        for index, text in enumerate(definition.get("conclFr" if fr else "conclEn") or []):
            labels["c_%d" % index] = text
            labels["c_%d_x" % index] = text
        item = paper.file_item_id
        rows = Markup("").join(
            Markup("<tr><th>%s</th><td>%s</td></tr>") % (labels.get(key) or key, value)
            for key, value in sorted(values.items()) if (value or "").strip()
        )
        conclusion = self.env["ea.audit.section.conclusion"].sudo().search([("file_item_id", "=", item.id)], limit=1)
        signoffs = self.env["ea.audit.signoff"].sudo().search([("file_item_id", "=", item.id)], order="signed_at, id")
        signs = Markup("").join(
            Markup("<li>%s · %s · %s%s</li>") % (
                s.role, s.user_id.name or "", fields.Datetime.to_string(s.signed_at) or "",
                " (void)" if (s.voided_at or s.invalidated_at) else "",
            ) for s in signoffs
        )
        body = Markup(
            '<!DOCTYPE html><html><head><meta charset="utf-8"/><title>%s</title>'
            "<style>body{font-family:Arial,sans-serif;font-size:12px;color:#1f2a33}h1{font-size:16px;color:#17694f}"
            "table{border-collapse:collapse;width:100%%}th,td{border:1px solid #dfe3e6;padding:4px;text-align:left;vertical-align:top}"
            "th{background:#f3f5f6;width:40%%}</style></head><body>"
            "<h1>%s %s</h1><p>%s · %s</p><table>%s</table>%s<h2>%s</h2><ul>%s</ul></body></html>"
        ) % (
            item.code, item.code, item.title or "", self.client_id.name or "", self.fiscal_year,
            rows or Markup("<tr><td>—</td></tr>"),
            Markup("<h2>%s</h2><p>%s</p>") % ("Conclusion", conclusion.conclusion or "") if conclusion else "",
            "Signatures", signs,
        )
        return str(body).encode("utf-8")

    def _ea_render_pdf(self, bodies):
        """One PDF of every paper when the server can render PDF (wkhtmltopdf), else None."""
        if not bodies:
            return None
        try:
            with self.env.cr.savepoint():
                pdf = self.env["ir.actions.report"].sudo()._run_wkhtmltopdf([body.decode("utf-8") for body in bodies])
            return pdf if isinstance(pdf, bytes) and pdf.startswith(b"%PDF") else None
        except Exception:  # noqa: BLE001 - no PDF engine: the papers stay in HTML, and the seal says so
            _logger.info("sealed copy: PDF rendering unavailable, papers kept as HTML", exc_info=True)
            return None

    def _ea_seal_files(self, manifest_content):
        """[(path, bytes)]: every paper, the live evidence at its latest version, every letter and
        report at its current version, the trail and the archive manifest."""
        self.ensure_one()
        fr = self._ea_fr()
        files, bodies = [], []
        papers = self.env["ea.audit.paper"].sudo().search([("engagement_id", "=", self.id)], order="code")
        for paper in papers:
            if not paper._ea_values() and not paper.file_item_id.signoff_ids:
                continue
            body = self._ea_paper_html(paper, fr)
            bodies.append(body)
            files.append(("papers/%s.html" % safe_name(paper.code), body))
        pdf = self._ea_render_pdf(bodies)
        if pdf:
            files.append(("papers/all-papers.pdf", pdf))
        latest = {}
        for att in self.env["ea.audit.task.attachment"].sudo().search([("engagement_id", "=", self.id), ("deleted_at", "=", False)]):
            key = (att.code, att.name)
            if key not in latest or att.version > latest[key].version:
                latest[key] = att
        for (code, name), att in sorted(latest.items()):
            files.append(("evidence/%s/v%d %s" % (safe_name(code), att.version, safe_name(name)), att.attachment_id.raw or b""))
        for document in self.sudo().document_ids.sorted("id"):
            version = document.current_version_id
            if not version:
                continue
            extension = (version.attachment_id.name or "x.bin").rsplit(".", 1)[-1]
            files.append(("documents/%s/%d %s.%s" % (safe_name(document.code), document.id, safe_name(document.title), safe_name(extension)),
                          version.attachment_id.raw or b""))
        files.append(("trail/activity.jsonl", ("\n".join(json.dumps(row, ensure_ascii=False) for row in self._ea_trail_rows()) + "\n").encode("utf-8")))
        files.append(("archive-manifest.json", manifest_content.encode("utf-8")))
        return files, ("pdf" if pdf else "html")

    def _ea_build_seal(self, manifest_content):
        self.ensure_one()
        files, render = self._ea_seal_files(manifest_content)
        now = fields.Datetime.now()
        header = {
            "sealVersion": 1, "engagement": self.display_name, "client": self.client_id.name, "fiscalYear": self.fiscal_year,
            "reportDate": self.report_date, "archivedBy": self.env.user.name, "archivedAt": fields.Datetime.to_string(now),
            "retentionUntil": self.retention_until, "papersRenderedAs": render,
        }
        data, overall, rows = build_seal(files, header, now.timetuple()[:6])
        filename = "sealed-copy-%s-FY%s-%d.zip" % (safe_name(self.client_id.name, "file").replace(" ", "-").lower(), self.fiscal_year, self.id)
        seal = self.env["ea.audit.archive.seal"].sudo().create({
            "engagement_id": self.id, "sha256": overall, "zip_sha256": hashlib.sha256(data).hexdigest(),
            "file_count": len(rows), "byte_size": len(data), "render": render, "filename": filename,
            "sealed_by_id": self.env.user.id, "sealed_at": now,
        })
        self.env["ir.attachment"].sudo().create({
            "name": filename, "raw": data, "mimetype": "application/zip",
            "res_model": "ea.audit.archive.seal", "res_id": seal.id,
        })
        self._ea_log("sealed_copy", "Sealed copy made: %d files, fingerprint %s" % (len(rows), overall))
        return seal

