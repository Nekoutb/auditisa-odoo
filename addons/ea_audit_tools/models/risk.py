import re

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.signoff_rules import can_partner_signoff

from odoo.addons.ea_audit_core.services.phases import phase_still_open

from ..rules import rule_error
from ..services.assertions import clean_assertions
from ..services.lead_classes import LEAD_INDEX_BY_CODE
from ..services.risk_model import MGMT_OVERRIDE_PROCEDURE, PRESUMED_SEED, PRESUMED_TITLES, inherent_rating, risk_title
from .tool_record import is_french

RATING_SELECTION = [("low", "Low"), ("medium", "Medium"), ("high", "High")]
RISK_STATUS_SELECTION = [
    ("identified", "Identified"),
    ("response_planned", "Response planned"),
    ("response_executed", "Response executed"),
    ("concluded", "Concluded"),
]
CATEGORY_SELECTION = [("business", "Business"), ("fraud", "Fraud"), ("error", "Error")]
LEVEL_SELECTION = [("fs", "Financial statements"), ("assertion", "Assertion")]
STEP_STATUS_SELECTION = [("open", "Open"), ("done", "Done"), ("na", "Not applicable")]
_FACTOR = re.compile(r"^[a-z_]{1,40}$")


class ProgramStep(models.Model):
    """A planned procedure. The papers addon writes the results; the tools read the coverage."""

    _name = "ea.audit.program.step"
    _inherit = ["ea.audit.tool.record"]
    _description = "Audit program step"
    _order = "file_item_id, seq, id"
    _rec_name = "description"

    file_item_id = fields.Many2one("ea.audit.file.item", string="Task", required=True, index=True, ondelete="cascade")
    seq = fields.Integer(default=10)
    description = fields.Text(required=True)
    assertion_ids = fields.Many2many("ea.audit.assertion", string="Assertions")
    source = fields.Char(default="manual")
    status = fields.Selection(STEP_STATUS_SELECTION, default="open", required=True, index=True)
    na_rationale = fields.Text(string="N/A rationale")
    conclusion = fields.Text()
    completed_by_id = fields.Many2one("res.users", string="Completed by", ondelete="set null")
    completed_at = fields.Datetime(string="Completed on")
    risk_ids = fields.Many2many("ea.audit.risk", "ea_audit_risk_response", "program_step_id", "risk_id", string="Risks")

    def complete(self, conclusion):
        """completeStep: the conclusion, who reached it and when, together (assurance finding C7)."""
        self.ensure_one()
        self._ea_guard()
        if not (conclusion or "").strip():
            raise rule_error(self.env, "conclusion-required")
        step = self.sudo()
        if step.status != "open":
            raise rule_error(self.env, "not-found")
        still_open = phase_still_open("execution", step.engagement_id.phase, step.file_item_id.code)
        if still_open:
            raise rule_error(self.env, still_open)
        step.write({"status": "done", "conclusion": conclusion.strip(), "completed_by_id": self.env.user.id, "completed_at": fields.Datetime.now()})
        return True

    def uncomplete(self):
        """uncompleteStep: back to planned, with nothing of the earlier attribution left."""
        self.ensure_one()
        self._ea_guard()
        step = self.sudo()
        if step.status != "done":
            raise rule_error(self.env, "not-found")
        step.write({"status": "open", "conclusion": False, "completed_by_id": False, "completed_at": False})
        return True

    def action_open_complete(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": self.env._("Complete the step"), "res_model": "ea.audit.step.wizard",
            "view_mode": "form", "target": "new", "context": {"default_step_id": self.id, "default_mode": "complete"},
        }

    def action_open_na(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": self.env._("Not applicable"), "res_model": "ea.audit.step.wizard",
            "view_mode": "form", "target": "new", "context": {"default_step_id": self.id, "default_mode": "na"},
        }

    def action_uncomplete(self):
        self.uncomplete()
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def mark_na(self, rationale):
        """markStepNa."""
        self.ensure_one()
        self._ea_guard()
        if not (rationale or "").strip():
            raise rule_error(self.env, "rationale-required")
        self.sudo().write({"status": "na", "na_rationale": rationale})
        return True


