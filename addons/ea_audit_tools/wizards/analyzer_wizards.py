from odoo import fields, models


class SupplierReconWizard(models.TransientModel):
    _name = "ea.audit.supplier.recon.wizard"
    _description = "Supplier statements against the ledger"

    engagement_id = fields.Many2one("ea.audit.engagement", required=True)
    statement_id = fields.Many2one("ea.audit.dataset", string="Supplier statements", required=True, domain="[('engagement_id', '=', engagement_id), ('kind', '=', 'supplier_statements')]")
    ledger_id = fields.Many2one("ea.audit.dataset", string="Payables ledger", required=True, domain="[('engagement_id', '=', engagement_id), ('kind', '=', 'ap_open_items')]")

    def action_run(self):
        self.ensure_one()
        return self.engagement_id.run_supplier_recon(self.statement_id.id, self.ledger_id.id).action_export()
