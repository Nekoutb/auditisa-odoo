"""Roll forward to next year (owner's mock-up and rulings of 2026-11-16): what the tools carry.

Everything comes in as a draft of the new file, marked with the year it came from: SCOTs, controls
(their design, never a result) and walkthrough notes; the risk register and its lead-index links,
each assessment to re-confirm; the chosen ASPs and own procedures, not started; the significance
decisions; the materiality basis and percentages, without any amount; last year's closing balances
as the prior-year trial balance (ISA 510). The source file is only read: an archived file refuses
any row change.
"""
from odoo import api, fields, models

from ..services.scot_forms import WALKTHROUGH_FIELDS
from ..services.materiality_model import benchmark_label
from .scot_documents import _SCOT_TAG
from .tool_record import is_french

WALKTHROUGH_KEYS = [field["key"] for field in WALKTHROUGH_FIELDS]
_SCOT_FIELDS = ("name", "description", "transaction_type", "strategy", "applications")
# A control's design. Its test, sample, deviations and conclusions start again.
_CONTROL_FIELDS = (
    "name", "owner", "control_type", "frequency", "frequency_code", "frequency_other", "reliance", "objective",
    "selected_for_testing", "test_design",
)
_RISK_FIELDS = (
    "description", "source", "level", "category", "likelihood", "magnitude", "significant",
    "substantive_alone_insufficient", "controls_reliance", "inherent_factors", "fs_note",
)
_PROC_FIELDS = (
    "index_code", "library_id", "code", "kind", "sequence", "custom_text", "assertions", "in_scope", "reason",
    "reason_assertion", "reason_level",
)
_MAT_FIELDS = ("benchmark", "percentage", "performance_pct", "trivial_pct", "justification", "performance_justification")


def _values(record, names):
    out = {}
    for name in names:
        value = record[name]
        out[name] = value.id if isinstance(value, models.BaseModel) else value
    return out


class CarriedScot(models.Model):
    _inherit = "ea.audit.scot"

    carried_from_year = fields.Integer(string="Carried forward from", readonly=True, copy=False,
                                       help="A draft carried from last year's file: to update.")


class CarriedControl(models.Model):
    _inherit = "ea.audit.scot.control"

    carried_from_year = fields.Integer(string="Carried forward from", readonly=True, copy=False,
                                       help="Last year's design, carried as a draft: the test starts again.")


class CarriedRisk(models.Model):
    _inherit = "ea.audit.risk"

    carried_from_year = fields.Integer(string="Carried forward from", readonly=True, copy=False,
                                       help="Carried from last year's file: the assessment is to re-confirm.")


class CarriedProcedure(models.Model):
    _inherit = "ea.audit.designed.procedure"

    carried_from_year = fields.Integer(string="Carried forward from", readonly=True, copy=False,
                                       help="Chosen last year, carried as a draft: not started, no conclusion.")


class CarriedSignificance(models.Model):
    _inherit = "ea.audit.significance"

    carried_from_year = fields.Integer(string="Carried forward from", readonly=True, copy=False,
                                       help="Last year's decision, carried as a draft: to re-confirm.")


