import base64
import os
import secrets
import struct

from odoo import api, fields, models

from odoo.addons.ea_platform_admin.services import heartbeat
from odoo.addons.ea_platform_admin.services.messages import _

from ..services import pipeline


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

    def _pmail_refusal(self):
        """The staging server (test.auditisa.com) never sends email: no platform address for it, ever."""
        if self.pipeline_role == "staging":
            return _("The staging server (test.auditisa.com) never sends email: it gets no platform address.")
        return super()._pmail_refusal()

    def _alert(self, reasons):
        # Staging keeps no backups and tests no restore: that is no alarm.
        self.ensure_one()
        if self.pipeline_role == "staging":
            return None
        return super()._alert(reasons)

    @api.model
    def _pipeline_enrol_staging(self, token_path="/etc/auditisa-platform/staging-heartbeat.token"):
        """Adds the row that stands for the staging server. From `odoo shell` on the control plane, once.

        The token goes to a root-only file and is never printed. The owner copies that file to staging.
        The SSH key is a random public one with no private half: this row is never provisioned or logged in to.
        """
        existing = self.sudo().search([("pipeline_role", "=", "staging"), ("state", "!=", "archived")], limit=1)
        if existing:
            return existing
        token = secrets.token_hex(32)
        algorithm = b"ssh-ed25519"
        blob = struct.pack(">I", len(algorithm)) + algorithm + struct.pack(">I", 32) + secrets.token_bytes(32)
        firm = self.sudo().create({
            "name": "Staging (test.auditisa.com)",
            "slug": "staging-server",
            "contact_name": "Operator",
            "contact_email": "operator@auditisa.invalid",
            "allowed_email_domains": "auditisa.invalid",
            "region": "cdg",
            "size": "standard",
            "state": "active",
            "pipeline_role": "staging",
            "ssh_public_key": "ssh-ed25519 " + base64.b64encode(blob).decode("ascii") + " no-private-half",
            "heartbeat_token": token,
        })
        descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as handle:
            handle.write(token + "\n")
        return firm

    def _staging_health_word(self):
        """ok, down or unknown, from how recent its last heartbeat is. Only sent while Odoo answers."""
        self.ensure_one()
        if not self.last_heartbeat_at:
            return "unknown"
        return "ok" if fields.Datetime.now() - self.last_heartbeat_at <= pipeline.HEARTBEAT_FRESH else "down"

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
