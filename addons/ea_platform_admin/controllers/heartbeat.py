import logging

from odoo import SUPERUSER_ID, http
from odoo.http import request

from ..services import heartbeat

_logger = logging.getLogger(__name__)


class HeartbeatController(http.Controller):
    """The only door a firm's server has into the control plane.

    nginx exposes this path alone on the heartbeat address (deploy/control-plane). No session,
    no cookie. Every refusal looks the same to the caller; the reason stays here.
    """

    @http.route(
        "/platform/heartbeat",
        type="http", auth="none", methods=["POST"], csrf=False, sitemap=False, save_session=False, readonly=False,
    )
    def receive(self, **_kwargs):
        body = request.httprequest.get_data(cache=False)
        if request.httprequest.mimetype != "application/json":
            return self._refuse("bad_content_type")
        env = request.env(user=SUPERUSER_ID)
        try:
            answer, signature = env["platform.firm"]._receive_heartbeat(request.httprequest.headers, body)
        except heartbeat.HeartbeatRejected as rejected:
            return self._refuse(rejected.code)
        return request.make_response(answer, headers=[
            ("Content-Type", "application/json"),
            (heartbeat.HEADER_RESPONSE_SIGNATURE, signature),
            ("Cache-Control", "no-store"),
        ])

    def _refuse(self, code):
        _logger.info("Heartbeat refused: %s", code)
        return request.make_response(
            '{"ok":false}', headers=[("Content-Type", "application/json")], status=403,
        )
