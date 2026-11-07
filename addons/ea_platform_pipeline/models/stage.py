from odoo import api, fields, models

from odoo.addons.ea_platform_admin.services.messages import _
from ..services import collected, pipeline
from .i18n import t

STATE_FILE_PARAM = "ea_platform_pipeline.state_file"
STATE_FILE_DEFAULT = "/var/lib/auditisa-platform/pipeline-state.json"


class PlatformPipelineStage(models.Model):
    """Development, Staging and Production of both tools, side by side: the Pipeline screen.

    GitHub and the running sites are read by deploy/control-plane/pipeline-collect.py, outside Odoo, into a file
    that this model reads and checks again. The firms and the promotions come from this database. The Promote and
    Rebuild buttons are on the Odoo tool's cards only: nothing here can reach the Next.js tool.
    """

    _name = "platform.pipeline.stage"
    _description = "Pipeline stage"
    _order = "tool_sequence, sequence"

    tool = fields.Selection([("next", "Next.js tool"), ("odoo", "Odoo tool")], "Tool", required=True, readonly=True)
    tool_sequence = fields.Integer(readonly=True)
    code = fields.Selection(
        [("development", "Development"), ("staging", "Staging"), ("production", "Production")],
        "Stage", required=True, readonly=True,
    )
    name = fields.Char("Name", required=True, translate=True, readonly=True)
    sequence = fields.Integer(default=10, readonly=True)
    branch = fields.Char("Branch", compute="_compute_state")
    github_commit = fields.Char("On GitHub", compute="_compute_state")
    github_author = fields.Char("Author", compute="_compute_state")
    github_at = fields.Char("Committed", compute="_compute_state")
    running_commit = fields.Char("Running", compute="_compute_state")
    where = fields.Char("Where it runs", compute="_compute_state")
    matches = fields.Selection(
        [("yes", "Matches GitHub"), ("no", "Differs from GitHub"), ("unknown", "Cannot compare"), ("none", "Nothing runs")],
        "Against GitHub", compute="_compute_state",
    )
    ahead = fields.Char("Lead on the next stage", compute="_compute_state")
    last_change = fields.Char("Last release", compute="_compute_state")
    health = fields.Char("Health", compute="_compute_state")
    detail = fields.Text("Detail", compute="_compute_state")
    color = fields.Selection(
        [("green", "Green"), ("amber", "Amber"), ("red", "Red"), ("grey", "Grey")], "Colour", compute="_compute_state",
    )
    reading = fields.Char("Reading", compute="_compute_state")
    can_promote = fields.Boolean(compute="_compute_state")
    can_rebuild = fields.Boolean(compute="_compute_state")

    _stage_unique = models.Constraint("unique(tool, code)", "One row per tool and stage.")

    # ------------------------------------------------------------------ reading

    @api.model
    def _collected(self):
        path = self.env["ir.config_parameter"].sudo().get_param(STATE_FILE_PARAM, STATE_FILE_DEFAULT)
        try:
            with open(path, "rb") as handle:
                raw = handle.read(collected.MAX_BYTES + 1)
        except OSError:
            return None
        return collected.read_state(raw, fields.Datetime.now())

    def _production_firms(self):
        return self.env["platform.firm"].sudo().search([("pipeline_role", "=", "firm"), ("state", "=", "active")])

    def _last_promotion(self):
        return self.env["platform.pipeline.promotion"].sudo().search(
            [("state", "in", ("rolling", "awaiting_main", "done"))], limit=1,
        )

    @api.depends_context("lang")
    def _compute_state(self):
        env = self.env
        state = self._collected()
        for stage in self:
            values = dict.fromkeys(
                ("branch", "github_commit", "github_author", "github_at", "running_commit", "where", "ahead",
                 "last_change", "health", "detail"), False)
            values.update({"matches": "unknown", "color": "grey", "can_promote": False, "can_rebuild": False})
            if not state:
                values["reading"] = t(env, _("No reading yet: is pipeline-collect running? See PIPELINE.md, section 2."))
            elif state["stale"]:
                values["reading"] = t(env, _("Old reading: the collector last wrote at %(time)s UTC.",
                                             time=state["generated"].strftime("%H:%M")))
            else:
                values["reading"] = t(env, _("Read at %(time)s UTC, at most a minute behind GitHub. Reload to read again.",
                                             time=state["generated"].strftime("%H:%M")))
            tool = (state or {}).get(stage.tool) or {}
            getattr(stage, f"_fill_{stage.tool}")(values, tool)
            stage.update(values)

    def _github(self, values, tool, branch):
        commit = (tool.get("branches") or {}).get(branch)
        values["branch"] = branch
        if commit:
            values["github_commit"] = commit["sha"][:12]
            values["github_author"] = commit["author"] or False
            values["github_at"] = (commit["at"] or "")[:16].replace("T", " ") or False
        elif tool.get("github") == "no_key":
            values["detail"] = t(self.env, _("GitHub access is not set up for this private repository: see PIPELINE.md, section 2."))
        elif tool.get("github") == "unreachable":
            values["detail"] = t(self.env, _("GitHub did not answer at the last reading."))
        return commit

    def _lead(self, count, label):
        if count is None:
            return False
        if count == 0:
            return t(self.env, _("Level with %(stage)s", stage=label))
        return t(self.env, _("%(count)s commit(s) ahead of %(stage)s", count=count, stage=label))

    @staticmethod
    def _match(values, head, running):
        if not running:
            values["matches"] = "none"
        elif head:
            values["matches"] = "yes" if head["sha"] == running["sha"] else "no"

    def _fill_next(self, values, tool):
        env = self.env
        ahead = tool.get("ahead") or {}
        sites = tool.get("sites") or {}
        running = tool.get("running") or {}
        if self.code == "development":
            self._github(values, tool, "dev")
            values["where"] = t(env, _("No server of its own: dev.auditisa.com is its staging"))
            values["matches"] = "none"
            values["ahead"] = self._lead(ahead.get("development_over_staging"), t(env, _("Staging")))
            values["color"] = "green" if tool.get("github") == "ok" else "grey"
            return
        branch, site, url = ("dev", "staging", "dev.auditisa.com") if self.code == "staging" else ("main", "production", "www.auditisa.com")
        head = self._github(values, tool, branch)
        now = running.get(site)
        values["where"] = url
        values["running_commit"] = now["sha"][:12] if now else False
        self._match(values, head, now)
        figures = sites.get(site) or {}
        values["health"] = t(env, _("Up")) if figures.get("up") else t(env, _("Not answering"))
        values["last_change"] = (figures.get("started_at") or "")[:16].replace("T", " ") or False
        if self.code == "staging":
            values["ahead"] = self._lead(ahead.get("staging_over_production"), t(env, _("Production")))
        elif ahead.get("main_over_production"):
            values["detail"] = t(env, _("%(count)s commit(s) on main not yet running", count=ahead["main_over_production"]))
        values["color"] = "red" if not figures.get("up") else ("green" if values["matches"] == "yes" else "amber")

    def _fill_odoo(self, values, tool):
        getattr(self, f"_fill_odoo_{self.code}")(values, tool)

    def _fill_odoo_development(self, values, tool):
        env = self.env
        self._github(values, tool, "dev")
        values["where"] = t(env, _("Agents' throwaway databases; no server of its own"))
        values["matches"] = "none"
        values["ahead"] = self._lead((tool.get("ahead") or {}).get("development_over_staging"), t(env, _("Staging")))
        run = env["platform.pipeline.test.run"].sudo().search([], limit=1)
        if run:
            values["detail"] = t(env, _("Last test run: %(commit)s, %(suite)s, %(passed)s passed, %(failed)s failed",
                                        commit=run.commit_sha[:12], suite=run.suite, passed=run.passed, failed=run.failed))
        values["color"] = ("red" if run and run.failed else "green") if tool.get("github") == "ok" else "grey"

    def _fill_odoo_staging(self, values, tool):
        env = self.env
        branches = tool.get("branches") or {}
        branch = "staging" if branches.get("staging") else "dev"
        head = self._github(values, tool, branch)
        if branch == "dev" and tool.get("github") == "ok":
            values["detail"] = t(env, _("No staging branch yet: staging follows dev."))
        now = (tool.get("running") or {}).get("staging")
        site = (tool.get("sites") or {}).get("staging") or {}
        values["where"] = "test.auditisa.com"
        values["running_commit"] = now["sha"][:12] if now else False
        self._match(values, head, now)
        if not now:
            values["matches"] = "unknown"
        health = t(env, _("Up")) if site.get("up") else t(env, _("Not answering"))
        safe = None
        if site.get("mail_off") is not None:
            safe = bool(site.get("mail_off") and site.get("band_on"))
            health += " · " + (t(env, _("mail off, band on")) if safe else t(env, _("check mail and band")))
        values["health"] = health
        values["ahead"] = self._lead((tool.get("ahead") or {}).get("staging_over_main"), t(env, _("Production")))
        rebuild = env["platform.pipeline.rebuild"].sudo().search([], limit=1)
        if rebuild:
            label = dict(rebuild._fields["state"]._description_selection(env)).get(rebuild.state)
            values["last_change"] = t(env, _("Rebuild: %(state)s, %(date)s", state=label,
                                             date=fields.Datetime.to_string(rebuild.rebuilt_at or rebuild.requested_at)[:16]))
        if not site.get("up") or safe is False:
            values["color"] = "red"
        else:
            values["color"] = "amber" if values["matches"] == "no" else "green"
        values["can_rebuild"] = True

    def _fill_odoo_production(self, values, tool):
        env = self.env
        head = self._github(values, tool, "main")
        firms = self._production_firms()
        promotion = self._last_promotion()
        target = promotion.release_id
        values["where"] = t(env, _("%(count)s firm server(s)", count=len(firms))) if firms else t(env, _("No firm server yet"))
        values["running_commit"] = target.sha[:12] if target else False
        if not firms:
            values["matches"] = "none"
        elif head and target:
            values["matches"] = "yes" if pipeline.same_commit(head["sha"], target.sha) else "no"
        on_target = len(firms.filtered(lambda firm: target and pipeline.same_commit(firm.addon_release, target.sha)))
        reds = firms.filtered(lambda firm: firm.health_color == "red")
        if firms:
            values["health"] = t(env, _("%(on)s of %(all)s on this release", on=on_target, all=len(firms)))
        if promotion.rollout_id:
            lines = promotion.rollout_id.line_ids
            values["detail"] = t(env, _("Rollout: %(done)s of %(total)s through",
                                        done=len(lines.filtered(lambda line: line.state == "healthy")), total=len(lines)))
        if reds:
            values["detail"] = t(env, _("%(count)s firm(s) red", count=len(reds)))
        values["last_change"] = fields.Datetime.to_string(promotion.started_at)[:16] if promotion.started_at else False
        if not firms:
            values["color"] = "grey"
        elif reds:
            values["color"] = "red"
        else:
            values["color"] = "green" if target and on_target == len(firms) else "amber"
        values["can_promote"] = True

    # ------------------------------------------------------------------ the two buttons, Odoo only

    def action_new_promotion(self):
        self.ensure_one()
        if not (self.tool == "odoo" and self.code == "production"):
            return False
        self.env["platform.pipeline.guard"]._require_owner()
        return {
            "type": "ir.actions.act_window", "res_model": "platform.pipeline.promotion", "view_mode": "form",
            "target": "current", "name": t(self.env, _("New promotion")),
        }

    def action_new_rebuild(self):
        self.ensure_one()
        if not (self.tool == "odoo" and self.code == "staging"):
            return False
        return self.env["platform.pipeline.confirm"]._open_new_rebuild()
