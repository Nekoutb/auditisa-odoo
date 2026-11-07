from datetime import datetime, timezone

from odoo import api, fields, models

from odoo.addons.ea_platform_admin.services.messages import _
from ..services import pipeline
from .i18n import t


def _instant(value):
    return value.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


class PlatformPipelineStage(models.Model):
    """The three stages of the Odoo tool, as this control plane can see them.

    It has no connection to GitHub: status.auditisa.com shows the branches. Here is what the heartbeats and the
    pipeline's own records say. `dev` to `staging` to `main`, and `main` is what the firm servers run.
    """

    _name = "platform.pipeline.stage"
    _description = "Pipeline stage"
    _order = "sequence"

    code = fields.Selection(
        [("development", "Development"), ("staging", "Staging"), ("production", "Production")],
        "Stage", required=True, readonly=True,
    )
    name = fields.Char("Name", required=True, translate=True, readonly=True)
    sequence = fields.Integer(default=10, readonly=True)
    branch = fields.Char("Branch", required=True, readonly=True)
    where = fields.Char("Where it runs", compute="_compute_state")
    commit = fields.Char("Commit", compute="_compute_state")
    health = fields.Char("Health", compute="_compute_state")
    detail = fields.Text("Detail", compute="_compute_state")
    color = fields.Selection(
        [("green", "Green"), ("amber", "Amber"), ("red", "Red"), ("grey", "Grey")], "Colour", compute="_compute_state",
    )

    _code_unique = models.Constraint("unique(code)", "One row per stage.")

    def _production_firms(self):
        return self.env["platform.firm"].sudo().search([("pipeline_role", "=", "firm"), ("state", "=", "active")])

    def _target_release(self):
        promotion = self.env["platform.pipeline.promotion"].sudo().search(
            [("state", "in", ("rolling", "awaiting_main", "done"))], limit=1,
        )
        return promotion.release_id

    @api.depends_context("lang")
    def _compute_state(self):
        env = self.env
        for stage in self:
            stage.where = stage.commit = stage.health = stage.detail = False
            stage.color = "grey"
            if stage.code == "development":
                run = env["platform.pipeline.test.run"].sudo().search([], limit=1)
                stage.where = t(env, _("Agents' throwaway databases; no server of its own"))
                stage.commit = run.commit_sha[:12] if run else False
                stage.health = t(env, _("Last recorded test run")) if run else t(env, _("No test run recorded"))
                stage.detail = (
                    t(env, _("%(suite)s: %(passed)s passed, %(failed)s failed", suite=run.suite, passed=run.passed, failed=run.failed))
                    if run else False
                )
                stage.color = ("red" if run.failed else "green") if run else "grey"
            elif stage.code == "staging":
                firm = env["platform.firm"].sudo().search([("pipeline_role", "=", "staging"), ("state", "!=", "archived")], limit=1)
                stage.where = firm.name if firm else "test.auditisa.com"
                if firm:
                    stage.commit = (firm.addon_release or "")[:12] or False
                    word = firm._staging_health_word()
                    stage.health = {
                        "ok": t(env, _("Reporting")), "down": t(env, _("Not reporting")), "unknown": t(env, _("Never reported")),
                    }[word]
                    stage.color = {"ok": "green", "down": "red", "unknown": "grey"}[word]
                    stage.detail = t(env, _("Mail is on!")) if firm.mail_enabled else t(env, _("Mail is off"))
                else:
                    stage.health = t(env, _("Not reporting here yet"))
                    stage.detail = t(env, _("Mark the staging server: docs/runbook/PIPELINE.md, section 2."))
            else:
                firms = stage._production_firms()
                target = stage._target_release()
                stage.where = t(env, _("%(count)s firm server(s)", count=len(firms)))
                stage.commit = target.sha[:12] if target else False
                on_target = len(firms.filtered(lambda firm: pipeline.same_commit(firm.addon_release, target.sha))) if target else 0
                reds = firms.filtered(lambda firm: firm.health_color == "red")
                stage.health = (
                    t(env, _("%(on)s of %(all)s on this release", on=on_target, all=len(firms)))
                    if target else t(env, _("No release promoted yet"))
                )
                stage.detail = t(env, _("%(count)s firm(s) red", count=len(reds))) if reds else False
                if not firms:
                    stage.color = "grey"
                elif reds:
                    stage.color = "red"
                else:
                    stage.color = "green" if target and on_target == len(firms) else "amber"

    def action_new_promotion(self):
        return {
            "type": "ir.actions.act_window", "res_model": "platform.pipeline.promotion", "view_mode": "form",
            "target": "current", "name": t(self.env, _("New promotion")),
        }

    def action_new_rebuild(self):
        return self.env["platform.pipeline.confirm"]._open_new_rebuild()

    @api.model
    def _public_state(self):
        """What status.auditisa.com may read. Counts, commits, dates and closed words: no firm, person or reason."""
        firms = self._production_firms()
        promotion = self.env["platform.pipeline.promotion"].sudo().search(
            [("kind", "=", "promote"), ("state", "in", ("rolling", "awaiting_main", "done"))], limit=1,
        )
        target = promotion.release_id
        rollout = promotion.rollout_id
        rebuild = self.env["platform.pipeline.rebuild"].sudo().search([], limit=1)
        staging = self.env["platform.firm"].sudo().search([("pipeline_role", "=", "staging"), ("state", "!=", "archived")], limit=1)
        return pipeline.public_state({
            "schema": 1,
            "generated_at": _instant(datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)),
            "firms_total": len(firms),
            "firms_on_target": len(firms.filtered(lambda firm: pipeline.same_commit(firm.addon_release, target.sha))) if target else 0,
            "target_release": target.sha if target else None,
            "rollout_state": rollout.state if rollout else None,
            "rollout_done": len(rollout.line_ids.filtered(lambda line: line.state == "healthy")) if rollout else 0,
            "rollout_total": len(rollout.line_ids) if rollout else 0,
            "last_promotion_at": _instant(promotion.started_at),
            "last_promotion_release": target.sha if target else None,
            "last_rebuild_at": _instant(rebuild.rebuilt_at or rebuild.requested_at) if rebuild else None,
            "last_rebuild_state": rebuild.state if rebuild else None,
            "staging_release": staging.addon_release if staging else None,
            "staging_health": staging._staging_health_word() if staging else None,
        })
