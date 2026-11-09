from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.http import request

from odoo.addons.ea_platform_admin.services.messages import _, dumps_list
from ..services import pipeline
from .i18n import read, t

STATES = [
    ("draft", "To check"),
    ("rolling", "Rolling out"),
    ("awaiting_main", "Move main"),
    ("done", "Finished"),
    ("stopped", "Stopped on failure"),
]
KINDS = [("promote", "Promotion"), ("rollback", "Rollback")]
OWNER_ADDRESSES_PARAM = "ea_platform_pipeline.owner_addresses"


class PlatformPipelineMixin(models.AbstractModel):
    _name = "platform.pipeline.guard"
    _description = "Who may act on the pipeline, and from where"

    def _require_owner(self):
        """The owner, signed in. And, if the owner keeps a list of addresses, from one of them.

        The list is the system parameter ea_platform_pipeline.owner_addresses. Empty, the default, means
        no address check: the owner's ruling of 2026-11-08 (the control room opens from anywhere).
        """
        if not self.env.user.has_group("ea_platform_admin.group_platform_owner"):
            raise UserError(t(self.env, _("Only the owner can do this.")))
        if not request:
            return  # Odoo shell and tests have no address to check.
        cidrs = pipeline.owner_addresses(self.env["ir.config_parameter"].sudo().get_param(OWNER_ADDRESSES_PARAM, ""))
        address = request.httprequest.remote_addr
        if not pipeline.owner_address_ok(address, cidrs):
            raise UserError(t(self.env, _(
                "This address (%(address)s) is not one of the owner's: nothing was done. "
                "The owner's addresses are the system parameter ea_platform_pipeline.owner_addresses.",
                address=address or "?",
            )))


