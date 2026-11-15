"""Owner requests of 2026-11-15: figures written as an accountant writes them, a commentary
typed straight into its cell, and the Engagement team tile."""
from odoo import Command
from odoo.tests import tagged

from odoo.addons.ea_audit_tools.models.tool_record import decimal_label, fcfa, grouped
from odoo.addons.ea_audit_tools.wizards.gl_console_wizard import decimal, whole

from .common import ToolsCase


@tagged("post_install", "-at_install")
class TestFigures(ToolsCase):
    def test_a_negative_reads_in_brackets_and_fcfa_has_no_decimals(self):
        self.assertEqual(fcfa(-1234567.4, "en_US"), "(1,234,567) FCFA")
        self.assertEqual(fcfa(1234567.6, "en_US"), "1,234,568 FCFA")
        self.assertEqual(grouped(-2500, "fr_FR"), "(2 500)")
        self.assertEqual(decimal_label(-0.2, "en"), "(0.2)")
        self.assertEqual(decimal_label(-0.25, "fr"), "(0,25)")
        self.assertEqual(whole(-1000), "(1 000)")
        self.assertEqual(whole(-0.3), "0")
        self.assertEqual(decimal(-0.2, "en"), "(0.20)")


@tagged("post_install", "-at_install")
class TestCommentaryInline(ToolsCase):
    def _ratios(self, user):
        self.engagement.with_user(user).action_tool_financial()
        return self.env["ea.audit.fa.ratio"].with_user(user).search([("engagement_id", "=", self.engagement.id)])

    def test_financial_analysis_opens_grouped_and_expanded_with_commentary_open(self):
        self.import_tb()
        action = self.as_staff.action_tool_financial()
        self.assertEqual(action["context"].get("search_default_group_ratio"), 1)
        view = self.env.ref("ea_audit_tools.view_fa_ratio_list")
        arch = self.env["ea.audit.fa.ratio"].with_user(self.staff).get_view(view.id, "list")["arch"]
        self.assertIn('expand="1"', arch)
        self.assertIn('editable="bottom"', arch)
        self.assertNotIn('edit="false"', arch.lower())
        self.assertIn('readonly="ea_comment_locked"', arch)

    def test_who_may_type_a_ratio_commentary(self):
        self.import_tb()
        ratios = self._ratios(self.staff)
        self.assertTrue(ratios)
        self.assertFalse(any(ratios.mapped("ea_comment_locked")))
        ratios[0].write({"commentary": "Stable over the year"})
        self.assertEqual(self._ratios(self.staff)[0].commentary, "Stable over the year")
        self.assertTrue(all(self._ratios(self.reader).mapped("ea_comment_locked")))
        self.assertTrue(all(self._ratios(self.eqr).mapped("ea_comment_locked")))

    def test_an_archived_file_shows_its_commentary_read_only(self):
        self.import_tb()
        self.as_staff.action_tool_financial()
        self.engagement.sudo().write({"archived_at": "2026-01-01 00:00:00"})
        ratios = self.env["ea.audit.fa.ratio"].with_user(self.staff).search([("engagement_id", "=", self.engagement.id)])
        self.assertTrue(ratios)
        self.assertTrue(all(ratios.mapped("ea_comment_locked")))
        self.assertCode("archived", ratios[0].write, {"commentary": "too late"})

    def test_the_lead_board_saves_a_schedule_commentary_inline(self):
        self.import_tb()
        self.as_staff.action_tool_lead()
        schedule = self.as_staff.lead_schedule_ids[0]
        self.as_staff.write({"lead_schedule_ids": [Command.update(schedule.id, {"commentary": "Agreed to the ledger"})]})
        schedule.invalidate_recordset()
        self.assertEqual(schedule.commentary, "Agreed to the ledger")
        self.assertCode("invalid-field", self.as_staff.write, {"lead_schedule_ids": [Command.update(schedule.id, {"closing": 1})]})

    def test_the_schedule_form_saves_an_account_commentary_inline(self):
        self.import_tb()
        schedules = self.env["ea.audit.lead.schedule"].with_user(self.staff).search([("engagement_id", "=", self.engagement.id)])
        schedule = schedules.filtered("line_ids")[0]
        line = schedule.line_ids[0]
        schedule.write({"line_ids": [Command.update(line.id, {"commentary": "Seen the invoice"})]})
        line.invalidate_recordset()
        self.assertEqual(line.commentary, "Seen the invoice")
        self.assertCode("invalid-field", schedule.write, {"line_ids": [Command.update(line.id, {"closing": 1})]})
        self.assertCode("invalid-field", schedule.write, {"line_ids": [Command.delete(line.id)]})
        other = (schedules - schedule).filtered("line_ids")
        if other:
            self.assertCode("forbidden", schedule.write, {"line_ids": [Command.update(other[0].line_ids[0].id, {"commentary": "x"})]})
        self.assertCode("read-only-role", schedule.with_user(self.reader).write, {"line_ids": [Command.update(line.id, {"commentary": "x"})]})


@tagged("post_install", "-at_install")
class TestEngagementTeamTile(ToolsCase):
    def test_the_tile_opens_this_engagement_team(self):
        tile = self.env.ref("ea_audit_tools.tile_team").with_user(self.staff)
        self.assertEqual(tile.section, "hub")
        action = tile.with_context(ea_engagement_id=self.engagement.id).action_open_tool()
        self.assertEqual(action["res_model"], "ea.audit.team.member")
        self.assertEqual(action["domain"], [("engagement_id", "=", self.engagement.id)])
        members = self.env["ea.audit.team.member"].with_user(self.staff).search(action["domain"])
        self.assertIn(self.manager, members.mapped("user_id"))
        self.assertCode("not-on-this-engagement", tile.with_user(self.outsider).with_context(ea_engagement_id=self.engagement.id).action_open_tool)

    def test_a_manager_invites_from_the_list_and_staff_cannot(self):
        Member = self.env["ea.audit.team.member"]
        action = Member.with_user(self.manager).with_context(ea_engagement_id=self.engagement.id).action_ea_invite_member()
        self.assertEqual(action["res_model"], "ea.audit.team.invite.wizard")
        self.assertEqual(action["target"], "new")
        self.assertEqual(action["context"]["default_engagement_id"], self.engagement.id)
        self.assertCode("team-manager-only", Member.with_user(self.staff).with_context(ea_engagement_id=self.engagement.id).action_ea_invite_member)

    def test_only_a_manager_sees_the_role_open(self):
        domain = [("engagement_id", "=", self.engagement.id)]
        self.assertFalse(any(self.env["ea.audit.team.member"].with_user(self.manager).search(domain).mapped("ea_role_locked")))
        self.assertTrue(all(self.env["ea.audit.team.member"].with_user(self.staff).search(domain).mapped("ea_role_locked")))
        self.engagement.sudo().write({"archived_at": "2026-01-01 00:00:00"})
        self.assertTrue(all(self.env["ea.audit.team.member"].with_user(self.manager).search(domain).mapped("ea_role_locked")))

    def test_the_tile_reads_in_french(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        self.env["ir.module.module"].search([("name", "=", "ea_audit_tools")])._update_translations(["fr_FR"], overwrite=True)
        tile = self.env.ref("ea_audit_tools.tile_team").with_context(lang="fr_FR")
        self.assertEqual(tile.name, "Équipe de la mission")
