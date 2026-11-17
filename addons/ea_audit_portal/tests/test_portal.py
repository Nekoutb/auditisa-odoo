import re
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import HttpCase, tagged

from odoo.addons.ea_audit_reports.tests.common import ReportsCase

from ..models.pbc import password_problem

CSV = "Compte;Montant\n411;100".encode("utf-8")
GOOD_PASSWORD = "Choisi-Par-Le-Client-2026"


class PortalCase(ReportsCase):
    def setUp(self):
        super().setUp()
        self.client2 = self.env["ea.audit.client"].create({"name": "Other SA"})
        self.contact, self.link = self.client.with_user(self.senior).add_portal_contact("Contact@Client.example.com", "Mme Contact")
        self.portal_user = self.contact.sudo().user_id
        self.token = self.link.rsplit("/", 1)[1]


@tagged("post_install", "-at_install")
class TestContacts(PortalCase):
    """portal.test.ts 9.1."""

    def test_scoped_to_one_client(self):
        self.assertEqual(self.contact.sudo().client_id, self.client)
        self.assertEqual(self.contact.sudo().email, "contact@client.example.com")
        self.assertTrue(self.portal_user.has_group("base.group_portal"))
        self.assertFalse(self.portal_user.has_group("base.group_user"))
        self.assertFalse(self.portal_user._ea_firm_role())

    def test_no_auditor_set_password(self):
        """F069: nobody at the firm knows it, because nobody set it; only a digest of the link is kept."""
        self.env.cr.execute("SELECT password FROM res_users WHERE id = %s", [self.portal_user.id])
        self.assertFalse(self.env.cr.fetchone()[0])
        self.assertTrue(self.contact.sudo().pending)
        self.assertNotIn(self.token, self.contact.sudo().invite_digest)

    def test_no_email_sent(self):
        mails = self.env["mail.mail"].sudo().search_count([])
        self.client2.with_user(self.senior).add_portal_contact("x@client.example.com", "X")
        self.assertEqual(self.env["mail.mail"].sudo().search_count([]), mails)

    def test_refusals(self):
        as_senior = self.client.with_user(self.senior)
        self.assertCode("email-taken", as_senior.add_portal_contact, "contact@client.example.com", "Dup")
        self.assertCode("fields-required", as_senior.add_portal_contact, " ", "x")
        self.assertCode("forbidden", self.client.with_user(self.staff).add_portal_contact, "y@client.example.com", "Y")
        self.assertCode("forbidden", self.client.with_user(self.reader).add_portal_contact, "y@client.example.com", "Y")

    def test_new_link_replaces_the_old(self):
        old = self.token
        link = self.contact.with_user(self.senior).resend_invite()
        self.assertFalse(self.env["ea.audit.portal.contact"]._ea_from_token(old))
        self.assertTrue(self.env["ea.audit.portal.contact"]._ea_from_token(link.rsplit("/", 1)[1]))
        self.assertCode("forbidden", self.contact.with_user(self.staff).resend_invite)

    def test_link_expires(self):
        self.contact.sudo().invite_expires_at = fields.Datetime.now() - timedelta(minutes=1)
        self.assertCode("invalid-or-expired", self.env["ea.audit.portal.contact"].accept_invite, self.token, GOOD_PASSWORD, GOOD_PASSWORD)

    def test_password_policy(self):
        self.assertEqual(password_problem("Court1", "a@b"), "too-short")
        self.assertEqual(password_problem("toutenminuscule1", "a@b"), "needs-mixed-case")
        self.assertEqual(password_problem("SansChiffreDuTout", "a@b"), "needs-digit")
        self.assertEqual(password_problem("Xcontact2026abc", "contact@b"), "contains-email")
        self.assertIsNone(password_problem(GOOD_PASSWORD, "contact@b"))
        accept = self.env["ea.audit.portal.contact"].accept_invite
        self.assertCode("mismatch", accept, self.token, GOOD_PASSWORD, "autre")
        self.assertCode("too-short", accept, self.token, "Court1", "Court1")

    def test_link_works_once_then_active(self):
        accept = self.env["ea.audit.portal.contact"].accept_invite
        accept(self.token, GOOD_PASSWORD, GOOD_PASSWORD)
        self.assertFalse(self.contact.sudo().pending)
        self.assertCode("invalid-or-expired", accept, self.token, GOOD_PASSWORD, GOOD_PASSWORD)
        self.assertCode("already-active", self.contact.with_user(self.senior).resend_invite)


