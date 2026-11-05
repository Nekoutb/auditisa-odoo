"""Messages that can be shown in the reader's language. Pure.

Services cannot import Odoo, and much of what they say is stored and read later by someone else
(a health reason, a step's message, a log entry), so it cannot be translated when it is written.
`_("Disk %(pct)s%% full", pct=85)` therefore gives a `Msg`: a plain English string that remembers its
template and parameters. It is stored with `dumps` and translated when read, by models/i18n.py.

The name `_` is deliberate: Odoo's translation export picks up `_("...")` from every Python file of
the addon, so these sources land in i18n/fr.po like any others.
"""

import json

_PREFIX = '{"t":'
_LIST_PREFIX = '{"l":'


class Msg(str):
    def __new__(cls, template, params=None):
        params = params or {}
        self = super().__new__(cls, template % params if params else template)
        self.template = template
        self.params = params
        return self


def _(template, **params):
    return Msg(template, params)


def _encode(value):
    if isinstance(value, Msg):
        return {"t": value.template, "p": {key: _encode(item) for key, item in value.params.items()}}
    return value


def _decode(value):
    if isinstance(value, dict) and "t" in value:
        return Msg(value["t"], {key: _decode(item) for key, item in value.get("p", {}).items()})
    return value


def dumps(value):
    """Text for a database column. A message without parameters stays its plain source text."""
    if isinstance(value, Msg):
        return value.template if not value.params else json.dumps(_encode(value), ensure_ascii=False)
    return value


def dumps_list(values):
    return json.dumps({"l": [_encode(value) for value in values]}, ensure_ascii=False)


def loads(raw):
    """A list of what `dumps` or `dumps_list` wrote. Text that is neither is one plain item."""
    if not raw:
        return []
    if raw.startswith((_PREFIX, _LIST_PREFIX)):
        try:
            data = json.loads(raw)
        except ValueError:
            return [raw]
        if "l" in data:
            return [_decode(item) for item in data["l"]]
        return [_decode(data)]
    return [Msg(raw)] if "%" not in raw else [raw]


def render(value, translate):
    """The text of a message, with `translate(source)` applied at every level."""
    if isinstance(value, Msg):
        template = translate(value.template)
        if not value.params:
            return template
        return template % {key: render(item, translate) for key, item in value.params.items()}
    return str(value)
