from odoo import fields, models

from odoo.addons.ea_platform_admin.services import heartbeat


class PlatformFirm(models.Model):
    _inherit = "platform.firm"

    pipeline_role = fields.Selection(
        [("firm", "A firm"), ("staging", "The staging server")], "Role in the pipeline", default="firm", required=True,
        help="The staging server reports like a firm, so its health is known here. It never takes part in a "
             "rollout and is never a source for a rebuild.",
    )
    anon_export_state = fields.Selection(
        [("running", "Running"), ("done", "Done"), ("failed", "Failed"), ("refused", "Refused by the firm")],
        "Anonymised export", readonly=True, copy=False,
    )
    anon_export_ref = fields.Char("Anonymised export: reference", readonly=True, copy=False)
    anon_export_at = fields.Datetime("Anonymised export: when", readonly=True, copy=False)
    anon_export_sha256 = fields.Char("Anonymised export: digest", readonly=True, copy=False)

    def _apply_figures(self, values, timestamp):
        result = super()._apply_figures(values, timestamp)
        self.write({
            "anon_export_state": values.get("anon_export_state") or False,
            "anon_export_ref": values.get("anon_export_ref") or False,
            "anon_export_at": heartbeat.parse_instant(values.get("anon_export_at")) or False,
            "anon_export_sha256": values.get("anon_export_sha256") or False,
        })
        self.env["platform.pipeline.rebuild"]._on_firm_figures(self, values)
        return result

    def _heartbeat_answer(self):
        """One word more: the reference of an anonymised copy this firm is asked to make. It stays there."""
        answer = super()._heartbeat_answer()
        rebuild = self.env["platform.pipeline.rebuild"].sudo().search(
            [("source_firm_id", "=", self.id), ("state", "=", "requested")], limit=1,
        )
        if rebuild and self.state == "active":
            answer["anon_export_ref"] = rebuild.request_ref
        return answer

    def _staging_figures(self):
        firm = self.sudo().search([("pipeline_role", "=", "staging"), ("state", "!=", "archived")], limit=1)
        if not firm:
            return None
        return {
            "last_heartbeat_at": firm.last_heartbeat_at,
            "health_color": firm.health_color,
            "release": firm.addon_release,
            "mail_enabled": firm.mail_enabled,
        }
