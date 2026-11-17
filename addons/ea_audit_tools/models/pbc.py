"""PBC requests, firm side (lib/pbc.ts). The client's portal arrives with ea_audit_portal: it calls
upload_pbc. An accepted upload is filed on a task as an attachment, so it is reachable from the file."""
import base64
import hashlib

from odoo import fields, models

from odoo.addons.ea_audit_core.services.signoff_rules import can_review

from ..rules import rule_error
from ..services.errors import ServiceError
from ..services.upload_safety import check_upload
from .tool_record import french_date

MAX_PBC_BYTES = 25 * 1024 * 1024
STATUS_SELECTION = [("requested", "Requested"), ("uploaded", "Uploaded"), ("accepted", "Accepted")]


class PbcItem(models.Model):
    _name = "ea.audit.pbc.item"
    _inherit = ["ea.audit.tool.record"]
    _description = "Document request"
    _order = "create_date, id"
    _rec_name = "title"

    title = fields.Char(required=True)
    note = fields.Text()
    status = fields.Selection(STATUS_SELECTION, default="requested", required=True, index=True)
    filename = fields.Char()
    mime = fields.Char()
    content = fields.Binary(attachment=True)
    uploaded_at = fields.Datetime()
    uploaded_by_id = fields.Many2one("res.users", string="Uploaded by", ondelete="set null")
    chased_at = fields.Datetime()
    chase_count = fields.Integer()
    accepted_at = fields.Datetime()
    accepted_by_id = fields.Many2one("res.users", string="Accepted by", ondelete="set null")
    file_item_id = fields.Many2one("ea.audit.file.item", string="Filed under", ondelete="set null")
    attachment_id = fields.Many2one("ir.attachment", string="Filed document", ondelete="set null")
    age_days = fields.Integer(string="Age (days)", compute="_compute_age", compute_sudo=True)
    overdue = fields.Boolean(compute="_compute_age", compute_sudo=True)

    def _compute_age(self):
        """Calendar days at Africa/Douala (UAT B112); above 14 days reads red."""
        today = fields.Date.context_today(self.with_context(tz="Africa/Douala"))
        for item in self:
            created = fields.Date.context_today(self.with_context(tz="Africa/Douala"), item.create_date) if item.create_date else today
            item.age_days = (today - created).days
            item.overdue = item.status == "requested" and item.age_days > 14

    def chase(self):
        """chasePbc: a reminder nobody can receive is not a chase (UAT run 2 B76)."""
        self.ensure_one()
        self._ea_guard()
        as_root = self.sudo()
        engagement = as_root.engagement_id
        if not engagement._ea_portal_contacts():
            raise rule_error(self.env, "no-portal-contact")
        if as_root.status != "requested":
            raise rule_error(self.env, "wrong-status")
        as_root.write({"chased_at": fields.Datetime.now(), "chase_count": as_root.chase_count + 1})
        engagement._ea_log("pbc_chased", "PBC chased: %s" % as_root.title)
        return True

    def upload_pbc(self, filename, content):
        """uploadPbc: the portal's entry, and the firm's when a document arrives another way. The stored
        name and MIME come from what the bytes are. An accepted item is not replaced."""
        self.ensure_one()
        self._ea_guard()
        if not content:
            raise rule_error(self.env, "empty-file")
        if len(content) > MAX_PBC_BYTES:
            raise rule_error(self.env, "file-too-large")
        try:
            name, mime = check_upload(filename, content)
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error
        as_root = self.sudo()
        if as_root.status == "accepted":
            raise rule_error(self.env, "not-found")
        as_root.write({
            "status": "uploaded", "filename": name, "mime": mime, "content": base64.b64encode(content),
            "uploaded_at": fields.Datetime.now(), "uploaded_by_id": self.env.user.id,
        })
        as_root.engagement_id._ea_log(
            "pbc_uploaded", "PBC uploaded: %s (%s, sha256 %s)" % (as_root.title, name, hashlib.sha256(content).hexdigest()),
        )
        return True

    def _ea_require_reviewer(self):
        self._ea_guard()
        if not can_review(self.env.user._ea_firm_role()):
            raise rule_error(self.env, "forbidden")

    def _ea_file(self, file_item):
        """The bytes are checked again on the way into the audit file."""
        as_root = self.sudo()
        content = base64.b64decode(as_root.content or b"")
        try:
            name, mime = check_upload(as_root.filename or as_root.title, content)
        except ServiceError as error:
            raise rule_error(self.env, error.code) from error
        if not file_item or file_item.sudo().engagement_id != as_root.engagement_id:
            raise rule_error(self.env, "not-found")
        return self.env["ir.attachment"].sudo().create({
            "name": "Document request — %s — %s" % (as_root.title, name), "res_model": "ea.audit.file.item", "res_id": file_item.id,
            "datas": base64.b64encode(content), "mimetype": mime,
        })

    def accept(self, file_item):
        """acceptPbc: reviewer and above, and a task is required: an upload attached nowhere is
        unreachable from the file."""
        self.ensure_one()
        self._ea_require_reviewer()
        if not file_item:
            raise rule_error(self.env, "attach-required")
        as_root = self.sudo()
        if as_root.status != "uploaded" or not as_root.content:
            raise rule_error(self.env, "wrong-status")
        attachment = self._ea_file(file_item)
        as_root.write({
            "status": "accepted", "accepted_by_id": self.env.user.id, "accepted_at": fields.Datetime.now(),
            "attachment_id": attachment.id, "file_item_id": file_item.id,
        })
        as_root.engagement_id._ea_log("pbc_accepted", "PBC accepted: %s → %s" % (as_root.title, file_item.sudo().code))
        return attachment

    def attach_accepted(self, file_item):
        """attachAcceptedPbc: for an item accepted before the task became mandatory."""
        self.ensure_one()
        self._ea_require_reviewer()
        if not file_item:
            raise rule_error(self.env, "attach-required")
        as_root = self.sudo()
        if as_root.status != "accepted" or as_root.attachment_id or not as_root.content:
            raise rule_error(self.env, "wrong-status")
        attachment = self._ea_file(file_item)
        as_root.write({"attachment_id": attachment.id, "file_item_id": file_item.id})
        as_root.engagement_id._ea_log("pbc_attached", "PBC filed: %s → %s" % (as_root.title, file_item.sudo().code))
        return attachment

    def action_chase(self):
        for item in self:
            item.chase()
        return {"type": "ir.actions.client", "tag": "soft_reload"}

    def action_open_accept(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": self.env._("File the upload"), "res_model": "ea.audit.pbc.accept.wizard", "view_mode": "form", "views": [(False, "form")], "target": "new",
            "context": {"default_item_id": self.id, "default_engagement_id": self.sudo().engagement_id.id},
        }

    def action_open_upload(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "name": self.env._("Record a document received"), "res_model": "ea.audit.pbc.upload.wizard", "view_mode": "form", "views": [(False, "form")], "target": "new",
            "context": {"default_item_id": self.id},
        }

    def action_list_add_pbc(self):
        engagement = self._ea_context_engagement()
        return {
            "type": "ir.actions.act_window", "name": self.env._("Request a document"), "res_model": "ea.audit.pbc.wizard", "view_mode": "form", "views": [(False, "form")], "target": "new",
            "context": {"default_engagement_id": engagement.id},
        }

    def action_list_export(self):
        return self._ea_context_engagement()._ea_export_action("pbc")

    def _ea_export_kind(self):
        return "pbc"


