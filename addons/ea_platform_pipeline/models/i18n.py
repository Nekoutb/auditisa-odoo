"""Stored messages, in the reader's language. Same reading as ea_platform_admin/models/i18n.py.

Odoo finds a code translation by the module of the code that asks, so a message of this addon must be
asked for from here, and one of ea_platform_admin from there. A log row can come from either.
"""

from odoo.addons.ea_platform_admin.models.i18n import t as admin_t
from odoo.addons.ea_platform_admin.services.messages import Msg, loads, render


def t(env, message):
    return render(message, lambda source: env._(source))


def read(env, raw):
    return "\n".join(t(env, message) for message in loads(raw))


def read_any(env, raw):
    """For a column both addons write to: this addon's French, or the other's."""

    def translate(source):
        mine = env._(source)
        return mine if mine != source else admin_t(env, Msg(source))

    return "\n".join(render(message, translate) for message in loads(raw))
