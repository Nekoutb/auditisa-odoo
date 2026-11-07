import logging

from odoo import SUPERUSER_ID, http
from odoo.http import request

from ..services import practice
from ..services.heartbeat import HeartbeatRejected

_logger = logging.getLogger(__name__)


class PracticeHeartbeatController(http.Controller):
    """The practice computer's door into the control room. Same rules as a firm's heartbeat:
    no session, signed, figures only; every refusal looks the same to the caller."""

    @http.route(
        "/platform/practice-heartbeat",
        type="http", auth="none", methods=["POST"], csrf=False, sitemap=False, save_session=False, readonly=False,
    )
    def receive(self, **_kwargs):
        body = request.httprequest.get_data(cache=False)
        if request.httprequest.mimetype != "application/json":
            return self._refuse("bad_content_type")
        env = request.env(user=SUPERUSER_ID)
        try:
            answer, signature = env["platform.practice.computer"]._receive_heartbeat(request.httprequest.headers, body)
        except HeartbeatRejected as rejected:
            return self._refuse(rejected.code)
        return request.make_response(answer, headers=[
            ("Content-Type", "application/json"),
            (practice.HEADER_RESPONSE_SIGNATURE, signature),
            ("Cache-Control", "no-store"),
        ])

    def _refuse(self, code):
        _logger.info("Practice heartbeat refused: %s", code)
        return request.make_response('{"ok":false}', headers=[("Content-Type", "application/json")], status=403)
