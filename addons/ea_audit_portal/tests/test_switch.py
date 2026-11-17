"""Owner ruling 2026-11-17: document requests are switched off for now and come back later. One
system parameter (ea_audit_portal.document_requests, off by default). While it is off every way in
is hidden or refused and the client's pages answer 404; nothing is deleted, and switching it on
brings everything back as it was."""
from lxml import etree

from odoo.tests import HttpCase, tagged

from odoo.addons.ea_audit_tools.services.document_requests import PARAM

from .test_portal import CSV, GOOD_PASSWORD, PortalCase, switch_document_requests


def _invisible(arch, xpath):
    nodes = etree.fromstring(arch).xpath(xpath)
    assert nodes, xpath
    return [node.get("invisible") or "" for node in nodes]


@tagged("post_install", "-at_install")
class TestSwitchedOff(PortalCase):
    def setUp(self):
        super().setUp()
        self.req = self.as_senior.add_pbc_item("Grand livre 2025", "Format CSV ou Excel.")
        switch_document_requests(self.env, False)
        self.engagement.invalidate_recordset(["document_requests_enabled"])
        self.client.invalidate_recordset(["document_requests_enabled"])

    def test_off_unless_the_firm_turns_it_on(self):
        self.env["ir.config_parameter"].sudo().search([("key", "=", PARAM)]).unlink()
        self.assertFalse(self.engagement.with_user(self.senior).document_requests_enabled)
        self.assertCode("document-requests-off", self.as_senior.add_pbc_item, "Balance")

    def test_the_buttons_and_the_contacts_panel_are_hidden(self):
        self.assertFalse(self.engagement.with_user(self.senior).document_requests_enabled)
        self.assertFalse(self.client.with_user(self.senior).document_requests_enabled)
        engagement_form = self.env["ea.audit.engagement"].with_user(self.senior).get_view(
            self.env.ref("ea_audit_core.view_engagement_form").id, "form")["arch"]
        for button in ("action_view_pbc", "action_open_pbc_request"):
            for invisible in _invisible(engagement_form, "//button[@name='%s']" % button):
                self.assertIn("not document_requests_enabled", invisible, button)
        client_form = self.env["ea.audit.client"].with_user(self.senior).get_view(
            self.env.ref("ea_audit_core.view_client_form").id, "form")["arch"]
        panel = "//button[@name='action_add_portal_contact']/ancestor::div[contains(@class, 'o_ea_panel')][1]"
        self.assertEqual(_invisible(client_form, panel), ["not document_requests_enabled"])

    def test_every_way_in_is_refused(self):
        as_senior = self.engagement.with_user(self.senior)
        self.assertCode("document-requests-off", as_senior.add_pbc_item, "Balance")
        self.assertCode("document-requests-off", as_senior.action_view_pbc)
        self.assertCode("document-requests-off", as_senior.action_open_pbc_request)
        self.assertCode("document-requests-off", as_senior.add_portal_contact, "Autre", "autre@client.example.com")
        client = self.client.with_user(self.senior)
        self.assertCode("document-requests-off", client.add_portal_contact, "autre@client.example.com", "Autre")
        self.assertCode("document-requests-off", client.action_add_portal_contact)
        self.assertCode("document-requests-off", self.contact.with_user(self.senior).resend_invite)
        self.assertCode("document-requests-off", self.req.with_user(self.portal_user).upload_pbc, "gl.csv", CSV)
        self.assertCode("document-requests-off", self.req.with_user(self.senior).chase)
        self.assertCode("document-requests-off", self.req.with_user(self.senior).action_open_accept)
        task = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.engagement.id)], limit=1)
        self.assertCode("document-requests-off", self.req.with_user(self.senior).accept, task)

    def test_what_exists_is_kept(self):
        row = self.req.sudo()
        self.assertEqual((row.title, row.status), ("Grand livre 2025", "requested"))
        self.assertTrue(self.contact.sudo().exists())
        self.assertEqual(self.engagement.sudo().pbc_open_count, 1)

    def test_switching_on_brings_it_back(self):
        switch_document_requests(self.env, True)
        self.engagement.invalidate_recordset(["document_requests_enabled"])
        as_senior = self.engagement.with_user(self.senior)
        self.assertTrue(as_senior.document_requests_enabled)
        self.assertEqual(as_senior.action_view_pbc()["type"], "ir.actions.act_window")
        as_senior.add_pbc_item("Balance")
        self.req.with_user(self.portal_user).upload_pbc("gl.csv", CSV)
        self.assertEqual(self.req.sudo().status, "uploaded")


@tagged("post_install", "-at_install")
class TestPortalClosedOverHttp(HttpCase):
    def setUp(self):
        super().setUp()
        switch_document_requests(self.env, True)
        senior = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Sen", "login": "sen@closed.example.com", "email": "sen@closed.example.com",
            "group_ids": [(6, 0, [self.env.ref("ea_audit_core.group_senior").id])],
        })
        partner = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Par", "login": "par@closed.example.com", "email": "par@closed.example.com",
            "group_ids": [(6, 0, [self.env.ref("ea_audit_core.group_partner").id])],
        })
        client = self.env["ea.audit.client"].create({"name": "Ferme SA", "legal_form": "SA"})
        engagement = self.env["ea.audit.engagement"].with_user(partner).create({
            "client_id": client.id, "fiscal_year": 2025, "period_end": "2025-12-31", "engagement_partner_id": partner.id,
        })
        engagement.with_user(partner).add_pbc_item("Grand livre", "CSV")
        _contact, link = client.with_user(senior).add_portal_contact("ferme@client.example.com", "Ferme")
        self.token = link.rsplit("/", 1)[1]
        self.env["ea.audit.portal.contact"].accept_invite(self.token, GOOD_PASSWORD, GOOD_PASSWORD)
        _contact2, link2 = client.with_user(senior).add_portal_contact("ferme2@client.example.com", "Ferme 2")
        self.pending_path = "/" + link2.split("/", 3)[3]

    def test_the_client_pages_are_closed_then_open_again(self):
        self.authenticate("ferme@client.example.com", GOOD_PASSWORD)
        switch_document_requests(self.env, False)
        self.assertEqual(self.url_open("/my/pbc", allow_redirects=False).status_code, 404)
        self.assertNotIn("/my/pbc", self.url_open("/my").text)
        self.assertEqual(self.url_open(self.pending_path, allow_redirects=False).status_code, 404)
        switch_document_requests(self.env, True)
        listing = self.url_open("/my/pbc")
        self.assertEqual(listing.status_code, 200)
        self.assertIn("Grand livre", listing.text)
        self.assertIn("/my/pbc", self.url_open("/my").text)
        self.assertEqual(self.url_open(self.pending_path, allow_redirects=False).status_code, 200)
