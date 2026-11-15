import base64
import io

from openpyxl import Workbook, load_workbook

from odoo.exceptions import AccessError
from odoo.tests import tagged

from .common import BALANCED_CSV, UNBALANCED_CSV, ToolsCase, to_bytes


def xlsx_bytes(rows):
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


@tagged("post_install", "-at_install")
class TestTrialBalance(ToolsCase):
    def test_a_valid_csv_becomes_the_current_version(self):
        result = self.import_tb()
        self.assertEqual(result["versionNo"], 1)
        self.assertEqual(result["summary"]["status"], "valid")
        version = self.engagement.sudo()._ea_current_tb_version()
        self.assertEqual(version.row_count, 7)
        self.assertEqual(version.source_filename, "balance.csv")
        self.assertNotIn("source_sha256", version._fields)
        line = version.line_ids.filtered(lambda l: l.account_code == "411000")
        self.assertEqual((line.opening, line.closing), (800, 900))

    def test_xlsx_reads_as_csv_does(self):
        content = xlsx_bytes([
            ["Balance générale 2025"],
            ["Compte", "Libellé", "Solde ouverture débit", "Solde ouverture crédit", "Mouvement débit", "Mouvement crédit"],
            [411000, "Clients", 800, 0, 1000, 900],
            [701000, "Ventes", 0, 800, 0, 100],
        ])
        result = self.as_staff.import_trial_balance("balance.xlsx", content)
        self.assertEqual(result["summary"]["status"], "valid", result["summary"])
        lines = self.engagement.sudo()._ea_current_tb_version().line_ids
        self.assertEqual(lines.mapped("account_code"), ["411000", "701000"])
        self.assertEqual(lines[0].closing, 900)

    def test_a_cp1252_export_keeps_its_headers(self):
        result = self.as_staff.import_trial_balance("balance.csv", BALANCED_CSV.encode("cp1252"))
        self.assertEqual(result["summary"]["status"], "valid")
        self.assertEqual(self.engagement.sudo()._ea_current_tb_version().line_ids[1].account_name, "Bâtiments")

    def test_refusals_keep_the_platforms_codes(self):
        self.assertCode("unsupported-file", self.as_staff.import_trial_balance, "balance.pdf", b"x")
        self.assertCode("unreadable-file", self.as_staff.import_trial_balance, "balance.xlsx", b"not a workbook")
        self.assertCode("empty-file", self.as_staff.import_trial_balance, "balance.csv", b"\n")
        self.assertCode("missing-account-column", self.as_staff.import_trial_balance, "b.csv", to_bytes("Montant;Autre\n1;2\n"))
        self.assertCode("missing-amount-columns", self.as_staff.import_trial_balance, "b.csv", to_bytes("Compte;Libellé\n411;Clients\n"))

    def test_an_invalid_reimport_is_refused_and_the_valid_version_keeps_driving(self):
        """Owner's ruling of 2026-11-15: a file that fails the checks is not saved."""
        self.import_tb()
        self.assertCode("import-refused", self.import_tb, UNBALANCED_CSV)
        tb = self.engagement.sudo()._ea_tb()
        self.assertEqual(len(tb.version_ids), 1)
        self.assertEqual(tb.current_version_no, 1)
        first = self.engagement.sudo()._ea_current_tb_version()
        self.assertEqual(first.version_no, 1)
        self.assertFalse(first.superseded_at)
        self.assertTrue(first.line_ids)

    def test_a_new_valid_import_moves_the_file_and_keeps_the_old_rows(self):
        self.import_tb()
        self.import_tb()
        tb = self.engagement.sudo()._ea_tb()
        self.assertEqual(tb.current_version_no, 2)
        self.assertEqual(len(tb.version_ids), 2)
        self.assertTrue(all(version.line_ids for version in tb.version_ids))

    def test_post_audit_and_prior_year_never_drive_the_file(self):
        self.import_tb(timing="post_audit")
        self.import_tb(timing="prior_year")
        self.assertFalse(self.engagement.sudo()._ea_current_tb_version())
        self.import_tb()
        self.assertEqual(self.engagement.sudo()._ea_tb().current_version_no, 3)

    def test_opening_ties_to_the_prior_engagements_closing(self):
        prior = self.make_engagement(year=2024)
        self.seat(prior, self.staff, "staff")
        prior.with_user(self.staff).import_trial_balance("p.csv", to_bytes(BALANCED_CSV))
        result = self.import_tb()
        check = result["summary"]["checks"]["openingTiesToPrior"]
        self.assertTrue(check["checked"])
        self.assertTrue(check["exceptions"])

    def test_preview_writes_nothing(self):
        preview = self.as_staff.preview_trial_balance_file("b.csv", to_bytes(BALANCED_CSV))
        self.assertIsNone(preview["mappingError"])
        self.assertEqual(preview["rowCount"], 7)
        self.assertFalse(self.engagement.sudo()._ea_tb())

    def test_the_wizard_uploads_matches_checks_and_imports(self):
        wizard = self.env["ea.audit.import.wizard"].with_user(self.staff).create({
            "engagement_id": self.engagement.id,
            "file": base64.b64encode(to_bytes(BALANCED_CSV)),
            "filename": "balance.csv",
        })
        wizard.action_read()
        self.assertEqual(wizard.step, "match")
        self.assertEqual(wizard.column_ids.filtered(lambda line: line.field_id.key == "account").header, "Compte")
        wizard.action_check()
        self.assertEqual(wizard.step, "check")
        self.assertFalse(self.engagement.sudo()._ea_tb())
        wizard.action_import()
        self.assertEqual(self.engagement.sudo()._ea_tb().current_version_no, 1)


