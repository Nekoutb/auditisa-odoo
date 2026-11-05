"""The demonstration missions, loaded by demo_data.xml only when demo data is on.

Everything goes through the real methods, as the named user: engagements are created,
teams seated, papers answered with save_answers, signed with action_sign, the trial
balance imported, materiality approved, phases advanced by their gates. What cannot,
because the method or tool does not exist yet, is written directly and listed here:

- execution to conclusion and archiving: core has no method for them. The 2024 file's
  phase is set by hand once planning has really closed.
- S1.2, S1.3, S2.1, S2.2, S2.3: SCOT Studio and S2.5 are not built, so their signature
  refuses. They stay in progress on the current files and not applicable on the archive.
- the E4 tasks left out of the eleven shown: S5.5 decides that, and is not built, so the
  others are marked conditional here.

Tropical Agro-Industries 2025 is the file a person walks: its trial balance is imported,
P1.1 is prepared and waits for the partner, and nothing of planning is done.
"""
import logging
from datetime import date, timedelta

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.errors import AuditRuleError
from odoo.addons.ea_audit_core.services.signoff_rules import team_rank
from odoo.addons.ea_audit_papers.services import required_keys
from odoo.addons.ea_audit_papers.services.planning_ras import SECTION_A, SECTION_B
from odoo.addons.ea_audit_tools.services.lead_classes import INDEX_SECTION

_logger = logging.getLogger(__name__)

_E4_SHOWN = ("E4.1", "E4.2", "E4.3", "E4.4", "E4.5", "E4.6", "E4.7", "E4.8", "E4.9", "E4.10", "E4.20")
_NOT_DONE_STRATEGY = ("S2.5", "S4.4", "S5.4")
# their board belongs to a tool not built: see the module docstring
_NO_TOOL_YET = ("S1.2", "S1.3", "S2.1", "S2.2", "S2.3")
_SELECT_ANSWERS = {
    "engagement_type": "recurring",
    "auditor_change": "no",
    "rating": "moderate",
    "itgc_state": "support",
}
_DONE_TEXT = "Effectué, voir la feuille de travail."

