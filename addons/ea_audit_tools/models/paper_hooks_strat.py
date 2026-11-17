"""The tool hooks of the strategy papers (group "strat") in the working-paper layout of 2026-11-17:
S2.1 the controls selected for testing, S2.2 the design of the tests of controls, S2.3 and S2.5 the
IT applications and the conclusion on the IT general controls. Same contracts as paper_hooks.py:

    card   controls_selection (S2.1), controls_tests (S2.2), itgc_apps (S2.3), itgc_conclusion (S2.5)
    done   controls_strategy, controls_select, controls_itgc, toc_design, toc_extent, itgc_apps,
           itgc_strategy, itgc_state
    check  controls_strategy, controls_forced, controls_wcgw, controls_itgc, toc_designed, toc_extent,
           itgc_strategy, itgc_cra

The hooks only read: a payload of an archived file must never write (the IT applications are
brought up to date when the tool is opened, as before)."""
from odoo import models

from ..services.itgc_model import new_app_key
from .paper_hooks import _ROWS_SHOWN, _filled
from .scot import _APP_SPLIT

# Strategies of an IT application under which its IT general controls carry the automated controls.
_RELYING = ("rely_itgc", "test_direct")
_IT_DEPENDENT = ("automated", "it_dependent")
_STRATEGY_WORDS = {
    "rely_itgc": ("Rely on the IT processes", "Appui sur les processus informatiques"),
    "test_direct": ("Test the automated controls directly", "Test direct des contrôles automatisés"),
    "substantive_only": ("Fully substantive", "Entièrement substantif"),
}
_ITGC_STATE_WORDS = {
    "support": ("Support reliance", "Permettent l'appui"),
    "mixed": ("Mixed: support differs by application", "Mitigé : le soutien diffère selon l'application"),
    "not_support": ("Do not support reliance", "Ne permettent pas l'appui"),
}
_NOTE = (
    "The work is recorded in the tool; this paper shows it and records the judgements.",
    "Les travaux sont consignés dans l'outil ; ce papier les reprend et documente les jugements.",
)


