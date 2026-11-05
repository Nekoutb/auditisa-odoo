import base64
import binascii

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.phases import phase_still_open
from odoo.addons.ea_audit_core.services.signoff_rules import (
    EQR_PAPER,
    EQR_ROLE,
    at_least,
    below_minimum_code,
    can_partner_signoff,
    can_review,
    team_rank,
)

from ..services import MAX_BYTES, UnsafeFile, check_upload, completeness_exempt, has_bespoke_paper, missing_parts
from .errors import incomplete_error, paper_error

# What each of these codes refuses until ea_audit_tools reads the real records. Until
# then the record does not exist, so the refusal stands: the same rule as core's hooks.
_TOOL_GAPS = {
    "S1.2": "wcgw-missing",
    "S1.3": "walkthrough-incomplete",
    "S2.1": "control-selection-incomplete",
    "S2.2": "test-design-missing",
    "S2.3": "itapp-strategy-missing",
    "P6.2": "significance-unjustified",
}


_NA_FIELDS = {"not_applicable", "na_reason", "na_by_id", "na_at"}


class FileItem(models.Model):
    _inherit = "ea.audit.file.item"

    paper_ids = fields.One2many("ea.audit.paper", "file_item_id", string="Paper")
    review_note_ids = fields.One2many("ea.audit.review.note", "file_item_id", string="Review notes")
    attachment_ids = fields.One2many("ea.audit.task.attachment", "file_item_id", string="Evidence")
    na_reason = fields.Char(string="Why not applicable")
    na_by_id = fields.Many2one("res.users", string="Marked not applicable by", ondelete="restrict")
    na_at = fields.Datetime(string="Marked not applicable at")

    @api.model_create_multi
    def create(self, vals_list):
        items = super().create(vals_list)
        items._ea_ensure_papers()
        return items

    def write(self, vals):
        # Not applicable carries a rank and a reason: set_not_applicable is the way in.
        if not self.env.su and set(vals) & _NA_FIELDS:
            self.env["ea.audit.engagement"]._ea_require_write()
            self.sudo().engagement_id.with_env(self.env)._ea_require_access()
            raise paper_error(self.env, "forbidden")
        return super().write(vals)

    def _ea_ensure_papers(self):
        """A paper exists from the moment its task does, so no reader has to create one."""
        have = set(self.env["ea.audit.paper"].sudo().search([("file_item_id", "in", self.ids)]).file_item_id.ids)
        missing = [{"file_item_id": item.id} for item in self if item.id not in have]
        if missing:
            self.env["ea.audit.paper"].sudo().with_context(
                tracking_disable=True, mail_create_nolog=True, mail_create_nosubscribe=True,
            ).create(missing)

    def _ea_paper(self):
        self.ensure_one()
        return self.env["ea.audit.paper"].sudo().search([("file_item_id", "=", self.id)], limit=1)

    def action_open_paper(self):
        """The renderer, as a task row opens it."""
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "ea_audit_paper",
            "name": "%s %s" % (self.code, self.short_title or self.title),
            "params": {"file_item_id": self.id},
            # active_id is what the web client keeps in the URL for a reload
            "context": {"active_id": self.id},
        }

    def get_paper_payload(self):
        """The renderer's entry point: it knows the task, not the paper."""
        self.ensure_one()
        return self.sudo()._ea_paper().with_env(self.env).get_payload()

    # ------------------------------------------------------------------
    # core's sign-off hooks
    # ------------------------------------------------------------------

    def _ea_paper_refusal(self, role):
        self.ensure_one()
        if not completeness_exempt(self.code, has_bespoke_paper(self.code)):
            paper = self._ea_paper()
            parts = missing_parts(paper._ea_resolved(), paper._ea_values())
            if parts:
                raise incomplete_error(self.env, parts)
        gap = self._ea_tool_gap()
        if gap:
            raise paper_error(self.env, gap)
        return super()._ea_paper_refusal(role)

    def _ea_tool_gap(self):
        """ea_audit_tools: embeddedWorkGap, significance-unjustified, itapp-strategy-missing."""
        self.ensure_one()
        return _TOOL_GAPS.get(self.code)

    def _ea_review_refusal(self):
        self.ensure_one()
        if self.env["ea.audit.review.note"].sudo().search_count(
            [("file_item_id", "=", self.id), ("state", "=", "open")]
        ):
            return "open-notes"
        if self.env["ea.audit.section.conclusion"].sudo().search_count([
            ("file_item_id", "=", self.id), ("reviewed_by_id", "=", False), ("partner_reviewed_by_id", "=", False),
        ]):
            return "review-conclusion-first"
        return super()._ea_review_refusal()

    def _ea_paper_content_hash(self):
        self.ensure_one()
        return self._ea_paper()._content_hash()

    def _ea_paper_version(self):
        self.ensure_one()
        return self._ea_paper().answer_version

    # ------------------------------------------------------------------
    # Assignment and not-applicable, as the header shows them
    # ------------------------------------------------------------------

    def _ea_assignment_payload(self):
        self.ensure_one()
        item = self.sudo()
        engagement = item.engagement_id
        firm_role = self.env.user._ea_firm_role()
        team = self.env["ea.audit.team.member"].sudo().search(
            [("engagement_id", "=", engagement.id), ("state", "=", "accepted"), ("team_role", "!=", EQR_ROLE)]
        )
        options = [{"id": m.user_id.id, "name": m.user_id.name, "role": m.team_role} for m in team]
        for current in (item.preparer_id, item.approver_id):
            # an assignee off the team is still shown (UAT run 2 B04)
            if current and current.id not in {o["id"] for o in options}:
                options.append({"id": current.id, "name": current.name, "role": False})
        return {
            "preparer_id": item.preparer_id.id,
            "approver_id": item.approver_id.id,
            "options": options,
            "can_assign": bool(
                can_review(firm_role) and not engagement._ea_acts_as_eqr(self.env.user) and not engagement._ea_is_archived()
            ),
        }

    def _ea_na_payload(self):
        self.ensure_one()
        item = self.sudo()
        return {
            "active": bool(item.not_applicable),
            "reason": item.na_reason or "",
            "by": item.na_by_id.name or "",
            "can_set": bool(
                can_review(self.env.user._ea_firm_role())
                and not item.engagement_id._ea_acts_as_eqr(self.env.user)
                and not item.engagement_id._ea_is_archived()
            ),
        }

    def set_not_applicable(self, reason="", clear=False):
        """markNotApplicableAction: reviewer rank, never the EQR, always with a reason."""
        self.ensure_one()
        item = self.sudo()
        engagement = item.engagement_id
        engagement.with_env(self.env)._ea_require_access()
        if not can_review(self.env.user._ea_firm_role()):
            raise paper_error(self.env, "forbidden")
        if engagement._ea_acts_as_eqr(self.env.user):
            raise paper_error(self.env, "eqr-read-only")
        text = (reason or "").strip()[:500]
        if not clear and not text:
            raise paper_error(self.env, "rationale-required")
        engagement.with_env(self.env)._ea_assert_mutable()
        item.write({
            "not_applicable": not clear,
            "na_reason": False if clear else text,
            "na_by_id": False if clear else self.env.user.id,
            "na_at": False if clear else fields.Datetime.now(),
        })
        item._ea_paper().with_env(self.env)._ea_trail(
            "na_cleared" if clear else "marked_not_applicable",
            "%s no longer marked not applicable" % item.code if clear else "%s marked not applicable: %s" % (item.code, text),
        )
        return True

    # ------------------------------------------------------------------
    # Review notes
    # ------------------------------------------------------------------

    def add_review_note(self, body):
        """addTaskNote and addReviewNote as one: addressed to the active preparer, else the
        task's owner. The EQR reads and raises notes, so this is open to them."""
        self.ensure_one()
        env = self.env
        env["ea.audit.engagement"]._ea_require_write()
        item = self.sudo()
        if not item.exists():
            raise paper_error(env, "not-found")
        engagement = item.engagement_id.with_env(env)
        engagement._ea_require_access()
        engagement._ea_assert_mutable()
        text = (body or "").strip()
        if not text:
            raise paper_error(env, "body-required")
        paper = item._ea_paper()
        preparer = paper._ea_active_signoffs().filtered(lambda s: s.role == "preparer").user_id[:1]
        addressee = preparer or item.preparer_id or item.assignee_id
        note = env["ea.audit.review.note"].sudo().create({
            "file_item_id": item.id, "author_id": env.user.id, "assignee_id": addressee.id, "body": text,
        })
        paper.with_env(env)._ea_trail("review_note_raised", "Review note raised on %s" % item.code)
        paper.with_env(env)._ea_notify_users(addressee, "%s: note de revue / review note" % item.code, text[:400])
        return note.id

    # ------------------------------------------------------------------
    # Section conclusions
    # ------------------------------------------------------------------

    def _ea_program_step_counts(self):
        """ea_audit_tools: the task's program steps. None exist until it is installed."""
        return {"retained": 0, "open": 0}

    def _ea_assert_procedures_support(self, objectives_achieved, rationale):
        if not objectives_achieved:
            return
        steps = self._ea_program_step_counts()
        if steps["open"]:
            raise paper_error(self.env, "steps-open")
        if not steps["retained"] and not rationale:
            raise paper_error(self.env, "no-procedures-rationale-required")

    def save_section_conclusion(self, conclusion, objectives_achieved=False, no_procedures_rationale=""):
        """saveSectionConclusion: rewriting it clears its reviews and voids any signature
        given over the earlier text."""
        self.ensure_one()
        env = self.env
        env["ea.audit.engagement"]._ea_require_write()
        item = self.sudo()
        if not item.exists() or item.section != "E":
            raise paper_error(env, "not-found")
        engagement = item.engagement_id.with_env(env)
        engagement._ea_require_access()
        engagement._ea_assert_mutable()
        if item.code != EQR_PAPER and item.engagement_id._ea_acts_as_eqr(env.user):
            raise paper_error(env, "eqr-read-only")
        text = (conclusion or "")
        if not text.strip():
            raise paper_error(env, "conclusion-required")
        rationale = (no_procedures_rationale or "").strip() or False
        still_open = phase_still_open("execution", item.engagement_id.phase, item.code)
        if still_open:
            raise paper_error(env, still_open)
        item.with_env(env)._ea_assert_procedures_support(objectives_achieved, rationale)
        Conclusion = env["ea.audit.section.conclusion"].sudo()
        row = Conclusion.search([("file_item_id", "=", item.id)], limit=1)
        vals = {
            "conclusion": text, "objectives_achieved": bool(objectives_achieved), "no_procedures_rationale": rationale,
            "prepared_by_id": env.user.id, "prepared_at": fields.Datetime.now(),
            "reviewed_by_id": False, "reviewed_at": False,
            "partner_reviewed_by_id": False, "partner_reviewed_at": False,
        }
        if row:
            row.write(vals)
        else:
            Conclusion.create(dict(vals, file_item_id=item.id))
        item._ea_paper().with_env(env)._void_stale_signoffs()
        return True

    def review_section_conclusion(self, as_partner=False):
        """reviewSectionConclusion: a sign-off like any other. Whoever prepared it never
        reviews it (F001), and the partner's review is the engagement partner's (F003)."""
        self.ensure_one()
        env = self.env
        user = env.user
        env["ea.audit.engagement"]._ea_require_write()
        firm_role = user._ea_firm_role()
        if as_partner and not can_partner_signoff(firm_role):
            raise paper_error(env, "forbidden")
        if not as_partner and not can_review(firm_role):
            raise paper_error(env, "forbidden")
        item = self.sudo()
        if not item.exists():
            raise paper_error(env, "not-found")
        row = env["ea.audit.section.conclusion"].sudo().search([("file_item_id", "=", item.id)], limit=1)
        if row.prepared_by_id == user:
            raise paper_error(env, "self-review")
        engagement = item.engagement_id
        engagement.with_env(env)._ea_assert_mutable()
        member = engagement._ea_member(user)
        if not member:
            raise paper_error(env, "not-on-team-to-sign")
        if member.state != "accepted":
            raise paper_error(env, "accept-engagement-first")
        if as_partner:
            partners, delegate = engagement._ea_partner_seat()
            if not partners:
                raise paper_error(env, "designate-engagement-partner-first")
            if user not in partners and not (delegate and delegate == user):
                raise paper_error(env, "not-engagement-partner")
        else:
            rule = env["ea.audit.signoff.policy"].sudo()._ea_effective_rule(item.code)
            if team_rank(member.team_role) < team_rank(rule["min_reviewer"]):
                raise paper_error(env, below_minimum_code(rule["min_reviewer"]))
        if row:
            item.with_env(env)._ea_assert_procedures_support(row.objectives_achieved, row.no_procedures_rationale)
        if not row:
            raise paper_error(env, "not-found")
        now = fields.Datetime.now()
        row.write(
            {"partner_reviewed_by_id": user.id, "partner_reviewed_at": now}
            if as_partner else {"reviewed_by_id": user.id, "reviewed_at": now}
        )
        return True

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    def _ea_guard_evidence(self, minimum):
        """assertCanWrite or assertCanDelete, the file's mutability, and the EQR files
        evidence only on C4.2, their own record (UAT run 3 B03)."""
        self.ensure_one()
        env = self.env
        item = self.sudo()
        engagement = item.engagement_id
        engagement.with_env(env)._ea_require_access()
        if not at_least(env.user._ea_firm_role(), minimum):
            raise paper_error(env, "forbidden")
        engagement.with_env(env)._ea_assert_mutable()
        if item.code != EQR_PAPER and engagement._ea_acts_as_eqr(env.user):
            raise paper_error(env, "eqr-read-only")

    def _ea_after_evidence_change(self, env, action, summary):
        """The task's evidence is part of what its signatures attest (UAT run 2 B10)."""
        paper = self.sudo()._ea_paper().with_env(env)
        paper._ea_trail("attachment_%s" % action, "%s: %s" % (self.code, summary))
        paper._void_stale_signoffs()

    def upload_attachment(self, filename, content_b64):
        """saveAttachment and checkUpload. Re-uploading a name adds the next version;
        numbering climbs past a removed chain so that a re-upload can never collide."""
        self.ensure_one()
        env = self.env
        item = self.sudo()
        if not item.exists():
            raise paper_error(env, "not-found")
        item.with_env(env)._ea_guard_evidence("staff")
        try:
            content = base64.b64decode(content_b64 or "", validate=True)
        except (binascii.Error, ValueError):
            raise paper_error(env, "content-mismatch") from None
        if len(content) > MAX_BYTES:
            raise paper_error(env, "file-too-large")
        try:
            name, mime, _ext = check_upload(filename or "", content)
        except UnsafeFile as refusal:
            raise paper_error(env, refusal.code) from None
        Attachment = env["ea.audit.task.attachment"].sudo()
        previous = Attachment.search([("file_item_id", "=", item.id), ("name", "=", name)], order="version desc", limit=1)
        version = previous.version + 1
        stored = env["ir.attachment"].sudo().create({
            "name": name, "raw": content, "mimetype": mime,
            "res_model": "ea.audit.task.attachment", "res_id": 0,
        })
        row = Attachment.create({
            "file_item_id": item.id, "name": name, "mime": mime, "size_bytes": len(content), "version": version,
            "attachment_id": stored.id, "uploaded_by_id": env.user.id,
        })
        stored.res_id = row.id
        item._ea_after_evidence_change(env, "uploaded", "%s v%s" % (name, version))
        return row.id
