import hashlib
import io
import json
import re
import tempfile
import zipfile
from datetime import timedelta

from markupsafe import Markup

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.file_scope import FACT_CODES, SCOPE_CURRENT
from odoo.addons.ea_audit_core.services.signoff_rules import at_least, can_partner_signoff
from odoo.addons.ea_audit_tools.models.tool_record import french_date, is_french
from odoo.addons.ea_audit_tools.services.materiality_model import uncorrected_misstatement_threshold
from odoo.addons.ea_audit_tools.services.retention import RETENTION_MAX_YEARS, RETENTION_MIN_YEARS, due_for_destruction, retention_until_sql
from odoo.addons.ea_audit_tools.services.risk_model import MGMT_OVERRIDE_PROCEDURE

from ..rules import gates_error, rule_error
from odoo.addons.ea_audit_tools.models.tool_record import grouped

from ..services.articles import mark_articles
from ..services.docx_builder import DOCX_MIME, block, build_docx
from ..services.fs_tieout import run_tieout
from ..services.gates import CODE_CAP, GROUP_OF, GROUPS, gate_applies_to_nature, gate_label
from ..services.letters import LETTER_CODES, LETTER_KINDS, build_letter, end_sentence
from ..services.opinion import OPINIONS, decide_opinion, report_blocks

SYSTEM_COMPLETION_KEYS = {"archive_manifest", "ready_to_issue"}
OPINION_SELECTION = [
    ("unmodified", "Unmodified"), ("qualified", "Qualified"), ("adverse", "Adverse"), ("disclaimer", "Disclaimer"),
]
_REPORT_ENGINE_FIELDS = {
    "report_date", "opinion", "retention_until", "report_basis", "report_kam", "report_kam_none_reason",
    "report_going_concern", "agm_date", "board_date",
}
# What the letter calls a finding's grade.
_GRADES = {
    "significant_deficiency": ("Déficience significative", "Significant deficiency"),
    "deficiency": ("Déficience", "Deficiency"),
    "observation": ("Observation", "Observation"),
}
_ROLE_LABELS = {
    "partner": ("Associé responsable", "Engagement partner"),
    "director": ("Directeur", "Director"),
    "senior_manager": ("Manager senior", "Senior manager"),
    "manager": ("Manager", "Manager"),
    "senior": ("Senior", "Senior"),
    "staff": ("Assistant", "Staff"),
}
_LETTER_STORED_TITLES = {
    "engagement": ("Lettre de mission", "Engagement letter"),
    "planning_tcwg": ("Communication de planification (ISA 260)", "Planning communication (ISA 260)"),
    "rep_affirmation": ("Lettre d'affirmation (pré-arrêté)", "Representation letter (before approval of the accounts)"),
    "rep_complementary": ("Lettre d'affirmation complémentaire", "Complementary representation letter"),
    "management_letter": ("Lettre de recommandations", "Management letter"),
    "tcwg_completion": ("Rapport à la gouvernance — achèvement (ISA 260)", "Governance report — completion (ISA 260)"),
}


def assembly_deadline(report_date):
    """ISA 230 para 14: 60 days from the report date. Shown, not enforced."""
    return report_date + timedelta(days=60)


