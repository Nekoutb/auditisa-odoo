"""What the papers addon asks of the tools: its gaps, the parts of a signature's hash, the
auto fields, the header chips, and the board shown in a paper. The papers addon stays
unaware of the tools; every reader here is the tools' own."""
from odoo import models
from odoo.exceptions import AccessError, UserError

from ..services.lead_classes import INDEX_SECTION, LEAD_INDEXES, lead_index_label
from ..services.scot_forms import FSCP_FIELDS
from ..services.risk_model import MGMT_OVERRIDE_PROCEDURE
from ..services.significant_accounts import unjustified_count
from .tool_record import fcfa, french_date, is_french

# The chip of a paper, by the engagement method that opens its tool.
_TOOL_OF_CODE = {
    "P6.1": "action_tool_materiality",
    "P6.2": "action_tool_significance",
    "C1.1": "action_tool_sad",
    "S3.1": "action_tool_risk",
}
_BENCHMARK_WORDS = {
    "fr": {
        "pbt": "résultat avant impôt", "revenue": "chiffre d'affaires", "total_assets": "total de l'actif",
        "equity": "capitaux propres", "expenses": "total des charges",
    },
    "en": {
        "pbt": "profit before tax", "revenue": "revenue", "total_assets": "total assets",
        "equity": "equity", "expenses": "total expenses",
    },
}


def _words(env, french, english):
    return french if is_french(env) else english


class FileItem(models.Model):
    _inherit = "ea.audit.file.item"

    def _ea_tool_gap(self):
        """P6.2 reads the real rows; S1.2, S1.3, S2.1, S2.2 and S2.3 read SCOT Studio (scot.py)."""
        self.ensure_one()
        if self.code == "P6.2":
            rows = self.sudo().engagement_id._ea_significance_rows()
            return "significance-unjustified" if unjustified_count(rows) else None
        return super()._ea_tool_gap()

    def _ea_program_step_counts(self):
        """What a section conclusion reads: the steps retained, and those still open."""
        self.ensure_one()
        steps = self.env["ea.audit.program.step"].sudo().search([("file_item_id", "=", self.id)])
        retained = steps.filtered(lambda step: step.status != "na")
        return {"retained": len(retained), "open": len(retained.filtered(lambda step: step.status == "open"))}

    def _ea_program_lines(self):
        steps = self.env["ea.audit.program.step"].sudo().search([("file_item_id", "=", self.id)])
        return sorted(
            [step.description or "", step.status or "", step.na_rationale or "", step.source or ""] for step in steps
        )

    # ------------------------------------------------------------------
    # The board of a paper: one payload, read by one component
    # ------------------------------------------------------------------

    def ea_paper_board(self):
        """What the tool holds for this paper, and the way into it."""
        self.ensure_one()
        item = self.sudo()
        engagement = item.engagement_id
        engagement.with_env(self.env)._ea_require_access()
        builder = {
            "P6.1": self._ea_board_materiality,
            "P6.2": self._ea_board_significance,
            "S3.1": self._ea_board_risks,
            "C1.1": self._ea_board_sad,
        }.get(item.code)
        if builder is None and item.code.startswith("E4."):
            builder = self._ea_board_lead
        board = builder(engagement) if builder else {"facts": [], "head": [], "rows": []}
        board["links"] = [
            {"label": label, "action": getattr(engagement.with_env(self.env), method)()}
            for label, method in self._ea_board_links(item.code)
        ]
        return board

    def _ea_board_links(self, code):
        if code in ("P6.1", "P6.2"):
            return [
                (_words(self.env, "Ouvrir l'outil de matérialité", "Open the materiality tool"), "action_tool_materiality"),
                (_words(self.env, "Comptes significatifs", "Significant accounts"), "action_tool_significance"),
            ]
        if code == "S3.1":
            return [
                (_words(self.env, "Registre des risques", "Risk register"), "action_tool_risk"),
                (_words(self.env, "Évaluation combinée", "Combined risk assessment"), "action_tool_cra"),
            ]
        if code == "C1.1":
            return [
                (_words(self.env, "Ouvrir la SAD", "Open the SAD"), "action_tool_sad"),
                (_words(self.env, "Constats", "Findings"), "action_tool_findings"),
            ]
        return [
            (_words(self.env, "Feuilles maîtresses", "Lead schedules"), "action_tool_lead"),
            (_words(self.env, "Balance générale", "Trial balance"), "action_tool_tb"),
        ]

    def _ea_board_materiality(self, engagement):
        approved = engagement._ea_approved_materiality()
        latest = self.env["ea.audit.materiality"].sudo().search(
            [("engagement_id", "=", engagement.id)], order="version_no desc", limit=1,
        )
        version = approved or latest
        if not version:
            return {
                "facts": [], "head": [], "rows": [],
                "empty": _words(self.env, "Aucune version de seuil pour le moment.", "No materiality version yet."),
            }
        return {
            "facts": [
                {"label": _words(self.env, "Seuil global", "Overall"), "value": fcfa(version.overall)},
                {"label": _words(self.env, "Seuil de travail", "Performance"), "value": fcfa(version.performance)},
                {"label": _words(self.env, "Anomalies manifestement négligeables", "Clearly trivial"), "value": fcfa(version.trivial)},
                {"label": _words(self.env, "Version", "Version"), "value": "v%d" % version.version_no},
                {
                    "label": _words(self.env, "État", "Status"),
                    "value": (
                        _words(self.env, "Approuvée par %s", "Approved by %s") % version.approved_by_id.name
                        if version.state == "approved"
                        else _words(self.env, "À approuver par l'associé", "Awaiting the partner's approval")
                    ),
                },
            ],
            "head": [],
            "rows": [],
        }

    def _ea_board_significance(self, engagement):
        rows = engagement._ea_significance_rows()
        unjustified = unjustified_count(rows)
        return {
            "facts": [
                {"label": _words(self.env, "Comptes", "Accounts"), "value": str(len(rows))},
                {
                    "label": _words(self.env, "Significatifs", "Significant"),
                    "value": str(len([row for row in rows if row["status"] == "significant"])),
                },
                {"label": _words(self.env, "Décisions à justifier", "Decisions to justify"), "value": str(unjustified)},
            ],
            "head": [_words(self.env, "Index", "Index"), _words(self.env, "Solde", "Closing"), _words(self.env, "Décision", "Decision")],
            "rows": [[row["index"], fcfa(row["closing"]), row["status"] or "—"] for row in rows[:12]],
        }

    def _ea_board_risks(self, engagement):
        risks = self.env["ea.audit.risk"].sudo().search([("engagement_id", "=", engagement.id)])
        fr = is_french(self.env)
        titled = risks.with_context(lang="fr_FR" if fr else "en_US")
        return {
            "facts": [
                {"label": _words(self.env, "Risques", "Risks"), "value": str(len(risks))},
                {
                    "label": _words(self.env, "Significatifs", "Significant"),
                    "value": str(len(risks.filtered("significant"))),
                },
                {
                    "label": _words(self.env, "Cellules à évaluer", "Cells to assess"),
                    "value": str(len(engagement._ea_cra_to_assess())),
                },
            ],
            "head": [_words(self.env, "Risque", "Risk"), _words(self.env, "Cotation", "Rating")],
            "rows": [[risk.title or "", risk.inherent_rating or "—"] for risk in titled[:10]],
        }

    def _ea_board_sad(self, engagement):
        result = engagement._ea_evaluate_b5()
        meta = engagement._ea_sad_meta(create=False)
        return {
            "facts": [
                {"label": _words(self.env, "Anomalies non corrigées", "Uncorrected misstatements"), "value": fcfa(result["uncorrectedTotal"])},
                {
                    "label": _words(self.env, "Conclusion", "Conclusion"),
                    "value": (meta.concl_text or "").strip() if meta and (meta.concl_text or "").strip()
                    else _words(self.env, "Pas encore rédigée", "Not written yet"),
                },
            ],
            "head": [],
            "rows": [],
        }

    def _ea_board_lead(self, engagement):
        indexes = [code for code, paper in INDEX_SECTION.items() if paper == self.code]
        lines = self.env["ea.audit.lead.line"].sudo().search(
            [("schedule_id.engagement_id", "=", engagement.id), ("index_code", "in", indexes)], limit=15,
        )
        return {
            "facts": [],
            "head": [
                _words(self.env, "Compte", "Account"), _words(self.env, "Libellé", "Description"),
                _words(self.env, "Solde", "Closing"), _words(self.env, "N-1", "Prior"),
            ],
            "rows": [[line.account_code, line.account_name or "", fcfa(line.closing), fcfa(line.prior)] for line in lines],
            "empty": _words(
                self.env,
                "Aucune ligne de balance sur ce papier : importez une balance valide.",
                "No trial balance line on this paper: import a valid trial balance.",
            ),
        }


