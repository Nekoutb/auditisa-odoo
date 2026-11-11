#!/usr/bin/python3 -I
"""practice-heartbeat: figures of the practice computer and of each space, for the control room.

Runs as root every minute (a timer), and at each step of an update. Figures only, from PostgreSQL
and root's own files: the release, the template's release, the guard's verdict, how far an update
has gone (closed words only), and per space its state, last reset, number of active internal users
and the DAY of the last login. No name, no login, no record of a space leaves this computer. The figures are always written to status/heartbeat.json; they are sent only
when PRACTICE_HEARTBEAT_URL (https) and secrets/heartbeat.token both exist.

The signature is the firms' heartbeat format (HMAC-SHA256 under a token known to this computer and
the control room) with its own prefix, so a firm's heartbeat can never pass for this one. An answer
is kept only if the control room signed it; it goes to a root-only spool file and nothing here acts
on it.

Standard library only: this runs with the system's python3, outside Odoo.
"""

import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

SCHEMA_VERSION = 1
PREFIX = b"ea-practice-heartbeat-v1"
RESPONSE_PREFIX = b"ea-practice-heartbeat-response-v1"
HEADER_COMPUTER = "X-EA-Practice"
HEADER_TIMESTAMP = "X-EA-Timestamp"
HEADER_SIGNATURE = "X-EA-Signature"
HEADER_RESPONSE_SIGNATURE = "X-EA-Response-Signature"
MAX_ANSWER_BYTES = 65536

