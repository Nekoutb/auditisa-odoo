import base64
import hashlib
import secrets
from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.ea_audit_core.services.signoff_rules import can_review
from odoo.addons.ea_audit_papers.services.upload_safety import UnsafeFile, check_upload

from ..rules import rule_error

MAX_PBC_BYTES = 25 * 1024 * 1024
INVITE_TTL_DAYS = 14
MIN_PASSWORD_LENGTH = 12
STATUS_SELECTION = [("requested", "Requested"), ("uploaded", "Uploaded"), ("accepted", "Accepted")]


def _digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def password_problem(password, email):
    """lib/password-policy.ts: a code, or None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return "too-short"
    if password == password.lower() or password == password.upper():
        return "needs-mixed-case"
    if not any(char.isdigit() for char in password):
        return "needs-digit"
    local = (email or "").split("@")[0].lower()
    if len(local) > 2 and local in password.lower():
        return "contains-email"
    return None


class PortalContact(models.Model):
    """A client's portal user: one account scoped to ONE client, never the audit file. The auditor
    never sets or sees the password (F069): the account starts with none and the contact chooses
    theirs from a one-time link. Only the link's digest is stored."""

    _inherit = "ea.audit.portal.contact"
    _order = "email"
    _rec_name = "email"

    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade", readonly=True)
    email = fields.Char(required=True, readonly=True)
    pending = fields.Boolean(default=True, readonly=True, help="The contact has not chosen a password yet.")
    invite_digest = fields.Char(readonly=True, copy=False, groups="base.group_system")
    invite_expires_at = fields.Datetime(readonly=True, copy=False)

    _user_uniq = models.Constraint("UNIQUE(user_id)", "A portal account belongs to one client.")

    def _ea_new_link(self):
        """A fresh one-time link. The previous one stops working as soon as this one is issued."""
        self.ensure_one()
        token = secrets.token_urlsafe(32)
        self.sudo().write({
            "invite_digest": _digest(token),
            "invite_expires_at": fields.Datetime.now() + timedelta(days=INVITE_TTL_DAYS),
        })
        return "%s/ea_audit/portal/invite/%s" % (self.get_base_url(), token)

    def resend_invite(self):
        """Senior and above; refused once the contact has chosen a password."""
        self.ensure_one()
        self.env["ea.audit.client"]._ea_require_contact_manager()
        if not self.sudo().pending:
            raise rule_error(self.env, "already-active")
        return self._ea_new_link()

    def action_new_link(self):
        self.ensure_one()
        return self.client_id._ea_show_link(self, self.resend_invite())

    @api.model
    def _ea_from_token(self, token):
        """The live contact of a link. One answer for expired, spent and never-existed alike."""
        contact = self.sudo().search([("invite_digest", "=", _digest(token or ""))], limit=1)
        if contact and contact.invite_expires_at and contact.invite_expires_at > fields.Datetime.now():
            return contact
        return self.sudo().browse()

    @api.model
    def accept_invite(self, token, password, confirm):
        """acceptInvite: the link is claimed before the password is written, in one row lock, so
        two submissions racing each other cannot both win."""
        contact = self._ea_from_token(token)
        if not contact:
            raise rule_error(self.env, "invalid-or-expired")
        if password != confirm:
            raise rule_error(self.env, "mismatch")
        problem = password_problem(password or "", contact.email)
        if problem:
            raise rule_error(self.env, problem)
        self.env.cr.execute(
            "UPDATE ea_audit_portal_contact SET invite_digest = NULL, pending = FALSE WHERE id = %s AND invite_digest = %s",
            [contact.id, _digest(token)],
        )
        if not self.env.cr.rowcount:
            raise rule_error(self.env, "invalid-or-expired")
        contact.invalidate_recordset()
        contact.user_id.sudo().with_context(ea_portal_first_password=True).write({"password": password})
        return contact


class ResUsers(models.Model):
    _inherit = "res.users"

    def _notify_security_setting_update(self, subject, content, mail_values=None, **kwargs):
        """Choosing the first password from the invitation is no change to warn about, and nothing
        goes out by email from here. Later changes of password keep Odoo's alert."""
        if self.env.context.get("ea_portal_first_password"):
            return None
        return super()._notify_security_setting_update(subject, content, mail_values=mail_values, **kwargs)


