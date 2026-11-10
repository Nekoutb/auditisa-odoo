"""The pipeline, through its models and the real heartbeat receiver, on simulated firms."""

import ast
import json
import os
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import HttpCase, tagged

from odoo.addons.ea_platform_admin.services.heartbeat import HeartbeatRejected, format_instant
from odoo.addons.ea_platform_admin.services.simulator import healthy_figures, signed_request
from odoo.addons.ea_platform_admin.tests.common import PlatformCase, PlatformMixin

from .. import models as _models  # noqa: F401

ADDON = Path(__file__).parents[1]
REASON = "The owner tested staging and signed off."


class PipelineMixin:
    @classmethod
    def _setup_pipeline(cls):
        """Nothing to sign since 2026-11-10: a registered release is all a promotion needs."""

    def _on_staging(self, release=None):
        """The practice computer (Staging) runs this release, as its own heartbeat says."""
        computer = self.env["platform.practice.computer"]._current()
        if not computer:
            computer = self.env["platform.practice.computer"]._enrol("practice-1", token_path=None, simulation=True)
        computer.sudo().write({"desired_release_id": (release or self.release2).id})
        computer._simulate_heartbeat()
        return computer

    def _firm_on(self, slug, release=None, **changes):
        firm = self._active_firm(slug)
        now = format_instant(datetime.utcnow().replace(microsecond=0))
        firm._simulate_heartbeat(release=(release or self.release).sha, update_state="idle", last_backup_at=now, last_backup_ok=True, **changes)
        firm.flush_recordset()
        return firm

    def _staging(self, release=None, **changes):
        firm = self._firm_on("staging-server", release or self.release2, **changes)
        firm.sudo().pipeline_role = "staging"
        return firm

    def _green(self, release=None):
        self.env["platform.pipeline.test.run"].with_user(self.owner).create({
            "commit_sha": (release or self.release2).sha, "suite": "odoo", "passed": 100, "failed": 0,
        })

    def _promotion(self, canary, firms=None, release=None):
        return self.env["platform.pipeline.promotion"].with_user(self.owner).create({
            "release_id": (release or self.release2).id,
            "canary_firm_id": canary.id,
            "firm_ids": [(6, 0, (firms or canary).ids)],
        })

    def _confirm(self, wizard_action, typed=None, reason=REASON, **values):
        wizard = self.env["platform.pipeline.confirm"].with_user(self.owner).browse(wizard_action["res_id"])
        wizard.write({"typed": typed if typed is not None else wizard.expected, "reason": reason, **values})
        return wizard.action_confirm()


