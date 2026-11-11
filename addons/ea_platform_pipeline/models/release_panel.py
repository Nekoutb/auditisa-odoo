from markupsafe import Markup

from odoo import api, fields, models

from odoo.addons.ea_platform_admin.services.messages import _
from ..services import environments as envs
from ..services import progress as progress_service
from .environment import _when
from .i18n import t

# What Staging is doing, step by step. The codes are the practice computer's closed list
# (ea_platform_admin/services/practice.py PROGRESS_CODES); "waiting" is the console's own first step.
STEP_TEXTS = {
    "waiting": _("waiting for Staging to pick it up (about a minute)"),
    "download": _("downloading the version and checking it"),
    "copy": _("the practice spaces are closed for the update; a safety copy of each one is being made"),
    "space": _("updating a practice space"),
    "start": _("starting again and checking that every practice space answers"),
    "template": _("rebuilding the demo template (the practice spaces already run the new version)"),
    "done": _("finishing"),
}
# Why Staging could not install a version (PROGRESS_REASONS).
REASON_TEXTS = {
    "download": _("The version could not be downloaded."),
    "digest": _("The downloaded file is not the one the console registered (its fingerprint differs), so Staging refused it."),
    "bundle": _("The downloaded file could not be opened."),
    "busy": _("Another operation was running on Staging for more than ten minutes."),
    "leftover": _("An earlier update did not finish cleanly: its safety copies are still there."),
    "copy": _("The safety copy of the practice spaces could not be made."),
    "space_update": _("The update of a practice space failed."),
    "no_answer": _("After the update, a practice space did not answer."),
    "template": _("The demo template could not be rebuilt."),
    "other": _("The installation failed."),
}
LINE_TEXTS = {
    "failed": _("failed"),
    "rolled_back": _("failed and put itself back"),
    "timed_out": _("did not answer"),
}


def _bar(percent, kind="running"):
    """A progress bar. `kind`: running (moving stripes), failed (red), warning (amber), done (green)."""
    classes = {
        "running": "progress-bar progress-bar-striped progress-bar-animated",
        "failed": "progress-bar bg-danger",
        "warning": "progress-bar bg-warning",
        "done": "progress-bar bg-success",
    }[kind]
    percent = max(0, min(100, int(percent)))
    return Markup(
        '<div class="progress ea-rel-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="%s">'
        '<div class="%s" style="width: %s%%"></div></div>'
    ) % (percent, classes, percent)