class PlatformPipelinePromotion(models.Model):
    """Staging's commit going to the firms: a release signed offline, then the existing rollout.

    `main` moves last, by the owner's own hand, once every firm runs the release: it then always says
    what the firms run. The control plane has no write access to GitHub and no signing key.
    """

    _name = "platform.pipeline.promotion"
    _description = "Promotion"
    _inherit = ["platform.pipeline.guard"]
    _order = "id desc"
    _rec_name = "release_id"

    kind = fields.Selection(KINDS, "Kind", default="promote", required=True, readonly=True)
    release_id = fields.Many2one("platform.release", "Release", required=True, ondelete="restrict")
    previous_release_id = fields.Many2one("platform.release", "Release before it", readonly=True, ondelete="restrict")
    canary_firm_id = fields.Many2one(
        "platform.firm", "Test firm", required=True, ondelete="restrict",
        domain=[("state", "=", "active"), ("pipeline_role", "=", "firm")],
        help="The firm that goes first, alone. The others wait for its result.",
    )
    firm_ids = fields.Many2many(
        "platform.firm", string="Firms", domain=[("state", "=", "active"), ("pipeline_role", "=", "firm")],
    )
    batch_size = fields.Integer("Batch size", default=2, required=True)
    state = fields.Selection(STATES, "State", default="draft", required=True, readonly=True)
    checks_raw = fields.Text("Pre-checks (source)", readonly=True, copy=False)
    checks_ok = fields.Boolean("Every pre-check passed", readonly=True, copy=False)
    checks_at = fields.Datetime("Checked on", readonly=True, copy=False)
    checks_text = fields.Text("Pre-checks", compute="_compute_checks_text")
    reason = fields.Text("Reason", readonly=True, copy=False)
    started_by_id = fields.Many2one("res.users", "Started by", readonly=True, copy=False)
    started_at = fields.Datetime("Started on", readonly=True, copy=False)
    rollout_id = fields.Many2one("platform.rollout", "Rollout", readonly=True, copy=False, ondelete="restrict")
    rollout_state = fields.Selection(related="rollout_id.state", string="Rollout state")
    main_moved_at = fields.Datetime("main moved on", readonly=True, copy=False)
    next_step = fields.Text("What you do now", compute="_compute_next_step")
    rollout_line_ids = fields.One2many(related="rollout_id.line_ids", string="Result, firm by firm")
    # The practice-first rule: 7 days on the practice computer, or the owner's written, logged exception.
    hold_override = fields.Boolean("Practice wait skipped", readonly=True, copy=False)
    hold_override_reason = fields.Text("Why the wait was skipped", readonly=True, copy=False)
    hold_override_by_id = fields.Many2one("res.users", "Skipped by", readonly=True, copy=False)
    hold_override_at = fields.Datetime("Skipped on", readonly=True, copy=False)
    hold_ok = fields.Boolean("Practice wait respected", compute="_compute_hold")
    hold_text = fields.Char("Practice wait", compute="_compute_hold")

    @api.depends("release_id", "hold_override")
    @api.depends_context("lang")
    def _compute_hold(self):
        for promotion in self:
            if not promotion.release_id:
                promotion.hold_ok, promotion.hold_text = False, False
                continue
            ok, message = promotion._hold_check()
            promotion.hold_ok = ok
            promotion.hold_text = t(self.env, message)

    def _hold_check(self):
        """(ok, message): the release's holding period on the practice computer, or the owner's exception."""
        self.ensure_one()
        if self.hold_override:
            return True, _("Practice wait skipped by the owner: %(reason)s", reason=self.hold_override_reason or "")
        ok, _until, message = self.release_id.sudo()._practice_hold(fields.Datetime.now())
        return ok, message

    @api.depends("checks_raw")
    @api.depends_context("lang")
    def _compute_checks_text(self):
        for promotion in self:
            promotion.checks_text = read(self.env, promotion.checks_raw)

    @api.depends("state", "release_id")
    @api.depends_context("lang")
    def _compute_next_step(self):
        for promotion in self:
            sha = promotion.release_id.sha or ""
            if promotion.state == "awaiting_main":
                promotion.next_step = t(self.env, _(
                    "Every firm runs this release. On your computer: git push origin %(sha)s:refs/heads/main, then Confirm main moved.",
                    sha=sha))
            elif promotion.state == "stopped":
                promotion.next_step = t(self.env, _(
                    "The rollout stopped. The failed firm put itself back. main has not moved. See docs/runbook/PIPELINE.md."))
            else:
                promotion.next_step = False

    def _target_firms(self):
        self.ensure_one()
        return (self.firm_ids | self.canary_firm_id).sudo().filtered(lambda firm: firm.pipeline_role == "firm")

    def _collect_checks(self):
        """Each pre-check as a dict: code, ok, detail. A rollback goes back to something already signed
        and proven, so it needs no new test run and no staging check."""
        self.ensure_one()
        now = fields.Datetime.now()
        release = self.release_id
        checks = []
        checks.append(pipeline.check(
            "signed", release.attestation_ok,
            _("Signed offline: the attestation holds for this commit and digest.") if release.attestation_ok
            else _("No valid offline attestation for this release: run sign_promotion.sh on your computer."),
        ))
        if self.kind == "promote":
            # The release order: the practice computer first, the firms after its holding period.
            hold_ok, hold_message = self._hold_check()
            checks.append(pipeline.check("practice", hold_ok, hold_message))
            runs = self.env["platform.pipeline.test.run"].sudo().search([("commit_sha", "=like", release.sha[:7] + "%")])
            matching = [
                {"suite": run.suite, "passed": run.passed, "failed": run.failed}
                for run in runs if pipeline.same_commit(run.commit_sha, release.sha)
            ]
            checks.append(pipeline.test_check(matching))
            checks.append(pipeline.staging_check(self.env["platform.firm"]._staging_figures(), release.sha, now))
        firms = self._target_firms()
        checks.append(pipeline.backup_check(
            [{"name": firm.name, "last_backup_at": firm.last_backup_at, "last_backup_ok": firm.last_backup_ok} for firm in firms],
            now,
        ))
        canary = self.canary_firm_id.sudo()
        canary_ok = canary.pipeline_role == "firm" and canary.addon_release != release.sha
        checks.append(pipeline.check(
            "canary", canary_ok,
            _("The test firm can go first.") if canary_ok else _("The test firm is the staging server, or already on this release."),
        ))
        running = self.env["platform.rollout"].sudo().search_count([("state", "=", "running")])
        checks.append(pipeline.check(
            "alone", not running,
            _("No other rollout is running.") if not running else _("Another rollout is running: only one at a time."),
        ))
        return checks

    def action_run_checks(self):
        self.ensure_one()
        self._require_owner()
        if self.state != "draft":
            raise UserError(t(self.env, _("This promotion has already started.")))
        checks = self._collect_checks()
        lines = [
            _("%(mark)s %(detail)s", mark="OK" if item["ok"] else "NO", detail=item["detail"]) for item in checks
        ]
        passed = all(item["ok"] for item in checks)
        self.write({"checks_raw": dumps_list(lines), "checks_ok": passed, "checks_at": fields.Datetime.now()})
        self.env["platform.log"]._record(
            _("Promotion pre-checks: passed") if passed else _("Promotion pre-checks: not passed"),
            None, _("Release %(release)s", release=self.release_id.sha[:12]),
        )
        return True

    def action_open_confirm(self):
        self.ensure_one()
        self._require_owner()
        return self.env["platform.pipeline.confirm"]._open(self, "rollback" if self.kind == "rollback" else "promote", self.release_id.sha[:12])

    def _confirmed(self, kind, reason):
        """After the typed confirmation. The checks run again: minutes may have passed."""
        self.ensure_one()
        self._require_owner()
        if self.state != "draft":
            raise UserError(t(self.env, _("This promotion has already started.")))
        self.action_run_checks()
        if not self.checks_ok:
            raise UserError(t(self.env, _("A pre-check does not pass: nothing was started.")) + "\n" + self.checks_text)
        firms = self._target_firms()
        previous = firms.desired_release_id[:1]
        rollout = self.env["platform.rollout"].sudo().create({
            "release_id": self.release_id.id,
            "canary_firm_id": self.canary_firm_id.id,
            "firm_ids": [(6, 0, firms.ids)],
            "batch_size": self.batch_size,
        })
        # A rollback goes back to a release the firms already ran: no holding period again.
        rollout.with_context(ea_practice_hold_skip=self.kind == "rollback" or self.hold_override).action_start()
        self.write({
            "state": "rolling",
            "reason": reason,
            "started_by_id": self.env.user.id,
            "started_at": fields.Datetime.now(),
            "rollout_id": rollout.id,
            "previous_release_id": previous.id if previous and previous != self.release_id else False,
        })
        self.env["platform.log"]._record(
            _("Rollback started") if self.kind == "rollback" else _("Promotion started"), self.canary_firm_id,
            _("Release %(release)s, reason: %(reason)s", release=self.release_id.sha[:12], reason=reason),
        )
        return True

    @api.model
    def _sync_from_rollouts(self, rollouts):
        """Follows the rollout it started. `main` is the owner's own step, once the firms are through."""
        promotions = self.sudo().search([("rollout_id", "in", rollouts.ids), ("state", "=", "rolling")])
        for promotion in promotions:
            if promotion.rollout_id.state == "done":
                promotion.state = "done" if promotion.kind == "rollback" else "awaiting_main"
                self.env["platform.log"]._record(
                    _("Promotion: every firm is through"), None, _("Release %(release)s", release=promotion.release_id.sha[:12]),
                )
            elif promotion.rollout_id.state == "stopped":
                promotion.state = "stopped"
                self.env["platform.log"]._record(
                    _("Promotion stopped"), promotion.canary_firm_id, _("Release %(release)s", release=promotion.release_id.sha[:12]),
                )

    def _change_summary(self):
        """Exactly what will change, for the confirmation screen: from, to, which firms, the list of changes."""
        self.ensure_one()
        from markupsafe import Markup

        from ..services import environments as envs
        from ..wizard.environment import _changes
        from .environment import _table

        env = self.env
        firms = self._target_firms()
        installed = sorted({firm.addon_release[:12] for firm in firms if firm.addon_release})
        canary = self.canary_firm_id.sudo()
        others = (firms - canary).mapped("name")
        rows = [
            [t(env, _("From")), ", ".join(installed) or "?"],
            [t(env, _("To")), Markup("<code>%s</code>") % self.release_id.display_name],
            [t(env, _("Test firm, alone first")), canary.name or ""],
            [t(env, _("Then, in batches of %(size)s", size=self.batch_size)), ", ".join(others) or t(env, _("no other firm"))],
            [t(env, _("Practice wait")), self.hold_text or ""],
            [t(env, _("Backup")), t(env, _("Each firm's server backs itself up just before it updates. Without that fresh backup the update counts as failed and the rollout stops."))],
        ]
        log = (((env["platform.environment"]._pipeline_state() or {}).get("odoo") or {}).get("log") or {})
        old = installed[0] if len(installed) == 1 else None
        changes = None
        for branch in ("main", "staging", "dev"):
            changes = envs.changes_between(log.get(branch), old, self.release_id.sha)
            if changes:
                break
        return _table([t(env, _("What")), t(env, _("Value"))], rows, "") + _changes(env, changes, self.release_id)

    def action_open_confirm_override(self):
        """The owner's exception to the 7 days on practice: a typed word and a written reason, both logged."""
        self.ensure_one()
        self._require_owner()
        if self.state != "draft" or self.kind != "promote":
            raise UserError(t(self.env, _("The practice wait can be skipped only before a promotion starts.")))
        if self.hold_override:
            raise UserError(t(self.env, _("The practice wait is already skipped for this promotion.")))
        return self.env["platform.pipeline.confirm"]._open(self, "override", self.release_id.sha[:12])

    def _confirmed_override(self, reason):
        self.ensure_one()
        self._require_owner()
        self.write({"hold_override": True, "hold_override_reason": reason, "hold_override_by_id": self.env.user.id,
                    "hold_override_at": fields.Datetime.now(), "checks_ok": False})
        self.env["platform.log"]._record(
            _("Practice wait skipped by the owner"), None,
            _("Release %(release)s, reason: %(reason)s", release=self.release_id.sha[:12], reason=reason),
        )

    def action_open_confirm_main(self):
        self.ensure_one()
        self._require_owner()
        if self.state != "awaiting_main":
            raise UserError(t(self.env, _("main moves once every firm runs the release.")))
        return self.env["platform.pipeline.confirm"]._open(self, "main", self.release_id.sha[:12])

    def _confirmed_main(self, reason):
        self.ensure_one()
        self._require_owner()
        self.write({"state": "done", "main_moved_at": fields.Datetime.now()})
        self.env["platform.log"]._record(
            _("main moved, by the owner's hand"), None,
            _("Release %(release)s, reason: %(reason)s", release=self.release_id.sha[:12], reason=reason),
        )

    def action_prepare_rollback(self):
        """A new rollout of the release before this one, which was already signed. Goes through the same screen."""
        self.ensure_one()
        self._require_owner()
        if self.state not in ("done", "awaiting_main", "stopped") or not self.previous_release_id:
            raise UserError(t(self.env, _("There is no earlier release to go back to.")))
        rollback = self.sudo().create({
            "kind": "rollback",
            "release_id": self.previous_release_id.id,
            "canary_firm_id": self.canary_firm_id.id,
            "firm_ids": [(6, 0, self.firm_ids.ids)],
            "batch_size": self.batch_size,
        })
        self.env["platform.log"]._record(
            _("Rollback prepared"), None,
            _("From %(new)s back to %(old)s", new=self.release_id.sha[:12], old=self.previous_release_id.sha[:12]),
        )
        return {
            "type": "ir.actions.act_window", "res_model": self._name, "res_id": rollback.id,
            "view_mode": "form", "target": "current",
        }


class PlatformRollout(models.Model):
    _inherit = "platform.rollout"

    def _advance(self):
        result = super()._advance()
        self.env["platform.pipeline.promotion"]._sync_from_rollouts(self)
        return result