class Client(models.Model):
    _inherit = "ea.audit.client"

    portal_contact_ids = fields.One2many("ea.audit.portal.contact", "client_id", string="Portal contacts")

    @api.model
    def _ea_require_contact_manager(self):
        """I-9: the form and the method agree, senior and above."""
        if not can_review(self.env.user._ea_firm_role()):
            raise rule_error(self.env, "forbidden")

    def add_portal_contact(self, email, name):
        """addPortalContact: (contact, link). No email goes out here: the link is handed to the
        caller, who passes it on until the firm turns mail on."""
        self.ensure_one()
        self._ea_require_contact_manager()
        email = (email or "").strip().lower()
        name = (name or "").strip()
        if not email or not name:
            raise rule_error(self.env, "fields-required")
        Users = self.env["res.users"].sudo().with_context(active_test=False, no_reset_password=True)
        if Users.search_count([("login", "=ilike", email)]):
            raise rule_error(self.env, "email-taken")
        partner = self.env["res.partner"].sudo().create({
            "name": name, "email": email, "parent_id": self.sudo().partner_id.id, "type": "contact",
            "lang": self.env.company.partner_id.lang,
        })
        user = Users.create({
            "name": name, "login": email, "email": email, "partner_id": partner.id,
            "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
        })
        contact = self.env["ea.audit.portal.contact"].sudo().create({"client_id": self.id, "user_id": user.id, "email": email, "name": name})
        return contact.with_env(self.env), contact._ea_new_link()

    def _ea_show_link(self, contact, link):
        return {
            "type": "ir.actions.act_window", "res_model": "ea.audit.portal.contact.wizard", "view_mode": "form", "views": [(False, "form")], "target": "new",
            "name": self.env._("Invitation link"),
            "context": {"default_client_id": self.id, "default_contact_id": contact.id, "default_invite_link": link},
        }

    def action_add_portal_contact(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "ea.audit.portal.contact.wizard", "view_mode": "form", "views": [(False, "form")], "target": "new",
            "name": self.env._("New portal contact"), "context": {"default_client_id": self.id},
        }


