from odoo import fields, models

from odoo.addons.ea_audit_core.services.errors import rule_error as core_rule_error

from ..rules import rule_error
from ..services.significant_accounts import unjustified_count


class Engagement(models.Model):
    """The guard of every write of the tools, the core's hooks, and the board screens."""

    _inherit = "ea.audit.engagement"

    def _ea_tool_guard(self):
        """requireWrite + F008 (accepted member) + assertMutable + the EQR's independence."""
        self.ensure_one()
        self._ea_require_write()
        self._ea_require_access()
        self._ea_assert_mutable()
        if self._ea_acts_as_eqr(self.env.user):
            raise core_rule_error(self.env, "eqr-read-only")

    def _ea_partner_tier_refusal(self):
        """partnerTierRefusalTx: this file's engagement partner or delegate, else a code."""
        self.ensure_one()
        partners, delegate = self._ea_partner_seat()
        if not partners:
            return "designate-engagement-partner-first"
        user = self.env.user
        return None if user in partners or (delegate and delegate == user) else "not-engagement-partner"

    def _ea_lock(self):
        self.env.cr.execute("SELECT id FROM ea_audit_engagement WHERE id IN %s FOR UPDATE", [tuple(self.ids)])

    def _ea_invalidate_signoffs(self, code):
        """A changed input voids the paper's live signatures, so they are given again (UAT B49)."""
        self.ensure_one()
        now = fields.Datetime.now()
        live = self.env["ea.audit.signoff"].sudo().search([
            ("engagement_id", "=", self.id), ("code", "=", code),
            ("voided_at", "=", False), ("invalidated_at", "=", False),
        ])
        if live:
            live.write({"invalidated_at": now})
            self._ea_log("signoffs_invalidated", "%s: %d signature(s) to give again" % (code, len(live)))
        return len(live)

    # ------------------------------------------------------------------
    # The core's hooks
    # ------------------------------------------------------------------

    def _ea_materiality_approved(self):
        """The planning gate reads the LATEST version, the paper any approved one (D.5)."""
        self.ensure_one()
        latest = self.env["ea.audit.materiality"].sudo().search(
            [("engagement_id", "=", self.id)], order="version_no desc", limit=1,
        )
        return latest.state == "approved"

    def _ea_unsupported_rely_count(self):
        self.ensure_one()
        cells = self.env["ea.audit.cra.assessment"].sudo().search(
            [("engagement_id", "=", self.id), ("cr", "=", "rely")],
        )
        return len(cells.filtered(
            lambda c: not (c.cr_basis or "").strip()
            and not self._ea_control_coverage(c.index_code, c.assertion)["covering"],
        ))

    def _ea_unlinked_significant_risk_count(self):
        self.ensure_one()
        return self.env["ea.audit.risk"].sudo().search_count([
            ("engagement_id", "=", self.id), ("significant", "=", True), ("rebutted", "=", False),
            ("program_step_ids", "=", False),
        ])

    def _ea_unapproved_rebuttal_count(self):
        self.ensure_one()
        return self.env["ea.audit.risk"].sudo().search_count([
            ("engagement_id", "=", self.id), ("rebutted", "=", True), ("rebuttal_approved_by_id", "=", False),
        ])

    def _ea_section_has_planned_step(self, item):
        return bool(self.env["ea.audit.program.step"].sudo().search_count([
            ("file_item_id", "=", item.id), ("status", "!=", "na"),
        ]))

    def _ea_unmapped_tb_account_count(self):
        """Engagements with no TB pass: the gate looks only at the current version's accounts."""
        self.ensure_one()
        version = self._ea_current_tb_version()
        if not version:
            return 0
        rules = self._ea_grouping_matchers()
        return len([code for code in set(version.line_ids.mapped("account_code")) if not rules(code)])

    def _ea_planning_snapshot_data(self):
        self.ensure_one()
        materiality = self._ea_approved_materiality()
        risks = self.env["ea.audit.risk"].sudo().search([("engagement_id", "=", self.id)])
        steps = self.env["ea.audit.program.step"].sudo().search([("engagement_id", "=", self.id)])
        return {
            "materiality": materiality and {
                "versionNo": materiality.version_no,
                "overall": materiality.overall,
                "performance": materiality.performance,
                "trivial": materiality.trivial,
            } or None,
            "risks": [{
                "id": risk.id, "description": risk.description, "significant": risk.significant,
                "rebutted": risk.rebutted, "rating": risk.inherent_rating, "status": risk.status,
                "stepIds": risk.program_step_ids.ids,
            } for risk in risks],
            "steps": [{
                "id": step.id, "code": step.file_item_id.code, "description": step.description,
                "status": step.status,
            } for step in steps],
        }

    # ------------------------------------------------------------------
    # What later tools answer: SCOT Studio and S2.5 are not built yet
    # ------------------------------------------------------------------

    def _ea_control_coverage(self, index_code, assertion):
        """Selected controls answering a WCGW on this index and assertion."""
        return {"covering": 0, "effective": 0, "failed": 0}

    def _ea_itgc_state(self):
        """The S2.5 conclusion: support, not_support, mixed, or None until concluded."""
        return None

    # ------------------------------------------------------------------
    # Screens
    # ------------------------------------------------------------------

    def _ea_board(self, view_xmlid, name):
        self.ensure_one()
        self._ea_require_access()
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": "ea.audit.engagement",
            "res_id": self.id,
            "view_mode": "form",
            "views": [(self.env.ref(view_xmlid).id, "form")],
            "target": "current",
            "context": {"ea_engagement_id": self.id},
        }

    def _ea_list(self, model, name, views, extra=None):
        self.ensure_one()
        self._ea_require_access()
        action = {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": model,
            "view_mode": ",".join(mode for _xmlid, mode in views),
            "views": [(self.env.ref(xmlid).id if xmlid else False, mode) for xmlid, mode in views],
            "domain": [("engagement_id", "=", self.id)],
            "context": {"default_engagement_id": self.id, "ea_engagement_id": self.id},
            "target": "current",
        }
        action.update(extra or {})
        return action

    def _ea_export_action(self, kind):
        self.ensure_one()
        self._ea_require_access()
        return {
            "type": "ir.actions.act_url",
            "url": "/ea_audit_tools/export/%s/%d" % (kind, self.id),
            "target": "self",
        }


class FileItem(models.Model):
    """The core's hooks on a task: tool-fed outputs, and the P6.2 refusal."""

    _inherit = "ea.audit.file.item"

    def _ea_tool_output_present(self, output):
        self.ensure_one()
        engagement = self.sudo().engagement_id
        if output == "materiality":
            return bool(engagement._ea_approved_materiality())
        if output == "tb":
            version = engagement._ea_current_tb_version()
            return bool(version) and version.validation_status == "valid"
        if output == "sad":
            return bool((engagement._ea_sad_meta(create=False).concl_text or "").strip())
        return False

    def _ea_paper_refusal(self, role):
        refusal = super()._ea_paper_refusal(role)
        if refusal or self.code != "P6.2":
            return refusal
        rows = self.sudo().engagement_id._ea_significance_rows()
        return "significance-unjustified" if unjustified_count(rows) else None
