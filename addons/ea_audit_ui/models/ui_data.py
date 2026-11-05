"""What the screens read. Every method runs under the caller's rights through the
normal ORM, so the record rules of ea_audit_core decide what exists: someone who
is not an accepted member of a file's team gets nothing from it, whatever their
firm role. sudo() appears only on the core's own read helpers and on the caller's
own notification rows."""
from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.phases import phase_of_task

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
            "role": FIRM_ROLE_LABELS.get(role, ""),
            "can_write": role != "read_only",
            "is_partner": user.has_group("ea_audit_core.group_partner"),
            "is_system": user.has_group("base.group_system"),
            "apps": self._ea_ui_apps(),
            "mission_items": self._ea_ui_mission_items(),
        }

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
    def _ea_ui_titled(self, records):
        """Task titles in French first, whatever the user's language, where the
        database has French installed."""
        if "fr_FR" in dict(self.env["res.lang"].get_installed()):
            return records.with_context(lang="fr_FR")
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
            "phase_label": phase_label(engagement.phase),
            "section": SECTION_OF_PHASE[engagement.phase],
        }

    @api.model
    def _ea_ui_active_items(self, engagements):
        """The tasks on the file: a conditional task is not active until its
        trigger is answered."""
        return self._ea_ui_titled(self.env["ea.audit.file.item"].search([
            ("engagement_id", "in", engagements.ids), ("conditional", "=", False),
        ]))

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
        """What this open task asks of me, None when it asks nothing."""
        if not self._ea_ui_is_open(item):
            return None
        if is_partner and self._ea_ui_partner_awaited(item, policy):
            # the assigned reviewer goes first where the paper has one
            if item.state == "reviewed" or item.approver_id in (user, self.env["res.users"]):
                return "À signer"
        if item.state == "prepared" and item.approver_id == user:
            return "À réviser"
        if user in (item.preparer_id, item.assignee_id) and item.state in ("not_started", "in_progress"):
            return "À préparer" if item.state == "not_started" else "En cours"
        return None

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
            engagement = self.env["ea.audit.file.item"].search([("id", "=", res_id)], limit=1).engagement_id
        return self._ea_ui_mission(engagement) if engagement else False

    @api.model
    def ea_ui_search(self, term):
        """Missions by client, name or year, tasks by code or title, in the files
        the caller can open."""
        term = (term or "").strip()
        if len(term) < 2:
            return {"missions": [], "tasks": []}
        domain = ["|", ("client_id.name", "ilike", term), ("name", "ilike", term)]
        if term.isdigit():
            domain = ["|", ("fiscal_year", "=", int(term))] + domain
        engagements = self.env["ea.audit.engagement"].search(domain, limit=6)
        Item = self.env["ea.audit.file.item"]
        items = self._ea_ui_titled(Item).search(
            [("conditional", "=", False), "|", ("code", "=ilike", "%s%%" % term), ("template_id.title", "ilike", term)],
            limit=8,
        )
        return {
            "missions": [self._ea_ui_mission(engagement) for engagement in engagements],
            "tasks": [{
                "id": item.id,
                "code": item.code,
                "title": item.title,
                "mission": "%s, %s" % (item.engagement_id.client_id.name, item.engagement_id.fiscal_year),
            } for item in items],
        }

    # ------------------------------------------------------------------
    # The bell
    # ------------------------------------------------------------------

    @api.model
    def ea_ui_notifications(self):
        rows = self.env["ea.audit.notification"]._ea_ui_visible()
        return {
            "unread": len(rows.filtered(lambda row: not row.read_at)),
            "rows": [{
                "id": row.id,
                "kind": row.kind,
                "title": row.title,
                "detail": row.detail or "",
                "unread": not row.read_at,
                "created": fields.Datetime.to_string(row.create_date),
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
            mission = "%s, exercice %s" % (engagement.client_id.name, engagement.fiscal_year)
            own = items.filtered(lambda item: item.engagement_id == engagement)
            is_partner = user == engagement.engagement_partner_id or user == engagement.partner_delegate_id
            awaiting_acceptance = (
                is_partner and engagement.phase == "acceptance" and not engagement.sudo()._ea_approval_signed("P1.1")
            )
            to_review = own.filtered(
                lambda item: self._ea_ui_my_word(item, user, is_partner, policy) in ("À réviser", "À signer")
                # the acceptance has a row of its own
                and not (awaiting_acceptance and item.code == "P1.1")
            )
            if to_review:
                rows.append({
                    "title": "Feuilles de travail en attente de revue",
                    "mission": mission,
                    "count": len(to_review),
                    "engagement_id": engagement.id,
                    "item_ids": to_review.ids,
                })
            if awaiting_acceptance:
                acceptance = own.filtered(lambda item: item.code == "P1.1")
                rows.append({
                    "title": "Acceptation en attente de la signature de l'associé",
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
                    "title": "Tâches en retard",
                    "mission": mission,
                    "count": len(late),
                    "engagement_id": engagement.id,
                    "item_ids": late.ids,
                })
            uncommunicated = engagement.sudo()._ea_uncommunicated_significant_count() if is_partner else 0
            if uncommunicated:
                rows.append({
                    "title": "Déficience significative à communiquer",
                    "mission": mission,
                    "count": uncommunicated,
                    "engagement_id": engagement.id,
                    "tool": "action_tool_deficiencies",
                })
        invitations = self.env["ea.audit.team.member"].search([("user_id", "=", user.id), ("state", "=", "invited")])
        for invitation in invitations:
            rows.append({
                "title": "Invitation à répondre",
                "mission": "%s, exercice %s" % (invitation.invitation_client_name, invitation.invitation_fiscal_year),
                "count": 0,
                "invitation": True,
            })
        return rows

    @api.model
    def ea_ui_home(self):
        today = fields.Date.context_today(self)
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
                "nature": NATURE_LABELS.get(engagement.nature, ""),
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
    def _ea_ui_rings(self, items, done_ids):
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
                    "label": group.get("short") or group["title"],
                    "done": len([item for item in members if item.id in done_ids]),
                    "total": len(members),
                })
            done = sum(group["done"] for group in groups)
            total = sum(group["total"] for group in groups)
            # the group in hand: the first one with work left
            current = next((g["id"] for g in groups if g["total"] and g["done"] < g["total"]), None)
            rings.append({
                "key": section,
                "label": SECTION_LABELS[section],
                "done": done,
                "total": total,
                "pct": percent(done, total),
                "current_group": current,
                "groups": [group for group in groups if group["total"]],
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
            "text": "en retard de %s j" % self._ea_ui_late_days(item, today),
        } for item in late[:_LATE_CHIPS]]
        register = items.filtered(lambda item: item.code == "S3.1")[:1]
        if register:
            risks = self.env["ea.audit.risk"].search([
                ("engagement_id", "=", engagement.id), ("significant", "=", True), ("rebutted", "=", False),
                ("program_step_ids", "=", False),
            ]).with_context(lang=register.env.lang)
            chips += [{
                "id": register.id, "code": register.code, "title": risk.title, "tone": "r", "text": "sans procédure prévue",
            } for risk in risks[:2]]
        notes = self.env["ea.audit.review.note"].search([
            ("engagement_id", "=", engagement.id), ("state", "=", "open"), ("assignee_id", "=", self.env.uid),
        ])
        by_item = {item.id: item for item in items}
        chips += [{
            "id": note.file_item_id.id, "code": note.code, "title": by_item[note.file_item_id.id].short_title or by_item[note.file_item_id.id].title,
            "tone": "g", "text": "note de revue",
        } for note in notes if note.file_item_id.id in by_item][:3]
        awaiting = items.filtered(
            lambda item: not item.not_applicable and item.state in ("prepared", "reviewed") and item not in late
        )
        chips += [{
            "id": item.id, "code": item.code, "title": item.short_title or item.title, "tone": "g",
            "text": "à signer" if item.state == "reviewed" else "à réviser",
        } for item in awaiting[:_STRIP_CHIPS]]
        return chips[:_STRIP_CHIPS], late

    @api.model
    def ea_ui_dashboard(self, engagement_id):
        engagement = self._ea_ui_visible_engagement(engagement_id)
        if not engagement:
            return {"denied": True}
        today = fields.Date.context_today(self)
        user = self.env.user
        items = self._ea_ui_active_items(engagement)
        done_ids = self._ea_ui_done_ids(items)
        rings = self._ea_ui_rings(items, done_ids)
        archived = bool(engagement.archived_at or engagement.phase == "archived")
        policy = self.env["ea.audit.signoff.policy"]._ea_policy()
        is_partner = user == engagement.engagement_partner_id or user == engagement.partner_delegate_id

        # tasks with no preparer and no assignee; a done task needs nobody, and
        # nothing is handed out on an archived file
        unassigned = self.env["ea.audit.file.item"] if archived else items.filtered(
            lambda item: not item.preparer_id and not item.assignee_id and item.id not in done_ids
        )

        chips, late = self._ea_ui_attention_chips(engagement, items, today)

        mine = []
        for item in items:
            word = self._ea_ui_my_word(item, user, is_partner, policy)
            if word:
                mine.append({"id": item.id, "code": item.code, "title": item.short_title or item.title, "word": word})

        upcoming = items.filtered(
            lambda item: self._ea_ui_is_open(item) and not archived and self._ea_ui_due(item)
        ).sorted(lambda item: (self._ea_ui_due(item), item.sequence))
        calendar_rows = [{
            "id": item.id,
            "code": item.code,
            "title": item.short_title or item.title,
            "due": fmt_date(self._ea_ui_due(item)),
            "late_days": self._ea_ui_late_days(item, today),
            "status": STATUS_WORDS[self._ea_ui_status(item)],
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
            "my_tasks": {"count": len(mine), "rows": mine[:_MY_TASK_ROWS]},
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
                "detail": "Signé le %s" % fmt_date(fields.Date.context_today(self, signoff.signed_at)),
            }
        return {"name": short_name(name) if name else "Non assigné", "signed": False, "detail": waiting if name else ""}

    @api.model
    def _ea_ui_task_row(self, item, signoffs, partner, policy, today):
        own = signoffs.filtered(lambda s: s.file_item_id == item)
        by_role = {s.role: s for s in own}
        rule = self.env["ea.audit.signoff.policy"]._ea_effective_rule(item.code, policy)
        preparer_user = item.preparer_id or item.assignee_id
        preparer_waiting = "En cours" if item.state == "in_progress" else "Non commencé"
        reviewer_user = item.approver_id or partner
        if "partner" in by_role and "reviewer" not in by_role:
            reviewer_waiting = "Approbation de l'associé"
        elif "preparer" in by_role:
            reviewer_waiting = "En attente de révision"
        else:
            reviewer_waiting = "En attente du préparateur"
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
            "pill": pill,
            "tone": tone,
        }
        if rule["partner_required"]:
            waiting = "En attente de signature" if item.state in ("prepared", "reviewed") else "En attente du préparateur"
            row["partner"] = self._ea_ui_signer_cell(partner.name, by_role.get("partner"), waiting)
        return row

    @api.model
    def ea_ui_tasks(self, engagement_id, group_id):
        engagement = self._ea_ui_visible_engagement(engagement_id)
        group = GROUP_BY_ID.get(group_id)
        if not engagement or not group:
            return {"denied": True}
        today = fields.Date.context_today(self)
        items = self._ea_ui_active_items(engagement).filtered(lambda item: group_of_code(item.code)["id"] == group_id)
        signoffs = self._ea_ui_live_signoffs(items)
        done_ids = self._ea_ui_done_ids(items, signoffs)
        policy = self.env["ea.audit.signoff.policy"]._ea_policy()
        partner = engagement.engagement_partner_id
        return {
            "mission": self._ea_ui_mission(engagement),
            "group": {
                "id": group["id"],
                "code": group["code"],
                "title": group["title"],
                "section": group["section"],
                "section_label": SECTION_LABELS[group["section"]],
            },
            "done": len(done_ids & set(items.ids)),
            "total": len(items),
            "rows": [self._ea_ui_task_row(item, signoffs, partner, policy, today) for item in items],
        }
