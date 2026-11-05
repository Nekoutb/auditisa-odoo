"""The demonstration missions, loaded by demo_data.xml only when demo data is on.

Everything goes through the real methods, as the real user: engagements are created, teams seated,
papers answered with save_answers, signed with action_sign, the trial balance imported, materiality
approved, SCOTs and controls recorded, S5.5 designed (which is what scopes the E4 tasks), phases
advanced by their gates, the report issued and the file archived. Nothing here writes a phase, a
state or a task's scope by hand.

- Négoce 2024 went all the way: it is really archived, through issue_report and archive_engagement.
- Négoce 2025 is mid-execution, with the mock-up's lists of late, waiting and open tasks.
- Forêt 2025 is another partner's file, on invitation.
- Tropical Agro-Industries 2025 is the file a person walks, from the partner's signature on P1.1 to
  the archive. So that a walk is one sitting and not a real audit's hundred papers, the papers the
  walk does not need are marked not applicable, with that reason, by the manager (WALK_PAPERS below
  are the ones left). The S-section, E1 and C5.3 papers a very simple file does not start with are
  put on the file with _ea_ensure_task, which is the method a trigger uses.
"""
import logging
import os
from datetime import date, timedelta

import os

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.signoff_rules import team_rank
from odoo.addons.ea_audit_papers.services import required_keys
from odoo.addons.ea_audit_papers.services.planning_ras import SECTION_A, SECTION_B
from odoo.addons.ea_audit_tools.services.lead_classes import INDEX_SECTION
from odoo.addons.ea_audit_tools.services.scot_forms import WALKTHROUGH_FIELDS

_logger = logging.getLogger(__name__)

_E4_SHOWN = ("E4.1", "E4.2", "E4.3", "E4.4", "E4.5", "E4.6", "E4.7", "E4.8", "E4.9", "E4.10", "E4.20")
_NOT_DONE_STRATEGY = ("S2.5", "S4.4", "S5.4")
# What a very simple file does not start with and the walk goes through.
_WALK_ENSURED = ("S1.1", "S1.2", "S1.3", "S2.1", "S2.2", "S2.3", "S2.5", "S5.5", "E1.2", "C5.3")
# The papers of the walk, past acceptance. Every other one is marked not applicable on that file.
WALK_PAPERS = (
    "P6.1", "P6.2", "S3.1", "S1.1", "S1.2", "S1.3", "S2.1", "S2.2", "S2.3", "S2.5", "S5.5", "P7.2",
    "E1.2", "E3.1", "E4.1", "E4.20", "E6.10",
    "C1.1", "C1.2", "C2.1", "C3.1", "C4.1", "C4.3", "C5.3", "C5.11", "C6.1", "C6.2",
)
_WALK_NA_REASON = ("Demonstration file: paper not kept for the guided walk.", "Dossier de démonstration : papier non retenu pour la visite guidée.")
_SELECT_ANSWERS = {
    "engagement_type": "recurring",
    "auditor_change": "no",
    "rating": "moderate",
    "itgc_state": "support",
}
_DONE_TEXT = ("Done, see the working paper.", "Effectué, voir la feuille de travail.")

