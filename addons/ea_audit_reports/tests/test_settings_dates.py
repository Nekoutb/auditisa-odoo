"""F073: the settings page shows what the conclusion holds, read-only, with its link."""
from datetime import date

from lxml import etree

from odoo.tests import tagged

from odoo.addons.ea_audit_core.tests.common import EaAuditCase


@tagged("post_install", "-at_install")
class TestSettingsDates(EaAuditCase):
    def test_f073_report_date_deadline_and_lock(self):
        engagement = self.make_engagement(2025).sudo()
        self.assertEqual(engagement.lock_status, "Open")
        self.assertFalse(engagement.assembly_deadline)
        engagement.report_date = date(2026, 3, 31)
        engagement.invalidate_recordset(["assembly_deadline"])
        self.assertEqual(engagement.assembly_deadline, date(2026, 5, 30))  # 60 days (ISA 230)
        engagement.phase = "archived"
        engagement.invalidate_recordset(["lock_status"])
        self.assertEqual(engagement.lock_status, "Locked: archived")

    def test_f073_the_block_is_read_only_with_its_link(self):
        arch = etree.fromstring(self.env.ref("ea_audit_reports.view_engagement_form_report_dates").arch)
        for name in ("report_date", "assembly_deadline", "lock_status"):
            self.assertEqual(arch.xpath("//field[@name='%s']" % name)[0].get("readonly"), "1")
        self.assertTrue(arch.xpath("//button[@name='action_tool_conclusion']"))