class Engagement(models.Model):
    _inherit = "ea.audit.engagement"

    report_date = fields.Date(readonly=True, copy=False, tracking=True)
    opinion = fields.Selection(OPINION_SELECTION, readonly=True, copy=False, tracking=True)
    report_basis = fields.Text(string="Basis of the modification", readonly=True, copy=False)
    report_kam = fields.Text(string="Key audit matters", readonly=True, copy=False)
    report_kam_none_reason = fields.Text(readonly=True, copy=False)
    report_going_concern = fields.Boolean(string="Going-concern paragraph", readonly=True, copy=False)
    retention_until = fields.Date(readonly=True, copy=False)
    agm_date = fields.Date(string="General meeting", readonly=True, copy=False)
    board_date = fields.Date(string="Board meeting closing the accounts", readonly=True, copy=False)
    assembly_deadline = fields.Date(string="File assembly deadline", compute="_compute_conclusion_cards")
    lock_status = fields.Char(string="Lock status", compute="_compute_lock_status", compute_sudo=True)
    document_ids = fields.One2many("ea.audit.document", "engagement_id", string="Documents")
    completion_record_ids = fields.One2many("ea.audit.completion.record", "engagement_id", string="Completion records")
    legal_hold_ids = fields.One2many("ea.audit.legal.hold", "engagement_id", string="Legal holds")
    archive_manifest_id = fields.Many2one("ea.audit.archive.manifest", compute="_compute_conclusion_cards", compute_sudo=True)
    held = fields.Boolean(compute="_compute_conclusion_cards", compute_sudo=True)
    completion_gates_html = fields.Html(compute="_compute_conclusion_cards", sanitize=False)
    fs_tieout_html = fields.Html(string="Financial statements tie-out", compute="_compute_conclusion_cards", sanitize=False)
    archive_checklist_html = fields.Html(compute="_compute_conclusion_cards", sanitize=False)
    gates_blocking_count = fields.Integer(compute="_compute_conclusion_cards")
    points_from_prior = fields.Text(compute="_compute_conclusion_cards", compute_sudo=True)

    @api.depends("phase", "archived_at")
    @api.depends_context("lang")
    def _compute_lock_status(self):
        """F073: the settings page says whether the file still takes changes."""
        for engagement in self:
            engagement.lock_status = self.env._("Locked: archived") if engagement._ea_is_archived() else self.env._("Open")

    @api.depends_context("lang")
    def _compute_conclusion_cards(self):
        Manifest = self.env["ea.audit.archive.manifest"].sudo()
        for engagement in self:
            as_root = engagement.sudo()
            engagement.assembly_deadline = assembly_deadline(as_root.report_date) if as_root.report_date else False
            engagement.archive_manifest_id = Manifest.search([("engagement_id", "=", engagement.id)], limit=1)
            engagement.held = bool(as_root._ea_active_hold())
            checklist = as_root._ea_checklist()
            engagement.gates_blocking_count = checklist["blocking"]
            engagement.completion_gates_html = engagement._ea_gates_html(as_root._ea_completion_gates())
            engagement.fs_tieout_html = engagement._ea_tieout_html() if as_root._ea_tb_balances() else False
            engagement.archive_checklist_html = engagement._ea_checklist_html(checklist)
            prior = as_root._ea_completion_data("points_from_prior") or {}
            engagement.points_from_prior = prior.get("points") or False

    def write(self, vals):
        if not self.env.su and set(vals) & _REPORT_ENGINE_FIELDS:
            raise rule_error(self.env, "forbidden")
        if vals.get("archived_at"):
            # What is still pending reaches the database before the lock does, or the
            # archive triggers would refuse the file's own last writes.
            self.env.flush_all()
        return super().write(vals)

    def unlink(self):
        """assertNotHeld: belt to the trigger's braces."""
        for engagement in self.sudo():
            if engagement._ea_active_hold():
                raise rule_error(self.env, "legal-hold")
        return super().unlink()

    # ------------------------------------------------------------------
    # Small shared pieces
    # ------------------------------------------------------------------

    def _ea_fr(self):
        return is_french(self.env)

    def _ea_notify(self, users, kind, title, body=""):
        """createNotification: a row for each addressee, never an email. The bell, when the
        interface addon is installed, gets a line as well. ``title`` and ``body`` may be
        callables of an environment: they then read in each addressee's language."""
        self.ensure_one()
        Notice = self.env["ea.audit.notice"].sudo()
        Bell = self.env.get("ea.audit.notification")
        for user in users:
            reader = self.with_context(lang=user.sudo().lang or self.env.lang).env
            title_text = title(reader) if callable(title) else title
            body_text = body(reader) if callable(body) else body
            Notice.create({"user_id": user.id, "engagement_id": self.id, "kind": kind, "title": title_text, "body": body_text})
            if Bell is not None and user.has_group("ea_audit_core.group_member"):
                Bell.sudo().create({"user_id": user.id, "kind": "mission", "title": title_text, "detail": (body_text or "")[:200], "engagement_id": self.id})

    def _ea_partner_users(self):
        """Every engagement partner on the team."""
        self.ensure_one()
        return self.env["ea.audit.team.member"].sudo().search([
            ("engagement_id", "=", self.id), ("team_role", "=", "partner"),
        ]).user_id

    def _ea_partner_name(self):
        seat = self.env["ea.audit.team.member"].sudo().search([
            ("engagement_id", "=", self.id), ("team_role", "=", "partner"), ("state", "!=", "declined"),
        ], limit=1, order="id")
        return seat.user_id.name or seat.user_id.email or False

    def _ea_letterhead(self):
        """letterheadParagraphs and letterheadFooter, in blocks."""
        company = self.env.company.sudo()
        name = company.ea_display_name or company.name
        head = [block("b", name)]
        head += [block("small", line) for line in (company.ea_letterhead1, company.ea_letterhead2) if line]
        foot = [block("small", company.ea_letterhead_footer)] if company.ea_letterhead_footer else []
        return head, foot

    def _ea_firm_name(self):
        company = self.env.company.sudo()
        return company.ea_display_name or company.name

    def _ea_seal_blocks(self, blocks, language=None):
        """Letterhead, footer, and the validation mark on every article number; the jurist's
        switch also lifts the "(to validate)" of new English wording."""
        head, foot = self._ea_letterhead()
        validated = self.env.company.sudo().ea_articles_validated
        fr = (language or self.sudo().report_language) == "fr"

        def sealed(text):
            text = mark_articles(text, validated, fr)
            return text.replace(" (to validate)", "") if validated and text else text

        return [block(item["t"], sealed(item["s"])) for item in head + blocks + foot]

    def _ea_file_under_code(self, code, title, kind, blocks, note, language=None, restricted=False):
        """fileUnderCode: a generated .docx filed as the next version of the document of that
        title on that task. A very-simple file may lack the task: the OHADA procedures are
        required whatever the tier, so it is added from the template (UAT B34)."""
        self.ensure_one()
        as_root = self.sudo()
        Item = self.env["ea.audit.file.item"].sudo()
        item = Item.search([("engagement_id", "=", self.id), ("code", "=", code)], limit=1)
        if not item:
            as_root._ea_ensure_task(code)
            item = Item.search([("engagement_id", "=", self.id), ("code", "=", code)], limit=1)
            if not item:
                raise rule_error(self.env, "task-not-in-scope")
        if item.conditional and code in FACT_CODES and as_root._ea_scope_version() >= SCOPE_CURRENT:
            # a document filed under a task that waits for its fact is that fact (owner's table of 2026-11-17)
            if as_root._ea_ensure_task(code):
                self._ea_log("tasks_from_facts", "%s brought onto the file: a document was filed under it" % code)
        Document = self.env["ea.audit.document"].sudo()
        document = Document.search([("file_item_id", "=", item.id), ("kind", "=", kind), ("title", "=", title)], limit=1)
        if not document:
            document = Document.create({
                "engagement_id": self.id, "file_item_id": item.id, "title": title, "kind": kind,
                "language": language or as_root.report_language, "restricted": restricted, "created_by_id": self.env.user.id,
            })
        language = language or as_root.report_language
        sealed = self._ea_seal_blocks(blocks, language)
        document._ea_add_version(build_docx(sealed, "fr-FR" if language == "fr" else "en-US"), DOCX_MIME, note, sealed)
        return document

    # ------------------------------------------------------------------
    # Completion records
    # ------------------------------------------------------------------

    def _ea_completion_record(self, key):
        self.ensure_one()
        return self.env["ea.audit.completion.record"].sudo().search(
            [("engagement_id", "=", self.id), ("key", "=", key)], limit=1,
        )

    def _ea_completion_data(self, key):
        record = self._ea_completion_record(key)
        return record.data if record else None

    def completion_record_version(self, key):
        """The token the form holds: "" when there is no record yet."""
        self._ea_require_access()
        record = self._ea_completion_record(key)
        return str(record.version) if record else ""

    def record_completion(self, key, data=None, expected_version=None):
        """recordCompletion. The partner check comes first so staff refused the partner conclusion
        are told it is the partner's (UAT run 2 B36); senior is the floor; points_forward stays
        writable across the archive, for next year's file."""
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_access()
        role = self.env.user._ea_firm_role()
        if key == "partner_conclusion":
            if not can_partner_signoff(role):
                raise rule_error(self.env, "requires-partner")
            refusal = self._ea_partner_tier_refusal()
            if refusal:
                raise rule_error(self.env, refusal)
        if not at_least(role, "senior"):
            raise rule_error(self.env, "requires-senior")
        if key in SYSTEM_COMPLETION_KEYS:
            raise rule_error(self.env, "system-key")
        if key != "points_forward":
            self._ea_assert_mutable()
        self.env.cr.execute(
            "SELECT 1 FROM ea_audit_completion_record WHERE engagement_id = %s AND key = %s FOR UPDATE", [self.id, key],
        )
        record = self._ea_completion_record(key)
        if expected_version is not None and (str(record.version) if record else "") != str(expected_version):
            raise rule_error(self.env, "stale-edit")
        vals = {"data": data or {}, "done_by_id": self.env.user.id, "done_at": fields.Datetime.now()}
        if record:
            record.write({**vals, "version": record.version + 1})
        else:
            record = self.env["ea.audit.completion.record"].sudo().create({"engagement_id": self.id, "key": key, **vals})
        self._ea_log(
            "completion_record_updated" if record.version > 1 else "completion_record_recorded",
            ("Completion record %s updated" if record.version > 1 else "Completion record %s recorded") % key,
        )
        return record

    def _ea_record_exists(self, key):
        return bool(self.env["ea.audit.completion.record"].sudo().search_count(
            [("engagement_id", "=", self.id), ("key", "=", key), ("done", "=", True)],
        ))

    def run_final_analytics(self):
        """finalAnalyticsAction: needs the trial balance; records the review's lines."""
        self.ensure_one()
        self._ea_require_access()
        balances = self.sudo()._ea_tb_balances()
        if not balances:
            raise rule_error(self.env, "no-tb")
        materiality = self.sudo()._ea_materiality_dict() or {}
        lines = sorted(balances, key=lambda line: -abs(line["value"]))[:30]
        return self.record_completion("final_analytical_review", {
            "lines": lines, "performanceMateriality": materiality.get("performance"),
        })

    def _ea_fs_tieout(self, client_fs=None):
        """runFsTieout: the cascade and the aggregates from the current trial balance, the equilibrium
        checks, and, when the client's statements are given (ref;amount), what differs from them above
        the trivial line (spec 10.4). Read as superuser by callers that have guarded."""
        as_root = self.sudo()
        rows = [(line["account"] or "", line["value"]) for line in as_root._ea_tb_balances()]
        threshold = (as_root._ea_materiality_dict() or {}).get("trivial") or 0
        return run_tieout(rows, threshold, client_fs)

    def run_fs_tieout(self, client_fs=None):
        """fsTieoutAction: only a tie-out that passes reaches the gate."""
        self.ensure_one()
        self._ea_require_access()
        result = self._ea_fs_tieout(client_fs)
        if not result["pass"]:
            raise rule_error(self.env, "tieout-failed")
        return self.record_completion("fs_tieout", {
            "checks": result["checks"], "crResult": result["crResult"], "clientCompared": bool(client_fs),
        })

    def action_open_tieout_wizard(self):
        self.ensure_one()
        self._ea_require_access()
        return {
            "type": "ir.actions.act_window", "res_model": "ea.audit.tieout.wizard", "view_mode": "form", "views": [(False, "form")], "target": "new",
            "name": self.env._("Tie-out against the client's statements"), "context": {"default_engagement_id": self.id},
        }

    def _ea_tieout_html(self, result=None):
        """The subtotals of the cascade, the aggregates and the checks, as the auditor reads them."""
        self.ensure_one()
        result = result or self._ea_fs_tieout()
        _ = self.env._
        cell = Markup('<tr class="%s"><td>%s</td><td>%s</td><td class="text-end">%s</td></tr>')
        rows = [
            cell % ("fw-bold" if line["ref"].startswith("X") else "", line["ref"], _(line["label"]), grouped(line["amount"]))
            for line in result["cr"] if line["amount"] or line["ref"] == "XI"
        ]
        rows += [
            cell % ("", line["ref"], _(line["label"]), grouped(line["amount"]))
            for line in result["bilan"] if line["amount"]
        ]
        names = {"tb_balanced": _("Trial balance balanced"), "bilan_equilibrium": _("Balance sheet equilibrium")}
        marks = Markup("").join(
            Markup('<li class="o_ea_gate %s"><span class="o_ea_gate_mark">%s</span> %s</li>') % (
                "o_ea_gate_ok" if check["ok"] else "o_ea_gate_ko", "✓" if check["ok"] else "✗", names[check["key"]],
            ) for check in result["checks"]
        )
        diffs = Markup("").join(
            Markup('<tr class="table-danger"><td>%s</td><td>%s</td><td class="text-end">%s</td></tr>') % (
                diff["ref"],
                _("Client: %(client)s; recomputed: %(recomputed)s", client=diff["client"], recomputed=diff["recomputed"]),
                grouped(diff["difference"]),
            ) for diff in result["clientDiffs"]
        )
        return Markup('<ul class="o_ea_gates">%s</ul><table class="table table-sm o_ea_tieout"><tbody>%s%s</tbody></table>') % (
            marks, diffs, Markup("").join(rows),
        )

    def record_disclosure_checklist(self, all_complete, notes=""):
        self.ensure_one()
        if not all_complete:
            raise rule_error(self.env, "checklist-incomplete")
        return self.record_completion("disclosure_checklist", {"notes": notes or "", "notesRange": "1-36"})

    def record_subsequent_events(self, reviewed_to, events=""):
        self.ensure_one()
        if not reviewed_to:
            raise rule_error(self.env, "fields-required")
        reviewed = fields.Date.to_date(reviewed_to)
        if reviewed <= self.sudo().period_end:
            raise rule_error(self.env, "reviewed-before-period-end")
        return self.record_completion("subsequent_events", {"reviewedTo": reviewed.isoformat(), "events": events or ""})

    def _ea_carry_forward_from(self, source):
        """C6.1 points forward, injected into the next file (spec 8.6)."""
        result = super()._ea_carry_forward_from(source)
        points = source.sudo()._ea_completion_data("points_forward")
        if points:
            self.env["ea.audit.completion.record"].sudo().create({
                "engagement_id": self.id, "key": "points_from_prior", "data": points,
                "done_by_id": self.env.user.id,
            })
        return result

    # ------------------------------------------------------------------
    # C4.1 completion gates
    # ------------------------------------------------------------------

    def _ea_unconcluded_step_items(self):
        """Tasks with a designed program whose conclusion nobody reviewed, ignoring the ISA 240 para 32
        procedure, whose conclusion is its own paper, and the tasks with a step still open."""
        self.ensure_one()
        steps = self.env["ea.audit.program.step"].sudo().search([("engagement_id", "=", self.id), ("status", "!=", "na")])
        reviewed = self.env["ea.audit.section.conclusion"].sudo().search([
            ("engagement_id", "=", self.id), ("reviewed_by_id", "!=", False),
        ]).file_item_id
        unconcluded = steps.filtered(
            lambda s: not (s.source == "risk_extension" and s.description == MGMT_OVERRIDE_PROCEDURE)
            and s.file_item_id not in reviewed
        ).file_item_id
        return unconcluded, steps.filtered(lambda s: s.status == "open")

    def _ea_eqr_signed(self):
        """ISQM 2 para 24-27: the appointed reviewer's own active sign-off on C4.2, with q_complete and
        q_resolved answered yes and last written by that same reviewer (UAT run 3 B02)."""
        self.ensure_one()
        signoffs = self.env["ea.audit.signoff"].sudo().search([
            ("engagement_id", "=", self.id), ("code", "=", "C4.2"), ("kind", "=", "workpaper"), ("role", "=", "eqr"),
            ("voided_at", "=", False), ("invalidated_at", "=", False),
        ])
        answers = self._ea_paper_values("C4.2")
        confirmed = all((answers.get(key) or "").strip() == "yes" for key in ("q_complete", "q_resolved"))
        if not confirmed:
            return False
        for signoff in signoffs:
            if self._ea_is_appointed_eqr(signoff.user_id) and all(
                self._ea_last_writer("C4.2", key) == signoff.user_id for key in ("q_complete", "q_resolved")
            ):
                return True
        return False

    def _ea_last_writer(self, code, key):
        """Who last wrote an answer, from its history: write_uid moves with any later flush of the row."""
        return self.env["ea.audit.paper.answer.history"].sudo().search([
            ("engagement_id", "=", self.id), ("code", "=", code), ("field_key", "=", key),
        ], limit=1).user_id

    def _ea_open_note_count(self):
        return self.env["ea.audit.review.note"].sudo().search_count([("engagement_id", "=", self.id), ("state", "=", "open")])

    def _ea_sad_out_of_register(self):
        """UAT run 2 B12: an uncorrected SAD entry above the trivial line must be posted and current."""
        entries = self.env["ea.audit.sad.entry"].sudo().search([("engagement_id", "=", self.id)])
        trivial = (self._ea_materiality_dict() or {}).get("trivial") or 0
        return len(entries.filtered(lambda e: e.stale or (
            not e.posted and not e.corrected and max(abs(e.dr_amount), abs(e.cr_amount)) >= trivial
        )))

    def _ea_completion_gates(self):
        """completionGatesTx. Run as superuser by the callers that have already guarded."""
        self.ensure_one()
        unconcluded, open_steps = self._ea_unconcluded_step_items()
        Risk = self.env["ea.audit.risk"].sudo()
        open_risks = Risk.search_count([("engagement_id", "=", self.id), ("rebutted", "=", False), ("status", "!=", "concluded")])
        unapproved = Risk.search_count([
            ("engagement_id", "=", self.id), ("added_after_planning", "=", True), ("addition_approved_by_id", "=", False),
        ])
        materiality = self._ea_materiality_dict()
        threshold = uncorrected_misstatement_threshold(materiality)
        uncorrected = sum(self.env["ea.audit.misstatement"].sudo().search([
            ("engagement_id", "=", self.id), ("trivial", "=", False), ("corrected", "=", False),
        ]).mapped("amount"))
        b5_ok = threshold is not None and abs(uncorrected) <= threshold and self._ea_sad_out_of_register() == 0
        open_b4 = self.env["ea.audit.finding"].sudo().search_count([
            ("engagement_id", "=", self.id), ("route", "=", "b4"), ("status", "=", "open"),
        ])
        rep_titles = set(self.env["ea.audit.document"].sudo().search([
            ("engagement_id", "=", self.id), ("code", "=", "C3.1"), ("kind", "=", "letter"),
        ]).mapped("title"))
        eqr_ok = not self._ea_eqr_required() or self._ea_eqr_signed()
        # C4.3 merged into C4.1 (owner's table of 2026-11-17): a file without an active C4.3 clears its
        # open points in C4.1
        points_code, points_key = self._ea_open_points_answer()
        c43_ok = (self._ea_paper_values(points_code).get(points_key) or "").strip() == "yes" and self._ea_open_note_count() == 0
        results = [
            {"key": "sections_concluded", "ok": not unconcluded and not open_steps},
            {"key": "risks_concluded", "ok": open_risks == 0 and unapproved == 0},
            {"key": "b5_within_materiality", "ok": b5_ok},
            {"key": "final_analytical_review", "ok": self._ea_record_exists("final_analytical_review")},
            {"key": "fs_tieout_passed", "ok": self._ea_record_exists("fs_tieout")},
            {"key": "disclosure_checklist", "ok": self._ea_record_exists("disclosure_checklist")},
            {"key": "subsequent_events", "ok": self._ea_record_exists("subsequent_events")},
            {"key": "rep_letters_generated", "ok": len(rep_titles) >= 2},
            {"key": "b4_cleared", "ok": open_b4 == 0},
            {"key": "eqr_complete", "ok": bool(eqr_ok)},
            {"key": "c43_cleared", "ok": c43_ok},
            {"key": "partner_conclusion", "ok": self._ea_record_exists("partner_conclusion")},
        ]
        if self._ea_scope_version() >= SCOPE_CURRENT:
            # the compulsory question of the current scope: it decides whether C1.3 applies
            results.append({"key": "consultation_answered", "ok": bool(self.consultation_needed)})
        return [gate for gate in results if gate_applies_to_nature(gate["key"], self.nature)]

    def _ea_open_points_answer(self):
        """Where "no point remains open at the report date" is answered: C4.3 while it is active on the
        file, C4.1 otherwise."""
        self.ensure_one()
        return ("C4.3", "q_none_open") if self._ea_task_active("C4.3") else ("C4.1", "q_cleared")

    def completion_gates(self):
        self.ensure_one()
        self._ea_require_access()
        return self.sudo()._ea_completion_gates()

    def _ea_raise_report_gates(self, failed):
        if failed:
            raise gates_error(self.env, failed, [gate_label(key, self._ea_fr()) for key in failed])

    def _ea_report_guard(self):
        """canPartnerSignoff, then the engagement partner or their delegate (F003)."""
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_access()
        if not can_partner_signoff(self.env.user._ea_firm_role()):
            raise rule_error(self.env, "requires-partner")
        refusal = self._ea_partner_tier_refusal()
        if refusal:
            raise rule_error(self.env, refusal)

    def issue_report(self, opinion, report_date):
        """issueReport: gates, phase check and report-date stamp in one transaction. Starts the
        60-day assembly clock."""
        self.ensure_one()
        self._ea_report_guard()
        if opinion not in OPINIONS:
            raise rule_error(self.env, "invalid-value")
        self.env.flush_all()
        self.env.cr.execute("SELECT phase, report_date FROM ea_audit_engagement WHERE id = %s FOR UPDATE", [self.id])
        phase, stamped = self.env.cr.fetchone()
        self.invalidate_recordset(["phase", "report_date"])
        if phase not in ("execution", "conclusion"):
            raise rule_error(self.env, "report-requires-execution")
        if stamped:
            raise rule_error(self.env, "already-issued")
        report_date = fields.Date.to_date(report_date)
        as_root = self.sudo()
        failed = [gate["key"] for gate in as_root._ea_completion_gates() if not gate["ok"]]
        # ISA 560 para 6: the reviewed-to date must reach the date being put on the report (UAT run 2 B79).
        if "subsequent_events" not in failed and gate_applies_to_nature("subsequent_events", as_root.nature):
            reviewed_to = (as_root._ea_completion_data("subsequent_events") or {}).get("reviewedTo") or ""
            if not reviewed_to or reviewed_to < report_date.isoformat():
                failed.append("subsequent_events")
        # C6.1: the engagement partner's "ready to issue", still describing the file (owner, 2026-11-16).
        failed += as_root._ea_ready_failed()
        self._ea_raise_report_gates(failed)
        as_root.write({"phase": "conclusion", "report_date": report_date, "opinion": opinion})
        self._ea_log("engagement_finalised", "Report issued: %s, dated %s" % (opinion, french_date(report_date)))
        return True

    def generate_audit_report(self, opinion, report_date, basis=None, going_concern=False, kam=None, kam_none_reason=None):
        """generateAuditReport: the statutory report in the report language, filed under C2.1 as kind='report'."""
        self.ensure_one()
        self._ea_tool_guard()
        as_root = self.sudo()
        client = as_root.client_id
        disagreement = (as_root._ea_completion_data("f8_disagreement") or {}).get("text") if client.co_cac else None
        blocks = report_blocks(
            opinion, client.name, as_root.period_end, fields.Date.to_date(report_date), listed=client.listed, co_cac=client.co_cac,
            basis=basis, going_concern=going_concern, kam=kam, kam_none_reason=kam_none_reason, disagreement=disagreement,
            fr=self._ea_report_fr(),
        )
        return self._ea_file_under_code(
            "C2.1", self._ea_pick("Auditor's report — %s", "Rapport CAC — %s") % as_root.fiscal_year, "report", blocks, "report:%s" % opinion,
        )

    def issue_report_from_form(self, material_misstatement=False, pervasive=False, scope_limitation=False,
                               going_concern_uncertainty=False, report_date=None, basis="", kam="",
                               kam_none=False, kam_none_reason=""):
        """issueReportAction: the opinion is derived from the four drivers, never chosen."""
        self.ensure_one()
        opinion, going_concern = decide_opinion(material_misstatement, pervasive, scope_limitation, going_concern_uncertainty)
        if not report_date:
            raise rule_error(self.env, "fields-required")
        basis, kam, kam_none_reason = (basis or "").strip(), (kam or "").strip(), (kam_none_reason or "").strip()
        if opinion != "unmodified" and not basis:
            raise rule_error(self.env, "basis-required")
        listed = self.sudo().client_id.listed
        if listed and not kam and not (kam_none and kam_none_reason):
            raise rule_error(self.env, "kam-required")
        self.issue_report(opinion, report_date)
        self.sudo().write({
            "report_basis": basis or False, "report_kam": kam or False,
            "report_kam_none_reason": kam_none_reason if listed and kam_none else False,
            "report_going_concern": going_concern,
        })
        return self.generate_audit_report(
            opinion, report_date, basis=basis or None, going_concern=going_concern, kam=kam or None,
            kam_none_reason=kam_none_reason if listed and kam_none else None,
        )

    # ------------------------------------------------------------------
    # Letters
    # ------------------------------------------------------------------

    def _ea_paper_answers(self, code, keys):
        values = self._ea_paper_values(code)
        return [(values.get(key) or "").strip() for key in keys if (values.get(key) or "").strip()]

    def _ea_letter_item_code(self, kind):
        self.ensure_one()
        Item = self.env["ea.audit.file.item"].sudo()
        code = LETTER_CODES[kind]

        def present(candidate):
            return bool(Item.search_count([("engagement_id", "=", self.id), ("code", "=", candidate)]))

        # P7.1 is merged into P1.4 (2026-11-16): only a file that still has it active files there.
        if kind == "planning_tcwg" and Item.search_count([
            ("engagement_id", "=", self.id), ("code", "=", "P7.1"), ("conditional", "=", False),
        ]):
            code = "P7.1"
        if not present(code) and code == "C5.11" and present("C5.1"):
            code = "C5.1"
        if not present(code):
            raise rule_error(self.env, "not-found")
        return code

    def _ea_letter_fields(self, kind, fr):
        self.ensure_one()
        client = self.client_id
        index = 0 if fr else 1
        out = {
            "client_name": client.name, "legal_form": client.legal_form, "fiscal_year": self.fiscal_year,
            "period_end": french_date(self.period_end), "co_cac": client.co_cac, "mandate_type": client.mandate_type,
            "mandate_start_year": client.mandate_start_year, "framework": self.framework or client.framework,
            "address": client.address, "registration_number": client.registration_number, "niu": client.niu,
        }
        Finding = self.env["ea.audit.finding"].sudo()
        if kind in ("management_letter", "tcwg_completion"):
            rank = {"significant_deficiency": 0, "deficiency": 1, "observation": 2}
            findings = Finding.search([("engagement_id", "=", self.id), ("route", "=", "c1")], order="id")
            points = []
            for finding in sorted(findings, key=lambda f: rank.get(f.severity, 3)):
                grade = "[%s] " % _GRADES.get(finding.severity, (finding.severity, finding.severity))[index] if finding.severity else ""
                body = "%s — %s" % (finding.title, finding.detail) if finding.detail else finding.title
                reco = " %s : %s" % ("Recommandation" if fr else "Recommendation", end_sentence(finding.recommendation)) if finding.recommendation else ""
                resp = " %s : %s" % ("Réponse de la direction" if fr else "Management response", end_sentence(finding.management_response)) if finding.management_response else ""
                points.append("%s%s%s%s" % (grade, body, reco, resp))
            out["c1_points"] = points
        if kind in ("rep_affirmation", "tcwg_completion"):
            rows = self.env["ea.audit.misstatement"].sudo().search(
                [("engagement_id", "=", self.id), ("trivial", "=", False), ("corrected", "=", False)], order="id",
            )
            ordered = sorted(rows, key=lambda m: -abs(m.amount))
            out["uncorrected"] = [{"description": m.description, "amount": m.amount} for m in ordered]
        if kind == "rep_affirmation":
            out["specific_representations"] = self._ea_paper_answers("C3.1", ["p_specific", "p_materiality"])
        if kind == "tcwg_completion":
            matters = []
            for finding in Finding.search([("engagement_id", "=", self.id), ("route", "=", "b4")], order="id"):
                grade = "[%s] " % _GRADES.get(finding.severity, (finding.severity, finding.severity))[index] if finding.severity else ""
                body = "%s — %s" % (finding.title, end_sentence(finding.detail)) if finding.detail else end_sentence(finding.title)
                status = (("ouvert" if fr else "open") if finding.status == "open" else ("levé" if fr else "cleared"))
                resp = " %s : %s" % ("Réponse de la direction" if fr else "Management response", end_sentence(finding.management_response)) if finding.management_response else ""
                matters.append("%s%s (%s : %s)%s" % (grade, body, "statut" if fr else "status", status, resp))
            matters += self._ea_paper_answers("C1.2", ["p_collect", "p_conclusion", "p_judgements", "p_disagreements", "key_findings"])
            out["significant_matters"] = matters
        if kind == "planning_tcwg":
            materiality = self._ea_materiality_dict()
            risks = self.env["ea.audit.risk"].sudo().search([
                ("engagement_id", "=", self.id), ("significant", "=", True), ("rebutted", "=", False),
            ], order="id")
            team = self.env["ea.audit.team.member"].sudo().search([
                ("engagement_id", "=", self.id), ("state", "!=", "declined"), ("team_role", "!=", "eqr_reviewer"),
            ], order="id")
            # P1.4 Part D since P7.1 was merged into it; an older file's P7.1 answers still count.
            addressees = self._ea_paper_answers("P1.4", ["tcwg_who"]) or self._ea_paper_answers("P7.1", ["addressees"])
            scope = self._ea_paper_answers("P1.4", ["tcwg_planned"]) or self._ea_paper_answers("P7.1", ["scope"])
            out["planning"] = {
                "addressees": addressees[0] if addressees else "",
                "scope": scope[0] if scope else "",
                "materiality": materiality,
                "risks": risks.mapped("description"),
                "team": [
                    (m.user_id.name or m.user_id.email, _ROLE_LABELS.get(m.team_role, (m.team_role, m.team_role))[index])
                    for m in team
                ],
            }
        return out

    def generate_letter(self, kind, locale=None):
        """generateLetter: a versioned document under its task. Regenerating adds a version."""
        self.ensure_one()
        self._ea_tool_guard()
        if kind not in LETTER_KINDS:
            raise rule_error(self.env, "invalid-letter-kind")
        fr = (locale or self.sudo().report_language) == "fr"
        as_root = self.sudo()
        code = as_root._ea_letter_item_code(kind)
        blocks = build_letter(kind, as_root._ea_letter_fields(kind, fr), fr)
        title = _LETTER_STORED_TITLES[kind][0 if fr else 1]
        document = self._ea_file_under_code(code, title, "letter", blocks, "letter:%s" % kind, "fr" if fr else "en")
        self._ea_log("letter_generated", "%s letter generated: %s (v%d)" % (code, title, document.current_version))
        return document

    def action_generate_letter(self):
        self.ensure_one()
        return self.generate_letter(self.env.context.get("letter_kind")).action_download()

    # ------------------------------------------------------------------
    # Archive gates and checklist
    # ------------------------------------------------------------------

    def _ea_item_activity(self):
        """Per task of the file: holds work, signed by its preparer, reviewed, half-reviewed."""
        self.ensure_one()
        items = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.id)], order="sequence, code")
        steps = self.env["ea.audit.program.step"].sudo().search([("engagement_id", "=", self.id), ("status", "!=", "na")]).file_item_id
        conclusions = self.env["ea.audit.section.conclusion"].sudo().search([("engagement_id", "=", self.id)]).file_item_id
        documents = self.env["ea.audit.document"].sudo().search([("engagement_id", "=", self.id), ("kind", "=", "workpaper")]).file_item_id
        answers = self.env["ea.audit.paper.answer"].sudo().search([("engagement_id", "=", self.id)])
        with_values = {answer.code for answer in answers if (answer.value or "").strip()}
        signoffs = self.env["ea.audit.signoff"].sudo().search([("engagement_id", "=", self.id), ("voided_at", "=", False)])
        prepared = signoffs.filtered(lambda s: s.role == "preparer").file_item_id
        reviewed = signoffs.filtered(lambda s: s.role in ("reviewer", "partner")).file_item_id
        rows = []
        for item in items:
            rows.append({
                "item": item,
                "worked": item in steps or item in conclusions or item in documents or item.code in with_values,
                "prepared": item in prepared,
                "reviewed": item in reviewed,
            })
        return rows

    def _ea_paper_gaps(self):
        """paperGapsTx (finding C5): a task holding work owes a paper, prepared and reviewed."""
        unsigned, unreviewed = [], []
        for row in self._ea_item_activity():
            owes = not row["item"].conditional and row["worked"]
            if owes and not row["prepared"]:
                unsigned.append(row["item"])
            # a paper someone prepared but nobody reviewed blocks the file whether or not it was owed
            if (owes and not row["reviewed"]) or (row["prepared"] and not row["reviewed"]):
                unreviewed.append(row["item"])
        return unsigned, unreviewed

    def _ea_untouched_tasks(self):
        """UAT B63: every non-conditional task carries work or is marked not applicable with a reason.
        An E4 task S5.5 left out is on no list, so it asks for nothing here, and a paper its preparer
        signed is not untouched, whatever it holds: P7.2's answers live on its summary (see QUESTIONS.md)."""
        scoped_out = self._ea_e4_out_of_scope()
        return [
            row["item"] for row in self._ea_item_activity()
            if not row["item"].conditional and not (row["item"].na_reason or "").strip() and not row["worked"]
            and not row["prepared"] and row["item"] not in scoped_out
        ]

    def _ea_paper_is_complete(self, code):
        paper = self.env["ea.audit.paper"].sudo().search([("engagement_id", "=", self.id), ("code", "=", code)], limit=1)
        # as the file documents it: depth, merged parts, a paper concluded before its conversion
        return bool(paper) and paper._ea_complete()

    def _ea_open_control_rows(self):
        """Selected controls not concluded on: design not evaluated, or operating test not recorded,
        unless the selection was reversed in S2.1. Named for the checklist."""
        self.ensure_one()
        controls = self.env["ea.audit.scot.control"].sudo().search([
            ("engagement_id", "=", self.id), ("selected_for_testing", "=", True),
        ])
        return controls.filtered(lambda control: control._ea_is_open()).mapped("name")

    def _ea_archive_gates(self):
        """archiveGates. The 60-day window is shown, not enforced: a late file must still be archivable."""
        self.ensure_one()
        completion_pending = len([gate for gate in self._ea_completion_gates() if not gate["ok"]])
        unsigned, unreviewed = self._ea_paper_gaps()
        untouched = self._ea_untouched_tasks()
        notes = self.env["ea.audit.review.note"].sudo().search([("engagement_id", "=", self.id), ("state", "=", "open")])
        controls = self._ea_open_control_rows()
        uncommunicated = self._ea_uncommunicated_significant_count()
        c41, c62 = self._ea_paper_is_complete("C4.1"), self._ea_paper_is_complete("C6.2")

        def gate(key, pending, codes=()):
            return {"key": key, "ok": pending == 0, "pending": pending, "codes": list(codes)[:CODE_CAP]}

        return [
            gate("report_issued", 0 if self.report_date else 1),
            gate("completion_gates", completion_pending),
            gate("controls_concluded", len(controls)),
            gate("deficiencies_communicated", uncommunicated, ["C5.11"] if uncommunicated else []),
            gate("tasks_addressed", len(untouched), [item.code for item in untouched]),
            gate("reviews_complete", len(unreviewed), [item.code for item in unreviewed]),
            gate("papers_signed", len(unsigned), [item.code for item in unsigned]),
            gate("review_approval", 0 if c41 else 1),
            gate("review_notes_cleared", len(notes), sorted(set(notes.mapped("code")))),
            gate("c62_checklist", 0 if c62 else 1),
            # owner's mock-up of 2026-11-16: the partner's checklist, and the team's two confirmations
            gate("checklist_signed", 0 if self._ea_record_exists("ready_to_issue") else 1, ["C6.1"]),
            gate("assembly_confirmed", 0 if self._ea_assembly_confirmed() else 1, ["C6.2"]),
        ]

    def archive_gates(self):
        self.ensure_one()
        self._ea_require_access()
        return self.sudo()._ea_archive_gates()

    def _ea_checklist_items(self, fr):
        """itemise: behind each gate, the items still standing, with the task to open."""
        self.ensure_one()

        def task(item, suffix=""):
            title = item.short_title or item.title or ""
            return {"label": "%s — %s%s" % (item.code, title, suffix), "code": item.code, "item_id": item.id}

        def code_item(code, fr_label, en_label):
            return {"label": "%s — %s" % (code, fr_label if fr else en_label), "code": code}

        unsigned, unreviewed = self._ea_paper_gaps()
        unconcluded, open_steps = self._ea_unconcluded_step_items()
        sections = []
        for item in (unconcluded | open_steps.file_item_id):
            planned = len(open_steps.filtered(lambda s: s.file_item_id == item))
            if planned:
                suffix = " · %d diligence(s) planifiée(s)" % planned if fr else " · %d step(s) still planned" % planned
            else:
                suffix = " · conclusion de section non revue" if fr else " · section conclusion not reviewed"
            sections.append(task(item, suffix))
        risks = self.env["ea.audit.risk"].sudo().search([("engagement_id", "=", self.id)]).filtered(
            lambda r: (not r.rebutted and r.status != "concluded") or (r.added_after_planning and not r.addition_approved_by_id)
        )
        note_items = [
            {"label": "%s — %s" % (note.code, (note.body or "")[:90]), "code": note.code, "item_id": note.file_item_id.id}
            for note in self.env["ea.audit.review.note"].sudo().search([("engagement_id", "=", self.id), ("state", "=", "open")])
        ]
        open_b4 = self.env["ea.audit.finding"].sudo().search_count([
            ("engagement_id", "=", self.id), ("route", "=", "b4"), ("status", "=", "open"),
        ])
        return {
            "tasks_addressed": [task(item) for item in self._ea_untouched_tasks()],
            "papers_signed": [task(item) for item in unsigned],
            "reviews_complete": [task(item) for item in unreviewed],
            "sections_concluded": sections,
            "risks_concluded": [
                {"label": "%s%s" % (r.description, (" · ajout non approuvé" if fr else " · addition not approved") if r.added_after_planning and not r.addition_approved_by_id else "")}
                for r in risks
            ],
            "controls_concluded": [{"label": row} for row in self._ea_open_control_rows()],
            "review_notes_cleared": note_items,
            "b4_cleared": [{"label": ("%d point(s) significatif(s) ouvert(s) en C1.2" if fr else "%d open significant matter(s) in C1.2") % open_b4}] if open_b4 else [],
            "review_approval": [code_item("C4.1", "récapitulatif de revue et d'approbation", "review and approval summary")],
            "eqr_complete": [code_item("C4.2", "revue de qualité de la mission", "engagement quality review")],
            "deficiencies_communicated": [code_item("C5.11", "évaluation des déficiences (ISA 265)", "deficiency evaluation (ISA 265)")],
            "c43_cleared": [
                code_item("C4.3", "points en suspens", "points outstanding") if self._ea_task_active("C4.3")
                else code_item("C4.1", "points en suspens levés", "open points cleared")
            ] + note_items,
            "c62_checklist": [code_item("C6.2", "documentation et archivage", "documentation and archive")],
            "checklist_signed": [code_item("C6.1", "liste d'achèvement", "completion checklist")],
            "assembly_confirmed": [code_item("C6.2", "confirmations avant l'archivage", "confirmations before archiving")],
        }

    def _ea_checklist(self, locale=None):
        """archiveChecklist: every gate, grouped, each with the items behind it when red."""
        self.ensure_one()
        fr = (locale or ("fr" if self._ea_fr() else "en")) == "fr"
        items = self._ea_checklist_items(fr)

        def line(gate):
            own = items.get(gate["key"], [])
            return {
                "key": gate["key"], "label": gate_label(gate["key"], fr), "ok": gate["ok"],
                "pending": 0 if gate["ok"] else max(gate.get("pending", len(own)), len(own)),
                "blocking": True, "items": [] if gate["ok"] else own,
            }

        lines = []
        for gate in self._ea_archive_gates():
            if gate["key"] == "completion_gates":
                # the archive gate folds the completion gates; the reader wants them unfolded
                lines += [line(g) for g in self._ea_completion_gates()]
            else:
                lines.append(line(gate))
        groups = [
            {"key": key, "title": title_fr if fr else title_en,
             "gates": [g for g in lines if GROUP_OF.get(g["key"], "completion") == key]}
            for key, title_en, title_fr in GROUPS
        ]
        return {
            "archived_at": self.archived_at, "report_date": self.report_date,
            "blocking": len([g for g in lines if not g["ok"]]),
            "groups": [group for group in groups if group["gates"]],
        }

    def archive_checklist(self, locale=None):
        self.ensure_one()
        self._ea_require_access()
        return self.sudo()._ea_checklist(locale)

    def _ea_gates_html(self, gates):
        fr = self._ea_fr()
        rows = Markup("").join(
            Markup('<li class="o_ea_gate %s"><span class="o_ea_gate_mark">%s</span> %s</li>') % (
                "o_ea_gate_ok" if gate["ok"] else "o_ea_gate_ko", "✓" if gate["ok"] else "✗", gate_label(gate["key"], fr),
            ) for gate in gates
        )
        return Markup('<ul class="o_ea_gates">%s</ul>') % rows

    def _ea_checklist_html(self, checklist):
        parts = []
        for group in checklist["groups"]:
            parts.append(Markup('<h4 class="o_ea_group">%s</h4>') % group["title"])
            lines = []
            for gate in group["gates"]:
                subs = Markup("").join(Markup("<li>%s</li>") % item["label"] for item in gate["items"][:CODE_CAP])
                lines.append(Markup('<li class="o_ea_gate %s"><span class="o_ea_gate_mark">%s</span> %s<ul>%s</ul></li>') % (
                    "o_ea_gate_ok" if gate["ok"] else "o_ea_gate_ko", "✓" if gate["ok"] else "✗", gate["label"], subs,
                ))
            parts.append(Markup('<ul class="o_ea_gates">%s</ul>') % Markup("").join(lines))
        return Markup("").join(parts)

    # ------------------------------------------------------------------
    # Archive
    # ------------------------------------------------------------------

    def _ea_manifest(self):
        """Manifest v2: what the file contained when it closed, inside the archiving transaction."""
        self.ensure_one()
        env, company, client = self.env, self.env.company, self.client_id

        def who(user):
            return user.name or user.email if user else None

        def stamp(value):
            return fields.Datetime.to_string(value) if value else None

        def day(value):
            return value.isoformat() if value else None

        def rows(model, *names):
            records = env[model].sudo().search([("engagement_id", "=", self.id)], order="id")
            return [{name: (rec[name].id if hasattr(rec[name], "ids") else rec[name]) or None for name in names} for rec in records]

        items = env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.id)], order="sequence, code")
        answers = env["ea.audit.paper.answer"].sudo().search([("engagement_id", "=", self.id)], order="code, field_key")
        conclusions = env["ea.audit.section.conclusion"].sudo().search([("engagement_id", "=", self.id)], order="code")
        signoffs = env["ea.audit.signoff"].sudo().search([("engagement_id", "=", self.id)], order="signed_at, id")
        documents = env["ea.audit.document"].sudo().search([("engagement_id", "=", self.id)], order="title")
        attachments = env["ea.audit.task.attachment"].sudo().search([("engagement_id", "=", self.id)], order="name, version")
        notes = env["ea.audit.review.note"].sudo().search([("engagement_id", "=", self.id)], order="create_date, id")
        team = env["ea.audit.team.member"].sudo().search([("engagement_id", "=", self.id)], order="id")
        versions = documents.version_ids
        manifest = {
            "manifestVersion": 2,
            "generatedAt": stamp(fields.Datetime.now()),
            "engagement": {
                "id": self.id, "name": self.display_name, "client": client.name, "clientLegalForm": client.legal_form,
                "fiscalYear": self.fiscal_year, "periodEnd": day(self.period_end), "reportDate": day(self.report_date),
                "opinion": self.opinion, "framework": self.framework or client.framework, "firstYear": self.first_year,
                "complexity": self.complexity, "retentionUntil": day(self.retention_until),
            },
            "firm": {"name": company.name, "retentionYears": company.ea_retention_years},
            "archivedBy": who(env.user),
            "fileIndex": [{
                "id": item.id, "code": item.code, "section": item.section, "title": item.title,
                "conditional": item.conditional, "material": item.material, "notApplicable": item.not_applicable,
                "naReason": item.na_reason or None,
                "preparer": who(item.preparer_id), "assignee": who(item.assignee_id),
            } for item in items],
            "workingPapers": [{
                "code": a.code, "field": a.field_key, "value": a.value, "updatedAt": stamp(a.write_date), "updatedBy": who(self._ea_last_writer(a.code, a.field_key)),
            } for a in answers],
            "sectionConclusions": [{
                "code": c.code, "conclusion": c.conclusion, "objectivesAchieved": c.objectives_achieved,
                "preparedBy": who(c.prepared_by_id), "reviewedBy": who(c.reviewed_by_id), "partnerReviewedBy": who(c.partner_reviewed_by_id),
            } for c in conclusions],
            "signoffs": [{
                "code": s.code, "kind": s.kind, "role": s.role, "versionNo": s.version_no, "by": who(s.user_id),
                "signedAt": stamp(s.signed_at), "contentHash": s.content_hash, "voidedAt": stamp(s.voided_at),
                "voidReason": s.void_reason or None, "invalidatedAt": stamp(s.invalidated_at),
            } for s in signoffs],
            "documents": [{
                "id": d.id, "title": d.title, "kind": d.kind, "fileItemCode": d.code, "currentVersion": d.current_version,
                "versions": [{
                    "versionNo": v.version_no, "sha256": v.sha256, "bytes": v.byte_size, "note": v.note,
                    "createdAt": stamp(v.create_date), "createdBy": who(v.created_by_id),
                } for v in d.version_ids.sorted("version_no")],
            } for d in documents],
            "attachments": [{
                "name": a.name, "mime": a.mime, "bytes": a.size_bytes, "version": a.version, "uploadedAt": stamp(a.uploaded_at),
                "sha256": hashlib.sha256(a.attachment_id.raw or b"").hexdigest(), "deletedAt": stamp(a.deleted_at),
            } for a in attachments],
            "reviewNotes": [{
                "body": n.body, "status": n.state, "response": n.response or None, "raisedAt": stamp(n.create_date),
                "clearedAt": stamp(n.cleared_at), "author": who(n.author_id),
            } for n in notes],
            "materiality": [self._ea_materiality_dict()] if self._ea_materiality_dict() else [],
            "team": [{"name": who(m.user_id), "role": m.team_role, "status": m.state} for m in team],
            "risks": rows("ea.audit.risk", "description", "status", "significant", "rebutted", "rebuttal_justification", "added_after_planning"),
            "misstatements": rows("ea.audit.misstatement", "description", "accounts", "amount", "mtype", "corrected", "trivial"),
            "findings": rows("ea.audit.finding", "number", "route", "title", "detail", "severity", "status", "recommendation", "management_response"),
            "counts": {
                "fileItems": len(items), "documents": len(documents), "documentVersions": len(versions),
                "signoffs": len(signoffs), "attachments": len(attachments),
                "activityEntries": env["mail.message"].sudo().search_count([("model", "=", self._name), ("res_id", "=", self.id)]),
            },
        }
        extra = self._ea_manifest_extra()
        manifest.update(extra)
        return manifest

    def _ea_manifest_extra(self):
        """Later addons add their registers to the manifest here."""
        return {}

    def archive_engagement(self, late_reason=None):
        """archiveEngagement: gates, retention, manifest, sealed copy and lock, in one transaction.
        Any accepted team member with write rights may archive, not only the partner (owner,
        2026-11-16); the EQR stays independent and read-only. Past the 60 days, with the reason
        logged; the trail names who archived."""
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_access()
        if self._ea_acts_as_eqr(self.env.user):
            raise rule_error(self.env, "eqr-read-only")
        as_root = self.sudo()
        self.env.flush_all()
        self.env.cr.execute("SELECT report_date, archived_at FROM ea_audit_engagement WHERE id = %s FOR UPDATE", [self.id])
        report_date, archived_at = self.env.cr.fetchone()
        self.invalidate_recordset(["report_date", "archived_at"])
        if archived_at:
            raise rule_error(self.env, "already-archived")
        self._ea_raise_report_gates([gate["key"] for gate in as_root._ea_archive_gates() if not gate["ok"]])
        if not report_date:
            raise rule_error(self.env, "no-report")
        late = (late_reason or "").strip()
        if fields.Date.context_today(self) > assembly_deadline(report_date) and not late:
            raise rule_error(self.env, "late-archive-reason")
        # Fixed here, from the firm's period as it stands today, and before the manifest is built,
        # so a later change of the firm's setting cannot shorten the life of a closed file.
        years = self.env.company.sudo().ea_retention_years or RETENTION_MIN_YEARS
        as_root.retention_until = retention_until_sql(report_date.isoformat(), as_root.period_end.isoformat(), years)
        content = json.dumps(as_root._ea_manifest(), ensure_ascii=False, indent=2, default=str)
        raw = content.encode("utf-8")
        manifest = self.env["ea.audit.archive.manifest"].sudo().create({
            "engagement_id": self.id, "content": content, "sha256": hashlib.sha256(raw).hexdigest(),
            "archived_by_id": self.env.user.id,
        })
        self.env["ir.attachment"].sudo().create({
            "name": "archive-manifest-%s.json" % as_root.fiscal_year, "raw": raw, "mimetype": "application/json",
            "res_model": "ea.audit.archive.manifest", "res_id": manifest.id,
        })
        if late:
            self._ea_log("archive.late", "Archived after the assembly deadline. Reason: %s" % late)
        open_note = as_root._ea_open_late_work()
        if open_note:
            open_note.write({"closed_at": fields.Datetime.now(), "closed_by_id": self.env.user.id})
        as_root.with_env(self.env)._ea_build_seal(content)
        as_root.write({"phase": "archived", "archived_at": fields.Datetime.now()})
        self._ea_log("archive", "Audit file archived and locked by %s" % self.env.user.name)
        # Everyone on the file hears it closed. Never an email; a failure must not undo the archive.
        members = self.env["ea.audit.team.member"].sudo().search([("engagement_id", "=", self.id)]).user_id
        as_root._ea_notify(
            members, "engagement_archived", lambda env: env._("Engagement archived"),
            lambda env: env._("The file is frozen: no further change is possible. It remains available and can be rolled forward from the list of archived engagements."),
        )
        return manifest

    def action_archive_file(self):
        """The archive asks for the client's name: it is done on the C6.2 page."""
        self.ensure_one()
        return self.action_tool_archive()

    # ------------------------------------------------------------------
    # Retention and legal hold
    # ------------------------------------------------------------------

    def _ea_active_hold(self):
        self.ensure_one()
        return self.env["ea.audit.legal.hold"].sudo().search(
            [("engagement_id", "=", self.id), ("released_at", "=", False)], limit=1,
        )

    def active_hold(self):
        self.ensure_one()
        self._ea_require_access()
        return self._ea_active_hold()

    def list_holds(self):
        """Every hold ever placed, newest first: released ones are history, not noise."""
        self.ensure_one()
        self._ea_require_access()
        return self.env["ea.audit.legal.hold"].sudo().search([("engagement_id", "=", self.id)])

    def _ea_hold_guard(self, minimum, code):
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_access()
        if not at_least(self.env.user._ea_firm_role(), minimum):
            raise rule_error(self.env, code)

    def place_legal_hold(self, reason):
        """Manager and above: the person who hears of a dispute is usually not the partner. Stays
        open on an archived file: a hold is worth most there."""
        self._ea_hold_guard("manager", "requires-manager")
        text = (reason or "").strip()
        if not text:
            raise rule_error(self.env, "reason-required")
        self.env.cr.execute("SELECT id FROM ea_audit_engagement WHERE id = %s FOR UPDATE", [self.id])
        if self._ea_active_hold():
            raise rule_error(self.env, "already-held")
        hold = self.env["ea.audit.legal.hold"].sudo().create({
            "engagement_id": self.id, "reason": text, "placed_by_id": self.env.user.id,
        })
        self._ea_log("legal_hold.placed", "Legal hold placed, retention expiry suspended. Reason: %s" % text)
        return hold

    def release_legal_hold(self, reason):
        """Partner only: releasing is the act that lets a file become destructible."""
        self._ea_hold_guard("partner", "requires-partner")
        text = (reason or "").strip()
        if not text:
            raise rule_error(self.env, "reason-required")
        hold = self._ea_active_hold()
        if not hold:
            raise rule_error(self.env, "no-active-hold")
        hold.write({"released_at": fields.Datetime.now(), "released_by_id": self.env.user.id, "release_reason": text})
        self._ea_log("legal_hold.released", "Legal hold released, retention expiry resumes. Reason: %s" % text)
        return True

    @api.model
    def retention_report(self):
        """retentionReport (UAT B65): the firm's archived files, what may be destroyed and what must
        be kept. Manager and above, like the source, whatever the team."""
        if not at_least(self.env.user._ea_firm_role(), "manager"):
            raise rule_error(self.env, "requires-manager")
        today = fields.Date.context_today(self).isoformat()
        rows = []
        files = self.sudo().search([("archived_at", "!=", False)]).sorted(
            lambda e: (e.retention_until or fields.Date.to_date("9999-12-31"), e.client_id.name, e.fiscal_year)
        )
        for engagement in files:
            held = bool(engagement._ea_active_hold())
            until = engagement.retention_until.isoformat() if engagement.retention_until else None
            rows.append({
                "engagement_id": engagement.id, "client": engagement.client_id.name, "fiscal_year": engagement.fiscal_year,
                "archived_at": french_date(engagement.archived_at), "retention_until": french_date(engagement.retention_until),
                "held": held, "due_for_destruction": due_for_destruction(until, held, today),
            })
        return rows

    @api.model
    def set_retention_years(self, years):
        """Only files archived from here on are affected."""
        if self.env.user._ea_firm_role() != "firm_admin":
            raise rule_error(self.env, "requires-firm-admin")
        if not isinstance(years, int) or isinstance(years, bool) or not RETENTION_MIN_YEARS <= years <= RETENTION_MAX_YEARS:
            raise rule_error(self.env, "retention-out-of-range")
        self.env.company.sudo().ea_retention_years = years
        return years

    # ------------------------------------------------------------------
    # Export bundle
    # ------------------------------------------------------------------

    def _ea_trail_rows(self):
        return [
            {"at": fields.Datetime.to_string(m.date), "by": m.author_id.name or m.email_from, "body": m.body and re.sub(r"<[^>]+>", "", str(m.body))}
            for m in self.env["mail.message"].sudo().search([("model", "=", self._name), ("res_id", "=", self.id)], order="date, id")
        ]

    def _ea_bundle_file_index(self):
        """The regulator's status index: a real workbook of the tasks and who signed them."""
        from openpyxl import Workbook

        book = Workbook(write_only=True)
        sheet = book.create_sheet("Index")
        sheet.append(["Code", "Task", "State", "Not applicable", "Reason", "Prepared", "Reviewed"])
        for row in self._ea_item_activity():
            item = row["item"]
            sheet.append([
                item.code, item.title, item.state, "yes" if item.not_applicable else "", item.na_reason or "",
                "yes" if row["prepared"] else "", "yes" if row["reviewed"] else "",
            ])
        buffer = io.BytesIO()
        book.save(buffer)
        return "file-index-%s.xlsx" % self.fiscal_year, buffer.getvalue()

    def _ea_bundle_conclusion(self):
        """60-conclusion: the registers an inspection asks for, one JSON each."""
        return {
            "completion-records": [
                {"key": r.key, "data": r.data, "doneBy": r.done_by_id.name, "doneAt": fields.Datetime.to_string(r.done_at)}
                for r in self.completion_record_ids
            ],
            "legal-holds": [
                {"reason": h.reason, "placedBy": h.placed_by_id.name, "placedAt": fields.Datetime.to_string(h.placed_at),
                 "releasedAt": fields.Datetime.to_string(h.released_at) if h.released_at else None, "releaseReason": h.release_reason or None}
                for h in self.legal_hold_ids
            ],
            "findings": [
                {"number": f.number, "route": f.route, "title": f.title, "severity": f.severity or None, "status": f.status}
                for f in self.finding_ids
            ],
            "misstatements": [
                {"description": m.description, "amount": m.amount, "corrected": m.corrected, "trivial": m.trivial}
                for m in self.misstatement_ids
            ],
        }

    def export_engagement_bundle(self):
        """exportEngagementBundle: the complete file as a ZIP on disk, built one artefact at a time.
        Any team member may take it; every export is logged (I-9). Returns (filename, file object),
        and the caller closes the file."""
        self.ensure_one()
        self._ea_require_access()
        as_root = self.sudo()
        client = as_root.client_id
        slug = re.sub(r"[^a-z0-9]+", "-", (client.name or "engagement").lower()).strip("-")
        filename = "auditisa-export-%s-FY%s-%d.zip" % (slug, as_root.fiscal_year, self.id)
        stamp = (as_root.archived_at or fields.Datetime.now()).timetuple()[:6]
        handle = tempfile.NamedTemporaryFile(suffix=".zip")
        recorded = []
        with zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:

            def put(path, body):
                info = zipfile.ZipInfo(path, date_time=stamp)
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, body)
                recorded.append({"path": path, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})

            def put_json(path, value):
                put(path, (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8"))

            put_json("00-index/engagement.json", {
                "id": self.id, "name": as_root.display_name, "client": client.name, "firm": self.env.company.name,
                "fiscalYear": as_root.fiscal_year, "periodEnd": as_root.period_end, "reportDate": as_root.report_date,
                "opinion": as_root.opinion, "phase": as_root.phase, "archivedAt": as_root.archived_at,
                "retentionUntil": as_root.retention_until,
                # stated plainly: an unarchived file is a point-in-time copy whose contents can still change
                "complete": bool(as_root.archived_at),
            })
            name, content = as_root._ea_bundle_file_index()
            put("00-index/%s" % name, content)
            for paper in self.env["ea.audit.paper"].sudo().search([("engagement_id", "=", self.id)], order="code"):
                values = paper._ea_values()
                if values:
                    put_json("10-working-papers/%s/paper.json" % paper.code, {"code": paper.code, "answers": values})
            for conclusion in self.env["ea.audit.section.conclusion"].sudo().search([("engagement_id", "=", self.id)]):
                put_json("10-working-papers/%s/conclusion.json" % conclusion.code, {
                    "conclusion": conclusion.conclusion, "objectivesAchieved": conclusion.objectives_achieved,
                    "reviewedBy": conclusion.reviewed_by_id.name or None,
                })
            for attachment in self.env["ea.audit.task.attachment"].sudo().search([("engagement_id", "=", self.id), ("deleted_at", "=", False)]):
                put("10-working-papers/%s/_attachments/v%d %s" % (attachment.code, attachment.version, attachment.name), attachment.attachment_id.raw or b"")
            for document in as_root.document_ids.sorted("id").filtered(
                lambda d: not d.restricted or can_partner_signoff(self.env.user._ea_firm_role())
            ):
                folder = "20-documents/%s/%d" % (document.code, document.id)
                put_json("%s/versions.json" % folder, [
                    {"version": v.version_no, "sha256": v.sha256, "note": v.note, "bytes": v.byte_size}
                    for v in document.version_ids.sorted("version_no")
                ])
                for version in document.version_ids.sorted("version_no"):
                    extension = (version.attachment_id.name or "x.bin").rsplit(".", 1)[-1]
                    put("%s/v%d.%s" % (folder, version.version_no, extension), version.attachment_id.raw or b"")
            for section, rows in as_root._ea_bundle_conclusion().items():
                put_json("60-conclusion/%s.json" % section, rows)
            manifest = self.env["ea.audit.archive.manifest"].sudo().search([("engagement_id", "=", self.id)], limit=1)
            if manifest:
                put("60-conclusion/archive-manifest.json", manifest.content.encode("utf-8"))
            put("70-audit-trail/activity.jsonl", ("\n".join(
                json.dumps(row, ensure_ascii=False) for row in as_root._ea_trail_rows()
            ) + "\n").encode("utf-8"))
            put_json("80-people/team.json", [
                {"name": m.user_id.name, "role": m.team_role, "status": m.state} for m in as_root.team_member_ids
            ])
            put_json("80-people/signoffs.json", [
                {"code": s.code, "role": s.role, "by": s.user_id.name, "signedAt": s.signed_at, "contentHash": s.content_hash,
                 "voidedAt": s.voided_at, "invalidatedAt": s.invalidated_at}
                for s in self.env["ea.audit.signoff"].sudo().search([("engagement_id", "=", self.id)], order="signed_at, id")
            ])
            put_json("manifest.json", {"files": recorded, "complete": bool(as_root.archived_at)})
            put("SHA256SUMS", "".join("%s  %s\n" % (row["sha256"], row["path"]) for row in recorded).encode("utf-8"))
        handle.seek(0)
        self._ea_log("export_bundle", "Engagement export taken: %s" % filename)
        return filename, handle

    def action_export_bundle(self):
        self.ensure_one()
        self._ea_require_access()
        return {"type": "ir.actions.act_url", "target": "self", "url": "/ea_audit/engagement/%d/export" % self.id}

    # ------------------------------------------------------------------
    # Screens
    # ------------------------------------------------------------------

    def action_tool_conclusion(self):
        return self.action_open_conclusion()

    def action_open_conclusion(self):
        self.ensure_one()
        return self._ea_board("ea_audit_reports.view_engagement_conclusion_form", self.env._("Conclusion and archive"))

    def action_open_completion_wizard(self):
        self.ensure_one()
        key = self.env.context.get("completion_key")
        return {
            "type": "ir.actions.act_window", "res_model": "ea.audit.completion.wizard", "view_mode": "form", "views": [(False, "form")], "target": "new",
            "name": self.env._("Completion record"),
            "context": {"default_engagement_id": self.id, "default_key": key},
        }

    def action_open_issue_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "ea.audit.issue.report.wizard", "view_mode": "form", "views": [(False, "form")], "target": "new",
            "name": self.env._("Issue the report"), "context": {"default_engagement_id": self.id},
        }

    def action_open_hold_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "ea.audit.hold.wizard", "view_mode": "form", "views": [(False, "form")], "target": "new",
            "name": self.env._("Legal hold"),
            "context": {"default_engagement_id": self.id, "default_mode": "release" if self.held else "place"},
        }

    def action_view_documents(self):
        self.ensure_one()
        return self._ea_list(
            "ea.audit.document", self.env._("Letters and reports"),
            [("ea_audit_reports.view_document_list", "list"), ("ea_audit_reports.view_document_form", "form")],
        )