_ACCOUNTS = {
    "101000": ("Share capital", "Capital social"),
    "121000": ("Retained earnings", "Report à nouveau"),
    "162000": ("Borrowings", "Emprunts"),
    "231000": ("Buildings", "Bâtiments"),
    "241000": ("Equipment and tools", "Matériel et outillage"),
    "284000": ("Accumulated depreciation of equipment", "Amortissements du matériel"),
    "311000": ("Goods for resale", "Marchandises"),
    "401000": ("Trade payables", "Fournisseurs"),
    "411000": ("Trade receivables", "Clients"),
    "431000": ("Social security", "Sécurité sociale"),
    "441000": ("State, income tax", "État, impôt sur les bénéfices"),
    "521000": ("Banks", "Banques"),
    "571000": ("Cash on hand", "Caisse"),
    "601000": ("Purchases of goods", "Achats de marchandises"),
    "622000": ("Rentals", "Locations"),
    "641000": ("Taxes and duties", "Impôts et taxes"),
    "661000": ("Salaries", "Rémunérations"),
    "681000": ("Depreciation expense", "Dotations aux amortissements"),
    "701000": ("Sales of goods", "Ventes de marchandises"),
}
_CLOSING_2024 = {
    "101000": -50000000, "121000": -8000000, "162000": -20000000, "231000": 60000000, "241000": 25000000,
    "284000": -15000000, "311000": 18000000, "401000": -22000000, "411000": 30000000, "431000": -2000000,
    "441000": -3000000, "571000": 1000000, "601000": 90000000, "622000": 6000000, "641000": 2000000,
    "661000": 25000000, "681000": 5000000, "701000": -150000000,
}
_CLOSING_2025 = {
    "101000": -50000000, "121000": -30000000, "162000": -16000000, "231000": 60000000, "241000": 32000000,
    "284000": -21000000, "311000": 21000000, "401000": -26000000, "411000": 41000000, "431000": -2500000,
    "441000": -3500000, "571000": 1500000, "601000": 104000000, "622000": 6500000, "641000": 2500000,
    "661000": 28000000, "681000": 6000000, "701000": -175000000,
}


def _d(english, french):
    """Demonstration content, in the firm's language: what its people would have typed."""
    return french if _Demo.french else english


def _ledger_csv(year):
    """A small general ledger: twelve months of sales, purchases and cash, with what the journal-entry
    selection looks for: round amounts, a Saturday, a closing-day entry, one self-approved."""
    # A client's file: its column names are read, not shown.
    lines = ["Compte;Intitulé;N° écriture;Libellé;Date;Débit;Crédit;Référence;Journal;Préparé;Approuvé"]  # i18n: input

    def entry(number, label, day, debit_account, credit_account, amount, journal, preparer="Awa", approver="Ben"):
        for account, debit, credit in ((debit_account, amount, ""), (credit_account, "", amount)):
            lines.append(";".join(str(cell) for cell in (
                account, _d(*_ACCOUNTS[account]), number, label, day, debit, credit, "P-%s" % number, journal, preparer, approver,
            )))

    for month in range(1, 13):
        stamp = "%02d/%02d/%d" % (15, month, year)
        entry("VE%03d" % month, _d("Sales for month %d", "Ventes du mois %d") % month, stamp, "411000", "701000", 14000000 + month * 137000, "VE")
        entry("AC%03d" % month, _d("Purchases for month %d", "Achats du mois %d") % month, stamp, "601000", "401000", 8000000 + month * 91000, "AC")
        entry("BQ%03d" % month, _d("Customer receipts %d", "Encaissement clients %d") % month, "20/%02d/%d" % (month, year), "521000", "411000", 12500000 + month * 73000, "BQ")
        entry("PA%03d" % month, _d("Salaries for month %d", "Salaires du mois %d") % month, "28/%02d/%d" % (month, year), "661000", "521000", 2300000 + month * 11000, "OD")
    entry("OD900", _d("Manual closing entry", "Écriture manuelle de clôture"), "31/12/%d" % year, "622000", "401000", 5000000, "OD", "Dan", "Dan")
    entry("OD901", _d("Adjustment on a Saturday", "Régularisation un samedi"), "01/02/%d" % year, "641000", "521000", 1000000, "OD", "Dan", "Ben")
    return ("\n".join(lines) + "\n").encode("utf-8")


_LEDGER_MAPPING = {
    "account": "Compte", "accountName": "Intitulé", "jeNumber": "N° écriture", "jeDescription": "Libellé",  # i18n: input
    "journalDate": "Date", "debit": "Débit", "credit": "Crédit", "reference": "Référence",  # i18n: input
    "journalCode": "Journal", "preparedBy": "Préparé", "approvedBy": "Approuvé",  # i18n: input
}


def _balanced(closing):
    """The bank takes what the other accounts leave, so every version balances."""
    out = dict(closing)
    out["521000"] = -sum(closing.values())
    return out


