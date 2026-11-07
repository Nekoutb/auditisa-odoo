"""What the screens read. Every method runs under the caller's rights through the
normal ORM, so the record rules of ea_audit_core decide what exists: someone who
is not an accepted member of a file's team gets nothing from it, whatever their
firm role. sudo() appears only on the core's own read helpers and on the caller's
own notification rows."""
from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools import ormcache

from odoo.addons.ea_audit_core.services.firm_time import FIRM_TZ, FIRM_TZ_LABEL
from odoo.addons.ea_audit_core.services.phases import phase_of_task

from ..services.methodology import answer_snippet, methodology_entry, methodology_matches
from ..services.presentation import (
    FIRM_ROLE_LABELS,
    NATURE_LABELS,
    STATUS_PILLS,
    STATUS_WORDS,
    first_name,
    fmt_date,
    initials,
    percent,
    phase_deadline,
    report_due,
    short_name,
)
from ..services.task_groups import (
    E3_MERGED_NOTE,
    GROUP_BY_ID,
    SECTION_LABELS,
    SECTION_OF_PHASE,
    SECTION_ORDER,
    group_of_code,
    groups_of_section,
    phase_label,
)

_RECENT_MISSIONS = 6
_STRIP_CHIPS = 6
_LATE_CHIPS = 3
_MY_TASK_ROWS = 3
_CALENDAR_ROWS = 3