class PbcItem(models.Model):
    """The firm's request lives in ea_audit_tools. Here: what the client's contact reads and uploads,
    and the versioned document an accepted upload becomes."""

    _inherit = "ea.audit.pbc.item"

    client_id = fields.Many2one(related="engagement_id.client_id", store=True, index=True, string="Client")
    fiscal_year = fields.Integer(related="engagement_id.fiscal_year", store=True)
    attachment_id = fields.Many2one("ir.attachment", string="Upload", ondelete="restrict", readonly=True)
    document_id = fields.Many2one("ea.audit.document", ondelete="set null", readonly=True)
    filed_code = fields.Char(related="document_id.code", string="Filed under")

    # -- portal side -------------------------------------------------------------------

    @api.model
    def _ea_contact(self):
        """requirePortalUser: the caller's client comes from the session, never from an argument."""
        contact = self.env["ea.audit.portal.contact"].sudo().search([("user_id", "=", self.env.uid)], limit=1)
        if not contact:
            raise rule_error(self.env, "portal-only")
        return contact

    @api.model
    def list_portal_items(self):
        """Requests across the client's engagements."""
        contact = self._ea_contact()
        return self.sudo().search([("client_id", "=", contact.client_id.id)])

    def upload_pbc(self, filename, content):
        """uploadPbc: the same allowlist and byte-signature check as a task attachment; the stored
        name and MIME come from what the bytes are, never from the client's claim. A member of the
        firm records a document received another way through the tools' half (A30), and its bytes end
        up in the same place."""
        self.ensure_one()
        if self.env.user.has_group("ea_audit_core.group_member"):
            result = super().upload_pbc(filename, content)
            row = self.sudo()
            row.attachment_id = self.env["ir.attachment"].sudo().create({
                "name": row.filename, "raw": content, "mimetype": row.mime, "res_model": self._name, "res_id": row.id,
            })
            return result
        contact = self._ea_contact()
        row = self.sudo()
        if not row.exists() or row.client_id != contact.client_id:
            raise rule_error(self.env, "not-your-client")
        if not content:
            raise rule_error(self.env, "empty-file")
        if len(content) > MAX_PBC_BYTES:
            raise rule_error(self.env, "file-too-large")
        try:
            name, mime, _ext = check_upload(filename, content)
        except UnsafeFile as error:
            raise rule_error(self.env, error.code) from None
        row.engagement_id._ea_assert_mutable()
        if row.status == "accepted":
            raise rule_error(self.env, "not-found")
        attachment = self.env["ir.attachment"].sudo().create({
            "name": name, "datas": base64.b64encode(content), "mimetype": mime, "res_model": self._name, "res_id": row.id,
        })
        row.write({
            "status": "uploaded", "filename": name, "mime": mime, "attachment_id": attachment.id,
            "uploaded_by_id": self.env.uid, "uploaded_at": fields.Datetime.now(),
        })
        engagement = row.engagement_id
        engagement._ea_log("pbc_uploaded", "PBC uploaded by the client: %s (%s) sha256 %s" % (row.title, name, hashlib.sha256(content).hexdigest()))
        members = self.env["ea.audit.team.member"].sudo().search([("engagement_id", "=", engagement.id)]).user_id
        engagement._ea_notify(members, "pbc-uploaded", lambda env: env._("Requested document received: %(name)s", name=name))
        return True

    # -- firm side ---------------------------------------------------------------------

    def _ea_contacts_of_client(self):
        self.ensure_one()
        return self.env["ea.audit.portal.contact"].sudo().search([("client_id", "=", self.sudo().client_id.id)]).user_id

    def chase(self):
        """chasePbc (UAT B112): a reminder nobody can receive is not a chase (UAT run 2 B76)."""
        self.ensure_one()
        self._ea_guard()
        row = self.sudo()
        users = row._ea_contacts_of_client()
        if not users:
            raise rule_error(self.env, "no-portal-contact")
        if row.status != "requested":
            raise rule_error(self.env, "wrong-status")
        row.write({"chased_at": fields.Datetime.now(), "chase_count": row.chase_count + 1})
        row.engagement_id._ea_log("pbc_chased", "PBC chased: %s" % row.title)
        row.engagement_id._ea_notify(users, "pbc-reminder", lambda env: env._("Reminder — %(title)s", title=row.title), row.note or (lambda env: env._("This document is still expected: please upload it to the portal.")))
        return True

    def _ea_review_guard(self, item):
        self.ensure_one()
        self._ea_guard()
        if not can_review(self.env.user._ea_firm_role()):
            raise rule_error(self.env, "forbidden")
        if not item:
            raise rule_error(self.env, "attach-required")
        if item.sudo().engagement_id != self.sudo().engagement_id:
            raise rule_error(self.env, "not-found")

    def _ea_file(self, item):
        """filePbcAsDocument: the bytes are checked again on the way into the audit file."""
        row = self.sudo()
        content = row.attachment_id.raw or b""
        try:
            name, mime, _ext = check_upload(row.filename or row.title, content)
        except UnsafeFile as error:
            raise rule_error(self.env, error.code) from None
        Document = self.env["ea.audit.document"].sudo()
        title = "Document request — %s" % row.title
        document = Document.search([("file_item_id", "=", item.id), ("kind", "=", "workpaper"), ("title", "=", title)], limit=1)
        if not document:
            document = Document.create({
                "engagement_id": row.engagement_id.id, "file_item_id": item.id, "title": title, "kind": "workpaper",
                "created_by_id": self.env.user.id,
            })
        document._ea_add_version(content, mime, "pbc:%s" % name, filename=name)
        return document

    def accept(self, file_item):
        """acceptPbc, reviewer and above: an accepted upload attached nowhere was unreachable, so
        the task is required. Becomes a versioned working-paper document."""
        self._ea_review_guard(file_item)
        self.env.flush_all()
        self.env.cr.execute("SELECT status FROM ea_audit_pbc_item WHERE id = %s FOR UPDATE", [self.id])
        row = self.sudo()
        if row.status != "uploaded" or not row.attachment_id:
            raise rule_error(self.env, "wrong-status")
        document = self._ea_file(file_item.sudo())
        row.write({
            "status": "accepted", "accepted_by_id": self.env.user.id, "accepted_at": fields.Datetime.now(),
            "document_id": document.id, "file_item_id": file_item.id,
        })
        row.engagement_id._ea_log("pbc_accepted", "PBC accepted: %s → %s" % (row.title, file_item.sudo().code))
        return document

    def attach_accepted(self, file_item):
        """An item accepted before the task became mandatory: its bytes are still on the row."""
        self._ea_review_guard(file_item)
        row = self.sudo()
        if row.status != "accepted" or row.document_id or not row.attachment_id:
            raise rule_error(self.env, "wrong-status")
        document = self._ea_file(file_item.sudo())
        row.write({"document_id": document.id, "file_item_id": file_item.id})
        row.engagement_id._ea_log("pbc_attached", "PBC filed: %s → %s" % (row.title, file_item.sudo().code))
        return document

    def action_open_accept(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "ea.audit.portal.pbc.wizard", "view_mode": "form", "views": [(False, "form")], "target": "new",
            "name": self.env._("Accept and file the upload"),
            "context": {"default_engagement_id": self.sudo().engagement_id.id, "default_item_id": self.id},
        }

    def action_download(self):
        self.ensure_one()
        self.sudo().engagement_id.with_env(self.env)._ea_require_access()
        return {"type": "ir.actions.act_url", "target": "self", "url": "/web/content/%d?download=true" % self.sudo().attachment_id.id}


