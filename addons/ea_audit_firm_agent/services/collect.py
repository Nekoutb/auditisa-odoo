"""Gathers the heartbeat's figures and reads what root's scripts left for the agent. Pure.

The root-run scripts of deploy/firm write one small file per figure in the status folder. Only the
names below are read, and each is checked again, so a stray file cannot add to a heartbeat.
"""

import json
import os
import re
import shutil

from .recipients import valid_reply_to

_INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_RELEASE = re.compile(r"^[0-9a-f]{7,40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ODOO_VERSION = re.compile(r"^\d{2}\.\d$")
_CIDR = re.compile(r"^[0-9a-fA-F:.]+/\d{1,3}$")
_ANON_REF = re.compile(r"^[0-9a-f]{16}$")
_ADDON_CODE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
_OPERATOR = re.compile(r"^[\w .'-]{1,64}$")
# A signed download address of a release file: https, a host name, a path and a query of the
# characters SigV4 uses. Root checks it again; the release's signature still decides.
_RELEASE_URL = re.compile(r"^https://[a-z0-9.-]{3,253}(:[0-9]{2,5})?/[A-Za-z0-9._~%/-]{1,512}(\?[A-Za-z0-9._~%&=-]{1,1500})?$")
MAX_ADDON_CODES = 24
# What the console's "Email for this firm" screen may ask. Root's firm_mail.py checks the settings again.
_MAIL_REF = re.compile(r"^[0-9a-f]{16}$")
MAIL_RESULTS = ("on", "off", "login", "connect", "tls", "sender", "staging", "refused", "failed")
_MAIL_SET_KEYS = frozenset({"ref", "action", "host", "port", "encryption", "user", "password", "from"})
_MAIL_TEXT_LIMITS = {"host": 253, "encryption": 8, "user": 254, "password": 512, "from": 320}


def _text(pattern):
    def read(value):
        return value if pattern.match(value) else None
    return read


def _flag(value):
    return {"1": True, "0": False}.get(value)


def _count(value):
    return int(value) if value.isdigit() else None


def _word(*allowed):
    def read(value):
        return value if value in allowed else None
    return read


STATUS_FILES = {
    "odoo_version": _text(_ODOO_VERSION),
    "release": _text(_RELEASE),
    "last_backup_at": _text(_INSTANT),
    "last_backup_ok": _flag,
    "last_restore_test_at": _text(_INSTANT),
    "last_restore_test_ok": _flag,
    "cert_expires_on": _text(_DAY),
    "update_state": _word("idle", "updating", "ok", "failed", "rolled_back"),
    "update_release": _text(_RELEASE),
    "export_state": _word("none", "running", "done", "failed"),
    "export_at": _text(_INSTANT),
    "export_sha256": _text(_SHA256),
    # Absent until this firm is first asked for an anonymised copy, so an older control plane, which
    # refuses a figure it does not know, keeps working.
    "anon_export_state": _word("running", "done", "failed", "refused"),
    "anon_export_ref": _text(_ANON_REF),
    "anon_export_at": _text(_INSTANT),
    "anon_export_sha256": _text(_SHA256),
    "ssh_sessions_24h": _count,
    "last_ssh_at": _text(_INSTANT),
    "addons_refused": _count,
    # Absent until the console first sends this firm its email settings: an older console, which
    # refuses a figure it does not know, keeps working.
    "mail_request_ref": _text(_MAIL_REF),
    "mail_request_result": _word(*MAIL_RESULTS),
}

DEFAULTS = {
    "update_state": "idle", "export_state": "none", "ssh_sessions_24h": 0, "odoo_version": "19.0", "addons_refused": 0,
}


def read_status(folder):
    """Whatever valid figures the folder holds. A missing or malformed one is simply absent."""
    figures = {}
    for name, reader in STATUS_FILES.items():
        try:
            with open(os.path.join(folder, name), encoding="ascii") as handle:
                raw = handle.read(128).strip()
        except (OSError, UnicodeDecodeError):
            continue
        value = reader(raw)
        if value is not None:
            figures[name] = value
    return figures


def memory_figures(path="/proc/meminfo"):
    total = available = 0
    try:
        with open(path, encoding="ascii") as handle:
            for line in handle:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) // 1024
                elif line.startswith("MemAvailable:"):
                    available = int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return {"mem_total_mb": total, "mem_available_mb": available}


