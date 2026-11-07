from odoo import api, fields, models

LEGAL_FORM_SELECTION = [
    ("SA", "SA (board of directors)"),
    ("SA_AG", "SA (administrateur général)"),
    ("SARL", "SARL"),
    ("SAS", "SAS"),
    ("GIE", "GIE"),
    ("OTHER", "Other"),
]

SECTOR_SELECTION = [
    ("agriculture", "Agriculture"),
    ("industry", "Industry"),
    ("trade", "Trade"),
    ("services", "Services"),
    ("financial", "Financial"),
    ("telecom", "Telecoms"),
    ("energy", "Energy"),
    ("construction", "Construction"),
    ("transport", "Transport"),
    ("public", "Public sector"),
    ("other", "Other"),
]


GOVERNANCE_SELECTION = [
    ("ca_pdg", "Board with chair and CEO (PDG)"),
    ("ca_dg", "Board with a chair and a CEO (PCA + DG)"),
    ("administrateur_general", "Sole director (administrateur général)"),
    ("gerance", "Management by gérant(s)"),
]
REGULATOR_SELECTION = [
    ("COBAC", "COBAC (banking)"),
    ("CIMA", "CIMA (insurance)"),
    ("COSUMAF", "COSUMAF (capital markets)"),
    ("CRCA", "CRCA (cooperatives)"),
    ("BEAC", "BEAC"),
    ("ARSEL", "ARSEL (electricity)"),
    ("ART", "ART (telecoms)"),
    ("OTHER", "Other"),
]
#: F073: the one framework on offer; the stored key is what the column already holds.
FRAMEWORK_SELECTION = [("SYSCOHADA", "Revised SYSCOHADA, normal system")]


class AuditClient(models.Model):
    """The firm's client entity. Clients are firm-level records: any firm role
    reads them; only their engagements are team-only."""

    _name = "ea.audit.client"
    _description = "Audit client"
    _order = "name, id"

    name = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True, help="Retired clients are archived.")
    partner_id = fields.Many2one(
        "res.partner", string="Contact", required=True, index=True, ondelete="restrict", copy=False,
    )
    legal_form = fields.Selection(LEGAL_FORM_SELECTION, required=True, default="SA")
    sector = fields.Selection(SECTOR_SELECTION)
    listed = fields.Boolean()
    co_cac = fields.Boolean(string="Joint auditor (co-CAC)")
    pie = fields.Boolean(string="Public interest entity")
    niu = fields.Char(string="NIU")
    registration_number = fields.Char()
    framework = fields.Selection(FRAMEWORK_SELECTION, string="Reporting framework", required=True, default="SYSCOHADA")
    governance_mode = fields.Selection(GOVERNANCE_SELECTION)
    regulator = fields.Selection(REGULATOR_SELECTION)
    engagement_ids = fields.One2many("ea.audit.engagement", "client_id", string="Engagements")

    _partner_uniq = models.Constraint("UNIQUE(partner_id)", "This contact already has a client record.")

    def init(self):
        # F074: a client saved before the framework was required, or with free text, takes the only one on offer.
        self.env.cr.execute("UPDATE ea_audit_client SET framework = 'SYSCOHADA' WHERE framework IS DISTINCT FROM 'SYSCOHADA'")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("partner_id"):
                # internal link only: writers need no rights on the contact book
                partner = self.env["res.partner"].sudo().create({"name": vals.get("name"), "is_company": True})
                vals["partner_id"] = partner.id
        return super().create(vals_list)

    def write(self, vals):
        result = super().write(vals)
        if vals.get("name"):
            self.partner_id.sudo().write({"name": vals["name"]})
        return result
