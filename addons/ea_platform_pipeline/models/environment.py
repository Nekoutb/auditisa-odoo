import json
import os
import secrets
from datetime import datetime, timedelta

from markupsafe import Markup

from odoo import api, fields, models, release as odoo_release
from odoo.exceptions import UserError

from odoo.addons.ea_platform_admin.services import platform_mail
from odoo.addons.ea_platform_admin.services.messages import _
from ..services import environments as envs
from .i18n import t

ENV_STATE_PARAM = "ea_platform_pipeline.env_state_file"
ENV_STATE_DEFAULT = "/var/lib/auditisa-platform/env-state.json"
SPOOL_PARAM = "ea_platform_pipeline.env_spool_dir"
SPOOL_DEFAULT = "/var/lib/auditisa-platform/env-requests"
STAGING_URL_PARAM = "ea_platform_pipeline.staging_url"
STAGING_URL_DEFAULT = "https://test.auditisa.com"
PRACTICE_URL_PARAM = "ea_platform_pipeline.practice_url"
PRACTICE_URL_DEFAULT = "https://test.auditisa.com:8443/practice/%s"
REQUEST_TIMEOUT = timedelta(minutes=15)

KINDS = [("production", "Production"), ("practice", "Practice"), ("staging", "Staging"), ("development", "Development")]
COLORS = [("green", "Green"), ("amber", "Amber"), ("red", "Red"), ("grey", "Grey")]
ROLE_SELECTION = envs.ROLES + [("admin", "Administrator"), ("user", "Other")]


def _when(value):
    """A datetime or an ISO instant, as the screen writes it: always UTC, said so."""
    if not value:
        return ""
    if isinstance(value, str):
        value = datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")
    return value.strftime("%Y-%m-%d %H:%M") + " UTC"


def _table(headers, rows, empty):
    """A plain table. Every cell is escaped here unless it is already Markup."""
    if not rows:
        return Markup('<p class="text-muted ea-env-empty">%s</p>') % empty
    head = Markup("").join(Markup("<th>%s</th>") % header for header in headers)
    body = Markup("").join(
        Markup("<tr>%s</tr>") % Markup("").join(Markup("<td>%s</td>") % (cell if cell not in (None, False) else "") for cell in row)
        for row in rows
    )
    return Markup('<table class="table table-sm ea-env-table"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>') % (head, body)


def _section(title, content):
    return Markup('<h4 class="ea-env-section">%s</h4>%s') % (title, content)


def _note(text, kind="info"):
    return Markup('<div class="alert alert-%s ea-env-note" role="status">%s</div>') % (kind, text)


def _code(lines):
    return Markup('<pre class="ea-env-code">%s</pre>') % "\n".join(lines)


