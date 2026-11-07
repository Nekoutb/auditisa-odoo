"""The practice computer, as the control room sees it. Pure: no Odoo, no network.

The practice computer holds one practice space per client firm (deploy/practice). It sends one
heartbeat for itself and all its spaces, signed like a firm's under its own prefix
(deploy/practice/practice_heartbeat.py), so neither can pass for the other. As for a firm, a key
outside the list below rejects the whole heartbeat, and every value must match a closed pattern:
figures only, never a name, a login or a record of a space.

Release order: a release goes to the practice computer first. A firm's real server is offered it
only once the practice computer has run it for the holding period (7 days unless the owner sets
another number on that release). `hold_status` decides it.
"""

import base64
import hashlib
import hmac
import json
import re
from datetime import datetime, timedelta

from .heartbeat import MAX_CLOCK_SKEW_SECONDS, HeartbeatRejected
from .messages import _

PREFIX = b"ea-practice-heartbeat-v1"
RESPONSE_PREFIX = b"ea-practice-heartbeat-response-v1"
HEADER_COMPUTER = "X-EA-Practice"
HEADER_TIMESTAMP = "X-EA-Timestamp"
HEADER_SIGNATURE = "X-EA-Signature"
HEADER_RESPONSE_SIGNATURE = "X-EA-Response-Signature"
SCHEMA_VERSION = 1
MAX_SPACES = 300
MAX_BODY_BYTES = 400 * MAX_SPACES + 1024
DEFAULT_HOLD_DAYS = 7

