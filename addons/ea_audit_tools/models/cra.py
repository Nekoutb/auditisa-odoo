from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.errors import AuditRuleError

from ..rules import rule_error
from ..services.assertions import ASSERTIONS
from ..services.cra_board import (
    cell_level, default_relevance, is_rely_unsupported, page_progress, row_worst_tod, suggested_cr, suggested_ir,
)
from ..services.cra_model import cells_to_assess, cr_basis_label, threshold_suggestion, timing_suggestion, to_tod
from ..services.lead_classes import INDEX_SECTION, LEAD_INDEX_BY_CODE, lead_index_label
from .tool_record import ASSERTION_SELECTION, grouped, is_french

IR_SELECTION = [("lower", "Lower"), ("higher", "Higher")]
CR_SELECTION = [("rely", "Rely"), ("not_rely", "Not rely")]
LEVEL_SELECTION = [("minimal", "Minimal"), ("low", "Low"), ("moderate", "Moderate"), ("high", "High")]
TOD_SELECTION = [
    ("minimal", "Minimal"), ("low", "Low"), ("low_sr", "Low +SR"),
    ("moderate", "Moderate"), ("high", "High"), ("high_sr", "High +SR"),
]
CELL_SELECTION = LEVEL_SELECTION + [("to_assess", "To assess"), ("na", "Not applicable")]