class PlatformEnvironment(models.Model):
    """One environment of the Odoo tool, as the Status page shows it: Production, Practice, Staging, Development.

    It keeps nothing of its own but its name. Every figure comes from what the console already has: the firms'
    heartbeats, the practice computer's, the releases, rollouts and promotions, the platform log, the
    pipeline collector's file (GitHub) and the env-sync file (staging and the practice spaces). See
    docs/runbook/ENVIRONMENTS.md.
    """

    _name = "platform.environment"
    _description = "Environment"
    _order = "sequence"

    code = fields.Selection(KINDS, "Environment", required=True, readonly=True)
    name = fields.Char("Name", required=True, translate=True, readonly=True)
    sequence = fields.Integer(default=10, readonly=True)
    stage_id = fields.Many2one("platform.pipeline.stage", "Pipeline stage", readonly=True, ondelete="set null")

    color = fields.Selection(COLORS, "Colour", compute="_compute_figures")
    status_word = fields.Char("State", compute="_compute_figures")
    branch = fields.Char("Branch", compute="_compute_figures")
    odoo_version = fields.Char("Odoo version", compute="_compute_figures")
    revision = fields.Char("Revision", compute="_compute_figures")
    can_connect = fields.Boolean(compute="_compute_figures")
    is_owner = fields.Boolean(compute="_compute_rights")
    is_operator = fields.Boolean(compute="_compute_rights")

    sidebar_html = fields.Html("Environments", compute="_compute_pages", sanitize=False)
    head_html = fields.Html(compute="_compute_pages", sanitize=False)
    info_html = fields.Html("Information", compute="_compute_pages", sanitize=False)
    rules_html = fields.Html("How this works", compute="_compute_pages", sanitize=False)
    deploys_html = fields.Html("Deploys", compute="_compute_pages", sanitize=False)
    commits_html = fields.Html("Commits on the branch", compute="_compute_pages", sanitize=False)
    backups_html = fields.Html("Backups", compute="_compute_pages", sanitize=False)
    monitor_html = fields.Html("Monitor", compute="_compute_pages", sanitize=False)
    people_html = fields.Html("People", compute="_compute_pages", sanitize=False)

    log_ids = fields.Many2many("platform.log", string="Log", compute="_compute_log_ids")
    account_ids = fields.One2many("platform.environment.account", "environment_id", "Accounts", readonly=True)
    request_ids = fields.One2many("platform.environment.request", "environment_id", "Account requests", readonly=True)
    firm_ids = fields.Many2many("platform.firm", string="Client firms", compute="_compute_firm_ids")

    # The previous Status board, folded in: the same reading of GitHub and the sites.
    stage_github_commit = fields.Char(related="stage_id.github_commit")
    stage_running_commit = fields.Char(related="stage_id.running_commit")
    stage_matches = fields.Selection(related="stage_id.matches")
    stage_ahead = fields.Char(related="stage_id.ahead")
    stage_health = fields.Char(related="stage_id.health")
    stage_detail = fields.Text(related="stage_id.detail")
    stage_reading = fields.Char(related="stage_id.reading")
    stage_is_sample = fields.Boolean(related="stage_id.is_sample")
    stage_where = fields.Char(related="stage_id.where")

    _code_unique = models.Constraint("unique(code)", "One row per environment.")

    # ------------------------------------------------------------------ what the console reads

    @api.model
    def _env_state(self):
        """env-sync.py's file, checked. None when it is missing or not what env-sync writes."""
        path = self.env["ir.config_parameter"].sudo().get_param(ENV_STATE_PARAM, ENV_STATE_DEFAULT)
        try:
            with open(path, "rb") as handle:
                raw = handle.read(envs.MAX_BYTES + 1)
        except OSError:
            return None
        return envs.read_env_state(raw, fields.Datetime.now())

    @api.model
    def _pipeline_state(self):
        return self.env["platform.pipeline.stage"]._collected()

    def _remote(self, state):
        """The part of env-state that is this environment's, or an empty dict."""
        self.ensure_one()
        if not state or self.code not in ("staging", "practice"):
            return {}
        return state.get(self.code) or {}

    @api.model
    def _production_firms(self):
        return self.env["platform.firm"].sudo().search([("pipeline_role", "=", "firm"), ("state", "=", "active")])

    @api.model
    def _practice_url(self, slug):
        pattern = self.env["ir.config_parameter"].sudo().get_param(PRACTICE_URL_PARAM, PRACTICE_URL_DEFAULT)
        computer = self.env["platform.practice.computer"]._current()
        if computer and computer.entry_url and "%s" in computer.entry_url and not computer.is_simulation:
            pattern = computer.entry_url
        return pattern.replace("%s", slug)

    @api.model
    def _staging_url(self):
        return self.env["ir.config_parameter"].sudo().get_param(STAGING_URL_PARAM, STAGING_URL_DEFAULT)

    def _branch_name(self, pipeline):
        branches = ((pipeline or {}).get("odoo") or {}).get("branches") or {}
        return {"development": "dev", "staging": "staging" if branches.get("staging") else "dev",
                "practice": None, "production": "main"}[self.code]

    @api.model
    def _registered_release(self, sha):
        """The registered release for this commit (short or long), or an empty recordset."""
        if not sha:
            return self.env["platform.release"]
        releases = self.env["platform.release"].sudo().search([])
        return releases.filtered(lambda r: envs.same_commit(r.sha, sha))[:1]

    @api.model
    def _release_overview(self):
        """Where each version is, for the Versions panel at the top of the Status page (release_panel.py).

        new: the newest registered release that Staging neither runs nor has been asked to take ("New version
        ready"); asked: what Staging was asked to take and has not installed yet; staging: the registered release
        Staging (the practice computer) runs; production_sha and production_count: what most client firms run.
        """
        computer = self.env["platform.practice.computer"]._current()
        running = computer.release if computer else False
        staging = self._registered_release(running)
        asked = computer.desired_release_id if computer else self.env["platform.release"]
        if asked and staging == asked:
            asked = self.env["platform.release"]
        newest = self.env["platform.release"].sudo().search([], limit=1)
        new = newest if newest and newest != staging and newest != asked else self.env["platform.release"]
        firms = self._production_firms()
        releases = [firm.addon_release for firm in firms if firm.addon_release]
        production = max(set(releases), key=releases.count) if releases else False
        return {
            "computer": computer, "running": running, "staging": staging, "asked": asked, "new": new,
            "production_sha": production,
            "production_count": len([sha for sha in releases if production and envs.same_commit(sha, production)]),
            "firm_count": len(firms),
        }

    def _tests_for(self, sha):
        runs = self.env["platform.pipeline.test.run"].sudo().search([], limit=200)
        if not sha:
            return False
        matching = runs.filtered(lambda run: envs.same_commit(run.commit_sha, sha))
        if not matching:
            return t(self.env, _("No test run recorded for this commit"))
        latest = {}
        for run in matching:
            latest.setdefault(run.suite, run)
        failed = sum(run.failed for run in latest.values())
        passed = sum(run.passed for run in latest.values())
        if failed:
            return t(self.env, _("%(failed)s failed, %(passed)s passed", failed=failed, passed=passed))
        return t(self.env, _("All green: %(passed)s passed", passed=passed))

    # ------------------------------------------------------------------ figures

    def _compute_rights(self):
        owner = self.env.user.has_group("ea_platform_admin.group_platform_owner")
        operator = self.env.user.has_group("ea_platform_admin.group_platform_operator")
        for environment in self:
            environment.is_owner = owner
            environment.is_operator = operator

    @api.depends_context("lang")
    def _compute_figures(self):
        state = self._env_state()
        pipeline = self._pipeline_state()
        for environment in self:
            environment.update(environment._figures(state, pipeline))

    def _figures(self, state, pipeline):
        """colour, state word, branch, Odoo version, revision and whether Connect applies."""
        self.ensure_one()
        env = self.env
        odoo = (pipeline or {}).get("odoo") or {}
        branch = self._branch_name(pipeline)
        values = {"branch": branch or False, "odoo_version": odoo_release.serie, "revision": False,
                  "color": "grey", "status_word": t(env, _("Unknown")), "can_connect": False}
        if self.code == "development":
            head = (odoo.get("branches") or {}).get("dev")
            values["revision"] = head["sha"][:12] if head else False
            run = env["platform.pipeline.test.run"].sudo().search([], limit=1)
            values["status_word"] = t(env, _("No server: code only"))
            values["color"] = ("red" if run and run.failed else "green") if odoo.get("github") == "ok" else "grey"
            return values
        if self.code == "production":
            firms = self._production_firms()
            values["can_connect"] = bool(firms)
            if not firms:
                values["status_word"] = t(env, _("No client firm yet"))
                values["odoo_version"] = False
                return values
            releases = [firm.addon_release for firm in firms if firm.addon_release]
            values["revision"] = max(set(releases), key=releases.count)[:12] if releases else False
            versions = sorted({firm.odoo_version for firm in firms if firm.odoo_version})
            values["odoo_version"] = ", ".join(versions) or False
            colors = set(firms.mapped("health_color"))
            values["color"] = "red" if "red" in colors else ("amber" if colors - {"green"} else "green")
            values["status_word"] = t(env, _("%(count)s firm(s) running", count=len(firms)))
            return values
        remote = self._remote(state)
        values["can_connect"] = True
        if self.code == "practice":
            values["revision"] = remote.get("revision") or False
        else:
            running = (odoo.get("running") or {}).get("staging")
            values["revision"] = remote.get("revision") or (running["sha"][:12] if running else False)
        values["odoo_version"] = remote.get("odoo_version") or odoo_release.serie
        if not state:
            site = ((odoo.get("sites") or {}).get("staging") or {}) if self.code == "staging" else {}
            if site.get("up"):
                values.update(color="green", status_word=t(env, _("Running")))
            return values
        if not remote.get("reachable"):
            values.update(color="grey", status_word=t(env, _("Cannot be read")))
        elif remote.get("service_active"):
            values.update(color="amber" if not remote.get("mail_off") else "green", status_word=t(env, _("Running")))
        else:
            values.update(color="red", status_word=t(env, _("Stopped")))
        return values

    @api.depends_context("lang")
    def _compute_pages(self):
        state = self._env_state()
        pipeline = self._pipeline_state()
        everyone = self.search([])
        for environment in self:
            environment.update(environment._pages(state, pipeline, everyone))

    def _pages(self, state, pipeline, everyone):
        self.ensure_one()
        builder = getattr(self, f"_page_{self.code}")
        page = builder(state, pipeline)
        page["sidebar_html"] = self._sidebar(everyone)
        page["head_html"] = self._head()
        page["info_html"] = self._info(state, pipeline)
        return page

    def _sidebar(self, everyone):
        env = self.env
        groups = []
        firms = self._production_firms()
        # "Staging" is where Promote to Staging sends a version: the practice spaces. The developer's own
        # test site, on the same server, is named for what it is, so that one word is one thing.
        for code, label in [("production", _("Production")), ("practice", _("Staging: practice spaces")),
                            ("staging", _("Developer test site")), ("development", _("Development"))]:
            items = Markup("")
            for environment in everyone.filtered(lambda e, c=code: e.code == c):
                sub = " · ".join(part for part in (environment.branch or "", environment.odoo_version or "") if part)
                items += Markup(
                    '<a class="ea-env-item%s" href="/odoo/status/%s"><span class="ea-env-dot ea-env-%s"></span>'
                    '<span class="ea-env-item-name">%s</span><span class="ea-env-item-sub">%s</span></a>'
                ) % (" ea-env-active" if environment == self else "", environment.id, environment.color,
                     environment.name, sub)
            if code == "production":
                for firm in firms[:30]:
                    items += Markup('<div class="ea-env-firm"><span class="ea-env-dot ea-env-%s"></span>%s</div>') % (
                        firm.health_color if firm.health_color in ("green", "amber", "red") else "grey", firm.name)
                if not firms:
                    items += Markup('<div class="ea-env-firm text-muted">%s</div>') % t(env, _("No client firm yet"))
            groups.append(Markup('<div class="ea-env-group"><div class="ea-env-group-title">%s</div>%s</div>') % (t(env, label), items))
        board = Markup('<div class="ea-env-foot"><a href="/odoo/status-board">%s</a></div>') % t(
            env, _("Both tools side by side (the previous board)"))
        return Markup('<nav class="ea-env-nav">%s%s</nav>') % (Markup("").join(groups), board)

    def _head(self):
        return Markup('<span class="ea-env-status"><span class="ea-env-dot ea-env-%s"></span>%s</span>') % (
            self.color, self.status_word or "")

    def _info(self, state, pipeline):
        env = self.env
        remote = self._remote(state)
        parts = []
        if self.odoo_version:
            parts.append(Markup("<span><b>%s</b> %s</span>") % (t(env, _("Odoo")), self.odoo_version))
        modules = remote.get("modules") or []
        if modules:
            listing = Markup("").join(Markup("<li><code>%s</code> %s</li>") % (name, version) for name, version in modules)
            parts.append(Markup('<details class="ea-env-addons"><summary><b>%s</b> %s</summary><ul>%s</ul></details>') % (
                t(env, _("Add-ons")), t(env, _("%(count)s installed", count=len(modules))), listing))
        size = remote.get("db_size_mb")
        if self.code == "practice":
            spaces = remote.get("spaces") or []
            total = sum(space["db_size_mb"] or 0 for space in spaces)
            size = total if spaces else None
        if size is not None:
            parts.append(Markup("<span><b>%s</b> %s</span>") % (t(env, _("Database size")), envs.size_text(size)))
        if self.revision:
            url = envs.revision_url(self.revision)
            link = (Markup('<a href="%s" target="_blank" rel="noopener noreferrer"><code>%s</code></a>') % (url, self.revision)
                    if url else Markup("<code>%s</code>") % self.revision)
            parts.append(Markup("<span><b>%s</b> %s</span>") % (t(env, _("Revision")), link))
        if remote.get("up_since"):
            parts.append(Markup("<span><b>%s</b> %s</span>") % (t(env, _("Up since")), _when(remote["up_since"])))
        tests = self._tests_for(self.revision) if self.code in ("development", "staging", "practice") else False
        if tests:
            parts.append(Markup("<span><b>%s</b> %s</span>") % (t(env, _("Tests on this commit")), tests))
        if not parts:
            return Markup('<div class="ea-env-info text-muted">%s</div>') % t(env, _("Nothing is known about this environment yet."))
        return Markup('<div class="ea-env-info">%s</div>') % Markup('<span class="ea-env-sep">·</span>').join(parts)

    # ------------------------------------------------------------------ the pages, one per environment

    def _not_connected_note(self, state):
        env = self.env
        if state is None:
            return _note(t(env, _(
                "The console does not read staging's figures and accounts yet: the env-sync service is not installed "
                "on the console. Until then this page shows what the console already knows. See docs/runbook/ENVIRONMENTS.md.")), "warning")
        if state["stale"]:
            return _note(t(env, _("Old reading: staging's figures were last read at %(time)s.", time=_when(state["generated"]))), "warning")
        return Markup("")

    def _commits(self, pipeline, branch):
        env = self.env
        odoo = (pipeline or {}).get("odoo") or {}
        sample = bool(pipeline and pipeline.get("sample"))
        log = (odoo.get("log") or {}).get(branch or "") or []
        if odoo.get("github") == "no_key":
            note = _note(Markup("%s %s") % (
                t(env, _("Connect GitHub read-only key: the console cannot read this private repository's commits yet. "
                         "On the console's server, as root (once, by you):")),
                _code(["ssh-keygen -t ed25519 -N '' -C 'control room read-only' -f /root/.ssh/auditisa_odoo_ro",
                       "gh repo deploy-key add /root/.ssh/auditisa_odoo_ro.pub --repo Nekoutb/auditisa-odoo --title control-room-read-only"])
                + Markup("<p>%s</p>") % t(env, _("Do not tick write access. Commits then appear here within a minute."))), "warning")
            return note
        rows = []
        for row in log[:20]:
            url = envs.revision_url(row["sha"])
            rows.append([
                Markup('<a href="%s" target="_blank" rel="noopener noreferrer"><code>%s</code></a>') % (url, row["sha"][:8]),
                _when(row["at"]), row["author"] or "", row["subject"] or "",
            ])
        table = _table([t(env, _("Revision")), t(env, _("Date")), t(env, _("Author")), t(env, _("Message"))], rows,
                       t(env, _("No commit to show for this branch yet.")))
        if sample:
            table = _note(t(env, _("SAMPLE DATA: the collector is not connected yet, so these commits are made up."))) + table
        return table

    def _page_development(self, state, pipeline):
        env = self.env
        runs = env["platform.pipeline.test.run"].sudo().search([], limit=10)
        run_rows = [[_when(run.create_date), Markup("<code>%s</code>") % run.commit_sha[:12], run.suite,
                     str(run.passed), str(run.failed), run.note or ""] for run in runs]
        return {
            "rules_html": _note(t(env, _(
                "Development is the git branch dev. It has no server of its own: changes are tested on throwaway "
                "databases, then deployed to Staging. Nothing to connect to here."))),
            "deploys_html": _section(t(env, _("Deploys")), Markup('<p class="text-muted">%s</p>') % t(env, _(
                "No server: nothing is deployed here. Staging's page lists what reached staging."))),
            "commits_html": _section(t(env, _("Commits on the branch %(branch)s", branch=self.branch or "dev")), self._commits(pipeline, self.branch)),
            "backups_html": Markup('<p class="text-muted">%s</p>') % t(env, _("No server, no database: the code is kept by GitHub.")),
            "monitor_html": _section(t(env, _("Recorded test runs")), _table(
                [t(env, _("When")), t(env, _("Commit")), t(env, _("Suite")), t(env, _("Passed")), t(env, _("Failed")), t(env, _("Where it ran"))],
                run_rows, t(env, _("No test run recorded yet.")))),
            "people_html": Markup('<p class="text-muted">%s</p>') % t(env, _("No server, so nobody is connected here.")),
        }

    def _page_staging(self, state, pipeline):
        env = self.env
        remote = self._remote(state)
        rows = []
        releases = remote.get("releases") or []
        for index, row in enumerate(releases):
            before = releases[index + 1]["name"] if index + 1 < len(releases) else ""
            result = {"running": t(env, _("Running now")), "replaced": t(env, _("Replaced"))}.get(row["result"] or "", "")
            rows.append([_when(row["at"]), Markup("<code>%s</code> → <code>%s</code>") % (before[:12] or "…", row["name"][:12]),
                         result, t(env, _("On the server (not recorded)"))])
        for rebuild in env["platform.pipeline.rebuild"].sudo().search([], limit=10):
            label = dict(rebuild._fields["state"]._description_selection(env)).get(rebuild.state)
            rows.append([_when(rebuild.rebuilt_at or rebuild.requested_at),
                         t(env, _("Rebuilt from %(firm)s's anonymised copy", firm=rebuild.source_firm_id.name)),
                         label, rebuild.requested_by_id.name or ""])
        rows.sort(key=lambda row: row[0], reverse=True)
        deploys = _table([t(env, _("When")), t(env, _("From → to")), t(env, _("Result")), t(env, _("By"))], rows,
                         t(env, _("No deploy known yet: the console reads them once env-sync is installed.")))
        staging_firm = env["platform.firm"].sudo().search([("pipeline_role", "=", "staging"), ("state", "!=", "archived")], limit=1)
        site = (((pipeline or {}).get("odoo") or {}).get("sites") or {}).get("staging") or {}
        monitor = []
        yes, no = t(env, _("Yes")), t(env, _("No"))
        monitor.append([t(env, _("Answers on the web")), yes if site.get("up") else no])
        if state is not None:
            monitor.append([t(env, _("Odoo service")), t(env, _("Running")) if remote.get("service_active") else t(env, _("Stopped"))])
            monitor.append([t(env, _("Outgoing mail closed")), yes if remote.get("mail_off") else no])
        elif site.get("mail_off") is not None:
            monitor.append([t(env, _("Outgoing mail closed")), yes if site.get("mail_off") else no])
        if site.get("band_on") is not None:
            monitor.append([t(env, _("\"Staging\" band on screen")), yes if site.get("band_on") else no])
        if staging_firm:
            monitor.append([t(env, _("Last heartbeat")), _when(staging_firm.last_heartbeat_at) or t(env, _("Never"))])
            if staging_firm.disk_total_gb:
                monitor.append([t(env, _("Disk")), t(env, _("%(used)s%% of %(total)s GB used", used=staging_firm.disk_used_pct, total=staging_firm.disk_total_gb))])
            if staging_firm.mem_total_mb:
                monitor.append([t(env, _("Memory")), t(env, _("%(free)s MB free of %(total)s MB", free=staging_firm.mem_available_mb, total=staging_firm.mem_total_mb))])
        rules = _note(Markup("%s<br/>%s") % (
            t(env, _("This is the developer's test site (test.auditisa.com), with test data only. It never sends email. "
                     "Promote to Staging does not send a version here: it sends it to the practice spaces.")),
            t(env, _("Connect opens it in a new tab. Test accounts made here get a password shown once, on this screen: "
                     "nothing is emailed. Only the owner and operators make or change accounts; viewers only look."))))
        return {
            "rules_html": self._not_connected_note(state) + rules,
            "deploys_html": _section(t(env, _("Deploys")), deploys),
            "commits_html": _section(t(env, _("Commits on the branch %(branch)s", branch=self.branch or "dev")), self._commits(pipeline, self.branch)),
            "backups_html": Markup("%s%s") % (
                Markup('<p>%s</p>') % t(env, _("Staging holds test data only, so it keeps no nightly backup. Before each rebuild, "
                                               "the database in service is copied to /var/backups/odoo/before-rebuild/ on staging.")),
                _section(t(env, _("Rebuilds")), _table(
                    [t(env, _("When")), t(env, _("Source firm")), t(env, _("State"))],
                    [[_when(r.requested_at), r.source_firm_id.name, dict(r._fields["state"]._description_selection(env)).get(r.state)]
                     for r in env["platform.pipeline.rebuild"].sudo().search([], limit=10)],
                    t(env, _("No rebuild yet."))))),
            "monitor_html": _section(t(env, _("Health")), _table([t(env, _("Check")), t(env, _("Now"))], monitor, "")),
            "people_html": self._people_note(state),
        }

    def _page_practice(self, state, pipeline):
        env = self.env
        remote = self._remote(state)
        computer = env["platform.practice.computer"]._current()
        result_words = {"ok": t(env, _("Succeeded")), "rolled_back": t(env, _("Failed: put back as it was"))}
        rows = []
        releases = remote.get("releases") or []
        for index, row in enumerate(releases):
            before = releases[index + 1]["name"] if index + 1 < len(releases) else ""
            rows.append([_when(row["at"]), Markup("<code>%s</code> → <code>%s</code>") % (before[:12] or "…", row["name"][:12]),
                         result_words.get(row["result"] or "", ""), t(env, _("On the server (practice-update)"))])
        for entry in env["platform.log"].sudo().search([("action", "ilike", "Release sent to the practice computer")], limit=10):
            rows.append([_when(entry.logged_at), entry.detail_text or "", t(env, _("Asked from the console")), entry.user_id.name or ""])
        rows.sort(key=lambda row: row[0], reverse=True)
        spaces = remote.get("spaces") or []
        console_spaces = env["platform.practice.space"].sudo().search([])
        space_rows = []
        for space in spaces:
            known = console_spaces.filtered(lambda s, slug=space["slug"]: s.slug == slug)[:1]
            users = space["users"]
            space_rows.append([
                Markup('<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>') % (self._practice_url(space["slug"]), space["slug"]),
                known.firm_name or t(env, _("Demonstration space")),
                str(len([u for u in users if u["active"]])),
                str(len([u for u in users if u["online"]])),
                envs.size_text(space["db_size_mb"]) or "",
            ])
        monitor = [[t(env, _("Practice service")), t(env, _("Running")) if remote.get("service_active") else t(env, _("Stopped"))
                    if state is not None else t(env, _("Unknown"))]]
        if state is not None:
            monitor.append([t(env, _("Outgoing mail closed")), t(env, _("Yes")) if remote.get("mail_off") else t(env, _("No"))])
        allowed = platform_mail.parse_allowlist(
            self.env["ir.config_parameter"].sudo().get_param("ea_platform.practice_mail_allowlist") or "")[0]
        monitor.append([t(env, _("Practice spaces may email")), t(env, _(
            "%(count)s address(es) only (Platform > Settings)", count=len(allowed)) if allowed else _(
            "Nobody: no email at all (the default)"))])
        if computer:
            monitor.append([t(env, _("Practice computer's last heartbeat")), _when(computer.last_heartbeat_at) or t(env, _("Never"))])
            monitor.append([t(env, _("Real-data guard")), dict(computer._fields["guard_state"]._description_selection(env)).get(computer.guard_state)])
        else:
            monitor.append([t(env, _("Practice computer's heartbeat")), t(env, _("Not connected to the console yet"))])
        rules = _note(Markup("%s<br/>%s") % (
            t(env, _("The practice spaces: one per client firm, with made-up data only. This is what \"Staging\" means in "
                     "the Versions panel above: Promote to Staging sends a version here first, and Promote to Production "
                     "sends the version that runs here to the client firms.")),
            t(env, _("Connect asks which space to open. Accounts made in a space disappear when that space is reset to fresh "
                     "demo data; its first administrator stays."))))
        return {
            "rules_html": self._not_connected_note(state) + rules,
            "deploys_html": _section(t(env, _("Deploys")), _table(
                [t(env, _("When")), t(env, _("From → to")), t(env, _("Result")), t(env, _("By"))], rows,
                t(env, _("No update known yet.")))),
            "commits_html": _section(t(env, _("Commits")), Markup('<p class="text-muted">%s</p>') % t(env, _(
                "Practice runs a release, not a branch: its commits are those of Staging's page, up to the revision above."))),
            "backups_html": Markup('<p>%s</p>') % t(env, _(
                "Practice spaces hold made-up data. Before each update every space is copied, and put back if the update "
                "fails. A reset rebuilds a space from the demo template.")),
            "monitor_html": _section(t(env, _("Health")), _table([t(env, _("Check")), t(env, _("Now"))], monitor, ""))
            + _section(t(env, _("Spaces")), _table(
                [t(env, _("Space")), t(env, _("Firm")), t(env, _("Accounts")), t(env, _("Online now")), t(env, _("Database size"))],
                space_rows, t(env, _("No practice space known yet.")))),
            "people_html": self._people_note(state),
        }

    def _page_production(self, state, pipeline):
        env = self.env
        firms = self._production_firms()
        rows = []
        for promotion in env["platform.pipeline.promotion"].sudo().search([("state", "!=", "draft")], limit=15):
            lines = promotion.rollout_id.line_ids
            done = len(lines.filtered(lambda line: line.state == "healthy"))
            label = dict(promotion._fields["state"]._description_selection(env)).get(promotion.state)
            rows.append([_when(promotion.started_at),
                         Markup("<code>%s</code> → <code>%s</code>") % ((promotion.previous_release_id.sha or "…")[:12], promotion.release_id.sha[:12]),
                         t(env, _("%(state)s: %(done)s of %(total)s firm(s) through", state=label, done=done, total=len(lines))),
                         promotion.started_by_id.name or ""])
        promoted = env["platform.pipeline.promotion"].sudo().search([]).rollout_id
        for rollout in env["platform.rollout"].sudo().search([("state", "!=", "draft"), ("id", "not in", promoted.ids)], limit=15):
            lines = rollout.line_ids
            done = len(lines.filtered(lambda line: line.state == "healthy"))
            label = dict(rollout._fields["state"]._description_selection(env)).get(rollout.state)
            before = lines.previous_release_id[:1].sha or "…"
            rows.append([_when(rollout.started_at), Markup("<code>%s</code> → <code>%s</code>") % (before[:12], rollout.release_id.sha[:12]),
                         t(env, _("%(state)s: %(done)s of %(total)s firm(s) through", state=label, done=done, total=len(lines))),
                         rollout.create_uid.name or ""])
        rows.sort(key=lambda row: row[0], reverse=True)
        last = env["platform.rollout"].sudo().search([("state", "!=", "draft")], limit=1)
        per_firm = []
        if last:
            states = dict(last.line_ids._fields["state"]._description_selection(env))
            per_firm = [[line.firm_id.name, str(line.batch), states.get(line.state), _when(line.requested_at), _when(line.closed_at)]
                        for line in last.line_ids]
        backups = [[firm.name, _when(firm.last_backup_at) or t(env, _("Never")),
                    t(env, _("Yes")) if firm.last_backup_ok else t(env, _("No")),
                    _when(firm.last_restore_test_at) or t(env, _("Never")),
                    t(env, _("Yes")) if firm.last_restore_test_ok else t(env, _("No"))] for firm in firms]
        health = dict(env["platform.firm"]._fields["health_color"]._description_selection(env))
        monitor = [[firm.name, health.get(firm.health_color), firm.health_summary or "", _when(firm.last_heartbeat_at) or t(env, _("Never")),
                    f"{firm.disk_used_pct}%" if firm.disk_total_gb else "", firm.addon_release and firm.addon_release[:12] or ""] for firm in firms]
        rules = _note(Markup("%s<br/>%s") % (
            t(env, _("Production is each client firm's own server. A firm's data belongs to the firm.")),
            t(env, _("Connect does not sign you in freely: it starts a read-only support visit, which is logged, limited in time "
                     "and shown to the firm, who can end it. Accounts are never created on a client firm from here."))))
        return {
            "rules_html": rules,
            "deploys_html": _section(t(env, _("Deploys")), _table(
                [t(env, _("When")), t(env, _("From → to")), t(env, _("Result")), t(env, _("By"))], rows,
                t(env, _("No version has been sent to the client firms yet."))))
            + (_section(t(env, _("Last update, firm by firm")), _table(
                [t(env, _("Firm")), t(env, _("Batch")), t(env, _("Result")), t(env, _("Asked")), t(env, _("Finished"))], per_firm, ""))
               if per_firm else Markup("")),
            "commits_html": _section(t(env, _("Commits on the branch %(branch)s", branch="main")), self._commits(pipeline, "main")),
            "backups_html": Markup('<p>%s</p>') % t(env, _(
                "Each firm's server backs itself up every night, tests a restore, and backs up again just before any update. "
                "An update whose fresh backup is missing counts as failed.")) + _table(
                [t(env, _("Firm")), t(env, _("Last backup")), t(env, _("Succeeded")), t(env, _("Last restore test")), t(env, _("Succeeded"))],
                backups, t(env, _("No client firm yet."))),
            "monitor_html": _table(
                [t(env, _("Firm")), t(env, _("Health")), t(env, _("Main reason")), t(env, _("Last heartbeat")), t(env, _("Disk used")), t(env, _("Release"))],
                monitor, t(env, _("No client firm yet."))),
            "people_html": _note(t(env, _(
                "For client firms the console shows counts only: how many accounts each firm has. Names and emails of a "
                "firm's people never leave the firm's server. \"Online now\" is not sent by the firms' servers yet."))),
        }

    def _people_note(self, state):
        env = self.env
        if state is None:
            return _note(t(env, _("The list of accounts appears here once the env-sync service is installed on the console "
                                  "(see docs/runbook/ENVIRONMENTS.md).")), "warning")
        if state["stale"]:
            return _note(t(env, _("Old reading: the accounts were last read at %(time)s.", time=_when(state["generated"]))), "warning")
        return _note(t(env, _("Read at %(time)s. \"Online now\" means active in the last 3 minutes.", time=_when(state["generated"]))))

    @api.depends_context("lang")
    def _compute_log_ids(self):
        Log = self.env["platform.log"].sudo()
        domains = {
            "production": ["|", "|", ("firm_id.pipeline_role", "=", "firm"), ("action", "ilike", "promotion"), ("action", "ilike", "rollout")],
            "staging": ["|", ("firm_id.pipeline_role", "=", "staging"), ("action", "ilike", "staging")],
            "practice": [("action", "ilike", "practice")],
            "development": [("action", "ilike", "test run")],
        }
        for environment in self:
            environment.log_ids = Log.search(domains[environment.code], limit=100)

    def _compute_firm_ids(self):
        firms = self._production_firms()
        for environment in self:
            environment.firm_ids = firms if environment.code == "production" else False

    # ------------------------------------------------------------------ syncing the accounts and the requests

    @api.model
    def _cron_sync(self):
        self._sync_from_state(self._env_state())

    @api.model
    def _sync_from_state(self, state):
        """Accounts and request outcomes from env-sync's file. A missing file changes nothing."""
        Request = self.env["platform.environment.request"].sudo()
        Request._expire_old()
        if state is None:
            return False
        environments = {environment.code: environment for environment in self.sudo().search([])}
        Account = self.env["platform.environment.account"].sudo()
        seen = Account
        for code in ("staging", "practice"):
            environment = environments.get(code)
            remote = state.get(code) or {}
            if not environment or not remote.get("reachable"):
                continue
            groups = [("staging", None, remote.get("users") or [])] if code == "staging" else [
                (f"practice:{space['slug']}", space["slug"], space["users"]) for space in remote.get("spaces") or []]
            for target, slug, users in groups:
                existing = {account.login.lower(): account for account in Account.search([("target", "=", target)])}
                for user in users:
                    values = {
                        "environment_id": environment.id, "target": target, "space": slug or False,
                        "login": user["login"], "name": user["name"], "role": user["role"], "active": user["active"],
                        "online": user["online"], "protected": user["protected"],
                        "last_login": user["last_login"] and datetime.strptime(user["last_login"], "%Y-%m-%dT%H:%M:%SZ"),
                        "seen_at": state["generated"],
                    }
                    account = existing.get(user["login"].lower())
                    if account:
                        account.write(values)
                    else:
                        account = Account.create(values)
                    seen |= account
            gone = Account.search([("environment_id", "=", environment.id), ("id", "not in", seen.ids)])
            gone.unlink()
        for ref, outcome in state["requests"].items():
            Request.search([("ref", "=", ref), ("state", "=", "queued")])._close(outcome["state"], outcome["code"])
        return True

    def action_refresh(self):
        self._sync_from_state(self._env_state())
        return True

    # ------------------------------------------------------------------ the buttons

    def action_connect(self):
        self.ensure_one()
        env = self.env
        if self.code == "staging":
            return {"type": "ir.actions.act_url", "url": self._staging_url(), "target": "new"}
        if self.code in ("practice", "production"):
            if self.code == "production" and not env.user.has_group("ea_platform_admin.group_platform_operator"):
                raise UserError(t(env, _("Only an operator or the owner can start a support visit. Viewers only look.")))
            if self.code == "production" and not self._production_firms():
                raise UserError(t(env, _("There is no client firm yet: nothing to connect to.")))
            wizard = env["platform.environment.connect"].create({"environment_id": self.id})
            return {"type": "ir.actions.act_window", "res_model": wizard._name, "res_id": wizard.id, "view_mode": "form", "views": [(False, "form")],
                    "target": "new", "name": t(env, _("Connect to %(environment)s", environment=self.name))}
        raise UserError(t(env, _("Development has no server: there is nothing to connect to.")))

    def action_promote_staging(self):
        """Promote to Staging: the newest version goes to the practice spaces. One confirmation, nothing to type.
        Both buttons are in the Versions panel, the same on every environment's page: they act on the versions,
        not on the page that happens to be open."""
        return self.env["platform.environment.promote"]._open("staging")

    def action_promote_production(self):
        """Promote to Production: the version Staging runs goes to the client firms. One confirmation."""
        return self.env["platform.environment.promote"]._open("production")

    def action_new_account(self):
        self.ensure_one()
        self.env["platform.environment.request"]._require_operator()
        if self.code not in ("staging", "practice"):
            raise UserError(t(self.env, _("Accounts are made only on Staging or in a Practice space, never on a client firm.")))
        wizard = self.env["platform.environment.account.wizard"].create({"environment_id": self.id, "mode": "create"})
        return wizard._reopen()


