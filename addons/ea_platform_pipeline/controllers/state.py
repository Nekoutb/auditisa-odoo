import json

from odoo import SUPERUSER_ID, http
from odoo.http import request


class PipelineStateController(http.Controller):
    """What status.auditisa.com reads: counts, commits, dates and closed words.

    No session. nginx opens this one path to the status server's address alone (deploy/control-plane).
    It accepts nothing and can change nothing.
    """

    @http.route(
        "/platform/pipeline-state",
        type="http", auth="none", methods=["GET"], csrf=False, sitemap=False, save_session=False, readonly=True,
    )
    def state(self, **_kwargs):
        env = request.env(user=SUPERUSER_ID)
        body = json.dumps(env["platform.pipeline.stage"]._public_state(), sort_keys=True, separators=(",", ":"))
        return request.make_response(body, headers=[
            ("Content-Type", "application/json"),
            ("Cache-Control", "no-store"),
        ])
