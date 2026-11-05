"""Substantive analytical procedures (lib/sap.ts, ISA 520, F038): one per index and assertion. The CRA
level, the firm percentage and performance materiality are frozen at save."""
from markupsafe import Markup

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.signoff_rules import at_least

from ..rules import rule_error
from ..services.cra_model import cra_of
from ..services.lead_classes import LEAD_INDEX_BY_CODE, LEAD_INDEXES, lead_index_label
from ..services.sap_model import DEFAULT_SAP_THRESHOLDS, evaluate_sap, is_sap_assertion, is_sap_pct, sap_assertion_label, threshold_pct_for
from .tool_record import fcfa, is_french

CONCLUSION_SELECTION = [("supported", "Supported"), ("not_supported", "Not supported")]
_PARAM = "ea_audit_tools.sap_threshold_%s_pct"


class SapProcedure(models.Model):
    _name = "ea.audit.sap.procedure"
    _inherit = ["ea.audit.tool.record"]
    _description = "Substantive analytical procedure"
    _order = "index_code, assertion"
    _rec_name = "index_code"

    index_code = fields.Selection(selection="_lead_index_selection", string="Lead index", required=True, index=True)
    assertion = fields.Selection([("C", "C"), ("E", "E"), ("A", "A"), ("V", "V"), ("P", "P")], required=True)
    expectation_model = fields.Text(required=True)
    inputs = fields.Text()
    expected_value = fields.Float(digits=(18, 2), required=True)
    data_reliability = fields.Text()
    cra_level = fields.Char(string="CRA level", readonly=True)
    threshold_pct = fields.Integer(string="Threshold %", readonly=True)
    threshold_override_pct = fields.Integer(string="Override %")
    has_override = fields.Boolean(readonly=True)
    threshold_override_reason = fields.Text()
    performance_materiality = fields.Float(digits=(18, 0), readonly=True)
    has_materiality = fields.Boolean(readonly=True)
    actual_value = fields.Float(digits=(18, 2))
    has_actual = fields.Boolean(readonly=True)
    actual_source = fields.Selection([("tb", "Trial balance"), ("manual", "Typed")], readonly=True)
    investigation = fields.Text()
    corroboration = fields.Text()
    conclusion = fields.Selection(CONCLUSION_SELECTION)
    threshold_amount = fields.Float(string="Threshold", digits=(18, 0), compute="_compute_evaluation", compute_sudo=True)
    difference = fields.Float(digits=(18, 0), compute="_compute_evaluation", compute_sudo=True)
    evaluation = fields.Selection(
        [("within", "Within the threshold"), ("above", "Above the threshold"), ("none", "Not evaluable")],
        compute="_compute_evaluation", compute_sudo=True,
    )

    _uniq = models.Constraint("UNIQUE(engagement_id, index_code, assertion)", "One procedure per index and assertion.")

    @api.depends("expected_value", "actual_value", "has_actual", "threshold_pct", "threshold_override_pct", "has_override", "performance_materiality", "has_materiality")
    def _compute_evaluation(self):
        for procedure in self:
            result = procedure._ea_evaluation()
            procedure.threshold_amount = result["threshold"] or 0
            procedure.difference = result["difference"] or 0
            exceeds = result["exceeds"]
            procedure.evaluation = "none" if exceeds is None else "above" if exceeds else "within"

    def _ea_evaluation(self):
        self.ensure_one()
        return evaluate_sap({
            "expected": self.expected_value, "actual": self.actual_value if self.has_actual else None,
            "performanceMateriality": self.performance_materiality if self.has_materiality else None,
            "pct": self.threshold_override_pct if self.has_override else self.threshold_pct,
        })


class SapSettings(models.AbstractModel):
    """The firm's percentages (one database per firm, so one set)."""

    _name = "ea.audit.sap.settings"
    _description = "Substantive analytics thresholds"

    @api.model
    def _ea_get(self):
        params = self.env["ir.config_parameter"].sudo()
        out = {}
        for key, default in DEFAULT_SAP_THRESHOLDS.items():
            try:
                out[key] = int(params.get_param(_PARAM % key, default))
            except (TypeError, ValueError):
                out[key] = default
        return out

    @api.model
    def set_thresholds(self, low, moderate, high):
        """setSapThresholds: firm administrators. Only procedures saved after this take the new figures."""
        if not at_least(self.env.user._ea_firm_role(), "firm_admin"):
            raise rule_error(self.env, "forbidden")
        for value in (low, moderate, high):
            if not is_sap_pct(value):
                raise rule_error(self.env, "sap-threshold-out-of-range")
        if not low >= moderate >= high:
            raise rule_error(self.env, "sap-threshold-order")
        params = self.env["ir.config_parameter"].sudo()
        for key, value in (("low", low), ("moderate", moderate), ("high", high)):
            params.set_param(_PARAM % key, str(value))
        return True