class PlatformEnvironmentAccount(models.Model):
    """An account on staging or in a practice space, as env-sync last read it. Read from there: never typed here."""

    _name = "platform.environment.account"
    _description = "Account on a test environment"
    _order = "target, active desc, name"

    environment_id = fields.Many2one("platform.environment", "Environment", required=True, ondelete="cascade", index=True)
    target = fields.Char("Where", required=True, index=True)
    space = fields.Char("Practice space")
    login = fields.Char("Email", required=True)
    name = fields.Char("Name")
    role = fields.Selection(ROLE_SELECTION, "Role")
    active = fields.Boolean("Enabled", default=True)
    last_login = fields.Datetime("Last login")
    online = fields.Boolean("Online now")
    protected = fields.Boolean("Protected", help="An administrator, or the practice space's first administrator: changed on the server itself.")
    seen_at = fields.Datetime("Read on")
    pending = fields.Boolean("Change waiting", compute="_compute_pending")

    def _compute_pending(self):
        queued = self.env["platform.environment.request"].sudo().search([("state", "=", "queued")])
        keys = {(request.target, request.login.lower()) for request in queued}
        for account in self:
            account.pending = (account.target, (account.login or "").lower()) in keys

    def action_disable(self):
        self.ensure_one()
        Request = self.env["platform.environment.request"]
        Request._require_operator()
        if self.protected:
            raise UserError(t(self.env, _("This account is protected: change it on the server itself.")))
        Request._submit("disable", self.target, self.login, environment=self.environment_id)
        return True

    def action_reset_password(self):
        self.ensure_one()
        self.env["platform.environment.request"]._require_operator()
        if self.protected:
            raise UserError(t(self.env, _("This account is protected: change it on the server itself.")))
        wizard = self.env["platform.environment.account.wizard"].create({
            "environment_id": self.environment_id.id, "mode": "reset", "login": self.login, "name": self.name,
            "space": self.space or False,
        })
        return wizard._reopen()


