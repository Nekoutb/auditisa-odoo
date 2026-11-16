"""Attach a document already in the engagement (owner, 2026-11-16): the picker lists THIS
engagement's live files only, searches them, and attaching one reuses the stored file."""

from odoo.tests import tagged

from .common import PaperCase


@tagged("post_install", "-at_install")
class TestDocumentLibrary(PaperCase):
    def setUp(self):
        super().setUp()
        self.other = self.make_engagement(year=2024)
        self.seat(self.other, self.staff, "staff")
        self.set_phase(self.other, "execution")

    def upload_to(self, engagement, code, name, content):
        import base64

        return self.item(engagement, code).with_user(self.staff).upload_attachment(
            name, base64.b64encode(content).decode(),
        )

    def names(self, engagement, search=None):
        return [row["name"] for row in engagement.with_user(self.staff).ea_document_library(search)]

    def test_another_engagements_files_are_never_listed(self):
        self.upload_to(self.engagement, "P3.1", "ours.txt", b"ours")
        theirs = self.upload_to(self.other, "P3.1", "theirs.txt", b"theirs")
        self.assertEqual(self.names(self.engagement), ["ours.txt"])
        self.assertEqual(self.names(self.other), ["theirs.txt"])
        # nor attached by its id
        target = self.item(self.engagement, "P1.1").with_user(self.staff)
        self.assertCode("not-found", target.attach_existing, [theirs])

    def test_search_filters_and_lists_the_latest_version_only(self):
        self.upload_to(self.engagement, "P3.1", "bank statement.txt", b"v1")
        self.upload_to(self.engagement, "P3.1", "bank statement.txt", b"v2")
        self.upload_to(self.engagement, "P1.1", "letter.txt", b"letter")
        rows = self.engagement.with_user(self.staff).ea_document_library()
        self.assertEqual(sorted((r["name"], r["version"]) for r in rows), [("bank statement.txt", 2), ("letter.txt", 1)])
        self.assertEqual(self.names(self.engagement, "BANK"), ["bank statement.txt"])
        self.assertEqual(self.names(self.engagement, "P1.1"), ["letter.txt"])
        self.assertEqual(self.names(self.engagement, "nothing like it"), [])

    def test_a_removed_file_is_not_offered(self):
        row = self.upload_to(self.engagement, "P3.1", "gone.txt", b"gone")
        self.Attachment.sudo().browse(row).with_user(self.manager).remove()
        self.assertEqual(self.names(self.engagement), [])
        target = self.item(self.engagement, "P1.1").with_user(self.staff)
        self.assertCode("not-found", target.attach_existing, [row])

    def test_attaching_reuses_the_stored_file(self):
        source_id = self.upload_to(self.engagement, "P3.1", "contract.txt", b"the contract")
        target = self.item(self.engagement, "P1.1")
        created = target.with_user(self.staff).attach_existing([source_id])
        source = self.Attachment.sudo().browse(source_id)
        copy = self.Attachment.sudo().browse(created)
        self.assertEqual(len(copy), 1)
        self.assertEqual((copy.file_item_id, copy.name, copy.version), (target, "contract.txt", 1))
        self.assertNotEqual(copy.attachment_id, source.attachment_id)
        self.assertEqual(copy.attachment_id.checksum, source.attachment_id.checksum)
        if source.attachment_id.store_fname:
            self.assertEqual(copy.attachment_id.store_fname, source.attachment_id.store_fname)
        self.assertEqual(copy.attachment_id.raw, b"the contract")
        # the original removed: the attached copy stays readable
        source.with_user(self.manager).remove()
        self.assertEqual(copy.with_user(self.staff).attachment_id.raw, b"the contract")
        bodies = self.engagement.sudo().message_ids.mapped("body")
        self.assertTrue(any("attachment_attached" in b for b in bodies))

    def test_an_outsider_cannot_read_the_library(self):
        self.upload_to(self.engagement, "P3.1", "ours.txt", b"ours")
        with self.assertRaises(Exception):
            self.engagement.with_user(self.outsider).ea_document_library()
