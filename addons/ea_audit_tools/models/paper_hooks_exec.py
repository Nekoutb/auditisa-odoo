"""The tool hooks of the execution papers converted to the layout of 2026-11-17 (group "exec"):
E1.1 (IT general controls), E1.2 and E2.1 (tests of controls), E6.6 (the next-year ledger), E6.8 (changes to the
combined risk assessment since planning) and E6.10 (the tie-out of the statements).

Same contracts as paper_hooks.py (card, done, check, warn). E6.3 reads the going concern hooks of
S4.2 there. Hooks available here: card itgc, toc, subsequent, cra_changes; done itgc_scope,
toc_selection, toc_population, toc_execute, toc_exceptions; check itgc_scope, toc_selection,
toc_population, toc_grids, toc_exceptions, cra_reasons, fs_tieout; warn itgc, toc."""
from odoo import models
from odoo.exceptions import AccessError, UserError

from .tool_record import fcfa, french_date

_ROWS_SHOWN = 6


def _filled(text):
    return bool((text or "").strip())


def _dmy(iso):
    """An ISO day (yyyy-mm-dd) as dd/mm/yyyy."""
    return "%s/%s/%s" % (iso[8:10], iso[5:7], iso[0:4]) if iso else "—"


class PaperExecHooks(models.Model):
    _inherit = "ea.audit.paper"

    # ------------------------------------------------------------------
    # E1.1 ITGC: the IT applications and the S2.5 conclusion
    # ------------------------------------------------------------------

    def _ea_it_apps(self):
        return self.sudo().engagement_id.it_application_ids.filtered(lambda app: not app.removed)

    def _ea_hook_card_itgc(self):
        engagement = self.sudo().engagement_id
        apps = self._ea_it_apps()
        card = {
            "title": self._ea_pick("From the IT applications and IT general controls tool", "Depuis l'outil des applications informatiques et ITGC"),
            "open_label": self._ea_pick("Open IT applications and IT general controls", "Ouvrir les applications informatiques et ITGC"),
            "action": self._ea_open("action_tool_itgc"),
            "note": self._ea_pick(
                "The applications and the IT strategy are recorded in the tool; this paper records the testing of the IT general controls and its conclusion.",
                "Les applications et la stratégie informatique sont consignées dans l'outil ; ce papier documente les tests ITGC et leur conclusion.",
            ),
            "warnings": self._ea_hook_warn_itgc(),
        }
        if not apps:
            card["empty"] = self._ea_pick(
                "No IT application recorded yet: open the tool to list them from the classes of transactions.",
                "Aucune application informatique consignée : ouvrir l'outil pour les reprendre des flux.",
            )
            return card
        strategies = dict(apps._fields["strategy"]._description_selection(self.env))
        states = dict(engagement._fields["itgc_state"]._description_selection(self.env))
        card["subtitle"] = self._ea_pick("%d IT applications", "%d applications informatiques") % len(apps)
        card["facts"] = [
            {"label": self._ea_pick("IT applications", "Applications informatiques"), "value": str(len(apps))},
            {"label": self._ea_pick("Rely on the IT processes (test the IT general controls)", "Appui sur les processus informatiques (tests ITGC)"),
             "value": str(len(apps.filtered(lambda app: app.strategy == "rely_itgc")))},
            {"label": self._ea_pick("Strategy still to decide", "Stratégie à décider"),
             "value": str(len(apps.filtered(lambda app: not app.strategy)))},
            {"label": self._ea_pick("IT general controls conclusion (S2.5)", "Conclusion ITGC (S2.5)"),
             "value": states.get(engagement.itgc_state) or self._ea_pick("not recorded yet", "pas encore consignée")},
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

    def _ea_hook_warn_itgc(self):
        if self.sudo().engagement_id.itgc_state in ("not_support", "mixed"):
            return [self._ea_pick(
                "The IT general controls conclusion (S2.5) does not support reliance on every IT process.",
                "La conclusion ITGC (S2.5) ne soutient pas l'appui sur chaque processus informatique.",
            )]
        return []

    def _ea_hook_done_itgc_scope(self):
        apps = self._ea_it_apps()
        ok = apps and all(_filled(app.layers) for app in apps)
        return self._ea_done_if(ok, self._ea_pick("%d applications, each with its layers", "%d applications, chacune avec ses couches") % len(apps))

    def _ea_hook_check_itgc_scope(self):
        apps = self._ea_it_apps()
        if not apps:
            return {"ok": None, "note": ""}
        missing = apps.filtered(lambda app: not _filled(app.layers))
        return {"ok": not missing, "note": ", ".join(missing.mapped("name"))}

    # ------------------------------------------------------------------
    # E1.2 and E2.1: tests of operating effectiveness of the selected controls
    # ------------------------------------------------------------------

    def _ea_toc_controls(self):
        return self.sudo().engagement_id.scot_ids.control_ids.filtered("selected_for_testing")

    @staticmethod
    def _ea_toc_size(control):
        return control.sample_size or control.suggested_size or 0

    def _ea_toc_populated(self, control):
        """A size is known: from the frequency, or from the population a frequent control needs."""
        return self._ea_toc_size(control) > 0

    def _ea_toc_tested(self, control):
        size = self._ea_toc_size(control)
        return size > 0 and control.rows_tested >= size

    def _ea_hook_card_toc(self):
        controls = self._ea_toc_controls()
        card = {
            "title": self._ea_pick("From the classes of transactions and controls tool · tests of controls", "Depuis l'outil des flux et contrôles · tests des contrôles"),
            "open_label": self._ea_pick("Open the classes of transactions and controls tool", "Ouvrir l'outil des flux et contrôles"),
            "action": self._ea_open("action_tool_scot"),
            "note": self._ea_pick(
                "Populations, samples, test grids and conclusions are recorded in the tool; this paper records the judgements around them.",
                "Populations, échantillons, grilles de test et conclusions sont consignés dans l'outil ; ce papier documente les jugements qui les entourent.",
            ),
            "warnings": self._ea_hook_warn_toc(),
        }
        if not controls:
            card["empty"] = self._ea_pick("No control selected for testing yet.", "Aucun contrôle retenu pour les tests pour le moment.")
            return card
        effective = controls.filtered(lambda c: c.operating_eval == "effective")
        failed = controls.filtered(lambda c: c.operating_eval == "not_effective")
        card["subtitle"] = self._ea_pick("%d controls selected for testing", "%d contrôles retenus pour les tests") % len(controls)
        card["facts"] = [
            {"label": self._ea_pick("Controls selected", "Contrôles retenus"), "value": str(len(controls))},
            {"label": self._ea_pick("Concluded effective", "Conclus efficaces"), "value": str(len(effective))},
            {"label": self._ea_pick("Concluded not effective", "Conclus non efficaces"), "value": str(len(failed))},
            {"label": self._ea_pick("Deviations found", "Déviations relevées"), "value": str(sum(controls.mapped("deviations")))},
        ]
        card["head"] = [
            self._ea_pick("Control", "Contrôle"), self._ea_pick("Class of transactions", "Flux"),
            self._ea_pick("Frequency", "Fréquence"), self._ea_pick("Tested", "Testés"),
            self._ea_pick("Deviations", "Déviations"), self._ea_pick("Conclusion", "Conclusion"),
        ]
        results = dict(controls._fields["operating_eval"]._description_selection(self.env))
        ranked = controls.sorted(lambda c: (c.operating_eval != "not_effective", bool(c.operating_eval), c.scot_id.name or "", c.id))
        card["rows"] = [
            [
                "%s %s" % (control.code, control.name), control.scot_id.name, control.frequency_display or "—",
                "%d / %d" % (control.rows_tested, self._ea_toc_size(control)), str(control.deviations) if control.deviations else "—",
                results.get(control.operating_eval) or self._ea_pick("to conclude", "à conclure"),
            ]
            for control in ranked[:_ROWS_SHOWN]
        ]
        card["more"] = self._ea_more(len(controls))
        return card

    def _ea_hook_warn_toc(self):
        failed = self._ea_toc_controls().filtered(lambda c: c.operating_eval == "not_effective")
        if not failed:
            return []
        return [self._ea_pick(
            "Controls concluded not effective: %s. The combined risk assessment no longer relies on them.",
            "Contrôles conclus non efficaces : %s. L'évaluation combinée des risques ne s'y appuie plus.",
        ) % ", ".join("%s %s" % (c.code, c.name) for c in failed)]

    def _ea_toc_relied(self):
        """(relied classes, relied classes with no control selected)."""
        relied = self.sudo().engagement_id.scot_ids.filtered(lambda scot: scot.strategy == "controls")
        return relied, relied.filtered(lambda scot: not scot.control_ids.filtered("selected_for_testing"))

    def _ea_hook_done_toc_selection(self):
        relied, missing = self._ea_toc_relied()
        controls = self._ea_toc_controls()
        return self._ea_done_if(relied and controls and not missing, self._ea_pick(
            "%d controls selected over %d classes relied on", "%d contrôles retenus sur %d flux en appui",
        ) % (len(controls), len(relied)))

    def _ea_hook_check_toc_selection(self):
        relied, missing = self._ea_toc_relied()
        if not relied:
            return {"ok": None, "note": ""}
        return {"ok": not missing, "note": ", ".join(missing.mapped("name"))}

    def _ea_hook_done_toc_population(self):
        controls = self._ea_toc_controls()
        ok = controls and all(self._ea_toc_populated(control) for control in controls)
        return self._ea_done_if(ok, self._ea_pick(
            "population and sample size recorded for the %d controls", "population et taille d'échantillon consignées pour les %d contrôles",
        ) % len(controls))

    def _ea_hook_check_toc_population(self):
        controls = self._ea_toc_controls()
        if not controls:
            return {"ok": None, "note": ""}
        missing = controls.filtered(lambda control: not self._ea_toc_populated(control))
        return {"ok": not missing, "note": ", ".join(missing.mapped("code"))}

    def _ea_hook_done_toc_execute(self):
        controls = self._ea_toc_controls()
        ok = controls and all(self._ea_toc_tested(control) for control in controls)
        return self._ea_done_if(ok, self._ea_pick(
            "%d items tested in the grids of %d controls", "%d éléments testés dans les grilles de %d contrôles",
        ) % (sum(controls.mapped("rows_tested")), len(controls)))

    def _ea_hook_check_toc_grids(self):
        controls = self._ea_toc_controls()
        if not controls:
            return {"ok": None, "note": ""}
        missing = controls.filtered(lambda control: not self._ea_toc_tested(control))
        return {"ok": not missing, "note": ", ".join(missing.mapped("code"))}

    def _ea_hook_done_toc_exceptions(self):
        """Nothing to evaluate: every control concluded and no deviation found. A deviation is a
        judgement the paper records, so the task then stays open."""
        controls = self._ea_toc_controls()
        deviations = sum(controls.mapped("deviations"))
        ok = controls and not deviations and all(controls.mapped("operating_eval"))
        if ok:
            return {"done": True, "result": self._ea_pick(
                "no deviation; %d controls concluded effective", "aucune déviation ; %d contrôles conclus efficaces",
            ) % len(controls)}
        result = self._ea_pick("%d deviations to evaluate", "%d déviations à évaluer") % deviations if deviations else ""
        return {"done": False, "result": result}

    def _ea_hook_check_toc_exceptions(self):
        deviating = self._ea_toc_controls().filtered(lambda control: control.deviations)
        if not deviating:
            return {"ok": None, "note": ""}
        open_ = deviating.filtered(lambda control: not control.operating_eval)
        return {"ok": not open_, "note": ", ".join(open_.mapped("code"))}

    # ------------------------------------------------------------------
    # E6.6 subsequent events: the next-year ledger
    # ------------------------------------------------------------------

    def _ea_subsequent_overview(self):
        engagement = self.sudo().engagement_id
        if not hasattr(engagement, "ea_subsequent_overview"):
            return None
        try:
            return engagement.ea_subsequent_overview()
        except (AccessError, UserError):
            return None

    def _ea_hook_card_subsequent(self):
        overview = self._ea_subsequent_overview()
        card = {
            "title": self._ea_pick("From the General ledger · subsequent period", "Depuis le grand livre · période postérieure"),
            "open_label": self._ea_pick("Open the General ledger", "Ouvrir le grand livre"),
            "action": self._ea_open("action_tool_gl"),
            "note": self._ea_pick(
                "Upload the next-year ledger as a subsequent-period dataset; the review of the entries after the year end is recorded in task 2.5.",
                "Importer le grand livre de l'exercice suivant comme période postérieure ; la revue des écritures postérieures à la clôture se documente en tâche 2.5.",
            ),
        }
        if not overview or (not overview.get("entries") and not overview.get("others")):
            card["empty"] = self._ea_pick(
                "No next-year ledger uploaded yet: upload it in the General ledger, subsequent period.",
                "Aucun grand livre de l'exercice suivant importé : l'importer dans le grand livre, période postérieure.",
            )
            return card
        card["subtitle"] = overview.get("sentence") or ""
        facts = []
        if overview.get("entries"):
            facts.append({"label": self._ea_pick("Entries after the year end", "Écritures après la clôture"), "value": str(overview["entries"])})
        if overview.get("last_date"):
            facts.append({
                "label": self._ea_pick("Period covered", "Période couverte"),
                "value": "%s → %s" % (_dmy(overview.get("first_date")), _dmy(overview["last_date"])),
            })
        if overview.get("days_after_year_end") is not None:
            facts.append({"label": self._ea_pick("Days after the year end", "Jours après la clôture"), "value": str(overview["days_after_year_end"])})
        card["facts"] = facts
        notes = [line for line in [overview.get("warning")] + list(overview.get("others") or []) if line]
        if notes:
            card["note"] = " ".join(notes)
        return card

    # ------------------------------------------------------------------
    # E6.8 changes to the combined risk assessment since planning
    # ------------------------------------------------------------------

    def _ea_cra_history(self):
        return self.env["ea.audit.cra.history"].sudo().search([("engagement_id", "=", self.sudo().engagement_id.id)])

    def _ea_hook_card_cra_changes(self):
        engagement = self.sudo().engagement_id
        history = self._ea_cra_history()
        failed = engagement.scot_ids.control_ids.filtered(lambda c: c.operating_eval == "not_effective")
        card = {
            "title": self._ea_pick("From the Combined risk assessment tool · changes since planning", "Depuis l'outil d'évaluation combinée des risques · changements depuis la planification"),
            "open_label": self._ea_pick("Open the Combined risk assessment", "Ouvrir l'évaluation combinée des risques"),
            "action": self._ea_open("action_tool_cra"),
            "note": self._ea_pick(
                "Each revision is made in the tool with its reason; this paper confronts the assessment with what execution found.",
                "Chaque révision se fait dans l'outil avec sa raison ; ce papier confronte l'évaluation aux constats de l'exécution.",
            ),
        }
        facts = [
            {"label": self._ea_pick("Revisions recorded", "Révisions consignées"), "value": str(len(history))},
            {"label": self._ea_pick("Controls concluded not effective", "Contrôles conclus non efficaces"), "value": str(len(failed))},
        ]
        if hasattr(engagement, "_ea_evaluate_b5"):
            try:
                total = engagement._ea_evaluate_b5()["uncorrectedTotal"]
            except (AccessError, UserError, KeyError):
                total = None
            if total is not None:
                facts.append({"label": self._ea_pick("Uncorrected misstatements", "Anomalies non corrigées"), "value": fcfa(total)})
        card["facts"] = facts
        if not history:
            card["empty"] = self._ea_pick("No assessment revised since planning.", "Aucune évaluation révisée depuis la planification.")
            return card
        irs = dict(history._fields["ir"]._description_selection(self.env))
        crs = dict(history._fields["cr"]._description_selection(self.env))

        def move(labels, old, new):
            if old == new or not new:
                return labels.get(old) or "—"
            return "%s → %s" % (labels.get(old) or "—", labels.get(new) or "—")

        card["head"] = [
            self._ea_pick("Account", "Compte"), self._ea_pick("Assertion", "Assertion"), self._ea_pick("Inherent risk", "Risque inhérent"),
            self._ea_pick("Control risk", "Risque lié au contrôle"), self._ea_pick("Reason", "Raison"), self._ea_pick("Date", "Date"),
        ]
        card["rows"] = [
            [
                self._ea_index_label(row.index_code), row.assertion, move(irs, row.ir, row.new_ir), move(crs, row.cr, row.new_cr),
                (row.reason or "—")[:80], french_date(row.create_date),
            ]
            for row in history[:_ROWS_SHOWN]
        ]
        card["more"] = self._ea_more(len(history))
        return card

    def _ea_hook_check_cra_reasons(self):
        history = self._ea_cra_history()
        if not history:
            return {"ok": None, "note": ""}
        return {"ok": all(_filled(row.reason) for row in history), "note": ""}

    # ------------------------------------------------------------------
    # E6.10 the tie-out of the statements to the trial balance
    # ------------------------------------------------------------------

    def _ea_hook_check_fs_tieout(self):
        engagement = self.sudo().engagement_id
        if not hasattr(engagement, "_ea_fs_tieout") or not engagement._ea_tb_balances():
            return {"ok": None, "note": ""}
        result = engagement._ea_fs_tieout()
        if not result.get("cr"):
            return {"ok": None, "note": ""}
        return {"ok": bool(result.get("pass")), "note": ""}