class PlatformEnvironmentRequest(models.Model):
    """An account action asked from the console, and its outcome. Never holds a password, nor its hash."""

    _name = "platform.environment.request"
    _description = "Account request"
    _order = "id desc"
    _rec_name = "ref"

    ref = fields.Char("Reference", required=True, readonly=True, index=True, default=lambda self: secrets.token_hex(8))
    environment_id = fields.Many2one("platform.environment", "Environment", required=True, readonly=True, ondelete="cascade")
    action = fields.Selection([("create", "Create"), ("disable", "Disable"), ("reset", "New password")], "Action", required=True, readonly=True)
    target = fields.Char("Where", required=True, readonly=True)
    login = fields.Char("Email", required=True, readonly=True)
    role = fields.Selection(envs.ROLES, "Role", readonly=True)
    state = fields.Selection([("queued", "Waiting for staging"), ("done", "Done"), ("failed", "Failed")], "State",
                             default="queued", required=True, readonly=True)
    code = fields.Char("Reason code", readonly=True)
    message = fields.Char("What happened", compute="_compute_message")
    requested_by_id = fields.Many2one("res.users", "Asked by", readonly=True, default=lambda self: self.env.user)
    done_at = fields.Datetime("Finished on", readonly=True)

    _ref_unique = models.Constraint("unique(ref)", "This reference is already used.")

    @api.depends("state", "code")
    @api.depends_context("lang")
    def _compute_message(self):
        for request in self:
            if request.state == "queued":
                request.message = t(self.env, _("Waiting: staging carries it out within a minute."))
            elif request.state == "done":
                request.message = t(self.env, _("Done."))
            else:
                request.message = t(self.env, envs.FAILURE_CODES.get(request.code) or _("It failed. Nothing was changed."))

    def _where_text(self):
        self.ensure_one()
        if self.target == "staging":
            return t(self.env, _("on Staging"))
        return t(self.env, _("in the practice space %(slug)s", slug=self.target[9:]))

    @api.model
    def _require_operator(self):
        if not self.env.user.has_group("ea_platform_admin.group_platform_operator"):
            raise UserError(t(self.env, _("Only an operator or the owner can do this. Viewers only look.")))

    @api.model
    def _submit(self, action, target, login, name=None, role=None, password_hash=None, environment=None):
        """Writes the request for env-sync, then records it and logs it. The hash goes to the file only."""
        self._require_operator()
        errors = envs.request_errors(action, target, login, name, role, password_hash)
        if errors:
            raise UserError("\n".join(t(self.env, error) for error in errors))
        folder = self.env["ir.config_parameter"].sudo().get_param(SPOOL_PARAM, SPOOL_DEFAULT)
        if not os.path.isdir(folder) or not os.access(folder, os.W_OK):
            raise UserError(t(self.env, _(
                "The console is not connected to staging yet (the env-sync service is not installed). Nothing was sent. "
                "See docs/runbook/ENVIRONMENTS.md.")))
        if self.sudo().search_count([("target", "=", target), ("login", "=ilike", login.strip()), ("state", "=", "queued")]):
            raise UserError(t(self.env, _("A change for this account is already waiting. Wait for it to finish.")))
        ref = secrets.token_hex(8)
        payload = envs.request_payload(ref, action, target, login, name, role, password_hash)
        path = os.path.join(folder, f"{ref}.json")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        environment = environment or self.env["platform.environment"].sudo().search(
            [("code", "=", "staging" if target == "staging" else "practice")], limit=1)
        request = self.sudo().create({
            "ref": ref, "environment_id": environment.id, "action": action, "target": target,
            "login": payload["login"], "role": role if action == "create" else False, "requested_by_id": self.env.user.id,
        })
        self.env["platform.log"]._record(self._log_action(action, "asked", target), None, self._log_detail(request))
        return request

    @api.model
    def _log_action(self, action, step, target):
        staging = target == "staging"
        texts = {
            ("create", "asked"): (_("Test account creation asked on staging"), _("Test account creation asked in a practice space")),
            ("disable", "asked"): (_("Test account disabling asked on staging"), _("Test account disabling asked in a practice space")),
            ("reset", "asked"): (_("New password asked for a test account on staging"), _("New password asked for a test account in a practice space")),
            ("create", "done"): (_("Test account created on staging"), _("Test account created in a practice space")),
            ("disable", "done"): (_("Test account disabled on staging"), _("Test account disabled in a practice space")),
            ("reset", "done"): (_("Test account given a new password on staging"), _("Test account given a new password in a practice space")),
            ("create", "failed"): (_("Test account creation failed on staging"), _("Test account creation failed in a practice space")),
            ("disable", "failed"): (_("Test account disabling failed on staging"), _("Test account disabling failed in a practice space")),
            ("reset", "failed"): (_("New password for a test account failed on staging"), _("New password for a test account failed in a practice space")),
        }
        return texts[(action, step)][0 if staging else 1]

    @api.model
    def _log_detail(self, request):
        if request.target == "staging":
            return _("%(login)s, role %(role)s, request %(ref)s", login=request.login, role=request.role or "-", ref=request.ref) \
                if request.role else _("%(login)s, request %(ref)s", login=request.login, ref=request.ref)
        slug = request.target[9:]
        return _("%(login)s, space %(slug)s, role %(role)s, request %(ref)s", login=request.login, slug=slug, role=request.role, ref=request.ref) \
            if request.role else _("%(login)s, space %(slug)s, request %(ref)s", login=request.login, slug=slug, ref=request.ref)

    def _close(self, state, code=None):
        for request in self.sudo():
            if request.state != "queued":
                continue
            request.write({"state": state, "code": code or False, "done_at": fields.Datetime.now()})
            self.env["platform.log"]._record(
                self._log_action(request.action, state, request.target), None, self._log_detail(request),
                user=request.requested_by_id,
            )

    @api.model
    def _expire_old(self):
        old = self.sudo().search([("state", "=", "queued"), ("create_date", "<", fields.Datetime.now() - REQUEST_TIMEOUT)])
        old._close("failed", "expired")
