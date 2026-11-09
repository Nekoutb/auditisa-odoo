import secrets

from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ea_platform_admin.services.messages import _
from ..models.environment import _code, _note, _table, _when
from ..models.i18n import t, t_any
from ..services import environments as envs
from ..services import pipeline

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
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id, "view_mode": "form",
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
    """The Promote button: two separate steps, each with its own screen and its own confirmation."""

    _name = "platform.environment.promote"
    _description = "Promote staging to production"

    overview_html = fields.Html(compute="_compute_overview", sanitize=False)
    staging_release_id = fields.Many2one("platform.release", compute="_compute_overview")
    practice_release_id = fields.Many2one("platform.release", compute="_compute_overview")

    @api.depends_context("lang")
    def _compute_overview(self):
        env = self.env
        environments = env["platform.environment"].search([])
        staging = environments.filtered(lambda e: e.code == "staging")[:1]
        practice = environments.filtered(lambda e: e.code == "practice")[:1]
        computer = env["platform.practice.computer"]._current()
        firms = env["platform.environment"]._production_firms()
        running = (((env["platform.environment"]._pipeline_state() or {}).get("odoo") or {}).get("running") or {}).get("staging")
        for wizard in self:
            sha = staging.revision
            full_sha = running["sha"] if running and envs.same_commit(running["sha"], sha or "") else None
            signed = staging._signed_release(sha) if staging else env["platform.release"]
            practice_sha = (computer.release if computer else False) or practice.revision
            practice_release = practice._signed_release(practice_sha) if practice else env["platform.release"]
            wizard.staging_release_id = signed
            wizard.practice_release_id = practice_release
            parts = [Markup("<p>%s</p>") % t(env, _(
                "A new version goes to the client firms in two separate steps. Each step has its own screen, shows exactly "
                "what will change, and asks you to type a word to confirm."))]
            step1 = [Markup("<p>%s <code>%s</code></p>") % (t(env, _("Staging runs")), sha or "?")]
            if signed:
                step1.append(Markup("<p>%s <code>%s</code></p>") % (t(env, _("Signed release ready:")), signed.display_name))
            else:
                step1.append(_note(Markup("<b>%s</b><br/>%s%s") % (
                    t(env, _("This version is not signed yet. Sign it on your computer first.")),
                    t(env, _("On the computer that holds your signing key, in the auditisa-odoo folder:")),
                    _code(envs.sign_commands(sha, full_sha))
                    + Markup("<p>%s</p>") % t(env, _(
                        "Then upload it and register it in Platform > Updates > Releases, as in console-live/first-release.md. "
                        "The console never signs: the key stays on your computer."))), "warning"))
            if not computer:
                step1.append(_note(t(env, _(
                    "The practice computer is not connected to the console yet, so it cannot pick a version up from here. "
                    "Until then the practice spaces are updated by hand on the server (docs/runbook/PRACTICE-SPACES.md).")), "warning"))
            parts.append(Markup('<div class="ea-env-step"><h4>%s</h4>%s</div>') % (
                t(env, _("Step 1. Staging → Practice: the client practice spaces get it first")), Markup("").join(step1)))
            step2 = [Markup("<p>%s <code>%s</code></p>") % (t(env, _("Practice runs")), practice_sha or "?")]
            if practice_release:
                step2.append(Markup("<p>%s</p>") % t_any(env, practice_release._practice_hold()[2]))
            else:
                step2.append(Markup("<p>%s</p>") % t(env, _("No signed release is registered for what practice runs.")))
            step2.append(Markup("<p>%s</p>") % (t(env, _("%(count)s client firm(s) would get it.", count=len(firms)))
                                               if firms else t(env, _("There is no client firm yet: nothing would change."))))
            step2.append(Markup("<p>%s</p>") % t(env, _(
                "One test firm goes first, alone; then the others in small batches. Each firm's server backs itself up just "
                "before it updates, and puts itself back if anything fails. The rollout then stops.")))
            parts.append(Markup('<div class="ea-env-step"><h4>%s</h4>%s</div>') % (
                t(env, _("Step 2. Practice → Production: the client firms, after 7 days on practice")), Markup("").join(step2)))
            wizard.overview_html = Markup("").join(parts)

    def action_to_practice(self):
        self.ensure_one()
        self.env["platform.pipeline.guard"]._require_owner()
        computer = self.env["platform.practice.computer"]._current()
        if not computer:
            raise UserError(t(self.env, _(
                "The practice computer is not connected to the console yet: it cannot pick a version up from here. "
                "Update the practice spaces on the server (docs/runbook/PRACTICE-SPACES.md).")))
        context = {"default_computer_id": computer.id, "ea_status_promote": True}
        if self.staging_release_id:
            context["default_release_id"] = self.staging_release_id.id
        return {"type": "ir.actions.act_window", "res_model": "platform.practice.release.wizard", "view_mode": "form",
                "target": "new", "context": context, "name": t(self.env, _("Promote staging → practice"))}

    def action_to_production(self):
        self.ensure_one()
        self.env["platform.pipeline.guard"]._require_owner()
        context = {}
        if self.practice_release_id:
            context["default_release_id"] = self.practice_release_id.id
        return {"type": "ir.actions.act_window", "res_model": "platform.pipeline.promotion", "view_mode": "form",
                "target": "current", "context": context, "name": t(self.env, _("Promote practice → production"))}


