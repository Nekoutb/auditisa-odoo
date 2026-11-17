"""The tool hooks of E3.1 (journal entries, ISA 240) and S5.4 (journal entry testing design):
their tasks are done in the Journal entry testing screen (owner's mock-up of 18/11).

Same contracts as paper_hooks.py. Hooks available here: card je_testing; done je_population,
je_criteria, je_period_end, je_tested, je_settings."""
from odoo import models


class PaperJeHooks(models.Model):
    _inherit = "ea.audit.paper"

    def _ea_jet(self):
        """What the Journal entry testing screen knows, in short (models/je_testing.py). Read
        once per paper read: the card and each task's hook share it."""
        cached = getattr(self, "_ea_jet_memo", None)
        if cached is None:
            cached = self.sudo().engagement_id._ea_jet_state()
            try:
                self._ea_jet_memo = cached
            except AttributeError:
                pass
        return cached

    def _ea_hook_card_je_testing(self):
        state = self._ea_jet()
        card = {
            "title": self._ea_pick("From the journal entry testing tool", "Depuis l'outil des tests des écritures de journal"),
            "open_label": self._ea_pick("Open Journal entry testing", "Ouvrir les tests des écritures de journal"),
            "action": self._ea_open("action_tool_je"),
            "note": self._ea_pick(
                "The criteria, the entries they select and the test of each entry are recorded in the tool; this paper records the judgements around them.",
                "Les critères, les écritures qu'ils sélectionnent et le test de chaque écriture sont consignés dans l'outil ; ce papier documente les jugements qui les entourent.",
            ),
            "warnings": [],
        }
        if not state["lines"]:
            card["empty"] = self._ea_pick(
                "No general ledger is in use yet: import it, then open the tool.",
                "Aucun grand livre n'est encore utilisé : importez-le, puis ouvrez l'outil.",
            )
            return card
        card["subtitle"] = self._ea_pick("%s entries selected", "%s écritures sélectionnées") % state["selectedText"]
        card["facts"] = [
            {"label": self._ea_pick("General ledger in use", "Grand livre utilisé"), "value": state["ledgerText"]},
            {"label": self._ea_pick("Entries selected", "Écritures sélectionnées"), "value": state["selectedText"]},
            {"label": self._ea_pick("Tested", "Testées"), "value": "%d / %d" % (state["tested"], state["selected"])},
            {"label": self._ea_pick("With exceptions", "Avec exceptions"), "value": str(state["exceptions"])},
            {"label": self._ea_pick("Findings raised", "Constats relevés"), "value": str(state["findings"])},
        ]
        return card

    def _ea_hook_done_je_population(self):
        state = self._ea_jet()
        return self._ea_done_if(bool(state["lines"]), state["ledgerText"])

    def _ea_hook_done_je_criteria(self):
        state = self._ea_jet()
        return self._ea_done_if(state["selected"] > 0, self._ea_pick(
            "%s entries selected by the criteria", "%s écritures sélectionnées par les critères",
        ) % state["selectedText"])

    def _ea_hook_done_je_period_end(self):
        state = self._ea_jet()
        return self._ea_done_if(state["selected"] > 0, self._ea_pick(
            "%d entries in the days around the year end", "%d écritures dans les jours autour de la clôture",
        ) % state["yearEnd"])

    def _ea_hook_done_je_tested(self):
        state = self._ea_jet()
        ok = state["selected"] > 0 and state["tested"] >= state["selected"]
        return self._ea_done_if(ok, self._ea_pick(
            "%(t)d of %(n)d entries tested, %(e)d with exceptions", "%(t)d écritures testées sur %(n)d, %(e)d avec exceptions",
        ) % {"t": state["tested"], "n": state["selected"], "e": state["exceptions"]})

    def _ea_hook_done_je_settings(self):
        state = self._ea_jet()
        return self._ea_done_if(state["settingsSaved"] or state["selected"] > 0, state["settingsText"])