class Paper(models.Model):
    _inherit = "ea.audit.paper"

    def _content_parts(self):
        """The records a paper fronts. Each is added only where it holds something, so a
        paper with no programme keeps the hash it had."""
        parts = super()._content_parts()
        paper = self.sudo()
        program = paper.file_item_id._ea_program_lines()
        if program:
            parts["program_steps"] = program
        if paper.code == "S3.1":
            cells = self.env["ea.audit.cra.assessment"].sudo().search([("engagement_id", "=", paper.engagement_id.id)])
            if cells:
                parts["cra"] = sorted(
                    [cell.index_code, cell.assertion, bool(cell.relevant), cell.ir or "", cell.cr or "", cell.ir_basis or "", cell.cr_basis or ""]
                    for cell in cells
                )
        return parts

    def _ea_auto_values(self):
        self.ensure_one()
        values = super()._ea_auto_values()
        paper = self.sudo()
        engagement = paper.engagement_id
        code = paper.code
        if code == "P1.3":
            values["framework"] = engagement.framework or ""
        elif code in ("P6.1", "S6.1"):
            text = self._ea_materiality_text(engagement)
            if text:
                values["benchmark" if code == "P6.1" else "context"] = text
        elif code == "S3.1":
            text = self._ea_register_text(engagement)
            if text:
                values["register"] = text
        return {key: value for key, value in values.items() if value}

    def _ea_materiality_text(self, engagement):
        version = engagement._ea_approved_materiality()
        if not version:
            return ""
        lang = "fr" if is_french(self.env) else "en"
        benchmark = _BENCHMARK_WORDS[lang].get(version.benchmark, version.benchmark)
        template = (
            "%(benchmark)s : %(amount)s à %(pct)s %% ; seuil global %(overall)s, seuil de travail %(perf)s, "
            "anomalies manifestement négligeables %(trivial)s. Version %(version)s approuvée par %(who)s le %(on)s."
            if lang == "fr" else
            "%(benchmark)s: %(amount)s at %(pct)s%%; overall %(overall)s, performance %(perf)s, "
            "clearly trivial %(trivial)s. Version %(version)s approved by %(who)s on %(on)s."
        )
        return template % {
            "benchmark": benchmark.capitalize(), "amount": fcfa(version.benchmark_amount), "pct": version.percentage,
            "overall": fcfa(version.overall), "perf": fcfa(version.performance), "trivial": fcfa(version.trivial),
            "version": version.version_no, "who": version.approved_by_id.name or "—", "on": french_date(version.approved_at),
        }

    def _ea_register_text(self, engagement):
        risks = self.env["ea.audit.risk"].sudo().search([("engagement_id", "=", engagement.id)])
        if not risks:
            return ""
        significant = len(risks.filtered("significant"))
        return _words(
            self.env,
            "%d risque(s) au registre, dont %d significatif(s).",
            "%d risk(s) on the register, %d of them significant.",
        ) % (len(risks), significant)

    def _ea_tool_links(self):
        """The chips, now with where each one goes. A chip whose tool is not built keeps no action."""
        self.ensure_one()
        links = super()._ea_tool_links()
        paper = self.sudo()
        method = _TOOL_OF_CODE.get(paper.code) or ("action_tool_lead" if paper.code.startswith("E4.") else None)
        if method:
            action = getattr(paper.engagement_id.with_env(self.env), method)()
            for link in links:
                link["action"] = action
        if paper.code == "C3.1":
            links.append(self._ea_rep_letter_link(paper.engagement_id.with_env(self.env)))
        return links

    def _ea_rep_letter_link(self, engagement):
        """C3.1: the sample representation letter, downloaded where the work is done."""
        template = self.env.ref("ea_audit_tools.wp_c31_rep_letter", raise_if_not_found=False)
        return {
            "en": "Template: management representation letter (Word)",
            "fr": "Modèle : lettre d'affirmation de la direction (Word)",
            "plain": True,
            "note_en": "Yellow text must be completed or deleted. Date it the same day as the auditor's report. File the signed copy on this task.",
            "note_fr": "Le texte en jaune doit être complété ou supprimé. Datez-la du même jour que le rapport de l'auditeur. Classez la copie signée sur cette tâche.",
            "action": engagement._ea_export_action("wp_%d" % template.id) if template else None,
        }

    def _ea_after_save(self, writes):
        """S2.5: the conclusion answered on the paper is the one the CRA reads."""
        result = super()._ea_after_save(writes)
        paper = self.sudo()
        if paper.code == "S2.5" and "itgc_state" in writes:
            engagement = paper.engagement_id
            state = (writes["itgc_state"] or "").strip() or False
            if engagement.itgc_state != state:
                engagement.itgc_state = state
                engagement._ea_log("itgc_concluded", "S2.5 ITGC conclusion: %s" % (state or "—"))
        return result

    def _ea_sync_seeded_response_step(self):
        """E3.1 (syncSeededResponseStep): every conclusion answered completes the seeded
        management-override step; a conclusion withdrawn reopens it."""
        self.ensure_one()
        super()._ea_sync_seeded_response_step()
        paper = self.sudo()
        if paper.code != "E3.1":
            return
        total = len(paper._ea_resolved().get("conclEn") or [])
        if not total:
            return
        values = paper._ea_values()
        answered = len([i for i in range(total) if values.get("c_%d" % i) in ("yes", "no")])
        steps = self.env["ea.audit.program.step"].sudo().search([
            ("file_item_id", "=", paper.file_item_id.id), ("source", "=", "risk_extension"),
            ("description", "=", MGMT_OVERRIDE_PROCEDURE),
        ])
        target = "done" if answered == total else "open"
        steps.filtered(lambda step: step.status != "na" and step.status != target).write({"status": target})


