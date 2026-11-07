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
PREFIX_TRACE = b"ea-support-trace-v1"
MAX_TRACE_ENTRIES = 200
_MODEL = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+){0,6}$")
_RELEASE = re.compile(r"^([0-9a-f]{7,40})?$")
_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
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


def parse_trace(body):
    """A visit's trail: which screens and records were opened. Identifiers only, never content."""
    data = _load(body, {"visit", "release", "entries"})
    visit, release, entries = data["visit"], data["release"], data["entries"]
    if not (type(visit) is int and 0 < visit < 10 ** 9 and isinstance(release, str) and _RELEASE.match(release)):
        raise HeartbeatRejected("bad_value")
    if not (isinstance(entries, list) and 0 < len(entries) <= MAX_TRACE_ENTRIES):
        raise HeartbeatRejected("bad_value")
    for entry in entries:
        if not (isinstance(entry, dict) and set(entry) == {"at", "model", "method", "ids"}
                and isinstance(entry["at"], str) and _INSTANT.match(entry["at"])
                and isinstance(entry["model"], str) and _MODEL.match(entry["model"]) and len(entry["model"]) <= 80
                and entry["method"] in ("form", "list")
                and isinstance(entry["ids"], list) and len(entry["ids"]) <= 20
                and all(type(i) is int and 0 < i < 2 ** 31 for i in entry["ids"])):
            raise HeartbeatRejected("bad_value")
    return data


def parse_sync(body):
    data = _load(body, {"refs"})
    refs = data["refs"]
    if not (isinstance(refs, list) and len(refs) <= MAX_REFS and all(isinstance(r, str) and _REF.match(r) for r in refs)):
        raise HeartbeatRejected("bad_value")
    return sorted(set(refs))
