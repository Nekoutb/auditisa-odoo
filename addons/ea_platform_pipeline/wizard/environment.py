import secrets

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ea_platform_admin.services.messages import _
from ..models.environment import _table, _when
from ..models.i18n import t
from ..services import environments as envs

PASSWORD_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"


def new_password():
    """Four groups of four, without look-alike letters: about 92 bits, easy to read out and type."""
    return "-".join("".join(secrets.choice(PASSWORD_ALPHABET) for _i in range(4)) for _j in range(4))


def _space_selection(model):
    state = model.env["platform.environment"]._env_state()
    spaces = ((state or {}).get("practice") or {}).get("spaces") or []
    return [(space["slug"], space["slug"]) for space in spaces]


class PlatformEnvironmentConnect(models.TransientModel):
    """Connect: which practice space to open, or which client firm to visit (read-only, logged, time-limited)."""

    _name = "platform.environment.connect"
    _description = "Connect to an environment"

    environment_id = fields.Many2one("platform.environment", required=True, readonly=True)
    code = fields.Selection(related="environment_id.code")
    space = fields.Selection(_space_selection, "Practice space")
    firm_id = fields.Many2one("platform.firm", "Client firm", domain=[("state", "=", "active"), ("pipeline_role", "=", "firm")])

    def action_open(self):
        self.ensure_one()
        if self.code == "practice":
            if not self.space:
                raise UserError(t(self.env, _("Choose the practice space to open.")))
            return {"type": "ir.actions.act_url", "url": self.env["platform.environment"]._practice_url(self.space), "target": "new"}
        if self.code == "production":
            self.env["platform.environment.request"]._require_operator()
            if not self.firm_id:
                raise UserError(t(self.env, _("Choose the client firm.")))
            # The existing support visit: reason, length, a link shown once, logged, seen and ended by the firm.
            return self.firm_id.action_support_visit()
        raise UserError(t(self.env, _("There is nothing to connect to here.")))


class PlatformEnvironmentAccountWizard(models.TransientModel):
    """Make a test account, or give one a new password. The password is shown once, here, and never sent."""

    _name = "platform.environment.account.wizard"
    _description = "Test account"

    environment_id = fields.Many2one("platform.environment", required=True, readonly=True)
    code = fields.Selection(related="environment_id.code")
    mode = fields.Selection([("create", "New test account"), ("reset", "New password")], required=True, readonly=True, default="create")
    space = fields.Selection(_space_selection, "Practice space")
    name = fields.Char("Full name")
    login = fields.Char("Email (the login)")
    login_shown = fields.Char(related="login", string="Login")
    role = fields.Selection(envs.ROLES, "Role", default="staff")
    password = fields.Char("Password, shown once", readonly=True)
    done = fields.Boolean(readonly=True)
    request_ref = fields.Char("Request", readonly=True)

    def _reopen(self):
        self.ensure_one()
        title = t(self.env, _("New test account")) if self.mode == "create" else t(self.env, _("New password"))
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form", "views": [(False, "form")],
                "target": "new", "name": title}

    def _target(self):
        if self.code == "staging":
            return "staging"
        if self.code == "practice":
            if not self.space:
                raise UserError(t(self.env, _("Choose the practice space.")))
            return f"practice:{self.space}"
        raise UserError(t(self.env, _("Accounts are made only on Staging or in a Practice space, never on a client firm.")))

    def action_confirm(self):
        self.ensure_one()
        Request = self.env["platform.environment.request"]
        Request._require_operator()
        if self.done:
            raise UserError(t(self.env, _("This has already been sent.")))
        password = new_password()
        hashed = self.env["res.users"]._crypt_context().hash(password)
        request = Request._submit(
            self.mode, self._target(), (self.login or "").strip(), self.name, self.role if self.mode == "create" else None,
            hashed, environment=self.environment_id,
        )
        self.write({"password": password, "done": True, "request_ref": request.ref})
        return self._reopen()

    def action_close(self):
        self.write({"password": False})
        return {"type": "ir.actions.act_window_close"}