class PortalContact(models.Model):
    """A client's portal contact. The account and its invitation belong to ea_audit_portal, which sets
    user_id; until then the firm records who is to receive the requests."""

    _name = "ea.audit.portal.contact"
    _inherit = ["ea.audit.client.override.mixin"]
    _description = "Client portal contact"
    _rec_name = "name"

    account_prefix = fields.Char(required=False, default="-")
    name = fields.Char(required=True)
    email = fields.Char(required=True)
    user_id = fields.Many2one("res.users", ondelete="set null")


class EngagementPbc(models.Model):
    _inherit = "ea.audit.engagement"

    def _ea_portal_contacts(self):
        self.ensure_one()
        return self.env["ea.audit.portal.contact"].sudo().search([("client_id", "=", self.sudo().client_id.id)])

    def add_pbc_item(self, title, note=""):
        """addPbcItem: on the trail (UAT run 2 B74). The portal's notice comes with ea_audit_portal."""
        self.ensure_one()
        self._ea_tool_guard()
        title = (title or "").strip()
        if not title:
            raise rule_error(self.env, "fields-required")
        item = self.env["ea.audit.pbc.item"].sudo().create({"engagement_id": self.id, "title": title, "note": note or False})
        self._ea_log("pbc_requested", "PBC requested: %s" % title)
        return item.with_env(self.env)

    def add_portal_contact(self, name, email):
        """addPortalContact, the firm's half. Reviewer and above."""
        self.ensure_one()
        self._ea_tool_guard()
        if not can_review(self.env.user._ea_firm_role()):
            raise rule_error(self.env, "forbidden")
        email = (email or "").lower().strip()
        if not email or not (name or "").strip():
            raise rule_error(self.env, "fields-required")
        Contact = self.env["ea.audit.portal.contact"].sudo()
        client = self.sudo().client_id
        if Contact.search_count([("client_id", "=", client.id), ("email", "=", email)]):
            raise rule_error(self.env, "email-taken")
        return Contact.create({"client_id": client.id, "name": name.strip(), "email": email})

    def action_tool_pbc(self):
        return self._ea_list(
            "ea.audit.pbc.item", self.env._("Document requests"), [("ea_audit_tools.view_pbc_list", "list")],
            {"context": {"ea_engagement_id": self.id, "create": False}},
        )

    def _ea_export_pbc(self, fr):
        from ..exports import simple_workbook

        rows = []
        for item in self.env["ea.audit.pbc.item"].sudo().search([("engagement_id", "=", self.id)]):
            rows.append([
                item.title, item.note or "", item.status, french_date(item.create_date), french_date(item.uploaded_at),
                item.age_days, item.chase_count, item.filename or "", item.file_item_id.code or "",
            ])
        return "pbc-%s.xlsx" % self._ea_export_slug(), simple_workbook("PBC", PBC_HEAD, rows)

    def _ea_import_pbc(self, table):
        count = 0
        for row in table["rows"]:
            self.add_pbc_item(row.get("title"), row.get("note") or "")
            count += 1
        return count


PBC_HEAD = ["title", "note", "status", "requested", "uploaded", "age", "chased", "file", "paper"]
