from markupsafe import escape

from odoo import http
from odoo.http import request

from odoo.addons.ea_audit_core.services.errors import AuditRuleError
from odoo.addons.ea_audit_tools.models.tool_record import french_date
from odoo.addons.portal.controllers.portal import CustomerPortal


class PbcPortal(CustomerPortal):
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if "pbc_count" in counters:
            Contact = request.env["ea.audit.portal.contact"].sudo()
            contact = Contact.search([("user_id", "=", request.env.uid)], limit=1)
            values["pbc_count"] = request.env["ea.audit.pbc.item"].sudo().search_count(
                [("client_id", "=", contact.client_id.id), ("status", "=", "requested")]
            ) if contact else 0
        return values

    @http.route("/my/pbc", type="http", auth="user", website=True, methods=["GET"])
    def pbc_list(self, error=None, **_kw):
        """9.1: PBC requests only, never the audit file."""
        Item = request.env["ea.audit.pbc.item"]
        try:
            items = Item.list_portal_items()
        except AuditRuleError:
            return request.redirect("/my")
        company = request.env.company.sudo()
        values = self._prepare_portal_layout_values()
        values.update({
            "items": [{
                "id": item.id, "title": item.title, "note": item.note, "status": item.status,
                "status_label": dict(item._fields["status"]._description_selection(request.env)).get(item.status),
                "client": item.client_id.name, "year": item.fiscal_year, "filename": item.filename,
                "created": french_date(item.create_date), "uploaded": french_date(item.uploaded_at),
            } for item in items],
            "firm_name": company.ea_display_name or company.name,
            "error": error,
            "page_name": "pbc",
        })
        return request.render("ea_audit_portal.portal_pbc_list", values)

    @http.route("/my/pbc/<int:item_id>/upload", type="http", auth="user", website=True, methods=["POST"], csrf=True)
    def pbc_upload(self, item_id, upload=None, **_kw):
        """The rules are the model's. A refusal comes back to the list, in the reader's language."""
        item = request.env["ea.audit.pbc.item"].browse(item_id)
        content = upload.read() if upload else b""
        try:
            item.upload_pbc(upload.filename if upload else "", content)
        except AuditRuleError as refusal:
            return request.redirect("/my/pbc?error=%s" % refusal.code)
        return request.redirect("/my/pbc")


class PortalInvite(http.Controller):
    def _render(self, token, error=None):
        contact = request.env["ea.audit.portal.contact"]._ea_from_token(token)
        company = request.env.company.sudo()
        return request.render("ea_audit_portal.portal_invite", {
            "token": token, "valid": bool(contact), "email": contact.email, "error": error,
            "firm_name": company.ea_display_name or company.name, "no_header": True,
        })

    @http.route("/ea_audit/portal/invite/<string:token>", type="http", auth="public", methods=["GET"], sitemap=False)
    def invite_form(self, token, **_kw):
        response = self._render(token)
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    @http.route("/ea_audit/portal/invite/<string:token>", type="http", auth="public", methods=["POST"], csrf=True, sitemap=False)
    def invite_accept(self, token, password="", confirm="", **_kw):
        """Choose the password. No login is performed here: the contact signs in with it."""
        try:
            contact = request.env["ea.audit.portal.contact"].accept_invite(token, password, confirm)
        except AuditRuleError as refusal:
            return self._render(token, escape(str(refusal.args[0])))
        return request.redirect("/web/login?redirect=/my/pbc&login=%s" % contact.email)
