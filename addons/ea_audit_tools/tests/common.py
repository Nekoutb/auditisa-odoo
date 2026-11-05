from datetime import date

from odoo.addons.ea_audit_core.tests.common import EaAuditCase

#: A balanced SYSCOHADA TB with opening balances, in the columns a French export carries.
BALANCED_CSV = """Compte;Libellé;Solde ouverture débit;Solde ouverture crédit;Mouvement débit;Mouvement crédit
101000;Capital;0;5000;0;0
231000;Bâtiments;4000;0;0;0
411000;Clients;800;0;1000;900
401000;Fournisseurs;0;500;400;500
521000;Banque;700;0;900;900
601000;Achats;0;0;2000;0
701000;Ventes;0;0;0;2000
"""

UNBALANCED_CSV = """Compte;Libellé;Mouvement débit;Mouvement crédit
411000;Clients;1000;0
701000;Ventes;0;900
"""


def to_bytes(text):
    return text.encode("utf-8")


class ToolsCase(EaAuditCase):
    """One engagement, a full team, a read-only member, and an outsider with a firm role."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reader2 = cls._user("reader2", "group_read_only")

    def setUp(self):
        super().setUp()
        self.engagement = self.make_engagement(year=2025)
        self.seat(self.engagement, self.manager, "manager")
        self.seat(self.engagement, self.senior, "senior")
        self.seat(self.engagement, self.staff, "staff")
        self.seat(self.engagement, self.reader, "staff")
        self.seat(self.engagement, self.eqr, "eqr_reviewer")
        self.as_partner = self.engagement.with_user(self.partner)
        self.as_staff = self.engagement.with_user(self.staff)
        self.as_manager = self.engagement.with_user(self.manager)
        self.as_reader = self.engagement.with_user(self.reader)
        self.as_outsider = self.engagement.with_user(self.outsider)
        self.as_eqr = self.engagement.with_user(self.eqr)

    def import_tb(self, content=BALANCED_CSV, filename="balance.csv", timing="pre_audit", actor=None):
        return (actor or self.as_staff).import_trial_balance(filename, to_bytes(content), timing=timing)

    def approve(self, overall_pct=2, trivial_pct=5, benchmark="total_assets", amount=None):
        """A TB, a version on its base, the partner's approval."""
        if not self.engagement.sudo()._ea_current_tb_version():
            self.import_tb()
        bases = self.engagement.sudo()._ea_tb_bases()
        version = self.as_staff.create_materiality_version(
            benchmark, amount if amount is not None else bases[benchmark], overall_pct, "Profitable and stable.",
            trivial_pct=trivial_pct,
        )
        version.with_user(self.partner).action_approve()
        return version.sudo()

    def period_end(self):
        return date(2025, 12, 31)