@tagged("post_install", "-at_install")
class TestPbcFlow(PortalCase):
    """portal.test.ts 9.1/9.2: requested, uploaded, accepted and attached."""

    def setUp(self):
        super().setUp()
        self.req = self.as_senior.add_pbc_item("Grand livre 2025", "Format CSV ou Excel.")
        self.as_contact = self.env["ea.audit.pbc.item"].with_user(self.portal_user)

    def test_request_reaches_the_contact(self):
        self.assertTrue(self.env["ea.audit.notice"].sudo().search_count([("user_id", "=", self.portal_user.id), ("kind", "=", "pbc-requested")]))
        items = self.as_contact.list_portal_items()
        self.assertEqual(items, self.req.sudo())
        self.assertEqual(items.status, "requested")
        self.assertEqual(self.engagement.with_user(self.partner).pbc_open_count, 1)

    def test_title_required_and_guards(self):
        self.assertCode("fields-required", self.as_senior.add_pbc_item, " ")
        self.assertCode("read-only-role", self.engagement.with_user(self.reader).add_pbc_item, "x")
        self.assertCode("not-on-this-engagement", self.engagement.with_user(self.outsider).add_pbc_item, "x")
        self.assertCode("eqr-read-only", self.engagement.with_user(self.eqr).add_pbc_item, "x")

    def test_upload_then_accept(self):
        self.req.with_user(self.portal_user).upload_pbc("gl.csv", CSV)
        row = self.req.sudo()
        self.assertEqual((row.status, row.filename, row.mime, row.uploaded_by_id), ("uploaded", "gl.csv", "text/csv", self.portal_user))
        self.assertTrue(self.env["ea.audit.notice"].sudo().search_count([("user_id", "=", self.staff.id), ("kind", "=", "pbc-uploaded")]))
        message = self.env["mail.message"].sudo().search([("model", "=", "ea.audit.engagement"), ("res_id", "=", self.engagement.id)], limit=1, order="id desc")
        self.assertIn("pbc_uploaded", str(message.body))
        task = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.engagement.id), ("code", "=", "E4.1")])
        document = self.req.with_user(self.senior).accept(task.with_user(self.senior))
        self.assertEqual(document.kind, "workpaper")
        self.assertIn("Document request", document.title)
        self.assertEqual(document.code, "E4.1")
        self.assertEqual(document.sudo().current_version_id.attachment_id.raw, CSV)
        self.assertEqual(row.status, "accepted")
        self.assertEqual(row.document_id, document.sudo())
        self.assertEqual(self.engagement.with_user(self.partner).pbc_open_count, 0)
        self.assertCode("wrong-status", self.req.with_user(self.senior).accept, task)
        self.assertCode("not-found", self.req.with_user(self.portal_user).upload_pbc, "gl2.csv", CSV)
        # filed document is a working paper: the task now owes its signatures
        self.assertTrue(next(r for r in self.engagement.sudo()._ea_item_activity() if r["item"] == task)["worked"])

    def test_upload_refusals(self):
        upload = self.req.with_user(self.portal_user).upload_pbc
        self.assertCode("empty-file", upload, "gl.csv", b"")
        self.assertCode("executable-refused", upload, "virus.exe", b"MZ")
        self.assertCode("content-mismatch", upload, "faux.pdf", b"pas un pdf")
        self.assertCode("no-extension", upload, "sansextension", b"abc")
        self.assertCode("file-too-large", upload, "gros.csv", b"a" * (25 * 1024 * 1024 + 1))

    def test_another_clients_contact_cannot_touch_it(self):
        contact, _link = self.client2.with_user(self.senior).add_portal_contact("autre@client.example.com", "Autre")
        other = self.req.with_user(contact.sudo().user_id)
        self.assertCode("not-your-client", other.upload_pbc, "gl.csv", CSV)
        self.assertFalse(self.env["ea.audit.pbc.item"].with_user(contact.sudo().user_id).list_portal_items())
        with self.assertRaises(AccessError):
            other.read(["title"])

    def test_firm_user_is_not_a_portal_user(self):
        self.assertCode("portal-only", self.env["ea.audit.pbc.item"].with_user(self.partner).list_portal_items)
        # the firm records a document received another way, on a file it is seated on (A30)
        self.req.with_user(self.partner).upload_pbc("gl.csv", CSV)
        self.assertEqual(self.req.sudo().status, "uploaded")
        self.assertEqual(self.req.sudo().attachment_id.raw, CSV)

    def test_contact_never_reaches_the_audit_file(self):
        """Spec 2.3: the portal is PBC requests only."""
        user = self.portal_user
        self.assertTrue(self.req.with_user(user).title)
        self.assertCode("not-on-this-engagement", self.engagement.with_user(user).export_engagement_bundle)
        for model, record in (
            ("ea.audit.engagement", self.engagement),
            ("ea.audit.file.item", self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.engagement.id)], limit=1)),
            ("ea.audit.client", self.client),
        ):
            with self.assertRaises(AccessError, msg=model):
                record.with_user(user).read(["id"])
        with self.assertRaises(AccessError):
            self.env["ea.audit.paper"].with_user(user).search([])
        with self.assertRaises(AccessError):
            self.env["ea.audit.document"].with_user(user).search([])

    def test_contact_cannot_write_directly(self):
        self.assertCode("forbidden", self.req.with_user(self.portal_user).write, {"status": "accepted"})
        with self.assertRaises(AccessError):
            self.env["ea.audit.pbc.item"].with_user(self.portal_user).check_access("write")

    def test_team_only_for_the_firm(self):
        self.assertTrue(self.req.with_user(self.reader).title)
        with self.assertRaises(AccessError):
            self.req.with_user(self.outsider).read(["title"])
        with self.assertRaises(AccessError):
            self.req.with_user(self.admin).read(["title"])

    def test_chase(self):
        self.req.with_user(self.staff).chase()
        row = self.req.sudo()
        self.assertEqual(row.chase_count, 1)
        self.assertTrue(row.chased_at)
        self.assertEqual(self.env["ea.audit.notice"].sudo().search_count([("user_id", "=", self.portal_user.id), ("kind", "=", "pbc-reminder")]), 1)
        self.req.with_user(self.portal_user).upload_pbc("gl.csv", CSV)
        self.assertCode("wrong-status", self.req.with_user(self.staff).chase)

    def test_chase_without_a_contact(self):
        """UAT run 2 B76."""
        self.contact.sudo().unlink()
        self.assertCode("no-portal-contact", self.req.with_user(self.staff).chase)
        self.assertEqual(self.req.sudo().chase_count, 0)

    def test_accept_needs_a_reviewer_and_a_task(self):
        self.req.with_user(self.portal_user).upload_pbc("gl.csv", CSV)
        task = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.engagement.id), ("code", "=", "E4.1")])
        self.assertCode("forbidden", self.req.with_user(self.staff).accept, task)
        self.assertCode("attach-required", self.req.with_user(self.senior).accept, self.env["ea.audit.file.item"])
        other = self.make_engagement(year=2026)
        foreign = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", other.id), ("code", "=", "E4.1")])
        self.assertCode("not-found", self.req.with_user(self.senior).accept, foreign)

    def test_attach_accepted_late(self):
        self.req.with_user(self.portal_user).upload_pbc("gl.csv", CSV)
        self.req.sudo().write({"status": "accepted"})
        task = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.engagement.id), ("code", "=", "E4.1")])
        document = self.req.with_user(self.senior).attach_accepted(task)
        self.assertEqual(self.req.sudo().document_id, document.sudo())
        self.assertCode("wrong-status", self.req.with_user(self.senior).attach_accepted, task)

    def test_archived_file_is_closed_to_the_portal(self):
        self.engagement.sudo().write({"phase": "archived"})
        self.assertCode("archived", self.req.with_user(self.portal_user).upload_pbc, "gl.csv", CSV)
        self.assertCode("archived", self.as_senior.add_pbc_item, "x")


