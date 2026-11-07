"""The signature of a heartbeat and of its answer. Pure.

Same format as ea_platform_admin/services/heartbeat.py, which a firm's release does not ship.
A test in that addon checks that the two agree.
"""

import hashlib
import hmac
import json

HEADER_FIRM = "X-EA-Firm"
HEADER_TIMESTAMP = "X-EA-Timestamp"
HEADER_SIGNATURE = "X-EA-Signature"
HEADER_RESPONSE_SIGNATURE = "X-EA-Response-Signature"


def _message(prefix, slug, timestamp, body):
    return b"\n".join([
        prefix,
        slug.encode("ascii"),
        str(timestamp).encode("ascii"),
        hashlib.sha256(body).hexdigest().encode("ascii"),
    ])


def sign(token, slug, timestamp, body):
    message = _message(b"ea-heartbeat-v1", slug, timestamp, body)
    return hmac.new(token.encode("utf-8"), message, hashlib.sha256).hexdigest()


def response_is_authentic(token, slug, timestamp, body, signature):
    message = _message(b"ea-heartbeat-response-v1", slug, timestamp, body)
    expected = hmac.new(token.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


# The support channel: a deliberate message from a user, and its replies. Its own prefixes, so a
# signature made for one kind of message never passes for another.
PREFIX_TICKET = b"ea-support-ticket-v1"
PREFIX_SYNC = b"ea-support-sync-v1"
PREFIX_TRACE = b"ea-support-trace-v1"


def sign_kind(prefix, token, slug, timestamp, body):
    return hmac.new(token.encode("utf-8"), _message(prefix, slug, timestamp, body), hashlib.sha256).hexdigest()


def response_is_authentic_kind(prefix, token, slug, timestamp, body, signature):
    expected = hmac.new(token.encode("utf-8"), _message(prefix + b"-response", slug, timestamp, body), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def encode(figures):
    return json.dumps(figures, sort_keys=True, separators=(",", ":")).encode("utf-8")