class CraAssessment(models.Model):
    """One cell: a lead index x an assertion. ``recorded`` is cra_assessment's row existing:
    an unrecorded cell only carries what the file suggests until someone saves it."""

    _name = "ea.audit.cra.assessment"
    _inherit = ["ea.audit.tool.record"]
    _description = "Combined risk assessment cell"
    _order = "row_id, sequence"
    _rec_name = "assertion"

    row_id = fields.Many2one("ea.audit.cra.row", required=True, ondelete="cascade", index=True)
    index_code = fields.Selection(selection="_lead_index_selection", string="Lead index", required=True, index=True)
    assertion = fields.Selection(ASSERTION_SELECTION, required=True)
    sequence = fields.Integer(default=10)
    recorded = fields.Boolean(readonly=True)
    relevant = fields.Boolean(default=True)
    relevant_defaulted = fields.Boolean(readonly=True)
    ir = fields.Selection(IR_SELECTION, string="Inherent risk")
    ir_basis = fields.Char(string="Inherent risk basis")
    cr = fields.Selection(CR_SELECTION, string="Control risk")
    cr_basis = fields.Char(string="Control risk basis")
    reason = fields.Char(string="Revision reason", compute="_compute_reason", inverse="_inverse_noop")
    level = fields.Selection(LEVEL_SELECTION + [("to_assess", "To assess")], compute="_compute_derived", compute_sudo=True)
    tod_level = fields.Selection(TOD_SELECTION, string="Sampling level", compute="_compute_derived", compute_sudo=True)
    suggested_ir = fields.Selection(IR_SELECTION, string="Suggested inherent risk", compute="_compute_derived", compute_sudo=True)
    suggested_cr = fields.Selection(CR_SELECTION, string="Suggested control risk", compute="_compute_derived", compute_sudo=True)
    risk_count = fields.Integer(string="Risks", compute="_compute_derived", compute_sudo=True)
    significant = fields.Boolean(string="Significant risk", compute="_compute_derived", compute_sudo=True)
    fraud = fields.Boolean(compute="_compute_derived", compute_sudo=True)
    controls_covering = fields.Integer(string="Controls", compute="_compute_derived", compute_sudo=True)
    threshold_hint = fields.Char(string="Key items", compute="_compute_derived", compute_sudo=True)
    timing_hint = fields.Char(string="Timing", compute="_compute_derived", compute_sudo=True)
    history_ids = fields.One2many("ea.audit.cra.history", "assessment_id", string="History")

    _uniq = models.Constraint("UNIQUE(engagement_id, index_code, assertion)", "One cell per index and assertion.")

    def _compute_reason(self):
        self.reason = False

    def _inverse_noop(self):
        """The value arrives through _ea_user_write, never through here."""

    @api.depends("ir", "cr", "index_code", "assertion")
    def _compute_derived(self):
        locale = "fr" if is_french(self.env) else "en"
        for engagement in self.engagement_id:
            risks = engagement._ea_risk_cells()
            itgc = engagement._ea_itgc_state()
            for cell in self.filtered(lambda c: c.engagement_id == engagement):
                risk = risks.get(cell.index_code, {}).get(cell.assertion) or {"count": 0, "significant": False, "fraud": False}
                coverage = engagement._ea_control_coverage(cell.index_code, cell.assertion)
                ir_suggested = suggested_ir(risk["count"])
                cr_suggested = suggested_cr(coverage["covering"], coverage["failed"], itgc)
                # The level waits for both choices: the suggestions are shown, never used (2026-11-16).
                level = cell_level(cell.ir, cell.cr)
                assessed = level != "to_assess"
                cell.suggested_ir = ir_suggested
                cell.suggested_cr = cr_suggested
                cell.risk_count = risk["count"]
                cell.significant = risk["significant"]
                cell.fraud = risk["fraud"]
                cell.controls_covering = coverage["covering"]
                cell.level = level
                cell.tod_level = to_tod(level, risk["significant"]) if assessed else False
                cell.threshold_hint = threshold_suggestion(level, locale) if assessed else False
                cell.timing_hint = timing_suggestion(level, locale) if assessed else False

    def _ea_user_write(self, vals):
        self._ea_only(vals, {"relevant", "ir", "ir_basis", "cr", "cr_basis", "reason"})
        for cell in self:
            cell._ea_save_cell(vals)
        self.invalidate_recordset()
        return True

    def ea_cra_page_save(self, patch):
        """One click on the one-page CRA: the cell is written through its own rule-bearing
        path (never through its row), then the page is read again."""
        self.ensure_one()
        self.write(dict(patch or {}))
        engagement = self.sudo().engagement_id.with_env(self.env)
        return engagement.ea_cra_page()

    def _ea_save_cell(self, patch):
        """saveCraCell, in the source's order. Clearing a value is False here, "" there."""
        self.ensure_one()
        self._ea_guard()
        as_root = self.sudo()
        engagement = as_root.engagement_id
        if patch.get("cr") == "rely":
            coverage = engagement._ea_control_coverage(as_root.index_code, as_root.assertion)
            # Switching to rely needs a basis written for that decision in the same
            # request: the old not-rely basis is no reason to rely (UAT B51).
            basis = patch.get("cr_basis", as_root.cr_basis or "") if as_root.cr == "rely" else patch.get("cr_basis", "")
            if is_rely_unsupported(coverage["covering"], engagement._ea_itgc_state(), basis):
                raise rule_error(self.env, "rely-without-controls")
        next_ir = patch["ir"] if "ir" in patch else as_root.ir
        next_cr = patch["cr"] if "cr" in patch else as_root.cr
        # A revision changes a risk already chosen; filling the other, still blank one (the
        # one-page CRA saves IR and CR one click at a time) is the first assessment, not a revision.
        reassessed = bool((as_root.ir and next_ir != as_root.ir) or (as_root.cr and next_cr != as_root.cr))
        reason = (patch.get("reason") or "").strip()
        if reassessed:
            if not reason and engagement._ea_assessment_locked():
                raise rule_error(self.env, "reassessment-reason-required")
            self.env["ea.audit.cra.history"].sudo().create({
                "engagement_id": engagement.id, "assessment_id": as_root.id,
                "index_code": as_root.index_code, "assertion": as_root.assertion,
                "ir": as_root.ir, "ir_basis": as_root.ir_basis, "cr": as_root.cr, "cr_basis": as_root.cr_basis,
                "new_ir": next_ir, "new_cr": next_cr, "reason": reason or False, "changed_by_id": self.env.user.id,
            })
        values = {"recorded": True, "relevant_defaulted": False}
        for key in ("relevant", "ir", "ir_basis", "cr", "cr_basis"):
            if key in patch:
                values[key] = patch[key]
        as_root.write(values)
        engagement._ea_invalidate_signoffs("S3.1")
        if reassessed:
            engagement._ea_log(
                "reassessed",
                "CRA %s/%s reassessed: IR %s→%s, CR %s→%s%s" % (
                    as_root.index_code, as_root.assertion, self._ea_prior(values, "ir"), next_ir or "—",
                    self._ea_prior(values, "cr"), next_cr or "—", " (%s)" % reason if reason else "",
                ),
            )
        return True

    def _ea_prior(self, _values, field):
        history = self.sudo().history_ids.sorted("id", reverse=True)[:1]
        return history[field] or "—"


