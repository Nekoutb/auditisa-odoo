from datetime import timedelta

import psycopg2

from odoo import fields
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import ReportsCase


@tagged("post_install", "-at_install")
class TestRetentionPeriod(ReportsCase):
    """retention.test.ts."""

    def test_defaults_to_ten_years(self):
        self.assertEqual(self.env.company.ea_retention_years, 10)

    def test_range(self):
        Engagement = self.env["ea.audit.engagement"].with_user(self.admin)
        for years in (3, 9, 31):
            self.assertCode("retention-out-of-range", Engagement.set_retention_years, years)
        self.assertEqual(Engagement.set_retention_years(12), 12)
        self.assertEqual(self.env.company.ea_retention_years, 12)

    def test_firm_admin_only(self):
        self.assertCode("requires-firm-admin", self.env["ea.audit.engagement"].with_user(self.manager).set_retention_years, 12)
        self.assertCode("requires-firm-admin", self.env["ea.audit.engagement"].with_user(self.partner).set_retention_years, 12)


@tagged("post_install", "-at_install")
class TestLegalHold(ReportsCase):
    def test_manager_places(self):
        self.as_manager.place_legal_hold("Client dispute, letter of 20 August")
        hold = self.as_partner.active_hold()
        self.assertIn("Client dispute", hold.reason)
        self.assertFalse(hold.released_at)
        self.assertTrue(self.engagement.with_user(self.partner).held)

    def test_staff_cannot(self):
        self.assertCode("requires-manager", self.as_staff.place_legal_hold, "reason")
        self.assertCode("read-only-role", self.engagement.with_user(self.reader).place_legal_hold, "reason")

    def test_reason_required(self):
        self.assertCode("reason-required", self.as_manager.place_legal_hold, "   ")

    def test_no_second_active_hold(self):
        self.as_manager.place_legal_hold("First")
        self.assertCode("already-held", self.as_manager.place_legal_hold, "Second")

    def test_release_by_a_partner_with_a_reason(self):
        self.as_manager.place_legal_hold("Dispute")
        self.assertCode("requires-partner", self.as_manager.release_legal_hold, "done")
        self.assertCode("reason-required", self.as_partner.release_legal_hold, "  ")
        self.as_partner.release_legal_hold("Matter settled")
        self.assertFalse(self.as_partner.active_hold())

    def test_released_stays_as_history(self):
        """UAT run 2 B158."""
        self.as_manager.place_legal_hold("Dispute")
        self.as_partner.release_legal_hold("Settled")
        holds = self.as_partner.list_holds()
        self.assertEqual(len(holds), 1)
        self.assertTrue(holds.released_at)
        self.assertEqual(holds.release_reason, "Settled")
        self.assertEqual(holds.placed_by_id, self.manager)
        self.assertEqual(holds.released_by_id, self.partner)

    def test_nothing_to_release(self):
        self.assertCode("no-active-hold", self.as_partner.release_legal_hold, "nothing")

    def test_trail_carries_the_reason(self):
        self.as_manager.place_legal_hold("Dispute grave")
        message = self.env["mail.message"].sudo().search([("model", "=", "ea.audit.engagement"), ("res_id", "=", self.engagement.id)], limit=1, order="id desc")
        self.assertIn("Dispute grave", str(message.body))

    def test_a_held_file_is_not_destroyed(self):
        self.as_manager.place_legal_hold("Litigation")
        self.assertCode("legal-hold", self.engagement.sudo().unlink)

    @mute_logger("odoo.sql_db")
    def test_the_guarantee_is_in_the_database(self):
        """Even as the table owner: the trigger refuses, whoever is connected."""
        hold = self.as_manager.place_legal_hold("Litigation")
        self.env.flush_all()
        with self.assertRaises(psycopg2.errors.RaiseException) as caught, self.cr.savepoint():
            self.cr.execute("DELETE FROM ea_audit_engagement WHERE id = %s", [self.engagement.id])
        self.assertIn("legal-hold", str(caught.exception))
        with self.assertRaises(psycopg2.errors.RaiseException), self.cr.savepoint():
            self.cr.execute("DELETE FROM ea_audit_legal_hold WHERE id = %s", [hold.id])
        with self.assertRaises(psycopg2.errors.RaiseException), self.cr.savepoint():
            self.cr.execute("UPDATE ea_audit_legal_hold SET reason = 'x' WHERE id = %s", [hold.id])

    @mute_logger("odoo.sql_db")
    def test_a_released_hold_cannot_be_rewritten(self):
        hold = self.as_manager.place_legal_hold("Dispute")
        self.as_partner.release_legal_hold("Settled")
        self.env.flush_all()
        with self.assertRaises(psycopg2.errors.RaiseException), self.cr.savepoint():
            self.cr.execute("UPDATE ea_audit_legal_hold SET released_at = NULL WHERE id = %s", [hold.id])

    def test_hold_on_an_archived_file(self):
        self.engagement.sudo().write({"phase": "archived", "archived_at": fields.Datetime.now()})
        self.assertEqual(self.attempt(self.as_manager.place_legal_hold, "After closing"), "ok")


@tagged("post_install", "-at_install")
class TestRetentionReport(ReportsCase):
    def _close(self, until):
        self.env.flush_all()
        self.env.cr.execute(
            "UPDATE ea_audit_engagement SET archived_at = now(), phase = 'archived', retention_until = %s WHERE id = %s",
            [until, self.engagement.id],
        )
        self.env.invalidate_all()

    def _row(self):
        rows = self.env["ea.audit.engagement"].with_user(self.manager).retention_report()
        return next(row for row in rows if row["engagement_id"] == self.engagement.id)

    def test_manager_and_above(self):
        self.assertCode("requires-manager", self.env["ea.audit.engagement"].with_user(self.senior).retention_report)

    def test_due_unless_held(self):
        today = fields.Date.context_today(self.env.user)
        self._close(today - timedelta(days=1))
        self.assertTrue(self._row()["due_for_destruction"])
        self.assertEqual(self._row()["retention_until"], (today - timedelta(days=1)).strftime("%d/%m/%Y"))
        self.as_manager.place_legal_hold("Dispute")
        row = self._row()
        self.assertTrue(row["held"])
        self.assertFalse(row["due_for_destruction"])

    def test_not_yet_due(self):
        self._close(fields.Date.context_today(self.env.user) + timedelta(days=30))
        self.assertFalse(self._row()["due_for_destruction"])
