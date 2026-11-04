"""The demonstration missions, loaded by demo_data.xml only when demo data is on.

Everything goes through the real methods, as the named user, wherever the core
lets it: engagements are created, teams seated, tasks assigned and papers signed
with action_sign. Three things cannot, because the hooks of later addons fail
closed until those addons exist, and are written directly:

- phases: advance_to_planning and close_planning need the P1.1 form, materiality
  and the rest. The mission's phase is set by hand.
- signatures on tool-fed papers: E4.1-E4.34 need the trial balance, P6.1 and P6.2
  materiality, C1.1 the three of them, and P7.2 the RAS approval. Those rows carry
  content_hash = DEMO_DIRECT_HASH and the task list labels them "démo".
- the E4 tasks left out of the eleven shown: S5.5 decides that today and lives in a
  later addon, so the others are marked conditional here.
"""
from datetime import date, timedelta

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.signoff_rules import team_rank
from odoo.addons.ea_audit_core.services.tool_fed import is_tool_fed_paper

from ..models.ui_data import DEMO_DIRECT_HASH

_E4_SHOWN = ("E4.1", "E4.2", "E4.3", "E4.4", "E4.5", "E4.6", "E4.7", "E4.8", "E4.9", "E4.10", "E4.20")
_NOT_DONE_STRATEGY = ("S2.5", "S4.4", "S5.4")


def _fails_closed(code):
    """A paper whose real sign-off refuses until a later addon overrides its hook."""
    return is_tool_fed_paper(code) or code == "P7.2"


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

    def mission(self, client_xmlid, year, partner, complexity, phase=None):
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
        if phase:
            engagement.phase = phase  # see the module docstring
        return engagement

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

    def direct(self, item, role, user, days_ago):
        self.env["ea.audit.signoff"].sudo().create({
            "file_item_id": item.id,
            "role": role,
            "user_id": user.id,
            "content_hash": DEMO_DIRECT_HASH,
            "signed_at": fields.Datetime.now() - timedelta(days=days_ago),
        })

    def complete(self, item, days_ago=10):
        """Prepared and reviewed, or approved by the partner where the rule says so."""
        preparer, reviewer = self.assign_by_rule(item)
        rule = self.Policy._ea_effective_rule(item.code)
        role = "partner" if rule["partner_required"] else "reviewer"
        signer = self.mbarga if rule["partner_required"] else reviewer
        if _fails_closed(item.code):
            self.direct(item, "preparer", preparer, days_ago + 2)
            self.direct(item, role, signer, days_ago)
            item.state = "signed"
            return
        item.with_user(preparer).action_sign("preparer")
        item.with_user(signer).action_sign(role)

    def prepared(self, item, preparer, approver):
        self.assign(item, preparer, approver)
        if _fails_closed(item.code):
            self.direct(item, "preparer", preparer, 8)
            item.state = "prepared"
            return
        item.with_user(preparer).action_sign("preparer")

    def due(self, items, days):
        if items:
            self.env["ea.audit.file.item"].browse([item.id for item in items]).with_user(self.essomba).write({
                "due_date": self.today + timedelta(days=days),
            })

    # ------------------------------------------------------------------

    def archived_2024(self):
        engagement = self.mission("ea_audit_ui.demo_client_negoce", 2024, self.mbarga, "very_simple", "conclusion")
        self.seat_team(engagement)
        for item in engagement.file_item_ids.filtered(lambda i: not i.conditional):
            self.complete(item, days_ago=30)
        engagement.write({"phase": "archived", "archived_at": fields.Datetime.now() - timedelta(days=60)})
        return engagement

    def negoce_2025(self):
        engagement = self.mission("ea_audit_ui.demo_client_negoce", 2025, self.mbarga, "complex", "execution")
        self.seat_team(engagement)
        items = self.items(engagement)
        for code, item in items.items():
            if code.startswith("E4.") and code not in _E4_SHOWN:
                item.conditional = True  # see the module docstring
        active = {code: item for code, item in items.items() if not item.conditional}

        # planning done; strategy nearly
        for code, item in active.items():
            if code[0] == "P" or (code[0] == "S" and code not in _NOT_DONE_STRATEGY):
                self.complete(item)
        for code in _NOT_DONE_STRATEGY:
            self.assign_by_rule(active[code])
            active[code].state = "in_progress"

        # execution, as the mock-up's lists
        for code in ("E1.1", "E1.2", "E2.1", "E3.1", "E6.7", "E6.2", "E6.4", "E4.2", "E4.5", "E4.6", "E4.7"):
            self.complete(active[code], days_ago=9)
        self.prepared(active["E4.1"], self.tchoua, self.ndongo)
        self.assign(active["E4.3"], self.tchoua, self.ndongo)
        self.assign(active["E4.4"], approver=self.ndongo)
        self.assign(active["E4.20"], self.ndongo, self.essomba)
        for code in ("E4.3", "E4.4", "E4.20", "E6.6"):
            active[code].state = "in_progress"
        for code in ("E4.8", "E4.9", "E4.10", "E6.5", "E6.8", "E6.6"):
            self.assign(active[code], self.tchoua, self.ndongo)
        self.assign(active["E6.10"], self.ndongo, self.essomba)

        # waiting for the partner
        self.prepared(active["E6.3"], self.ndongo, self.mbarga)
        self.prepared(active["E6.1"], self.tchoua, self.mbarga)
        self.prepared(active["E6.9"], self.tchoua, self.mbarga)
        self.prepared(active["C5.3"], self.essomba, self.mbarga)

        # conclusion: staffed in part, the rest in the "no preparer" band
        for code in ("C1.1", "C1.2", "C1.3", "C2.1", "C2.2", "C3.1", "C4.1"):
            self.assign_by_rule(active[code])
        self.assign(active["C5.11"], assignee=self.mbarga)

        # deadlines: two late, the rest ahead
        open_items = [i for i in active.values() if i.state != "signed"]
        self.due([i for i in open_items if i.section == "D"], 10)
        self.due([i for i in open_items if i.section == "E"], 24)
        self.due([i for i in open_items if i.section not in ("D", "E")], 60)
        self.due([active["E4.1"]], -12)
        self.due([active["E6.3"]], -5)
        return engagement

    def agro_2025(self):
        """Still in acceptance: only the acceptance papers can be signed yet."""
        engagement = self.mission("ea_audit_ui.demo_client_agro", 2025, self.mbarga, "very_simple")
        self.seat_team(engagement)
        for code, item in self.items(engagement).items():
            if item.task_phase == "acceptance" and not item.conditional and code != "P1.1":
                self.complete(item, days_ago=4)
        p11 = self.items(engagement)["P1.1"]
        self.assign(p11, self.essomba, self.mbarga)
        p11.with_user(self.essomba).action_sign("preparer")
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
            still_asked = row.kind == "invitation" or (
                row.title.startswith("À réviser") and item.state == "prepared" and item.approver_id == row.user_id
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
        admin.write({"lang": "fr_FR", "group_ids": [(4, env.ref("ea_audit_core.group_firm_admin").id)]})

        demo = _Demo(env)
        demo.archived_2024()
        demo.negoce_2025()
        demo.agro_2025()
        demo.foret_2025()
        demo.settle_the_bell()