class EngagementRollforward(models.Model):
    _inherit = "ea.audit.engagement"

    ea_carried_basis = fields.Json(string="Carried from last year", readonly=True, copy=False)
    mat_carried_label = fields.Char(string="Last year's basis", compute="_compute_mat_carried_label", compute_sudo=True)

    @api.depends("ea_carried_basis")
    @api.depends_context("lang")
    def _compute_mat_carried_label(self):
        fr = is_french(self.env)
        for engagement in self:
            basis = (engagement.ea_carried_basis or {}).get("materiality")
            engagement.mat_carried_label = self.env._(
                "Last year (%(year)s): %(benchmark)s, %(pct)s%%; performance %(perf)s%%; clearly trivial %(trivial)s%%. "
                "Amounts are worked out again from this year's figures.",
                year=engagement.ea_carried_basis.get("year"), benchmark=benchmark_label(basis["benchmark"], fr),
                pct=basis["percentage"], perf=basis["performance_pct"], trivial=basis["trivial_pct"],
            ) if basis else False

    def _ea_rollforward_carry(self, source, carry, mapping):
        super()._ea_rollforward_carry(source, carry, mapping)
        self.ensure_one()
        year = source.fiscal_year
        if "materiality" in carry:
            self._ea_rf_materiality(source, year)
        if "scots" in carry:
            self._ea_rf_scots(source, year, mapping)
        if "risks" in carry:
            self._ea_rf_risks(source, year, mapping)
        if "procedures" in carry:
            self._ea_rf_procedures(source, year, mapping)
        if "significance" in carry:
            self._ea_rf_significance(source, year)
        if "comparatives" in carry:
            self._ea_rf_comparatives(source, year)

    def _ea_rf_materiality(self, source, year):
        versions = self.env["ea.audit.materiality"].sudo().search([("engagement_id", "=", source.id)], order="version_no desc")
        version = versions.filtered(lambda v: v.state == "approved")[:1] or versions[:1]
        if version:
            self.sudo().ea_carried_basis = {"year": year, "materiality": _values(version, _MAT_FIELDS)}

    def _ea_rf_scots(self, source, year, mapping):
        Scot = self.env["ea.audit.scot"].sudo()
        Control = self.env["ea.audit.scot.control"].sudo()
        for scot in Scot.search([("engagement_id", "=", source.id)]):
            values = _values(scot, _SCOT_FIELDS + tuple(WALKTHROUGH_KEYS))
            new = Scot.create(dict(values, engagement_id=self.id, carried_from_year=year))
            mapping[("ea.audit.scot", scot.id)] = new
            for index in scot.index_ids:
                self.env["ea.audit.scot.index"].sudo().create({
                    "engagement_id": self.id, "scot_id": new.id, "index_code": index.index_code,
                    "assertion_ids": [(6, 0, index.assertion_ids.ids)],
                })
            wcgws = {}
            for wcgw in scot.wcgw_ids:
                wcgws[wcgw.id] = self.env["ea.audit.wcgw"].sudo().create({
                    "engagement_id": self.id, "scot_id": new.id, "description": wcgw.description, "sort": wcgw.sort,
                    "assertion_ids": [(6, 0, wcgw.assertion_ids.ids)],
                })
            for control in scot.control_ids:
                linked = [wcgws[w.id].id for w in control.wcgw_ids if w.id in wcgws]
                copy = Control.create(dict(
                    _values(control, _CONTROL_FIELDS), engagement_id=self.id, scot_id=new.id, carried_from_year=year,
                    wcgw_ids=[(6, 0, linked)],
                ))
                mapping[("ea.audit.scot.control", control.id)] = copy

    def _ea_rf_risks(self, source, year, mapping):
        """The presumed ISA 240 risks are not carried: the new file seeds its own, and a rebuttal is
        decided again each year."""
        Risk = self.env["ea.audit.risk"].sudo()
        for risk in Risk.search([("engagement_id", "=", source.id), ("presumed_type", "=", False)]):
            new = Risk.create(dict(
                _values(risk, _RISK_FIELDS), engagement_id=self.id, status="identified", carried_from_year=year,
                created_by_id=self.env.user.id,
            ))
            mapping[("ea.audit.risk", risk.id)] = new
            for link in risk.index_link_ids:
                self.env["ea.audit.risk.index"].sudo().create({
                    "engagement_id": self.id, "risk_id": new.id, "index_code": link.index_code,
                    "assertion_ids": [(6, 0, link.assertion_ids.ids)],
                })
            for link in risk.section_link_ids:
                item = self.env["ea.audit.file.item"].sudo().search(
                    [("engagement_id", "=", self.id), ("code", "=", link.file_item_id.code)], limit=1,
                )
                if item:
                    self.env["ea.audit.risk.section"].sudo().create({
                        "engagement_id": self.id, "risk_id": new.id, "file_item_id": item.id,
                        "assertion_ids": [(6, 0, link.assertion_ids.ids)],
                    })

    def _ea_rf_procedures(self, source, year, mapping):
        """The ASPs chosen and the team's own procedures, ticked, not started, with no conclusion.
        The mandatory procedures come back by themselves with the significant accounts."""
        Proc = self.env["ea.audit.designed.procedure"].sudo()
        chosen = Proc.search([
            ("engagement_id", "=", source.id), ("selected", "=", True), ("kind", "in", ("ASP", "custom")),
        ])
        for proc in chosen:
            new = Proc.create(dict(
                _values(proc, _PROC_FIELDS), engagement_id=self.id, selected=True, state="draft", carried_from_year=year,
            ))
            mapping[(Proc._name, proc.id)] = new

    def _ea_rf_significance(self, source, year):
        Significance = self.env["ea.audit.significance"].sudo()
        for row in Significance.search([("engagement_id", "=", source.id)]):
            if not (row.decision or row.justification or row.assertion_ids):
                continue
            Significance.create({
                "engagement_id": self.id, "index_code": row.index_code, "sequence": row.sequence, "closing": 0,
                "decision": row.decision, "justification": row.justification,
                "assertion_ids": [(6, 0, row.assertion_ids.ids)], "carried_from_year": year,
            })

    def _ea_rf_comparatives(self, source, year):
        """Last year's closing trial balance (post-audit if there is one, else the version that drove
        the file) becomes this file's prior-year trial balance: the comparatives of the lead
        schedules, the analytical review and the significance list read it (ISA 510)."""
        tb = source._ea_tb()
        if not tb:
            return
        Version = self.env["ea.audit.tb.version"].sudo()
        closing = Version.search([
            ("tb_id", "=", tb.id), ("timing", "=", "post_audit"), ("superseded_at", "=", False), ("validation_status", "=", "valid"),
        ], order="version_no desc", limit=1) or source._ea_current_tb_version()
        if not closing or not closing.line_ids:
            return
        mine = self._ea_tb() or self.env["ea.audit.tb"].sudo().create({"engagement_id": self.id, "period_end": self.period_end})
        number = max(Version.search([("tb_id", "=", mine.id)], order="version_no desc", limit=1).version_no, mine.last_version_no) + 1
        mine.last_version_no = number
        version = Version.create({
            "engagement_id": self.id, "tb_id": mine.id, "version_no": number, "timing": "prior_year",
            "validation_status": "valid", "source_filename": self.env._("Closing balances of the %(year)s file", year=year),
            "row_count": len(closing.line_ids), "total_debit": closing.total_debit, "total_credit": closing.total_credit,
            "validation_summary": closing.validation_summary,
        })
        self.env["ea.audit.tb.line"].sudo().create([{
            "engagement_id": self.id, "version_id": version.id, "row_no": line.row_no, "account_code": line.account_code,
            "account_name": line.account_name, "opening_debit": line.opening_debit, "opening_credit": line.opening_credit,
            "debit": line.debit, "credit": line.credit,
        } for line in closing.line_ids])

    def _ea_rf_evidence_links(self, row, mapping):
        links = super()._ea_rf_evidence_links(row, mapping)
        links["doc_type"] = row.doc_type or False
        for field, model in (
            ("scot_id", "ea.audit.scot"), ("control_id", "ea.audit.scot.control"),
            ("designed_procedure_id", "ea.audit.designed.procedure"),
        ):
            carried = mapping.get((model, row[field].id)) if row[field] else None
            if carried:
                links[field] = carried.id
        if row.scot_id:
            # a SCOT's document is named after its SCOT: it takes the carried SCOT's tag, or none
            tag = _SCOT_TAG % row.scot_id.id
            if row.name.startswith(tag):
                new = links.get("scot_id")
                links["name"] = (_SCOT_TAG % new if new else "") + row.name[len(tag):]
        return links
