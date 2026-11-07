import logging

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.errors import AuditRuleError, rule_error
from odoo.addons.ea_audit_core.services.signoff_rules import EQR_PAPER, can_review, can_write

from ..services import (
    EQR_C42_KEYS,
    StaleEdit,
    all_paper_keys,
    answer_changed,
    base_digests,
    completeness_exempt,
    default_definition,
    digest,
    group_siblings,
    has_bespoke_paper,
    is_blank,
    load_definition,
    missing_parts,
    norm_text,
    paper_missing,
    paper_progress,
    persons_on_save,
    plan_save,
    resolve_definition,
    same_answer,
)
from ..services.completeness import EMBED_ONLY_PAPERS
from odoo.addons.ea_audit_core.services.conditional_triggers import S61_TRIGGERS

from .engagement import _EQR_DETERMINATION
from .errors import paper_error
from .paper_answer import ANSWER_DOOR

_logger = logging.getLogger(__name__)

# English source of the stored reason; the paper's readers get it through fr.po.
SIGNOFF_INVALIDATED_REASON = "Paper content changed after sign-off"
CONTENT_SCHEME = 2
TZ = "Africa/Douala"

# app/engagements/[id]/sections/[itemId]/page.tsx. The E4 line is the mock-up's rail: the
# platform shows none on account tasks.
CROSS_LINKS = {
    "P1.1": ["P1.2", "P2.1"], "P2.1": ["P1.1", "P1.5"], "P1.2": ["P1.1", "E6.5"],
    "P1.5": ["P2.1", "C4.2"], "P6.1": ["C1.1", "S3.1"], "S4.1": ["E6.9"],
    "P5.1": ["E3.1", "E4.1"], "S4.2": ["E6.3", "C2.2"], "S4.3": ["E6.2"], "S4.4": ["E6.7"],
    "S3.1": ["P5.1", "E1.1"], "C1.1": ["P6.1", "C1.2"], "C2.2": ["E6.6", "E6.3", "C5.1"],
    "E6.3": ["S4.2", "C2.2", "C5.1", "C5.11"],
    "S1.1": ["P6.2", "S1.2"], "S1.2": ["S1.3", "E1.1"], "S1.3": ["S1.2", "E1.1"], "S1.4": ["E3.1", "C2.1"],
    "S2.1": ["S2.2", "E1.1"], "S2.2": ["E1.1", "S3.1"], "S5.1": ["P2.2"], "S5.2": ["P4.3"], "S5.3": ["E1.1"],
    "S6.1": ["P7.2", "P6.1", "S3.1"], "S6.2": ["P7.2", "S6.1"],
    "C3.1": ["C1.1", "E6.9"], "C4.2": ["P1.5", "C5.11"], "C5.1": ["C1.1", "C2.2", "C4.2", "C5.11"],
    "C5.11": ["C1.2", "C1.1", "C4.2", "C5.1", "P7.1"],
    "C4.1": ["C4.3", "C6.1"], "C1.2": ["C1.1", "C1.3"], "C5.3": ["E6.2"], "C5.8": ["E4.9", "E6.3"],
    "E6.2": ["S4.3", "C5.3"], "E6.7": ["S4.4"],
}
E4_LINKS = ["S3.1", "C1.1", "E6.9"]

# Task header chips. ea_audit_tools adds where each one goes, by overriding _ea_tool_links.
TOOL_LABELS = {
    "P6.1": ("Materiality tool", "Outil de matérialité"),
    "P6.2": ("Materiality tool", "Outil de matérialité"),
    "C1.1": ("SAD tool", "Outil SAD"),
    "S3.1": ("Risk register", "Registre des risques"),
    "P3.2": ("Analytical procedures", "Procédures analytiques"),
    "C5.2": ("Legal tool, statutory calendar", "Outil juridique, calendrier légal"),
    "C5.3": ("Legal tool, regulated agreements register", "Outil juridique, registre des conventions"),
    "C5.4": ("Legal tool, article 715 report", "Outil juridique, rapport article 715"),
    "C5.5": ("Legal tool, alert procedure", "Outil juridique, procédure d'alerte"),
    "C5.6": ("Legal tool, criminal facts", "Outil juridique, faits délictueux"),
    "C5.7": ("Legal tool, securities attestation", "Outil juridique, attestation titres"),
    "C5.8": ("Legal tool, equity monitor", "Outil juridique, suivi des capitaux propres"),
}
LEAD_SCHEDULES = ("Lead schedules", "Feuilles maîtresses")