_NAME = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
_SLUG = re.compile(r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$")
_SIGNATURE = re.compile(r"^[0-9a-f]{64}$")
_RELEASE = re.compile(r"^[0-9a-f]{7,40}$")
_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ADDON = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
_LOGIN = re.compile(r"^[A-Za-z0-9._+-]{1,64}(@[A-Za-z0-9.-]{1,190})?$")


def _message(prefix, computer, timestamp, body):
    return b"\n".join([prefix, computer.encode("ascii"), str(timestamp).encode("ascii"), hashlib.sha256(body).hexdigest().encode("ascii")])


def sign(token, computer, timestamp, body):
    return hmac.new(token.encode("utf-8"), _message(PREFIX, computer, timestamp, body), hashlib.sha256).hexdigest()


def sign_response(token, computer, timestamp, body):
    return hmac.new(token.encode("utf-8"), _message(RESPONSE_PREFIX, computer, timestamp, body), hashlib.sha256).hexdigest()


def _optional(pattern):
    def check(value):
        return value is None or (type(value) is str and bool(pattern.match(value)))
    return check


def _int(low, high, optional=False):
    def check(value):
        return (optional and value is None) or (type(value) is int and low <= value <= high)
    return check


SPACE_FIGURES = {
    "slug": lambda value: type(value) is str and bool(_SLUG.match(value)),
    "state": lambda value: value in ("ready", "missing"),
    "last_reset_at": _optional(_INSTANT),
    "users": _int(0, 99999, optional=True),
    "last_login_on": _optional(_DAY),
    "reset_generation": _int(0, 10 ** 9 - 1),
    "addons_on": lambda value: type(value) is list and len(value) <= 24 and all(type(c) is str and _ADDON.match(c) for c in value),
    "link_set": lambda value: type(value) is bool,
}
FIGURES = {
    "schema": lambda value: type(value) is int and value == SCHEMA_VERSION,
    "computer": lambda value: type(value) is str and bool(_NAME.match(value)),
    "release": _optional(_RELEASE),
    "template_release": _optional(_RELEASE),
    "guard": lambda value: value in ("ok", "refused", "unknown"),
    "spaces": lambda value: type(value) is list and len(value) <= MAX_SPACES,
}


def _refuse_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise HeartbeatRejected("duplicate_key")
        result[key] = value
    return result


def parse_figures(body):
    """The validated figures, or a rejection. An unknown key anywhere rejects it all."""
    if len(body) > MAX_BODY_BYTES:
        raise HeartbeatRejected("body_too_large")
    try:
        data = json.loads(body.decode("utf-8"), object_pairs_hook=_refuse_duplicates)
    except (UnicodeDecodeError, ValueError):
        raise HeartbeatRejected("not_json") from None
    if not isinstance(data, dict) or set(data) != set(FIGURES):
        raise HeartbeatRejected("unknown_key" if isinstance(data, dict) and set(data) - set(FIGURES) else "missing_key")
    for key, value in data.items():
        if not FIGURES[key](value):
            raise HeartbeatRejected("bad_value")
    seen = set()
    for space in data["spaces"]:
        if not isinstance(space, dict) or set(space) != set(SPACE_FIGURES):
            raise HeartbeatRejected("bad_space")
        for key, value in space.items():
            if not SPACE_FIGURES[key](value):
                raise HeartbeatRejected("bad_value")
        if space["slug"] in seen:
            raise HeartbeatRejected("duplicate_space")
        seen.add(space["slug"])
    return data


def accept(headers, body, find_computer, now_seconds):
    """`find_computer(name)` returns (token, last_timestamp) or None. Returns (name, timestamp, figures).

    The signature is checked before the body is parsed, as for a firm."""
    name = headers.get(HEADER_COMPUTER) or ""
    raw_timestamp = headers.get(HEADER_TIMESTAMP) or ""
    signature = headers.get(HEADER_SIGNATURE) or ""
    if not _NAME.match(name):
        raise HeartbeatRejected("bad_computer_header")
    if not raw_timestamp.isascii() or not raw_timestamp.isdigit() or len(raw_timestamp) > 12:
        raise HeartbeatRejected("bad_timestamp_header")
    if not _SIGNATURE.match(signature):
        raise HeartbeatRejected("bad_signature_header")
    if len(body) > MAX_BODY_BYTES:
        raise HeartbeatRejected("body_too_large")
    found = find_computer(name)
    if not found or not found[0]:
        raise HeartbeatRejected("unknown_computer")
    token, last_timestamp = found
    timestamp = int(raw_timestamp)
    if not hmac.compare_digest(sign(token, name, timestamp, body), signature):
        raise HeartbeatRejected("bad_signature")
    if abs(now_seconds - timestamp) > MAX_CLOCK_SKEW_SECONDS:
        raise HeartbeatRejected("stale_timestamp")
    if last_timestamp and timestamp <= last_timestamp:
        raise HeartbeatRejected("replayed_timestamp")
    return name, timestamp, parse_figures(body)


def parse_instant(value):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ") if value else None


def format_instant(value):
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


def space_request(slug, name, login, lang, addons, generation, link_hash=None, link_expires=None):
    """One space as the answer asks for it. What the practice computer checks again, field by field."""
    if not _SLUG.match(slug or "") or not _LOGIN.match(login or ""):
        return None
    item = {
        "slug": slug,
        "name_b64": base64.b64encode((name or slug)[:80].replace("\n", " ").replace("\t", " ").encode("utf-8")).decode("ascii"),
        "admin_login": login,
        "lang": lang if lang in ("fr_FR", "en_US") else "fr_FR",
        "addons": sorted({code for code in addons if _ADDON.match(code)}),
        "reset_generation": int(generation or 0),
    }
    if link_hash and link_expires:
        item["first_admin_hash"] = link_hash
        item["first_admin_expires"] = format_instant(link_expires)
    return item


def link_hash(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def hold_status(practice_since, hold_days, now):
    """(ok, until, message) for offering a release to the firms.

    `practice_since` is when the practice computer first reported running the release (None: not
    yet). `hold_days` 0 means the owner chose not to wait for this release.
    """
    days = DEFAULT_HOLD_DAYS if hold_days is None else max(0, int(hold_days))
    if days == 0:
        return True, None, _("Holding period waived by the owner for this release.")
    if not practice_since:
        return False, None, _("Not yet on the practice computer: firms are offered a release after %(days)s days there.", days=days)
    until = practice_since + timedelta(days=days)
    if now >= until:
        return True, until, _("On the practice computer for %(days)s days or more: firms may have it.", days=days)
    return False, until, _(
        "On the practice computer since %(since)s: firms may have it from %(until)s.",
        since=practice_since.strftime("%Y-%m-%d %H:%M"), until=until.strftime("%Y-%m-%d %H:%M"),
    )
