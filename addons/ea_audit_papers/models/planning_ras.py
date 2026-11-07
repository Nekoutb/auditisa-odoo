"""The Planning Review & Approval Summary of P7.2: answers and signatures per engagement.
No plain ORM writes: every change goes through ea_ras_save and ea_ras_sign."""
from odoo import fields, models

from odoo.addons.ea_audit_core.services.signoff_rules import at_least

from ..services.completeness import js_trim
from ..services.planning_ras import (
    ALL_ITEMS,
    ANSWERS,
    ITEM_KEYS,
    SECTION_A,
    SECTION_B,
    SECTION_C,
    SIGNATURE_ROLES,
    outstanding,
    ras_gaps,
    unready_lines,
)
from .errors import paper_error, ras_incomplete_error

_RAS_CODE = "P7.2"
_ITEM_CODES = sorted({code for item in ALL_ITEMS for code in item["codes"]})


class PlanningRas(models.Model):
    _name = "ea.audit.planning.ras"
    _description = "Planning review and approval summary"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True, index=True, ondelete="cascade")
    answers = fields.Json(default=dict)
    signatures = fields.Json(default=dict)

    _engagement_uniq = models.Constraint("UNIQUE(engagement_id)", "One summary per engagement.")


class Engagement(models.Model):
    _inherit = "ea.audit.engagement"

    def _ea_ras(self, create=False):
        self.ensure_one()
        Ras = self.env["ea.audit.planning.ras"].sudo()
        ras = Ras.search([("engagement_id", "=", self.id)], limit=1)
        if not ras and create:
            ras = Ras.create({"engagement_id": self.id, "answers": {}, "signatures": {}})
        return ras

    def _ea_ras_task_states(self):
        items = self.env["ea.audit.file.item"].sudo().search([
            ("engagement_id", "=", self.id), ("code", "in", _ITEM_CODES), ("conditional", "=", False),
        ])
        return {item.code: "not_applicable" if item.not_applicable else item.state for item in items}

    def _ea_ras_partner_approved(self):
        """rasPartnerApprovedTx: the partner's signature on the summary, with every
        confirmation of sections A and B still answered and every "no" explained."""
        self.ensure_one()
        ras = self._ea_ras()
        if not ras or "partner" not in (ras.signatures or {}):
            return False
        # deliverables and the lower tiers were enforced when the partner signed
        return not ras_gaps(ras.answers or {}, {"fieldwork": 1, "manager": 1}, [], "partner")

    def _ea_ras_guard(self):
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_access()
        self._ea_assert_mutable()

    def _ea_ras_touch_paper(self):
        """The summary is part of P7.2's hash."""
        paper = self.env["ea.audit.paper"].sudo().search([("engagement_id", "=", self.id), ("code", "=", _RAS_CODE)], limit=1)
        if paper:
            paper._void_stale_signoffs()

    def ea_ras_save(self, key, value):
        """saveRasAnswer. Section B is the partner's first person, section C the quality reviewer's."""
        self._ea_ras_guard()
        key = key or ""
        base = key[:-2] if key.endswith("_x") else key
        if base not in ITEM_KEYS:
            raise paper_error(self.env, "ras-invalid-key")
        value = js_trim(value or "")
        if not key.endswith("_x") and value and value not in ANSWERS:
            raise paper_error(self.env, "ras-invalid-key")
        user = self.env.user
        role = user._ea_firm_role()
        floor = {"a": "senior", "b": "partner"}.get(key[0])
        if floor and not at_least(role, floor):
            raise paper_error(self.env, "ras-section-floor")
        if key[0] == "c" and not self.sudo()._ea_is_appointed_eqr(user):
            raise paper_error(self.env, "eqr-must-be-the-quality-reviewer")
        ras = self.sudo()._ea_ras(create=True)
        answers = dict(ras.answers or {})
        if value:
            answers[key] = value
        else:
            answers.pop(key, None)
        ras.answers = answers
        self.sudo()._ea_ras_touch_paper()
        return self.ea_ras_view()

    def ea_ras_sign(self, role, clear=False):
        """signRas. Withdrawing needs nothing; adding needs the summary ready."""
        self._ea_ras_guard()
        tier = next((row for row in SIGNATURE_ROLES if row["role"] == role), None)
        if not tier:
            raise paper_error(self.env, "ras-invalid-key")
        user = self.env.user
        as_root = self.sudo()
        if role == "partner":
            partners, delegate = as_root._ea_partner_seat()
            if not partners:
                raise paper_error(self.env, "designate-engagement-partner-first")
            if user not in partners and not (delegate and delegate == user):
                raise paper_error(self.env, "not-engagement-partner")
        elif role == "eqr":
            if not as_root._ea_is_appointed_eqr(user):
                raise paper_error(self.env, "eqr-must-be-the-quality-reviewer")
        elif not at_least(user._ea_firm_role(), tier["min"]):
            raise paper_error(self.env, "ras-section-floor")
        ras = as_root._ea_ras(create=True)
        signatures = dict(ras.signatures or {})
        if clear:
            signatures.pop(role, None)
        else:
            answers = ras.answers or {}
            gaps = ras_gaps(answers, signatures, unready_lines(answers, as_root._ea_ras_task_states()), role)
            if gaps:
                raise ras_incomplete_error(self.env, gaps)
            signatures[role] = {"name": user.name, "uid": user.id, "at": fields.Datetime.to_string(fields.Datetime.now())}
        ras.signatures = signatures
        self._ea_log(
            "ras_signature_cleared" if clear else "ras_signed",
            ("P7.2 summary: %s withdrawn by %s" if clear else "P7.2 summary: %s signed by %s") % (role, user.name),
        )
        as_root._ea_ras_touch_paper()
        return self.ea_ras_view()

    def ea_ras_view(self):
        """The summary as the board shows it. The client decides nothing."""
        self.ensure_one()
        self._ea_require_access()
        as_root = self.sudo()
        ras = as_root._ea_ras()
        answers = dict(ras.answers or {}) if ras else {}
        signatures = dict(ras.signatures or {}) if ras else {}
        states = as_root._ea_ras_task_states()
        unready = unready_lines(answers, states)
        role = self.env.user._ea_firm_role()
        readonly = as_root._ea_is_archived() or not role or role == "read_only"
        is_eqr = as_root._ea_is_appointed_eqr(self.env.user)
        partners, delegate = as_root._ea_partner_seat()
        is_partner = self.env.user in partners or (delegate and delegate == self.env.user)

        def section(letter, items, editable):
            return {
                "letter": letter,
                "editable": bool(editable) and not readonly,
                "items": [{
                    **item,
                    "answer": answers.get(item["key"], ""),
                    "why": answers.get("%s_x" % item["key"], ""),
                    "unready": item["key"] in unready,
                    "tasks": [{"code": code, "state": states.get(code, "absent")} for code in item["codes"]],
                } for item in items],
            }

        tiers = []
        for tier in SIGNATURE_ROLES:
            allowed = {"partner": is_partner, "eqr": is_eqr}.get(tier["role"], at_least(role, tier["min"]))
            tiers.append({
                **tier,
                "signature": signatures.get(tier["role"]) or False,
                "allowed": bool(allowed) and not readonly,
                "gaps": ras_gaps(answers, signatures, unready, tier["role"]),
            })
        return {
            "sections": [
                section("A", SECTION_A, at_least(role, "senior")),
                section("B", SECTION_B, at_least(role, "partner")),
                section("C", SECTION_C, is_eqr),
            ],
            "tiers": tiers,
            "outstanding": outstanding(answers),
            "approved": as_root._ea_ras_partner_approved(),
        }


class Paper(models.Model):
    _inherit = "ea.audit.paper"

    def _content_parts(self):
        parts = super()._content_parts()
        paper = self.sudo()
        if paper.code == _RAS_CODE:
            ras = paper.engagement_id._ea_ras()
            if ras and ras.answers:
                parts["ras"] = sorted([key, value] for key, value in ras.answers.items())
        return parts
