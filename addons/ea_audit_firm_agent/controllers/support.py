import logging

from odoo import http
from odoo.exceptions import AccessDenied
from odoo.http import request

from ..models.support import SUPPORT_LOGIN

_logger = logging.getLogger(__name__)


class SupportVisit(http.Controller):
    """The operator's way in during an open support visit: a one-time link, never a password.

    The server holds only the link's fingerprint, sent by the control plane in a signed answer and
    written by root's script. The sign-in is the named support account's, so everything done shows
    as support, never as a firm user.
    """

    @http.route("/ea-firm/support/<string:token>", type="http", auth="public", methods=["GET"],
                sitemap=False, readonly=False)
    def enter(self, token, **_kwargs):
        credential = {"type": "ea_support_visit", "login": SUPPORT_LOGIN, "token": token}
        try:
            request.session.authenticate(request.env, credential)
        except AccessDenied:
            _logger.warning("Support visit link refused")
            return request.make_response(
                request.env._("This support link is not valid, or the visit is not open."),
                headers=[("Content-Type", "text/plain; charset=utf-8"), ("Cache-Control", "no-store")], status=403,
            )
        return request.redirect("/odoo", local=True)