class PlatformPracticeReleaseWizard(models.TransientModel):
    """Staging → Practice: a signed release only, what changes shown, and a typed word."""

    _inherit = "platform.practice.release.wizard"

    signed_release_ids = fields.Many2many("platform.release", compute="_compute_signed")
    summary_html = fields.Html(compute="_compute_summary", sanitize=False)
    expected = fields.Char("Type this", compute="_compute_summary")
    typed = fields.Char("Confirmation")
    reason = fields.Text("Reason")

    def _compute_signed(self):
        signed = self.env["platform.release"].sudo().search([]).filtered("attestation_ok")
        for wizard in self:
            wizard.signed_release_ids = signed

    @api.depends("release_id", "computer_id")
    @api.depends_context("lang")
    def _compute_summary(self):
        env = self.env
        pipe = env["platform.environment"]._pipeline_state()
        log = (((pipe or {}).get("odoo") or {}).get("log") or {})
        for wizard in self:
            release = wizard.release_id
            wizard.expected = pipeline.phrase("practice", release.sha[:12], env.lang) if release else False
            current = wizard.computer_id.release or False
            spaces = env["platform.practice.space"].sudo().search([("computer_id", "=", wizard.computer_id.id)])
            rows = [[t(env, _("From")), Markup("<code>%s</code>") % (current or "?")],
                    [t(env, _("To")), Markup("<code>%s</code>") % (release.display_name if release else "?")],
                    [t(env, _("Practice spaces")), ", ".join(spaces.mapped("slug")) or t(env, _("every space on the practice computer"))],
                    [t(env, _("Holding period before the firms")), t(env, _("%(days)s day(s)", days=release.practice_hold_days)) if release else ""]]
            changes = envs.changes_between(log.get("staging") or log.get("dev"), current, release.sha if release else None)
            wizard.summary_html = _table([t(env, _("What")), t(env, _("Value"))], rows, "") + _changes(env, changes, release)

    def action_confirm(self):
        """From the screens (the Status page's step 1, or the practice computer's Send button), with the guards.

        Both screens open this wizard with `ea_status_promote` in the context, and the form then asks for the typed
        word and the reason. A call from code keeps ea_platform_admin's plain behaviour; the practice computer
        itself still refuses any bundle that is not signed with the owner's key (practice-update.sh).
        """
        self.ensure_one()
        env = self.env
        if not env.context.get("ea_status_promote"):
            return super().action_confirm()
        if not env.user.has_group("ea_platform_admin.group_platform_owner"):
            raise UserError(t(env, _("Only the owner can send a release.")))
        if not self.release_id.attestation_ok:
            raise UserError(t(env, _("This version is not signed yet. Sign it on your computer first.")))
        errors = pipeline.confirmation_errors(self.expected, self.typed, self.reason)
        if errors:
            raise UserError("\n".join(t(env, error) for error in errors))
        result = super().action_confirm()
        env["platform.log"]._record(
            _("Promote staging → practice confirmed"), None,
            _("From %(old)s to %(new)s, reason: %(reason)s", old=self.computer_id.release or "?",
              new=self.release_id.sha[:12], reason=self.reason.strip()),
        )
        return result


def _changes(env, changes, release):
    """The list of changes between two versions, or a plain sentence saying why it cannot be shown."""
    if changes:
        rows = [[Markup("<code>%s</code>") % row["sha"][:8], _when(row["at"]), row["author"] or "", row["subject"] or ""] for row in changes[:40]]
        return Markup("<h5>%s</h5>") % t(env, _("Changes")) + _table(
            [t(env, _("Revision")), t(env, _("Date")), t(env, _("Author")), t(env, _("Message"))], rows, "")
    text = t(env, _("The list of changes cannot be read: the console has no GitHub read-only key yet, or the two versions are not on the same branch."))
    notes = Markup("<p>%s</p>") % release.notes if release and release.notes else Markup("")
    return Markup('<h5>%s</h5><p class="text-muted">%s</p>%s') % (t(env, _("Changes")), text, notes)
