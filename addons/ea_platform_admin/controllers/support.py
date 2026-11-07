import logging

from odoo import SUPERUSER_ID, http
from odoo.http import request

from ..services import heartbeat, support

_logger = logging.getLogger(__name__)


class SupportController(http.Controller):
    """The firm's 'Report a problem' channel: two signed POST paths beside the heartbeat.

    nginx lets these two paths through on the heartbeat address (deploy/control-plane). Every refusal
    looks the same to the caller.
    """

    @http.route("/platform/support/ticket", type="http", auth="none", methods=["POST"], csrf=False,
                sitemap=False, save_session=False, readonly=False)
    def ticket(self, **_kwargs):
        return self._handle(support.PREFIX_TICKET)

    @http.route("/platform/support/sync", type="http", auth="none", methods=["POST"], csrf=False,
                sitemap=False, save_session=False, readonly=False)
    def sync(self, **_kwargs):
        return self._handle(support.PREFIX_SYNC)

    def _handle(self, prefix):
        body = request.httprequest.get_data(cache=False)
        if request.httprequest.mimetype != "application/json":
            return self._refuse("bad_content_type")
        env = request.env(user=SUPERUSER_ID)
        try:
            answer, signature = env["platform.firm"]._receive_support(prefix, request.httprequest.headers, body)
        except heartbeat.HeartbeatRejected as rejected:
            return self._refuse(rejected.code)
        return request.make_response(answer, headers=[
            ("Content-Type", "application/json"),
            (heartbeat.HEADER_RESPONSE_SIGNATURE, signature),
            ("Cache-Control", "no-store"),
        ])

    def _refuse(self, code):
        _logger.info("Support message refused: %s", code)
        return request.make_response('{"ok":false}', headers=[("Content-Type", "application/json")], status=403)
