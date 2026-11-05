from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import PlatformCase


@tagged("post_install", "-at_install")
class TestRollout(PlatformCase):
    def setUp(self):
        super().setUp()
        self.a = self._active_firm("cabinet-a")
        self.b = self._active_firm("cabinet-b")
        self.c = self._active_firm("cabinet-c")
        self.d = self._active_firm("cabinet-d")
        self.firms = self.a | self.b | self.c | self.d

    def _rollout(self, canary=None, firms=None, batch=2):
        return self.env["platform.rollout"].with_user(self.operator).create({
            "release_id": self.release2.id,
            "canary_firm_id": (canary or self.a).id,
            "firm_ids": [(6, 0, (firms or self.firms).ids)],
            "batch_size": batch,
        })

    def _state_by_slug(self, rollout):
        return {line.firm_id.slug: line.state for line in rollout.line_ids}

    def test_only_the_canary_is_asked_first(self):
        rollout = self._rollout()
        rollout.action_start()
        self.assertEqual(rollout.state, "running")
        self.assertEqual(self.a.desired_release_id, self.release2)
        self.assertEqual(self.b.desired_release_id, self.release)
        self.assertEqual(self.a._heartbeat_answer()["desired_release"], self.release2.sha)
        self.assertEqual(self.b._heartbeat_answer()["desired_release"], self.release.sha)
        self.assertEqual(self._state_by_slug(rollout)["cabinet-a"], "requested")
        self.assertEqual(self._state_by_slug(rollout)["cabinet-b"], "pending")

    def test_it_runs_to_the_end_batch_by_batch(self):
        rollout = self._rollout(batch=2)
        rollout.action_start()
        rollout.action_simulate_answers()
        batch1 = rollout.line_ids.filtered(lambda l: l.batch == 1)
        self.assertEqual(set(batch1.mapped("state")), {"requested"})
        self.assertEqual(len(batch1), 2)
        rollout.action_simulate_answers()
        rollout.action_simulate_answers()
        self.assertEqual(rollout.state, "done")
        self.assertEqual(set(rollout.line_ids.mapped("state")), {"healthy"})
        self.assertEqual(set(self.firms.mapped("addon_release")), {self.release2.sha})
        self.assertIn("Rollout finished", self.a.log_ids.mapped("action"))

    def test_it_stops_at_a_canary_failure_and_asks_nobody_else(self):
        rollout = self._rollout()
        rollout.action_start()
        rollout.with_context(fail_slugs=["cabinet-a"]).action_simulate_answers()
        self.assertEqual(rollout.state, "stopped")
        self.assertIn("cabinet-a", rollout.stop_reason)
        states = self._state_by_slug(rollout)
        self.assertEqual(states["cabinet-a"], "rolled_back")
        self.assertEqual({states[s] for s in ("cabinet-b", "cabinet-c", "cabinet-d")}, {"cancelled"})
        for firm in self.b | self.c | self.d:
            self.assertEqual(firm.desired_release_id, self.release)

    def test_a_failed_firm_goes_back_to_its_previous_release_and_is_not_asked_again(self):
        rollout = self._rollout()
        rollout.action_start()
        rollout.with_context(fail_slugs=["cabinet-a"]).action_simulate_answers()
        self.assertEqual(self.a.desired_release_id, self.release)
        self.assertEqual(self.a._heartbeat_answer()["desired_release"], self.release.sha)
        self.assertEqual(self.a.addon_release, self.release.sha)

    def test_a_failure_in_a_later_batch_stops_the_following_ones(self):
        rollout = self._rollout(batch=1)
        rollout.action_start()
        rollout.action_simulate_answers()
        second = rollout.line_ids.filtered(lambda l: l.batch == 1)
        rollout.with_context(fail_slugs=[second.firm_id.slug]).action_simulate_answers()
        self.assertEqual(rollout.state, "stopped")
        self.assertEqual(len(rollout.line_ids.filtered(lambda l: l.state == "healthy")), 1)
        self.assertEqual(len(rollout.line_ids.filtered(lambda l: l.state == "cancelled")), 2)

    def test_it_counts_as_failed_without_a_backup_after_the_request(self):
        rollout = self._rollout()
        rollout.action_start()
        yesterday = fields.Datetime.now() - timedelta(hours=20)
        self.a._simulate_heartbeat(
            release=self.release2.sha, update_state="ok", update_release=self.release2.sha,
            last_backup_at=yesterday.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        self.assertEqual(self._state_by_slug(rollout)["cabinet-a"], "failed")
        self.assertEqual(rollout.state, "stopped")

    def test_silence_ends_in_a_timeout_and_a_stop(self):
        rollout = self._rollout()
        rollout.action_start()
        rollout.line_ids.filtered(lambda l: l.firm_id == self.a).sudo().write({
            "requested_at": fields.Datetime.now() - timedelta(hours=3),
        })
        self.env["platform.rollout"]._cron_advance()
        self.assertEqual(rollout.state, "stopped")
        self.assertEqual(self._state_by_slug(rollout)["cabinet-a"], "timed_out")
        self.assertEqual(self.a.desired_release_id, self.release)

    def test_a_locked_firm_is_set_aside_and_said_so(self):
        self.b.release_locked = True
        rollout = self._rollout()
        rollout.action_start()
        self.assertIn("locked", rollout.skipped)
        self.assertNotIn("cabinet-b", self._state_by_slug(rollout))

    def test_a_firm_without_a_good_backup_is_set_aside(self):
        self.b.sudo().write({"last_backup_ok": False})
        self.b._evaluate_health()
        rollout = self._rollout()
        rollout.action_start()
        self.assertIn(self.b.name, rollout.skipped)

    def test_a_red_canary_is_refused(self):
        self.a.sudo().write({"last_backup_ok": False})
        self.a._evaluate_health()
        with self.assertRaisesRegex(UserError, "canary"):
            self._rollout().action_start()

    def test_a_canary_already_on_the_release_is_refused(self):
        self.a._simulate_heartbeat(release=self.release2.sha)
        with self.assertRaisesRegex(UserError, "already on this release"):
            self._rollout().action_start()

    def test_one_rollout_at_a_time(self):
        self._rollout().action_start()
        with self.assertRaisesRegex(UserError, "only one at a time"):
            self._rollout(canary=self.b).action_start()

    def test_it_cannot_start_twice(self):
        rollout = self._rollout()
        rollout.action_start()
        with self.assertRaises(UserError):
            rollout.action_start()

    def test_a_viewer_cannot_start_one(self):
        with self.assertRaises(AccessError):
            self.env["platform.rollout"].with_user(self.viewer).create({
                "release_id": self.release2.id, "canary_firm_id": self.a.id,
            })

    def test_simulated_answers_are_refused_on_a_real_firm(self):
        rollout = self._rollout()
        rollout.action_start()
        self.a.sudo().is_simulation = False
        with self.assertRaisesRegex(UserError, "simulation"):
            rollout.action_simulate_answers()

    def test_every_request_is_in_the_log(self):
        self._rollout().action_start()
        rows = self.a.log_ids.filtered(lambda r: r.action == "Update requested from the firm")
        self.assertEqual(len(rows), 1)
        self.assertIn(self.release2.sha[:12], rows.detail)


@tagged("post_install", "-at_install")
class TestRelease(PlatformCase):
    def test_a_release_must_look_right(self):
        model = self.env["platform.release"].with_user(self.owner)
        with self.assertRaises(ValidationError):
            model.create({"sha": "pas-un-commit", "bundle_sha256": "a" * 64})
        with self.assertRaises(ValidationError):
            model.create({"sha": "abc123abc123abc", "bundle_sha256": "court"})

    def test_only_the_owner_registers_a_release(self):
        with self.assertRaises(AccessError):
            self.env["platform.release"].with_user(self.operator).create({"sha": "a" * 12, "bundle_sha256": "a" * 64})

    def test_it_counts_firms_on_it(self):
        self._active_firm()
        self.release.invalidate_recordset()
        self.assertEqual(self.release.firm_count, 1)