class Paper(models.Model):
    """The task's paper, one per file item (spec D.12): it takes over `document`."""

    _name = "ea.audit.paper"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Working paper"
    _order = "engagement_id, id"
    _rec_name = "code"

    file_item_id = fields.Many2one("ea.audit.file.item", string="Task", required=True, index=True, ondelete="restrict")
    engagement_id = fields.Many2one(related="file_item_id.engagement_id", store=True, index=True)
    code = fields.Char(related="file_item_id.code", store=True, index=True)
    state = fields.Selection(
        [("draft", "Draft"), ("signed", "Signed")], compute="_compute_state", store=True, default="draft",
    )
    answer_version = fields.Integer(default=0, help="Moves with every change of an answer: the optimistic lock.")
    answer_ids = fields.One2many("ea.audit.paper.answer", "paper_id", string="Answers")
    history_ids = fields.One2many("ea.audit.paper.answer.history", "paper_id", string="Answer history")
    signoff_ids = fields.One2many(related="file_item_id.signoff_ids", string="Sign-offs")

    _file_item_uniq = models.Constraint("UNIQUE(file_item_id)", "A task has one paper.")

    @api.depends("file_item_id.state")
    def _compute_state(self):
        for paper in self:
            paper.state = "signed" if paper.file_item_id.state == "signed" else "draft"

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def _ea_values(self):
        self.ensure_one()
        return {answer.field_key: answer.value or "" for answer in self.sudo().answer_ids}

    def _ea_unresolved(self):
        self.ensure_one()
        row = self.env["ea.audit.paper.def"]._ea_current(self.code)
        if row:
            return row.definition
        return load_definition(self.code) if has_bespoke_paper(self.code) else default_definition(self.code)

    def _ea_resolved(self):
        """The paper as this file reads it. Edition and form are read each time."""
        self.ensure_one()
        engagement = self.sudo().engagement_id
        return resolve_definition(self._ea_unresolved(), engagement.standards_edition, engagement.client_id.legal_form)

    # ------------------------------------------------------------------
    # What a signature attests to
    # ------------------------------------------------------------------

    def _content_parts(self):
        """The named parts of the hash, in order. ea_audit_tools extends this per code
        (CRA, SCOT and the rest), and any writer of a part it adds calls
        _void_stale_signoffs itself. Blanks are left out: a save that adds an empty key
        says nothing (Q4)."""
        self.ensure_one()
        paper = self.sudo()
        fields_part = sorted(
            [answer.field_key, norm_text(answer.value)]
            for answer in paper.answer_ids
            if not is_blank(answer.value)
        )
        conclusion = paper.env["ea.audit.section.conclusion"].search([("file_item_id", "=", paper.file_item_id.id)], limit=1)
        evidence = paper.env["ea.audit.task.attachment"].search(
            [("file_item_id", "=", paper.file_item_id.id), ("deleted_at", "=", False)]
        )
        return {
            "fields": fields_part,
            "section_conclusion": (
                {"conclusion": conclusion.conclusion or "", "objectives_achieved": conclusion.objectives_achieved}
                if conclusion else None
            ),
            "attachments": sorted([att.name, att.version, att.checksum or ""] for att in evidence),
        }

    def _content_hash(self):
        return digest({"scheme": CONTENT_SCHEME, "parts": self._content_parts()})

    def _ea_active_signoffs(self):
        return self.sudo().signoff_ids.filtered(
            lambda s: s.kind == "workpaper" and not s.voided_at and not s.invalidated_at
        )

    def _void_stale_signoffs(self):
        """invalidateStaleSignoffs. The row stays and records why. A signature with no hash
        (or a migrated one Odoo cannot recompute, Q3) is never voided by comparison, and a
        changed wording never voids (Q1). Returns the voided rows."""
        self.ensure_one()
        paper = self.sudo()
        current = paper._content_hash()
        stale = paper._ea_active_signoffs().filtered(
            lambda s: s.content_hash and s.content_scheme == CONTENT_SCHEME and s.content_hash != current
        )
        if not stale:
            return stale
        now = fields.Datetime.now()
        stale.write({
            "invalidated_at": now, "invalidated_reason": SIGNOFF_INVALIDATED_REASON,
            "voided_at": now, "void_reason": SIGNOFF_INVALIDATED_REASON,
        })
        cleared = False
        if set(stale.mapped("role")) & {"reviewer", "partner"}:
            # A voided review voids the conclusion's review with it (UAT run 3 B05).
            cleared = paper.env["ea.audit.section.conclusion"]._ea_clear_reviews(paper.file_item_id)
        paper._ea_restate_after_void()
        paper._ea_report_voided(stale, cleared)
        return stale

    def _ea_restate_after_void(self):
        item = self.sudo().file_item_id
        roles = set(self._ea_active_signoffs().mapped("role"))
        rule = self.env["ea.audit.signoff.policy"].sudo()._ea_effective_rule(item.code)
        if "partner" in roles or ("reviewer" in roles and not rule["partner_required"]):
            item.state = "signed"
        elif "reviewer" in roles:
            item.state = "reviewed"
        elif "preparer" in roles:
            item.state = "prepared"
        else:
            item.state = "in_progress"

    def _ea_trail(self, action, summary):
        """The trail must not take the edit down with it."""
        try:
            with self.env.cr.savepoint():
                self.sudo().engagement_id.with_env(self.env)._ea_log(action, summary)
        except Exception:
            _logger.exception("Trail entry lost: %s %s", action, summary)

    def _ea_notify_users(self, users, summary, note):
        """In-app only: an activity on the paper, with no mail (quick_update skips it)."""
        paper = self.sudo().with_context(mail_activity_quick_update=True)
        for user in users:
            if user == self.env.user:
                continue
            reader = self.with_context(lang=user.sudo().lang or self.env.lang).env
            try:
                with self.env.cr.savepoint():
                    paper.activity_schedule(
                        "mail.mail_activity_data_todo", user_id=user.id,
                        summary=summary(reader) if callable(summary) else summary,
                        note=note(reader) if callable(note) else note,
                    )
            except Exception:
                _logger.exception("Notification lost for user %s on paper %s", user.id, self.id)

    def _ea_report_voided(self, rows, conclusion_review_cleared):
        self.ensure_one()
        roles = ", ".join(rows.mapped("role"))
        self._ea_trail("signoff_invalidated", "%s signature(s) voided after the paper changed: %s" % (self.code, roles))
        if conclusion_review_cleared:
            self._ea_trail("section_conclusion_review_cleared", "%s conclusion review cleared with the voided signature" % self.code)
        self._ea_notify_users(
            rows.user_id,
            lambda env: env._("%(code)s: signature voided", code=self.code),
            lambda env: env._("Paper content changed after sign-off"),
        )

    # ------------------------------------------------------------------
    # The one door for writes
    # ------------------------------------------------------------------

    def _ea_filter_write(self, values):
        """filterPaperWrite: the EQR writes nothing on the team's papers. On C4.2 where a
        review is required, the reviewer's part is the appointed reviewer's alone and the
        reviewer writes nothing else."""
        self.ensure_one()
        engagement = self.sudo().engagement_id
        user = self.env.user
        if self.code != EQR_PAPER:
            if engagement._ea_acts_as_eqr(user):
                raise paper_error(self.env, "eqr-read-only")
            return values
        appointed = bool(engagement._ea_is_appointed_eqr(user))
        if not appointed and user._ea_firm_role() == "eqr_reviewer":
            raise paper_error(self.env, "eqr-own-paper")
        if not appointed and not engagement._ea_eqr_required():
            return values
        stored = self._ea_values()
        allowed = all_paper_keys(self._ea_unresolved())
        out = {}
        for key, value in values.items():
            if key not in allowed:
                continue
            if appointed == (key in EQR_C42_KEYS):
                out[key] = value
            elif not same_answer(stored.get(key, ""), value):
                raise paper_error(self.env, "eqr-read-only" if appointed else "eqr-own-paper")
        return out

    def _ea_locked_keys(self):
        """What this user sees but cannot change on C4.2."""
        self.ensure_one()
        if self.code != EQR_PAPER:
            return []
        engagement = self.sudo().engagement_id
        appointed = bool(engagement._ea_is_appointed_eqr(self.env.user))
        if not appointed and not engagement._ea_eqr_required():
            return []
        allowed = all_paper_keys(self._ea_unresolved())
        return sorted(k for k in allowed if appointed != (k in EQR_C42_KEYS))

    def _ea_refuse_contradictions(self, values):
        """Per-code refusals: the typed text stays with the user, nothing is stored."""
        self.ensure_one()
        if self.code == "E6.10" and values.get("q_n_agrees") == "yes":
            explained = values.get("p_tie_n")
            if explained is None:
                explained = self._ea_values().get("p_tie_n", "")
            if self._ea_tieout_failed() and is_blank(explained):
                raise paper_error(self.env, "tieout-unexplained")
        if self.code == "C5.8" and values.get("q_above") == "yes" and self._ea_equity_breach():
            raise paper_error(self.env, "c58-equity-contradicts")

    # Extension points of ea_audit_tools. No tool yet, so no figures to contradict.
    def _ea_tieout_failed(self):
        """E6.10: runFsTieout shows differences."""
        return False

    def _ea_equity_breach(self):
        """C5.8: equityStatus shows a breach on live figures."""
        return False

    def _ea_sync_seeded_response_step(self):
        """E3.1: its conclusions complete or reopen the seeded management-override step."""

    def _ea_auto_values(self):
        """Auto fields, filled from the tools and never saved."""
        return {}

    def _ea_tool_links(self):
        """The header chips: label and, once the tool exists, the action it opens."""
        self.ensure_one()
        labels = TOOL_LABELS.get(self.code)
        if not labels and self.code.startswith("E4."):
            labels = LEAD_SCHEDULES
        return [{"en": labels[0], "fr": labels[1], "action": None}] if labels else []

    def _ea_after_save(self, values):
        """savePaper's side effects, inside the save's transaction."""
        self.ensure_one()
        engagement = self.sudo().engagement_id
        self._ea_sync_seeded_response_step()
        if self.code == "P1.1" and ("engagement_type" in values or "auditor_change" in values):
            stored = self._ea_values()
            engagement._ea_set_predecessor_active(
                stored.get("engagement_type") == "new" or stored.get("auditor_change") == "yes"
            )
        if self.code == "P1.5" and any(values.get(key) == "yes" for key in _EQR_DETERMINATION):
            engagement._ea_ensure_task(EQR_PAPER)
        if self.code == "S6.1":
            for key, code in S61_TRIGGERS.items():
                if key in values:
                    engagement._ea_set_task_active(code, values[key] == "yes")

    def save_answers(self, values, base_version=None, base_digests=None):
        """The port of savePaper; see DESIGN section 2 for the order. Returns what was
        stored and what was held back: {"written", "conflicts", "voided", "version"}.
        A conflict is {key: {"mine": text, "theirs": text}}: the rest is saved and the
        user keeps their text. Refusals raise AuditRuleError and store nothing."""
        self.ensure_one()
        env = self.env
        Engagement = env["ea.audit.engagement"]
        paper = self.sudo()
        if not paper.exists():
            raise paper_error(env, "not-found")
        engagement = paper.engagement_id
        engagement.with_env(env)._ea_require_access()
        engagement.with_env(env)._ea_assert_mutable()
        Engagement._ea_require_write()
        values = {key: ("" if value is None else str(value)) for key, value in (values or {}).items()}
        values = self.with_env(env)._ea_filter_write(values)

        allowed = all_paper_keys(paper._ea_unresolved())
        if paper.code == "C5.10":
            persons = persons_on_save(paper._ea_values(), values)
            if persons:
                values["persons"] = persons
        self.with_env(env)._ea_refuse_contradictions(values)

        # The row lock serialises saves of this paper. Under repeatable read a colleague's
        # commit makes this a serialization failure, and Odoo replays the call with a fresh
        # snapshot, which is when the version below sees the difference.
        env.cr.execute("SELECT id FROM ea_audit_paper WHERE id = %s FOR UPDATE", [paper.id])
        paper.invalidate_recordset()
        stale = base_version is not None and int(base_version) != paper.answer_version
        answers = {answer.field_key: answer for answer in paper.answer_ids}
        stored = {key: answer.value or "" for key, answer in answers.items()}
        try:
            writes, conflicts = plan_save(values, allowed, stored, base_digests, stale)
        except StaleEdit:
            raise paper_error(env, "stale-edit") from None

        door = env["ea.audit.paper.answer"].sudo().with_context(**{ANSWER_DOOR: True})
        history = []
        for key, value in writes.items():
            answer = answers.get(key)
            before = stored.get(key, "")
            if not answer_changed(before, value):
                # posting a carried-forward text back unchanged makes it this year's answer
                if answer and answer.carried_forward:
                    door.browse(answer.id).carried_forward = False
                continue
            if answer:
                door.browse(answer.id).write({"value": value, "carried_forward": False})
            else:
                door.create({"paper_id": paper.id, "field_key": key, "value": value})
            history.append({
                "paper_id": paper.id, "field_key": key,
                "before": before or False, "after": value if not is_blank(value) else False,
                "user_id": env.user.id,
            })
        if history:
            env["ea.audit.paper.answer.history"].sudo().create(history)
            # the firm's audit log (F027) keeps the same full text, whoever reads it
            env["ea.audit.activity"].sudo().create([
                env["ea.audit.activity"]._ea_vals(
                    engagement, "answer_changed" if row["after"] else "answer_cleared",
                    "%s: answer %s" % (paper.code, "changed" if row["after"] else "cleared"),
                    code=paper.code, field_key=row["field_key"], before=row["before"], after=row["after"],
                )
                for row in history
            ])
            paper.answer_version += 1
            if paper.file_item_id.state == "not_started":
                paper.file_item_id.state = "in_progress"
        paper.invalidate_recordset(["answer_ids"])
        paper._ea_after_save(writes)
        voided = paper.with_env(env)._void_stale_signoffs()
        written = [row["field_key"] for row in history]
        if written:
            self.with_env(env)._ea_trail(
                "paper_saved", "%s working paper saved: %s" % (paper.code, ", ".join(sorted(written))),
            )
        return {
            "written": written,
            "conflicts": {key: {"mine": value, "theirs": stored.get(key, "")} for key, value in conflicts.items()},
            "voided": voided.mapped("role"),
            "version": paper.answer_version,
        }

    def _ea_carry_forward_answers(self, values):
        """The named door of roll-forward: no history, marked carried forward, and nothing
        that voids a signature."""
        self.ensure_one()
        door = self.env["ea.audit.paper.answer"].sudo().with_context(**{ANSWER_DOOR: True})
        for key, value in values.items():
            door.create({"paper_id": self.id, "field_key": key, "value": value, "carried_forward": True})

    # ------------------------------------------------------------------
    # The renderer's one payload
    # ------------------------------------------------------------------

    def _ea_date(self, value, with_time=False):
        if not value:
            return False
        local = fields.Datetime.context_timestamp(self.with_context(tz=TZ), value)
        return local.strftime("%d/%m/%Y %H:%M" if with_time else "%d/%m/%Y")

    def _ea_sign_chip(self, role, active):
        """One P/R/A/EQR chip: who signed, or whether this user may, and if not why. The
        reason comes from running core's own chain without its final write, so that the
        chip and the server cannot disagree."""
        self.ensure_one()
        signature = active.filtered(lambda s: s.role == role)[:1]
        if signature:
            item = self.sudo().file_item_id
            assigned = {
                "preparer": item.preparer_id or item.assignee_id,
                "reviewer": item.approver_id,
            }.get(role)
            return {
                "role": role, "state": "signed", "by": signature.user_id.name,
                "date": self._ea_date(signature.signed_at),
                "non_assignee": bool(assigned and assigned != signature.user_id),
                "definition_changed": bool(
                    signature.definition_hash
                    and signature.definition_hash != self.env["ea.audit.paper.def"]._ea_current(self.code).definition_hash
                ),
            }
        item = self.file_item_id.with_env(self.env).with_context(ea_sign_dry_run=True)
        try:
            recorded = item.action_sign(role)
        except AuditRuleError as error:
            suffix = " [%s]" % error.code
            message = error.args[0]
            return {
                "role": role, "state": "refused", "code": error.code,
                "reason": message[: -len(suffix)] if message.endswith(suffix) else message,
            }
        return {"role": role, "state": "open", "recorded": recorded}

    def _ea_signing_payload(self):
        self.ensure_one()
        sudo_self = self.sudo()
        item = sudo_self.file_item_id
        env = self.env
        rule = env["ea.audit.signoff.policy"].sudo()._ea_effective_rule(item.code)
        active = sudo_self._ea_active_signoffs()
        roles = ["preparer", "reviewer"]
        if rule["partner_required"] or "partner" in active.mapped("role"):
            roles.append("partner")
        if item.code == EQR_PAPER:
            roles.append("eqr")
        all_rows = sudo_self.signoff_ids.filtered(lambda s: s.kind == "workpaper")
        member = sudo_self.engagement_id._ea_member(env.user)
        return {
            "chips": [self._ea_sign_chip(role, active) for role in roles],
            "voided": [
                {
                    "role": row.role, "by": row.user_id.name, "date": self._ea_date(row.voided_at),
                    "reason": self.env._(row.void_reason) if row.void_reason else "",
                }
                for row in all_rows.filtered(lambda s: s.voided_at)
            ],
            "rule": {
                "min_preparer": rule["min_preparer"], "min_reviewer": rule["min_reviewer"],
                "partner_required": bool(rule["partner_required"]),
            },
            "my_team_role": member.team_role if member else False,
        }

    def _ea_linked_tasks(self):
        self.ensure_one()
        wanted = list(CROSS_LINKS.get(self.code, E4_LINKS if self.code.startswith("E4.") else []))
        for code in group_siblings(self.code):
            if code not in wanted:
                wanted.append(code)
        wanted = wanted[:6]
        items = self.env["ea.audit.file.item"].sudo().with_context(self.env.context).search(
            [("engagement_id", "=", self.sudo().engagement_id.id), ("code", "in", wanted)]
        )
        by_code = {item.code: item for item in items}
        return [
            {"id": by_code[code].id, "code": code, "title": by_code[code].short_title or by_code[code].title}
            for code in wanted if code in by_code
        ]

    def get_payload(self):
        """DESIGN section 7. The client shows what this says and decides nothing."""
        self.ensure_one()
        env = self.env
        paper = self.sudo()
        if not paper.exists():
            raise paper_error(env, "not-found")
        engagement = paper.engagement_id
        engagement.with_env(env)._ea_require_access()
        item = paper.file_item_id.with_context(env.context)
        user = env.user
        firm_role = user._ea_firm_role()
        definition = paper._ea_resolved()
        values = paper._ea_values()
        readonly_code = False
        if engagement._ea_is_archived():
            readonly_code = "archived"
        elif firm_role == "read_only" or not firm_role:
            readonly_code = "read-only-role"
        elif engagement._ea_acts_as_eqr(user) and paper.code != EQR_PAPER:
            readonly_code = "eqr-read-only"
        exempt = completeness_exempt(paper.code, has_bespoke_paper(paper.code))
        latest = paper.answer_ids.sorted("write_date", reverse=True)[:1]
        return {
            "paper_id": paper.id,
            "file_item_id": item.id,
            "engagement_id": engagement.id,
            "code": paper.code,
            "title": item.title,
            "short_title": item.short_title or item.title,
            "section": item.section,
            "client": engagement.client_id.name,
            "fiscal_year": engagement.fiscal_year,
            "edition": engagement.standards_edition,
            "state": paper.state,
            "item_state": item.state,
            "definition": definition,
            "values": values,
            "digests": base_digests(values),
            "version": paper.answer_version,
            "saved_at": fields.Datetime.to_string(latest.write_date) if latest else False,
            "progress": paper_progress(definition, values),
            "missing": [] if exempt else paper_missing(definition, values),
            "missing_parts": [] if exempt else missing_parts(definition, values),
            "readonly": bool(readonly_code),
            "readonly_reason": rule_error(env, readonly_code).args[0] if readonly_code else False,
            "locked_keys": self.with_env(env)._ea_locked_keys(),
            "auto_values": paper._ea_auto_values(),
            "embed_only": paper.code in EMBED_ONLY_PAPERS,
            "signing": self.with_env(env)._ea_signing_payload(),
            "tool_links": paper._ea_tool_links(),
            "linked_tasks": self.with_env(env)._ea_linked_tasks(),
            "assignment": item.with_env(env)._ea_assignment_payload(),
            "deadline": item.with_env(env)._ea_deadline_payload(),
            "not_applicable": item.with_env(env)._ea_na_payload(),
            "notes": env["ea.audit.review.note"]._ea_payload(item),
            "attachments": env["ea.audit.task.attachment"]._ea_payload(item),
            "section_conclusion": env["ea.audit.section.conclusion"]._ea_payload(item),
            "can_review": can_review(firm_role),
            "can_write_notes": bool(can_write(firm_role)) and not engagement._ea_is_archived(),
        }

    def get_answer_history(self):
        self.ensure_one()
        self.check_access("read")
        return [
            {
                "field_key": row.field_key, "before": row.before or "", "after": row.after or "",
                "user": row.user_id.name, "date": self._ea_date(row.changed_at, with_time=True),
            }
            for row in self.history_ids
        ]
