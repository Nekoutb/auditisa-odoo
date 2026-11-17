"""The client's governance and shell findings, one regression test per fix."""
import base64
import io
from datetime import date, timedelta

from openpyxl import load_workbook

from odoo.exceptions import AccessError, UserError
from odoo.tests import tagged
from odoo.tools import file_open, mute_logger

from odoo.addons.ea_audit_core.services.errors import AuditRuleError
from odoo.addons.ea_audit_papers.services import load_definition
from odoo.addons.ea_audit_tools.tests.common import ToolsCase


@tagged("post_install", "-at_install")
class TestGovFindings(ToolsCase):
    def setUp(self):
        super().setUp()
        self.Ui = self.env["ea.audit.ui"]
        self.env["res.lang"]._ea_setup_languages()
        self.company_partner = self.env.company.sudo().partner_id

    def ui(self, user):
        return self.Ui.with_user(user)

    def fr(self, user):
        return self.Ui.with_user(user).with_context(lang="fr_FR")

    def item(self, code, engagement=None):
        return (engagement or self.engagement).sudo().file_item_ids.filtered(lambda i: i.code == code)

    def paper(self, code):
        return self.item(code)._ea_paper()

    def ring(self, data, key):
        return next(r for r in data["rings"] if r["key"] == key)

    def group(self, ring, group_id):
        return next(g for g in ring["groups"] if g["id"] == group_id)

    # ---- F027 ---------------------------------------------------------------------------

    def test_f027_the_firm_admin_reads_the_whole_firm_and_the_full_text(self):
        self.assertFalse(self.engagement.sudo()._ea_member(self.admin))
        long_text = "premier " * 800
        self.paper("P3.1").with_user(self.staff).save_answers({"key_findings": long_text})
        self.paper("P3.1").with_user(self.staff).save_answers({"key_findings": long_text + "suite"})
        Log = self.env["ea.audit.activity"].with_user(self.admin)
        rows = Log.search([("field_key", "=", "key_findings"), ("code", "=", "P3.1")])
        self.assertEqual(len(rows), 2)
        latest = rows[0]
        self.assertEqual(latest.before, long_text)
        self.assertEqual(latest.after, long_text + "suite")
        self.assertEqual(latest.user_id, self.staff)
        self.assertIn(self.engagement.sudo().client_id.name, latest.engagement_label)
        self.assertEqual(latest.summary_display, "P3.1: answer changed")

    def test_f027_nobody_else_reads_it(self):
        self.as_partner._ea_log("signed_off", "P1.1 signed by X as partner")
        for user in (self.partner, self.manager, self.senior, self.staff, self.eqr, self.reader):
            with self.assertRaises(AccessError):
                self.env["ea.audit.activity"].with_user(user).search([])

    def test_f027_the_log_cannot_be_changed(self):
        self.as_partner._ea_log("signed_off", "P1.1 signed by X as partner")
        row = self.env["ea.audit.activity"].with_user(self.admin).search([], limit=1)
        with self.assertRaises(AuditRuleError):
            row.write({"summary": "other"})
        with self.assertRaises(AuditRuleError):
            row.unlink()
        with self.assertRaises(AuditRuleError):
            self.env["ea.audit.activity"].with_user(self.admin).create({"action": "x", "summary": "y"})

    def test_f027_every_trail_line_and_every_rule_change_reaches_the_log(self):
        self.item("E6.2").with_user(self.manager).assign_tasks(self.staff.id, "preparer")
        Log = self.env["ea.audit.activity"].with_user(self.admin)
        self.assertEqual(Log.search([("action", "=", "tasks_assigned")], limit=1).user_id, self.manager)
        self.env["ea.audit.signoff.task.rule"].with_user(self.partner).save_task_rules([
            {"code": "P1.5", "min_preparer": "staff", "min_reviewer": None, "partner_required": None},
        ])
        row = Log.search([("action", "=", "signoff_rule_added"), ("code", "=", "P1.5")], limit=1)
        self.assertIn("min_preparer: staff", row.after)
        self.assertEqual(row.user_id, self.partner)

    def test_f027_the_gear_has_it_for_the_firm_admin_alone(self):
        self.assertTrue(self.ui(self.admin)._ea_ui_shell_session()["is_firm_admin"])
        self.assertFalse(self.ui(self.partner)._ea_ui_shell_session()["is_firm_admin"])

    # ---- F031 ---------------------------------------------------------------------------

    def test_f031_a_conditional_paper_shows_with_its_trigger(self):
        data = self.ui(self.staff).ea_ui_tasks(self.engagement.id, "s5")
        rows = {row["code"]: row["trigger"] for row in data["conditional"]}
        self.assertEqual(rows["S5.1"], "S6.1: expert used = Yes")
        self.assertNotIn("S5.1", [row["code"] for row in data["rows"]])
        french = self.fr(self.staff).ea_ui_tasks(self.engagement.id, "s5")
        rows = {row["code"]: row["trigger"] for row in french["conditional"]}
        self.assertIn("expert", rows["S5.1"])
        self.assertIn("Oui", rows["S5.1"])

    def test_f031_the_note_on_e3(self):
        self.assertIn("E3", self.ui(self.staff).ea_ui_tasks(self.engagement.id, "e5")["note"])
        self.assertFalse(self.ui(self.staff).ea_ui_tasks(self.engagement.id, "s5")["note"])
        ring = self.ring(self.ui(self.staff).ea_ui_dashboard(self.engagement.id), "execution")
        self.assertIn("E3", ring["note"])
        self.assertIn("E5", self.fr(self.staff).ea_ui_tasks(self.engagement.id, "e5")["note"])

    def test_f031_forms_lists_them_too(self):
        action = self.as_staff.action_tool_forms()
        rows = self.env["ea.audit.file.item"].with_user(self.staff).search(action["domain"])
        self.assertIn("S5.1", rows.mapped("code"))
        self.assertTrue(rows.filtered(lambda r: r.code == "S5.1").conditional_trigger)

    def test_f031_the_trigger_is_true_answering_it_brings_the_paper(self):
        item = self.item("S5.1")
        self.assertTrue(item.conditional)
        paper = self.paper("S6.1").with_user(self.staff)
        paper.save_answers({"uses_expert": "yes"})
        self.assertFalse(item.conditional)
        self.assertIn("S5.1", [r["code"] for r in self.ui(self.staff).ea_ui_tasks(self.engagement.id, "s5")["rows"]])
        paper.save_answers({"uses_expert": "no"})
        self.assertTrue(item.conditional)

    # ---- F086 ---------------------------------------------------------------------------

    def test_f086_a_new_account_takes_the_firm_language(self):
        self.company_partner.lang = "fr_FR"
        user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "New One", "login": "new.one@gov.example.com", "group_ids": [(6, 0, [self.env.ref("ea_audit_core.group_staff").id])],
        })
        self.assertEqual(user.lang, "fr_FR")
        chosen = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "New Two", "login": "new.two@gov.example.com", "lang": "en_US",
        })
        self.assertEqual(chosen.lang, "en_US")

    def test_f086_the_firm_admin_sets_the_language(self):
        self.company_partner.lang = "en_US"
        with self.assertRaises(AuditRuleError):
            self.env["res.company"].with_user(self.partner).ea_set_firm_language("fr_FR")
        self.env["res.company"].with_user(self.admin).ea_set_firm_language("fr_FR")
        self.assertEqual(self.company_partner.lang, "fr_FR")
        policy = self.env["ea.audit.signoff.policy"].with_user(self.admin).search([], limit=1)
        if not policy:
            policy = self.env["ea.audit.signoff.policy"].with_user(self.admin).create({"min_reviewer_role": "senior"})
        self.assertEqual(policy.firm_language, "fr_FR")
        policy.write({"firm_language": "en_US"})
        self.assertEqual(self.company_partner.lang, "en_US")

    def test_f086_the_feed_reads_translated_without_key(self):
        self.as_partner._ea_log("signed_off", "P1.4 signed by Marie & Paul as reviewer")
        message = self.env["mail.message"].search([
            ("model", "=", "ea.audit.engagement"), ("res_id", "=", self.engagement.id), ("message_type", "=", "notification"),
        ], order="id desc", limit=1)
        self.assertIn("signed_off:", message.body)
        french = str(message.with_context(lang="fr_FR")._ea_body_for_reader())
        self.assertNotIn("signed_off", french)
        self.assertIn("P1.4 signée par Marie &amp; Paul comme réviseur", french)
        english = str(message.with_context(lang="en_US")._ea_body_for_reader())
        self.assertEqual(english, "P1.4 signed by Marie &amp; Paul as reviewer")
        target = type("Target", (), {"is_internal": lambda _self, _env: True})()
        body = next(f for f in message._to_store_defaults(target) if getattr(f, "field_name", f) == "body")
        self.assertEqual(body._get_value(message.with_context(lang="en_US")), english)

    def test_f086_someone_elses_note_is_left_alone(self):
        message = self.engagement.sudo().message_post(body="key_like: a person's words", message_type="comment")
        self.assertEqual(str(message._ea_body_for_reader()), str(message.body))

    # ---- F002 ---------------------------------------------------------------------------

    def _matrix_rows(self, content):
        sheet = load_workbook(io.BytesIO(content))["Tasks"]
        return sheet

    def test_f002_the_default_matrix_is_listed_whole(self):
        Template = self.env["ea.audit.task.template"].with_user(self.partner)
        templates = Template.search([], order="matrix_order, id")
        self.assertGreater(len(templates), 100)
        rows = {t.code: t for t in templates}
        self.assertEqual((rows["P1.5"].matrix_min_preparer, rows["P1.5"].matrix_min_reviewer), ("manager", "partner"))
        self.assertTrue(rows["P1.1"].matrix_partner)
        self.assertEqual((rows["E4.1"].matrix_min_preparer, rows["E4.1"].matrix_min_reviewer), ("staff", "senior"))
        self.assertFalse(rows["P1.5"].matrix_firm_rule)
        codes = templates.mapped("code")
        self.assertLess(codes.index("P1.2"), codes.index("P1.10") if "P1.10" in codes else len(codes))
        self.assertEqual(codes[0], "P1.1")

    def test_f002_export_then_import_changes_the_rule_and_it_takes_effect(self):
        staff_item = self.item("P1.5")
        self.assertCode(
            "role-below-task-minimum-manager",
            staff_item.with_user(self.staff).with_context(ea_sign_dry_run=True).action_sign, "preparer",
        )
        Rule = self.env["ea.audit.signoff.task.rule"].with_user(self.partner)
        name, content = self.env["ea.audit.signoff.task.rule"].with_user(self.partner)._ea_matrix_workbook()
        self.assertTrue(name.endswith(".xlsx"))
        book = load_workbook(io.BytesIO(content))
        sheet = book["Tasks"]
        row = next(r for r in sheet.iter_rows(min_row=2) if r[0].value == "P1.5")
        self.assertEqual((row[5].value, row[6].value), ("Manager", "Partner"))
        row[8].value = "Staff"
        out = io.BytesIO()
        book.save(out)
        self.assertEqual(Rule._ea_matrix_import(out.getvalue()), 1)
        self.assertEqual(self.env["ea.audit.signoff.policy"]._ea_effective_rule("P1.5")["min_preparer"], "staff")
        self.engagement.invalidate_recordset()
        refusal = self.attempt(staff_item.with_user(self.staff).with_context(ea_sign_dry_run=True).action_sign, "preparer")
        self.assertNotEqual(refusal, "role-below-task-minimum-manager")
        # the matrix now says so too, and a blank cell gives the default back
        template = self.env["ea.audit.task.template"].with_user(self.partner).search([("code", "=", "P1.5")])
        template.invalidate_recordset()
        self.assertTrue(template.matrix_firm_rule)
        row[8].value = None
        out = io.BytesIO()
        book.save(out)
        self.assertEqual(Rule._ea_matrix_import(out.getvalue()), 1)
        self.assertEqual(self.env["ea.audit.signoff.policy"]._ea_effective_rule("P1.5")["min_preparer"], "manager")

    def test_f002_a_french_file_reads_too(self):
        Rule = self.env["ea.audit.signoff.task.rule"].with_user(self.partner).with_context(lang="fr_FR")
        _name, content = Rule._ea_matrix_workbook()
        book = load_workbook(io.BytesIO(content))
        self.assertIn("Tasks", book.sheetnames)
        sheet = book["Tasks"]
        row = next(r for r in sheet.iter_rows(min_row=2) if r[0].value == "P1.5")
        row[8].value = row[5].value  # the French word for manager
        row[10].value = "Oui"
        out = io.BytesIO()
        book.save(out)
        self.env["ea.audit.signoff.task.rule"].with_user(self.partner).with_context(lang="fr_FR")._ea_matrix_import(out.getvalue())
        own = self.env["ea.audit.signoff.task.rule"]._ea_rules(["P1.5"])["P1.5"]
        self.assertEqual((own["min_preparer"], own["partner_required"]), ("manager", True))

    def test_f002_a_wrong_row_saves_nothing_and_says_where(self):
        _name, content = self.env["ea.audit.signoff.task.rule"].with_user(self.partner)._ea_matrix_workbook()
        book = load_workbook(io.BytesIO(content))
        sheet = book["Tasks"]
        rows = list(sheet.iter_rows(min_row=2))
        rows[0][8].value = "Staff"
        rows[1][9].value = "Nobody"
        out = io.BytesIO()
        book.save(out)
        with self.assertRaises(UserError) as caught:
            self.env["ea.audit.signoff.task.rule"].with_user(self.partner)._ea_matrix_import(out.getvalue())
        self.assertIn("Nobody", str(caught.exception))
        self.assertIn("3", str(caught.exception))
        self.assertFalse(self.env["ea.audit.signoff.task.rule"].search([]))

    def test_f002_not_a_workbook(self):
        with self.assertRaises(UserError):
            self.env["ea.audit.signoff.task.rule"].with_user(self.partner)._ea_matrix_import(b"not a workbook")

    def test_f002_staff_and_manager_neither_export_nor_import(self):
        for user in (self.staff, self.manager):
            with self.assertRaises(AuditRuleError):
                self.env["ea.audit.signoff.task.rule"].with_user(user)._ea_matrix_workbook()
            with self.assertRaises(AuditRuleError):
                self.env["ea.audit.signoff.task.rule"].with_user(user)._ea_matrix_import(b"x")

    def test_f002_the_export_button_gives_a_file(self):
        action = self.env["ea.audit.task.template"].with_user(self.partner).action_matrix_export()
        self.assertEqual(action["type"], "ir.actions.act_url")
        attachment = self.env["ir.attachment"].with_user(self.partner).browse(int(action["url"].split("/")[3].split("?")[0]))
        self.assertTrue(load_workbook(io.BytesIO(base64.b64decode(attachment.datas)))["Tasks"])

    # ---- F005 ---------------------------------------------------------------------------

    def test_f005_c42_is_the_quality_review_alone(self):
        definition = load_definition("C4.2")
        # the layout of 2026-11-17: one standard conclusion in place of the conclusion statement
        self.assertNotIn("conclEn", definition)
        self.assertIn("C5.11", definition["ownsEn"])
        self.assertIn("C5.11", definition["ownsFr"])
        text = " ".join(definition["reqEn"] + [definition["conclStdEn"], definition["objectiveEn"]]).lower()
        self.assertNotIn("governance", text)
        for section in definition["sections"]:
            for entry in section.get("procs", []) + section.get("items", []):
                self.assertNotIn("governance", entry["en"].lower(), entry["key"])
        # and what it no longer holds is on C5.11
        keys = [i["key"] for s in load_definition("C5.11")["sections"] for i in s.get("items", [])]
        for key in ("planning", "findings", "independence", "sig_written"):
            self.assertIn(key, keys)

    # ---- F006 ---------------------------------------------------------------------------

    def test_f006_the_lists_leave_out_the_other_role(self):
        item = self.item("E6.2")
        item.with_user(self.manager).assign_tasks(self.staff.id, "preparer")
        item.invalidate_recordset()
        payload = item.with_user(self.manager)._ea_assignment_payload()
        self.assertNotIn(self.staff.id, [o["id"] for o in payload["approver_options"]])
        self.assertIn(self.staff.id, [o["id"] for o in payload["preparer_options"]])
        item.with_user(self.manager).assign_tasks(self.senior.id, "approver")
        item.invalidate_recordset()
        payload = item.with_user(self.manager)._ea_assignment_payload()
        self.assertNotIn(self.senior.id, [o["id"] for o in payload["preparer_options"]])
        self.assertIn(self.senior.id, [o["id"] for o in payload["approver_options"]])

    def test_f006_a_legacy_row_stays_readable_and_red_on_forms(self):
        item = self.item("E6.2")
        item.write({"preparer_id": self.staff.id, "approver_id": self.staff.id})
        payload = item.with_user(self.manager)._ea_assignment_payload()
        self.assertIn(self.staff.id, [o["id"] for o in payload["approver_options"]])
        arch = self.env.ref("ea_audit_tools.view_forms_register").arch
        self.assertIn('decoration-danger="preparer_id and preparer_id == approver_id"', arch)

    def test_f006_the_task_form_offers_team_members_only(self):
        item = self.item("E6.2")
        self.assertIn(self.staff, item.team_user_ids)
        self.assertNotIn(self.outsider, item.team_user_ids)
        self.assertNotIn(self.eqr, item.team_user_ids)
        arch = self.env.ref("ea_audit_core.view_file_item_form").arch
        self.assertIn("('id', 'in', team_user_ids), ('id', '!=', preparer_id)", arch)

    # ---- F007 ---------------------------------------------------------------------------

    def test_f007_reviewer_everywhere(self):
        Item = self.env["ea.audit.file.item"]
        self.assertEqual(Item.fields_get(["approver_id"])["approver_id"]["string"], "Reviewer")
        french = Item.with_context(lang="fr_FR").fields_get(["approver_id"])["approver_id"]["string"]
        self.assertEqual(french, "Réviseur")
        with self.assertRaises(AuditRuleError) as caught:
            item = self.item("E6.2")
            item.with_user(self.manager).assign_tasks(self.staff.id, "preparer")
            item.with_user(self.manager).with_context(lang="fr_FR").assign_tasks(self.staff.id, "approver")
        self.assertNotIn("pprobateur", caught.exception.args[0])

    # ---- F010 ---------------------------------------------------------------------------

    def test_f010_one_count_of_the_designed_on_every_screen(self):
        total = len(self.engagement.sudo().file_item_ids.filtered(lambda i: i.code.startswith("E4.") and not i.conditional))
        out = len(self.engagement.sudo()._ea_e4_out_of_scope())
        expected = "%d of %d designed" % (total - out, total)
        dashboard = self.ui(self.staff).ea_ui_dashboard(self.engagement.id)
        groups = {g["id"]: g for g in self.ring(dashboard, "execution")["groups"]}
        if "e4" in groups:
            self.assertEqual(groups["e4"]["designed"], expected)
            # the Execution menu's "Substantive procedures" opens the tool page (2026-11-16)
            self.assertEqual(groups["e4"]["tool"], "action_tool_substantive")
        self.assertEqual(dashboard["my_tasks"]["e4"]["text"], expected)
        self.assertEqual(self.ui(self.staff).ea_ui_tasks(self.engagement.id, "e4")["designed"], expected)
        self.assertEqual(self.ui(self.staff).ea_ui_all_tasks(self.engagement.id)["designed"], expected)
        self.assertIn("sur", self.fr(self.staff).ea_ui_tasks(self.engagement.id, "e4")["designed"])

    # ---- F011 ---------------------------------------------------------------------------

    def test_f011_the_paper_shows_the_date_the_group_shows(self):
        item = self.item("E6.2").with_user(self.manager)
        item.set_due_date("2020-01-15")
        payload = self.paper("E6.2").with_user(self.staff).get_payload()
        self.assertEqual(payload["deadline"]["date"], "15/01/2020")
        self.assertEqual(payload["deadline"]["own"], "2020-01-15")
        self.assertIn("Overdue", payload["deadline"]["late_text"])
        row = next(r for r in self.ui(self.staff).ea_ui_tasks(self.engagement.id, "e5")["rows"] if r["code"] == "E6.2")
        self.assertEqual(row["due"], payload["deadline"]["date"])
        self.assertEqual(row["late_text"], payload["deadline"]["late_text"])

    def test_f011_clearing_goes_back_to_the_phase_and_is_logged(self):
        item = self.item("E6.2").with_user(self.manager)
        future = (date.today() + timedelta(days=30)).isoformat()
        item.set_due_date(future)
        self.assertEqual(self.env["ea.audit.activity"].sudo().search([("action", "=", "due_date_set")], limit=1).code, "E6.2")
        item.set_due_date(False)
        payload = self.paper("E6.2").with_user(self.staff).get_payload()
        self.assertEqual(payload["deadline"]["own"], "")
        self.assertTrue(payload["deadline"]["date"])

    def test_f011_staff_and_outsider_cannot_set_it(self):
        self.assertCode("requires-senior", self.item("E6.2").with_user(self.staff).set_due_date, "2030-01-01")
        self.assertNotEqual(self.attempt(self.item("E6.2").with_user(self.outsider).set_due_date, "2030-01-01"), "ok")

    # ---- F014 ---------------------------------------------------------------------------

    def test_f014_an_empty_board_says_not_assessable_yet(self):
        # The CRA is one page since 2026-11-16: the empty state is the page's, in EN and FR.
        self.assertFalse(self.engagement.sudo().cra_row_ids)
        page = self.engagement.with_user(self.staff).ea_cra_page()
        self.assertTrue(page["missing"])
        self.assertFalse(page["accounts"])
        with file_open("ea_audit_tools/static/src/xml/cra_page.xml") as handle:
            template = handle.read()
        self.assertIn("Not assessable yet", template)
        self.assertIn('t-if="p.missing"', template)
        with file_open("ea_audit_tools/i18n/fr.po") as handle:
            self.assertIn('msgid "Not assessable yet"\nmsgstr "Pas encore évaluable"', handle.read())

    # ---- F021 ---------------------------------------------------------------------------

    def test_f021_tasks_page_mine_and_open_agree_with_the_tile(self):
        item = self.item("E6.2")
        item.with_user(self.manager).assign_tasks(self.staff.id, "preparer")
        data = self.ui(self.staff).ea_ui_all_tasks(self.engagement.id)
        mine = [row for row in data["rows"] if row["mine"]]
        self.assertEqual([row["code"] for row in mine], ["E6.2"])
        self.assertEqual(len([row for row in mine if row["open"]]), 1)
        tile = self.ui(self.staff).ea_ui_dashboard(self.engagement.id)["my_tasks"]
        self.assertEqual(tile["count"], 1)
        self.assertGreater(len(data["rows"]), len(mine))

    def test_f021_an_outsider_gets_nothing(self):
        self.assertTrue(self.ui(self.outsider).ea_ui_all_tasks(self.engagement.id)["denied"])

    # ---- F029 ---------------------------------------------------------------------------

    def test_f029_the_session_carries_the_firm_clock(self):
        session = self.ui(self.staff)._ea_ui_shell_session()
        self.assertEqual((session["tz"], session["tz_label"]), ("Africa/Douala", "WAT"))

    # ---- F033 ---------------------------------------------------------------------------

    def test_f033_one_word_for_clearly_trivial(self):
        self.approve()
        item = self.item("P6.1").with_context(lang="fr_FR")
        board = item._ea_board_materiality(self.engagement.sudo())
        labels = [fact["label"] for fact in board["facts"]]
        self.assertIn("Anomalies manifestement négligeables", labels)
        self.assertFalse([label for label in labels if "lairement" in label])
        Version = self.env["ea.audit.materiality"].with_context(lang="fr_FR")
        words = Version.fields_get(["trivial", "trivial_pct"])
        self.assertIn("manifestement", words["trivial"]["string"])
        self.assertIn("manifestement", words["trivial_pct"]["string"])

    # ---- F023 ---------------------------------------------------------------------------

    def test_f023_c22_is_retitled_on_new_and_existing_files(self):
        item = self.item("C2.2")
        self.assertIn("Going Concern", item.title)
        self.assertIn("continuité", item.with_context(lang="fr_FR").title.lower())
        self.assertIn("continuité", item.with_context(lang="fr_FR").short_title.lower())

    # ---- an update on a firm with an archived file ---------------------------------------

    def test_an_unchanged_index_row_leaves_an_archived_file_alone(self):
        self.set_phase(self.engagement, "execution")
        self.item("E6.2").with_user(self.staff).action_sign("preparer")
        self.env.flush_all()
        self.cr.execute("UPDATE ea_audit_engagement SET archived_at = now() WHERE id = %s", [self.engagement.id])
        self.env.invalidate_all()
        template = self.item("E6.2").template_id
        # what the data file of a module update does
        template.write({"code": template.code, "section": template.section, "sequence": template.sequence, "tier": template.tier})
        self.env.flush_all()
        self.assertEqual(template.code, "E6.2")

    def test_f027_an_existing_firm_gets_its_trail_and_answers_in_the_log(self):
        self.paper("E6.2").with_user(self.staff).save_answers({"key_findings": "Un texte"})
        self.env.flush_all()
        Log = self.env["ea.audit.activity"].sudo()
        before = Log.search_count([("engagement_id", "=", self.engagement.id)])
        self.assertGreater(before, 1)
        self.cr.execute("DELETE FROM ea_audit_activity")
        self.env.invalidate_all()
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("ea_audit_core.activity_backfilled", "")
        params.set_param("ea_audit_papers.history_backfilled", "")
        Log._ea_backfill_trail()
        self.env["ea.audit.paper.answer.history"]._ea_backfill_audit_log()
        answer = Log.search([("field_key", "=", "key_findings"), ("code", "=", "E6.2")])
        self.assertEqual((answer.after, answer.user_id), ("Un texte", self.staff))
        self.assertTrue(Log.search_count([("action", "=", "paper_saved"), ("code", "=", "E6.2")]))
        # once only
        Log._ea_backfill_trail()
        self.assertEqual(Log.search_count([("action", "=", "paper_saved"), ("code", "=", "E6.2")]), 1)

    # ---- the extra defects --------------------------------------------------------------

    def test_a_year_is_not_an_amount(self):
        for xmlid in ("ea_audit_core.view_engagement_form", "ea_audit_core.view_engagement_list"):
            self.assertIn("enable_formatting", self.env.ref(xmlid).arch)
        arch = self.env["ir.ui.view"].search([("model", "=", "ea.audit.team.member")]).mapped("arch")
        self.assertTrue(all("enable_formatting" in text for text in arch if "invitation_fiscal_year" in text))

    def test_no_record_title_reads_as_model_and_id(self):
        """Every stored model of the addons: a name, or a display name of its own."""
        raw = []
        for name, model in self.env.items():
            if not name.startswith("ea.") or model._transient or model._abstract or not model._auto:
                continue
            if name in (model.new({}).display_name or ""):
                raw.append(name)
        self.assertEqual(raw, [])
        policy = self.env["ea.audit.signoff.policy"].with_user(self.partner).new({})
        self.assertEqual(policy.display_name, "Sign-off policy")

    def test_the_top_bar_gets_the_phase_of_the_paper(self):
        data = self.ui(self.staff).ea_ui_context("ea.audit.file.item", self.item("E6.2").id)
        self.assertEqual(data["item_section"], "execution")
        data = self.ui(self.staff).ea_ui_context("ea.audit.file.item", self.item("P3.1").id)
        self.assertEqual(data["item_section"], "acceptance")
        self.assertNotIn("item_section", self.ui(self.staff).ea_ui_context("ea.audit.engagement", self.engagement.id))

    def test_staff_get_no_save_button_on_the_firm_rules(self):
        for model in ("ea.audit.signoff.policy", "ea.audit.signoff.task.rule"):
            self.assertFalse(self.env[model].with_user(self.staff).has_access("write"), model)
            self.assertFalse(self.env[model].with_user(self.manager).has_access("write"), model)
            self.assertTrue(self.env[model].with_user(self.partner).has_access("write"), model)
            self.assertTrue(self.env[model].with_user(self.admin).has_access("write"), model)
        self.assertCode("signoff-policy-partner-only", self.env["ea.audit.signoff.policy"].with_user(self.staff).save_policy, "senior", [], True)

    def test_the_operator_log_is_kept_but_shown_to_no_firm_user(self):
        """Owner, 2026-11-07: the operator's access log leaves the firm's screens. The record stays."""
        self.assertNotIn("has_operator_log", self.ui(self.admin)._ea_ui_shell_session())
        if "ea.firm.access.log" not in self.env:
            return
        self.assertFalse(self.env.ref("ea_audit_firm_agent.action_ea_firm_access_log", raise_if_not_found=False))
        self.assertFalse(self.env.ref("ea_audit_firm_agent.menu_ea_firm_access_log", raise_if_not_found=False))
        Log = self.env["ea.firm.access.log"].sudo()
        Log.create({"logged_at": "2026-11-06 10:00:00", "event": "login", "account": "root", "source": "192.0.2.1"})
        self.assertTrue(Log.search_count([]))
        with mute_logger("odoo.addons.base.models.ir_model", "odoo.models"), self.assertRaises(AccessError):
            self.env["ea.firm.access.log"].with_user(self.partner).search([])

    def test_dsp_gap_label_reads_on_several_engagements(self):
        other = self.make_engagement(year=2024)
        self.seat(other, self.staff, "staff")
        self.env.invalidate_all()
        rows = self.env["ea.audit.engagement"].sudo().browse([self.engagement.id, other.id])
        rows.read(["dsp_gap_label"])
        self.assertTrue(rows[0].dsp_gap_label and rows[1].dsp_gap_label)