class Risk(models.Model):
    _name = "ea.audit.risk"
    _inherit = ["ea.audit.tool.record"]
    _description = "Risk"
    _order = "id"
    _rec_name = "title"

    description = fields.Text(required=True)
    title = fields.Char(string="Risk", compute="_compute_title", compute_sudo=True)
    source = fields.Char()
    level = fields.Selection(LEVEL_SELECTION, default="assertion", required=True)
    category = fields.Selection(CATEGORY_SELECTION, default="business")
    likelihood = fields.Selection(RATING_SELECTION, default="medium", required=True)
    magnitude = fields.Selection(RATING_SELECTION, default="medium", required=True)
    inherent_rating = fields.Selection(RATING_SELECTION, compute="_compute_rating", store=True)
    significant = fields.Boolean()
    substantive_alone_insufficient = fields.Boolean(string="Substantive alone insufficient")
    controls_reliance = fields.Boolean(string="Controls reliance")
    status = fields.Selection(RISK_STATUS_SELECTION, default="identified", required=True)
    inherent_factors = fields.Char(string="Inherent risk factors")
    fs_note = fields.Text(string="Pervasive effect")
    presumed_type = fields.Selection([("revenue_fraud", "Revenue fraud"), ("mgmt_override", "Management override")], readonly=True)
    rebutted = fields.Boolean(readonly=True)
    rebuttal_justification = fields.Text(readonly=True)
    rebuttal_approved_by_id = fields.Many2one("res.users", string="Rebuttal approved by", ondelete="restrict", readonly=True)
    added_after_planning = fields.Boolean(readonly=True)
    addition_approved_by_id = fields.Many2one("res.users", string="Addition approved by", ondelete="restrict", readonly=True)
    created_by_id = fields.Many2one("res.users", string="Created by", ondelete="restrict", readonly=True)
    index_link_ids = fields.One2many("ea.audit.risk.index", "risk_id", string="Lead indexes")
    section_link_ids = fields.One2many("ea.audit.risk.section", "risk_id", string="Sections")
    program_step_ids = fields.Many2many("ea.audit.program.step", "ea_audit_risk_response", "risk_id", "program_step_id", string="Program steps")
    linked_step_count = fields.Integer(string="Steps", compute="_compute_links", compute_sudo=True)
    index_summary = fields.Char(string="Indexes", compute="_compute_links", compute_sudo=True)

    @api.depends("description", "presumed_type")
    @api.depends_context("lang")
    def _compute_title(self):
        locale = "fr" if is_french(self.env) else "en"
        for risk in self:
            risk.title = risk_title(risk.description or "", risk.presumed_type, locale)

    @api.depends("likelihood", "magnitude")
    def _compute_rating(self):
        for risk in self:
            risk.inherent_rating = inherent_rating(risk.likelihood or "medium", risk.magnitude or "medium")

    @api.depends("program_step_ids", "index_link_ids.index_code", "index_link_ids.assertion_ids")
    def _compute_links(self):
        for risk in self:
            risk.linked_step_count = len(risk.program_step_ids)
            risk.index_summary = " · ".join(
                "%s (%s)" % (link.index_code, ", ".join(link.assertion_ids.mapped("code"))) for link in risk.index_link_ids
            )

    def _ea_user_write(self, vals):
        """updateRisk. A presumed risk is never de-flagged through a plain update."""
        self._ea_only(vals, {
            "description", "level", "likelihood", "magnitude", "significant", "substantive_alone_insufficient",
            "controls_reliance", "status", "category", "inherent_factors", "fs_note",
        })
        self._ea_guard()
        self.env.cr.execute("SELECT id FROM ea_audit_risk WHERE id IN %s FOR UPDATE", [tuple(self.ids)])
        for risk in self.sudo():
            if risk.presumed_type and vals.get("significant") is False:
                raise rule_error(self.env, "not-rebuttable")
        self.sudo().write(vals)
        return True

    def link_index(self, index_code, assertions):
        """linkRiskToIndex: upsert on (risk, index). Only an index of the map is accepted."""
        self.ensure_one()
        self._ea_guard()
        if index_code not in LEAD_INDEX_BY_CODE:
            raise rule_error(self.env, "invalid-index")
        Link = self.env["ea.audit.risk.index"].sudo()
        as_root = self.sudo()
        codes = clean_assertions(assertions)
        tags = self.env["ea.audit.assertion"]._ea_from_codes(codes)
        found = Link.search([("risk_id", "=", as_root.id), ("index_code", "=", index_code)], limit=1)
        if found:
            found.assertion_ids = [(6, 0, tags.ids)]
        else:
            Link.create({
                "engagement_id": as_root.engagement_id.id, "risk_id": as_root.id,
                "index_code": index_code, "assertion_ids": [(6, 0, tags.ids)],
            })
        return True

    def unlink_index(self, index_code):
        self.ensure_one()
        self._ea_guard()
        self.env["ea.audit.risk.index"].sudo().search([
            ("risk_id", "=", self.sudo().id), ("index_code", "=", index_code),
        ]).unlink()
        return True

    def map_section(self, file_item, assertions):
        """mapRiskToSection."""
        self.ensure_one()
        self._ea_guard()
        as_root = self.sudo()
        if file_item.sudo().engagement_id != as_root.engagement_id:
            raise rule_error(self.env, "not-found")
        tags = self.env["ea.audit.assertion"]._ea_from_codes(clean_assertions(assertions))
        Section = self.env["ea.audit.risk.section"].sudo()
        found = Section.search([("risk_id", "=", as_root.id), ("file_item_id", "=", file_item.id)], limit=1)
        if found:
            found.assertion_ids = [(6, 0, tags.ids)]
        else:
            Section.create({
                "engagement_id": as_root.engagement_id.id, "risk_id": as_root.id,
                "file_item_id": file_item.id, "assertion_ids": [(6, 0, tags.ids)],
            })
        return True

    def link_step(self, step):
        """linkRiskToStep: the planned response. Identified moves to response_planned."""
        self.ensure_one()
        self._ea_guard()
        as_root = self.sudo()
        if step.sudo().engagement_id != as_root.engagement_id:
            raise rule_error(self.env, "not-found")
        as_root.program_step_ids = [(4, step.id)]
        if as_root.status == "identified":
            as_root.status = "response_planned"
        return True

    def rebut(self, justification):
        """rebutRevenueFraudRisk: the engagement partner's judgement, or their delegate's (F003)."""
        self.ensure_one()
        as_root = self.sudo()
        engagement = as_root.engagement_id.with_env(self.env)
        engagement._ea_tool_guard()
        if not can_partner_signoff(self.env.user._ea_firm_role()):
            raise rule_error(self.env, "rebut-partner-only")
        if not (justification or "").strip():
            raise rule_error(self.env, "justification-required")
        if as_root.presumed_type == "revenue_fraud":
            refusal = engagement._ea_partner_tier_refusal()
            if refusal:
                raise rule_error(self.env, refusal)
        else:
            raise rule_error(self.env, "not-rebuttable")
        as_root.write({
            "rebutted": True, "rebuttal_justification": justification,
            "rebuttal_approved_by_id": self.env.user.id, "significant": False, "status": "concluded",
        })
        engagement._ea_log("risk_rebutted", "Presumed revenue-fraud risk rebutted: %s" % justification.strip()[:160])
        return True

    def approve_addition(self):
        """approveRiskAddition (spec 8.4): the partner re-approves a mid-audit addition."""
        self.ensure_one()
        as_root = self.sudo()
        engagement = as_root.engagement_id.with_env(self.env)
        engagement._ea_tool_guard()
        if not can_partner_signoff(self.env.user._ea_firm_role()):
            raise rule_error(self.env, "forbidden")
        if not as_root.added_after_planning or as_root.addition_approved_by_id:
            raise rule_error(self.env, "not-found")
        as_root.addition_approved_by_id = self.env.user
        return True

    def action_open_rebut(self):
        return self.env["ea.audit.reason.wizard"]._ea_open("rebut", self)

    def action_open_index_link(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.env._("Link to a lead index"),
            "res_model": "ea.audit.risk.link.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_risk_id": self.id},
        }