class EngagementSap(models.Model):
    _inherit = "ea.audit.engagement"

    sap_board_html = fields.Html(string="Lead indexes", compute="_compute_sap_board", sanitize=False, compute_sudo=True)
    sap_threshold_label = fields.Char(string="Firm thresholds", compute="_compute_sap_board", compute_sudo=True)

    def _compute_sap_board(self):
        fr = is_french(self.env)
        thresholds = self.env["ea.audit.sap.settings"]._ea_get()
        for engagement in self:
            engagement.sap_threshold_label = "%s / %s / %s %%" % (thresholds["low"], thresholds["moderate"], thresholds["high"])
            counts = engagement.sap_counts_by_index()
            lines = Markup("").join(
                Markup("<tr><td>{code}</td><td>{label}</td><td class='text-end'>{total}</td><td class='text-end'>{concluded}</td><td class='text-end'>{above}</td></tr>").format(
                    code=definition["code"], label=lead_index_label(definition, "fr" if fr else "en"),
                    total=counts.get(definition["code"], {}).get("total", 0), concluded=counts.get(definition["code"], {}).get("concluded", 0),
                    above=counts.get(definition["code"], {}).get("exceeding", 0),
                )
                for definition in LEAD_INDEXES
            )
            engagement.sap_board_html = Markup(
                "<table class='table table-sm o_ea_table'><thead><tr><th>{a}</th><th>{b}</th><th class='text-end'>{c}</th><th class='text-end'>{d}</th><th class='text-end'>{e}</th></tr></thead><tbody>{lines}</tbody></table>"
            ).format(
                a="Indice" if fr else "Index", b="Libellé" if fr else "Label", c="Procédures" if fr else "Procedures",
                d="Conclues" if fr else "Concluded", e="Au-dessus du seuil" if fr else "Above threshold", lines=lines,
            )

    def sap_counts_by_index(self):
        """sapCountsByIndex, also read by the E4 papers."""
        self.ensure_one()
        counts = {}
        for procedure in self.env["ea.audit.sap.procedure"].sudo().search([("engagement_id", "=", self.id)]):
            row = counts.setdefault(procedure.index_code, {"total": 0, "concluded": 0, "exceeding": 0})
            row["total"] += 1
            if procedure.conclusion:
                row["concluded"] += 1
            if procedure.evaluation == "above":
                row["exceeding"] += 1
        return counts

    def _ea_cra_level(self, index_code, assertion):
        cell = self.env["ea.audit.cra.assessment"].sudo().search([
            ("engagement_id", "=", self.id), ("index_code", "=", index_code), ("assertion", "=", assertion), ("relevant", "=", True),
        ], limit=1)
        return cra_of(cell.ir, cell.cr) if cell and cell.ir and cell.cr else None

    def save_sap(self, index_code, assertion, expectation_model, expected_value, inputs=None, data_reliability=None,
                 override_pct=None, override_reason=None, actual_value=None, investigation=None, corroboration=None, conclusion=None):
        """saveSap. The expectation is mandatory: with none it is a variance review, not a substantive
        procedure. An override needs a reason. The actual is the TB's when there is one, else typed."""
        self.ensure_one()
        self._ea_tool_guard()
        if index_code not in LEAD_INDEX_BY_CODE:
            raise rule_error(self.env, "invalid-index")
        if not is_sap_assertion(assertion):
            raise rule_error(self.env, "invalid-assertion")
        expectation_model = (expectation_model or "").strip()
        if not expectation_model:
            raise rule_error(self.env, "sap-expectation-required")
        if expected_value is None or expected_value is False or isinstance(expected_value, str):
            raise rule_error(self.env, "sap-expected-value-required")
        reason = (override_reason or "").strip()
        if override_pct is not None:
            if not is_sap_pct(override_pct):
                raise rule_error(self.env, "sap-threshold-out-of-range")
            if not reason:
                raise rule_error(self.env, "sap-override-reason-required")
        if conclusion and conclusion not in dict(CONCLUSION_SELECTION):
            raise rule_error(self.env, "invalid-conclusion")
        as_root = self.sudo()
        tb_closing = next((schedule["closing"] for schedule in as_root._ea_ap_lead_schedules() if schedule["index"] == index_code), None)
        typed = actual_value is not None and actual_value is not False
        actual = tb_closing if tb_closing is not None else (actual_value if typed else 0)
        approved = as_root._ea_approved_materiality()
        level = as_root._ea_cra_level(index_code, assertion)
        pct = threshold_pct_for(level, self.env["ea.audit.sap.settings"]._ea_get())
        values = {
            "expectation_model": expectation_model, "inputs": (inputs or "").strip() or False, "expected_value": expected_value,
            "data_reliability": (data_reliability or "").strip() or False, "cra_level": level or False, "threshold_pct": pct,
            "threshold_override_pct": override_pct or 0, "has_override": override_pct is not None, "threshold_override_reason": reason if override_pct is not None else False,
            "performance_materiality": approved.performance if approved else 0, "has_materiality": bool(approved),
            "actual_value": actual, "has_actual": tb_closing is not None or typed, "actual_source": "tb" if tb_closing is not None else "manual",
            "investigation": (investigation or "").strip() or False, "corroboration": (corroboration or "").strip() or False, "conclusion": conclusion or False,
        }
        Procedure = self.env["ea.audit.sap.procedure"].sudo()
        procedure = Procedure.search([("engagement_id", "=", self.id), ("index_code", "=", index_code), ("assertion", "=", assertion)], limit=1)
        if procedure:
            procedure.write(values)
        else:
            procedure = Procedure.create({"engagement_id": self.id, "index_code": index_code, "assertion": assertion, **values})
        self._ea_log("sap_saved", "Substantive analytical procedure saved on %s / %s: expected %s" % (index_code, assertion, fcfa(expected_value)))
        return procedure.with_env(self.env)

    def action_tool_sap(self):
        return self._ea_board("ea_audit_tools.view_engagement_sap_board", self.env._("Substantive analytics"))

    def action_sap_procedures(self):
        return self._ea_list(
            "ea.audit.sap.procedure", self.env._("Substantive analytical procedures"),
            [("ea_audit_tools.view_sap_list", "list")], {"context": {"ea_engagement_id": self.id, "create": False}},
        )

    def action_open_sap_wizard(self):
        self.ensure_one()
        self._ea_require_access()
        return {"type": "ir.actions.act_window", "name": self.env._("A substantive analytical procedure"), "res_model": "ea.audit.sap.wizard", "view_mode": "form", "target": "new", "context": {"default_engagement_id": self.id}}

    def action_export_sap(self):
        return self._ea_export_action("sap")

    def _ea_export_sap(self, fr):
        from ..exports import simple_workbook

        locale = "fr" if fr else "en"
        rows = []
        for p in self.env["ea.audit.sap.procedure"].sudo().search([("engagement_id", "=", self.id)]):
            rows.append([
                p.index_code, sap_assertion_label(p.assertion, locale), p.expectation_model, p.inputs or "", p.expected_value, p.data_reliability or "",
                p.cra_level or "", p.threshold_override_pct if p.has_override else p.threshold_pct, p.threshold_override_reason or "", p.threshold_amount,
                p.actual_value if p.has_actual else "", p.actual_source or "", p.difference, p.evaluation, p.investigation or "", p.corroboration or "", p.conclusion or "",
            ])
        head = (
            ["Indice", "Assertion", "Modèle d'attente", "Données", "Valeur attendue", "Fiabilité des données", "Niveau ECR", "Seuil %", "Motif de la dérogation", "Seuil", "Montant comptabilisé", "Source", "Écart", "Évaluation", "Investigation", "Corroboration", "Conclusion"]
            if fr else
            ["Index", "Assertion", "Expectation model", "Inputs", "Expected value", "Data reliability", "CRA level", "Threshold %", "Override reason", "Threshold", "Recorded amount", "Source", "Difference", "Evaluation", "Investigation", "Corroboration", "Conclusion"]
        )
        return "sap-%s.xlsx" % self._ea_export_slug(), simple_workbook("SAP", head, rows)
