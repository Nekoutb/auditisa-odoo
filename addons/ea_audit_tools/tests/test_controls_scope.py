"""The controls tasks follow the reliance on controls (owner's ruling of 2026-11-17 evening): on the
file while the strategy relies on controls, off it when it stops (a task holding work stays, marked
not applicable), back with their work when the reliance returns. An archived file is left alone."""
from odoo.tests import tagged

from odoo.addons.ea_audit_core.services.file_scope import CONTROLS_CODES

from .common import ToolsCase

REASON = "The strategy no longer relies on controls"


@tagged("post_install", "-at_install")
class TestControlsScope(ToolsCase):
    def item(self, code):
        return self.env["ea.audit.file.item"].sudo().search(
            [("engagement_id", "=", self.engagement.id), ("code", "=", code)], limit=1,
        )

    def active(self):
        return {code for code in CONTROLS_CODES if not self.item(code).conditional}

    def trail(self, action):
        return self.env["ea.audit.activity"].sudo().search(
            [("engagement_id", "=", self.engagement.id), ("action", "=", action)],
        )

    def scot(self, strategy="controls", name="Ventes"):
        return self.env["ea.audit.scot"].sudo().create(
            {"engagement_id": self.engagement.id, "name": name, "strategy": strategy},
        )

    def sign_off(self, code):
        return self.env["ea.audit.signoff"].sudo().create({
            "file_item_id": self.item(code).id, "kind": "workpaper", "role": "preparer", "user_id": self.senior.id,
        })

    def test_no_reliance_no_controls_task(self):
        self.assertEqual(self.active(), set())
        self.scot(strategy="substantive")
        self.assertEqual(self.active(), set())

    def test_rely_stop_and_rely_again(self):
        scot = self.scot()
        self.assertEqual(self.active(), set(CONTROLS_CODES))
        signoff = self.sign_off("S2.1")
        self.env["ea.audit.review.note"].sudo().create({
            "file_item_id": self.item("S2.2").id, "author_id": self.manager.id, "body": "Which control?",
        })

        scot.write({"strategy": "substantive"})
        # the tasks holding work stay, readable and not applicable; the empty ones leave the file
        self.assertEqual(self.active(), {"S2.1", "S2.2"})
        for code in ("S2.1", "S2.2"):
            item = self.item(code)
            self.assertTrue(item.not_applicable, code)
            self.assertTrue(item.controls_na, code)
            self.assertEqual(item.na_reason, REASON)
            self.assertTrue(item.na_at)
        self.assertTrue(self.item("S2.3").conditional)
        self.assertFalse(self.item("S2.3").not_applicable)
        off = self.trail("tasks_off_by_reliance")
        self.assertEqual(len(off), 1)
        self.assertIn("holding no work: E1.1, E1.2, E2.1, S2.3, S2.4, S2.5", off.summary)
        self.assertIn("Kept as not applicable, holding work: S2.1, S2.2", off.summary)
        self.assertTrue(self.trail("marked_not_applicable"))

        # saving the same strategy again moves nothing more
        scot.write({"strategy": "substantive"})
        self.assertEqual(len(self.trail("tasks_off_by_reliance")), 1)

        scot.write({"strategy": "controls"})
        self.assertEqual(self.active(), set(CONTROLS_CODES))
        for code in ("S2.1", "S2.2"):
            item = self.item(code)
            self.assertFalse(item.not_applicable, code)
            self.assertFalse(item.na_reason, code)
            self.assertFalse(item.controls_na, code)
        self.assertTrue(signoff.exists())
        self.assertIn(signoff, self.item("S2.1").signoff_ids)
        self.assertEqual(len(self.item("S2.2").review_note_ids), 1)
        self.assertIn("work kept: S2.1, S2.2", self.trail("tasks_back_by_reliance").summary)
        self.assertTrue(self.trail("na_cleared"))

    def test_the_tasks_stay_while_another_record_still_relies(self):
        scot = self.scot()
        app = self.env["ea.audit.it.application"].sudo().create({
            "engagement_id": self.engagement.id, "key": "erp", "name": "ERP", "strategy": "rely_itgc",
        })
        scot.write({"strategy": "substantive"})
        self.assertEqual(self.active(), set(CONTROLS_CODES))
        app.write({"removed": True})
        self.assertEqual(self.active(), set())

    def test_deleting_the_relying_class_takes_the_tasks_off(self):
        scot = self.scot()
        self.sign_off("E1.1")
        scot.unlink()
        self.assertEqual(self.active(), {"E1.1"})
        self.assertTrue(self.item("E1.1").not_applicable)

    def test_a_cell_set_to_rely_through_the_board(self):
        self.approve()
        self.engagement.sudo()._ea_sync_cra()
        cell = self.env["ea.audit.cra.assessment"].with_user(self.staff).search([
            ("engagement_id", "=", self.engagement.id), ("index_code", "=", "E"), ("assertion", "=", "C"),
        ])
        cell.write({"cr": "rely", "cr_basis": "IT dependent control tested in E1.2"})
        self.assertEqual(self.active(), set(CONTROLS_CODES))
        # materiality is approved: a revision carries its reason
        cell.write({"cr": "not_rely", "reason": "The controls will not be tested this year"})
        self.assertEqual(self.active(), set())

    def test_a_reviewers_own_not_applicable_is_kept(self):
        scot = self.scot()
        self.sign_off("S2.4")
        self.item("S2.4").with_user(self.manager).set_not_applicable("No IT general controls in this entity")
        scot.write({"strategy": "substantive"})
        scot.write({"strategy": "controls"})
        item = self.item("S2.4")
        self.assertTrue(item.not_applicable)
        self.assertEqual(item.na_reason, "No IT general controls in this entity")
        self.assertFalse(item.controls_na)

    def test_an_archived_file_is_left_alone(self):
        self.scot()
        self.sign_off("S2.1")
        self.engagement.sudo().write({"phase": "archived", "archived_at": "2026-01-01 00:00:00"})
        self.patch(type(self.env["ea.audit.engagement"]), "_ea_relies_on_controls", lambda _self: False)
        self.engagement._ea_follow_controls_reliance()
        self.assertEqual(self.active(), set(CONTROLS_CODES))
        self.assertFalse(self.item("S2.1").not_applicable)
        self.assertFalse(self.trail("tasks_off_by_reliance"))