class Engagement(models.Model):
    _inherit = "ea.audit.engagement"

    pbc_item_ids = fields.One2many("ea.audit.pbc.item", "engagement_id", string="Client-provided documents")

    def add_portal_contact(self, name, email):
        """The account and its invitation: see Client.add_portal_contact, which returns the link."""
        self.ensure_one()
        self._ea_tool_guard()
        return self.sudo().client_id.with_env(self.env).add_portal_contact(email, name)[0]

    pbc_open_count = fields.Integer(string="Open requests", compute="_compute_pbc_open", compute_sudo=True)

    def _compute_pbc_open(self):
        for engagement in self:
            engagement.pbc_open_count = len(engagement.pbc_item_ids.filtered(lambda item: item.status != "accepted"))

    def add_pbc_item(self, title, note=""):
        """addPbcItem: the request goes on the trail (UAT run 2 B74) and the contacts see it."""
        self.ensure_one()
        self._ea_tool_guard()
        title = (title or "").strip()
        if not title:
            raise rule_error(self.env, "fields-required")
        item = self.env["ea.audit.pbc.item"].sudo().create({"engagement_id": self.id, "title": title, "note": note or ""})
        users = item._ea_contacts_of_client()
        self._ea_log("pbc_requested", "PBC requested: %s (%d contact(s))" % (title, len(users)))
        self.sudo()._ea_notify(users, "pbc-requested", lambda env: env._("Document requested: %(title)s", title=title), note or (lambda env: env._("Please upload this document to the portal.")))
        return item

    def action_view_pbc(self):
        self.ensure_one()
        return self._ea_list(
            "ea.audit.pbc.item", self.env._("Client-provided documents"),
            [("ea_audit_portal.view_pbc_item_list", "list"), ("ea_audit_portal.view_pbc_item_form", "form")],
        )

    def action_open_pbc_request(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "ea.audit.portal.pbc.wizard", "view_mode": "form", "views": [(False, "form")], "target": "new",
            "name": self.env._("New request"), "context": {"default_engagement_id": self.id},
        }

    def _ea_manifest_extra(self):
        extra = super()._ea_manifest_extra()
        extra["pbcItems"] = [
            {"title": item.title, "status": item.status, "filename": item.filename or None, "documentId": item.document_id.id or None}
            for item in self.pbc_item_ids
        ]
        return extra