class AuditUi(models.AbstractModel):
    _name = "ea.audit.ui"
    _description = "AuditISA screens: read methods"

    # ------------------------------------------------------------------
    # Who is looking
    # ------------------------------------------------------------------

    @api.model
    def _ea_ui_shell_session(self):
        """The top bar's facts, False for someone outside the firm (they keep
        Odoo's own navbar)."""
        user = self.env.user
        role = user._ea_firm_role()
        if not role:
            return False
        return {
            "firm": self.env.company.name,
            "name": short_name(user.name),
            "first_name": first_name(user.name),
            "initials": initials(user.name),
            "role": self.env._(FIRM_ROLE_LABELS[role]) if role in FIRM_ROLE_LABELS else "",
            "language": "fr_FR" if (user.lang or "").startswith("fr") else "en_US",
            "can_write": role != "read_only",
            "is_partner": user.has_group("ea_audit_core.group_partner"),
            "is_system": user.has_group("base.group_system"),
            "is_firm_admin": role == "firm_admin",
            # meant to be visible to the firm: ea_audit_firm_agent, where the server has it
            "has_operator_log": "ea.firm.access.log" in self.env,
            "tz": FIRM_TZ,
            "tz_label": FIRM_TZ_LABEL,
            "apps": self._ea_ui_apps(),
            "mission_items": self._ea_ui_mission_items(),
        }

    @api.model
    def ea_ui_set_language(self, code):
        """The language switch: saved on the user and on the running session, so the
        reload comes back in it."""
        if code not in ("en_US", "fr_FR"):
            raise UserError(self.env._("Unknown language."))
        self.env.user.sudo().write({"lang": code})
        if request and request.session.uid == self.env.uid:
            request.session.context = dict(request.session.context, lang=code)
        return code

    @api.model
    def _ea_ui_apps(self):
        """The app switcher: what this person may open. Later addons append."""
        return [{"key": "audit", "label": self.env._("Audit"), "sub": self.env._("Engagements and files"), "xmlid": "ea_audit_ui.action_home"}]

    @api.model
    def _ea_ui_mission_items(self):
        """The gear's entries inside a mission: client actions taking resId. Later addons append."""
        return []

    # ------------------------------------------------------------------
    # Shared facts
    # ------------------------------------------------------------------

    @api.model
    def _ea_ui_today(self):
        """Today on the firm's clock, whatever the user's own zone says (F029)."""
        return fields.Date.context_today(self.with_context(tz=FIRM_TZ))

    @api.model
    def _ea_ui_titled(self, records):
        """Task titles read in the caller's language."""
        return records

    @api.model
    def _ea_ui_mission(self, engagement):
        return {
            "id": engagement.id,
            "client_id": engagement.client_id.id,
            "client": engagement.client_id.name,
            "fiscal_year": engagement.fiscal_year,
            "label": "%s, %s" % (engagement.client_id.name, engagement.fiscal_year),
            "phase": engagement.phase,
            "phase_label": self.env._(phase_label(engagement.phase)),
            "section": SECTION_OF_PHASE[engagement.phase],
        }

    @api.model
    def _ea_ui_active_items(self, engagements):
        """The tasks on the file: a conditional task is not active until its
        trigger is answered, and an E4 task S5.5 left out is on no list (F010)."""
        items = self.env["ea.audit.file.item"].search([
            ("engagement_id", "in", engagements.ids), ("conditional", "=", False),
        ])
        scoped_out = set()
        for engagement in items.engagement_id:
            scoped_out.update(engagement.sudo()._ea_e4_out_of_scope().ids)
        return self._ea_ui_titled(items.filtered(lambda item: item.id not in scoped_out))

    @api.model
    def _ea_ui_e4_designed(self, engagement):
        """F010: the one count of E4 tasks that every screen shows. ``total`` is every E4 paper of
        the file, ``designed`` those S5.5 brought into scope: the ones the group lists."""
        total = self.env["ea.audit.file.item"].search_count([
            ("engagement_id", "=", engagement.id), ("code", "=like", "E4.%"), ("conditional", "=", False),
        ])
        out = len(engagement.sudo()._ea_e4_out_of_scope())
        designed = total - out
        return {
            "designed": designed,
            "total": total,
            "text": self.env._("%(designed)s of %(total)s designed", designed=designed, total=total),
        }

    @api.model
    def _ea_ui_live_signoffs(self, items):
        return self.env["ea.audit.signoff"].search([
            ("file_item_id", "in", items.ids), ("kind", "=", "workpaper"),
            ("voided_at", "=", False), ("invalidated_at", "=", False),
        ])

    @api.model
    def _ea_ui_done_ids(self, items, signoffs=None):
        """A task counts as done with a live reviewer or partner signature, or
        when marked not applicable: preparation alone never moves a percentage."""
        signoffs = self._ea_ui_live_signoffs(items) if signoffs is None else signoffs
        done = {s.file_item_id.id for s in signoffs if s.role in ("reviewer", "partner")}
        return done | set(items.filtered("not_applicable").ids)

    @api.model
    def _ea_ui_due(self, item):
        """The one due date a task has: its own, or its phase's."""
        return item.due_date or phase_deadline(
            item.engagement_id.period_end, phase_of_task(item.section, item.code),
        )

    @api.model
    def _ea_ui_status(self, item):
        return "not_applicable" if item.not_applicable else item.state

    @api.model
    def _ea_ui_is_open(self, item):
        return item.state != "signed" and not item.not_applicable

    @api.model
    def _ea_ui_late_days(self, item, today):
        if not self._ea_ui_is_open(item) or item.engagement_id.archived_at:
            return 0
        due = self._ea_ui_due(item)
        return (today - due).days if due and due < today else 0

    @api.model
    def _ea_ui_partner_awaited(self, item, policy):
        """Is this task waiting for the engagement partner's own signature?"""
        if item.state not in ("prepared", "reviewed"):
            return False
        return self.env["ea.audit.signoff.policy"]._ea_effective_rule(item.code, policy)["partner_required"]

    @api.model
    def _ea_ui_my_word(self, item, user, is_partner, policy):
        """What this open task asks of me, a key of _ea_ui_word; None when it asks nothing."""
        if not self._ea_ui_is_open(item):
            return None
        if is_partner and self._ea_ui_partner_awaited(item, policy):
            # the assigned reviewer goes first where the paper has one
            if item.state == "reviewed" or item.approver_id in (user, self.env["res.users"]):
                return "to_sign"
        if item.state == "prepared" and item.approver_id == user:
            return "to_review"
        if user in (item.preparer_id, item.assignee_id) and item.state in ("not_started", "in_progress"):
            return "to_prepare" if item.state == "not_started" else "in_progress"
        return None

    @api.model
    def _ea_ui_is_mine(self, item, user, is_partner, policy):
        """Assigned to me in any role, or waiting for my signature."""
        return user in (item.preparer_id, item.assignee_id, item.approver_id) or bool(
            self._ea_ui_my_word(item, user, is_partner, policy)
        )

    @api.model
    def _ea_ui_word(self, word):
        return {
            "to_sign": self.env._("To sign"),
            "to_review": self.env._("To review"),
            "to_prepare": self.env._("To prepare"),
            "in_progress": self.env._("In progress"),
        }[word]

    @api.model
    def _ea_ui_late_text(self, days):
        return self.env._("Overdue by %(days)s d", days=days) if days else ""

    # ------------------------------------------------------------------
    # The top bar
    # ------------------------------------------------------------------

    @api.model
    def ea_ui_shell(self):
        engagements = self.env["ea.audit.engagement"].search([], order="write_date desc, id desc")
        ordered = engagements.sorted(lambda e: bool(e.archived_at or e.phase == "archived"))[:_RECENT_MISSIONS]
        return {
            "recent": [self._ea_ui_mission(engagement) for engagement in ordered],
            "unread": len(self.env["ea.audit.notification"]._ea_ui_visible(unread_only=True)),
        }

    @api.model
    def ea_ui_context(self, model, res_id):
        """The mission a form belongs to, so the top bar stays inside it."""
        engagement = self.env["ea.audit.engagement"]
        if model == "ea.audit.engagement":
            engagement = engagement.search([("id", "=", res_id)], limit=1)
        elif model == "ea.audit.file.item":
            item = self.env["ea.audit.file.item"].search([("id", "=", res_id)], limit=1)
            engagement = item.engagement_id
            if item:
                # the bar shows the phase of the paper one is on, not the ring last opened
                group = group_of_code(item.code)
                return {**self._ea_ui_mission(engagement), "item_section": group["section"] if group else False}
        return self._ea_ui_mission(engagement) if engagement else False

    @api.model
    @ormcache("lang")
    def _ea_ui_methodology_index(self, lang):
        """F079: what the papers say, built once per language in each process: the standards,
        requirements and procedures live in the definitions, where a title search cannot see."""
        Definition = self.env["ea.audit.paper.def"].sudo()
        titles = {
            template.code: template.title
            for template in self.env["ea.audit.task.template"].sudo().with_context(lang=lang).search([])
        }
        fr = (lang or "").startswith("fr")
        return tuple(
            methodology_entry(definition.code, titles.get(definition.code, ""), definition.definition, fr)
            for definition in Definition.search([("is_current", "=", True)])
        )

    @api.model
    def ea_ui_search(self, term, mission_id=None):
        """Missions by client, name or year, tasks by code or title, the papers' own text and
        what the team wrote in them, in the files the caller can open: every search below runs
        under the caller's rules."""
        term = (term or "").strip()
        if len(term) < 2:
            return {"missions": [], "tasks": [], "methodology": [], "answers": []}
        domain = ["|", ("client_id.name", "ilike", term), ("name", "ilike", term)]
        if term.isdigit():
            domain = ["|", ("fiscal_year", "=", int(term))] + domain
        engagements = self.env["ea.audit.engagement"].search(domain, limit=6)
        Item = self.env["ea.audit.file.item"]
        items = self._ea_ui_titled(Item).search(
            [("conditional", "=", False), "|", ("code", "=ilike", "%s%%" % term), ("template_id.title", "ilike", term)],
            limit=8,
        )
        def row(item, snippet=""):
            return {
                "id": item.id,
                "code": item.code,
                "title": item.title,
                "snippet": snippet,
                "mission": "%s, %s" % (item.engagement_id.client_id.name, item.engagement_id.fiscal_year),
            }

        matched = methodology_matches(term, self._ea_ui_methodology_index(self.env.lang or "en_US"))
        # What a paper says is the same on every file: one row per paper, on the open mission, else the latest file.
        candidates = self._ea_ui_titled(Item).search(
            [("conditional", "=", False), ("code", "in", list(matched)), ("id", "not in", items.ids)],
        ).sorted(lambda item: (item.engagement_id.id != mission_id, -item.engagement_id.fiscal_year, item.sequence, item.code)) if matched else Item
        in_methodology = Item.browse()
        seen_codes = set()
        for item in candidates:
            if item.code not in seen_codes:
                seen_codes.add(item.code)
                in_methodology |= item
        in_methodology = in_methodology[:12]
        # below three characters, "no" and "yes" would match every answer
        written = self.env["ea.audit.paper.answer"].search([("value", "ilike", term)], limit=6) if len(term) >= 3 else self.env["ea.audit.paper.answer"]
        written_items = Item.search([
            ("engagement_id", "in", written.engagement_id.ids), ("code", "in", written.mapped("code")),
        ])
        by_key = {(item.engagement_id.id, item.code): item for item in written_items}
        answers = []
        for answer in written:
            item = by_key.get((answer.engagement_id.id, answer.code))
            if item:
                answers.append(row(self._ea_ui_titled(item), answer_snippet(answer.value, term)))
        return {
            "missions": [self._ea_ui_mission(engagement) for engagement in engagements],
            "tasks": [row(item) for item in items],
            "methodology": [row(item, matched[item.code]) for item in in_methodology],
            "answers": answers,
        }

    # ------------------------------------------------------------------
    # The bell
    # ------------------------------------------------------------------

    @api.model
    def ea_ui_notifications(self):
        rows = self.env["ea.audit.notification"]._ea_ui_visible()
        return {
            "unread": len(rows.filtered(lambda row: not row.read_at)),
            "total": len(rows),
            "rows": [{
                "id": row.id,
                "kind": row.kind,
                "title": row.title,
                "detail": row.detail or "",
                "unread": not row.read_at,
                "created": fields.Datetime.to_string(row.create_date),
                "url": row._ea_ui_url(),
            } for row in rows[:20]],
        }

    @api.model
    def ea_ui_notification_open(self, notification_id):
        """Mark one's own row read and say where it leads."""
        rows = self.env["ea.audit.notification"]._ea_ui_visible().filtered(lambda row: row.id == notification_id)
        if not rows:
            return False
        if not rows.read_at:
            rows.read_at = fields.Datetime.now()
        return {
            "kind": rows.kind,
            "engagement_id": rows.engagement_id.id,
            "file_item_id": rows.file_item_id.id,
        }

    # ------------------------------------------------------------------
    # Home
    # ------------------------------------------------------------------

    @api.model
    def _ea_ui_home_todo(self, engagements, items, today):
        user = self.env.user
        policy = self.env["ea.audit.signoff.policy"]._ea_policy()
        rows = []
        for engagement in engagements.filtered(lambda e: not e.archived_at and e.phase != "archived"):
            mission = self.env._("%(client)s, fiscal year %(year)s", client=engagement.client_id.name, year=engagement.fiscal_year)
            own = items.filtered(lambda item: item.engagement_id == engagement)
            is_partner = user == engagement.engagement_partner_id or user == engagement.partner_delegate_id
            awaiting_acceptance = (
                is_partner and engagement.phase == "acceptance" and not engagement.sudo()._ea_approval_signed("P1.1")
            )
            to_review = own.filtered(
                lambda item: self._ea_ui_my_word(item, user, is_partner, policy) in ("to_review", "to_sign")
                # the acceptance has a row of its own
                and not (awaiting_acceptance and item.code == "P1.1")
            )
            if to_review:
                rows.append({
                    "title": self.env._("Working papers awaiting review"),
                    "mission": mission,
                    "count": len(to_review),
                    "engagement_id": engagement.id,
                    "item_ids": to_review.ids,
                })
            if awaiting_acceptance:
                acceptance = own.filtered(lambda item: item.code == "P1.1")
                rows.append({
                    "title": self.env._("Acceptance awaiting the partner's sign-off"),
                    "mission": mission,
                    "count": 0,
                    "engagement_id": engagement.id,
                    "item_ids": acceptance.ids,
                })
            late = own.filtered(
                lambda item: user in (item.preparer_id, item.assignee_id) and self._ea_ui_late_days(item, today) > 0
            )
            if late:
                rows.append({
                    "title": self.env._("Overdue tasks"),
                    "mission": mission,
                    "count": len(late),
                    "engagement_id": engagement.id,
                    "item_ids": late.ids,
                })
            uncommunicated = engagement.sudo()._ea_uncommunicated_significant_count() if is_partner else 0
            if uncommunicated:
                rows.append({
                    "title": self.env._("Significant deficiency to communicate"),
                    "mission": mission,
                    "count": uncommunicated,
                    "engagement_id": engagement.id,
                    "tool": "action_tool_deficiencies",
                })
        invitations = self.env["ea.audit.team.member"].search([("user_id", "=", user.id), ("state", "=", "invited")])
        for invitation in invitations:
            rows.append({
                "title": self.env._("Invitation to answer"),
                "mission": self.env._("%(client)s, fiscal year %(year)s", client=invitation.invitation_client_name, year=invitation.invitation_fiscal_year),
                "count": 0,
                "invitation": True,
            })
        return rows

    @api.model
    def ea_ui_home(self):
        today = self._ea_ui_today()
        engagements = self.env["ea.audit.engagement"].search([], order="fiscal_year desc, id")
        engagements = engagements.sorted(lambda e: bool(e.archived_at or e.phase == "archived"))
        items = self._ea_ui_active_items(engagements)
        done_ids = self._ea_ui_done_ids(items)
        missions = []
        for engagement in engagements:
            own = items.filtered(lambda item: item.engagement_id == engagement)
            done = len([item for item in own if item.id in done_ids])
            archived = bool(engagement.archived_at or engagement.phase == "archived")
            partner = engagement.engagement_partner_id
            missions.append({
                **self._ea_ui_mission(engagement),
                "period_end": fmt_date(engagement.period_end),
                "nature": self.env._(NATURE_LABELS[engagement.nature]) if engagement.nature in NATURE_LABELS else "",
                "archived": archived,
                "archived_on": fmt_date(fields.Date.to_date(engagement.archived_at)) if engagement.archived_at else "",
                "phase_deadline": fmt_date(phase_deadline(engagement.period_end, engagement.phase)),
                "report_due": fmt_date(report_due(engagement.period_end)),
                "partner": short_name(partner.name) if partner else "—",
                "acceptance_signed": engagement.sudo()._ea_approval_signed("P1.1"),
                "done": done,
                "total": len(own),
                "pct": percent(done, len(own)),
            })
        return {"todo": self._ea_ui_home_todo(engagements, items, today), "missions": missions}

    # ------------------------------------------------------------------
    # The engagement dashboard
    # ------------------------------------------------------------------

    @api.model
    def _ea_ui_visible_engagement(self, engagement_id):
        return self.env["ea.audit.engagement"].search([("id", "=", engagement_id)], limit=1)

    @api.model
    def _ea_ui_rings(self, items, done_ids, e4=None):
        by_group = {}
        for item in items:
            by_group.setdefault(group_of_code(item.code)["id"], []).append(item)
        rings = []
        for section in SECTION_ORDER:
            groups = []
            for group in groups_of_section(section):
                members = by_group.get(group["id"], [])
                groups.append({
                    "id": group["id"],
                    "code": group["code"],
                    "label": self.env._(group.get("short") or group["title"]),
                    "done": len([item for item in members if item.id in done_ids]),
                    "total": len(members),
                    "designed": e4["text"] if e4 and group["id"] == "e4" else False,
                })
            done = sum(group["done"] for group in groups)
            total = sum(group["total"] for group in groups)
            # the group in hand: the first one with work left
            current = next((g["id"] for g in groups if g["total"] and g["done"] < g["total"]), None)
            rings.append({
                "key": section,
                "label": self.env._(SECTION_LABELS[section]),
                "done": done,
                "total": total,
                "pct": percent(done, total),
                "current_group": current,
                "groups": [group for group in groups if group["total"]],
                "note": self.env._(E3_MERGED_NOTE) if section == "execution" else False,
            })
        return rings

    @api.model
    def _ea_ui_notes_tile(self, engagement):
        """Open review notes addressed to me and raised by me, open ISA 265 deficiencies,
        misstatements still uncorrected and above the clearly trivial."""
        user = self.env.user
        notes = self.env["ea.audit.review.note"].search([("engagement_id", "=", engagement.id), ("state", "=", "open")])
        for_me = notes.filtered(lambda note: note.assignee_id == user)
        return {
            "for_me": len(for_me),
            "by_me": len(notes.filtered(lambda note: note.author_id == user)),
            "deficiencies": self.env["ea.audit.finding"].search_count([
                ("engagement_id", "=", engagement.id), ("route", "=", "c1"), ("status", "=", "open"),
            ]),
            "misstatements": self.env["ea.audit.misstatement"].search_count([
                ("engagement_id", "=", engagement.id), ("corrected", "=", False), ("trivial", "=", False),
            ]),
            "note_item_ids": for_me.file_item_id.ids,
        }

    @api.model
    def _ea_ui_attention_chips(self, engagement, items, today):
        """What the file asks for now: a late task, a significant risk with no planned
        response, a note addressed to me, a paper waiting for its next signature."""
        late = items.filtered(lambda item: self._ea_ui_late_days(item, today) > 0).sorted(
            lambda item: (self._ea_ui_due(item), item.sequence)
        )
        chips = [{
            "id": item.id, "code": item.code, "title": item.short_title or item.title, "tone": "r",
            "text": self.env._("overdue by %(days)s d", days=self._ea_ui_late_days(item, today)),
        } for item in late[:_LATE_CHIPS]]
        register = items.filtered(lambda item: item.code == "S3.1")[:1]
        if register:
            risks = self.env["ea.audit.risk"].search([
                ("engagement_id", "=", engagement.id), ("significant", "=", True), ("rebutted", "=", False),
                ("program_step_ids", "=", False),
            ]).with_context(lang=register.env.lang)
            chips += [{
                "id": register.id, "code": register.code, "title": risk.title, "tone": "r", "text": self.env._("no planned procedure"),
            } for risk in risks[:2]]
        notes = self.env["ea.audit.review.note"].search([
            ("engagement_id", "=", engagement.id), ("state", "=", "open"), ("assignee_id", "=", self.env.uid),
        ])
        by_item = {item.id: item for item in items}
        chips += [{
            "id": note.file_item_id.id, "code": note.code, "title": by_item[note.file_item_id.id].short_title or by_item[note.file_item_id.id].title,
            "tone": "g", "text": self.env._("review note"),
        } for note in notes if note.file_item_id.id in by_item][:3]
        awaiting = items.filtered(
            lambda item: not item.not_applicable and item.state in ("prepared", "reviewed") and item not in late
        )
        chips += [{
            "id": item.id, "code": item.code, "title": item.short_title or item.title, "tone": "g",
            "text": self.env._("to sign") if item.state == "reviewed" else self.env._("to review"),
        } for item in awaiting[:_STRIP_CHIPS]]
        return chips[:_STRIP_CHIPS], late

    @api.model
    def ea_ui_dashboard(self, engagement_id):
        engagement = self._ea_ui_visible_engagement(engagement_id)
        if not engagement:
            return {"denied": True}
        today = self._ea_ui_today()
        user = self.env.user
        items = self._ea_ui_active_items(engagement)
        done_ids = self._ea_ui_done_ids(items)
        e4 = self._ea_ui_e4_designed(engagement)
        rings = self._ea_ui_rings(items, done_ids, e4)
        archived = bool(engagement.archived_at or engagement.phase == "archived")
        policy = self.env["ea.audit.signoff.policy"]._ea_policy()
        is_partner = user == engagement.engagement_partner_id or user == engagement.partner_delegate_id

        # tasks with no preparer and no assignee; a done task needs nobody, and
        # nothing is handed out on an archived file
        unassigned = self.env["ea.audit.file.item"] if archived else items.filtered(
            lambda item: not item.preparer_id and not item.assignee_id and item.id not in done_ids
        )

        chips, late = self._ea_ui_attention_chips(engagement, items, today)

        # F021: the tile counts what the Tasks page calls Mine and Open
        mine = []
        for item in items:
            if self._ea_ui_is_mine(item, user, is_partner, policy) and self._ea_ui_is_open(item):
                word = self._ea_ui_my_word(item, user, is_partner, policy)
                mine.append({
                    "id": item.id, "code": item.code, "title": item.short_title or item.title,
                    "word": self._ea_ui_word(word) if word else self.env._(STATUS_WORDS[self._ea_ui_status(item)]),
                })

        upcoming = items.filtered(
            lambda item: self._ea_ui_is_open(item) and not archived and self._ea_ui_due(item)
        ).sorted(lambda item: (self._ea_ui_due(item), item.sequence))
        calendar_rows = [{
            "id": item.id,
            "code": item.code,
            "title": item.short_title or item.title,
            "due": fmt_date(self._ea_ui_due(item)),
            "late_days": self._ea_ui_late_days(item, today),
            "late_text": self._ea_ui_late_text(self._ea_ui_late_days(item, today)),
            "status": self.env._(STATUS_WORDS[self._ea_ui_status(item)]),
        } for item in upcoming[:_CALENDAR_ROWS]]

        total = sum(ring["total"] for ring in rings)
        done = sum(ring["done"] for ring in rings)
        return {
            "mission": self._ea_ui_mission(engagement),
            "period_end": fmt_date(engagement.period_end),
            "report_due": fmt_date(report_due(engagement.period_end)),
            "archived": archived,
            "pct": percent(done, total),
            "done": done,
            "total": total,
            "rings": rings,
            "unassigned_ids": unassigned.ids,
            "attention": chips,
            "my_tasks": {"count": len(mine), "rows": mine[:_MY_TASK_ROWS], "e4": e4},
            "notes": self._ea_ui_notes_tile(engagement),
            "calendar": {"late": len(late), "rows": calendar_rows},
        }

    # ------------------------------------------------------------------
    # The task list of a group
    # ------------------------------------------------------------------

    @api.model
    def _ea_ui_signer_cell(self, name, signoff, waiting):
        if signoff:
            return {
                "name": short_name(signoff.user_id.name),
                "signed": True,
                "detail": self.env._("Signed on %(date)s", date=fmt_date(fields.Date.context_today(self.with_context(tz=FIRM_TZ), signoff.signed_at))),
            }
        return {"name": short_name(name) if name else self.env._("Unassigned"), "signed": False, "detail": waiting if name else ""}

    @api.model
    def _ea_ui_task_row(self, item, signoffs, partner, policy, today):
        own = signoffs.filtered(lambda s: s.file_item_id == item)
        by_role = {s.role: s for s in own}
        rule = self.env["ea.audit.signoff.policy"]._ea_effective_rule(item.code, policy)
        preparer_user = item.preparer_id or item.assignee_id
        preparer_waiting = self.env._("In progress") if item.state == "in_progress" else self.env._("Not started yet")
        reviewer_user = item.approver_id or partner
        if "partner" in by_role and "reviewer" not in by_role:
            reviewer_waiting = self.env._("Partner approval")
        elif "preparer" in by_role:
            reviewer_waiting = self.env._("Awaiting review")
        else:
            reviewer_waiting = self.env._("Awaiting preparer")
        status = self._ea_ui_status(item)
        pill, tone = STATUS_PILLS[status]
        row = {
            "id": item.id,
            "code": item.code,
            "title": item.title,
            "preparer": self._ea_ui_signer_cell(preparer_user.name, by_role.get("preparer"), preparer_waiting),
            "reviewer": self._ea_ui_signer_cell(reviewer_user.name, by_role.get("reviewer"), reviewer_waiting),
            "partner": None,
            "due": fmt_date(self._ea_ui_due(item)),
            "late_days": self._ea_ui_late_days(item, today),
            "late_text": self._ea_ui_late_text(self._ea_ui_late_days(item, today)),
            "pill": self.env._(pill),
            "tone": tone,
        }
        if rule["partner_required"]:
            waiting = self.env._("Awaiting sign-off") if item.state in ("prepared", "reviewed") else self.env._("Awaiting preparer")
            row["partner"] = self._ea_ui_signer_cell(partner.name, by_role.get("partner"), waiting)
        return row

    @api.model
    def ea_ui_tasks(self, engagement_id, group_id):
        engagement = self._ea_ui_visible_engagement(engagement_id)
        group = GROUP_BY_ID.get(group_id)
        if not engagement or not group:
            return {"denied": True}
        today = self._ea_ui_today()
        items = self._ea_ui_active_items(engagement).filtered(lambda item: group_of_code(item.code)["id"] == group_id)
        signoffs = self._ea_ui_live_signoffs(items)
        done_ids = self._ea_ui_done_ids(items, signoffs)
        policy = self.env["ea.audit.signoff.policy"]._ea_policy()
        partner = engagement.engagement_partner_id
        conditional = self.env["ea.audit.file.item"].search([
            ("engagement_id", "=", engagement.id), ("conditional", "=", True),
        ]).filtered(lambda item: group_of_code(item.code)["id"] == group_id)
        return {
            "mission": self._ea_ui_mission(engagement),
            "designed": self._ea_ui_e4_designed(engagement)["text"] if group_id == "e4" else False,
            "note": self.env._(E3_MERGED_NOTE) if group_id == "e5" else False,
            # F031: not on the file, and why, rather than silently absent
            "conditional": [{
                "id": item.id, "code": item.code, "title": item.title, "trigger": item.conditional_trigger or "",
            } for item in conditional],
            "group": {
                "id": group["id"],
                "code": group["code"],
                "title": self.env._(group["title"]),
                "section": group["section"],
                "section_label": self.env._(SECTION_LABELS[group["section"]]),
            },
            "done": len(done_ids & set(items.ids)),
            "total": len(items),
            "rows": [self._ea_ui_task_row(item, signoffs, partner, policy, today) for item in items],
        }

    @api.model
    def ea_ui_all_tasks(self, engagement_id):
        """The Tasks page of a mission (F021): every active task, each saying whether it is mine
        and whether it is open. The page filters on Mine first, and shows what Open counts."""
        engagement = self._ea_ui_visible_engagement(engagement_id)
        if not engagement:
            return {"denied": True}
        today = self._ea_ui_today()
        user = self.env.user
        items = self._ea_ui_active_items(engagement)
        signoffs = self._ea_ui_live_signoffs(items)
        policy = self.env["ea.audit.signoff.policy"]._ea_policy()
        partner = engagement.engagement_partner_id
        is_partner = user == partner or user == engagement.partner_delegate_id
        rows = []
        for item in items:
            row = self._ea_ui_task_row(item, signoffs, partner, policy, today)
            row["mine"] = self._ea_ui_is_mine(item, user, is_partner, policy)
            row["open"] = self._ea_ui_is_open(item)
            rows.append(row)
        return {
            "mission": self._ea_ui_mission(engagement),
            "designed": self._ea_ui_e4_designed(engagement)["text"],
            "rows": rows,
        }