_SLUG = re.compile(r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$")
_RELEASE = re.compile(r"^[0-9a-f]{7,40}$")
_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NAME = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
_ADDON = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
# The steps of an update and the reasons it can fail: the same closed lists as practice-lib.sh and
# the control room's (addons/ea_platform_admin/services/practice.py).
PROGRESS_CODES = ("download", "copy", "space", "start", "template", "done")
PROGRESS_REASONS = ("download", "digest", "bundle", "busy", "leftover", "copy", "space_update", "no_answer", "template", "other")


# ---------------------------------------------------------------------------- pure


def _message(prefix, computer, timestamp, body):
    return b"\n".join([
        prefix,
        computer.encode("ascii"),
        str(timestamp).encode("ascii"),
        hashlib.sha256(body).hexdigest().encode("ascii"),
    ])


def sign(token, computer, timestamp, body):
    return hmac.new(token.encode("utf-8"), _message(PREFIX, computer, timestamp, body), hashlib.sha256).hexdigest()


def response_is_authentic(token, computer, timestamp, body, signature):
    expected = hmac.new(token.encode("utf-8"), _message(RESPONSE_PREFIX, computer, timestamp, body), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def encode(figures):
    return json.dumps(figures, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _clean(value, pattern):
    return value if isinstance(value, str) and pattern.match(value) else None


def space_figures(slug, exists, reset_at, users, last_login_on, generation=0, addons=(), link_set=False):
    """One space, every value checked against a closed pattern: a figure or nothing.

    `generation` is the number of the last reset the control room asked for and this computer did;
    `addons` the optional add-ons on (technical names of the release, nothing typed by anyone);
    `link_set` whether the first administrator's one-time link the control room sent is in place.
    """
    if not _SLUG.match(slug or ""):
        raise ValueError("bad slug")
    return {
        "slug": slug,
        "state": "ready" if exists else "missing",
        "last_reset_at": _clean(reset_at, _INSTANT),
        "users": users if type(users) is int and 0 <= users < 100000 else None,
        "last_login_on": _clean(last_login_on, _DAY),
        "reset_generation": generation if type(generation) is int and 0 <= generation < 10 ** 9 else 0,
        "addons_on": sorted({code for code in addons if isinstance(code, str) and _ADDON.match(code)}),
        "link_set": link_set is True,
    }


def progress_figures(record):
    """status/progress as practice-update wrote it (KEY='value'), every value checked: figures or None."""
    target = _clean(record.get("TARGET"), _RELEASE)
    step, total = record.get("STEP", ""), record.get("TOTAL", "")
    code = record.get("CODE")
    at = _clean(record.get("AT"), _INSTANT)
    if not (target and at and code in PROGRESS_CODES and step.isascii() and step.isdigit() and total.isascii()
            and total.isdigit() and len(step) <= 3 and len(total) <= 3 and 1 <= int(total) and int(step) <= int(total)):
        return None
    failed = record.get("FAILED") == "1"
    reason = record.get("REASON") or None
    if failed and reason not in PROGRESS_REASONS:
        reason = "other"
    return {
        "target": target, "step": int(step), "total": int(total), "code": code,
        "slug": _clean(record.get("SLUG"), _SLUG), "failed": failed, "reason": reason if failed else None, "at": at,
    }


def build_figures(computer, release, template_release, guard, spaces, progress=None):
    if not _NAME.match(computer or ""):
        raise ValueError("bad computer name")
    figures = {
        "schema": SCHEMA_VERSION,
        "computer": computer,
        "release": _clean(release, _RELEASE),
        "template_release": _clean(template_release, _RELEASE),
        "guard": guard if guard in ("ok", "refused") else "unknown",
        "spaces": sorted(spaces, key=lambda s: s["slug"]),
    }
    # Only when an update has reported: a computer that never updated sends what it always sent.
    if progress:
        figures["progress"] = progress
    return figures


def parse_env(text):
    """KEY='value' lines, as the practice scripts write them."""
    out = {}
    for line in text.splitlines():
        match = re.match(r"^([A-Z0-9_]+)='([^']*)'$", line)
        if match:
            out[match.group(1)] = match.group(2)
    return out


# ---------------------------------------------------------------------------- the computer

ETC = "/etc/auditisa-practice"
VAR = "/var/lib/auditisa-practice"


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def _psql(sql, database="postgres"):
    # During an update a space's tables can be locked for a while: the figure is then left out and the
    # heartbeat is not held up (it also carries the update's progress).
    try:
        result = subprocess.run(
            ["runuser", "-u", "postgres", "--", "env", "PGOPTIONS=-c lock_timeout=3s -c statement_timeout=15s",
             "psql", "-X", "-At", "-d", database, "-c", sql],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except subprocess.TimeoutExpired:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def collect():
    env = parse_env(_read(os.path.join(ETC, "practice.env")))
    template = parse_env(_read(os.path.join(VAR, "template.env")))
    guard = (_read(os.path.join(VAR, "status", "guard")).split() or ["unknown"])[0]
    spaces = []
    folder = os.path.join(VAR, "spaces")
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        slug = name[:-4] if name.endswith(".env") else ""
        if not _SLUG.match(slug):
            continue
        record = parse_env(_read(os.path.join(folder, name)))
        database = "practice_" + slug
        exists = _psql("SELECT 1 FROM pg_database WHERE datname = '%s' AND datallowconn" % database) == "1"
        users = last = None
        if exists:
            count = _psql("SELECT count(*) FROM res_users WHERE active AND NOT share AND login <> '__system__'", database)
            users = int(count) if count and count.isdigit() else None
            last = _psql("SELECT to_char(max(create_date), 'YYYY-MM-DD') FROM res_users_log", database) or None
        generation = record.get("RESET_GEN", "0")
        spaces.append(space_figures(
            slug, exists, record.get("RESET_AT"), users, last,
            int(generation) if generation.isdigit() else 0,
            [code for code in record.get("ADDONS", "").split(",") if code],
            bool(re.match(r"^[0-9a-f]{64}$", record.get("FIRST_ADMIN_HASH", ""))),
        ))
    release = (_read(os.path.join(VAR, "status", "release")).split() or [""])[0]
    progress = progress_figures(parse_env(_read(os.path.join(VAR, "status", "progress"))))
    return env, build_figures(env.get("PRACTICE_NAME", ""), release, template.get("RELEASE"), guard, spaces, progress)


def _write_atomic(path, data, mode):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=folder, prefix=".hb-")
    with os.fdopen(handle, "wb") as out:
        out.write(data)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def send(url, computer, token, figures):
    body = encode(figures)
    timestamp = int(time.time())
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        HEADER_COMPUTER: computer,
        HEADER_TIMESTAMP: str(timestamp),
        HEADER_SIGNATURE: sign(token, computer, timestamp, body),
    })
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - https only, checked by main
        answer = response.read(MAX_ANSWER_BYTES + 1)
        signature = response.headers.get(HEADER_RESPONSE_SIGNATURE)
    if len(answer) > MAX_ANSWER_BYTES or not response_is_authentic(token, computer, timestamp, answer, signature):
        print("practice-heartbeat: answer ignored (unsigned or too large)", file=sys.stderr)
        return
    json.loads(answer)  # kept only if it is JSON; root's apply script checks every value again
    _write_atomic(os.path.join(VAR, "spool", "desired.json"), answer, 0o600)


def main():
    env, figures = collect()
    _write_atomic(os.path.join(VAR, "status", "heartbeat.json"), encode(figures), 0o644)
    url = env.get("PRACTICE_HEARTBEAT_URL", "")
    token = _read(os.path.join(ETC, "secrets", "heartbeat.token")).strip()
    if not (url and token):
        return 0
    if not url.startswith("https://"):
        print("practice-heartbeat: refused, the address is not https", file=sys.stderr)
        return 1
    try:
        try:
            send(url, figures["computer"], token, figures)
        except urllib.error.HTTPError as error:
            if error.code != 403 or "progress" not in figures:
                raise
            # A control room from before the progress report refuses a figure it does not know: the
            # same heartbeat again without it, so this computer stays known during the transition.
            send(url, figures["computer"], token, {key: value for key, value in figures.items() if key != "progress"})
    except (OSError, ValueError) as error:
        print("practice-heartbeat: not delivered (%s)" % type(error).__name__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
