import re

from markupsafe import Markup

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.signoff_rules import can_partner_signoff

from odoo.addons.ea_audit_core.services.phases import phase_still_open

from ..rules import rule_error
from ..services.lead_classes import INDEX_SECTION
from ..services.assertions import clean_assertions
from ..services.lead_classes import LEAD_INDEX_BY_CODE
from ..services.risk_model import MGMT_OVERRIDE_PROCEDURE, PRESUMED_SEED, PRESUMED_TITLES, inherent_rating, risk_title
from .tool_record import is_french

RATING_SELECTION = [("low", "Low"), ("medium", "Medium"), ("high", "High")]
REBUTTAL_STATE_SELECTION = [
    ("proposed", "Awaiting partner approval"),
    ("approved", "Approved by the partner"),
    ("rejected", "Rejected by the partner"),
]
# The presumed revenue-fraud risk sits on revenue until a rebuttal is approved.
REVENUE_INDEX = "UA"
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
    # Owner's ruling of 2026-11-15: anyone on the team proposes the rebuttal, the engagement
    # partner (or delegate) approves or rejects it. Until approved the risk stays live and linked.
    rebuttal_state = fields.Selection(REBUTTAL_STATE_SELECTION, string="Rebuttal", readonly=True)
    rebuttal_proposed_by_id = fields.Many2one("res.users", string="Rebuttal proposed by", ondelete="restrict", readonly=True)
    rebuttal_proposed_at = fields.Datetime(string="Rebuttal proposed on", readonly=True)
    rebuttal_decided_at = fields.Datetime(string="Rebuttal decided on", readonly=True)
    rebuttal_rejected_by_id = fields.Many2one("res.users", string="Rebuttal rejected by", ondelete="restrict", readonly=True)
    rebuttal_rejection = fields.Text(string="Why the rebuttal was rejected", readonly=True)
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
        # The account's paper is where the response lives: a program generated for it finds the risk.
        task = INDEX_SECTION.get(index_code)
        item = self.env["ea.audit.file.item"].sudo().search(
            [("engagement_id", "=", as_root.engagement_id.id), ("code", "=", task)], limit=1,
        ) if task else None
        if item:
            Section = self.env["ea.audit.risk.section"].sudo()
            if not Section.search_count([("risk_id", "=", as_root.id), ("file_item_id", "=", item.id)]):
                Section.create({
                    "engagement_id": as_root.engagement_id.id, "risk_id": as_root.id,
                    "file_item_id": item.id, "assertion_ids": [(6, 0, tags.ids)],
                })
        return True

    def action_open_step_link(self):
        """The planned response, picked from the file's program."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": self.env._("Link a program step"), "res_model": "ea.audit.risk.step.wizard",
            "view_mode": "form", "target": "new",
            "context": {"default_risk_id": self.id, "default_engagement_id": self.sudo().engagement_id.id},
        }

    def unlink_index(self, index_code):
        self.ensure_one()
        self._ea_guard()
        self._ea_refuse_revenue_unlink(index_code)
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

    def _ea_refuse_revenue_unlink(self, index_code):
        """The presumed revenue-fraud risk leaves revenue only through an approved rebuttal."""
        as_root = self.sudo()
        if as_root.presumed_type == "revenue_fraud" and not as_root.rebutted and index_code == REVENUE_INDEX:
            raise rule_error(self.env, "revenue-fraud-link-locked")

    def propose_rebuttal(self, justification):
        """Step 1 (owner's ruling of 2026-11-15): anyone on the team writes why revenue does not
        carry the presumed fraud risk. The risk stays live and linked until the partner approves."""
        self.ensure_one()
        as_root = self.sudo()
        engagement = as_root.engagement_id.with_env(self.env)
        engagement._ea_tool_guard()
        if as_root.presumed_type != "revenue_fraud" or as_root.rebutted:
            raise rule_error(self.env, "not-rebuttable")
        if as_root.rebuttal_state == "proposed":
            raise rule_error(self.env, "rebuttal-already-proposed")
        text = (justification or "").strip()
        if not text:
            raise rule_error(self.env, "justification-required")
        as_root.write({
            "rebuttal_state": "proposed", "rebuttal_justification": text,
            "rebuttal_proposed_by_id": self.env.user.id, "rebuttal_proposed_at": fields.Datetime.now(),
            "rebuttal_rejected_by_id": False, "rebuttal_rejection": False, "rebuttal_decided_at": False,
        })
        engagement._ea_log(
            "rebuttal_proposed",
            "Rebuttal of the presumed revenue-fraud risk proposed by %s: %s" % (self.env.user.name, " ".join(text.split())[:160]),
        )
        return True

    def _ea_rebuttal_decider(self):
        """The engagement partner or their delegate (F003), never the one who proposed it (F001)."""
        as_root = self.sudo()
        engagement = as_root.engagement_id.with_env(self.env)
        engagement._ea_tool_guard()
        if as_root.rebuttal_state != "proposed" or as_root.rebutted:
            raise rule_error(self.env, "rebuttal-not-proposed")
        if not can_partner_signoff(self.env.user._ea_firm_role()):
            raise rule_error(self.env, "rebut-partner-only")
        refusal = engagement._ea_partner_tier_refusal()
        if refusal:
            raise rule_error(self.env, refusal)
        if as_root.rebuttal_proposed_by_id == self.env.user:
            raise rule_error(self.env, "rebuttal-own-proposal")
        return engagement

    def approve_rebuttal(self):
        """Step 2: the risk is rebutted, leaves revenue, and revenue falls back to its default."""
        self.ensure_one()
        engagement = self._ea_rebuttal_decider()
        as_root = self.sudo()
        as_root.write({
            "rebutted": True, "rebuttal_state": "approved", "rebuttal_approved_by_id": self.env.user.id,
            "rebuttal_decided_at": fields.Datetime.now(), "significant": False, "status": "concluded",
        })
        self.env["ea.audit.risk.index"].sudo().search([
            ("risk_id", "=", as_root.id), ("index_code", "=", REVENUE_INDEX),
        ]).unlink()
        engagement._ea_log(
            "risk_rebutted",
            "Rebuttal of the presumed revenue-fraud risk approved by %s: %s" % (
                self.env.user.name, " ".join((as_root.rebuttal_justification or "").split())[:160],
            ),
        )
        return True

    def reject_rebuttal(self, reason):
        """Step 2, the other way: the risk stays live and linked; the team may propose again."""
        self.ensure_one()
        engagement = self._ea_rebuttal_decider()
        text = (reason or "").strip()
        if not text:
            raise rule_error(self.env, "justification-required")
        self.sudo().write({
            "rebuttal_state": "rejected", "rebuttal_rejected_by_id": self.env.user.id,
            "rebuttal_rejection": text, "rebuttal_decided_at": fields.Datetime.now(),
        })
        engagement._ea_log(
            "rebuttal_rejected",
            "Rebuttal of the presumed revenue-fraud risk rejected by %s: %s" % (self.env.user.name, " ".join(text.split())[:160]),
        )
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

    def action_open_reject_rebuttal(self):
        return self.env["ea.audit.reason.wizard"]._ea_open("reject_rebuttal", self)

    def action_approve_rebuttal(self):
        self.approve_rebuttal()
        return {"type": "ir.actions.client", "tag": "soft_reload"}

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

    risk_heatmap_html = fields.Html(string="Risk heat map", compute="_compute_risk_heatmap", sanitize=False, compute_sudo=True)

    @api.depends_context("lang")
    def _compute_risk_heatmap(self):
        """F067: likelihood against magnitude, with its ticks and its legend, in the reader's language."""
        labels = dict(self.env["ea.audit.risk"]._fields["likelihood"]._description_selection(self.env))
        shades = {"low": "#e3f2ec", "medium": "#f7ecd7", "high": "#f6d5dc"}
        levels = [code for code, _label in RATING_SELECTION]
        for engagement in self:
            risks = self.env["ea.audit.risk"].sudo().search([("engagement_id", "=", engagement.id)])
            rows = Markup("")
            for magnitude in reversed(levels):
                cells = Markup("")
                for likelihood in levels:
                    here = risks.filtered(lambda r: r.likelihood == likelihood and r.magnitude == magnitude)
                    significant = len(here.filtered("significant"))
                    cells += Markup(
                        "<td class='text-center' data-ea-cell='{l}-{m}' title='{titles}' style='background:{bg};width:120px;height:64px;border:1px solid #fff;'><b>{n}</b>{sig}</td>"
                    ).format(
                        l=likelihood, m=magnitude, titles=" | ".join(here.mapped("title")), bg=shades[inherent_rating(likelihood, magnitude)],
                        n=len(here) or "", sig=Markup("<div class='small'>{}</div>").format(self.env._("%(count)s significant", count=significant)) if significant else "",
                    )
                rows += Markup("<tr><th class='text-end pe-2 fw-normal'>{}</th>{}</tr>").format(labels[magnitude], cells)
            ticks = Markup("").join(Markup("<th class='text-center fw-normal'>{}</th>").format(labels[level]) for level in levels)
            legend = Markup(" ").join(
                Markup("<span class='me-3'><span style='display:inline-block;width:12px;height:12px;background:{};margin-right:4px;'></span>{}</span>").format(shades[level], labels[level])
                for level in levels
            )
            engagement.risk_heatmap_html = Markup(
                "<table class='o_ea_heatmap' role='img' aria-label='{aria}'><tbody>"
                "<tr><th class='text-end pe-2'>{mag} &#8593;</th><th colspan='3'></th></tr>{rows}"
                "<tr><th></th>{ticks}</tr><tr><th></th><th colspan='3' class='text-center'>{lik} &#8594;</th></tr>"
                "</tbody></table><p class='o_ea_legend mt-3'><b>{rating}</b> {legend}</p><p class='o_ea_legend'>{how}</p>"
            ).format(
                aria=self.env._("Risk heat map: %(count)s risks by likelihood and magnitude", count=len(risks)),
                mag=self.env._("Magnitude"), lik=self.env._("Likelihood"), rows=rows, ticks=ticks,
                rating=self.env._("Inherent rating:"), legend=legend,
                how=self.env._("Each cell counts the risks of the register at that likelihood and magnitude. Inherent rating = likelihood x magnitude."),
            )

    def action_tool_risk_heatmap(self):
        return self._ea_board("ea_audit_tools.view_engagement_risk_heatmap", self.env._("Risk heat map"))

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
            if presumed == "revenue_fraud":
                self._ea_link_revenue_fraud(risk)
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

    def _ea_link_revenue_fraud(self, risk=None):
        """The presumed revenue-fraud risk sits on revenue (UA), with the assertions it was seeded
        with, unless a rebuttal was approved. Management override stays pervasive: no account.
        Nothing is written on an archived file."""
        self.ensure_one()
        if self._ea_is_archived():
            return False
        risk = risk or self.env["ea.audit.risk"].sudo().search([
            ("engagement_id", "=", self.id), ("presumed_type", "=", "revenue_fraud"),
        ], limit=1)
        if not risk or risk.rebutted:
            return False
        Link = self.env["ea.audit.risk.index"].sudo()
        if Link.search_count([("risk_id", "=", risk.id), ("index_code", "=", REVENUE_INDEX)]):
            return False
        assertions = dict((code, codes) for code, _section, codes in PRESUMED_SEED)["revenue_fraud"]
        Link.create({
            "engagement_id": self.id, "risk_id": risk.id, "index_code": REVENUE_INDEX,
            "assertion_ids": [(6, 0, self.env["ea.audit.assertion"]._ea_from_codes(assertions).ids)],
        })
        return True

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


class RiskStepWizard(models.TransientModel):
    _name = "ea.audit.risk.step.wizard"
    _description = "Link a risk to a program step"

    risk_id = fields.Many2one("ea.audit.risk", required=True)
    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    step_id = fields.Many2one("ea.audit.program.step", string="Program step", required=True, domain="[('engagement_id', '=', engagement_id)]")

    def action_link(self):
        self.ensure_one()
        self.risk_id.link_step(self.step_id)
        return {"type": "ir.actions.client", "tag": "soft_reload"}