class CraHistory(models.Model):
    _name = "ea.audit.cra.history"
    _inherit = ["ea.audit.tool.record"]
    _description = "Combined risk assessment history"
    _order = "id desc"

    assessment_id = fields.Many2one("ea.audit.cra.assessment", required=True, ondelete="cascade", index=True)
    index_code = fields.Char(string="Lead index", required=True)
    assertion = fields.Char(required=True)
    ir = fields.Selection(IR_SELECTION, string="Inherent risk")
    ir_basis = fields.Char(string="Inherent risk basis")
    cr = fields.Selection(CR_SELECTION, string="Control risk")
    cr_basis = fields.Char(string="Control risk basis")
    new_ir = fields.Selection(IR_SELECTION, string="New inherent risk")
    new_cr = fields.Selection(CR_SELECTION, string="New control risk")
    reason = fields.Char()
    changed_by_id = fields.Many2one("res.users", string="Changed by", ondelete="restrict")


class CraRow(models.Model):
    """One board line: a significant account across the six assertions (m13)."""

    _name = "ea.audit.cra.row"
    _inherit = ["ea.audit.tool.record"]
    _description = "Combined risk assessment row"
    _order = "sequence, id"
    _rec_name = "index_code"

    index_code = fields.Selection(selection="_lead_index_selection", string="Significant account", required=True, index=True)
    sequence = fields.Integer(default=10)
    closing = fields.Float(digits=(18, 0))
    key_item_threshold = fields.Float(string="Key-item threshold", digits=(18, 0))
    task_code = fields.Char(string="Task", compute="_compute_task_code")
    cell_ids = fields.One2many("ea.audit.cra.assessment", "row_id", string="Cells")
    cell_c = fields.Selection(CELL_SELECTION, string="C", compute="_compute_cells", compute_sudo=True)
    cell_e = fields.Selection(CELL_SELECTION, string="E", compute="_compute_cells", compute_sudo=True)
    cell_a = fields.Selection(CELL_SELECTION, string="A", compute="_compute_cells", compute_sudo=True)
    cell_v = fields.Selection(CELL_SELECTION, string="V", compute="_compute_cells", compute_sudo=True)
    cell_p = fields.Selection(CELL_SELECTION, string="P", compute="_compute_cells", compute_sudo=True)
    cell_ro = fields.Selection(CELL_SELECTION, string="RO", compute="_compute_cells", compute_sudo=True)
    worst_tod = fields.Selection(TOD_SELECTION, string="Sampling level", help="Highest combined risk among the relevant assertions", compute="_compute_cells", compute_sudo=True)

    _uniq = models.Constraint("UNIQUE(engagement_id, index_code)", "One board line per lead index.")

    @api.depends("index_code")
    def _compute_task_code(self):
        for row in self:
            row.task_code = INDEX_SECTION.get(row.index_code) or False

    @api.depends("cell_ids.relevant", "cell_ids.ir", "cell_ids.cr")
    def _compute_cells(self):
        for row in self:
            cells = {cell.assertion: cell for cell in row.cell_ids}
            for code in ASSERTIONS:
                cell = cells.get(code)
                if not cell or not cell.relevant:
                    value = "na"
                elif not cell.ir or not cell.cr:
                    value = "to_assess"
                else:
                    value = cell.level
                row["cell_%s" % code.lower()] = value
            # An RO cell on the board only by default and unassessed is "to be assessed",
            # not an assessment: it stays out of the roll-up (F041).
            # Sampling waits until every kept cell is chosen: no suggestion stands in (2026-11-16).
            row.worst_tod = row_worst_tod([{
                "ir": cell.ir, "cr": cell.cr, "significant": cell.significant,
                "kept": cell.relevant and not (
                    cell.assertion == "RO" and cell.relevant_defaulted and not cell.ir and not cell.cr
                ),
            } for cell in row.cell_ids]) or False

    def _ea_user_write(self, vals):
        """saveIndexThreshold: above zero, or cleared so TE applies again. Voids S3.1 (UAT B49)."""
        self._ea_only(vals, {"key_item_threshold"})
        self._ea_guard()
        threshold = vals["key_item_threshold"]
        if threshold and threshold <= 0:
            raise rule_error(self.env, "invalid-threshold")
        for row in self.sudo():
            row.write({"key_item_threshold": threshold or 0})
            row.engagement_id._ea_invalidate_signoffs("S3.1")
        return True