def _carried(closing):
    """Opening balances: the balance sheet carried, the year's result in retained earnings."""
    opening = {code: amount for code, amount in closing.items() if code[0] not in "678"}
    opening["121000"] = opening.get("121000", 0) + sum(a for code, a in closing.items() if code[0] in "678")
    return opening


def _tb_csv(opening, closing):
    lines = ["Compte;Libellé;Solde ouverture débit;Solde ouverture crédit;Mouvement débit;Mouvement crédit"]  # i18n: input
    for code in sorted(_ACCOUNTS):
        before = opening.get(code, 0)
        movement = closing.get(code, 0) - before
        lines.append(";".join(str(cell) for cell in (
            code, _ACCOUNTS[code], max(before, 0), max(-before, 0), max(movement, 0), max(-movement, 0),
        )))
    return ("\n".join(lines) + "\n").encode("utf-8")


class _Demo:
    french = False

    def __init__(self, env):
        self.env = env
        self.today = fields.Date.context_today(env["ea.audit.ui"])
        self.mbarga = env.ref("ea_audit_ui.demo_user_mbarga")
        self.essomba = env.ref("ea_audit_ui.demo_user_essomba")
        self.ndongo = env.ref("ea_audit_ui.demo_user_ndongo")
        self.tchoua = env.ref("ea_audit_ui.demo_user_tchoua")
        self.fotso = env.ref("ea_audit_ui.demo_user_fotso")
        self.team = (
            (self.tchoua, "staff"), (self.ndongo, "senior"), (self.essomba, "manager"), (self.mbarga, "partner"),
        )
        self.Policy = env["ea.audit.signoff.policy"]

    def mission(self, client_xmlid, year, partner, complexity):
        client = self.env.ref(client_xmlid)
        engagement = self.env["ea.audit.engagement"].with_user(partner).create({
            "client_id": client.id,
            "fiscal_year": year,
            "period_end": date(year, 12, 31),
            "duration_months": 12,
            "nature": "statutory_audit",
            "complexity": complexity,
            "engagement_partner_id": partner.id,
        }).sudo()
        self.seat_tester(engagement)
        return engagement

    def seat_tester(self, engagement):
        """EA_DEMO_TESTER_LOGIN, on a staging build only: whoever tests there is seated from the start,
        because nobody can join an archived file afterwards. The account has no password here."""
        login = os.environ.get("EA_DEMO_TESTER_LOGIN")
        if not login:
            return
        Users = self.env["res.users"].sudo().with_context(no_reset_password=True, mail_create_nosubscribe=True)
        user = Users.search([("login", "=", login)], limit=1) or Users.create({
            "name": "Testeur", "login": login, "email": login, "lang": "fr_FR", "tz": "Africa/Douala",
            "group_ids": [(4, self.env.ref("base.group_user").id), (4, self.env.ref("ea_audit_core.group_firm_admin").id)],
        })
        self.env["ea.audit.team.member"].sudo().create({
            "engagement_id": engagement.id, "user_id": user.id, "team_role": "director", "state": "accepted",
            "responded_at": fields.Datetime.now(),
        })

    def seat_team(self, engagement):
        for user, role in self.team:
            if role != "partner":
                engagement.with_user(self.mbarga).assign_team_member(user.id, role)

    def items(self, engagement):
        return {item.code: item for item in engagement.file_item_ids}

    def people_for(self, code):
        """The lowest ranks the task's rule accepts, the preparer never reviewing."""
        rule = self.Policy._ea_effective_rule(code)
        preparer = next(u for u, role in self.team if team_rank(role) >= team_rank(rule["min_preparer"]))
        reviewer = next(
            u for u, role in self.team if team_rank(role) >= team_rank(rule["min_reviewer"]) and u != preparer
        )
        return preparer, reviewer, rule

    def assign(self, item, preparer=None, approver=None, assignee=None):
        as_manager = item.with_user(self.essomba)
        if preparer:
            as_manager.assign_tasks(preparer.id, "preparer")
        if approver:
            as_manager.assign_tasks(approver.id, "approver")
        if assignee:
            as_manager.assign_tasks(assignee.id, "assignee")

    def assign_by_rule(self, item):
        preparer, reviewer, _rule = self.people_for(item.code)
        self.assign(item, preparer, reviewer)
        return preparer, reviewer

    # ------------------------------------------------------------------
    # The paper, as a preparer fills it
    # ------------------------------------------------------------------

    def answers(self, item):
        definition = item._ea_paper()._ea_resolved()
        options = {}
        fields_of = list(definition.get("fields") or [])
        for section in definition.get("sections") or []:
            if section["kind"] == "fields":
                fields_of += section["fields"]
        for field in fields_of:
            if field["kind"] == "select":
                options[field["key"]] = _SELECT_ANSWERS.get(field["key"]) or field["options"][0]["value"]
        out = {}
        for key in required_keys(definition):
            if key in options:
                out[key] = options[key]
            elif item.code == "P1.5" and key.startswith("q_"):
                # a "yes" on any criterion would require a quality reviewer on the file
                out[key] = "no"
                out["%s_x" % key] = _d("Criterion not met for this entity.", "Critère non rempli pour cette entité.")
            elif key.startswith(("q_", "c_")):
                out[key] = "yes"
            else:
                out[key] = _d(*_DONE_TEXT)
        return out

    def fill(self, item, user):
        item._ea_paper().with_user(user).save_answers(self.answers(item))

    def touch(self, item, user=None):
        """Started, not finished: a first remark on the paper."""
        item._ea_paper().with_user(user or self.ndongo).save_answers({"key_findings": "Travaux en cours."})

    def complete(self, item):
        """Prepared and reviewed, or approved by the partner where the rule says so."""
        preparer, reviewer = self.assign_by_rule(item)
        rule = self.Policy._ea_effective_rule(item.code)
        role = "partner" if rule["partner_required"] else "reviewer"
        signer = self.mbarga if rule["partner_required"] else reviewer
        self.fill(item, preparer)
        item.with_user(preparer).action_sign("preparer")
        item.with_user(signer).action_sign(role)

    def prepared(self, item, preparer, approver):
        self.assign(item, preparer, approver)
        self.fill(item, preparer)
        item.with_user(preparer).action_sign("preparer")

    def due(self, items, days):
        if items:
            self.env["ea.audit.file.item"].browse([item.id for item in items]).with_user(self.essomba).write({
                "due_date": self.today + timedelta(days=days),
            })

    # ------------------------------------------------------------------
    # The tools, through their own methods
    # ------------------------------------------------------------------

    def import_tb(self, engagement, opening, closing):
        name = "balance-%s.csv" % engagement.fiscal_year
        engagement.with_user(self.ndongo).import_trial_balance(name, _tb_csv(opening, _balanced(closing)))

    def approve_materiality(self, engagement):
        amount = engagement._ea_tb_bases()["revenue"]
        version = engagement.with_user(self.ndongo).create_materiality_version(
            "revenue", amount, 1, _d("Revenue is stable and the main indicator the shareholders follow.", "Le chiffre d'affaires est stable et le principal indicateur suivi par les associés."),
        )
        version.with_user(self.mbarga).action_approve()

    def respond_to_risks(self, engagement):
        """Every significant risk has a planned response, as the planning gate requires."""
        as_senior = engagement.with_user(self.ndongo)
        receivables = next(code for code, paper in INDEX_SECTION.items() if paper == "E4.1")
        as_senior.add_risk(
            _d("Insufficient allowance on old receivables", "Dépréciation insuffisante des créances anciennes"), category="error", likelihood="medium", magnitude="high",
            significant=True, index=receivables, assertions=["V"],
        )
        as_senior.add_risk(_d("Dependence on a single supplier", "Dépendance à un fournisseur unique"), category="business", likelihood="medium", magnitude="medium")
        for risk in self.env["ea.audit.risk"].sudo().search([
            ("engagement_id", "=", engagement.id), ("significant", "=", True), ("program_step_ids", "=", False),
        ]):
            items = self.items(engagement)
            section = risk.section_link_ids.file_item_id[:1] or items.get("E4.1") or items["E1.1"]
            step = as_senior.add_program_step(section, _d("Response to the risk: %s", "Réponse au risque : %s") % risk.description[:80])
            risk.with_user(self.ndongo).link_step(step)

    def record_scots(self, engagement):
        """SCOT Studio as a senior fills it: a controls SCOT with a selected, designed control, a
        substantive SCOT, the walkthroughs answered, each IT application given its strategy."""
        as_senior = engagement.with_user(self.ndongo)
        sales = as_senior.create_scot(
            _d("Sales and trade receivables", "Ventes et créances clients"), "routine", "controls", _d("Invoicing software", "Logiciel de facturation"),
            _d("From order to cash receipt.", "De la commande à l'encaissement."),
        )
        sales.link_index("E", ["E", "A", "C"])
        missed = sales.add_wcgw(_d("A sale is neither invoiced nor recorded.", "Une vente n'est pas facturée ni comptabilisée."), ["C"])
        control = sales.add_control(
            "Rapprochement mensuel des bons de livraison et des factures", "Directeur financier", "manual", "mensuel", "detect", wcgws=missed,
        )
        control.update_control({
            "selected_for_testing": True, "test_design": "Reprendre le rapprochement du mois et le visa du directeur financier.",
            "design_eval": "effective", "implemented": "yes",
        })
        purchases = as_senior.create_scot(_d("Purchases and suppliers", "Achats et fournisseurs"), "routine", "substantive", _d("Accounting software", "Logiciel comptable"), _d("From order to payment.", "De la commande au règlement."))
        purchases.link_index("N", ["C", "A"])
        purchases.add_wcgw(_d("A supplier invoice is recorded twice.", "Une facture fournisseur est enregistrée deux fois."), ["E"])
        answers = {
            field["key"]: "yes" if field.get("kind") == "yn" else _d("Described in the meeting with the finance director.", "Décrit lors de l'entretien avec le directeur financier.")
            for field in WALKTHROUGH_FIELDS
        }
        (sales | purchases).write(answers)
        engagement._ea_sync_it_applications()
        for application in self.env["ea.audit.it.application"].sudo().search([("engagement_id", "=", engagement.id), ("removed", "=", False)]):
            as_senior.save_it_application(application.key, {"strategy": "substantive_only"})
        return control

    def design(self, engagement, codes):
        """S5.5: a procedure designed on an account of each task brings that task on the lists."""
        as_senior = engagement.with_user(self.ndongo)
        for code in codes:
            index = next((index for index, task in INDEX_SECTION.items() if task == code), None)
            if index:
                as_senior.add_dsp_osp(index, _d("Test of details designed on account %s.", "Procédure de détail conçue sur le compte %s.") % index, ["E"])

    def conclude(self, engagement):
        """Execution to the archive, by the methods a file goes through. C6.x wait for the report."""
        as_senior = engagement.with_user(self.ndongo)
        as_partner = engagement.with_user(self.mbarga)
        steps = self.env["ea.audit.program.step"].sudo().search([("engagement_id", "=", engagement.id), ("status", "=", "open")])
        for step in steps:
            step.with_user(self.ndongo).complete(_d("Procedure performed, no misstatement.", "Diligence réalisée, sans anomalie."))
        for risk in self.env["ea.audit.risk"].sudo().search([("engagement_id", "=", engagement.id), ("rebutted", "=", False)]):
            risk.with_user(self.ndongo).write({"status": "concluded"})
        worked = steps.file_item_id
        for item in worked:
            item.with_user(self.ndongo).save_section_conclusion("Objectifs atteints.", objectives_achieved=True)
            item.with_user(self.essomba).review_section_conclusion()
        as_senior.save_sad_conclusion(_d("No uncorrected material misstatement.", "Aucune anomalie significative non corrigée."))
        as_senior.run_final_analytics()
        as_senior.run_fs_tieout()
        as_senior.record_disclosure_checklist(True, _d("Notes 1 to 36 reviewed.", "Notes 1 à 36 revues."))
        report_date = date(engagement.fiscal_year + 1, 3, 31)
        as_senior.record_subsequent_events(report_date)
        as_partner.generate_letter("rep_affirmation", "fr")
        as_partner.generate_letter("rep_complementary", "fr")
        as_partner.record_completion("partner_conclusion", {"conclusion": _d("The work supports an unmodified opinion.", "Les travaux soutiennent une opinion sans réserve.")})
        scoped_out = engagement._ea_e4_out_of_scope()
        open_items = engagement.file_item_ids.filtered(
            lambda i: not i.conditional and i.state != "signed" and not i.not_applicable and i not in scoped_out
        )
        for item in open_items.filtered(lambda i: i.code not in ("C6.1", "C6.2")).sorted(lambda i: i.code == "C4.1"):
            self.complete(item)
        as_partner.issue_report_from_form(report_date=report_date)
        for item in open_items.filtered(lambda i: i.code in ("C6.1", "C6.2")):
            self.complete(item)
        as_partner.archive_engagement()

    def assess_cra(self, engagement):
        engagement._ea_sync_cra()
        cells = self.env["ea.audit.cra.assessment"].sudo().search([("engagement_id", "=", engagement.id)], limit=8)
        for cell in cells:
            cell.with_user(self.ndongo)._ea_save_cell({"ir": "lower", "cr": "not_rely", "cr_basis": "Approche substantive."})

    def approve_plan(self, engagement):
        """The P7.2 summary, its three tiers, then the sign-off on the row."""
        as_senior = engagement.with_user(self.ndongo)
        as_partner = engagement.with_user(self.mbarga)
        for item in SECTION_A:
            as_senior.ea_ras_save(item["key"], "yes")
        for item in SECTION_B:
            as_partner.ea_ras_save(item["key"], "yes")
        as_senior.ea_ras_sign("fieldwork")
        engagement.with_user(self.essomba).ea_ras_sign("manager")
        as_partner.ea_ras_sign("partner")
        p72 = self.items(engagement).get("P7.2")
        if p72:
            preparer, _reviewer = self.assign_by_rule(p72)
            p72.with_user(preparer).action_sign("preparer")
            p72.with_user(self.mbarga).action_sign("partner")

    def walk_acceptance(self, engagement):
        for item in self.items(engagement).values():
            if item.task_phase == "acceptance" and not item.conditional:
                self.complete(item)
        engagement.with_user(self.mbarga).advance_to_planning()

    def walk_planning(self, engagement, opening, closing, keep_open=(), designed=()):
        self.import_tb(engagement, opening, closing)
        self.approve_materiality(engagement)
        self.respond_to_risks(engagement)
        self.assess_cra(engagement)
        if "S1.1" in self.items(engagement):
            self.record_scots(engagement)
        self.design(engagement, designed)
        for code, item in self.items(engagement).items():
            if item.conditional or item.task_phase != "planning" or code == "P7.2":
                continue
            if code in keep_open:
                self.assign_by_rule(item)
                self.touch(item)
            else:
                self.complete(item)
        self.approve_plan(engagement)
        engagement.with_user(self.mbarga).close_planning()

    # ------------------------------------------------------------------

    def archived_2024(self):
        engagement = self.mission("ea_audit_ui.demo_client_negoce", 2024, self.mbarga, "very_simple")
        self.seat_team(engagement)
        self.walk_acceptance(engagement)
        opening = _carried(_balanced({**_CLOSING_2024, "701000": -140000000}))
        self.walk_planning(engagement, opening, _CLOSING_2024, designed=("E4.1",))
        self.conclude(engagement)
        return engagement

    def negoce_2025(self):
        engagement = self.mission("ea_audit_ui.demo_client_negoce", 2025, self.mbarga, "complex")
        self.seat_team(engagement)
        self.walk_acceptance(engagement)
        self.walk_planning(
            engagement, _carried(_balanced(_CLOSING_2024)), _CLOSING_2025, keep_open=_NOT_DONE_STRATEGY, designed=_E4_SHOWN,
        )
        active = {code: item for code, item in self.items(engagement).items() if not item.conditional}

        # execution, as the mock-up's lists
        for code in ("E1.1", "E1.2", "E2.1", "E3.1", "E6.7", "E6.2", "E6.4", "E4.2", "E4.5", "E4.6", "E4.7"):
            self.complete(active[code])
        self.prepared(active["E4.1"], self.tchoua, self.ndongo)
        self.assign(active["E4.3"], self.tchoua, self.ndongo)
        self.assign(active["E4.4"], approver=self.ndongo)
        self.assign(active["E4.20"], self.ndongo, self.essomba)
        for code in ("E4.8", "E4.9", "E4.10", "E6.5", "E6.8", "E6.6"):
            self.assign(active[code], self.tchoua, self.ndongo)
        self.assign(active["E6.10"], self.ndongo, self.essomba)
        for code in ("E4.3", "E4.4", "E4.20", "E6.6"):
            self.touch(active[code])

        # waiting for the partner
        self.prepared(active["E6.3"], self.ndongo, self.mbarga)
        self.prepared(active["E6.1"], self.tchoua, self.mbarga)
        self.prepared(active["E6.9"], self.tchoua, self.mbarga)
        self.prepared(active["C5.3"], self.essomba, self.mbarga)

        # conclusion: staffed in part, the rest in the "no preparer" band
        for code in ("C1.1", "C1.2", "C1.3", "C2.1", "C2.2", "C3.1", "C4.1"):
            self.assign_by_rule(active[code])
        self.assign(active["C5.11"], assignee=self.mbarga)

        self.findings(engagement, active)
        self.review_notes(active)

        # deadlines: two late, the rest ahead
        open_items = [i for i in active.values() if i.state != "signed"]
        self.due([i for i in open_items if i.section == "D"], 10)
        self.due([i for i in open_items if i.section == "E"], 24)
        self.due([i for i in open_items if i.section not in ("D", "E")], 60)
        self.due([active["E4.1"]], -12)
        self.due([active["E6.3"]], -5)
        return engagement

    def findings(self, engagement, active):
        as_senior = engagement.with_user(self.ndongo)
        as_senior.route_finding(
            "c1", _d("No monthly bank reconciliation", "Absence de rapprochement bancaire mensuel"), severity="significant_deficiency",
            detail=_d("The 2025 reconciliations were only done at year end.", "Les rapprochements de 2025 n'ont été faits qu'en fin d'exercice."),
            recommendation=_d("Reconcile each bank account every month, reviewed by the finance director.", "Rapprocher chaque compte bancaire chaque mois, avec revue par le directeur financier."),
            file_item=active["E4.3"],
        )
        as_senior.route_finding(
            "b4", _d("Manual adjustment on the receivable accounts", "Reprise manuelle sur les comptes clients"), detail=_d("Manual entries without support in December.", "Saisies manuelles sans pièce en décembre."),
            file_item=active["E4.1"],
        )
        as_senior.route_finding(
            "b5", _d("Understated allowance on receivables", "Provision clients sous-estimée"), amount=3200000, accounts="411000 / 681000",
            file_item=active["E4.1"], mtype="factual",
        )
        as_senior.route_finding(
            "b5", _d("Cut-off of December sales", "Cut-off des ventes de décembre"), amount=1450000, accounts="701000 / 411000",
            file_item=active["E4.20"], mtype="judgmental",
        )

    def review_notes(self, active):
        active["C5.11"].with_user(self.essomba).add_review_note(_d("Please state who receives the communication.", "Merci de préciser les destinataires de la communication."))
        active["E6.3"].with_user(self.mbarga).add_review_note(_d("The twelve-month cash plan is missing: obtain it from management.", "Le plan de trésorerie à douze mois manque : à obtenir de la direction."))
        active["E4.1"].with_user(self.ndongo).add_review_note(_d("The 450,000 FCFA difference with the sub-ledger remains to be explained.", "L'écart de 450 000 FCFA avec la balance auxiliaire reste à expliquer."))

    def agro_2025(self):
        """The file a person walks: acceptance waits for the partner, then WALK_PAPERS."""
        engagement = self.mission("ea_audit_ui.demo_client_agro", 2025, self.mbarga, "very_simple")
        self.seat_team(engagement)
        for code in _WALK_ENSURED:
            engagement._ea_ensure_task(code)
        self.import_tb(engagement, _carried(_balanced(_CLOSING_2024)), _CLOSING_2025)
        engagement.with_user(self.ndongo).create_dataset(
            "journal_entries", "grand-livre-2025.csv", _ledger_csv(2025), mapping=_LEDGER_MAPPING,
        )
        ledger = self.env["ea.audit.dataset"].sudo().search([("engagement_id", "=", engagement.id)], limit=1)
        engagement.with_user(self.ndongo).gl_build_projection(ledger.id)
        for code, item in self.items(engagement).items():
            if item.task_phase == "acceptance" and not item.conditional and code != "P1.1":
                self.complete(item)
        p11 = self.items(engagement)["P1.1"]
        self.assign(p11, self.essomba, self.mbarga)
        self.fill(p11, self.essomba)
        p11.with_user(self.essomba).action_sign("preparer")
        for code, item in self.items(engagement).items():
            if item.task_phase == "acceptance" or item.conditional:
                continue
            if code in WALK_PAPERS:
                self.assign_by_rule(item)
            elif not code.startswith("E4.") or code == "E4.36":
                item.with_user(self.essomba).set_not_applicable(_WALK_NA_REASON)
        open_items = engagement.file_item_ids.filtered(lambda i: i.state != "signed" and not i.conditional and not i.not_applicable)
        self.due(list(open_items), 30)
        self.due([p11], 7)
        return engagement

    def foret_2025(self):
        """Another partner's file: J.-P. Mbarga only has the invitation until he
        accepts it, which is the team-only rule on screen."""
        engagement = self.mission("ea_audit_ui.demo_client_foret", 2025, self.fotso, "very_simple")
        engagement.with_user(self.fotso).invite_team_member(self.mbarga.login, "director")
        return engagement

    def settle_the_bell(self):
        """Keep what still asks something of the reader: the hundreds of rows the
        build itself produced would bury it."""
        Notification = self.env["ea.audit.notification"].sudo()
        for row in Notification.search([("read_at", "=", False)]):
            item = row.file_item_id
            still_asked = (
                row.kind == "invitation"
                or row.title.startswith(("Finding", "Review note", "Constat", "Note de revue"))  # i18n: input
                or (row.title.startswith(("To review", "À réviser")) and item.state == "prepared" and item.approver_id == row.user_id)  # i18n: input
            )
            if not still_asked:
                row.unlink()