@tagged("post_install", "-at_install")
class TestPromotion(PipelineMixin, PlatformCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_pipeline()

    def _ready(self):
        canary = self._firm_on("cabinet-a")
        other = self._firm_on("cabinet-b")
        self._staging()
        self._green()
        return canary, other

    def test_no_signature_and_no_test_run_are_needed(self):
        canary = self._firm_on("cabinet-a")
        other = self._firm_on("cabinet-b")
        self.assertFalse(self.env["platform.pipeline.test.run"].search_count([("commit_sha", "=", self.release2.sha)]))
        self._on_staging()
        self.assertNotIn("attestation", self.release2._fields)
        self.assertNotIn("signer_id", self.release2._fields)
        promotion = self._promotion(canary, canary | other)
        promotion.action_run_checks()
        self.assertTrue(promotion.checks_ok, promotion.checks_text)
        self.assertIn("OK Staging runs this version", promotion.checks_text)

    def test_a_release_staging_does_not_run_is_not_promoted(self):
        canary, other = self._ready()
        self._on_staging(self.release)
        promotion = self._promotion(canary, canary | other)
        promotion.action_run_checks()
        self.assertFalse(promotion.checks_ok)
        self.assertIn("NO Staging runs another version", promotion.checks_text)
        with self.assertRaises(UserError):
            self._confirm(promotion.action_open_confirm())
        self.assertFalse(promotion.rollout_id)

    def test_it_will_not_start_with_a_failed_check(self):
        canary = self._firm_on("cabinet-a")
        self._on_staging(self.release)
        promotion = self._promotion(canary)
        action = promotion.action_open_confirm()
        with self.assertRaises(UserError):
            self._confirm(action)
        self.assertEqual(promotion.state, "draft")
        self.assertFalse(promotion.rollout_id)

    def test_the_wrong_phrase_starts_nothing(self):
        canary, other = self._ready()
        promotion = self._promotion(canary, canary | other)
        promotion.action_run_checks()
        self.assertTrue(promotion.checks_ok, promotion.checks_text)
        action = promotion.action_open_confirm()
        with self.assertRaises(UserError):
            self._confirm(action, typed="PROMOTE something-else")
        with self.assertRaises(UserError):
            self._confirm(action, reason="short")
        self.assertEqual(promotion.state, "draft")

    def test_the_whole_way_through_the_existing_rollout(self):
        canary, other = self._ready()
        promotion = self._promotion(canary, canary | other)
        promotion.action_run_checks()
        self.assertTrue(promotion.checks_ok, promotion.checks_text)
        self._confirm(promotion.action_open_confirm())
        self.assertEqual(promotion.state, "rolling")
        self.assertEqual(promotion.reason, REASON)
        rollout = promotion.rollout_id
        self.assertEqual(rollout.release_id, self.release2)
        self.assertEqual(rollout.line_ids.filtered(lambda line: line.state == "requested").firm_id, canary)
        rollout.action_simulate_answers()
        self.assertEqual(rollout.line_ids.filtered(lambda line: line.state == "requested").firm_id, other)
        rollout.action_simulate_answers()
        self.assertEqual(rollout.state, "done")
        self.assertEqual(promotion.state, "awaiting_main")
        self.assertIn(self.release2.sha, promotion.next_step)
        self._confirm(promotion.action_open_confirm_main())
        self.assertEqual(promotion.state, "done")
        self.assertTrue(promotion.main_moved_at)

    def test_it_stops_with_the_rollout_and_main_stays(self):
        canary, other = self._ready()
        promotion = self._promotion(canary, canary | other)
        promotion.action_run_checks()
        self._confirm(promotion.action_open_confirm())
        promotion.rollout_id.with_context(fail_slugs=[canary.slug]).action_simulate_answers()
        self.assertEqual(promotion.rollout_id.state, "stopped")
        self.assertEqual(promotion.state, "stopped")
        self.assertFalse(promotion.main_moved_at)
        with self.assertRaises(UserError):
            promotion.action_open_confirm_main()

    def test_the_staging_server_never_joins_a_rollout(self):
        canary = self._firm_on("cabinet-a")
        staging = self._staging()
        self._green()
        promotion = self._promotion(canary, canary | staging)
        promotion.action_run_checks()
        self._confirm(promotion.action_open_confirm())
        self.assertNotIn(staging, promotion.rollout_id.line_ids.firm_id)

    def test_rollback_goes_back_to_the_release_before_it(self):
        canary, other = self._ready()
        (canary | other).sudo().desired_release_id = self.release
        promotion = self._promotion(canary, canary | other)
        promotion.action_run_checks()
        self._confirm(promotion.action_open_confirm())
        rollout = promotion.rollout_id
        rollout.action_simulate_answers()
        rollout.action_simulate_answers()
        self.assertEqual(promotion.previous_release_id, self.release)
        result = promotion.action_prepare_rollback()
        rollback = self.env["platform.pipeline.promotion"].with_user(self.owner).browse(result["res_id"])
        self.assertEqual(rollback.kind, "rollback")
        self.assertEqual(rollback.release_id, self.release)
        rollback.action_run_checks()
        self.assertTrue(rollback.checks_ok, rollback.checks_text)
        self._confirm(rollback.action_open_confirm())
        rollback.rollout_id.action_simulate_answers()
        rollback.rollout_id.action_simulate_answers()
        self.assertEqual(rollback.state, "done")

    def test_only_the_owner_acts(self):
        canary, _other = self._ready()
        promotion = self._promotion(canary)
        for user in (self.viewer, self.operator):
            with self.assertRaises(UserError):
                promotion.with_user(user).action_run_checks()
            with self.assertRaises(UserError):
                promotion.with_user(user).action_open_confirm()
            with self.assertRaises(UserError):
                self.env["platform.pipeline.promotion"].with_user(user).create({
                    "release_id": self.release2.id, "canary_firm_id": canary.id,
                })

    def test_it_is_all_in_the_log(self):
        canary, other = self._ready()
        before = self.env["platform.log"].search_count([])
        promotion = self._promotion(canary, canary | other)
        promotion.action_run_checks()
        self._confirm(promotion.action_open_confirm())
        rows = self.env["platform.log"].search([], limit=self.env["platform.log"].search_count([]) - before)
        self.assertTrue(any("Promotion started" in row.action for row in rows))
        self.assertTrue(any(REASON in (row.detail or "") for row in rows))
        self.assertFalse(self.env["platform.log"]._chain_break())

    def test_test_runs_cannot_be_changed(self):
        self._green()
        run = self.env["platform.pipeline.test.run"].search([], limit=1).with_user(self.owner)
        with self.assertRaises(AccessError):
            run.write({"failed": 0})
        with self.assertRaises(AccessError):
            run.unlink()


@tagged("post_install", "-at_install")
class TestRebuild(PipelineMixin, PlatformCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_pipeline()

    def _ask(self, firm):
        action = self.env.ref("ea_platform_pipeline.stage_odoo_staging").with_user(self.owner).action_new_rebuild()
        wizard = self.env["platform.pipeline.confirm"].with_user(self.owner).browse(action["res_id"])
        wizard.source_firm_id = firm
        wizard.write({"typed": wizard.expected, "reason": REASON})
        result = wizard.action_confirm()
        return self.env["platform.pipeline.rebuild"].with_user(self.owner).browse(result["res_id"])

    def _answer_to(self, firm, **figures):
        """The real receiver: a signed heartbeat in, the answer out."""
        firm = firm.sudo()
        now = datetime.utcnow().replace(microsecond=0)
        body = healthy_figures(now, firm.addon_release)
        body.update(figures)
        timestamp = firm.last_heartbeat_timestamp + 1
        headers, raw = signed_request(firm.heartbeat_token, firm.slug, timestamp, body)
        with patch("odoo.addons.ea_platform_admin.services.heartbeat.check_freshness"):
            answer, _signature = self.env["platform.firm"]._receive_heartbeat(headers, raw)
        firm.flush_recordset()
        return json.loads(answer)

    def test_the_request_goes_out_in_the_heartbeat_answer(self):
        firm = self._firm_on("cabinet-a")
        self.assertNotIn("anon_export_ref", self._answer_to(firm))
        rebuild = self._ask(firm)
        self.assertEqual(self._answer_to(firm)["anon_export_ref"], rebuild.request_ref)
        self.assertRegex(rebuild.request_ref, r"^[0-9a-f]{16}$")

    def test_another_firm_is_not_asked(self):
        firm = self._firm_on("cabinet-a")
        other = self._firm_on("cabinet-b")
        self._ask(firm)
        self.assertNotIn("anon_export_ref", self._answer_to(other))

    def test_it_follows_the_firm_to_ready_and_keeps_only_a_digest(self):
        firm = self._firm_on("cabinet-a")
        rebuild = self._ask(firm)
        ref = rebuild.request_ref
        self._answer_to(firm, anon_export_state="running", anon_export_ref=ref)
        self.assertEqual(rebuild.state, "running")
        self.assertNotIn("anon_export_ref", self._answer_to(firm, anon_export_state="running", anon_export_ref=ref))
        self._answer_to(firm, anon_export_state="done", anon_export_ref=ref, anon_export_sha256="c" * 64,
                        anon_export_at=format_instant(datetime.utcnow().replace(microsecond=0)))
        self.assertEqual(rebuild.state, "exported")
        self.assertEqual(rebuild.export_sha256, "c" * 64)
        self.assertIn(ref, rebuild.next_step)
        self._confirm(rebuild.action_open_confirm_rebuilt())
        self.assertEqual(rebuild.state, "rebuilt")

    def test_a_refusal_at_the_firm_is_recorded(self):
        firm = self._firm_on("cabinet-a")
        rebuild = self._ask(firm)
        self._answer_to(firm, anon_export_state="refused", anon_export_ref=rebuild.request_ref)
        self.assertEqual(rebuild.state, "refused")

    def test_free_text_in_the_new_figures_is_refused_and_not_kept(self):
        firm = self._firm_on("cabinet-a")
        self._ask(firm)
        with self.assertRaises(HeartbeatRejected):
            self._answer_to(firm, anon_export_state="done", anon_export_ref="Societe Agro SA")
        self.env.flush_all()
        self.env.cr.execute("SELECT count(*) FROM platform_firm WHERE anon_export_ref LIKE %s", ["%Agro%"])
        self.assertEqual(self.env.cr.fetchone()[0], 0)

    def test_one_rebuild_at_a_time(self):
        firm = self._firm_on("cabinet-a")
        self._ask(firm)
        with self.assertRaises(UserError):
            self._ask(firm)

    def test_staging_cannot_be_its_own_source(self):
        staging = self._staging()
        with self.assertRaises(UserError):
            self._ask(staging)

    def test_the_wrong_phrase_asks_nothing(self):
        firm = self._firm_on("cabinet-a")
        action = self.env.ref("ea_platform_pipeline.stage_odoo_staging").with_user(self.owner).action_new_rebuild()
        wizard = self.env["platform.pipeline.confirm"].with_user(self.owner).browse(action["res_id"])
        wizard.source_firm_id = firm
        wizard.write({"typed": "REBUILD another-firm", "reason": REASON})
        with self.assertRaises(UserError):
            wizard.action_confirm()
        self.assertFalse(self.env["platform.pipeline.rebuild"].search_count([]))

    def test_only_the_owner_asks(self):
        for user in (self.viewer, self.operator):
            with self.assertRaises(UserError):
                self.env.ref("ea_platform_pipeline.stage_odoo_staging").with_user(user).action_new_rebuild()


@tagged("post_install", "-at_install")
class TestBoardAndPublicState(PipelineMixin, PlatformCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_pipeline()

    def _write_state(self, data):
        handle = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, handle)
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        self.env["ir.config_parameter"].sudo().set_param("ea_platform_pipeline.state_file", handle.name)

    def _state(self, **odoo):
        now = datetime.utcnow().replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
        commit = lambda sha: {"sha": sha, "author": "Nekoutb", "at": now}  # noqa: E731
        return {
            "schema": 1, "generated": now,
            "next": {"github": "ok", "branches": {"dev": commit("1" * 40), "main": commit("2" * 40)},
                     "running": {"staging": commit("1" * 40), "production": commit("2" * 40)},
                     "ahead": {"development_over_staging": 0, "staging_over_production": 36, "main_over_production": 0},
                     "sites": {"staging": {"up": True, "started_at": now}, "production": {"up": True, "started_at": now}}},
            "odoo": {"github": "ok", "branches": {"dev": commit("3" * 40), "main": commit(self.release.sha + "0" * 28)},
                     "running": {"staging": commit("3" * 40)}, "ahead": {"development_over_staging": 0, "staging_over_main": 5},
                     "sites": {"staging": {"up": True, "mail_off": True, "band_on": True}}, **odoo},
        }

    def test_the_one_status_tab_opens_this_screen(self):
        menus = self.env["ir.ui.menu"].search([("parent_id", "=", self.env.ref("ea_platform_admin.menu_root").id)]).sorted("sequence")
        self.assertEqual(menus[:2].mapped("name"), ["Supervision", "Status"])
        self.assertEqual(self.env.ref("ea_platform_admin.menu_status").action, self.env.ref("ea_platform_pipeline.action_environments"))
        self.assertEqual(len(menus.filtered(lambda m: m.name == "Status")), 1)

    def test_both_tools_three_stages_each(self):
        stages = self.env["platform.pipeline.stage"].with_user(self.viewer).search([])
        self.assertEqual(stages.mapped("tool"), ["next"] * 3 + ["odoo"] * 3)
        self.assertEqual(stages.mapped("code"), ["development", "staging", "production"] * 2)

    def test_the_board_reads_github_and_the_sites(self):
        self._write_state(self._state())
        stages = {(s.tool, s.code): s for s in self.env["platform.pipeline.stage"].with_user(self.viewer).search([])}
        nxt = stages[("next", "staging")]
        self.assertEqual(nxt.github_commit, "1" * 12)
        self.assertEqual(nxt.running_commit, "1" * 12)
        self.assertEqual(nxt.matches, "yes")
        self.assertIn("36", nxt.ahead)
        self.assertEqual(nxt.github_author, "Nekoutb")
        self.assertEqual(stages[("odoo", "staging")].matches, "yes")
        self.assertIn("5", stages[("odoo", "staging")].ahead)
        self.assertIn("No staging branch yet", stages[("odoo", "staging")].detail)
        self.assertIn("No firm server", stages[("odoo", "production")].where)
        self.assertIn("at most a minute", nxt.reading)

    def test_the_buttons_are_on_the_odoo_tool_only(self):
        self._write_state(self._state())
        stages = self.env["platform.pipeline.stage"].with_user(self.owner).search([])
        self.assertEqual(
            {(s.tool, s.code) for s in stages if s.can_promote or s.can_rebuild},
            {("odoo", "staging"), ("odoo", "production")},
        )
        for stage in stages.filtered(lambda s: s.tool == "next"):
            self.assertFalse(stage.action_new_promotion())
            self.assertFalse(stage.action_new_rebuild())

    def test_no_file_shows_sample_data_and_says_so(self):
        self.env["ir.config_parameter"].sudo().set_param("ea_platform_pipeline.state_file", "/nonexistent/state.json")
        stages = self.env["platform.pipeline.stage"].with_user(self.viewer).search([])
        for stage in stages:
            self.assertTrue(stage.is_sample)
            self.assertIn("SAMPLE DATA", stage.reading)
        production = stages.filtered(lambda s: s.tool == "next" and s.code == "production")
        self.assertTrue(production.github_commit)
        self.assertIn("10.1 MB", production.backups)

    def test_the_current_tools_figures_show(self):
        state = self._state()
        state["next"]["figures"] = {"production": {"deploys": [{"sha": "2" * 40, "at": "2026-09-23T07:08:13Z"}],
                                                   "backups": [{"at": "2026-11-07T02:17:08Z", "size": "10.1 MB"}],
                                                   "migrations": 85, "pending": 0}}
        self._write_state(state)
        production = self.env.ref("ea_platform_pipeline.stage_next_production").with_user(self.viewer)
        self.assertFalse(production.is_sample)
        self.assertIn("2222222  2026-09-23 07:08", production.deploys)
        self.assertIn("10.1 MB", production.backups)
        self.assertIn("85", production.migrations)

    def test_a_missing_key_is_said_plainly(self):
        self._write_state(self._state(github="no_key", branches={}))
        odoo = self.env["platform.pipeline.stage"].with_user(self.viewer).search([("tool", "=", "odoo"), ("code", "=", "development")])
        self.assertIn("not set up", odoo.detail)

    def test_mail_on_at_staging_turns_it_red(self):
        self._write_state(self._state(sites={"staging": {"up": True, "mail_off": False, "band_on": True}}))
        odoo = self.env["platform.pipeline.stage"].with_user(self.viewer).search([("tool", "=", "odoo"), ("code", "=", "staging")])
        self.assertEqual(odoo.color, "red")
        self.assertIn("check mail", odoo.health)

    def test_enrolling_staging_keeps_the_token_in_a_root_only_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "token")
            firm = self.env["platform.firm"]._pipeline_enrol_staging(path)
            self.assertEqual(firm.pipeline_role, "staging")
            self.assertEqual(firm.state, "active")
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            with open(path, encoding="ascii") as handle:
                self.assertEqual(handle.read().strip(), firm.sudo().heartbeat_token)
            self.assertEqual(self.env["platform.firm"]._pipeline_enrol_staging(path), firm)
        rows = self.env["platform.log"].search([("firm_id", "=", firm.id)])
        self.assertFalse([row for row in rows if firm.sudo().heartbeat_token in (row.detail or "")])

    def test_a_staging_alert_is_silent(self):
        staging = self._staging()
        count = self.env["mail.message"].sudo().search_count([("model", "=", "platform.firm"), ("res_id", "=", staging.id)])
        staging._alert(["anything"])
        self.assertEqual(self.env["mail.message"].sudo().search_count([("model", "=", "platform.firm"), ("res_id", "=", staging.id)]), count)

    def test_the_addon_has_no_way_to_reach_a_firm_or_github(self):
        forbidden = {"paramiko", "fabric", "xmlrpc", "odoorpc", "asyncssh", "subprocess", "socket", "ftplib", "smtplib", "telnetlib", "requests", "urllib"}
        for path in ADDON.rglob("*.py"):
            if "tests" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    names = [node.module.split(".")[0]]
                self.assertFalse(forbidden & set(names), f"{path.name}: {names}")

    def test_the_manifest_depends_on_the_platform_only(self):
        manifest = ast.literal_eval((ADDON / "__manifest__.py").read_text(encoding="utf-8"))
        self.assertEqual(manifest["depends"], ["ea_platform_admin"])


@tagged("post_install", "-at_install")
class TestOwnerAddress(PipelineMixin, PlatformMixin, HttpCase):
    """The owner's address list for Promote and Rebuild: optional, and binding once written."""

    def _ask_rebuild(self):
        stage = self.env.ref("ea_platform_pipeline.stage_odoo_staging")
        return self.make_jsonrpc_request("/web/dataset/call_kw/platform.pipeline.stage/action_new_rebuild", {
            "model": "platform.pipeline.stage", "method": "action_new_rebuild", "args": [stage.ids], "kwargs": {},
        })

    def _owner_addresses(self, value):
        self.env["ir.config_parameter"].sudo().set_param("ea_platform_pipeline.owner_addresses", value)

    def test_an_address_outside_the_list_changes_nothing(self):
        self._setup_platform()
        self.authenticate("p_owner", "p_owner")
        self._owner_addresses("143.105.152.209/32")
        with self.assertRaises(Exception):
            self._ask_rebuild()
        self.assertFalse(self.env["platform.pipeline.rebuild"].search_count([]))

    def test_a_list_with_no_valid_range_refuses_everything(self):
        self._setup_platform()
        self.authenticate("p_owner", "p_owner")
        self._owner_addresses("not-an-address")
        with self.assertRaises(Exception):
            self._ask_rebuild()

    def test_the_owners_address_goes_through(self):
        self._setup_platform()
        self.authenticate("p_owner", "p_owner")
        # The test server answers on 127.0.0.1.
        self._owner_addresses("127.0.0.0/8 143.105.152.209/32")
        self.assertEqual(self._ask_rebuild()["res_model"], "platform.pipeline.confirm")

    def test_no_list_means_no_address_check(self):
        """The owner's ruling of 2026-11-08: the control room opens from anywhere. Sign-in still counts."""
        self._setup_platform()
        self._owner_addresses(False)
        # The firm servers' port-22 list is another matter, and no longer gates these buttons.
        self.patch(type(self.env["platform.firm"]), "_ssh_allowlist", lambda _self: ["143.105.152.209/32"])
        self.authenticate("p_owner", "p_owner")
        self.assertEqual(self._ask_rebuild()["res_model"], "platform.pipeline.confirm")

    def test_no_list_still_needs_the_owner(self):
        self._setup_platform()
        self._owner_addresses(False)
        self.authenticate("p_operator", "p_operator")
        with self.assertRaises(Exception):
            self._ask_rebuild()
        self.assertFalse(self.env["platform.pipeline.rebuild"].search_count([]))