class PlatformEnvironmentPromote(models.TransientModel):
    """The Status page's two buttons: Promote to Staging, Promote to Production. One screen each, which says in
    plain words what will happen, and one Yes button. Nothing to type.

    Staging here is the practice computer (the client practice spaces, on the staging server): a new version goes
    there first. Production is the client firms: they take only the version Staging runs now.
    """

    _name = "platform.environment.promote"
    _description = "Promote a version"

    target = fields.Selection([("staging", "Staging"), ("production", "Production")], required=True, readonly=True)
    release_id = fields.Many2one("platform.release", "Version", readonly=True)
    summary_html = fields.Html(compute="_compute_summary", sanitize=False)
    problem = fields.Char(compute="_compute_summary")

    @api.model
    def _open(self, target):
        """The confirmation dialog, with the version it would send already chosen."""
        self.env["platform.pipeline.guard"]._require_owner()
        overview = self.env["platform.environment"]._release_overview()
        release = overview["new"] if target == "staging" else overview["staging"]
        wizard = self.create({"target": target, "release_id": release.id or False})
        title = _("Promote to Staging") if target == "staging" else _("Promote to Production")
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": wizard.id, "view_mode": "form", "views": [(False, "form")],
                "target": "new", "name": t(self.env, title)}

    def _problem(self):
        """Why this cannot go now, in plain words, or None."""
        self.ensure_one()
        return self._problem_for(self.target, self.release_id)

    @api.model
    def _problem_for(self, target, release):
        """Why `release` cannot be promoted to `target` now, in plain words, or None. The Versions panel shows
        the same sentence under a greyed button."""
        env = self.env
        computer = env["platform.practice.computer"]._current()
        if not computer:
            return _("The practice computer (Staging) is not connected to the console yet.")
        if target == "staging":
            state = env["platform.environment"]._staging_progress()
            if state["state"] in ("waiting", "running") and not state["late"]:
                return _("Staging is installing a version: wait until it has finished.")
            if not release:
                if state["state"] == "failed":
                    return _("The last version could not be installed on Staging. The developer registers a corrected one first.")
                return _("There is no new version to promote. The developer registers one first.")
            if computer.desired_release_id == release and computer.release and envs.same_commit(computer.release, release.sha):
                return _("Staging already runs this version.")
            return None
        if not release:
            if computer.release:
                return _("The version on Staging (%(sha)s) is not a registered release: promote a registered version to Staging first.",
                         sha=computer.release[:12])
            return _("Staging runs no version yet: promote a version to Staging first.")
        ok, message = release.sudo()._staging_check()
        if not ok:
            return message
        firms = env["platform.environment"]._production_firms()
        if not firms:
            return _("There is no client firm yet: nothing would change.")
        if not firms.filtered(lambda firm: not envs.same_commit(firm.addon_release or "", release.sha)):
            return _("Every client firm already runs this version.")
        if env["platform.rollout"].sudo().search_count([("state", "=", "running")]):
            return _("Another update of the client firms is still running: wait until it ends.")
        return None

    @api.depends("target", "release_id")
    @api.depends_context("lang")
    def _compute_summary(self):
        env = self.env
        for wizard in self:
            problem = wizard._problem()
            wizard.problem = t(env, problem) if problem else False
            release = wizard.release_id
            parts = []
            if release:
                label = Markup(" %s") % release.label if release.label else Markup("")
                parts.append(Markup("<p><b>%s</b> <code>%s</code>%s</p>") % (t(env, _("Version:")), release.sha[:12], label))
            if wizard.target == "staging":
                computer = env["platform.practice.computer"]._current()
                spaces = env["platform.practice.space"].sudo().search([("computer_id", "=", computer.id)]) if computer else []
                parts.append(Markup("<p>%s</p>") % t(env, _(
                    "It goes to the practice spaces on the staging server (%(count)s space(s)). Each space is copied first, "
                    "and everything is put back automatically if anything fails. The client firms do not change.",
                    count=len(spaces))))
                parts.append(Markup("<p>%s</p>") % t(env, _(
                    "Staging starts within about a minute and takes about two minutes per practice space, then a few more "
                    "to rebuild the demo template. The Versions panel of the Status page shows a progress bar, step by "
                    "step, and says so plainly if it fails.")))
                parts.append(Markup("<p>%s</p>") % t(env, _(
                    "Next step, once Staging runs it and you have looked at it: Promote to Production.")))
            else:
                firms = env["platform.environment"]._production_firms()
                parts.append(Markup("<p>%s</p>") % t(env, _(
                    "It goes to the %(count)s client firm(s): one firm first, alone, then the others in small batches.",
                    count=len(firms))))
                parts.append(Markup("<p>%s</p>") % t(env, _(
                    "Each firm's server makes a backup just before it updates, checks itself afterwards, and puts itself back "
                    "automatically if anything fails. The update then stops for the firms that follow. Each firm is cut off for "
                    "a few minutes during its own update.")))
                parts.append(Markup("<p>%s</p>") % t(env, _(
                    "The Versions panel of the Status page then shows how many firms are updated, which one is updating now, "
                    "and says so plainly if one fails.")))
            if release:
                pipe = env["platform.environment"]._pipeline_state()
                log = (((pipe or {}).get("odoo") or {}).get("log") or {})
                current = (env["platform.practice.computer"]._current().release if wizard.target == "staging"
                           else env["platform.environment"]._release_overview()["production_sha"]) or None
                changes = None
                for branch in ("staging", "dev", "main"):
                    changes = envs.changes_between(log.get(branch), current, release.sha)
                    if changes:
                        break
                parts.append(_changes(env, changes, release))
            wizard.summary_html = Markup("").join(parts)

    def action_confirm(self):
        self.ensure_one()
        env = self.env
        env["platform.pipeline.guard"]._require_owner()
        problem = self._problem()
        if problem:
            raise UserError(t(env, problem))
        release = self.release_id
        if self.target == "staging":
            computer = env["platform.practice.computer"]._current()
            previous = computer.release or "?"
            computer.sudo().write({"desired_release_id": release.id})
            # The same log line as the practice computer's own Send button: Staging's History reads it.
            env["platform.log"]._record(
                _("Release sent to the practice computer"), None,
                _("Promote to Staging: from %(old)s to %(new)s", old=previous[:12], new=release.sha[:12]),
            )
            return {"type": "ir.actions.act_window_close"}
        firms = env["platform.environment"]._production_firms()
        waiting = firms.filtered(lambda firm: not envs.same_commit(firm.addon_release or "", release.sha))
        promotion = env["platform.pipeline.promotion"].create({
            "release_id": release.id,
            "canary_firm_id": waiting.sorted("id")[:1].id,
            "firm_ids": [(6, 0, waiting.ids)],
        })
        promotion._confirmed("promote", t(env, _("Promote to Production, from the Status page")))
        # Back to the Status page: its Versions panel shows the progress. Pipeline > Promotions has every detail.
        return {"type": "ir.actions.act_window_close"}


def _changes(env, changes, release):
    """The list of changes between two versions, or a plain sentence saying why it cannot be shown."""
    if changes:
        rows = [[Markup("<code>%s</code>") % row["sha"][:8], _when(row["at"]), row["author"] or "", row["subject"] or ""] for row in changes[:40]]
        return Markup("<h5>%s</h5>") % t(env, _("Changes")) + _table(
            [t(env, _("Revision")), t(env, _("Date")), t(env, _("Author")), t(env, _("Message"))], rows, "")
    text = t(env, _("The list of changes cannot be read: the console has no GitHub read-only key yet, or the two versions are not on the same branch."))
    notes = Markup("<p>%s</p>") % release.notes if release and release.notes else Markup("")
    return Markup('<h5>%s</h5><p class="text-muted">%s</p>%s') % (t(env, _("Changes")), text, notes)
