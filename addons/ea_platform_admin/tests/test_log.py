import psycopg2

from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import PlatformCase


@tagged("post_install", "-at_install")
class TestPlatformLog(PlatformCase):
    def setUp(self):
        super().setUp()
        self.log = self.env["platform.log"]
        self.row = self.log._record("Essai", detail="premier")
        self.log._record("Essai", detail="second")

    def test_the_model_refuses_changes(self):
        with self.assertRaises(AccessError):
            self.row.write({"action": "autre"})
        with self.assertRaises(AccessError):
            self.row.sudo().write({"action": "autre"})
        with self.assertRaises(AccessError):
            self.row.unlink()
        with self.assertRaises(AccessError):
            self.row.sudo().unlink()

    @mute_logger("odoo.sql_db")
    def test_the_database_refuses_changes_even_in_sql(self):
        self.env.flush_all()
        for statement in (
            "UPDATE platform_log SET action = 'x' WHERE id = %s",
            "DELETE FROM platform_log WHERE id = %s",
        ):
            with self.assertRaisesRegex(psycopg2.Error, "append-only"), self.env.cr.savepoint():
                self.env.cr.execute(statement, [self.row.id])

    @mute_logger("odoo.sql_db")
    def test_the_database_refuses_truncate(self):
        self.env.flush_all()
        with self.assertRaisesRegex(psycopg2.Error, "append-only"), self.env.cr.savepoint():
            self.env.cr.execute("TRUNCATE platform_log CASCADE")

    def test_nobody_has_write_rights(self):
        for user in (self.viewer, self.operator, self.owner):
            with self.assertRaises(AccessError):
                self.log.with_user(user).create({"action": "x", "previous_hash": "0", "entry_hash": "0"})
            self.assertTrue(self.log.with_user(user).search_count([]))

    def test_the_chain_holds(self):
        self.assertFalse(self.log._chain_break())

    def test_a_row_changed_behind_the_triggers_is_found(self):
        self.env.flush_all()
        self.env.cr.execute("ALTER TABLE platform_log DISABLE TRIGGER platform_log_append_only")
        self.env.cr.execute("UPDATE platform_log SET detail = 'falsifié' WHERE id = %s", [self.row.id])
        self.env.cr.execute("ALTER TABLE platform_log ENABLE TRIGGER platform_log_append_only")
        self.env.invalidate_all()
        self.assertEqual(self.log._chain_break(), self.row)

    def test_each_row_names_who_did_it(self):
        row = self.log.with_user(self.operator)._record("Essai opérateur")
        self.assertEqual(row.user_id, self.operator)