class EngagementCra(models.Model):
    _inherit = "ea.audit.engagement"

    cra_row_ids = fields.One2many("ea.audit.cra.row", "engagement_id", string="Combined risk assessment")
    cra_to_assess_label = fields.Char(string="Cells to assess", compute="_compute_cra_cards", compute_sudo=True)
    cra_to_assess_count = fields.Integer(compute="_compute_cra_cards", compute_sudo=True)
    cra_unlinked_risk_label = fields.Text(string="Significant risks with no account", compute="_compute_cra_cards", compute_sudo=True)
    cra_missing = fields.Selection(
        [("tb", "Trial balance"), ("materiality", "Materiality"), ("significance", "Significant accounts")],
        string="What the grid is waiting for", compute="_compute_cra_cards", compute_sudo=True,
    )

    def _compute_cra_cards(self):
        fr = is_french(self.env)
        for engagement in self:
            count = len(engagement._ea_cra_to_assess())
            engagement.cra_to_assess_count = count
            engagement.cra_to_assess_label = self.env._("%(count)s cells to assess", count=count)
            risks = self.env["ea.audit.risk"].sudo().with_context(lang="fr_FR" if fr else "en_US").search([
                ("engagement_id", "=", engagement.id), ("significant", "=", True), ("rebutted", "=", False),
                ("level", "=", "assertion"), ("index_link_ids", "=", False),
            ])
            engagement.cra_unlinked_risk_label = ", ".join(risks.mapped("title")) or False
            engagement.cra_missing = engagement._ea_cra_missing()

    def _ea_cra_missing(self):
        """F068: an empty grid says which step upstream is the one still open, the first in order."""
        self.ensure_one()
        if self.cra_row_ids:
            return False
        if not self._ea_current_tb_version():
            return "tb"
        if not self._ea_approved_materiality():
            return "materiality"
        return "significance"

    def _ea_cra_to_assess(self):
        self.ensure_one()
        cells = self.env["ea.audit.cra.assessment"].sudo().search([("engagement_id", "=", self.id)])
        rows = {}
        for cell in cells:
            rows.setdefault(cell.index_code, []).append({
                "assertion": cell.assertion, "relevant": cell.relevant, "ir": cell.ir or None, "cr": cell.cr or None,
            })
        return cells_to_assess([{"indexCode": code, "cells": entries} for code, entries in rows.items()])

    def _ea_assessment_locked(self):
        """Once planning closes or materiality is approved, a revision is a documented judgement."""
        self.ensure_one()
        return self.sudo().phase not in ("acceptance", "planning") or bool(self._ea_approved_materiality())

    def _ea_risk_cells(self):
        """Per index and assertion: the live risks, whether one is significant, whether one is fraud."""
        self.ensure_one()
        links = self.env["ea.audit.risk.index"].sudo().search([
            ("engagement_id", "=", self.id), ("risk_id.rebutted", "=", False),
        ])
        out = {}
        for link in links:
            risk = link.risk_id
            for code in link.assertion_ids.mapped("code"):
                cell = out.setdefault(link.index_code, {}).setdefault(code, {"count": 0, "significant": False, "fraud": False})
                cell["count"] += 1
                cell["significant"] = cell["significant"] or risk.significant
                cell["fraud"] = cell["fraud"] or risk.category == "fraud" or bool(risk.presumed_type)
        return out

    def _ea_sync_cra(self):
        """The board's lines: significant indexes, plus any index holding a saved cell or a
        threshold, which stays visible even if P6.2 later reclassified it."""
        self.ensure_one()
        if self.sudo()._ea_is_archived():
            return
        self._ea_sync_significance()
        rows = {row["index"]: row for row in self._ea_significance_rows() if row["status"] == "significant"}
        records = {r.index_code: r for r in self.env["ea.audit.significance"].sudo().search([("engagement_id", "=", self.id)])}
        derived = self._ea_risk_derived_assertions()
        Row = self.env["ea.audit.cra.row"].sudo()
        Cell = self.env["ea.audit.cra.assessment"].sudo()
        existing = {row.index_code: row for row in Row.search([("engagement_id", "=", self.id)])}
        order = {code: position for position, code in enumerate(LEAD_INDEX_BY_CODE)}
        for code in [code for code, row in existing.items() if (
            code not in rows and not row.key_item_threshold and not row.cell_ids.filtered("recorded")
        )]:
            existing.pop(code).unlink()
        for code, significance in rows.items():
            row = existing.get(code)
            if row:
                row.write({"closing": significance["closing"]})
            else:
                row = Row.create({
                    "engagement_id": self.id, "index_code": code,
                    "closing": significance["closing"], "sequence": order.get(code, 999),
                })
            defaults = default_relevance(
                records[code].assertion_ids.mapped("code") if code in records else [], derived.get(code, ()),
            )
            cells = {cell.assertion: cell for cell in row.cell_ids}
            for position, assertion in enumerate(ASSERTIONS):
                relevant, defaulted = defaults[assertion]
                cell = cells.get(assertion)
                if not cell:
                    Cell.create({
                        "engagement_id": self.id, "row_id": row.id, "index_code": code, "assertion": assertion,
                        "sequence": position, "relevant": relevant, "relevant_defaulted": defaulted,
                    })
                elif not cell.recorded:
                    if (cell.relevant, cell.relevant_defaulted) != (relevant, defaulted):
                        cell.write({"relevant": relevant, "relevant_defaulted": defaulted})
                elif relevant and not defaulted and not cell.relevant:
                    # An assertion ticked on P6.2 (or carried by a risk) after the cell was saved
                    # comes onto the page; a saved assessment is never hidden by a later untick.
                    cell.write({"relevant": True, "relevant_defaulted": False})

    def cra_rollup_by_index(self):
        """craRollupByIndex: what sampling and S5.5 consume."""
        self.ensure_one()
        return {row.index_code: row.worst_tod for row in self.cra_row_ids if row.worst_tod}

    def action_tool_cra(self):
        """The one-page CRA (owner's mock-up of 2026-11-16)."""
        self.ensure_one()
        self._ea_require_access()
        self.sudo()._ea_sync_cra()
        return {
            "type": "ir.actions.client", "tag": "ea_audit_tools.cra_page", "target": "current",
            "name": self.env._("Combined risk assessment"),
            "params": {"engagement_id": self.id},
            "context": {"active_id": self.id, "ea_engagement_id": self.id},
        }

    def _ea_cra_read_only(self):
        """None when the user may assess; otherwise why not: "archived" or "role"."""
        self.ensure_one()
        if self.sudo()._ea_is_archived():
            return "archived"
        try:
            self._ea_tool_guard()
        except AuditRuleError:
            return "role"
        return None

    def ea_cra_page(self):
        """What the one-page CRA shows: the significant accounts, each with only its relevant
        assertions, the choices, the suggestions beside them and the combined level."""
        self.ensure_one()
        self._ea_require_access()
        root = self.sudo()
        fr = is_french(self.env)
        locale = "fr" if fr else "en"
        lang = "fr_FR" if fr else "en_US"
        Cell = self.env["ea.audit.cra.assessment"].with_context(lang=lang)
        Row = self.env["ea.audit.cra.row"].with_context(lang=lang)
        levels = dict(Cell._fields["level"]._description_selection(Cell.env))
        tods = dict(Row._fields["worst_tod"]._description_selection(Row.env))
        names = {a.code: a.name for a in self.env["ea.audit.assertion"].sudo().with_context(lang=lang).search([])}
        significant = {row["index"] for row in root._ea_significance_rows() if row["status"] == "significant"}
        itgc = root._ea_itgc_state()
        accounts, every = [], []
        for row in root.cra_row_ids.filtered(lambda r: r.index_code in significant).sorted(lambda r: (r.sequence, r.id)):
            cells = []
            for cell in row.cell_ids.filtered("relevant").sorted(lambda c: (c.sequence, c.id)):
                basis = [cr_basis_label(cell.cr_basis, locale)] if cell.cr_basis else []
                if cell.ir_basis and cell.ir_basis not in basis:
                    basis.append(cell.ir_basis)
                cells.append({
                    "id": cell.id, "assertion": cell.assertion, "name": names.get(cell.assertion, cell.assertion),
                    "ir": cell.ir or False, "cr": cell.cr or False,
                    "suggested_ir": cell.suggested_ir, "suggested_cr": cell.suggested_cr,
                    "level": cell.level, "level_label": levels.get(cell.level, cell.level),
                    "significant": cell.significant, "risk_count": cell.risk_count,
                    "rely_needs_basis": cell.controls_covering == 0 or itgc == "not_support",
                    "basis": " · ".join(basis),
                })
                every.append({"relevant": True, "ir": cell.ir, "cr": cell.cr})
            done, total = page_progress([{"relevant": True, "ir": c["ir"], "cr": c["cr"]} for c in cells])
            definition = LEAD_INDEX_BY_CODE.get(row.index_code)
            accounts.append({
                "id": row.id, "code": row.index_code,
                "label": lead_index_label(definition, locale) if definition else row.index_code,
                "closing": grouped(row.closing or 0, lang),
                "task": row.task_code or False,
                "relevant": [c["assertion"] for c in cells],
                "worst": row.worst_tod or False,
                "worst_label": tods.get(row.worst_tod) if row.worst_tod else levels["to_assess"],
                "done": done, "total": total, "cells": cells,
            })
        done, total = page_progress(every)
        reason = self._ea_cra_read_only()
        return {
            "engagement": root.display_name,
            "readonly": bool(reason), "archived": reason == "archived",
            "locked": root._ea_assessment_locked(),
            "missing": root._ea_cra_missing() if not root.cra_row_ids else (False if accounts else "significance"),
            "unlinked": root.cra_unlinked_risk_label or False,
            "progress": {"done": done, "total": total},
            "choices": {
                "ir": Cell._fields["ir"]._description_selection(Cell.env),
                "cr": Cell._fields["cr"]._description_selection(Cell.env),
            },
            "accounts": accounts,
        }

    def ea_cra_page_open(self, method):
        """The page's links to the steps upstream and to the Excel list."""
        self.ensure_one()
        if method not in ("action_tool_tb", "action_tool_materiality", "action_tool_significance", "action_tool_cra_cells"):
            raise rule_error(self.env, "forbidden")
        return getattr(self, method)()

    def action_tool_cra_cells(self):
        self.sudo()._ea_sync_cra()
        return self._ea_list(
            "ea.audit.cra.assessment", self.env._("Combined risk assessment: cells"),
            [("ea_audit_tools.view_cra_cell_list", "list")],
            {"context": {"ea_engagement_id": self.id, "search_default_group_index": 1}},
        )

    def action_export_cra(self):
        return self._ea_export_action("cra")
