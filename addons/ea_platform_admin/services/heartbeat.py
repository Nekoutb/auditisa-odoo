"""The receiving side of the heartbeat. Pure: no Odoo, no network.

A heartbeat is a POST whose body is a JSON object of health figures, signed with HMAC-SHA256 under
a token unique to the firm. Everything here refuses by default:

- a key that is not listed in FIGURES is a rejection, not something to ignore, so a bug or a
  compromised agent cannot use this channel to carry audit data out;
- every text value must match a short closed pattern, so there is no free-text field to smuggle
  a client's name or a file's content through;
- the size is capped, and a timestamp must be recent and greater than the last one accepted.

The signing format is duplicated on purpose in ea_audit_firm_agent/services/signing.py: the firm's
release does not ship this addon. test_heartbeat.py checks that the two agree.
"""

import hashlib
import hmac
import json
import re
from datetime import date, datetime, timezone

SCHEMA_VERSION = 1
MAX_BODY_BYTES = 4096
MAX_CLOCK_SKEW_SECONDS = 300

HEADER_FIRM = "X-EA-Firm"
HEADER_TIMESTAMP = "X-EA-Timestamp"
HEADER_SIGNATURE = "X-EA-Signature"
HEADER_RESPONSE_SIGNATURE = "X-EA-Response-Signature"