@tagged("post_install", "-at_install")
class TestGuards(ToolsCase):
    def test_import_refuses_read_only_outsiders_and_the_eqr(self):
        self.assertCode("read-only-role", self.import_tb, actor=self.as_reader)
        self.assertCode("not-on-this-engagement", self.import_tb, actor=self.as_outsider)
        self.assertCode("eqr-read-only", self.import_tb, actor=self.as_eqr)

    def test_an_invited_member_is_not_yet_a_member(self):
        invited = self._user("invited", "group_staff")
        self.seat(self.engagement, invited, "staff", state="invited")
        self.assertCode("not-on-this-engagement", self.import_tb, actor=self.engagement.with_user(invited))

    def test_a_firm_admin_off_the_team_is_refused_as_anyone(self):
        self.assertCode("not-on-this-engagement", self.import_tb, actor=self.engagement.with_user(self.admin))

    def test_an_archived_file_refuses(self):
        self.engagement.sudo().phase = "archived"
        self.assertCode("archived", self.import_tb)

    def test_no_user_writes_a_tb_row_through_the_orm(self):
        self.import_tb()
        version = self.engagement.sudo()._ea_current_tb_version()
        line = version.line_ids[0].with_user(self.manager)
        self.assertCode("forbidden", line.write, {"debit": 1})
        self.assertCode("forbidden", line.unlink)
        self.assertCode("forbidden", version.with_user(self.partner).write, {"validation_status": "valid"})
        self.assertCode("forbidden", self.env["ea.audit.tb.line"].with_user(self.manager).create, [{
            "engagement_id": self.engagement.id, "version_id": version.id, "account_code": "1",
        }])

    def test_every_tool_record_is_team_only(self):
        self.import_tb()
        self.as_staff.create_materiality_version("pbt", 500, 7.5, "x")
        for model in (
            "ea.audit.tb", "ea.audit.tb.version", "ea.audit.tb.line", "ea.audit.lead.schedule", "ea.audit.lead.line",
            "ea.audit.materiality", "ea.audit.significance", "ea.audit.risk", "ea.audit.risk.section",
            "ea.audit.program.step",
        ):
            Model = self.env[model]
            record = Model.sudo().search([("engagement_id", "=", self.engagement.id)], limit=1)
            self.assertTrue(record, model)
            self.assertEqual(Model.with_user(self.staff).search_count([("id", "=", record.id)]), 1, model)
            self.assertEqual(Model.with_user(self.outsider).search_count([("id", "=", record.id)]), 0, model)
            self.assertEqual(Model.with_user(self.admin).search_count([("id", "=", record.id)]), 0, model)
            with self.assertRaises(AccessError):
                record.with_user(self.outsider).read(["create_date"])

    def test_every_engagement_model_carries_the_global_rule(self):
        """Declared once, so a model added later cannot miss the rule without failing here."""
        Rule = self.env["ir.rule"].sudo()
        checked = 0
        for name, model in self.env.items():
            if name.startswith("ea.audit.") and not model._abstract and not model._transient and "_ea_guard" in dir(model):
                # global, or the firm's own group rule where a client contact reads the same model
                member = self.env.ref("ea_audit_core.group_member")
                rules = Rule.search([("model_id.model", "=", name)]).filtered(lambda r: not r.groups or member in r.groups)
                self.assertTrue(rules.filtered(lambda r: "accepted" in r.domain_force), "%s has no team-only rule" % name)
                checked += 1
        self.assertGreaterEqual(checked, 20)


