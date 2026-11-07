import re

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

from odoo.addons.ea_platform_admin.services.messages import _
from .i18n import t

_SHA = re.compile(r"^[0-9a-f]{7,40}$")


class PlatformPipelineTestRun(models.Model):
    """A test run recorded by hand or by a script, for one commit. GitHub Actions is stopped for now.

    Append-only. A run that went wrong is followed by a newer one, never edited.
    """

    _name = "platform.pipeline.test.run"
    _description = "Test run"
    _order = "id desc"
    _rec_name = "commit_sha"

    commit_sha = fields.Char("Commit", required=True, index=True)
    suite = fields.Char("Suite", required=True, help="For example: odoo, pure, anonymiser.")
    passed = fields.Integer("Passed", required=True)
    failed = fields.Integer("Failed", required=True)
    note = fields.Char("Where it ran")
    recorded_by_id = fields.Many2one("res.users", "Recorded by", readonly=True, default=lambda self: self.env.user)

    @api.constrains("commit_sha", "passed", "failed")
    def _check_values(self):
        for run in self:
            if not _SHA.match(run.commit_sha or ""):
                raise ValidationError(t(self.env, _("The commit must be 7 to 40 hexadecimal characters.")))
            if run.passed < 0 or run.failed < 0:
                raise ValidationError(t(self.env, _("A count cannot be negative.")))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for run in records:
            self.env["platform.log"]._record(
                _("Test run recorded"), None,
                _("%(commit)s, %(suite)s: %(passed)s passed, %(failed)s failed",
                  commit=run.commit_sha[:12], suite=run.suite, passed=run.passed, failed=run.failed),
            )
        return records

    def write(self, vals):
        raise AccessError(t(self.env, _("A recorded test run cannot be changed.")))

    def unlink(self):
        raise AccessError(t(self.env, _("A recorded test run cannot be deleted.")))
