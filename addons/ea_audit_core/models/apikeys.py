"""No API key on a firm's server (owner, 2026-11-07): a key is a password that never expires
and bypasses two-factor login, a major risk for audit files. Refused for every user,
administrators and the superuser included, on every way Odoo offers to make one: the
preferences' wizard, the programmatic ``generate`` and a direct call of ``_generate``.

Keys already made before this, if any, keep working until removed: removing is still allowed.
Odoo's trusted-device record of two-factor login (auth_totp.device) is built on the same model
and stays allowed: it is not an API key."""
from odoo import api, models
from odoo.exceptions import AccessError

_API_KEY_MODEL = "res.users.apikeys"


def _refusal(env):
    return AccessError(env._("API keys are disabled on this firm's server, for every user."))


class ResUsersApikeys(models.Model):
    _inherit = "res.users.apikeys"

    def _generate(self, scope, name, expiration_date):
        if self._name == _API_KEY_MODEL:
            raise _refusal(self.env)
        return super()._generate(scope, name, expiration_date)


class ResUsersApikeysDescription(models.TransientModel):
    _inherit = "res.users.apikeys.description"

    @api.model_create_multi
    def create(self, vals_list):
        raise _refusal(self.env)

    def check_access_make_key(self):
        raise _refusal(self.env)

    def make_key(self):
        raise _refusal(self.env)


class ResUsers(models.Model):
    _inherit = "res.users"

    def api_key_wizard(self):
        raise _refusal(self.env)