class Paper(models.Model):
    _inherit = "ea.audit.paper"

    def _ea_tieout_failed(self):
        """E6.10: "column N agrees" cannot be Yes while the tie-out shows unexplained differences."""
        result = self.sudo().engagement_id._ea_fs_tieout()
        return bool(result["cr"]) and not result["pass"]


class FileItem(models.Model):
    _inherit = "ea.audit.file.item"

    def ea_paper_board(self):
        """E6.10 fronts the tie-out: the same figures as the conclusion board."""
        board = super().ea_paper_board()
        item = self.sudo()
        if item.code in ("C6.1", "C6.2"):
            # the paper fronts its page: the checklist before the report, the archive after it
            engagement = item.engagement_id.with_env(self.env)
            board["facts"], board["head"], board["rows"] = [], [], []
            board["links"] = [
                {"label": self.env._("Completion checklist"), "action": engagement.action_tool_checklist()},
                {"label": self.env._("Assemble and archive"), "action": engagement.action_tool_archive()},
            ]
            return board
        if item.code != "E6.10" or not item.engagement_id._ea_tb_balances():
            return board
        result = item.engagement_id._ea_fs_tieout()
        _ = self.env._
        board["facts"] = [
            {"label": _("Net result (income statement)"), "value": "%s FCFA" % grouped(result["crResult"])},
            {"label": _("Tie-out"), "value": _("Passed") if result["pass"] else _("Differences")},
        ]
        board["head"] = [_("Reference"), _("Caption"), _("Amount")]
        board["rows"] = [
            [line["ref"], _(line["label"]), grouped(line["amount"])]
            for line in result["cr"] if line["ref"].startswith("X")
        ]
        return board
