import re

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.signoff_rules import can_partner_signoff
from odoo.addons.ea_audit_papers.services.tokens import organ_name, resolve_legal_form_text
from odoo.addons.ea_audit_reports.services.articles import mark_articles
from odoo.addons.ea_audit_reports.services.docx_builder import block
from odoo.addons.ea_audit_reports.services.letters import mandate_expiry_year
from odoo.addons.ea_audit_reports.services.opinion import period_end_text
from odoo.addons.ea_audit_tools.models.tool_record import fcfa as tools_fcfa
from odoo.addons.ea_audit_tools.models.tool_record import french_date
from odoo.addons.ea_audit_tools.services import alerte as alerte_engine
from odoo.addons.ea_audit_tools.services.errors import ServiceError
from odoo.addons.ea_audit_tools.services.legal import add_months_clamped

from ..rules import rule_error
from ..services.texts import (
    CAPACITIES, CAPACITY_EN, CAPACITY_FR, EGM_EQUITY_BASIS, EGM_EQUITY_BASIS_FR, STAGE_DOC_TITLES_EN, STAGE_DOC_TITLES_FR, STAGE_LETTERS, amount_or_nd, deadline_rows,
    equity_conclusion_of, fmt_amount, persons_from_headcount, signature_blocks,
)

_JOINT_KEYS = ("worksplit", "crossreview", "disagreement")


def _p(text):
    return block("p", text)


def _b(text):
    return block("b", text)


def _h(text):
    return block("h", text)


def _title(text):
    return block("title", text)