@tagged("post_install", "-at_install")
class TestInviteOverHttp(HttpCase):
    """The whole flow with mail off: the auditor gets a link, the contact opens it, chooses a password,
    signs in and uploads. No screen at the firm ever held the password."""

    def setUp(self):
        super().setUp()
        self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Sen", "login": "sen@flow.example.com", "email": "sen@flow.example.com",
            "group_ids": [(6, 0, [self.env.ref("ea_audit_core.group_senior").id])],
        })
        self.senior = self.env["res.users"].search([("login", "=", "sen@flow.example.com")])
        self.partner_user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Par", "login": "par@flow.example.com", "email": "par@flow.example.com",
            "group_ids": [(6, 0, [self.env.ref("ea_audit_core.group_partner").id])],
        })
        self.client_row = self.env["ea.audit.client"].create({"name": "Flux SA", "legal_form": "SA"})
        self.engagement = self.env["ea.audit.engagement"].with_user(self.partner_user).create({
            "client_id": self.client_row.id, "fiscal_year": 2025, "period_end": "2025-12-31",
            "engagement_partner_id": self.partner_user.id,
        })
        self.req = self.engagement.with_user(self.partner_user).add_pbc_item("Grand livre", "CSV")
        self.contact, self.link = self.client_row.with_user(self.senior).add_portal_contact("flux@client.example.com", "Flux")
        self.path = "/" + self.link.split("/", 3)[3]

    def _csrf(self, html):
        return re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1)

    def test_the_flow(self):
        mails = self.env["mail.mail"].sudo().search_count([])
        page = self.url_open(self.path)
        self.assertEqual(page.status_code, 200)
        self.assertIn("flux@client.example.com", page.text)
        self.assertEqual(page.headers.get("Referrer-Policy"), "no-referrer")
        token = self._csrf(page.text)
        # a refused password stays on the form, and the link still works
        refused = self.url_open(self.path, data={"csrf_token": token, "password": "court", "confirm": "court"}, allow_redirects=False)
        self.assertEqual(refused.status_code, 200)
        accepted = self.url_open(self.path, data={"csrf_token": token, "password": GOOD_PASSWORD, "confirm": GOOD_PASSWORD}, allow_redirects=False)
        self.assertEqual(accepted.status_code, 303)
        self.assertIn("/web/login", accepted.headers["Location"])
        self.assertNotIn('name="password"', self.url_open(self.path).text)
        self.authenticate("flux@client.example.com", GOOD_PASSWORD)
        listing = self.url_open("/my/pbc")
        self.assertEqual(listing.status_code, 200)
        self.assertIn("Grand livre", listing.text)
        token = self._csrf(listing.text)
        upload = "/my/pbc/%d/upload" % self.req.id
        done = self.url_open(upload, data={"csrf_token": token}, files={"upload": ("gl.csv", CSV, "text/csv")}, allow_redirects=False)
        self.assertEqual(done.status_code, 303)
        self.env.invalidate_all()
        self.assertEqual(self.req.sudo().status, "uploaded")
        self.assertEqual(self.req.sudo().attachment_id.raw, CSV)
        refused = self.url_open(upload, data={"csrf_token": token}, files={"upload": ("x.exe", b"MZ", "application/octet-stream")}, allow_redirects=False)
        self.assertIn("error=executable-refused", refused.headers["Location"])
        self.assertEqual(self.url_open("/my/pbc?error=executable-refused").status_code, 200)
        self.assertEqual(self.env["mail.mail"].sudo().search_count([]), mails)

    def test_a_bad_token_says_so_and_nothing_else(self):
        page = self.url_open("/ea_audit/portal/invite/nimportequoi")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('name="password"', page.text)

    def test_a_firm_user_on_my_pbc_is_sent_home(self):
        self.partner_user.password = GOOD_PASSWORD
        self.authenticate("par@flow.example.com", GOOD_PASSWORD)
        response = self.url_open("/my/pbc", allow_redirects=False)
        self.assertEqual(response.status_code, 303)

@tagged("post_install", "-at_install")
class TestNoPublicSignup(HttpCase):
    def test_nobody_signs_up_uninvited(self):
        scope = self.env["ir.config_parameter"].sudo().get_param("auth_signup.invitation_scope")
        self.assertEqual(scope, "b2b")
        self.assertEqual(self.url_open("/web/signup", allow_redirects=False).status_code, 404)