class PaperStratHooks(models.Model):
    _inherit = "ea.audit.paper"

    # ------------------------------------------------------------------
    # shared readers
    # ------------------------------------------------------------------

    def _ea_strat_selected(self):
        return self._ea_scots().control_ids.filtered("selected_for_testing")

    def _ea_strat_apps(self):
        return self.sudo().engagement_id.it_application_ids.filtered(lambda app: not app.removed)

    def _ea_strat_app_keys(self, scot):
        return {new_app_key(name.strip()) for name in _APP_SPLIT.split(scot.applications or "") if name.strip()}

    def _ea_strat_uncovered_dependent(self):
        """(dependent, uncovered): the automated and IT-dependent controls selected, and those whose
        class of transactions names no application relying on the IT processes."""
        dependent = self._ea_strat_selected().filtered(lambda control: control.control_type in _IT_DEPENDENT)
        relying = {app.key for app in self._ea_strat_apps() if app.strategy in _RELYING}
        uncovered = dependent.filtered(lambda control: not (self._ea_strat_app_keys(control.scot_id) & relying))
        return dependent, uncovered

    def _ea_strat_para33(self):
        return self.sudo().engagement_id._ea_scot_studio()["para33Violations"]

    def _ea_strat_card(self, title, open_label, method):
        return {
            "title": self._ea_pick(*title),
            "open_label": self._ea_pick(*open_label),
            "action": self._ea_open(method),
            "note": self._ea_pick(*_NOTE),
        }

    def _ea_strat_controls_card(self):
        return self._ea_strat_card(
            ("From the Classes of transactions and controls tool", "Depuis l'outil des flux et contrôles"),
            ("Open the classes of transactions and controls", "Ouvrir les flux et contrôles"),
            "action_tool_scot",
        )

    # ------------------------------------------------------------------
    # S2.1 controls selected for testing
    # ------------------------------------------------------------------

    def _ea_hook_card_controls_selection(self):
        card = self._ea_strat_controls_card()
        para33 = self._ea_strat_para33()
        if para33:
            card["warnings"] = [self._ea_pick(
                "%d assertion(s) where substantive procedures alone are not enough have no control selected for testing (ISA 330 ¶8(b)).",
                "%d assertion(s) pour lesquelles les procédures de substance seules ne suffisent pas n'ont aucun contrôle retenu pour les tests (ISA 330 ¶8(b)).",
            ) % len(para33)]
        scots = self._ea_scots()
        if not scots:
            card["empty"] = self._ea_pick("No class of transactions recorded yet.", "Aucun flux de transactions consigné pour le moment.")
            return card
        selected = self._ea_strat_selected()
        relied = scots.filtered(lambda scot: scot.strategy == "controls")
        card["subtitle"] = self._ea_pick(
            "%d of %d classes of transactions rely on controls", "%d flux sur %d s'appuient sur les contrôles",
        ) % (len(relied), len(scots))
        card["facts"] = [
            {"label": self._ea_pick("Controls selected for testing", "Contrôles retenus pour les tests"), "value": str(len(selected))},
            {"label": self._ea_pick("Selected without a what can go wrong", "Retenus sans risque d'anomalie"),
             "value": str(len(selected.filtered(lambda control: not control.wcgw_ids)))},
            {"label": self._ea_pick("Assertions needing a control, none selected", "Assertions exigeant un contrôle, aucun retenu"),
             "value": str(len(para33))},
        ]
        card["head"] = [
            self._ea_pick("Class of transactions", "Flux"), self._ea_pick("Strategy", "Stratégie"),
            self._ea_pick("Controls selected", "Contrôles retenus"), self._ea_pick("Assertions covered", "Assertions couvertes"),
        ]
        rows = []
        for scot in scots[:_ROWS_SHOWN]:
            chosen = scot.control_ids.filtered("selected_for_testing")
            covered = sorted({code for control in chosen for code in control._ea_assertions()})
            rows.append([
                scot.name,
                self._ea_pick("Rely on controls", "Appui sur les contrôles") if scot.strategy == "controls" else self._ea_pick("Substantive", "Substantif"),
                "%d / %d" % (len(chosen), len(scot.control_ids)),
                ", ".join(covered) or "—",
            ])
        card["rows"] = rows
        card["more"] = self._ea_more(len(scots))
        return card

    def _ea_strat_cra_open(self):
        """The relevant cells of the combined risk assessment, and those with no strategy yet."""
        cells = self._ea_cra_cells()
        return cells, cells.filtered(lambda cell: not cell.cr)

    def _ea_hook_done_controls_strategy(self):
        cells, open_ = self._ea_strat_cra_open()
        relied = cells.filtered(lambda cell: cell.cr == "rely")
        return self._ea_done_if(cells and not open_, self._ea_pick(
            "rely on controls for %d assertion(s), substantive for %d", "appui sur les contrôles pour %d assertion(s), substantif pour %d",
        ) % (len(relied), len(cells) - len(relied)))

    def _ea_hook_check_controls_strategy(self):
        cells, open_ = self._ea_strat_cra_open()
        if not cells:
            return {"ok": None, "note": ""}
        return {"ok": not open_, "note": ", ".join(sorted({"%s %s" % (cell.index_code, cell.assertion) for cell in open_}))}

    def _ea_hook_done_controls_select(self):
        scots = self._ea_scots()
        relied = scots.filtered(lambda scot: scot.strategy == "controls")
        selected = self._ea_strat_selected()
        ok = (
            relied and all(scot.control_ids.filtered("selected_for_testing") for scot in relied)
            and all(control.wcgw_ids for control in selected)
        )
        return self._ea_done_if(ok, self._ea_pick(
            "%d control(s) selected, each linked to what can go wrong", "%d contrôle(s) retenu(s), chacun rattaché à un risque d'anomalie",
        ) % len(selected))

    def _ea_hook_check_controls_wcgw(self):
        selected = self._ea_strat_selected()
        if not selected:
            return {"ok": None, "note": ""}
        unlinked = selected.filtered(lambda control: not control.wcgw_ids)
        return {"ok": not unlinked, "note": ", ".join(unlinked.mapped("name"))}

    def _ea_hook_check_controls_forced(self):
        risks = self.env["ea.audit.risk"].sudo().search_count([
            ("engagement_id", "=", self.sudo().engagement_id.id), ("substantive_alone_insufficient", "=", True), ("rebutted", "=", False),
        ])
        if not risks:
            return {"ok": None, "note": ""}
        para33 = self._ea_strat_para33()
        return {"ok": not para33, "note": ", ".join(sorted({row["indexCode"] for row in para33}))}

    def _ea_hook_done_controls_itgc(self):
        if not self._ea_strat_selected():
            return self._ea_done_if(False, "")
        dependent, uncovered = self._ea_strat_uncovered_dependent()
        if not dependent:
            return self._ea_done_if(True, self._ea_pick(
                "no automated or IT-dependent control selected", "aucun contrôle automatisé ou dépendant de l'informatique retenu",
            ))
        return self._ea_done_if(not uncovered, self._ea_pick(
            "%d automated or IT-dependent control(s), their applications relying on the IT processes",
            "%d contrôle(s) automatisé(s) ou dépendant(s) de l'informatique, leurs applications s'appuyant sur les processus informatiques",
        ) % len(dependent))

    def _ea_hook_check_controls_itgc(self):
        dependent, uncovered = self._ea_strat_uncovered_dependent()
        if not dependent:
            return {"ok": None, "note": ""}
        return {"ok": not uncovered, "note": ", ".join(uncovered.mapped("name"))}

    # ------------------------------------------------------------------
    # S2.2 design of the tests of controls
    # ------------------------------------------------------------------

    @staticmethod
    def _ea_strat_sized(control):
        return control.control_type == "automated" or control.suggested_size > 0 or control.sample_size > 0

    def _ea_hook_card_controls_tests(self):
        card = self._ea_strat_controls_card()
        selected = self._ea_strat_selected()
        if not selected:
            card["empty"] = self._ea_pick("No control selected for testing yet (S2.1).", "Aucun contrôle retenu pour les tests pour le moment (S2.1).")
            return card
        designed = selected.filtered(lambda control: _filled(control.test_design))
        card["subtitle"] = self._ea_pick("%d control(s) selected for testing", "%d contrôle(s) retenu(s) pour les tests") % len(selected)
        card["facts"] = [
            {"label": self._ea_pick("Tests designed", "Tests conçus"), "value": "%d / %d" % (len(designed), len(selected))},
            {"label": self._ea_pick("Sample size known", "Taille d'échantillon connue"),
             "value": "%d / %d" % (len(selected.filtered(self._ea_strat_sized)), len(selected))},
        ]
        card["head"] = [
            self._ea_pick("Control", "Contrôle"), self._ea_pick("Class of transactions", "Flux"),
            self._ea_pick("Frequency", "Fréquence"), self._ea_pick("Minimum sample", "Échantillon minimum"),
            self._ea_pick("Test designed", "Test conçu"),
        ]
        card["rows"] = [
            [
                "%s %s" % (control.code, control.name), control.scot_id.name, control.frequency_display or "—",
                str(control.sample_size or control.suggested_size or "—"),
                self._ea_pick("Yes", "Oui") if _filled(control.test_design) else "—",
            ]
            for control in selected[:_ROWS_SHOWN]
        ]
        card["more"] = self._ea_more(len(selected))
        return card

    def _ea_hook_done_toc_design(self):
        selected = self._ea_strat_selected()
        ok = selected and all(_filled(control.test_design) for control in selected)
        return self._ea_done_if(ok, self._ea_pick("a test designed for each of the %d controls", "un test conçu pour chacun des %d contrôles") % len(selected))

    def _ea_hook_done_toc_extent(self):
        selected = self._ea_strat_selected()
        ok = selected and all(self._ea_strat_sized(control) for control in selected)
        return self._ea_done_if(ok, self._ea_pick(
            "sample size set from the frequency and the reliance of each control", "taille fixée selon la fréquence et l'appui de chaque contrôle",
        ))

    def _ea_hook_check_toc_designed(self):
        selected = self._ea_strat_selected()
        if not selected:
            return {"ok": None, "note": ""}
        missing = selected.filtered(lambda control: not _filled(control.test_design))
        return {"ok": not missing, "note": ", ".join(missing.mapped("name"))}

    def _ea_hook_check_toc_extent(self):
        selected = self._ea_strat_selected()
        if not selected:
            return {"ok": None, "note": ""}
        missing = selected.filtered(lambda control: not self._ea_strat_sized(control))
        return {"ok": not missing, "note": ", ".join(missing.mapped("name"))}

    # ------------------------------------------------------------------
    # S2.3 IT applications, S2.5 conclusion on the IT general controls
    # ------------------------------------------------------------------

    def _ea_strat_itgc_card(self):
        return self._ea_strat_card(
            ("From the IT applications and IT general controls tool", "Depuis l'outil des applications et contrôles généraux informatiques"),
            ("Open the IT applications and IT general controls", "Ouvrir les applications et contrôles généraux informatiques"),
            "action_tool_itgc",
        )

    def _ea_strat_strategy_word(self, strategy):
        words = _STRATEGY_WORDS.get(strategy)
        return self._ea_pick(*words) if words else self._ea_pick("To decide", "À décider")

    def _ea_hook_card_itgc_apps(self):
        card = self._ea_strat_itgc_card()
        apps = self._ea_strat_apps()
        if not apps:
            card["empty"] = self._ea_pick(
                "No IT application recorded yet: name the applications on the classes of transactions, then open the tool.",
                "Aucune application consignée pour le moment : citer les applications sur les flux, puis ouvrir l'outil.",
            )
            return card
        card["facts"] = [
            {"label": self._ea_pick("Applications", "Applications"), "value": str(len(apps))},
            {"label": self._ea_pick("With a strategy", "Avec une stratégie"), "value": "%d / %d" % (len(apps.filtered("strategy")), len(apps))},
            {"label": self._ea_pick("Relying on the IT processes", "Appui sur les processus informatiques"),
             "value": str(len(apps.filtered(lambda app: app.strategy in _RELYING)))},
        ]
        card["head"] = [
            self._ea_pick("Application", "Application"), self._ea_pick("Classes of transactions", "Flux"),
            self._ea_pick("Layers", "Couches"), self._ea_pick("Strategy", "Stratégie"),
        ]
        card["rows"] = [
            [app.name, app.scot_names or "—", app.layers or "—", self._ea_strat_strategy_word(app.strategy)]
            for app in apps[:_ROWS_SHOWN]
        ]
        card["more"] = self._ea_more(len(apps))
        return card

    def _ea_hook_done_itgc_apps(self):
        apps = self._ea_strat_apps()
        return self._ea_done_if(apps, self._ea_pick("%d application(s) from the classes of transactions", "%d application(s) issue(s) des flux") % len(apps))

    def _ea_hook_done_itgc_strategy(self):
        apps = self._ea_strat_apps()
        ok = apps and all(app.strategy for app in apps)
        counts = {key: len(apps.filtered(lambda app, key=key: app.strategy == key)) for key in _STRATEGY_WORDS}
        return self._ea_done_if(ok, self._ea_pick(
            "rely on the IT processes: %(rely)d; test directly: %(direct)d; substantive: %(sub)d",
            "appui sur les processus : %(rely)d ; test direct : %(direct)d ; substantif : %(sub)d",
        ) % {"rely": counts["rely_itgc"], "direct": counts["test_direct"], "sub": counts["substantive_only"]})

    def _ea_hook_check_itgc_strategy(self):
        apps = self._ea_strat_apps()
        if not apps:
            return {"ok": None, "note": ""}
        missing = apps.filtered(lambda app: not app.strategy)
        return {"ok": not missing, "note": ", ".join(missing.mapped("name"))}

    def _ea_strat_itgc_state(self):
        return self.sudo().engagement_id._ea_itgc_state()

    def _ea_hook_card_itgc_conclusion(self):
        card = self._ea_strat_itgc_card()
        state = self._ea_strat_itgc_state()
        if state == "not_support":
            card["warnings"] = [self._ea_pick(
                "The IT general controls do not support reliance: document the response to each ineffective control and the effect on the control risk in S3.1.",
                "Les contrôles généraux informatiques ne permettent pas l'appui : documenter la réponse à chaque contrôle inefficace et l'effet sur le risque lié au contrôle en S3.1.",
            )]
        apps = self._ea_strat_apps().filtered(lambda app: app.strategy in _RELYING)
        card["facts"] = [
            {"label": self._ea_pick("Overall conclusion", "Conclusion d'ensemble"),
             "value": self._ea_pick(*_ITGC_STATE_WORDS[state]) if state in _ITGC_STATE_WORDS else self._ea_pick("Not recorded yet", "Pas encore consignée")},
            {"label": self._ea_pick("Applications relying on the IT processes", "Applications s'appuyant sur les processus informatiques"), "value": str(len(apps))},
        ]
        if apps:
            card["head"] = [self._ea_pick("Application", "Application"), self._ea_pick("Strategy", "Stratégie"), self._ea_pick("Note", "Note")]
            card["rows"] = [
                [app.name, self._ea_strat_strategy_word(app.strategy), (app.itgc_note or "—").strip()[:80]]
                for app in apps[:_ROWS_SHOWN]
            ]
            card["more"] = self._ea_more(len(apps))
        return card

    def _ea_hook_done_itgc_state(self):
        state = self._ea_strat_itgc_state()
        return self._ea_done_if(state in _ITGC_STATE_WORDS, self._ea_pick(*_ITGC_STATE_WORDS[state]) if state in _ITGC_STATE_WORDS else "")

    def _ea_hook_check_itgc_cra(self):
        state = self._ea_strat_itgc_state()
        if not state:
            return {"ok": None, "note": ""}
        if state != "not_support":
            return {"ok": True, "note": ""}
        unsupported = self._ea_cra_cells().filtered(lambda cell: cell.cr == "rely" and not _filled(cell.cr_basis))
        return {"ok": not unsupported, "note": ", ".join(sorted({"%s %s" % (cell.index_code, cell.assertion) for cell in unsupported}))}
