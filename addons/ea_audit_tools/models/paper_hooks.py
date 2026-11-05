"""What the papers addon asks of the tools: its gaps, the parts of a signature's hash, the
auto fields, the header chips, and the board shown in a paper. The papers addon stays
unaware of the tools; every reader here is the tools' own."""
from odoo import models

from ..services.lead_classes import INDEX_SECTION
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
                {"label": _words(self.env, "Clairement négligeable", "Clearly trivial"), "value": fcfa(version.trivial)},
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
            values["framework"] = dict(
                engagement._fields["framework"]._description_selection(self.env)
            ).get(engagement.framework) or ""
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
            "clairement négligeable %(trivial)s. Version %(version)s approuvée par %(who)s le %(on)s."
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
        return links

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