_SLUG = re.compile(r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$")
_SIGNATURE = re.compile(r"^[0-9a-f]{64}$")
_RELEASE = re.compile(r"^[0-9a-f]{7,40}$")
_ODOO_VERSION = re.compile(r"^\d{2}\.\d$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ADDON_CODE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
MAX_ADDON_CODES = 24


class HeartbeatRejected(Exception):
    """`code` is short and safe to record; it never contains anything taken from the body."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _integer(low, high):
    def check(value):
        return type(value) is int and low <= value <= high
    return check


def _boolean(value):
    return type(value) is bool


def _pattern(regex, maximum=64):
    def check(value):
        return type(value) is str and len(value) <= maximum and bool(regex.match(value))
    return check


def _choice(*choices):
    def check(value):
        return type(value) is str and value in choices
    return check


def _timestamp(value):
    """A UTC instant in seconds, written YYYY-MM-DDTHH:MM:SSZ, and nothing else."""
    if type(value) is not str or len(value) != 20:
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _day(value):
    if type(value) is not str or len(value) != 10:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _addon_codes(value):
    """A short list of technical names. A code outside the catalogue is counted, never stored."""
    return (
        type(value) is list and len(value) <= MAX_ADDON_CODES
        and all(type(code) is str and _ADDON_CODE.match(code) for code in value)
        and len(set(value)) == len(value)
    )


_ERROR_MODULE = re.compile(r"^([a-z][a-z0-9_]{1,63}|-)$")
_ERROR_MODEL = re.compile(r"^([a-z][a-z0-9_]*(\.[a-z0-9_]+){0,6}|-)$")
_ERROR_KIND = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MAX_ERROR_GROUPS = 8
VISIT_STATES = ("open", "ended", "expired")


def _errors(value):
    """Technical errors as codes: addon, model, exception class, count, last time. No message."""
    if type(value) is not list or len(value) > MAX_ERROR_GROUPS:
        return False
    for item in value:
        if type(item) is not dict or set(item) != {"module", "model", "kind", "count", "last_at"}:
            return False
        if not (_pattern(_ERROR_MODULE, 64)(item["module"]) and _pattern(_ERROR_MODEL, 80)(item["model"])
                and _pattern(_ERROR_KIND, 64)(item["kind"]) and _integer(1, 100000)(item["count"])
                and _timestamp(item["last_at"])):
            return False
    return True


def _support_visit(value):
    return (
        type(value) is dict and set(value) == {"id", "state"} and _integer(1, 10 ** 9 - 1)(value["id"])
        and type(value["state"]) is str and value["state"] in VISIT_STATES
    )


def _optional(check):
    def inner(value):
        return value is None or check(value)
    return inner


UPDATE_STATES = ("idle", "updating", "ok", "failed", "rolled_back")
EXPORT_STATES = ("none", "running", "done", "failed")
ANON_EXPORT_STATES = ("running", "done", "failed", "refused")
_ANON_REF = re.compile(r"^[0-9a-f]{16}$")
_MAIL_REF = re.compile(r"^[0-9a-f]{16}$")
# Same words as ea_audit_firm_agent/services/collect.py MAIL_RESULTS and services/mail_settings.py RESULTS.
MAIL_RESULTS = ("on", "off", "login", "connect", "tls", "sender", "staging", "refused", "failed")
# The answer to "Add / Replace the firm administrator": the request's reference, one word and, for a new
# account, its one-time invitation link. Same rules as services/admin_change.py.
_ADMIN_REF = re.compile(r"^[0-9a-f]{16}$")
ADMIN_RESULTS = ("done", "email", "domain", "account", "unavailable", "failed")
# Document reading: on (the key works), refused (the service refuses it), unreachable, removed, unavailable
# (the firm's server cannot read documents yet) or failed. Same list as ea_audit_firm_agent/services/collect.py.
_DOC_READING_REF = re.compile(r"^[0-9a-f]{16}$")
_DOC_READING_LAST4 = re.compile(r"^[A-Za-z0-9_-]{4}$")
_DOC_READING_MONTH = re.compile(r"^\d{4}-\d{2}$")
DOC_READING_RESULTS = ("on", "refused", "unreachable", "removed", "unavailable", "failed")
_ADMIN_LINK = re.compile(r"^https://[a-z0-9.-]{3,253}(:[0-9]{2,5})?/web/signup\?[A-Za-z0-9._~%&=+-]{1,1000}$")

# The complete list of what a firm may tell the control plane.
FIGURES = {
    "schema": lambda value: value == SCHEMA_VERSION and type(value) is int,
    "odoo_version": _pattern(_ODOO_VERSION, 8),
    "release": _pattern(_RELEASE, 40),
    "disk_total_gb": _integer(0, 100000),
    "disk_used_pct": _integer(0, 100),
    "mem_total_mb": _integer(0, 10000000),
    "mem_available_mb": _integer(0, 10000000),
    "users_active": _integer(0, 1000000),
    "engagements_active": _integer(0, 10000000),
    "last_backup_at": _optional(_timestamp),
    "last_backup_ok": _optional(_boolean),
    "last_restore_test_at": _optional(_timestamp),
    "last_restore_test_ok": _optional(_boolean),
    "cert_expires_on": _optional(_day),
    "mail_enabled": _boolean,
    "update_state": _choice(*UPDATE_STATES),
    "update_release": _optional(_pattern(_RELEASE, 40)),
    "export_state": _choice(*EXPORT_STATES),
    "export_at": _optional(_timestamp),
    "export_sha256": _optional(_pattern(_SHA256, 64)),
    # An anonymised copy made for staging: it stays at the firm. See ea_platform_pipeline.
    "anon_export_state": _optional(_choice(*ANON_EXPORT_STATES)),
    "anon_export_ref": _optional(_pattern(_ANON_REF, 16)),
    "anon_export_at": _optional(_timestamp),
    "anon_export_sha256": _optional(_pattern(_SHA256, 64)),
    "ssh_sessions_24h": _integer(0, 1000000),
    "last_ssh_at": _optional(_timestamp),
    "addons_on": _addon_codes,
    "addons_refused": _integer(0, 1000),
    # Sent by firm servers set up before 2026-11-10 (the list of release signers, since removed).
    # Still accepted, so that such a server keeps reporting; nothing reads it.
    "signers_serial": _optional(_integer(0, 1000000)),
    "errors": _errors,
    "support_visit": _support_visit,
    # The answer to the console's "Email for this firm" screen: the request's reference and one word.
    "mail_request_ref": _optional(_pattern(_MAIL_REF, 16)),
    "mail_request_result": _optional(_choice(*MAIL_RESULTS)),
    "admin_request_ref": _optional(_pattern(_ADMIN_REF, 16)),
    "admin_request_result": _optional(_choice(*ADMIN_RESULTS)),
    "admin_request_link": _optional(_pattern(_ADMIN_LINK, 1300)),
    # The answer to the console's "Document reading" tab (Opening Balance Testing, 2026-11-20): the request's
    # reference and one word, the key's last four characters, and this month's use. Absent until a first request.
    "doc_reading_ref": _optional(_pattern(_DOC_READING_REF, 16)),
    "doc_reading_result": _optional(_choice(*DOC_READING_RESULTS)),
    "doc_reading_last4": _optional(_pattern(_DOC_READING_LAST4, 4)),
    "doc_reading_month": _optional(_pattern(_DOC_READING_MONTH, 7)),
    "doc_reading_documents": _optional(_integer(0, 10000000)),
    "doc_reading_pages": _optional(_integer(0, 100000000)),
}

REQUIRED = frozenset({
    "schema", "release", "disk_used_pct", "mem_total_mb", "mem_available_mb",
    "users_active", "engagements_active", "update_state", "export_state", "mail_enabled",
})


def message_to_sign(slug, timestamp, body):
    return b"\n".join([
        b"ea-heartbeat-v1",
        slug.encode("ascii"),
        str(timestamp).encode("ascii"),
        hashlib.sha256(body).hexdigest().encode("ascii"),
    ])


def sign(token, slug, timestamp, body):
    return hmac.new(token.encode("utf-8"), message_to_sign(slug, timestamp, body), hashlib.sha256).hexdigest()


def response_message(slug, timestamp, body):
    return b"\n".join([
        b"ea-heartbeat-response-v1",
        slug.encode("ascii"),
        str(timestamp).encode("ascii"),
        hashlib.sha256(body).hexdigest().encode("ascii"),
    ])


def sign_response(token, slug, timestamp, body):
    return hmac.new(token.encode("utf-8"), response_message(slug, timestamp, body), hashlib.sha256).hexdigest()


def sign_kind(prefix, token, slug, timestamp, body):
    """The support channel's signature: its own prefix, so no other message can pass for it."""
    message = b"\n".join([prefix, slug.encode("ascii"), str(timestamp).encode("ascii"), hashlib.sha256(body).hexdigest().encode("ascii")])
    return hmac.new(token.encode("utf-8"), message, hashlib.sha256).hexdigest()


def accept_kind(prefix, headers, body, find_firm, now_seconds, max_bytes):
    """As `accept`, for the support channel. Returns (slug, timestamp); the caller parses the body."""
    slug, timestamp, signature = parse_headers(headers)
    if len(body) > max_bytes:
        raise HeartbeatRejected("body_too_large")
    found = find_firm(slug)
    if not found or not found[0]:
        raise HeartbeatRejected("unknown_firm")
    token, last_timestamp = found
    if not hmac.compare_digest(sign_kind(prefix, token, slug, timestamp, body), signature):
        raise HeartbeatRejected("bad_signature")
    check_freshness(timestamp, last_timestamp, now_seconds)
    return slug, timestamp


def parse_headers(headers):
    """(slug, timestamp, signature), or a rejection. Nothing is looked up yet."""
    slug = headers.get(HEADER_FIRM) or ""
    raw_timestamp = headers.get(HEADER_TIMESTAMP) or ""
    signature = headers.get(HEADER_SIGNATURE) or ""
    if not _SLUG.match(slug):
        raise HeartbeatRejected("bad_firm_header")
    if not raw_timestamp.isascii() or not raw_timestamp.isdigit() or len(raw_timestamp) > 12:
        raise HeartbeatRejected("bad_timestamp_header")
    if not _SIGNATURE.match(signature):
        raise HeartbeatRejected("bad_signature_header")
    return slug, int(raw_timestamp), signature


def check_signature(token, slug, timestamp, body, signature):
    if not hmac.compare_digest(sign(token, slug, timestamp, body), signature):
        raise HeartbeatRejected("bad_signature")


def check_freshness(timestamp, last_timestamp, now_seconds):
    if abs(now_seconds - timestamp) > MAX_CLOCK_SKEW_SECONDS:
        raise HeartbeatRejected("stale_timestamp")
    if last_timestamp and timestamp <= last_timestamp:
        raise HeartbeatRejected("replayed_timestamp")


def _refuse_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise HeartbeatRejected("duplicate_key")
        result[key] = value
    return result


def parse_figures(body):
    """The validated figures of a body, or a rejection. A key outside FIGURES rejects it all."""
    if len(body) > MAX_BODY_BYTES:
        raise HeartbeatRejected("body_too_large")
    try:
        data = json.loads(body.decode("utf-8"), object_pairs_hook=_refuse_duplicates)
    except (UnicodeDecodeError, ValueError):
        raise HeartbeatRejected("not_json") from None
    if not isinstance(data, dict):
        raise HeartbeatRejected("not_an_object")
    if set(data) - set(FIGURES):
        raise HeartbeatRejected("unknown_key")
    if REQUIRED - set(data):
        raise HeartbeatRejected("missing_key")
    for key, value in data.items():
        if not FIGURES[key](value):
            raise HeartbeatRejected("bad_value")
    return data


def accept(headers, body, find_firm, now_seconds):
    """Runs the whole check. `find_firm(slug)` returns (token, last_timestamp), or None.

    Order matters: the signature is checked before the body is parsed, so an unauthenticated
    caller cannot learn anything about what the schema accepts.
    Returns (slug, timestamp, figures).
    """
    slug, timestamp, signature = parse_headers(headers)
    if len(body) > MAX_BODY_BYTES:
        raise HeartbeatRejected("body_too_large")
    found = find_firm(slug)
    if not found or not found[0]:
        raise HeartbeatRejected("unknown_firm")
    token, last_timestamp = found
    check_signature(token, slug, timestamp, body, signature)
    check_freshness(timestamp, last_timestamp, now_seconds)
    return slug, timestamp, parse_figures(body)


def parse_instant(value):
    """A naive UTC datetime, as Odoo stores it, from a validated timestamp."""
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")


def format_instant(value):
    return value.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