class Engagement(models.Model):
    _inherit = "ea.audit.engagement"

    legal_deadline_ids = fields.One2many("ea.audit.legal.deadline", "engagement_id", string="Statutory deadlines")
    regulated_agreement_ids = fields.One2many("ea.audit.regulated.agreement", "engagement_id", string="Regulated agreements")
    alerte_ids = fields.One2many("ea.audit.alerte", "engagement_id", string="Alert procedures")
    legal_form_name = fields.Char(string="Legal form", compute="_compute_legal_cards", compute_sudo=True)
    legal_board_name = fields.Char(string="Organ closing the accounts", compute="_compute_legal_cards", compute_sudo=True)
    legal_meeting_name = fields.Char(string="Owners' assembly", compute="_compute_legal_cards", compute_sudo=True)
    legal_overdue_count = fields.Integer(string="Overdue deadlines", compute="_compute_legal_cards", compute_sudo=True)
    legal_alerte_stage = fields.Char(string="Alert procedure", compute="_compute_legal_cards", compute_sudo=True)
    legal_equity_label = fields.Char(string="Net equity", compute="_compute_legal_cards", compute_sudo=True)
    legal_half_capital_label = fields.Char(string="Half of the capital", compute="_compute_legal_cards", compute_sudo=True)
    legal_equity_conclusion = fields.Selection(
        [("none", "No figures"), ("ok", "Above half of the capital"), ("stale", "Figures moved: check again"),
         ("unchecked-breach", "Below half: run the check"), ("breach", "Below half: procedure running")],
        string="C5.8 conclusion", compute="_compute_legal_cards", compute_sudo=True,
    )
    legal_titres_available = fields.Boolean(compute="_compute_legal_cards", compute_sudo=True)

    @api.depends_context("lang")
    def _compute_legal_cards(self):
        fr = (self.env.lang or "").startswith("fr")
        locale = "fr" if fr else "en"
        for engagement in self:
            form = engagement.client_id.legal_form
            engagement.legal_form_name = organ_name(form, "form", locale)
            engagement.legal_board_name = organ_name(form, "board", locale)
            engagement.legal_meeting_name = organ_name(form, "meeting", locale)
            today = fields.Date.context_today(self)
            engagement.legal_overdue_count = len(engagement.legal_deadline_ids.filtered(lambda d: not d.done and d.due_date < today))
            current = engagement._ea_current_alerte()
            engagement.legal_alerte_stage = (
                dict(current._fields["stage"]._description_selection(self.env)).get(current.stage) if current else False
            )
            figures = engagement._ea_compute_equity()
            engagement.legal_equity_label = tools_fcfa(figures["equity"]) if figures["has_tb"] else "—"
            engagement.legal_half_capital_label = tools_fcfa(figures["half_capital"]) if figures["half_capital"] is not None else "—"
            engagement.legal_equity_conclusion = engagement._ea_equity_conclusion(figures)
            engagement.legal_titres_available = bool(engagement.file_item_ids.filtered(lambda i: i.code == "C5.7"))

    # ------------------------------------------------------------------
    # The guard, and the plain helpers
    # ------------------------------------------------------------------

    def _ea_legal_guard(self):
        """Read-only may view the legal file, not change it (UAT B10)."""
        self.ensure_one()
        self._ea_tool_guard()

    def _ea_validated(self):
        return self.env.company.sudo().ea_articles_validated

    def _ea_organ(self, text):
        """"à l'[[lf.board]]" in the legal form of this client and the report language, with the
        right article in French."""
        return resolve_legal_form_text(text, self.sudo().client_id.legal_form, "fr" if self._ea_report_fr() else "en")

    def _ea_prose_date(self, value):
        return period_end_text(value, self._ea_report_fr())

    def _ea_iso(self, value):
        return value.isoformat() if value else None

    def _ea_service(self, func, *args, **kwargs):
        """A refusal of a pure service, as the rule error of its code."""
        try:
            return func(*args, **kwargs)
        except ServiceError as error:
            raise rule_error(self.env, error.code) from None

    def _ea_today_iso(self):
        return fields.Date.context_today(self).isoformat()

    # ------------------------------------------------------------------
    # C5.2 statutory deadlines
    # ------------------------------------------------------------------

    def _ea_upsert_deadline(self, key, due, basis):
        Deadline = self.env["ea.audit.legal.deadline"].sudo()
        basis = mark_articles(basis, self._ea_validated(), self._ea_report_fr())
        row = Deadline.search([("engagement_id", "=", self.id), ("key", "=", key)], limit=1)
        if row:
            row.write({"due_date": due, "basis": basis})
        else:
            Deadline.create({"engagement_id": self.id, "key": key, "due_date": due, "basis": basis})

    def generate_deadlines(self):
        """generateDeadlines: from period end, general meeting and report dates; then the escalation."""
        self._ea_legal_guard()
        row, client = self.sudo(), self.sudo().client_id
        for item in deadline_rows(
            row.period_end.isoformat(), self._ea_iso(row.agm_date), self._ea_iso(row.report_date), self._ea_iso(row.board_date),
            client.mandate_type, client.mandate_start_year, row.fiscal_year, mandate_expiry_year,
        ):
            self._ea_upsert_deadline(item["key"], item["due"], item["basisFr" if self._ea_report_fr() else "basisEn"])
        self._ea_escalate_overdue()
        return row.legal_deadline_ids

    def set_legal_dates(self, agm_date=None, report_date=None, board_date=None, clear_board=False):
        """setLegalDates: the planned meeting dates; the calendar follows. A report date already
        stamped stays. ``clear_board`` empties the board date, as undefined and null differ in the source."""
        self._ea_legal_guard()
        try:
            agm = fields.Date.to_date(agm_date) if agm_date else False
            report = fields.Date.to_date(report_date) if report_date else False
            board = fields.Date.to_date(board_date) if board_date else False
        except ValueError:
            raise rule_error(self.env, "invalid-date") from None
        vals = {"agm_date": agm}
        if report:
            vals["report_date"] = report
        if board or clear_board:
            vals["board_date"] = board
        self.sudo().write(vals)
        if clear_board and not board:
            self.env["ea.audit.legal.deadline"].sudo().search([
                ("engagement_id", "=", self.id), ("key", "=", "art715_board"), ("done", "=", False),
            ]).unlink()
        return self.generate_deadlines()

    def mark_deadline_done(self, key):
        self._ea_legal_guard()
        self.env["ea.audit.legal.deadline"].sudo().search([("engagement_id", "=", self.id), ("key", "=", key)]).write({
            "done": True, "done_at": fields.Datetime.now(),
        })
        return True

    def _ea_escalate_overdue(self):
        """escalateOverdue (UAT B102): one notification per partner and deadline."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        overdue = self.env["ea.audit.legal.deadline"].sudo().search([
            ("engagement_id", "=", self.id), ("done", "=", False), ("due_date", "<", today),
        ])
        Notice = self.env["ea.audit.notice"].sudo()
        partners = self.sudo()._ea_partner_users()
        for deadline in overdue:
            for partner in partners:
                reader = self.with_context(lang=partner.lang or self.env.lang).env
                title = reader._("Statutory deadline overdue: %(key)s", key=deadline.key)
                if Notice.search_count([("engagement_id", "=", self.id), ("user_id", "=", partner.id), ("kind", "=", "deadline-overdue"), ("title", "=", title)]):
                    continue
                self.sudo()._ea_notify(partner, "deadline-overdue", title, reader._("Deadline %(date)s: open the statutory calendar to clear it.", date=french_date(deadline.due_date)))
        return len(overdue)

    def escalate_overdue(self):
        self._ea_legal_guard()
        return self._ea_escalate_overdue()

    @api.model
    def _ea_cron_legal_deadlines(self):
        """Daily: the escalation of every open file, and the 60-day assembly reminder it carries."""
        for engagement in self.sudo().search([("archived_at", "=", False), ("legal_deadline_ids", "!=", False)]):
            engagement._ea_escalate_overdue()

    # ------------------------------------------------------------------
    # C5.3 regulated agreements and the special report
    # ------------------------------------------------------------------

    def add_convention(self, parties, interested, capacity, nature, terms="", amounts_period=None, continuing=False, board_auth_ref=None, notified_at=None):
        self._ea_legal_guard()
        if not (parties or "").strip() or not (interested or "").strip() or not (nature or "").strip():
            raise rule_error(self.env, "fields-required")
        if capacity not in CAPACITIES:
            raise rule_error(self.env, "invalid-capacity")
        return self.env["ea.audit.regulated.agreement"].sudo().create({
            "engagement_id": self.id, "parties": parties, "interested": interested, "capacity": capacity, "nature": nature,
            "terms": terms or "", "amounts_period": amounts_period or 0.0, "continuing": continuing,
            "board_auth_ref": board_auth_ref or False, "notified_at": notified_at or False, "created_by_id": self.env.user.id,
        })

    def _ea_partner_signature(self, on_date=None):
        return signature_blocks(self._ea_firm_name(), self.sudo()._ea_partner_name(), on_date or fields.Date.context_today(self), self._ea_report_fr())

    def generate_rapport_special(self):
        """The special report from the register (arts. 353/440/442); the organs follow the form (F052)."""
        self._ea_legal_guard()
        row = self.sudo()
        form = row.client_id.legal_form
        members = organ_name(form, "members", "fr" if self._ea_report_fr() else "en")
        blocks = [
            _title(self._ea_pick("Special report of the statutory auditor on regulated agreements (to validate)", "Rapport spécial du commissaire aux comptes sur les conventions réglementées")),
            _b(self._ea_pick("%s — Year ended %s", "%s — Exercice clos le %s") % (row.client_id.name, self._ea_prose_date(row.period_end))),
            _p(self._ea_pick("To the ordinary general meeting of the %s%s.", "À l'assemblée générale ordinaire des %s%s.") % (members, self._ea_pick(" of %s", " du %s") % self._ea_prose_date(row.agm_date) if row.agm_date else "")),
            _p(self._ea_pick("As statutory auditor, we present our report on the regulated agreements of which we have been notified, in accordance with the Uniform Act on commercial companies and economic interest groups.", "En notre qualité de commissaire aux comptes, nous vous présentons notre rapport sur les conventions réglementées dont nous avons été avisés, conformément aux dispositions de l'Acte uniforme relatif au droit des sociétés commerciales et du GIE.")),
        ]
        agreements = row.regulated_agreement_ids
        if not agreements:
            blocks += [
                _h(self._ea_pick("No agreement", "Absence de convention")),
                _p(self._ea_pick("We inform you that we were not notified of any regulated agreement entered into or continued during the year.", "Nous vous informons qu'il ne nous a été donné avis d'aucune convention réglementée conclue ou poursuivie au cours de l'exercice.")),
            ]
        else:
            blocks.append(_h(self._ea_pick("Agreements submitted for the approval of the general meeting", "Conventions soumises à l'approbation de l'assemblée")))
            # SA with a board: the board (arts. 438, 440); SA_AG: the general meeting (arts. 502-503);
            # SARL: none, the members approve on this report (arts. 350-354); SAS: the statutes.
            organ = self._ea_pick("the general meeting (arts. 502–503)", "l'assemblée générale (arts. 502–503)") if form == "SA_AG" else self._ea_pick("%s (arts. 438 and 440)", "%s (arts. 438 et 440)") % self._ea_organ(self._ea_pick("the [[lf.board]]", "le [[lf.board]]"))
            for index, agreement in enumerate(agreements, 1):
                blocks += [
                    _b(self._ea_pick("Agreement %d — %s", "Convention %d — %s") % (index, agreement.nature)),
                    _p(self._ea_pick("Parties: %s. Interested person: %s (%s).", "Parties : %s. Personne intéressée : %s (%s).") % (agreement.parties, agreement.interested, (CAPACITY_FR if self._ea_report_fr() else CAPACITY_EN)[agreement.capacity])),
                    _p(self._ea_pick("Essential terms: %s.", "Modalités essentielles : %s.") % (agreement.terms or "—")),
                ]
                if agreement.continuing:
                    blocks.append(_p(self._ea_pick("Continuing agreement — amounts recorded for the year: %s FCFA.", "Convention poursuivie — montants comptabilisés au titre de l'exercice : %s FCFA.") % fmt_amount(agreement.amounts_period, self._ea_report_fr())))
                if agreement.board_auth_ref:
                    blocks.append(_p(self._ea_pick("Prior authorisation of %s: %s.", "Autorisation préalable de %s : %s.") % (organ, agreement.board_auth_ref)))
                elif form in ("SA", "SA_AG"):
                    blocks.append(_p(self._ea_pick("WARNING: agreement not authorised in advance by %s — liable to nullity, curable by a special vote of the general meeting on an explanatory report of the statutory auditor (art. 447).", "ATTENTION : convention non autorisée préalablement par %s — nullité encourue, couvrable par un vote spécial de l'assemblée sur rapport explicatif du commissaire aux comptes (art. 447).") % organ))
                elif form == "SARL":
                    blocks.append(_p(self._ea_pick("Prior authorisation is not required in an SARL: the agreement is submitted to the members' approval on this report, the interested person not taking part in the vote (arts. 350–354).", "Autorisation préalable non requise dans la SARL : la convention est soumise à l'approbation des associés sur le présent rapport, l'intéressé ne prenant pas part au vote (arts. 350–354).")))
                else:
                    blocks.append(_p(self._ea_pick("Prior authorisation is not required for this legal form (SAS: art. 853-14 and the statutes; GIE: the founding contract).", "Autorisation préalable non requise pour cette forme sociale (SAS : art. 853-14 et statuts ; GIE : contrat constitutif).")))
        blocks.append(_p(self._ea_pick("This report is filed at the registered office at least fifteen days before the ordinary general meeting (art. 442).", "Le présent rapport est déposé au siège social quinze jours au moins avant la réunion de l'assemblée générale ordinaire (art. 442).")))
        blocks += self._ea_partner_signature()
        return self._ea_file_under_code("C5.3", self._ea_pick("Special report on agreements — %s", "Rapport spécial conventions — %s") % row.fiscal_year, "report", blocks, "legal:rapport-special")

    # ------------------------------------------------------------------
    # C5.4 article 715 report
    # ------------------------------------------------------------------

    def _ea_year_result(self, engagement):
        """-(classes 6+7+8 closings). No trial-balance row means no figure, not a result of nil
        (UAT run 2 B93, run 3 B26)."""
        balances = engagement._ea_tb_balances() if engagement else []
        if not balances:
            return None
        return -sum(line["value"] for line in balances if re.match(r"^[678]", line["account"] or ""))

    def generate_article_715_report(self):
        self._ea_legal_guard()
        row = self.sudo()
        items = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.id), ("conditional", "=", False)])
        prepared = self.env["ea.audit.signoff"].sudo().search([
            ("engagement_id", "=", self.id), ("kind", "=", "workpaper"), ("role", "=", "preparer"), ("voided_at", "=", False),
        ]).file_item_id
        complete = len(items & prepared)
        not_applicable = len(items.filtered(lambda i: (i.na_reason or "").strip()))
        conclusions = self.env["ea.audit.section.conclusion"].sudo().search([("engagement_id", "=", self.id)], order="code")
        adjustments = self.env["ea.audit.misstatement"].sudo().search(
            [("engagement_id", "=", self.id), ("trivial", "=", False), ("corrected", "=", False)], order="id",
        )
        Finding = self.env["ea.audit.finding"].sudo()
        points = Finding.search([("engagement_id", "=", self.id), ("route", "=", "c1")], order="id")
        irregularities = Finding.search([("engagement_id", "=", self.id), ("route", "=", "b4"), ("status", "=", "open")], order="id")
        prior = self.sudo().search([
            ("client_id", "=", row.client_id.id), ("fiscal_year", "=", row.fiscal_year - 1),
            ("nature", "=", row.nature),
        ], limit=1)
        addressee = self._ea_organ(self._ea_pick("to the [[lf.board]]", "au [[lf.board]]"))
        blocks = [
            _title(self._ea_pick("Report of the statutory auditor %s (art. 715) (to validate)", "Rapport du commissaire aux comptes %s (art. 715)") % addressee),
            _b(self._ea_pick("%s — Year ended %s", "%s — Exercice clos le %s") % (row.client_id.name, self._ea_prose_date(row.period_end))),
            _p(self._ea_pick("%s, when the accounts are approved%s.", "%s, lors de l'arrêté des comptes%s.") % (self._ea_organ(self._ea_pick("To the [[lf.board]]", "Au [[lf.board]]")), self._ea_pick(" of %s", " du %s") % self._ea_prose_date(row.board_date) if row.board_date else "")),
            _h(self._ea_pick("1. Checks and verifications performed and samples taken", "1. Contrôles et vérifications effectués et sondages opérés")),
            _p(self._ea_pick("Tasks of the audit file: %d performed (working paper signed by its preparer) and %d judged not applicable, of %d tasks applicable to the file.", "Tâches du dossier d'audit : %d réalisées (papier de travail signé par son préparateur) et %d jugées non applicables, sur %d tâches applicables au dossier.") % (complete, not_applicable, len(items))),
        ]
        blocks += [_p(self._ea_pick("Section %s: %s", "Section %s : %s") % (c.code, c.conclusion)) for c in conclusions]
        blocks.append(_h(self._ea_pick("2. Balance sheet items and accounting documents requiring changes", "2. Postes du bilan et documents comptables appelant des modifications")))
        if adjustments:
            blocks += [
                _p("%s%s — %s FCFA." % (m.description, self._ea_pick(" (accounts %s)", " (comptes %s)") % m.accounts if m.accounts else "", fmt_amount(m.amount, self._ea_report_fr())))
                for m in adjustments
            ]
        else:
            blocks.append(_p(self._ea_pick("No proposed adjustment remains uncorrected at the date of this report.", "Aucun ajustement proposé demeurant non corrigé à la date du présent rapport.")))
        blocks += [_p(self._ea_pick("Observation on the methods: %s%s", "Observation sur les méthodes : %s%s") % (f.title, " — %s" % f.detail if f.detail else "")) for f in points]
        blocks.append(_h(self._ea_pick("3. Irregularities and inaccuracies discovered", "3. Irrégularités et inexactitudes découvertes")))
        blocks += [_p(f.title) for f in irregularities] or [_p(self._ea_pick("None.", "Néant."))]
        blocks += [
            _h(self._ea_pick("4. Conclusions on the results of the year compared with the previous one", "4. Conclusions sur les résultats de l'exercice comparés au précédent")),
            _p(self._ea_pick("Result for the year %d: %s; year %d: %s.", "Résultat de l'exercice %d : %s ; exercice %d : %s.") % (
                row.fiscal_year, amount_or_nd(self._ea_year_result(row), self._ea_report_fr()), row.fiscal_year - 1, amount_or_nd(self._ea_year_result(prior), self._ea_report_fr()),
            )),
        ]
        blocks += self._ea_partner_signature()
        return self._ea_file_under_code("C5.4", self._ea_pick("Report art. 715 — %s", "Rapport art. 715 — %s") % row.fiscal_year, "report", blocks, "legal:art715")

    # ------------------------------------------------------------------
    # C5.5 alert procedure
    # ------------------------------------------------------------------

    def _ea_current_alerte(self):
        self.ensure_one()
        return self.env["ea.audit.alerte"].sudo().search([("engagement_id", "=", self.id)], limit=1, order="id desc")

    def active_alerte(self):
        """E6.3 and report linkage: an alerte still open means going-concern doubt."""
        self.ensure_one()
        self._ea_require_access()
        return bool(self.env["ea.audit.alerte"].sudo().search_count([
            ("engagement_id", "=", self.id), ("stage", "!=", "closed"), ("discontinued_at", "=", False),
        ]))

    def _ea_stage_addressee(self, stage, variant):
        """F052: the PCA or PDG of an SA with a board, the administrateur général otherwise."""
        if stage == "court_informed":
            return self._ea_pick("To the President of the competent court", "Au Président de la juridiction compétente")
        if stage == "rapport_special":
            return self._ea_pick("To the shareholders", "Aux actionnaires") if variant == "sa" else self._ea_pick("To the members", "Aux associés")
        return self._ea_organ(self._ea_pick("To the [[lf.executive]]", "Au [[lf.executive]]")) if variant == "sa" else self._ea_pick("To the manager", "Au gérant")

    def _ea_file_stage_letter(self, stage, variant, note, event_date):
        """buildStageLetter: dated with the event date the clock runs from, addressed and signed
        (UAT run 2 B94). Not every stage has a letter."""
        template = STAGE_LETTERS.get(stage)
        if not template:
            return self.env["ea.audit.document"].sudo()
        row = self.sudo()
        name = row.client_id.name
        blocks = [
            _title(template["titleFr" if self._ea_report_fr() else "titleEn"]),
            _b(self._ea_pick("%s — Fiscal year %s", "%s — Exercice %s") % (name, row.fiscal_year)),
            _p(self._ea_pick("%s of %s", "%s de %s") % (self._ea_stage_addressee(stage, variant), name)),
            _p(template["bodyFr" if self._ea_report_fr() else "bodyEn"]),
        ]
        if (note or "").strip():
            blocks.append(_p(self._ea_pick("Facts noted / observations: %s", "Faits relevés / observations : %s") % note))
        blocks += self._ea_partner_signature(fields.Date.to_date(event_date))
        title = (
            "Alerte — demande d'explications (%s)" % row.fiscal_year if stage == "request_sent"
            else self._ea_pick("Alert — %s (%s)", "Alerte — %s (%s)") % ((STAGE_DOC_TITLES_FR if self._ea_report_fr() else STAGE_DOC_TITLES_EN).get(stage, stage), row.fiscal_year)
        )
        return self._ea_file_under_code(
            "C5.5", title, "report" if stage == "rapport_special" else "letter", blocks, "alerte:%s" % stage,
        )

    def _ea_alerte_event(self, alerte, stage, note, event_date, document=None):
        return self.env["ea.audit.alerte.event"].sudo().create({
            "engagement_id": self.id, "alerte_id": alerte.id, "stage": stage, "note": note or "", "event_date": event_date,
            "document_id": document.id if document else False, "created_by_id": self.env.user.id,
        })

    def start_alerte(self, note="", event_date=None):
        """The variant derives from the legal form; a letter and a timer at each transition."""
        self._ea_legal_guard()
        state = self._ea_service(
            alerte_engine.start_alerte, self.sudo().client_id.legal_form, self.sudo().active_alerte(),
            event_date, self._ea_today_iso(),
        )
        alerte = self.env["ea.audit.alerte"].sudo().create({
            "engagement_id": self.id, "variant": state["variant"], "stage": state["stage"],
            "stage_deadline": state["stageDeadline"], "created_by_id": self.env.user.id,
        })
        document = self._ea_file_stage_letter("request_sent", state["variant"], note, state["eventDate"])
        self._ea_alerte_event(alerte, "request_sent", note, state["eventDate"], document)
        return alerte

    def get_alerte(self):
        """getAlerte: the latest procedure, with what the screen and the tests read."""
        self.ensure_one()
        self._ea_require_access()
        alerte = self._ea_current_alerte()
        if not alerte:
            return None
        discontinued = self._ea_iso(alerte.discontinued_at)
        return {
            "id": alerte.id, "variant": alerte.variant, "stage": alerte.stage, "stage_deadline": alerte.stage_deadline,
            "discontinued": bool(alerte.discontinued_at),
            "resumable_until": add_months_clamped(discontinued, 6) if discontinued else None,
            "next_stages": alerte_engine.next_stages_of(alerte.variant, alerte.stage, bool(alerte.discontinued_at)),
            "events": alerte.event_ids,
            "last_event_date": alerte_engine.last_event_date([e.event_date.isoformat() for e in alerte.event_ids if e.event_date]),
        }

    def advance_alerte(self, to_stage, note="", satisfactory=False, event_date=None):
        """A satisfactory reply discontinues the procedure, resumable for six months."""
        self._ea_legal_guard()
        self.env.flush_all()
        alerte = self._ea_current_alerte()
        if not alerte:
            raise rule_error(self.env, "not-found")
        self.env.cr.execute("SELECT id FROM ea_audit_alerte WHERE id = %s FOR UPDATE", [alerte.id])
        dates = [e.event_date.isoformat() for e in alerte.event_ids if e.event_date]
        state = self._ea_service(
            alerte_engine.advance_alerte, alerte.variant, alerte.stage, self._ea_iso(alerte.discontinued_at), to_stage,
            alerte_engine.last_event_date(dates), self._ea_today_iso(), satisfactory=satisfactory, event_date=event_date,
        )
        if state["discontinued"]:
            alerte.write({"stage": "reply_recorded", "stage_deadline": False, "discontinued_at": fields.Date.context_today(self)})
            self._ea_alerte_event(alerte, "discontinued", note, state["eventDate"])
            return alerte
        alerte.write({"stage": to_stage, "stage_deadline": state["stageDeadline"]})
        document = self._ea_file_stage_letter(to_stage, alerte.variant, note, state["eventDate"])
        self._ea_alerte_event(alerte, to_stage, note, state["eventDate"], document)
        return alerte

    def resume_alerte(self, note=""):
        self._ea_legal_guard()
        alerte = self._ea_current_alerte()
        if not alerte:
            raise rule_error(self.env, "not-found")
        today = self._ea_today_iso()
        state = self._ea_service(alerte_engine.resume_alerte, self._ea_iso(alerte.discontinued_at), today)
        alerte.write({"stage": state["stage"], "stage_deadline": state["stageDeadline"], "discontinued_at": False})
        self._ea_alerte_event(alerte, "resumed", note, today)
        return alerte

    # ------------------------------------------------------------------
    # C5.6 criminal facts and irregularities
    # ------------------------------------------------------------------

    def _ea_partner_only(self):
        if not can_partner_signoff(self.env.user._ea_firm_role()):
            raise rule_error(self.env, "forbidden")

    def reveal_fait(self, description):
        """Partner-only: revealed to the ministère public (art. 716), with a confidential log."""
        self._ea_legal_guard()
        self._ea_partner_only()
        if not (description or "").strip():
            raise rule_error(self.env, "fields-required")
        row = self.sudo()
        blocks = [
            _title(self._ea_pick("Disclosure of criminal facts to the public prosecutor (art. 716) (to validate)", "Révélation de faits délictueux au ministère public (art. 716)")),
            _b(self._ea_pick("%s — Fiscal year %s", "%s — Exercice %s") % (row.client_id.name, row.fiscal_year)),
            _p(self._ea_pick("Public Prosecutor, in application of article 716 of the Uniform Act on commercial companies and economic interest groups, we bring to your attention the following criminal facts of which we became aware in the course of our engagement, this disclosure engaging no liability on our part:", "Monsieur le Procureur de la République, en application de l'article 716 de l'Acte uniforme relatif au droit des sociétés commerciales et du GIE, nous portons à votre connaissance les faits délictueux suivants dont nous avons eu connaissance dans l'exercice de notre mission, sans que notre responsabilité puisse être engagée par cette révélation :")),
            _p(description),
            _b(self._ea_pick("The statutory auditor.", "Le commissaire aux comptes.")),
        ]
        document = self._ea_file_under_code(
            "C5.6", self._ea_pick("Disclosure of criminal facts — %s", "Révélation faits délictueux — %s") % row.fiscal_year, "letter", blocks, "legal:fait-delictueux", restricted=True,
        )
        self.env["ea.audit.criminal.disclosure"].sudo().create({
            "engagement_id": self.id, "description": description, "document_id": document.id, "created_by_id": self.env.user.id,
        })
        return document

    def list_faits(self):
        self.ensure_one()
        self._ea_require_access()
        self._ea_partner_only()
        return self.env["ea.audit.criminal.disclosure"].sudo().search([("engagement_id", "=", self.id)])

    def generate_irregularities_letter(self, target, points):
        """The report to the general meeting or the board (art. 716)."""
        self._ea_legal_guard()
        if not (points or "").strip():
            raise rule_error(self.env, "fields-required")
        row = self.sudo()
        audience = self._ea_pick("to the next general meeting", "à la plus proche assemblée générale") if target == "ag" else self._ea_organ(self._ea_pick("to the [[lf.board]]", "au [[lf.board]]"))
        blocks = [
            _title(self._ea_pick("Report of irregularities and inaccuracies %s (to validate)", "Signalement d'irrégularités et d'inexactitudes %s") % audience),
            _b(self._ea_pick("%s — Fiscal year %s", "%s — Exercice %s") % (row.client_id.name, row.fiscal_year)),
            _p(self._ea_pick("In accordance with article 716 of the AUSCGIE, we report the irregularities and inaccuracies identified in the course of our engagement:", "Conformément à l'article 716 de l'AUSCGIE, nous signalons les irrégularités et inexactitudes relevées au cours de l'accomplissement de notre mission :")),
            _p(points),
            _b(self._ea_pick("The statutory auditor.", "Le commissaire aux comptes.")),
        ]
        title = "Signalement AG — %s" % row.fiscal_year if target == "ag" else "Signalement conseil — %s" % row.fiscal_year
        return self._ea_file_under_code("C5.6", title, "letter", blocks, "legal:irregularites-%s" % target)

    # ------------------------------------------------------------------
    # C5.7 securities attestation
    # ------------------------------------------------------------------

    def generate_titres_attestation(self, inspection_date=None, securities_count=None, held_by_intermediary=False, intermediary_name=""):
        """UAT run 2 B21: states what the register showed and when; refused until the C5.7 paper
        concludes that it is kept and agrees. F055: the wording follows the holding mode."""
        self._ea_legal_guard()
        try:
            inspected = fields.Date.to_date(inspection_date) if inspection_date else None
        except ValueError:
            inspected = None
        if not inspected:
            raise rule_error(self.env, "titres-inspection-date-required")
        if not isinstance(securities_count, int) or isinstance(securities_count, bool) or securities_count <= 0:
            raise rule_error(self.env, "titres-count-required")
        name = (intermediary_name or "").strip()
        if held_by_intermediary and not name:
            raise rule_error(self.env, "titres-intermediary-required")
        row = self.sudo()
        if not self.env["ea.audit.file.item"].sudo().search_count([("engagement_id", "=", self.id), ("code", "=", "C5.7")]):
            raise rule_error(self.env, "titres-task-missing")
        values = row._ea_paper_values("C5.7")
        if values.get("q_kept") != "yes" or values.get("q_agrees") != "yes":
            raise rule_error(self.env, "titres-work-incomplete")
        capital = row.client_id.share_capital
        capital_line = self._ea_pick(" The share capital shown in the financial statements amounts to %s FCFA.", " Le capital social figurant dans les états financiers s'élève à %s FCFA.") % fmt_amount(capital, self._ea_report_fr()) if capital else ""
        on_date, count = self._ea_prose_date(inspected), fmt_amount(securities_count, self._ea_report_fr())
        blocks = [
            _title(self._ea_pick("Attestation on the registers of registered securities (art. 746-2) (to validate)", "Attestation sur les registres de titres nominatifs (art. 746-2)")),
            _b(self._ea_pick("%s — Year ended %s", "%s — Exercice clos le %s") % (row.client_id.name, self._ea_prose_date(row.period_end))),
        ]
        if held_by_intermediary:
            blocks += [
                _p(self._ea_pick("The company's registered securities are held in account with an approved financial intermediary, %s (art. 746-1). We verified the existence and the keeping of the registers: statement of the securities accounts obtained directly from the intermediary, chronological keeping of the entries, agreement of the total securities and holders with the share capital and with the company's own records.", "Les titres nominatifs de la société sont inscrits en compte auprès d'un intermédiaire financier agréé, %s (art. 746-1). Nous avons procédé à la vérification de l'existence et de la tenue des registres : obtention directe auprès de l'intermédiaire du relevé des comptes-titres, tenue chronologique des inscriptions, concordance du total des titres et des titulaires avec le capital social et avec les enregistrements propres de la société.") % name),
                _p(self._ea_pick("We examined the intermediary's statement as at %s. At that date it shows a total of %s securities held in account.%s", "Nous avons examiné le relevé de l'intermédiaire arrêté au %s. À cette date, il fait apparaître un total de %s titres inscrits en compte.%s") % (on_date, count, capital_line)),
                _p(self._ea_pick("On the basis of our work, we attest that the registers of registered securities, held in account by the approved intermediary, exist and are kept in accordance with the applicable provisions, and that their total agrees with the share capital.", "Sur la base de nos travaux, nous attestons que les registres de titres nominatifs, tenus en compte par l'intermédiaire agréé, existent et sont tenus conformément aux dispositions applicables, et que leur total concorde avec le capital social.")),
                _h(self._ea_pick("Appendix — Management's declaration", "Annexe — Déclaration de la direction")),
                _p(self._ea_pick("Management declares that the statement of securities accounts prepared by %s and presented to the statutory auditor is complete, up to date, and records all the movements of securities during the year.", "La direction déclare que le relevé des comptes-titres établi par %s et présenté au commissaire aux comptes est complet, à jour, et retrace l'intégralité des mouvements de titres intervenus au cours de l'exercice.") % name),
            ]
        else:
            blocks += [
                _p(self._ea_pick("We verified the existence and conformity of the registers of registered securities kept by the company: physical existence of the registers, chronological keeping of the entries, agreement with the movements of securities brought to our knowledge.", "Nous avons procédé à la vérification de l'existence et de la conformité des registres de titres nominatifs tenus par la société : existence matérielle des registres, tenue chronologique des inscriptions, concordance avec les mouvements de titres portés à notre connaissance.")),
                _p(self._ea_pick("We examined the registers on %s. At that date they show a total of %s registered securities.%s", "Nous avons examiné les registres le %s. À cette date, ils font apparaître un total de %s titres inscrits.%s") % (on_date, count, capital_line)),
                _p(self._ea_pick("On the basis of our work, we attest that the registers of registered securities are kept in accordance with the applicable provisions.", "Sur la base de nos travaux, nous attestons que les registres de titres nominatifs sont tenus conformément aux dispositions applicables.")),
                _h(self._ea_pick("Appendix — Management's declaration", "Annexe — Déclaration de la direction")),
                _p(self._ea_pick("Management declares that the registers of registered securities presented to the statutory auditor are complete, up to date, and record all the movements of securities during the year.", "La direction déclare que les registres de titres nominatifs présentés au commissaire aux comptes sont complets, à jour, et retracent l'intégralité des mouvements de titres intervenus au cours de l'exercice.")),
            ]
        blocks.append(_b(self._ea_pick("The company's legal representative", "Le représentant légal de la société")))
        blocks += self._ea_partner_signature()
        return self._ea_file_under_code("C5.7", self._ea_pick("Attestation on registered securities — %s", "Attestation titres nominatifs — %s") % row.fiscal_year, "report", blocks, "legal:titres-attestation")

    # ------------------------------------------------------------------
    # C5.8 equity against half of the share capital
    # ------------------------------------------------------------------

    def _ea_equity_version(self):
        """The valid post-audit trial balance when one exists, else the working pre-audit one."""
        tb = self._ea_tb()
        Version = self.env["ea.audit.tb.version"].sudo()
        if not tb:
            return Version
        final = Version.search(
            [("tb_id", "=", tb.id), ("timing", "=", "post_audit"), ("validation_status", "=", "valid")], order="version_no desc", limit=1,
        )
        return final or self._ea_current_tb_version()

    def _ea_compute_equity(self):
        """computeEquity: accounts 10-15 plus the unposted result of classes 6/7/8. The capital is
        the client record's figure, or by default the closing credit of account 101 (F056)."""
        self.ensure_one()
        version = self._ea_equity_version()
        equity, result, capital101, rows = 0.0, 0.0, None, 0
        for line in version.line_ids:
            rows += 1
            code = line.account_code or ""
            if re.match(r"^1[0-5]", code):
                equity -= line.closing
            if re.match(r"^[678]", code):
                result -= line.closing
            if code.startswith("101"):
                capital101 = (capital101 or 0.0) - line.closing
        has_tb = rows > 0
        from_client = self.client_id.share_capital or None
        capital = from_client or (capital101 if has_tb and capital101 is not None and capital101 > 0 else None)
        half = None if capital is None else capital / 2
        total = equity + result
        return {
            "equity": total, "share_capital": capital, "half_capital": half,
            "breach": bool(has_tb and half is not None and total < half), "has_tb": has_tb,
            "source": None if not has_tb else ("post_audit" if version.timing == "post_audit" else "pre_audit"),
            "share_capital_source": "client" if from_client else ("tb_101" if capital is not None else None),
        }

    def _ea_egm_row(self):
        return self.env["ea.audit.legal.deadline"].sudo().search(
            [("engagement_id", "=", self.id), ("key", "=", "egm_equity")], limit=1,
        )

    def _ea_equity_conclusion(self, figures):
        row = self._ea_egm_row()
        return equity_conclusion_of(figures["breach"], figures["has_tb"], figures["half_capital"], row.done if row else None)

    def equity_status(self):
        self.ensure_one()
        self._ea_require_access()
        return self.sudo()._ea_compute_equity()

    def equity_check(self):
        """A breach raises the statutory meeting's deadline and notifies the partners; a check that
        no longer breaches clears the open row (UAT B100)."""
        self._ea_legal_guard()
        row = self.sudo()
        figures = row._ea_compute_equity()
        if figures["breach"]:
            basis_date = row.agm_date.isoformat() if row.agm_date else add_months_clamped(row.period_end.isoformat(), 6)
            self._ea_upsert_deadline("egm_equity", add_months_clamped(basis_date, 4), self._ea_pick(EGM_EQUITY_BASIS, EGM_EQUITY_BASIS_FR))
            row._ea_notify(
                row._ea_partner_users(), "equity-breach", self._ea_pick("Equity below half of the share capital", "Capitaux propres < ½ capital social"),
                self._ea_pick("Equity %s FCFA against half the capital %s FCFA — statutory extraordinary general meeting procedure triggered (C5.8).", "Capitaux propres %s FCFA vs ½ capital %s FCFA — procédure statutaire d'AGE déclenchée (C5.8).") % (fmt_amount(figures["equity"], self._ea_report_fr()), fmt_amount(figures["half_capital"], self._ea_report_fr())),
            )
        elif figures["has_tb"] and figures["half_capital"] is not None:
            egm = row._ea_egm_row()
            if egm and not egm.done:
                egm.unlink()
        return figures

    def set_share_capital(self, amount):
        self._ea_legal_guard()
        if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount <= 0:
            raise rule_error(self.env, "invalid-amount")
        self.sudo().client_id.share_capital = amount
        return True

    # ------------------------------------------------------------------
    # C5.9 joint auditor file
    # ------------------------------------------------------------------

    def record_joint_auditor(self, key, text, confirmed=False, expected_version=None):
        """cocacAction: work split, cross-review, disagreement. A divergence reaches the report (art. 719)."""
        self.ensure_one()
        if key not in _JOINT_KEYS:
            raise rule_error(self.env, "invalid-key")
        return self.record_completion("f8_%s" % key, {"text": text or "", "confirmed": bool(confirmed)}, expected_version)

    # ------------------------------------------------------------------
    # C5.10 article 525 certification
    # ------------------------------------------------------------------

    def generate_art525_certification(self):
        """The source holds C5.10 as a paper; the document follows the form its header records from
        two signed attestations. Reads the paper: headcount, number of persons, amount."""
        self._ea_legal_guard()
        row = self.sudo()
        if not self.env["ea.audit.file.item"].sudo().search_count([("engagement_id", "=", self.id), ("code", "=", "C5.10")]):
            raise rule_error(self.env, "art525-task-missing")
        values = row._ea_paper_values("C5.10")
        persons = (values.get("persons") or "").strip() or persons_from_headcount(values.get("headcount"))
        amount = (values.get("amount") or "").strip()
        if persons not in ("five", "ten") or not amount:
            raise rule_error(self.env, "art525-work-incomplete")
        number = self._ea_pick("ten", "dix") if persons == "ten" else self._ea_pick("five", "cinq")
        members = organ_name(row.client_id.legal_form, "members", "fr" if self._ea_report_fr() else "en")
        blocks = [
            _title(self._ea_pick("Statutory auditor's attestation on the total remuneration paid to the highest-paid persons (art. 525) (to validate)", "Attestation du commissaire aux comptes sur le montant global des rémunérations versées aux personnes les mieux rémunérées (art. 525)")),
            _b(self._ea_pick("%s — Year ended %s", "%s — Exercice clos le %s") % (row.client_id.name, self._ea_prose_date(row.period_end))),
            _p(self._ea_pick("To the %s,", "Aux %s,") % members),
            _p(self._ea_pick("As statutory auditor, and in application of article 525 of the Uniform Act on commercial companies and economic interest groups, we have prepared this attestation on the total remuneration paid to the %s highest-paid persons for the year ended %s, shown in the attached document.", "En notre qualité de commissaire aux comptes, et en application de l'article 525 de l'Acte uniforme relatif au droit des sociétés commerciales et du GIE, nous avons établi la présente attestation sur le montant global des rémunérations versées aux %s personnes les mieux rémunérées au titre de l'exercice clos le %s, figurant dans le document joint.") % (number, self._ea_prose_date(row.period_end))),
            _p(self._ea_pick("This information was prepared under management's responsibility. Our responsibility is to attest it. The audit of the financial statements as a whole does not aim to express an opinion on these amounts taken in isolation.", "Cette information a été établie sous la responsabilité de la direction. Il nous appartient de l'attester. L'audit des états financiers pris dans leur ensemble n'a pas pour objet d'exprimer une opinion sur ces montants pris isolément.")),
            _p(self._ea_pick("Our procedures, performed under the professional standards of Regulation no. 01/2017/CM/OHADA, are neither an audit nor a limited review. They consisted of agreeing the total to the accounting records from which the financial statements are drawn.", "Nos diligences, réalisées selon les normes professionnelles du Règlement n°01/2017/CM/OHADA, ne constituent ni un audit ni un examen limité. Elles ont consisté à rapprocher le montant global de la comptabilité dont sont issus les états financiers.")),
            _p(self._ea_pick("On the basis of this work, we attest that the total remuneration paid to the %s highest-paid persons, being %s, is accurate and agrees with the accounting records.", "Sur la base de ces travaux, nous attestons que le montant global des rémunérations versées aux %s personnes les mieux rémunérées, soit %s, est exact et concorde avec la comptabilité.") % (number, amount)),
            _p(self._ea_pick("This attestation stands as the certification required by article 525. It is prepared for this sole purpose and may not be used for any other.", "La présente attestation tient lieu de la certification exigée par l'article 525. Elle est établie à cette seule fin et ne peut être utilisée à aucune autre.")),
        ]
        blocks += self._ea_partner_signature()
        return self._ea_file_under_code("C5.10", self._ea_pick("Attestation art. 525 — %s", "Attestation art. 525 — %s") % row.fiscal_year, "report", blocks, "legal:art525")

    # ------------------------------------------------------------------
    # Manifest and screens
    # ------------------------------------------------------------------

    def _ea_manifest_extra(self):
        extra = super()._ea_manifest_extra()
        extra["statutoryDeadlines"] = [
            {"key": d.key, "dueDate": d.due_date, "basis": d.basis, "done": d.done} for d in self.legal_deadline_ids
        ]
        extra["conventions"] = [
            {"parties": c.parties, "interested": c.interested, "capacity": c.capacity, "nature": c.nature, "continuing": c.continuing, "boardAuthRef": c.board_auth_ref or None}
            for c in self.regulated_agreement_ids
        ]
        extra["alertes"] = [
            {"variant": a.variant, "stage": a.stage, "deadline": a.stage_deadline, "discontinuedAt": a.discontinued_at,
             "events": [{"stage": e.stage, "date": e.event_date} for e in a.event_ids]}
            for a in self.alerte_ids
        ]
        return extra

    def action_tool_legal(self):
        """The hub's tile."""
        return self.action_open_legal()

    def action_open_legal(self):
        self.ensure_one()
        return self._ea_board("ea_audit_legal.view_engagement_legal_form", self.env._("Legal register"))

    def action_open_legal_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "ea.audit.legal.wizard", "view_mode": "form", "target": "new",
            "name": self.env._("OHADA legal register"),
            "context": {"default_engagement_id": self.id, "default_mode": self.env.context.get("legal_mode")},
        }

    def action_generate_deadlines(self):
        self.generate_deadlines()
        return True

    def action_generate_rapport_special(self):
        return self.generate_rapport_special().action_download()

    def action_generate_article_715(self):
        return self.generate_article_715_report().action_download()

    def action_generate_art525(self):
        return self.generate_art525_certification().action_download()

    def action_equity_check(self):
        self.equity_check()
        return True

    def action_view_faits(self):
        self.ensure_one()
        self._ea_partner_only()
        return self._ea_list(
            "ea.audit.criminal.disclosure", self.env._("Criminal facts"),
            [("ea_audit_legal.view_criminal_disclosure_list", "list")],
        )
