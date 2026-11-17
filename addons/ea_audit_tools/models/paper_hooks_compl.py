"""The tool hooks of the completion papers (group compl, layout of 2026-11-17): the summary of
audit differences behind C1.1, the ISA 265 deficiencies behind C5.11, and the open review notes
read by C4.1 and C6.2. Same kinds as paper_hooks.py: card, done, check. Every reader is the
tools' own and reads as the superuser; the card's button opens the tool for the reader only."""
from odoo import models

from .tool_record import fcfa


class PaperLayoutHooksCompl(models.Model):
    _inherit = "ea.audit.paper"

    # ------------------------------------------------------------------
    # C1.1 summary of audit differences
    # ------------------------------------------------------------------

    def _ea_sad_adjustments(self):
        """One count per adjustment (the lines of one misstatement are reviewed together), by
        review status: posted, note (an open review note) or to_review."""
        engagement = self.sudo().engagement_id
        counts = {"all": 0, "posted": 0, "note": 0, "to_review": 0}
        seen = set()
        for entry in self.env["ea.audit.sad.entry"].sudo().search([("engagement_id", "=", engagement.id)], order="id"):
            key = ("m", entry.misstatement_id.id) if entry.misstatement_id else ("e", entry.id)
            if key in seen:
                continue
            seen.add(key)
            counts["all"] += 1
            status = entry._ea_review_status()
            counts[status if status in counts else "to_review"] += 1
        return counts

    def _ea_hook_card_sad(self):
        engagement = self.sudo().engagement_id
        counts = self._ea_sad_adjustments()
        result = engagement._ea_evaluate_b5()
        threshold = result["finalMateriality"]
        card = {
            "title": self._ea_pick("From the Summary of audit differences", "Depuis le récapitulatif des anomalies"),
            "open_label": self._ea_pick("Open the summary", "Ouvrir le récapitulatif"),
            "action": self._ea_open("action_tool_sad"),
            "subtitle": self._ea_pick("%(posted)s of %(all)s adjustments posted", "%(posted)s ajustement(s) validé(s) sur %(all)s") % counts,
            "note": self._ea_pick(
                "Every line comes from a working paper; the reviewer posts it in the tool. This paper records the evaluation.",
                "Chaque ligne provient d'une feuille de travail ; le réviseur la valide dans l'outil. Ce papier en consigne l'évaluation.",
            ),
        }
        facts = [{"label": self._ea_pick("Adjustments posted", "Ajustements validés"), "value": "%(posted)s / %(all)s" % counts}]
        if counts["note"]:
            facts.append({"label": self._ea_pick("With an open review note", "Avec une note de revue ouverte"), "value": str(counts["note"])})
        facts.append({"label": self._ea_pick("Uncorrected misstatements", "Anomalies non corrigées"), "value": fcfa(result["uncorrectedTotal"])})
        if threshold is None:
            facts.append({
                "label": self._ea_pick("Threshold", "Seuil"),
                "value": self._ea_pick("materiality not approved", "seuil de signification non approuvé"),
            })
        else:
            facts.append({
                "label": self._ea_pick("Threshold (overall less performance materiality)", "Seuil (signification moins seuil de travail)"),
                "value": fcfa(threshold),
            })
            facts.append({
                "label": self._ea_pick("Uncorrected against the threshold", "Non corrigées / seuil"),
                "value": self._ea_pick("above: effect on the opinion in C5.1", "au-dessus : effet sur l'opinion en C5.1") if result["exceedsMateriality"]
                else self._ea_pick("below ✓", "en dessous ✓"),
            })
        if result["trivialCount"]:
            facts.append({"label": self._ea_pick("Clearly trivial, listed apart", "Manifestement négligeables, listées à part"), "value": str(result["trivialCount"])})
        card["facts"] = facts
        meta = engagement._ea_sad_meta(create=False)
        if meta and (meta.concl_text or "").strip():
            card["note"] = self._ea_pick("Conclusion in the tool: %s", "Conclusion dans l'outil : %s") % meta.concl_text.strip()
        if not counts["all"]:
            card["empty"] = self._ea_pick("No audit difference on the summary yet.", "Aucune anomalie au récapitulatif pour le moment.")
        return card

    def _ea_hook_done_sad_reviewed(self):
        counts = self._ea_sad_adjustments()
        ok = counts["all"] and counts["all"] == counts["posted"]
        return self._ea_done_if(ok, self._ea_pick(
            "%s adjustment(s) on the summary, all reviewed and posted", "%s ajustement(s) au récapitulatif, tous revus et validés",
        ) % counts["all"])

    def _ea_hook_check_sad_uncorrected(self):
        result = self.sudo().engagement_id._ea_evaluate_b5()
        if result["exceedsMateriality"] is None:
            return {"ok": None, "note": ""}
        if result["exceedsMateriality"]:
            return {"ok": False, "note": self._ea_pick("%(total)s against a threshold of %(umt)s", "%(total)s pour un seuil de %(umt)s") % {
                "total": fcfa(result["uncorrectedTotal"]), "umt": fcfa(result["finalMateriality"]),
            }}
        return {"ok": True, "note": ""}

    # ------------------------------------------------------------------
    # C5.11 deficiencies in internal control (ISA 265)
    # ------------------------------------------------------------------

    def _ea_deficiencies(self):
        engagement = self.sudo().engagement_id
        return self.env["ea.audit.finding"].sudo().search([("engagement_id", "=", engagement.id), ("route", "=", "c1")])

    def _ea_hook_card_deficiencies(self):
        engagement = self.sudo().engagement_id
        findings = self._ea_deficiencies()
        graded = findings.filtered(lambda finding: finding.evaluation_id)
        significant = findings.filtered(lambda finding: finding.severity == "significant_deficiency")
        card = {
            "title": self._ea_pick("From the ISA 265 deficiencies", "Depuis les déficiences ISA 265"),
            "open_label": self._ea_pick("Open the deficiencies", "Ouvrir les déficiences"),
            "action": self._ea_open("action_tool_deficiencies"),
            "facts": [
                {"label": self._ea_pick("Deficiencies on the register", "Déficiences au registre"), "value": str(len(findings))},
                {"label": self._ea_pick("Graded on the grid", "Graduées sur la grille"), "value": "%s / %s" % (len(graded), len(findings))},
                {"label": self._ea_pick("Significant deficiencies", "Déficiences significatives"), "value": str(len(significant))},
                {
                    "label": self._ea_pick("Significant, not yet communicated in writing", "Significatives non encore communiquées par écrit"),
                    "value": str(engagement._ea_uncommunicated_significant_count()),
                },
            ],
            "note": self._ea_pick(
                "The grades and the dates of communication are kept in the tool; the file cannot be archived while a significant deficiency is not communicated.",
                "Les gradations et les dates de communication sont tenues dans l'outil ; le dossier ne peut être archivé tant qu'une déficience significative n'est pas communiquée.",
            ),
        }
        if not findings:
            card["empty"] = self._ea_pick("No deficiency in internal control on the register.", "Aucune déficience du contrôle interne au registre.")
        return card

    def _ea_hook_check_deficiencies_graded(self):
        findings = self._ea_deficiencies()
        ungraded = findings.filtered(lambda finding: not finding.evaluation_id)
        if ungraded:
            return {"ok": False, "note": self._ea_pick("%s not graded yet", "%s non encore graduée(s)") % len(ungraded)}
        return {"ok": True, "note": ""}

    def _ea_hook_check_deficiencies_communicated(self):
        pending = self.sudo().engagement_id._ea_uncommunicated_significant_count()
        if pending:
            return {"ok": False, "note": self._ea_pick("%s not communicated yet", "%s non encore communiquée(s)") % pending}
        return {"ok": True, "note": ""}

    # ------------------------------------------------------------------
    # C4.1, C6.2: the review notes still open on the file
    # ------------------------------------------------------------------

    def _ea_hook_check_review_notes_cleared(self):
        engagement = self.sudo().engagement_id
        notes = self.env["ea.audit.review.note"].sudo().search([("engagement_id", "=", engagement.id), ("state", "=", "open")])
        if notes:
            codes = sorted(set(code for code in notes.mapped("code") if code))
            return {"ok": False, "note": self._ea_pick("%(n)s open: %(codes)s", "%(n)s ouverte(s) : %(codes)s") % {
                "n": len(notes), "codes": ", ".join(codes[:6]),
            }}
        return {"ok": True, "note": ""}