class ProgramStep(models.Model):
    _inherit = "ea.audit.program.step"

    def _ea_void_papers(self):
        """A step is part of its paper's hash: whoever writes one voids what it voids."""
        for item in self.sudo().file_item_id:
            item._ea_paper()._void_stale_signoffs()

    def mark_na(self, rationale):
        result = super().mark_na(rationale)
        self._ea_void_papers()
        return result

    def complete(self, conclusion):
        result = super().complete(conclusion)
        self._ea_void_papers()
        return result

    def uncomplete(self):
        result = super().uncomplete()
        self._ea_void_papers()
        return result


class Engagement(models.Model):
    _inherit = "ea.audit.engagement"

    def save_itgc_conclusion(self, state):
        """The tool and the paper hold one conclusion: the tool answers on the paper, so its hash,
        its history and its signatures follow."""
        result = super().save_itgc_conclusion(state)
        paper = self.env["ea.audit.paper"].sudo().search(
            [("engagement_id", "=", self.id), ("code", "=", "S2.5")], limit=1,
        )
        if paper and (paper._ea_values().get("itgc_state") or "") != (state or ""):
            paper.with_env(self.env).save_answers({"itgc_state": state or ""})
        return result

    def add_program_step(self, file_item, description, assertions=(), source="manual"):
        step = super().add_program_step(file_item, description, assertions=assertions, source=source)
        step._ea_void_papers()
        return step

    def _ea_invalidate_signoffs(self, code):
        """The CRA and its like void the paper's signatures: the task's state follows them,
        or a paper stays locked with nobody's signature on it."""
        count = super()._ea_invalidate_signoffs(code)
        if count:
            paper = self.env["ea.audit.paper"].sudo().search(
                [("engagement_id", "=", self.id), ("code", "=", code)], limit=1,
            )
            if paper:
                paper._ea_restate_after_void()
        return count


# ----------------------------------------------------------------------------------------
# The tool hooks of the working-paper layout of 2026-11-17 (ea_audit_papers/services/layout.py).
# 
# A converted definition names its hooks; ``ea.audit.paper._ea_hook(kind, name)`` calls
# ``_ea_hook_<kind>_<name>`` here. Four kinds, each with its contract:
# 
#     card   {title, subtitle, facts: [{label, value}], head: [..], rows: [[..]], more, note, empty,
#             open_label, action, warnings: [text]}: the read-only "From the <tool>" card
#     done   {done: bool, result: text}: the task is closed in the tool ("Done in the tool")
#     check  {ok: True | False | None, note: text}: a statement checked by the tool. None means
#            the tool has nothing to say yet; False refuses a "Yes"
#     warn   [text]: flags that force full documentation and close "No exceptions noted"
# 
# Hooks available: card materiality, significance, scot, scot_flows, walkthroughs, fscp, cra,
# going_concern; done materiality_benchmark, materiality_figure, materiality_percentage,
# materiality_pm, materiality_trivial, significance_listed, significance_quant,
# significance_assertions, scot_classes, scot_classified, scot_apps, scot_accounts, scot_flows,
# scot_wcgw, scot_controls, scot_design, walkthrough_selected, walkthrough_traced,
# walkthrough_differences, fscp_calendar, fscp_je, cra_gather, cra_assertion, cra_separate,
# cra_strategy; check materiality_approved, significance_screen, significance_assertions,
# significance_linked, scot_accounts, scot_classified, scot_apps, scot_flows, scot_wcgw_assertions,
# scot_design, walkthrough_all, walkthrough_differences, fscp_documented, fscp_je, fscp_override,
# cra_assertions, cra_separate, cra_reliance; warn going_concern, significance.
# A name written with a dot in a definition (materiality.benchmark) reads the same method.
# ----------------------------------------------------------------------------------------
_ROWS_SHOWN = 6
_BENCHMARK = {
    "pbt": ("Profit before tax", "Résultat avant impôt"), "revenue": ("Revenue", "Chiffre d'affaires"),
    "total_assets": ("Total assets", "Total de l'actif"), "equity": ("Equity", "Capitaux propres"),
    "expenses": ("Total expenses", "Total des charges"),
}
# S1.4: the close process tool's questions, by the area of the paper's card.
_FSCP_AREAS = [
    (("Close calendar and steps", "Calendrier et étapes de clôture"), ("tb_preparation", "fs_preparation")),
    (("Journal entries", "Écritures comptables"), ("je_process", "je_controls_design", "je_controls_implemented")),
    (("Disclosures", "Informations en annexe"), ("disclosure_sources", "wcgw_disclosures")),
    (("Tools outside the accounting system", "Outils hors du système comptable"), ("policies_it",)),
    (("Override points", "Points de contournement"), ("override_risk", "wcgw_je")),
    (("Conclusion of the tool", "Conclusion de l'outil"), ("fscp_strategy", "fscp_conclusion")),
]


def _filled(text):
    return bool((text or "").strip())


