"""Reads what deploy/control-plane/pipeline-collect.py wrote, and keeps only what passes. Pure.

The file is written by root on this server, but it carries text that came from GitHub and from three web
sites. So nothing is trusted: each value goes through a closed pattern or is dropped, and the screen escapes
what is left. A firm's name cannot be in it: the collector reads no firm.
"""

import json
import re
from datetime import datetime, timedelta

from .environments import commit_log

SHA = re.compile(r"^[0-9a-f]{7,40}$")
INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
AUTHOR = re.compile(r"^[^\x00-\x1f<>]{1,40}$")
SIZE = re.compile(r"^[0-9]{1,6}(\.[0-9])? (B|KB|MB|GB)$")
GITHUB_STATES = ("ok", "no_key", "unreachable")
FRESH = timedelta(minutes=3)
MAX_BYTES = 262144


def _sha(value):
    return value if isinstance(value, str) and SHA.match(value) else None


def _instant(value):
    return value if isinstance(value, str) and INSTANT.match(value) else None


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 1000000 else None


def _commit(value):
    if not isinstance(value, dict) or not _sha(value.get("sha")):
        return None
    author = value.get("author")
    return {
        "sha": value["sha"],
        "author": author if isinstance(author, str) and AUTHOR.match(author) else None,
        "at": _instant(value.get("at")),
    }


def _site(value):
    if not isinstance(value, dict):
        return None
    return {
        "up": value.get("up") is True,
        "started_at": _instant(value.get("started_at")),
        "mail_off": value.get("mail_off") is True if "mail_off" in value else None,
        "band_on": value.get("band_on") is True if "band_on" in value else None,
    }


def _figures(value):
    """Deploys, backups and migrations of one site of the current tool."""
    if not isinstance(value, dict):
        return None
    deploys = [
        {"sha": row["sha"], "at": row["at"]} for row in (value.get("deploys") or [])[:5]
        if isinstance(row, dict) and _sha(row.get("sha")) and _instant(row.get("at"))
    ]
    backups = [
        {"at": row["at"], "size": row.get("size") if isinstance(row.get("size"), str) and SIZE.match(row["size"]) else None}
        for row in (value.get("backups") or [])[:3] if isinstance(row, dict) and _instant(row.get("at"))
    ]
    return {"deploys": deploys, "backups": backups, "migrations": _count(value.get("migrations")), "pending": _count(value.get("pending"))}


def _tool(value, branches, stages, counts):
    value = value if isinstance(value, dict) else {}
    github = value.get("github") if value.get("github") in GITHUB_STATES else "unreachable"
    read = lambda key, names, check: {name: check((value.get(key) or {}).get(name)) for name in names}  # noqa: E731
    return {
        "github": github,
        "branches": read("branches", branches, _commit),
        "running": read("running", stages, _commit),
        "ahead": read("ahead", counts, _count),
        "sites": read("sites", stages, _site),
        "figures": read("figures", stages, _figures),
        "log": {name: commit_log(value["log"].get(name) if isinstance(value.get("log"), dict) else None) for name in branches},
    }


def read_state(raw, now):
    """The checked state, or None if the file is missing, too big or not what the collector writes.

    `now` is a naive UTC datetime. `stale` says the collector has not written for a while.
    """
    if not raw or len(raw) > MAX_BYTES:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != 1:
        return None
    generated = _instant(data.get("generated"))
    if not generated:
        return None
    when = datetime.strptime(generated[:19], "%Y-%m-%dT%H:%M:%S")
    return {
        "generated": when,
        "stale": now - when > FRESH,
        "sample": False,
        "next": _tool(data.get("next"), ("dev", "main"), ("staging", "production"),
                      ("development_over_staging", "staging_over_production", "main_over_production")),
        "odoo": _tool(data.get("odoo"), ("dev", "staging", "main"), ("staging",),
                      ("development_over_staging", "staging_over_main")),
    }
