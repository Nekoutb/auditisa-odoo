"""The client's findings on the client record and the file's settings: F073 to F076."""
from datetime import date

from freezegun import freeze_time
from lxml import etree

from odoo.exceptions import AccessError
from odoo.tests import Form, tagged
from odoo.tools import mute_logger

from .common import AuditRuleError, EaAuditCase


@tagged("post_install", "-at_install")
class TestClientRecord(EaAuditCase):
    def test_f074_governance_and_regulator_are_lists(self):
        Client = self.env["ea.audit.client"]
        self.assertEqual(
            [code for code, _label in Client._fields["governance_mode"].selection],
            ["ca_pdg", "ca_dg", "administrateur_general", "gerance"],
        )
        self.assertIn("COBAC", [code for code, _label in Client._fields["regulator"].selection])
        client = Client.create({"name": "Banque SA", "governance_mode": "ca_dg", "regulator": "COBAC"})
        self.assertEqual((client.governance_mode, client.regulator), ("ca_dg", "COBAC"))

    @mute_logger("odoo.sql_db")
    def test_f074_framework_is_required(self):
        self.assertEqual(self.env["ea.audit.client"].create({"name": "Défaut SA"}).framework, "SYSCOHADA")
        self.assertTrue(self.env["ea.audit.client"]._fields["framework"].required)
        with self.assertRaises(Exception), self.cr.savepoint():
            self.env["ea.audit.client"].create({"name": "Sans SA", "framework": False})

    def test_f074_only_admin_and_partners_edit(self):
        for user in (self.partner, self.admin):
            self.client.with_user(user).write({"sector": "trade"})
        for user in (self.manager, self.senior, self.staff, self.reader):
            with self.assertRaises(AccessError):
                self.client.with_user(user).write({"sector": "services"})
        self.assertEqual(self.client.sector, "trade")

    def test_f074_a_manager_still_reads_and_opens_a_client(self):
        self.assertEqual(self.client.with_user(self.staff).name, "Governance SA")
        created = self.env["ea.audit.client"].with_user(self.manager).create({"name": "Nouveau SA"})
        self.assertEqual(created.sudo().framework, "SYSCOHADA")


@tagged("post_install", "-at_install")
class TestEngagementSettings(EaAuditCase):
    def test_f073_framework_defaults_from_the_client_and_is_a_list(self):
        engagement = self.make_engagement(2025)
        self.assertEqual(engagement.sudo().framework, "SYSCOHADA")
        Engagement = self.env["ea.audit.engagement"]
        self.assertEqual([code for code, _label in Engagement._fields["framework"].selection], ["SYSCOHADA"])

    def test_f073_framework_and_planned_dates_are_editable(self):
        engagement = self.make_engagement(2025)
        as_partner = engagement.with_user(self.partner)
        as_partner.write({
            "framework": "SYSCOHADA", "planned_report_date": date(2026, 4, 30), "planned_agm_date": date(2026, 6, 15),
        })
        self.assertEqual(as_partner.planned_report_date, date(2026, 4, 30))
        arch = etree.fromstring(self.env.ref("ea_audit_core.view_engagement_form").arch)
        self.assertFalse(arch.xpath("//field[@name='framework'][@readonly]"))
        self.assertIn("enable_formatting", arch.xpath("//field[@name='fiscal_year']")[0].get("options"))

    def test_f073_the_rest_of_the_set_up_stays_with_its_rules(self):
        engagement = self.make_engagement(2025)
        self.assertCode("forbidden", engagement.with_user(self.partner).write, {"fiscal_year": 2030})


@tagged("post_install", "-at_install")
class TestNewEngagement(EaAuditCase):
    def wizard(self):
        return self.env["ea.audit.engagement.create.wizard"].with_user(self.partner)

    @freeze_time("2026-11-06")
    def test_f075_fiscal_year_does_not_start_at_zero(self):
        self.assertEqual(self.wizard().new().default_get(["fiscal_year"])["fiscal_year"], 2025)

    def test_f075_fiscal_year_follows_the_closing_date(self):
        form = Form(self.wizard())
        form.period_end = date(2024, 6, 30)
        self.assertEqual(form.fiscal_year, 2024)

    def test_f075_a_zero_year_is_refused(self):
        wizard = self.wizard().create({
            "client_id": self.client.id, "fiscal_year": 0, "period_end": date(2025, 12, 31),
            "engagement_partner_id": self.partner.id,
        })
        with self.assertRaises(AuditRuleError) as caught:
            wizard.action_create()
        self.assertEqual(caught.exception.code, "fiscal-year-required")

    def test_f075_name_preview(self):
        wizard = self.wizard().new({"fiscal_year": 2025})
        self.assertEqual(wizard.name_preview, "—")
        wizard.client_id = self.client
        self.assertEqual(wizard.name_preview, "Governance SA 2025")
        engagement = self.make_engagement(2025)
        self.assertEqual(engagement.sudo().display_name, wizard.name_preview)


@tagged("post_install", "-at_install")
class TestPortfolio(EaAuditCase):
    def test_f076_partner_filter(self):
        mine = self.make_engagement(2025, partner=self.partner)
        theirs = self.make_engagement(2024, partner=self.partner2)
        self.seat(theirs, self.partner, "manager")
        self.seat(mine, self.partner2, "manager")
        Engagement = self.env["ea.audit.engagement"].with_user(self.partner)
        self.assertEqual(Engagement.search([("engagement_partner_id", "=", self.partner.id)]), mine)
        self.assertEqual(Engagement.search([("engagement_partner_id", "=", self.partner2.id)]), theirs)
        self.assertEqual(Engagement.search([("engagement_partner_id", "ilike", self.partner2.name)]), theirs)
        arch = self.env.ref("ea_audit_core.view_engagement_search").arch
        self.assertIn("my_portfolio", arch)
        self.assertEqual(mine.sudo().engagement_partner_id, self.partner)