class AuditUiDemo(models.AbstractModel):
    _inherit = "ea.audit.ui"

    @api.model
    def _ea_ui_load_demo(self):
        env = self.env
        if env["ea.audit.engagement"].sudo().search_count([]):
            return  # never on top of real files
        # The demonstration speaks the firm's language: EA_AUDIT_DEMO_LANG, else the company's.
        lang = os.environ.get("EA_AUDIT_DEMO_LANG") or env.company.partner_id.lang or "en_US"
        _Demo.french = lang.startswith("fr")
        lang = "fr_FR" if _Demo.french else "en_US"
        xaf = env.ref("base.XAF")
        xaf.active = True
        env.ref("base.main_company").currency_id = xaf
        people = env["res.users"].browse([
            env.ref("ea_audit_ui.demo_user_%s" % name).id for name in ("mbarga", "essomba", "ndongo", "tchoua", "fotso")
        ])
        people.write({"lang": lang})
        # the administrator is a firm role like any other: no team, no mission
        admin = env.ref("base.user_admin")
        admin.write({"name": _d("Demo Administrator", "Administrateur Démo"), "lang": lang, "group_ids": [(4, env.ref("ea_audit_core.group_firm_admin").id)]})

        demo = _Demo(env)
        demo.archived_2024()
        demo.negoce_2025()
        demo.agro_2025()
        demo.foret_2025()
        demo.settle_the_bell()