_ACCOUNTS = {
    "101000": "Capital social",
    "121000": "Report à nouveau",
    "162000": "Emprunts",
    "231000": "Bâtiments",
    "241000": "Matériel et outillage",
    "284000": "Amortissements du matériel",
    "311000": "Marchandises",
    "401000": "Fournisseurs",
    "411000": "Clients",
    "431000": "Sécurité sociale",
    "441000": "État, impôt sur les bénéfices",
    "521000": "Banques",
    "571000": "Caisse",
    "601000": "Achats de marchandises",
    "622000": "Locations",
    "641000": "Impôts et taxes",
    "661000": "Rémunérations",
    "681000": "Dotations aux amortissements",
    "701000": "Ventes de marchandises",
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
    lines = ["Compte;Libellé;Solde ouverture débit;Solde ouverture crédit;Mouvement débit;Mouvement crédit"]
    for code in sorted(_ACCOUNTS):
        before = opening.get(code, 0)
        movement = closing.get(code, 0) - before
        lines.append(";".join(str(cell) for cell in (
            code, _ACCOUNTS[code], max(before, 0), max(-before, 0), max(movement, 0), max(-movement, 0),
        )))
    return ("\n".join(lines) + "\n").encode("utf-8")


class _Demo:
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
        return self.env["ea.audit.engagement"].with_user(partner).create({
            "client_id": client.id,
            "fiscal_year": year,
            "period_end": date(year, 12, 31),
            "duration_months": 12,
            "nature": "statutory_audit",
            "complexity": complexity,
            "engagement_partner_id": partner.id,
        }).sudo()

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
                out["%s_x" % key] = "Critère non rempli pour cette entité."
            elif key.startswith(("q_", "c_")):
                out[key] = "yes"
            else:
                out[key] = _DONE_TEXT
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
            "revenue", amount, 1, "Le chiffre d'affaires est stable et le principal indicateur suivi par les associés.",
        )
        version.with_user(self.mbarga).action_approve()

    def respond_to_risks(self, engagement):
        """Every significant risk has a planned response, as the planning gate requires."""
        as_senior = engagement.with_user(self.ndongo)
        receivables = next(code for code, paper in INDEX_SECTION.items() if paper == "E4.1")
        as_senior.add_risk(
            "Dépréciation insuffisante des créances anciennes", category="error", likelihood="medium", magnitude="high",
            significant=True, index=receivables, assertions=["V"],
        )
        as_senior.add_risk("Dépendance à un fournisseur unique", category="business", likelihood="medium", magnitude="medium")
        for risk in self.env["ea.audit.risk"].sudo().search([
            ("engagement_id", "=", engagement.id), ("significant", "=", True), ("program_step_ids", "=", False),
        ]):
            items = self.items(engagement)
            section = risk.section_link_ids.file_item_id[:1] or items.get("E4.1") or items["E1.1"]
            step = as_senior.add_program_step(section, "Réponse au risque : %s" % risk.description[:80])
            risk.with_user(self.ndongo).link_step(step)

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

    def walk_planning(self, engagement, opening, closing, keep_open=()):
        self.import_tb(engagement, opening, closing)
        self.approve_materiality(engagement)
        self.respond_to_risks(engagement)
        self.assess_cra(engagement)
        for code, item in self.items(engagement).items():
            if item.conditional or item.task_phase != "planning" or code == "P7.2":
                continue
            if code in _NO_TOOL_YET or code in keep_open:
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
        self.walk_planning(engagement, opening, _CLOSING_2024)
        engagement.phase = "conclusion"  # see the module docstring
        engagement.with_user(self.ndongo).save_sad_conclusion("Aucune anomalie significative non corrigée.")
        for item in engagement.file_item_ids.filtered(lambda i: not i.conditional and i.state != "signed"):
            if item.code in _NO_TOOL_YET:
                item.with_user(self.essomba).set_not_applicable("Traité hors outil sur ce dossier de démonstration.")
                continue
            try:
                with self.env.cr.savepoint():
                    self.complete(item)
            except AuditRuleError as error:
                _logger.warning("Demo: %s of the 2024 file stays unsigned: %s", item.code, error.code)
        engagement.write({"phase": "archived", "archived_at": fields.Datetime.now() - timedelta(days=60)})
        return engagement

    def negoce_2025(self):
        engagement = self.mission("ea_audit_ui.demo_client_negoce", 2025, self.mbarga, "complex")
        self.seat_team(engagement)
        for code, item in self.items(engagement).items():
            if code.startswith("E4.") and code not in _E4_SHOWN:
                item.conditional = True  # see the module docstring
        self.walk_acceptance(engagement)
        self.walk_planning(engagement, _carried(_balanced(_CLOSING_2024)), _CLOSING_2025, keep_open=_NOT_DONE_STRATEGY)
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
            "c1", "Absence de rapprochement bancaire mensuel", severity="significant_deficiency",
            detail="Les rapprochements de 2025 n'ont été faits qu'en fin d'exercice.",
            recommendation="Rapprocher chaque compte bancaire chaque mois, avec revue par le directeur financier.",
            file_item=active["E4.3"],
        )
        as_senior.route_finding(
            "b4", "Reprise manuelle sur les comptes clients", detail="Saisies manuelles sans pièce en décembre.",
            file_item=active["E4.1"],
        )
        as_senior.route_finding(
            "b5", "Provision clients sous-estimée", amount=3200000, accounts="411000 / 681000",
            file_item=active["E4.1"], mtype="factual",
        )
        as_senior.route_finding(
            "b5", "Cut-off des ventes de décembre", amount=1450000, accounts="701000 / 411000",
            file_item=active["E4.20"], mtype="judgmental",
        )

    def review_notes(self, active):
        active["C5.11"].with_user(self.essomba).add_review_note("Merci de préciser les destinataires de la communication.")
        active["E6.3"].with_user(self.mbarga).add_review_note("Le plan de trésorerie à douze mois manque : à obtenir de la direction.")
        active["E4.1"].with_user(self.ndongo).add_review_note("L'écart de 450 000 FCFA avec la balance auxiliaire reste à expliquer.")

    def agro_2025(self):
        """The file a person walks: acceptance waits for the partner, planning is all ahead."""
        engagement = self.mission("ea_audit_ui.demo_client_agro", 2025, self.mbarga, "very_simple")
        self.seat_team(engagement)
        self.import_tb(engagement, _carried(_balanced(_CLOSING_2024)), _CLOSING_2025)
        for code, item in self.items(engagement).items():
            if item.task_phase == "acceptance" and not item.conditional and code != "P1.1":
                self.complete(item)
        p11 = self.items(engagement)["P1.1"]
        self.assign(p11, self.essomba, self.mbarga)
        self.fill(p11, self.essomba)
        p11.with_user(self.essomba).action_sign("preparer")
        for item in engagement.file_item_ids.filtered(lambda i: i.state == "not_started" and not i.conditional):
            self.assign_by_rule(item)
        open_items = engagement.file_item_ids.filtered(lambda i: i.state != "signed" and not i.conditional)
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
                or row.title.startswith(("Constat", "Note de revue"))
                or (row.title.startswith("À réviser") and item.state == "prepared" and item.approver_id == row.user_id)
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
        env["res.lang"]._activate_lang("fr_FR")
        xaf = env.ref("base.XAF")
        xaf.active = True
        env.ref("base.main_company").currency_id = xaf
        people = env["res.users"].browse([
            env.ref("ea_audit_ui.demo_user_%s" % name).id for name in ("mbarga", "essomba", "ndongo", "tchoua", "fotso")
        ])
        people.write({"lang": "fr_FR"})
        # the administrator is a firm role like any other: no team, no mission
        admin = env.ref("base.user_admin")
        admin.write({"name": "Administrateur Démo", "lang": "fr_FR", "group_ids": [(4, env.ref("ea_audit_core.group_firm_admin").id)]})

        demo = _Demo(env)
        demo.archived_2024()
        demo.negoce_2025()
        demo.agro_2025()
        demo.foret_2025()
        demo.settle_the_bell()
