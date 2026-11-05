import logging

from odoo import fields, http
from odoo.http import request

from ..services.first_admin import MIN_PASSWORD_LENGTH, is_expired, password_problem, token_matches

_logger = logging.getLogger(__name__)

PARAM_HASH = "ea_firm_agent.first_admin_hash"
PARAM_EXPIRES = "ea_firm_agent.first_admin_expires"
HEADERS = {
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow",
}


class FirstAdmin(http.Controller):
    """The firm's first administrator chooses a password through a link that works once.

    No password is ever sent or known to anyone else. The account exists from the install, with a
    random password that nobody holds. The server stores only the hash of the link's token.
    """

    def _link_is_valid(self, token):
        get_param = request.env["ir.config_parameter"].sudo().get_param
        if not token_matches(token, get_param(PARAM_HASH)):
            return False
        expires = get_param(PARAM_EXPIRES)
        return bool(expires) and not is_expired(fields.Datetime.to_datetime(expires), fields.Datetime.now())

    def _render(self, **values):
        return request.render("ea_audit_firm_agent.first_admin_page", values, headers=HEADERS)

    @http.route(
        "/ea-firm/first-admin/<string:token>",
        type="http", auth="public", methods=["GET", "POST"], sitemap=False, readonly=False,
    )
    def first_admin(self, token, password=None, confirmation=None, **_kwargs):
        # The firm's language, chosen at onboarding: nobody is logged in yet to have a preference.
        lang = request.env(su=True).company.partner_id.lang
        if lang:
            request.update_context(lang=lang)
        if not self._link_is_valid(token):
            _logger.warning("First-administrator link refused")
            return self._render(invalid=True)
        env = request.env(su=True)
        admin = env.ref("base.user_admin")
        values = {"firm_name": env.company.name, "login": admin.login}
        if request.httprequest.method != "POST":
            return self._render(**values)
        problem = password_problem(password, confirmation)
        if problem:
            message = (
                request.env._("The password must be at least %(length)s characters.", length=MIN_PASSWORD_LENGTH)
                if problem == "too_short" else request.env._("The two entries do not match.")
            )
            return self._render(error=message, **values)
        admin.write({"password": password})
        env["ir.config_parameter"].search([("key", "in", [PARAM_HASH, PARAM_EXPIRES])]).unlink()
        _logger.info("First administrator set through the one-time link")
        return request.redirect("/web/login", local=True)