class RiskIndex(models.Model):
    _name = "ea.audit.risk.index"
    _inherit = ["ea.audit.tool.record"]
    _description = "Risk to lead index"
    _rec_name = "index_code"

    risk_id = fields.Many2one("ea.audit.risk", required=True, ondelete="cascade", index=True)
    index_code = fields.Selection(selection="_lead_index_selection", string="Lead index", required=True)
    assertion_ids = fields.Many2many("ea.audit.assertion", string="Assertions")

    _uniq = models.Constraint("UNIQUE(risk_id, index_code)", "This risk already lands on that index.")


class RiskSection(models.Model):
    _name = "ea.audit.risk.section"
    _inherit = ["ea.audit.tool.record"]
    _description = "Risk to task"

    risk_id = fields.Many2one("ea.audit.risk", required=True, ondelete="cascade", index=True)
    file_item_id = fields.Many2one("ea.audit.file.item", string="Task", required=True, ondelete="cascade")
    assertion_ids = fields.Many2many("ea.audit.assertion", string="Assertions")

    _uniq = models.Constraint("UNIQUE(risk_id, file_item_id)", "This risk is already mapped to that task.")


class PotentialRisk(models.Model):
    """P5.2: raised from any planning form, then dismissed with rationale or promoted to S3.1."""

    _name = "ea.audit.potential.risk"
    _inherit = ["ea.audit.tool.record"]
    _description = "Potential risk"
    _order = "id"
    _rec_name = "description"

    description = fields.Text(required=True)
    source_code = fields.Char(string="Raised from", required=True)
    status = fields.Selection(
        [("open", "Open"), ("dismissed", "Dismissed"), ("promoted", "Promoted")], default="open", required=True,
    )
    dismissal_rationale = fields.Text()
    raised_by_id = fields.Many2one("res.users", string="Raised by", ondelete="restrict")
    decided_by_id = fields.Many2one("res.users", string="Decided by", ondelete="restrict")
    decided_at = fields.Datetime()

    def dismiss(self, rationale):
        """dismissPotentialRisk. A row already decided is refused, not ignored."""
        self.ensure_one()
        self._ea_guard()
        if not (rationale or "").strip():
            raise rule_error(self.env, "rationale-required")
        as_root = self.sudo()
        if as_root.status != "open":
            raise rule_error(self.env, "not-found")
        as_root.write({
            "status": "dismissed", "dismissal_rationale": rationale,
            "decided_by_id": self.env.user.id, "decided_at": fields.Datetime.now(),
        })
        return True

    def promote(self):
        """promotePotentialRisk: guarded, a concurrent promote of the same row fails cleanly."""
        self.ensure_one()
        self._ea_guard()
        self.env.cr.execute("SELECT status FROM ea_audit_potential_risk WHERE id = %s FOR UPDATE", [self.id])
        as_root = self.sudo()
        as_root.invalidate_recordset(["status"])
        if as_root.status != "open":
            raise rule_error(self.env, "not-found")
        as_root.write({"status": "promoted", "decided_by_id": self.env.user.id, "decided_at": fields.Datetime.now()})
        risk = self.env["ea.audit.risk"].sudo().create({
            "engagement_id": as_root.engagement_id.id,
            "description": as_root.description,
            "source": "P5.2 (%s)" % as_root.source_code,
            "created_by_id": self.env.user.id,
        })
        return risk.with_env(self.env)

    def action_promote(self):
        self.promote()
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def action_open_dismiss(self):
        return self.env["ea.audit.reason.wizard"]._ea_open("dismiss", self)


