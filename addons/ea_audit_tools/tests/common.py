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


#: A receivables file with every mandatory field of its kind, and the mapping a person would confirm.
AR_CSV = """Client;Nom;Référence;Date;Montant
C1;Alpha;F1;15/12/2025;100
C2;Beta;F2;15/10/2025;250
"""
AR_MAPPING = {"party": "Client", "partyName": "Nom", "reference": "Référence", "date": "Date", "amount": "Montant"}
#: The same for payables. The name is not titled "Nom": the supplier reconciliation takes the first
#: column whose title reads as a supplier or a name for its key.
AP_MAPPING = {"party": "Fournisseur", "partyName": "Raison sociale", "reference": "Référence", "date": "Date", "amount": "Montant"}


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

    def invalid_version(self, content=UNBALANCED_CSV, filename="invalid.csv", timing="pre_audit"):
        """A version saved as invalid, as the import kept them before the ruling of 2026-11-15:
        such versions remain in the databases of that time. Written as that import wrote it."""
        from odoo import fields

        from odoo.addons.ea_audit_tools.services.tb import extract_tb_rows, infer_tb_mapping, readability_of, validate_tb_rows
        from odoo.addons.ea_audit_tools.tabular import parse_table

        engagement = self.engagement.sudo()
        table = parse_table(filename, to_bytes(content))
        mapping = infer_tb_mapping(table["headers"])
        rows = extract_tb_rows(table, mapping)
        summary = validate_tb_rows(rows, engagement._ea_known_prefixes(), None, mapping, readability_of(table, mapping))
        self.assertEqual(summary["status"], "invalid")
        tb = engagement._ea_tb() or self.env["ea.audit.tb"].sudo().create({"engagement_id": engagement.id})
        Version = self.env["ea.audit.tb.version"].sudo()
        Version.search([("tb_id", "=", tb.id), ("timing", "=", timing), ("superseded_at", "=", False)]).write({"superseded_at": fields.Datetime.now()})
        number = max(Version.search([("tb_id", "=", tb.id)], order="version_no desc", limit=1).version_no, tb.last_version_no) + 1
        tb.last_version_no = number
        version = Version.create({
            "engagement_id": engagement.id, "tb_id": tb.id, "version_no": number, "timing": timing, "validation_status": "invalid",
            "source_filename": filename, "row_count": len(rows), "validation_summary": summary,
            "total_debit": summary["checks"]["balanced"]["totalDebit"], "total_credit": summary["checks"]["balanced"]["totalCredit"],
        })
        self.env["ea.audit.tb.line"].sudo().create([{
            "engagement_id": engagement.id, "version_id": version.id, "row_no": row_no, "account_code": row["account"],
            "account_name": row["label"], "debit": row["debit"], "credit": row["credit"],
        } for row_no, row in enumerate(rows, start=1)])
        return version

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