class PlatformEnvironment(models.Model):
    """The Versions panel at the top of the Status page: the same on every environment's page.

    Three rows, in the order a version travels: New version, Staging (the practice spaces), Production (the
    client firms). Each row says which version is there, what is going on (a progress bar while a promotion
    runs, a red box with the reason if it failed), and carries the one button that applies to it. A button
    that cannot be used is greyed, with the reason under it. The page asks for this panel again every few
    seconds while something is going on (static/src/js/release_panel.js) and stops when nothing is.
    """

    _inherit = "platform.environment"

    release_html = fields.Html("Versions", compute="_compute_release_html", sanitize=False)
    release_busy = fields.Boolean(compute="_compute_release_html")

    @api.depends_context("lang", "uid")
    def _compute_release_html(self):
        panel = self._release_panel()
        for environment in self:
            environment.release_html = panel["html"]
            environment.release_busy = panel["busy"]

    def release_panel(self):
        """The panel again, for the page's own refresh: its HTML and whether anything is still going on."""
        self.check_access("read")
        return self._release_panel()

    # ------------------------------------------------------------------ what is going on

    @api.model
    def _staging_progress(self, overview=None):
        """services/progress.staging_progress for the practice computer, as its heartbeat last said."""
        overview = overview or self._release_overview()
        computer = overview["computer"]
        if not computer:
            return progress_service.staging_progress(None, None, None)
        now = fields.Datetime.now()
        report = computer._progress()

        def minutes(moment):
            return (now - moment).total_seconds() / 60 if moment else None

        asked = computer.desired_release_id
        pending = asked.sha if asked and not envs.same_commit(computer.release or "", asked.sha) else None
        return progress_service.staging_progress(
            pending, computer.release, report, minutes(computer.desired_since), minutes(report and report["at"]))

    @api.model
    def _production_progress(self):
        """services/progress.production_progress for the last rollout that started, and that rollout."""
        rollout = self.env["platform.rollout"].sudo().search([("state", "!=", "draft")], limit=1)
        lines = [{"firm": line.firm_id.name, "state": line.state} for line in rollout.line_ids]
        return progress_service.production_progress(rollout.state if rollout else None, lines), rollout

    # ------------------------------------------------------------------ the panel

    @api.model
    def _release_panel(self):
        env = self.env
        overview = self._release_overview()
        staging = self._staging_progress(overview)
        production, rollout = self._production_progress()
        owner = env.user.has_group("ea_platform_admin.group_platform_owner")
        Promote = env["platform.environment.promote"]
        rows = [
            self._panel_row(
                "new", 1, t(env, _("New version")), t(env, _("registered by the developer, not on Staging yet")),
                self._panel_new(overview, staging),
                self._panel_button("action_promote_staging", t(env, _("Promote to Staging")), "btn-primary", owner,
                                   Promote._problem_for("staging", overview["new"])),
            ),
            self._panel_row(
                "staging", 2, t(env, _("Staging")), t(env, _("the practice spaces, on test.auditisa.com")),
                self._panel_staging(overview, staging),
                self._panel_button("action_promote_production", t(env, _("Promote to Production")), "btn-danger", owner,
                                   Promote._problem_for("production", overview["staging"])),
            ),
            self._panel_row(
                "production", 3, t(env, _("Production")), t(env, _("the client firms")),
                self._panel_production(overview, production, rollout), Markup(""),
            ),
        ]
        busy = bool(staging["busy"] or production["busy"])
        live = Markup('<span class="ea-rel-live"><span class="ea-rel-pulse"></span>%s</span>') % t(
            env, _("In progress: this panel updates by itself every few seconds.")) if busy else Markup("")
        head = Markup('<div class="ea-rel-head"><span class="ea-rel-title">%s</span><span class="ea-rel-sub">%s</span>%s</div>') % (
            t(env, _("Versions")),
            t(env, _("A version goes to Staging first, then to Production. This panel is the same on every page.")),
            live,
        )
        html = Markup('<div class="ea-rel" data-busy="%s">%s%s</div>') % ("1" if busy else "0", head, Markup("").join(rows))
        return {"html": html, "busy": busy}

    def _panel_row(self, code, number, title, subtitle, state, action):
        return Markup(
            '<div class="ea-rel-row ea-rel-%s"><div class="ea-rel-what"><span class="ea-rel-num">%s</span>'
            '<div><div class="ea-rel-name">%s</div><div class="ea-rel-where">%s</div></div></div>'
            '<div class="ea-rel-state">%s</div><div class="ea-rel-act">%s</div></div>'
        ) % (code, number, title, subtitle, state, action)

    def _panel_button(self, method, label, style, owner, problem):
        """The row's button; greyed with the reason under it when it cannot be used."""
        env = self.env
        if not owner:
            problem = _("Only the owner promotes a version.")
        if problem:
            return Markup(
                '<button type="button" class="btn btn-secondary ea-rel-button" disabled="disabled">%s</button>'
                '<div class="ea-rel-why">%s</div>'
            ) % (label, t(env, problem))
        return Markup('<button type="button" class="btn %s ea-rel-button" data-ea-action="%s">%s</button>') % (style, method, label)

    def _panel_version(self, release, sha=None):
        sha = release.sha if release else sha
        if not sha:
            return Markup('<span class="text-muted">%s</span>') % t(self.env, _("none yet"))
        label = Markup(" %s") % release.label if release and release.label else Markup("")
        return Markup("<code>%s</code>%s") % (sha[:12], label)

    def _panel_new(self, overview, staging):
        env = self.env
        if overview["new"]:
            return Markup('<div class="ea-rel-line"><b>%s</b> %s</div><div class="ea-rel-note">%s</div>') % (
                t(env, _("New version ready:")), self._panel_version(overview["new"]), t(env, _("Next step: Promote to Staging.")))
        if staging["state"] in ("waiting", "running", "failed"):
            text = _("Sent to Staging: see the next row.")
        else:
            text = _("Nothing new: Staging has the newest version.")
        return Markup('<div class="ea-rel-line text-muted">%s</div>') % t(env, text)

    def _panel_staging(self, overview, staging):
        env = self.env
        computer = overview["computer"]
        if not computer:
            return Markup('<div class="ea-rel-line text-muted">%s</div>') % t(env, _("the practice computer is not connected yet"))
        parts = [Markup('<div class="ea-rel-line"><b>%s</b> %s</div>') % (
            t(env, _("Runs:")), self._panel_version(overview["staging"], overview["running"]))]
        asked = overview["asked"]
        state = staging["state"]
        if state in ("waiting", "running", "finishing"):
            code = "waiting" if state == "waiting" else staging["code"]
            what = t(env, STEP_TEXTS.get(code) or STEP_TEXTS["done"])
            if code == "space" and staging["slug"]:
                what = t(env, _("updating the practice space %(slug)s (%(index)s of %(count)s)",
                                slug=staging["slug"], index=staging["index"], count=staging["count"]))
            if staging["total"]:
                step = t(env, _("Step %(step)s of %(total)s:", step=staging["step"], total=staging["total"]))
            else:
                step = t(env, _("Step 1:"))
            target = asked or overview["staging"]
            news = []
            if asked and computer.desired_since:
                news.append(t(env, _("Asked at %(time)s.", time=_when(computer.desired_since))))
            if computer.last_heartbeat_at:
                news.append(t(env, _("Last news from Staging: %(time)s.", time=_when(computer.last_heartbeat_at))))
            late = Markup("")
            if staging["late"]:
                late = Markup('<div class="ea-rel-late">%s</div>') % t(env, _(
                    "This is taking longer than usual. If nothing moves in the next few minutes, tell the developer."))
            parts.append(Markup(
                '<div class="ea-rel-progress"><div class="ea-rel-line">%s %s</div>'
                '<div class="ea-rel-step"><b>%s</b> %s</div>%s<div class="ea-rel-note">%s</div>%s</div>'
            ) % (t(env, _("Installing")), self._panel_version(target), step, what, _bar(staging["percent"]), " ".join(news), late))
        elif state == "failed":
            reason = t(env, REASON_TEXTS.get(staging["reason"]) or REASON_TEXTS["other"])
            if staging["reason"] in ("space_update", "no_answer") and staging["slug"]:
                reason = t(env, _("The update of the practice space %(slug)s failed.", slug=staging["slug"])) \
                    if staging["reason"] == "space_update" else t(env, _("After the update, the practice space %(slug)s did not answer.", slug=staging["slug"]))
            parts.append(Markup(
                '<div class="ea-rel-progress ea-rel-failed" role="alert"><div class="ea-rel-step"><b>%s</b> %s</div>%s'
                '<div class="ea-rel-line">%s</div><div class="ea-rel-line">%s</div><div class="ea-rel-line"><b>%s</b> %s</div></div>'
            ) % (
                t(env, _("Not installed:")), self._panel_version(asked), _bar(staging["percent"], "failed"), reason,
                t(env, _("Everything was put back as it was: Staging still runs the version above. Nothing changed for the client firms.")),
                t(env, _("What you can do:")),
                t(env, _("tell the developer. Staging will not try this version again by itself.")),
            ))
        elif state == "warning":
            parts.append(Markup(
                '<div class="ea-rel-progress ea-rel-warning" role="alert"><div class="ea-rel-step"><b>%s</b></div>%s'
                '<div class="ea-rel-line">%s</div><div class="ea-rel-line"><b>%s</b> %s</div></div>'
            ) % (
                t(env, _("Installed, with one thing missing")), _bar(staging["percent"], "warning"),
                t(env, _("The practice spaces run the new version, but the demo template could not be rebuilt: "
                         "resetting a practice space will not work until it is.")),
                t(env, _("What you can do:")), t(env, _("tell the developer.")),
            ))
        elif overview["staging"] and not overview["new"]:
            parts.append(Markup('<div class="ea-rel-note ea-rel-ok">%s</div>') % t(env, _("Up to date.")))
        return Markup("").join(parts)

    def _panel_production(self, overview, production, rollout):
        env = self.env
        version = self._panel_version(self._registered_release(overview["production_sha"]), overview["production_sha"])
        count = Markup("")
        if overview["firm_count"]:
            count = Markup(' <span class="text-muted">%s</span>') % t(env, _(
                "%(count)s of %(total)s client firm(s)", count=overview["production_count"], total=overview["firm_count"]))
        parts = [Markup('<div class="ea-rel-line"><b>%s</b> %s%s</div>') % (t(env, _("Runs:")), version, count)]
        if not overview["firm_count"]:
            parts = [Markup('<div class="ea-rel-line text-muted">%s</div>') % t(env, _("No client firm yet"))]
        state = production["state"]
        if state in ("running", "stopped"):
            done = t(env, _("%(done)s of %(total)s client firm(s) updated", done=production["done"], total=production["total"]))
            details = []
            if production["now"]:
                details.append(t(env, _("Updating now: %(firms)s.", firms=", ".join(production["now"]))))
            if production["waiting"]:
                details.append(t(env, _("Waiting their turn: %(count)s.", count=production["waiting"])))
            if state == "running":
                parts.append(Markup(
                    '<div class="ea-rel-progress"><div class="ea-rel-line">%s %s</div><div class="ea-rel-step"><b>%s</b></div>%s'
                    '<div class="ea-rel-note">%s</div><div class="ea-rel-note">%s</div></div>'
                ) % (t(env, _("Sending")), self._panel_version(rollout.release_id), done,
                     _bar(max(production["percent"], 3)), " ".join(details),
                     t(env, _("One firm goes first, alone; the others follow in small batches. Each firm is cut off for a few minutes during its own update."))))
            else:
                bad = "; ".join(f"{firm} {t(env, LINE_TEXTS[line_state])}" for firm, line_state in production["bad"])
                untouched = Markup("")
                if production["untouched"]:
                    untouched = Markup('<div class="ea-rel-line">%s</div>') % t(env, _(
                        "The %(count)s firm(s) after it were not touched.", count=production["untouched"]))
                parts.append(Markup(
                    '<div class="ea-rel-progress ea-rel-failed" role="alert"><div class="ea-rel-step"><b>%s</b> %s</div>%s'
                    '<div class="ea-rel-line">%s: %s</div><div class="ea-rel-line">%s</div>%s'
                    '<div class="ea-rel-line"><b>%s</b> %s</div></div>'
                ) % (
                    t(env, _("Stopped:")), self._panel_version(rollout.release_id), _bar(production["percent"], "failed"), done, bad,
                    t(env, _("A firm whose update fails puts itself back as it was, from its own backup.")), untouched,
                    t(env, _("What you can do:")), t(env, _("tell the developer.")),
                ))
        elif overview["firm_count"] and overview["production_count"] == overview["firm_count"] and overview["staging"] \
                and envs.same_commit(overview["production_sha"] or "", overview["staging"].sha):
            parts.append(Markup('<div class="ea-rel-note ea-rel-ok">%s</div>') % t(env, _("Up to date: every client firm runs Staging's version.")))
        return Markup("").join(parts)