class EngagementRisk(models.Model):
    _inherit = "ea.audit.engagement"

    risk_ids = fields.One2many("ea.audit.risk", "engagement_id", string="Risks")
    potential_risk_ids = fields.One2many("ea.audit.potential.risk", "engagement_id", string="Potential risks")

    def _ea_seed_presumed_risks(self):
        """The two presumed ISA 240 risks. Revenue fraud is rebuttable, its procedures come from
        the S5.5 design, so the gate rightly waits on them. Management override is not, and its
        response is written into E3.1's programme here. Runs twice on a reclassified file: once."""
        self.ensure_one()
        Risk = self.env["ea.audit.risk"].sudo()
        items = self.env["ea.audit.file.item"].sudo()
        tags = self.env["ea.audit.assertion"]
        for presumed, section_code, assertions in PRESUMED_SEED:
            if Risk.search_count([("engagement_id", "=", self.id), ("presumed_type", "=", presumed)]):
                continue
            risk = Risk.create({
                "engagement_id": self.id,
                "description": PRESUMED_TITLES[presumed]["en"],
                "level": "assertion",
                "likelihood": "high",
                "magnitude": "high",
                "significant": True,
                "presumed_type": presumed,
                "source": "Auto-seeded (ISA 240)",
                "category": "fraud",
            })
            section = items.search([("engagement_id", "=", self.id), ("code", "=", section_code)], limit=1)
            if not section:
                continue
            codes = tags._ea_from_codes(assertions)
            self.env["ea.audit.risk.section"].sudo().create({
                "engagement_id": self.id, "risk_id": risk.id, "file_item_id": section.id,
                "assertion_ids": [(6, 0, codes.ids)],
            })
            if presumed == "mgmt_override":
                step = self.env["ea.audit.program.step"].sudo().create({
                    "engagement_id": self.id, "file_item_id": section.id, "seq": 10,
                    "description": MGMT_OVERRIDE_PROCEDURE, "assertion_ids": [(6, 0, codes.ids)],
                    "source": "risk_extension",
                })
                risk.write({"program_step_ids": [(4, step.id)], "status": "response_planned"})

    def add_risk(
        self, description, category="business", level="assertion", likelihood=None, magnitude=None, significant=False,
        factors=(), index=None, assertions=(), source=None, management_missed=None, fs_note=None,
    ):
        """addRisk: documented as it is added. After planning it needs the partner's approval."""
        self.ensure_one()
        description = (description or "").strip()
        if len(description) < 3:
            raise rule_error(self.env, "risk-description-required")
        self._ea_tool_guard()
        rating = lambda value: value if value in ("low", "high") else "medium"  # noqa: E731
        kept = [factor for factor in factors if _FACTOR.match(factor)][:10]
        text = description
        if (management_missed or "").strip():
            text = "%s [Not identified by management's risk process: %s]" % (description, management_missed.strip())
        origin = "Console (%s)" % source.strip()[:120] if (source or "").strip() else "Console"
        is_fs = level == "fs"
        risk = self.env["ea.audit.risk"].sudo().create({
            "engagement_id": self.id,
            "description": text,
            "source": origin,
            "level": "fs" if is_fs else "assertion",
            "category": category if category in ("fraud", "error") else "business",
            "likelihood": rating(likelihood),
            "magnitude": rating(magnitude),
            "significant": significant is True,
            "inherent_factors": ", ".join(kept) or False,
            "fs_note": (fs_note or "").strip() or False if is_fs else False,
            "added_after_planning": self.sudo().phase in ("execution", "conclusion"),
            "created_by_id": self.env.user.id,
        })
        if index and not is_fs and index in LEAD_INDEX_BY_CODE:
            risk.with_env(self.env).link_index(index, assertions)
        return risk.with_env(self.env)

    def raise_potential_risk(self, description, source_code):
        """raisePotentialRisk."""
        self.ensure_one()
        self._ea_tool_guard()
        if not (description or "").strip():
            raise rule_error(self.env, "description-required")
        record = self.env["ea.audit.potential.risk"].sudo().create({
            "engagement_id": self.id, "description": description.strip(),
            "source_code": source_code or "-", "raised_by_id": self.env.user.id,
        })
        return record.with_env(self.env)

    def add_program_step(self, file_item, description, assertions=(), source="manual"):
        self.ensure_one()
        self._ea_tool_guard()
        if file_item.sudo().engagement_id != self.sudo():
            raise rule_error(self.env, "not-found")
        if not (description or "").strip():
            raise rule_error(self.env, "description-required")
        step = self.env["ea.audit.program.step"].sudo().create({
            "engagement_id": self.id, "file_item_id": file_item.id, "description": description.strip(),
            "assertion_ids": [(6, 0, self.env["ea.audit.assertion"]._ea_from_codes(assertions).ids)],
            "source": source,
        })
        return step.with_env(self.env)

    def action_tool_risk(self):
        return self._ea_list(
            "ea.audit.risk", self.env._("Risk register"),
            [("ea_audit_tools.view_risk_list", "list"), ("ea_audit_tools.view_risk_form", "form")],
        )

    def action_tool_potential_risks(self):
        return self._ea_list(
            "ea.audit.potential.risk", self.env._("Potential risks"),
            [("ea_audit_tools.view_potential_risk_list", "list")],
        )

    def action_export_risks(self):
        return self._ea_export_action("risks")


class StepWizard(models.TransientModel):
    _name = "ea.audit.step.wizard"
    _description = "Complete a program step"

    step_id = fields.Many2one("ea.audit.program.step", required=True)
    mode = fields.Selection([("complete", "Complete"), ("na", "Not applicable")], default="complete", required=True)
    text = fields.Text(string="Conclusion or rationale", required=True)

    def action_save(self):
        self.ensure_one()
        if self.mode == "na":
            self.step_id.mark_na(self.text)
        else:
            self.step_id.complete(self.text)
        return {"type": "ir.actions.client", "tag": "soft_reload"}