class PaperLayoutHooks(models.Model):
    _inherit = "ea.audit.paper"

    # ------------------------------------------------------------------
    # small helpers
    # ------------------------------------------------------------------

    def _ea_pick(self, english, french):
        return french if is_french(self.env) else english

    def _ea_open(self, method):
        """The tool's action, or nothing for a reader the tool turns away: the card still reads."""
        engagement = self.sudo().engagement_id.with_env(self.env)
        if not hasattr(engagement, method):
            return False
        try:
            return getattr(engagement, method)()
        except (AccessError, UserError):
            return False

    def _ea_more(self, total):
        rest = total - _ROWS_SHOWN
        if rest <= 0:
            return ""
        return self._ea_pick("… %d more · open the tool for the full list", "… %d de plus · ouvrir l'outil pour la liste complète") % rest

    def _ea_index_label(self, code):
        locale = "fr" if is_french(self.env) else "en"
        for definition in LEAD_INDEXES:
            if definition["code"] == code:
                return "%s %s" % (code, lead_index_label(definition, locale))
        return code

    @staticmethod
    def _ea_done_if(ok, result):
        return {"done": bool(ok), "result": result if ok else ""}

    # ------------------------------------------------------------------
    # P6.1 materiality
    # ------------------------------------------------------------------

    def _ea_materiality_version(self):
        engagement = self.sudo().engagement_id
        return engagement._ea_approved_materiality()

    def _ea_hook_card_materiality(self):
        engagement = self.sudo().engagement_id
        version = engagement._ea_approved_materiality() or self.env["ea.audit.materiality"].sudo().search(
            [("engagement_id", "=", engagement.id)], order="version_no desc", limit=1,
        )
        card = {
            "title": self._ea_pick("From the Materiality tool", "Depuis l'outil de matérialité"),
            "open_label": self._ea_pick("Open the Materiality tool", "Ouvrir l'outil de matérialité"),
            "action": self._ea_open("action_tool_materiality"),
            "note": self._ea_pick(
                "The amounts are calculated and approved in the tool; this paper shows them and records the judgements around them.",
                "Les montants sont calculés et approuvés dans l'outil ; ce papier les reprend et documente les jugements qui les entourent.",
            ),
        }
        if not version:
            card["empty"] = self._ea_pick("No materiality version yet.", "Aucune version de seuil pour le moment.")
            return card
        if version.state == "approved":
            card["subtitle"] = self._ea_pick("version %(v)s · approved by %(who)s on %(on)s", "version %(v)s · approuvée par %(who)s le %(on)s") % {
                "v": version.version_no, "who": version.approved_by_id.name or "—", "on": french_date(version.approved_at),
            }
        else:
            card["subtitle"] = self._ea_pick("version %s · awaiting the partner's approval", "version %s · à approuver par l'associé") % version.version_no
        benchmark = _BENCHMARK.get(version.benchmark)
        card["facts"] = [
            {"label": self._ea_pick("Benchmark", "Référentiel"), "value": self._ea_pick(*benchmark) if benchmark else version.benchmark},
            {"label": self._ea_pick("Base amount", "Montant de base"), "value": fcfa(version.benchmark_amount)},
            {"label": self._ea_pick("Percentage", "Pourcentage"), "value": "%s%%" % version.percentage},
            {"label": self._ea_pick("Overall materiality", "Seuil de signification"), "value": fcfa(version.overall)},
            {"label": self._ea_pick("Performance materiality (%s%%)", "Seuil de travail (%s %%)") % version.performance_pct, "value": fcfa(version.performance)},
            {"label": self._ea_pick("Clearly trivial (%s%%)", "Anomalies manifestement négligeables (%s %%)") % version.trivial_pct, "value": fcfa(version.trivial)},
        ]
        if _filled(version.justification):
            card["note"] = self._ea_pick("Justification (from the tool): %s", "Justification (dans l'outil) : %s") % version.justification.strip()
        return card

    def _ea_hook_done_materiality_benchmark(self):
        version = self._ea_materiality_version()
        benchmark = _BENCHMARK.get(version.benchmark) if version else None
        label = self._ea_pick(*benchmark) if benchmark else (version.benchmark if version else "")
        return self._ea_done_if(version, self._ea_pick("%s · justification recorded in the tool", "%s · justification consignée dans l'outil") % label)

    def _ea_hook_done_materiality_figure(self):
        version = self._ea_materiality_version()
        return self._ea_done_if(version, version and fcfa(version.benchmark_amount))

    def _ea_hook_done_materiality_percentage(self):
        version = self._ea_materiality_version()
        return self._ea_done_if(version, version and "%s%%" % version.percentage)

    def _ea_hook_done_materiality_pm(self):
        version = self._ea_materiality_version()
        return self._ea_done_if(version, version and "%s%% · %s" % (version.performance_pct, fcfa(version.performance)))

    def _ea_hook_done_materiality_trivial(self):
        version = self._ea_materiality_version()
        return self._ea_done_if(version, version and "%s (%s%%)" % (fcfa(version.trivial), version.trivial_pct))

    def _ea_hook_check_materiality_approved(self):
        version = self._ea_materiality_version()
        if not version:
            return {"ok": None, "note": ""}
        return {"ok": True, "note": ""}

    # ------------------------------------------------------------------
    # P6.2 significant accounts
    # ------------------------------------------------------------------

    def _ea_significance(self):
        engagement = self.sudo().engagement_id
        rows = engagement._ea_significance_rows()
        materiality = engagement._ea_materiality_dict()
        return rows, materiality

    def _ea_hook_card_significance(self):
        rows, materiality = self._ea_significance()
        significant = [row for row in rows if row["status"] == "significant"]
        card = {
            "title": self._ea_pick("From the Significant accounts tool", "Depuis l'outil des comptes significatifs"),
            "open_label": self._ea_pick("Open the Significant accounts tool", "Ouvrir l'outil des comptes significatifs"),
            "action": self._ea_open("action_tool_significance"),
            "note": self._ea_pick(
                "The screen and the decisions are made in the tool; this paper shows them and records the judgements.",
                "Le filtre et les décisions sont faits dans l'outil ; ce papier les reprend et documente les jugements.",
            ),
            "warnings": self._ea_hook_warn_significance(),
        }
        if not rows:
            card["empty"] = self._ea_pick("No trial balance line yet.", "Aucune ligne de balance pour le moment.")
            return card
        card["facts"] = [
            {"label": self._ea_pick("Lead indexes with a balance", "Index avec un solde"), "value": str(len(rows))},
            {"label": self._ea_pick("Significant", "Significatifs"), "value": str(len(significant))},
        ]
        if materiality:
            card["facts"].append({
                "label": self._ea_pick("Screen", "Filtre"),
                "value": self._ea_pick("above performance materiality %s", "au-dessus du seuil de travail %s") % fcfa(materiality["performance"]),
            })
        card["head"] = [self._ea_pick("Account", "Compte"), self._ea_pick("Closing balance", "Solde de clôture"), self._ea_pick("Why significant", "Pourquoi significatif")]

        def why(row):
            if row["hasRisk"]:
                return self._ea_pick("a risk is linked", "un risque y est lié")
            if row["overridden"]:
                return self._ea_pick("brought in: %s", "retenu : %s") % (row["justification"] or "—")
            return self._ea_pick("above performance materiality", "au-dessus du seuil de travail")

        card["rows"] = [[self._ea_index_label(row["index"]), fcfa(row["closing"]), why(row)] for row in significant[:_ROWS_SHOWN]]
        card["more"] = self._ea_more(len(significant))
        return card

    def _ea_hook_warn_significance(self):
        rows, _materiality = self._ea_significance()
        count = unjustified_count(rows)
        if not count:
            return []
        return [self._ea_pick(
            "%d decision(s) depart from the screen without a written reason.",
            "%d décision(s) s'écartent du filtre sans justification écrite.",
        ) % count]

    def _ea_hook_done_significance_listed(self):
        rows, _materiality = self._ea_significance()
        return self._ea_done_if(rows, self._ea_pick("%d lead indexes from the trial balance", "%d index issus de la balance") % len(rows))

    def _ea_hook_done_significance_quant(self):
        rows, materiality = self._ea_significance()
        above = len([row for row in rows if row["aboveTe"]])
        return self._ea_done_if(rows and materiality, materiality and self._ea_pick(
            "against performance materiality %s; %d above it", "par rapport au seuil de travail %s ; %d au-dessus",
        ) % (fcfa(materiality["performance"]), above))

    def _ea_significant_without_assertion(self):
        rows, _materiality = self._ea_significance()
        significant = {row["index"] for row in rows if row["status"] == "significant"}
        cells = self.env["ea.audit.cra.assessment"].sudo().search([
            ("engagement_id", "=", self.sudo().engagement_id.id), ("relevant", "=", True),
        ])
        return significant, significant - set(cells.mapped("index_code"))

    def _ea_hook_done_significance_assertions(self):
        significant, missing = self._ea_significant_without_assertion()
        return self._ea_done_if(significant and not missing, self._ea_pick(
            "relevant assertions recorded for the %d significant accounts", "assertions pertinentes consignées pour les %d comptes significatifs",
        ) % len(significant))

    def _ea_hook_check_significance_screen(self):
        rows, _materiality = self._ea_significance()
        if not rows:
            return {"ok": None, "note": ""}
        count = unjustified_count(rows)
        return {"ok": not count, "note": self._ea_hook_warn_significance()[0] if count else ""}

    def _ea_hook_check_significance_assertions(self):
        significant, missing = self._ea_significant_without_assertion()
        if not significant:
            return {"ok": None, "note": ""}
        return {"ok": not missing, "note": ", ".join(sorted(missing))}

    def _ea_hook_check_significance_linked(self):
        uncovered = self.sudo().engagement_id._ea_scot_studio()["uncoveredIndexes"]
        if not self.sudo().engagement_id.scot_ids:
            return {"ok": None, "note": ""}
        return {"ok": not uncovered, "note": ", ".join(uncovered)}

    # ------------------------------------------------------------------
    # S1.1 to S1.3: SCOTs, flows and controls, walkthroughs
    # ------------------------------------------------------------------

    def _ea_scots(self):
        return self.sudo().engagement_id.scot_ids

    def _ea_scot_card(self, title_en, title_fr):
        return {
            "title": self._ea_pick(title_en, title_fr),
            "open_label": self._ea_pick("Open the SCOTs and controls tool", "Ouvrir l'outil des flux et contrôles"),
            "action": self._ea_open("action_tool_scot"),
            "note": self._ea_pick(
                "The work is recorded in the tool; this paper shows it and records the judgements.",
                "Les travaux sont consignés dans l'outil ; ce papier les reprend et documente les jugements.",
            ),
            "empty": self._ea_pick("No class of transactions recorded yet.", "Aucun flux de transactions consigné pour le moment."),
        }

    def _ea_hook_card_scot(self):
        scots = self._ea_scots()
        card = self._ea_scot_card("From the SCOTs and controls tool", title_fr="Depuis l'outil des flux et contrôles")
        if not scots:
            return card
        engagement = self.sudo().engagement_id
        uncovered = engagement._ea_scot_studio()["uncoveredIndexes"]
        significant = [row["index"] for row in engagement._ea_significance_rows() if row["status"] == "significant"]
        types = dict(scots._fields["transaction_type"]._description_selection(self.env))
        apps = sorted({app.strip() for scot in scots for app in (scot.applications or "").split(",") if app.strip()})
        card["subtitle"] = self._ea_pick("%d classes of transactions", "%d flux de transactions") % len(scots)
        card["facts"] = [
            {"label": self._ea_pick("Classes of transactions", "Flux de transactions"), "value": str(len(scots))},
            {"label": self._ea_pick("Significant accounts reached", "Comptes significatifs couverts"),
             "value": "%d / %d" % (len(significant) - len(uncovered), len(significant))},
            {"label": self._ea_pick("IT applications", "Applications informatiques"), "value": ", ".join(apps) or "—"},
        ]
        card["head"] = [
            self._ea_pick("Class of transactions", "Flux"), self._ea_pick("Type", "Type"),
            self._ea_pick("Applications", "Applications"), self._ea_pick("Significant accounts", "Comptes significatifs"),
        ]
        card["rows"] = [
            [scot.name, types.get(scot.transaction_type, ""), scot.applications or "—", scot.index_summary or "—"]
            for scot in scots[:_ROWS_SHOWN]
        ]
        card["more"] = self._ea_more(len(scots))
        return card

    def _ea_hook_done_scot_classes(self):
        scots = self._ea_scots()
        return self._ea_done_if(scots, self._ea_pick("%d classes recorded", "%d flux consignés") % len(scots))

    def _ea_hook_done_scot_classified(self):
        scots = self._ea_scots()
        return self._ea_done_if(scots, self._ea_pick("recorded for each class", "consigné pour chaque flux"))

    def _ea_hook_done_scot_apps(self):
        scots = self._ea_scots()
        apps = sorted({app.strip() for scot in scots for app in (scot.applications or "").split(",") if app.strip()})
        return self._ea_done_if(scots and all(_filled(scot.applications) for scot in scots), ", ".join(apps))

    def _ea_hook_done_scot_accounts(self):
        scots = self._ea_scots()
        engagement = self.sudo().engagement_id
        uncovered = engagement._ea_scot_studio()["uncoveredIndexes"]
        significant = [row["index"] for row in engagement._ea_significance_rows() if row["status"] == "significant"]
        return self._ea_done_if(scots and significant and not uncovered, self._ea_pick(
            "%d of %d accounts reached", "%d sur %d comptes couverts",
        ) % (len(significant), len(significant)))

    def _ea_hook_check_scot_accounts(self):
        if not self._ea_scots():
            return {"ok": None, "note": ""}
        uncovered = self.sudo().engagement_id._ea_scot_studio()["uncoveredIndexes"]
        return {"ok": not uncovered, "note": ", ".join(uncovered)}

    def _ea_hook_check_scot_classified(self):
        scots = self._ea_scots()
        return {"ok": True if scots else None, "note": ""}

    def _ea_hook_check_scot_apps(self):
        scots = self._ea_scots()
        if not scots:
            return {"ok": None, "note": ""}
        missing = scots.filtered(lambda scot: not _filled(scot.applications))
        return {"ok": not missing, "note": ", ".join(missing.mapped("name"))}

    def _ea_flow_counts(self, scot):
        wcgws = scot.wcgw_ids
        controls = scot.control_ids
        ineffective = controls.filtered(lambda c: c.design_eval == "ineffective")
        gaps = len(wcgws.filtered(lambda w: not w.control_ids)) + len(ineffective)
        return wcgws, controls, ineffective, gaps

    def _ea_hook_card_scot_flows(self):
        scots = self._ea_scots()
        card = self._ea_scot_card("From the SCOTs and controls tool", title_fr="Depuis l'outil des flux et contrôles")
        if not scots:
            return card
        wcgws = scots.wcgw_ids
        controls = scots.control_ids
        gaps = sum(self._ea_flow_counts(scot)[3] for scot in scots)
        card["subtitle"] = self._ea_pick("flows, what can go wrong and controls", "flux, risques d'anomalies et contrôles")
        card["facts"] = [
            {"label": self._ea_pick("What can go wrong", "Risques d'anomalies"), "value": str(len(wcgws))},
            {"label": self._ea_pick("Controls identified", "Contrôles identifiés"), "value": str(len(controls))},
            {"label": self._ea_pick("Gaps (no control or poor design)", "Lacunes (sans contrôle ou mal conçu)"), "value": str(gaps)},
        ]
        card["head"] = [
            self._ea_pick("Class of transactions", "Flux"), self._ea_pick("What can go wrong", "Risques"),
            self._ea_pick("Controls", "Contrôles"), self._ea_pick("Design", "Conception"), self._ea_pick("Gaps", "Lacunes"),
        ]
        rows = []
        for scot in scots[:_ROWS_SHOWN]:
            wcgw, ctl, ineffective, gap = self._ea_flow_counts(scot)
            unevaluated = ctl.filtered(lambda c: not c.design_eval)
            if ineffective:
                design = self._ea_pick("%d ineffective", "%d inefficace(s)") % len(ineffective)
            elif unevaluated:
                design = self._ea_pick("%d to evaluate", "%d à évaluer") % len(unevaluated)
            else:
                design = self._ea_pick("effective", "efficace") if ctl else "—"
            rows.append([scot.name, str(len(wcgw)), str(len(ctl)), design, str(gap) if gap else "—"])
        card["rows"] = rows
        card["more"] = self._ea_more(len(scots))
        return card

    def _ea_hook_done_scot_flows(self):
        scots = self._ea_scots()
        ok = scots and all(scot.wcgw_ids for scot in scots)
        return self._ea_done_if(ok, self._ea_pick("documented for all %d classes", "documentés pour les %d flux") % len(scots))

    def _ea_hook_done_scot_wcgw(self):
        wcgws = self._ea_scots().wcgw_ids
        ok = wcgws and all(w.assertion_ids for w in wcgws)
        return self._ea_done_if(ok, self._ea_pick("%d entries, each with its assertion", "%d risques, chacun avec son assertion") % len(wcgws))

    def _ea_hook_done_scot_controls(self):
        scots = self._ea_scots()
        wcgws = scots.wcgw_ids
        ok = wcgws and all(w.control_ids for w in wcgws)
        return self._ea_done_if(ok, self._ea_pick("%d controls", "%d contrôles") % len(scots.control_ids))

    def _ea_hook_done_scot_design(self):
        controls = self._ea_scots().control_ids
        ok = controls and all(c.design_eval for c in controls)
        ineffective = controls.filtered(lambda c: c.design_eval == "ineffective")
        return self._ea_done_if(ok, self._ea_pick("%d effective, %d ineffective", "%d efficace(s), %d inefficace(s)") % (
            len(controls) - len(ineffective), len(ineffective),
        ))

    def _ea_hook_check_scot_flows(self):
        scots = self._ea_scots()
        if not scots:
            return {"ok": None, "note": ""}
        missing = scots.filtered(lambda scot: not scot.wcgw_ids or not scot.control_ids)
        return {"ok": not missing, "note": ", ".join(missing.mapped("name"))}

    def _ea_hook_check_scot_wcgw_assertions(self):
        wcgws = self._ea_scots().wcgw_ids
        if not wcgws:
            return {"ok": None, "note": ""}
        return {"ok": all(w.assertion_ids for w in wcgws), "note": ""}

    def _ea_hook_check_scot_design(self):
        controls = self._ea_scots().control_ids
        if not controls:
            return {"ok": None, "note": ""}
        return {"ok": all(c.design_eval for c in controls), "note": ""}

    def _ea_hook_card_walkthroughs(self):
        scots = self._ea_scots()
        card = self._ea_scot_card("From the SCOTs and controls tool · walkthroughs", title_fr="Depuis l'outil des flux et contrôles · tests de cheminement")
        card["open_label"] = self._ea_pick("Open the walkthroughs", "Ouvrir les tests de cheminement")
        if not scots:
            return card
        done = scots.filtered(lambda scot: not scot.walkthrough_open)
        controls = scots.control_ids
        seen = controls.filtered(lambda c: c.implemented == "yes")
        card["facts"] = [
            {"label": self._ea_pick("Walkthroughs done", "Tests de cheminement réalisés"), "value": "%d / %d" % (len(done), len(scots))},
            {"label": self._ea_pick("Controls seen implemented", "Contrôles vus en place"), "value": "%d / %d" % (len(seen), len(controls))},
        ]
        card["head"] = [
            self._ea_pick("Class of transactions", "Flux"), self._ea_pick("Transaction traced", "Transaction suivie"),
            self._ea_pick("Controls seen", "Contrôles vus"), self._ea_pick("Status", "État"),
        ]
        rows = []
        for scot in scots[:_ROWS_SHOWN]:
            ctl = scot.control_ids
            status = self._ea_pick("done", "fait") if not scot.walkthrough_open else self._ea_pick("%d answers missing", "%d réponses manquantes") % scot.walkthrough_open
            rows.append([
                scot.name, (scot.wt_item or "—")[:80],
                "%d / %d" % (len(ctl.filtered(lambda c: c.implemented == "yes")), len(ctl)), status,
            ])
        card["rows"] = rows
        card["more"] = self._ea_more(len(scots))
        return card

    def _ea_walkthrough_all(self, key):
        scots = self._ea_scots()
        return scots, bool(scots) and all(_filled(scot[key]) for scot in scots)

    def _ea_hook_done_walkthrough_selected(self):
        scots, ok = self._ea_walkthrough_all("wt_item")
        return self._ea_done_if(ok, self._ea_pick("one transaction for each of the %d classes", "une transaction pour chacun des %d flux") % len(scots))

    def _ea_hook_done_walkthrough_traced(self):
        scots, ok = self._ea_walkthrough_all("wt_trace")
        return self._ea_done_if(ok, self._ea_pick("steps recorded against the S1.2 flow", "étapes consignées au regard du flux de S1.2"))

    def _ea_hook_done_walkthrough_differences(self):
        scots = self._ea_scots()
        ok = bool(scots) and not any(scot.walkthrough_open for scot in scots)
        return self._ea_done_if(ok, self._ea_pick("recorded in the conclusion of each walkthrough", "consignées dans la conclusion de chaque test de cheminement"))

    def _ea_hook_check_walkthrough_all(self):
        scots = self._ea_scots()
        if not scots:
            return {"ok": None, "note": ""}
        open_ = scots.filtered("walkthrough_open")
        return {"ok": not open_, "note": ", ".join(open_.mapped("name"))}

    def _ea_hook_check_walkthrough_differences(self):
        return self._ea_hook_check_walkthrough_all()

    # ------------------------------------------------------------------
    # S1.4 financial statement close process
    # ------------------------------------------------------------------

    def _ea_fscp(self):
        return self.env["ea.audit.fscp"].sudo().search([("engagement_id", "=", self.sudo().engagement_id.id)], limit=1)

    def _ea_fscp_filled(self, keys):
        record = self._ea_fscp()
        return bool(record) and all(_filled(str(record[key] or "")) for key in keys)

    def _ea_hook_card_fscp(self):
        record = self._ea_fscp()
        card = {
            "title": self._ea_pick("From the Financial statement close process tool", "Depuis l'outil du processus de clôture"),
            "open_label": self._ea_pick("Open the close process tool", "Ouvrir l'outil du processus de clôture"),
            "action": self._ea_open("action_tool_fscp"),
            "note": self._ea_pick(
                "The work is recorded in the tool; this paper shows it and records the judgements.",
                "Les travaux sont consignés dans l'outil ; ce papier les reprend et documente les jugements.",
            ),
        }
        if not record:
            card["empty"] = self._ea_pick("The close process is not documented in the tool yet.", "Le processus de clôture n'est pas encore documenté dans l'outil.")
            return card
        keys = [field["key"] for field in FSCP_FIELDS]
        answered = [key for key in keys if _filled(str(record[key] or ""))]
        card["facts"] = [{"label": self._ea_pick("Questions answered", "Questions renseignées"), "value": "%d / %d" % (len(answered), len(keys))}]
        card["head"] = [self._ea_pick("Area", "Domaine"), self._ea_pick("Status", "État")]
        card["rows"] = [
            [self._ea_pick(*label), self._ea_pick("complete", "complet") if all(k in answered for k in area) else self._ea_pick("to complete", "à compléter")]
            for label, area in _FSCP_AREAS
        ]
        return card

    def _ea_hook_done_fscp_calendar(self):
        ok = self._ea_fscp_filled(("tb_preparation", "fs_preparation"))
        return self._ea_done_if(ok, self._ea_pick("steps from trial balance to financial statements recorded", "étapes de la balance aux états financiers consignées"))

    def _ea_hook_done_fscp_je(self):
        ok = self._ea_fscp_filled(("je_process", "je_controls_design", "je_controls_implemented"))
        return self._ea_done_if(ok, self._ea_pick("posting rights and approval of manual entries recorded", "droits de saisie et approbation des écritures manuelles consignés"))

    def _ea_fscp_check(self, keys):
        if not self._ea_fscp():
            return {"ok": None, "note": ""}
        return {"ok": self._ea_fscp_filled(keys), "note": ""}

    def _ea_hook_check_fscp_documented(self):
        return self._ea_fscp_check(("tb_preparation", "fs_preparation", "disclosure_sources", "policies_it"))

    def _ea_hook_check_fscp_je(self):
        return self._ea_fscp_check(("je_process",))

    def _ea_hook_check_fscp_override(self):
        return self._ea_fscp_check(("override_risk",))

    # ------------------------------------------------------------------
    # S3.1 combined risk assessment
    # ------------------------------------------------------------------

    def _ea_cra_cells(self):
        return self.env["ea.audit.cra.assessment"].sudo().search([
            ("engagement_id", "=", self.sudo().engagement_id.id), ("relevant", "=", True),
        ])

    def _ea_hook_card_cra(self):
        cells = self._ea_cra_cells()
        card = {
            "title": self._ea_pick("From the Combined risk assessment tool", "Depuis l'outil d'évaluation combinée des risques"),
            "open_label": self._ea_pick("Open the Combined risk assessment", "Ouvrir l'évaluation combinée des risques"),
            "action": self._ea_open("action_tool_cra"),
            "note": self._ea_pick(
                "The work is recorded in the tool; this paper shows it and records the judgements.",
                "Les travaux sont consignés dans l'outil ; ce papier les reprend et documente les jugements.",
            ),
        }
        if not cells:
            card["empty"] = self._ea_pick("No account and assertion assessed yet.", "Aucun compte ni assertion évalué pour le moment.")
            return card
        levels = dict(cells._fields["level"]._description_selection(self.env))
        irs = dict(cells._fields["ir"]._description_selection(self.env))
        crs = dict(cells._fields["cr"]._description_selection(self.env))
        risks = self.env["ea.audit.risk"].sudo().search([("engagement_id", "=", self.sudo().engagement_id.id)])
        card["facts"] = [
            {"label": self._ea_pick("Account × assertion cells", "Cellules compte × assertion"), "value": str(len(cells))},
            {"label": self._ea_pick("Higher inherent risk", "Risque inhérent élevé"), "value": str(len(cells.filtered(lambda c: c.ir == "higher")))},
            {"label": self._ea_pick("Significant risks", "Risques importants"), "value": str(len(risks.filtered("significant")))},
            {"label": self._ea_pick("Cells to assess", "Cellules à évaluer"), "value": str(len(self.sudo().engagement_id._ea_cra_to_assess()))},
        ]
        card["head"] = [
            self._ea_pick("Account", "Compte"), self._ea_pick("Assertion", "Assertion"), self._ea_pick("Inherent risk", "Risque inhérent"),
            self._ea_pick("Controls", "Contrôles"), self._ea_pick("Combined", "Combiné"), self._ea_pick("Significant risk", "Risque important"),
        ]
        order = {"high": 0, "moderate": 1, "low": 2, "minimal": 3, "to_assess": 4}
        ranked = cells.sorted(lambda c: (not c.significant, order.get(c.level, 5), c.index_code, c.assertion))
        card["rows"] = [
            [
                self._ea_index_label(cell.index_code), cell.assertion, irs.get(cell.ir, "—"), crs.get(cell.cr, "—"),
                levels.get(cell.level, "—"), self._ea_pick("Yes", "Oui") if cell.significant else "—",
            ]
            for cell in ranked[:_ROWS_SHOWN]
        ]
        card["more"] = self._ea_more(len(cells))
        return card

    def _ea_hook_done_cra_gather(self):
        risks = self.env["ea.audit.risk"].sudo().search([("engagement_id", "=", self.sudo().engagement_id.id)])
        return self._ea_done_if(risks, self._ea_pick("%d risks on the register", "%d risques au registre") % len(risks))

    def _ea_hook_done_cra_assertion(self):
        cells = self._ea_cra_cells()
        return self._ea_done_if(cells, self._ea_pick("%d cells", "%d cellules") % len(cells))

    def _ea_hook_done_cra_separate(self):
        cells = self._ea_cra_cells()
        ok = cells and not self.sudo().engagement_id._ea_cra_to_assess()
        return self._ea_done_if(ok, self._ea_pick("for every cell", "pour chaque cellule"))

    def _ea_hook_done_cra_strategy(self):
        engagement = self.sudo().engagement_id
        scots = engagement.scot_ids
        violations = engagement._ea_scot_studio()["para33Violations"]
        relied = scots.filtered(lambda scot: scot.strategy == "controls")
        return self._ea_done_if(scots and not violations, self._ea_pick(
            "rely on %d class(es); not rely on %d", "confiance sur %d flux ; pas de confiance sur %d",
        ) % (len(relied), len(scots) - len(relied)))

    def _ea_hook_check_cra_assertions(self):
        # risks at financial statement level (management override) name no account by nature
        risks = self.env["ea.audit.risk"].sudo().search([
            ("engagement_id", "=", self.sudo().engagement_id.id), ("rebutted", "=", False), ("level", "=", "assertion"),
        ])
        if not risks:
            return {"ok": None, "note": ""}
        unlinked = risks.filtered(lambda risk: not risk.index_link_ids)
        return {"ok": not unlinked, "note": ""}

    def _ea_hook_check_cra_separate(self):
        cells = self._ea_cra_cells()
        if not cells:
            return {"ok": None, "note": ""}
        return {"ok": not self.sudo().engagement_id._ea_cra_to_assess(), "note": ""}

    def _ea_hook_check_cra_reliance(self):
        engagement = self.sudo().engagement_id
        relied = engagement.scot_ids.filtered(lambda scot: scot.strategy == "controls")
        if not relied:
            return {"ok": None, "note": ""}
        missing = relied.filtered(lambda scot: not scot.control_ids.filtered("selected_for_testing"))
        return {"ok": not missing, "note": ", ".join(missing.mapped("name"))}

    # ------------------------------------------------------------------
    # S4.2 going concern: equity against half of the share capital
    # ------------------------------------------------------------------

    def _ea_equity_figures(self):
        engagement = self.sudo().engagement_id
        if not hasattr(engagement, "_ea_compute_equity"):
            return None
        figures = engagement._ea_compute_equity()
        return figures if figures.get("has_tb") else None

    def _ea_hook_card_going_concern(self):
        figures = self._ea_equity_figures()
        card = {
            "title": self._ea_pick("Pre-filled from the data", "Prérempli à partir des données"),
            "open_label": self._ea_pick("Open the Financial analysis", "Ouvrir l'analyse financière"),
            "action": self._ea_open("action_tool_financial"),
            "warnings": self._ea_hook_warn_going_concern(),
        }
        if not figures:
            card["empty"] = self._ea_pick("No trial balance yet: the equity check runs once one is imported.", "Pas encore de balance : le contrôle des capitaux propres se fait dès son import.")
            return card
        card["facts"] = [{"label": self._ea_pick("Equity, result included", "Capitaux propres, résultat compris"), "value": fcfa(figures["equity"])}]
        if figures.get("half_capital") is not None:
            card["facts"].append({"label": self._ea_pick("Half of the share capital", "Moitié du capital social"), "value": fcfa(figures["half_capital"])})
            card["facts"].append({
                "label": self._ea_pick("Equity against half of the capital", "Capitaux propres / moitié du capital"),
                "value": self._ea_pick("below: art. 664 / 371 applies", "inférieurs : art. 664 / 371 applicables") if figures["breach"]
                else self._ea_pick("not below ✓", "pas inférieurs ✓"),
            })
        return card

    def _ea_hook_warn_going_concern(self):
        figures = self._ea_equity_figures()
        if figures and figures.get("breach"):
            return [self._ea_pick(
                "Equity is below half of the share capital (OHADA art. 664 / 371).",
                "Les capitaux propres sont inférieurs à la moitié du capital social (OHADA art. 664 / 371).",
            )]
        return []

    def _ea_hook_check_going_concern_equity(self):
        figures = self._ea_equity_figures()
        if not figures or figures.get("half_capital") is None:
            return {"ok": None, "note": ""}
        return {"ok": not figures["breach"], "note": ""}