def disk_figures(path="/"):
    usage = shutil.disk_usage(path)
    return {
        "disk_total_gb": usage.total // (1024 ** 3),
        "disk_used_pct": min(100, usage.used * 100 // usage.total) if usage.total else 0,
    }


def build_figures(status, memory, disk, users_active, engagements_active, mail_enabled, addons_on=(),
                  errors=None, support_visit=None):
    """The whole body. `release` is left out if unknown, which the receiver rejects, on purpose.

    `addons_on` holds technical names and nothing else. Past the cap they are not sent at all, since
    the receiver would refuse the whole heartbeat.
    """
    figures = {"schema": 1}
    figures.update(DEFAULTS)
    figures.update(status)
    figures.update(memory)
    figures.update(disk)
    figures.update({
        "users_active": users_active,
        "engagements_active": engagements_active,
        "mail_enabled": bool(mail_enabled),
    })
    codes = sorted(code for code in set(addons_on) if _ADDON_CODE.match(code))
    if len(codes) <= MAX_ADDON_CODES:
        figures["addons_on"] = codes
    if errors is not None:
        figures["errors"] = errors
    if support_visit is not None:
        figures["support_visit"] = support_visit
    return figures


def mail_request(data):
    """The console's email request, or None. A password travels this way, once, and only here."""
    if not isinstance(data, dict) or not isinstance(data.get("ref"), str) or not _MAIL_REF.match(data["ref"]):
        return None
    if data.get("action") == "off":
        return {"ref": data["ref"], "action": "off"} if set(data) == {"ref", "action"} else None
    if data.get("action") != "set" or set(data) != _MAIL_SET_KEYS or type(data["port"]) is not int:
        return None
    for key, limit in _MAIL_TEXT_LIMITS.items():
        value = data[key]
        if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
            return None
    return dict(data)


def parse_desired(body):
    """What the control plane asks, validated. Unknown keys are dropped.

    Only names and addresses come this way, never code: the release it names must still carry a
    signature made outside the control plane (firm-update.sh checks it).
    """
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    desired = {}
    release = data.get("desired_release")
    digest = data.get("desired_bundle_sha256")
    if isinstance(release, str) and _RELEASE.match(release) and isinstance(digest, str) and _SHA256.match(digest):
        desired["release"] = release
        desired["bundle_sha256"] = digest
        # Where to download the bundle. firm-update installs it only if its SHA-256 is `digest` above.
        bundle_url = data.get("desired_bundle_url")
        if isinstance(bundle_url, str) and _RELEASE_URL.match(bundle_url):
            desired["bundle_url"] = bundle_url
    desired["export_requested"] = data.get("export_requested") is True
    anon_ref = data.get("anon_export_ref")
    if isinstance(anon_ref, str) and _ANON_REF.match(anon_ref):
        desired["anon_export_ref"] = anon_ref
    allowlist = data.get("ssh_allowlist")
    if isinstance(allowlist, list) and all(isinstance(c, str) and _CIDR.match(c) for c in allowlist):
        desired["ssh_allowlist"] = allowlist
    # Absent means no request. Root's firm-addons checks the codes against the release in use.
    addons = data.get("desired_addons")
    if (
        isinstance(addons, list) and len(addons) <= MAX_ADDON_CODES
        and all(isinstance(code, str) and _ADDON_CODE.match(code) for code in addons)
    ):
        desired["addons"] = sorted(set(addons))
    visit = data.get("support_visit")
    if (
        isinstance(visit, dict) and set(visit) == {"id", "minutes", "token_sha256", "operator", "reason"}
        and type(visit["id"]) is int and 0 < visit["id"] < 10 ** 9
        and type(visit["minutes"]) is int and 1 <= visit["minutes"] <= 240
        and isinstance(visit["token_sha256"], str) and _SHA256.match(visit["token_sha256"])
        and isinstance(visit["operator"], str) and _OPERATOR.match(visit["operator"])
        and isinstance(visit["reason"], str) and 0 < len(visit["reason"]) <= 500
    ):
        desired["support_visit"] = visit
    ended = data.get("support_visit_end")
    if type(ended) is int and 0 < ended < 10 ** 9:
        desired["support_visit_end"] = ended
    mail = mail_request(data.get("mail_request"))
    if mail is not None:
        desired["mail_request"] = mail
    # The platform email address's reply address (the firm's contact email), or "" for none. The agent
    # keeps it as a setting of its own; it never reaches root's spool.
    reply_to = data.get("mail_reply_to")
    if valid_reply_to(reply_to):
        desired["mail_reply_to"] = reply_to
    return desired