@tagged("post_install", "-at_install")
class TestLeadSchedules(ToolsCase):
    def test_schedules_follow_the_map_with_opening_as_comparative(self):
        self.import_tb()
        schedules = self.env["ea.audit.lead.schedule"].with_user(self.staff).search([("engagement_id", "=", self.engagement.id)])
        by = {s.index_code: s for s in schedules}
        self.assertEqual(set(by), {"T", "K", "E", "N", "C", "VA1", "UA"})
        self.assertEqual((by["E"].closing, by["E"].prior, by["E"].movement), (900, 800, 100))
        self.assertEqual(by["E"].variance_pct, 12.5)
        self.assertEqual(by["E"].prior_source, "opening")
        self.assertFalse(by["UA"].has_variance_pct)
        self.assertEqual(by["E"].paper_code, "E4.1")

    def test_a_valid_prior_year_tb_supplies_the_comparative(self):
        self.import_tb()
        self.import_tb(BALANCED_CSV.replace("800;0;1000;900", "800;0;1000;900"), timing="prior_year")
        schedule = self.env["ea.audit.lead.schedule"].sudo().search([("engagement_id", "=", self.engagement.id), ("index_code", "=", "E")])
        self.assertEqual(schedule.prior_source, "prior_year_tb")
        self.assertEqual(schedule.prior, 900)

    def test_client_override_wins_by_longest_prefix_and_rebuilds(self):
        self.import_tb()
        self.as_staff.save_lead_index_override("4110", "G2")
        codes = self.env["ea.audit.lead.schedule"].sudo().search([("engagement_id", "=", self.engagement.id)]).mapped("index_code")
        self.assertIn("G2", codes)
        self.assertNotIn("E", codes)
        self.assertCode("invalid-prefix", self.as_staff.save_lead_index_override, "41x", "G2")
        self.assertCode("invalid-index", self.as_staff.save_lead_index_override, "41", "ZZ")

    def test_grouping_override_codes(self):
        self.assertCode("invalid-prefix", self.as_staff.add_grouping_override, "prefix", "", "E4.1", "x")
        self.assertCode("invalid-section", self.as_staff.add_grouping_override, "prefix", "41", "S1", "x")
        self.assertCode("rationale-required", self.as_staff.add_grouping_override, "prefix", "41", "E4.1", " ")
        self.as_staff.add_grouping_override("prefix", "41", "E4.1", "client chart")
        self.as_staff.add_grouping_override("prefix", "41", "E4.2", "client chart changed")
        overrides = self.env["ea.audit.client.grouping.override"].sudo().search([("client_id", "=", self.client.id)])
        self.assertEqual(overrides.section_code, "E4.2")

    def test_client_overrides_are_read_by_the_clients_teams_only(self):
        self.as_staff.add_grouping_override("prefix", "41", "E4.1", "client chart")
        Override = self.env["ea.audit.client.grouping.override"]
        self.assertEqual(Override.with_user(self.staff).search_count([]), 1)
        self.assertEqual(Override.with_user(self.outsider).search_count([]), 0)
        record = Override.sudo().search([], limit=1)
        self.assertCode("forbidden", record.with_user(self.staff).write, {"rationale": "x"})

    def test_commentary_survives_a_rebuild_and_read_only_cannot_write(self):
        self.import_tb()
        line = self.env["ea.audit.lead.line"].with_user(self.staff).search([
            ("engagement_id", "=", self.engagement.id), ("account_code", "=", "411000"),
        ])
        line.write({"commentary": "Reconciled to the ageing."})
        self.assertCode("invalid-field", line.write, {"closing": 1})
        self.assertCode("read-only-role", line.with_user(self.reader).write, {"commentary": "x"})
        self.assertCode("eqr-read-only", line.with_user(self.eqr).write, {"commentary": "x"})
        self.import_tb()
        again = self.env["ea.audit.lead.line"].with_user(self.reader).search([
            ("engagement_id", "=", self.engagement.id), ("account_code", "=", "411000"),
        ])
        self.assertEqual(again.commentary, "Reconciled to the ageing.")
        again.with_user(self.staff).write({"commentary": ""})
        self.assertFalse(self.env["ea.audit.ap.comment"].sudo().search_count([("engagement_id", "=", self.engagement.id)]))

    def test_excel_extract_has_introduction_and_one_tab_per_index(self):
        self.import_tb()
        filename, content = self.as_reader.ea_export_xlsx("lead")
        self.assertTrue(filename.startswith("lead-schedules-"))
        book = load_workbook(io.BytesIO(content))
        self.assertEqual(book.sheetnames[0], "Introduction")
        self.assertEqual(len(book.sheetnames), 8)
        sheet = next(book[name] for name in book.sheetnames if name.startswith("E "))
        self.assertEqual(sheet.cell(4, 1).value, "411000")
        self.assertEqual(sheet.cell(5, 1).value, "TOTAL")
        self.assertEqual(sheet.cell(5, 5).value, 900)
        self.assertCode("not-on-this-engagement", self.as_outsider.ea_export_xlsx, "lead")

    def test_no_tb_no_extract(self):
        self.assertCode("no-tb", self.as_staff.ea_export_xlsx, "lead")

    def test_an_export_is_on_the_trail(self):
        self.import_tb()
        self.as_staff.ea_export_xlsx("lead")
        messages = self.engagement.sudo().message_ids.mapped("body")
        self.assertTrue(any("exported" in str(body) for body in messages))


@tagged("post_install", "-at_install")
class TestBilan(ToolsCase):
    def test_the_board_figures_balance(self):
        self.import_tb()
        as_root = self.engagement.sudo()
        as_root.invalidate_recordset()
        self.assertEqual(as_root.bilan_total_assets, 4000 + 900 + 700)
        self.assertEqual(as_root.bilan_class1, 5000)
        self.assertEqual(as_root.bilan_class4_credit, 600)
        self.assertEqual(as_root.bilan_total_assets, as_root.bilan_total_equity_liabilities)
        self.assertIn("TB of ", as_root.bilan_label)
        self.assertNotIn("v1", as_root.bilan_label)

    def test_tb_mapped_gate_reads_unknown_accounts(self):
        self.import_tb("Compte;Libellé;Mouvement débit;Mouvement crédit\n999000;Inconnu;100;0\n411000;Clients;0;100\n")
        self.assertEqual(self.engagement.sudo()._ea_unmapped_tb_account_count(), 1)
        self.as_staff.add_grouping_override("exact", "999000", "E4.1", "client chart")
        self.assertEqual(self.engagement.sudo()._ea_unmapped_tb_account_count(), 0)
