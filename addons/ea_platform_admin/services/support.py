"""What a firm's support channel may carry. Pure.

Two kinds of signed POST, apart from the heartbeat: a problem a user chose to report, and a request
for the states and replies of the problems already reported. The heartbeat's rule (codes and
figures, no free text) is unchanged; this channel carries the text a user typed, after a warning on
the form not to write client details, and nothing else.
"""

import json
import re

from .heartbeat import HeartbeatRejected

PREFIX_TICKET = b"ea-support-ticket-v1"
PREFIX_SYNC = b"ea-support-sync-v1"
MAX_BODY_BYTES = 16384
MAX_SUBJECT = 200
MAX_MESSAGE = 4000
MAX_REFS = 50
_REF = re.compile(r"^[0-9a-f]{32}$")
_SCREEN = re.compile(r"^([a-z][a-z0-9_.]{0,79})?$")


def _load(body, keys):
    if len(body) > MAX_BODY_BYTES:
        raise HeartbeatRejected("body_too_large")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise HeartbeatRejected("not_json") from None
    if not isinstance(data, dict) or set(data) != keys:
        raise HeartbeatRejected("unknown_key")
    return data


def parse_ticket(body):
    data = _load(body, {"ref", "subject", "message", "screen"})
    if not (isinstance(data["ref"], str) and _REF.match(data["ref"])):
        raise HeartbeatRejected("bad_value")
    for key, limit in (("subject", MAX_SUBJECT), ("message", MAX_MESSAGE)):
        if not isinstance(data[key], str) or not data[key].strip() or len(data[key]) > limit:
            raise HeartbeatRejected("bad_value")
    if not (isinstance(data["screen"], str) and _SCREEN.match(data["screen"])):
        raise HeartbeatRejected("bad_value")
    return data


def parse_sync(body):
    data = _load(body, {"refs"})
    refs = data["refs"]
    if not (isinstance(refs, list) and len(refs) <= MAX_REFS and all(isinstance(r, str) and _REF.match(r) for r in refs)):
        raise HeartbeatRejected("bad_value")
    return sorted(set(refs))
