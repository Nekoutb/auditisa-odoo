from odoo import api, fields, models

from ..services.email_domains import InvalidDomainError, parse_domain_list
from ..services.errors import rule_error


class ResCompany(models.Model):
    _inherit = "res.company"

    ea_allowed_email_domains = fields.Text(
        string="Allowed email domains",
        help="The domains an engagement-team invitation may be sent to, one per line. Empty means no restriction.",
    )

    @api.model
    def _ea_allowed_domains(self):
        """The firm's list. One database per firm: the firm is the current company."""
        return (self.env.company.sudo().ea_allowed_email_domains or "").split()

    @api.model
    def ea_set_firm_language(self, code):
        """The language of the firm: new accounts take it (firm administrator)."""
        if self.env.user._ea_firm_role() != "firm_admin":
            raise rule_error(self.env, "forbidden")
        if code not in ("fr_FR", "en_US"):
            raise rule_error(self.env, "forbidden")
        partner = self.env.company.sudo().partner_id
        if partner.lang != code:
            partner.lang = code
            self.env["ea.audit.activity"]._ea_record(False, "firm_language_set", "Firm language set to %s" % code)
        return code

    @api.model
    def ea_set_allowed_domains(self, raw):
        """Replace the firm's list (firm administrator). An empty input clears it."""
        if self.env.user._ea_firm_role() != "firm_admin":
            raise rule_error(self.env, "forbidden")
        try:
            domains = parse_domain_list(raw)
        except InvalidDomainError:
            raise rule_error(self.env, "invalid-email-domain") from None
        self.env.company.sudo().ea_allowed_email_domains = "\n".join(domains)
        return domains
