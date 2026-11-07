import io

from openpyxl import load_workbook

from odoo.tests import HttpCase, tagged

from ..controllers import supervision
from .common import PlatformCase, PlatformMixin
from .test_addons import SAMPLE, catalogue_bytes


@tagged("post_install", "-at_install")
class TestSupervisionPage(PlatformCase):
    def test_it_is_the_first_screen_of_the_app(self):
        root = self.env.ref("ea_platform_admin.menu_root")
        first = root.child_id.sorted("sequence")[0]
        self.assertEqual(first, self.env.ref("ea_platform_admin.menu_supervision"))
        self.assertEqual(first.action, self.env.ref("ea_platform_admin.action_supervision"))

    def test_a_firm_shows_every_reference_it_was_given(self):
        firm = self._active_firm()
        for name in ("server_id", "server_ip", "region", "size", "ssh_key_id", "firewall_id", "storage_id", "platform_host", "provider_label"):
            self.assertTrue(firm[name], name)
        self.assertEqual(firm.provider_label, "Simulation")

    def test_a_simulation_firm_has_no_link_and_a_real_one_has_both(self):
        firm = self._active_firm()
        self.assertFalse(firm.site_url)
        firm.sudo().write({"is_simulation": False, "custom_domain": "audit.cabinet.cm"})
        firm.invalidate_recordset()
        self.assertEqual(firm.site_url, "https://cabinet-a.auditisa.com")
        self.assertEqual(firm.own_site_url, "https://audit.cabinet.cm")
        self.assertEqual(firm.provider_label, "Vultr")

    def test_backup_state_follows_the_figures(self):
        firm = self._active_firm()
        self.assertEqual(firm.backup_state, "ok")
        firm.sudo().write({"last_backup_ok": False})
        firm.invalidate_recordset()
        self.assertEqual(firm.backup_state, "failed")

    def test_the_search_finds_by_domain_server_and_add_on(self):
        self.release.sudo()._load_catalogue(catalogue_bytes(self.release.sha))
        firm = self._active_firm("cabinet-a")
        other = self._active_firm("cabinet-b")
        sample = self.env["platform.addon"].search([("code", "=", SAMPLE)])
        firm._set_addon(sample, True, "Why")
        firm.sudo().custom_domain = "audit.cabinet.cm"
        found = self.env["platform.firm"].search([("addon_line_ids.desired", "=", True), ("addon_line_ids.code", "ilike", "sample")])
        self.assertEqual(found, firm)
        self.assertEqual(self.env["platform.firm"].search([("custom_domain", "ilike", "cabinet.cm")]), firm)
        self.assertEqual(self.env["platform.firm"].search([("server_id", "=", other.server_id)]), other)

    def test_the_export_button_covers_the_search_or_the_selection(self):
        firm = self._active_firm("cabinet-a")
        other = self._active_firm("cabinet-b")
        model = self.env["platform.firm"].with_user(self.viewer)
        url = model.with_context(active_domain=[("id", "=", other.id)]).action_export_supervision()["url"]
        self.assertTrue(url.endswith(f"ids={other.id}"))
        self.assertTrue(firm.with_user(self.viewer).action_export_supervision()["url"].endswith(f"ids={firm.id}"))
        self.assertIn(str(firm.id), model.with_context(active_domain=[]).action_export_supervision()["url"])

    def test_the_workbook_holds_references_and_no_secret(self):
        firm = self._active_firm()
        token = firm.sudo().heartbeat_token
        content = supervision.build_workbook(self.env, firm)
        sheet = load_workbook(io.BytesIO(content)).active
        rows = list(sheet.iter_rows(values_only=True))
        self.assertEqual(len(rows), 2)
        joined = "|".join(str(cell) for cell in rows[1])
        for text in (firm.server_id, firm.server_ip, firm.ssh_key_id, firm.firewall_id, firm.storage_id, firm.platform_host):
            self.assertIn(text, joined)
        self.assertNotIn(token, joined)
        self.assertNotIn(firm.contact_email, joined)
        self.assertNotIn(firm.ssh_public_key, joined)

    def test_the_export_lists_only_what_the_security_model_allows(self):
        names = {name for name, _title in supervision.COLUMNS}
        self.assertFalse(names & {"heartbeat_token", "first_admin_token", "note", "contact_name", "contact_email", "contact_phone", "ssh_public_key"})
        for name in names:
            self.assertIn(name, self.env["platform.firm"]._fields)

    def test_the_page_never_shows_a_secret(self):
        for xmlid in ("view_supervision_kanban", "view_supervision_list", "view_supervision_search"):
            arch = self.env.ref(f"ea_platform_admin.{xmlid}").arch_db
            self.assertNotIn("heartbeat_token", arch)
            self.assertNotIn("first_admin_token", arch)


@tagged("post_install", "-at_install")
class TestSupervisionExportRoute(PlatformMixin, HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_platform()

    def test_a_viewer_downloads_and_it_is_logged(self):
        firm = self._active_firm()
        self.env.flush_all()
        self.authenticate("p_viewer", "p_viewer")
        response = self.url_open(f"/platform/supervision/export?ids={firm.id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response.headers["Content-Type"])
        rows = list(load_workbook(io.BytesIO(response.content)).active.iter_rows(values_only=True))
        self.assertEqual(rows[1][0], firm.name)
        self.assertTrue(self.env["platform.log"].search_count([("action", "=", "Supervision list exported")]))

    def test_someone_with_no_platform_group_is_refused(self):
        firm = self._active_firm()
        from odoo.tests import new_test_user
        new_test_user(self.env, login="p_outsider", groups="base.group_user")
        self.env.flush_all()
        self.authenticate("p_outsider", "p_outsider")
        response = self.url_open(f"/platform/supervision/export?ids={firm.id}")
        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn(firm.server_id.encode(), response.content)

    def test_a_bad_list_of_ids_is_not_found(self):
        self.authenticate("p_viewer", "p_viewer")
        self.assertEqual(self.url_open("/platform/supervision/export?ids=1;drop").status_code, 404)


