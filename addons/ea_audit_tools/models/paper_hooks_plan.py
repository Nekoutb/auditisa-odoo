"""Tool hooks of the planning papers (group "plan", layout of 2026-11-17): the cards, the tasks
done in the tool and the statements it checks, read from the tools that truly hold the data.

    P3.2  card plan_analytics      the Analytical procedures (trial balance against the prior year)
          done plan_analytics.compare, plan_analytics.ratios (Financial analysis)
    P4.3  card plan_it_apps        the IT applications and general controls tool
    P5.1  card plan_fraud          the fraud risks of the Risk register
          done plan_fraud.revenue, plan_fraud.override
          check plan_fraud_revenue, plan_fraud_override

Same contract as paper_hooks.py: read-only, as superuser, and a reader the tool turns away
still reads the card. Nothing here writes."""
from odoo import models
from odoo.exceptions import AccessError, UserError

from .paper_hooks import _ROWS_SHOWN
from .tool_record import decimal_label, fcfa, is_french


class PaperPlanHooks(models.Model):
    _inherit = "ea.audit.paper"

    def _ea_plan_lang(self):
        return "fr" if is_french(self.env) else "en"

    def _ea_plan_call(self, method):
        """An engagement reader of the tools, or None where the tool turns the reader away."""
        engagement = self.sudo().engagement_id
        try:
            return getattr(engagement, method)()
        except (AccessError, UserError):
            return None

    # ------------------------------------------------------------------
    # P3.2 preliminary analytical procedures
    # ------------------------------------------------------------------

    def _ea_plan_review(self):
        review = self._ea_plan_call("analytical_review")
        return review if review and review.get("hasTb") else None

    def _ea_hook_card_plan_analytics(self):
        review = self._ea_plan_review()
        card = {
            "title": self._ea_pick("From the Analytical procedures", "Depuis les procédures analytiques"),
            "open_label": self._ea_pick("Open the Analytical procedures", "Ouvrir les procédures analytiques"),
            "action": self._ea_open("action_tool_analytics"),
            "note": self._ea_pick(
                "The comparison is computed from the trial balance; this paper records the expectations, the explanations and what goes to the risk register.",
                "La comparaison est calculée à partir de la balance ; ce papier consigne les attentes, les explications et ce qui va au registre des risques.",
            ),
        }
        if not review:
            card["empty"] = self._ea_pick(
                "No trial balance yet: the comparison runs once one is imported.",
                "Pas encore de balance : la comparaison se fait dès son import.",
            )
            return card
        lang = self._ea_plan_lang()
        lines = review["lines"]
        flagged = [line for line in lines if line["flagged"]]
        performance = review.get("performanceMateriality")
        card["facts"] = [
            {"label": self._ea_pick("Sections compared", "Rubriques comparées"), "value": str(len(lines))},
            {
                "label": self._ea_pick("Comparative", "Comparatif"),
                "value": self._ea_pick("prior-year closing balances", "soldes de clôture N-1") if review["hasPrior"]
                else self._ea_pick("opening balances of this trial balance", "soldes d'ouverture de cette balance"),
            },
            {
                "label": self._ea_pick("Performance materiality", "Seuil de travail"),
                "value": fcfa(performance) if performance is not None else self._ea_pick("not approved yet", "pas encore approuvé"),
            },
            {"label": self._ea_pick("Movements above it", "Variations au-delà"), "value": str(len(flagged)) if performance is not None else "—"},
        ]
        card["head"] = [
            self._ea_pick("Section", "Rubrique"), self._ea_pick("Current", "N"), self._ea_pick("Prior", "N-1"),
            self._ea_pick("Movement", "Variation"), "%",
        ]
        ranked = flagged + [line for line in lines if not line["flagged"]]
        card["rows"] = [
            [
                line["sectionCode"], fcfa(line["closing"]), fcfa(line["prior"]), fcfa(line["movement"]),
                "%s %%" % decimal_label(round(line["variancePct"], 1), lang) if line["variancePct"] is not None else "—",
            ]
            for line in ranked[:_ROWS_SHOWN]
        ]
        card["more"] = self._ea_more(len(lines))
        return card

    def _ea_hook_done_plan_analytics_compare(self):
        review = self._ea_plan_review()
        if not review or not review["hasPrior"]:
            return self._ea_done_if(False, "")
        flagged = len([line for line in review["lines"] if line["flagged"]])
        if review.get("performanceMateriality") is None:
            result = self._ea_pick("%d sections against the prior year", "%d rubriques comparées à N-1") % len(review["lines"])
        else:
            result = self._ea_pick(
                "%d sections against the prior year; %d above performance materiality",
                "%d rubriques comparées à N-1 ; %d au-delà du seuil de travail",
            ) % (len(review["lines"]), flagged)
        return self._ea_done_if(True, result)

    def _ea_hook_done_plan_analytics_ratios(self):
        view = self._ea_plan_call("financial_analysis_view")
        rows = [row for row in (view or {}).get("rows") or [] if row.get("current") is not None]
        compared = [row for row in rows if row.get("prior") is not None]
        return self._ea_done_if(compared, self._ea_pick(
            "%d ratios against the prior year in the Financial analysis", "%d ratios comparés à N-1 dans l'analyse financière",
        ) % len(compared))

    # ------------------------------------------------------------------
    # P4.3 IT environment
    # ------------------------------------------------------------------

    def _ea_hook_card_plan_it_apps(self):
        engagement = self.sudo().engagement_id
        apps = engagement.it_application_ids.filtered(lambda app: not app.removed)
        card = {
            "title": self._ea_pick("From the IT applications and general controls tool", "Depuis l'outil applications et CGI"),
            "open_label": self._ea_pick("Open the IT applications and general controls", "Ouvrir les applications et CGI"),
            "action": self._ea_open("action_tool_itgc"),
            "note": self._ea_pick(
                "The applications come from the classes of transactions and the tool; this paper adds the spreadsheets, interfaces, risks and reports relied on.",
                "Les applications viennent des flux et de l'outil ; ce papier ajoute les tableurs, interfaces, risques et rapports utilisés.",
            ),
        }
        if not apps:
            card["empty"] = self._ea_pick(
                "No application recorded yet: name them on the classes of transactions or in the tool.",
                "Aucune application consignée : les nommer sur les flux ou dans l'outil.",
            )
            return card
        strategies = dict(apps._fields["strategy"]._description_selection(self.env))
        states = dict(engagement._fields["itgc_state"]._description_selection(self.env))
        card["facts"] = [
            {"label": self._ea_pick("Applications", "Applications"), "value": str(len(apps))},
            {
                "label": self._ea_pick("IT general controls conclusion (S2.5)", "Conclusion CGI (S2.5)"),
                "value": states.get(engagement.itgc_state) or self._ea_pick("not concluded yet", "pas encore conclue"),
            },
        ]
        card["head"] = [
            self._ea_pick("Application", "Application"), self._ea_pick("Layers", "Couches"),
            self._ea_pick("Classes of transactions", "Flux"), self._ea_pick("Strategy", "Stratégie"),
        ]
        card["rows"] = [
            [app.name, app.layers or "—", app.scot_names or "—", strategies.get(app.strategy) or "—"]
            for app in apps[:_ROWS_SHOWN]
        ]
        card["more"] = self._ea_more(len(apps))
        return card

    # ------------------------------------------------------------------
    # P5.1 fraud risks
    # ------------------------------------------------------------------

    def _ea_plan_fraud_risks(self):
        return self.env["ea.audit.risk"].sudo().search([
            ("engagement_id", "=", self.sudo().engagement_id.id),
            "|", ("category", "=", "fraud"), ("presumed_type", "!=", False),
        ])

    def _ea_plan_presumed(self, kind):
        return self._ea_plan_fraud_risks().filtered(lambda risk: risk.presumed_type == kind)[:1]

    def _ea_plan_rebuttal_text(self, risk):
        if risk.presumed_type != "revenue_fraud":
            return "—"
        if risk.rebutted:
            return self._ea_pick("rebutted, approved by %s", "réfutée, approuvée par %s") % (risk.rebuttal_approved_by_id.name or "—")
        if risk.rebuttal_state == "proposed":
            return self._ea_pick("rebuttal awaiting the partner", "réfutation à approuver par l'associé")
        return self._ea_pick("presumption applied", "présomption appliquée")

    def _ea_hook_card_plan_fraud(self):
        risks = self._ea_plan_fraud_risks()
        card = {
            "title": self._ea_pick("From the Risk register", "Depuis le registre des risques"),
            "open_label": self._ea_pick("Open the Risk register", "Ouvrir le registre des risques"),
            "action": self._ea_open("action_tool_risk"),
            "note": self._ea_pick(
                "The fraud risks, the presumed risks and any rebuttal are kept in the register; this paper records the inquiries, the factors and the communications.",
                "Les risques de fraude, les risques présumés et toute réfutation sont tenus au registre ; ce papier consigne les entretiens, les facteurs et les communications.",
            ),
        }
        if not risks:
            card["empty"] = self._ea_pick("No fraud risk on the register yet.", "Aucun risque de fraude au registre pour le moment.")
            return card
        levels = dict(risks._fields["level"]._description_selection(self.env))
        card["facts"] = [
            {"label": self._ea_pick("Fraud risks on the register", "Risques de fraude au registre"), "value": str(len(risks))},
            {"label": self._ea_pick("Significant", "Importants"), "value": str(len(risks.filtered("significant")))},
        ]
        card["head"] = [
            self._ea_pick("Risk", "Risque"), self._ea_pick("Level", "Niveau"),
            self._ea_pick("Significant", "Important"), self._ea_pick("Presumption", "Présomption"),
        ]
        ranked = risks.sorted(lambda risk: (not risk.presumed_type, not risk.significant, risk.id))
        card["rows"] = [
            [risk.title or risk.description or "", levels.get(risk.level, "—"), self._ea_pick("Yes", "Oui") if risk.significant else "—", self._ea_plan_rebuttal_text(risk)]
            for risk in ranked[:_ROWS_SHOWN]
        ]
        card["more"] = self._ea_more(len(risks))
        return card

    def _ea_hook_done_plan_fraud_revenue(self):
        risk = self._ea_plan_presumed("revenue_fraud")
        if not risk:
            return self._ea_done_if(False, "")
        if risk.rebutted:
            return self._ea_done_if(True, self._ea_pick("Rebutted (%s); approved by %s", "Réfutée (%s) ; approuvée par %s") % (
                (risk.rebuttal_justification or "").strip() or "—", risk.rebuttal_approved_by_id.name or "—",
            ))
        if risk.rebuttal_state == "proposed":
            return {"done": False, "result": self._ea_pick("A rebuttal awaits the partner's approval in the Risk register.", "Une réfutation attend l'approbation de l'associé dans le registre des risques.")}
        return self._ea_done_if(True, self._ea_pick("Presumption applied: a fraud risk on revenue in the register", "Présomption appliquée : un risque de fraude sur les produits au registre"))

    def _ea_hook_done_plan_fraud_override(self):
        risk = self._ea_plan_presumed("mgmt_override")
        return self._ea_done_if(risk and risk.significant, self._ea_pick(
            "Significant risk on the register; responses performed in E3.1", "Risque important au registre ; réponses mises en œuvre en E3.1",
        ))

    def _ea_hook_check_plan_fraud_revenue(self):
        risk = self._ea_plan_presumed("revenue_fraud")
        if not risk:
            return {"ok": None, "note": ""}
        return {"ok": not risk.rebutted, "note": self._ea_pick("rebutted in the Risk register", "réfutée dans le registre des risques") if risk.rebutted else ""}

    def _ea_hook_check_plan_fraud_override(self):
        risk = self._ea_plan_presumed("mgmt_override")
        if not risk:
            return {"ok": None, "note": ""}
        return {"ok": bool(risk.significant), "note": ""}
