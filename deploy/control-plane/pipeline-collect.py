#!/usr/bin/env python3
"""pipeline-collect.py: what the Pipeline screen shows about GitHub and the running tools. On the control plane.

    pipeline-collect.py [--out FILE]      reads once and writes the file (default /var/lib/auditisa-platform/pipeline-state.json)
    pipeline-collect.py --print           reads once and prints, writes nothing
    pipeline-collect.py --install         copies itself to /usr/local/sbin and adds a timer, every minute
    pipeline-collect.py --uninstall       removes the timer

Runs as root, outside Odoo, so that the admin Odoo keeps no network code and no key of any kind: it only
reads this file, and checks every value again. What it reads, all read-only:

  GitHub        `git ls-remote` of both repositories, every minute; commit details into blobless mirrors only
                when a branch has moved. The Odoo repository is private: a read-only deploy key, at
                /root/.ssh/auditisa_odoo_ro (see docs/runbook/PIPELINE.md). Without it the screen says so.
  Next.js tool  https://www.auditisa.com/api/version and https://dev.auditisa.com/api/version: public already,
                commit and dates only. Nothing to install on the production server.
  Odoo staging  https://test.auditisa.com/web/health, and the figures publish-staging-state.sh puts beside it.

The file holds commits, author names, dates, counts and yes-or-no answers. No commit message, no secret.
Standard library only.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone

OUT = os.environ.get("PIPELINE_STATE_FILE", "/var/lib/auditisa-platform/pipeline-state.json")
STATE = os.environ.get("PIPELINE_STATE_DIR", "/var/lib/auditisa-platform/pipeline-mirrors")
NEXT_REMOTE = os.environ.get("NEXT_REMOTE", "https://github.com/Nekoutb/ea-audit-tool.git")
ODOO_REMOTE = os.environ.get("ODOO_REMOTE", "git@github.com:Nekoutb/auditisa-odoo.git")
ODOO_KEY = os.environ.get("ODOO_DEPLOY_KEY", "/root/.ssh/auditisa_odoo_ro")
NEXT_PROD_URL = os.environ.get("NEXT_PROD_URL", "https://www.auditisa.com/api/version")
NEXT_DEV_URL = os.environ.get("NEXT_DEV_URL", "https://dev.auditisa.com/api/version")
STAGING_HEALTH_URL = os.environ.get("STAGING_HEALTH_URL", "https://test.auditisa.com/web/health")
STAGING_STATE_URL = os.environ.get("STAGING_STATE_URL", "https://test.auditisa.com/manual/staging-state.json")
TIMEOUT = 20

SHA = re.compile(r"^[0-9a-f]{7,40}$")
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
BRANCHES = ("dev", "staging", "main")


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def git(args, env=None, timeout=TIMEOUT):
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, timeout=timeout, check=True, env=env,
    ).stdout.strip()


def ssh_env(remote):
    if not remote.startswith("git@"):
        return None
    return {**os.environ, "GIT_SSH_COMMAND": f"ssh -i {ODOO_KEY} -o IdentitiesOnly=yes -o BatchMode=yes "
                                              "-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"}


def heads(remote):
    found = {}
    for line in git(["ls-remote", "--heads", remote], env=ssh_env(remote)).splitlines():
        match = re.match(r"^([0-9a-f]{40})\s+refs/heads/([A-Za-z0-9._/-]+)$", line)
        if match and match.group(2) in BRANCHES:
            found[match.group(2)] = match.group(1)
    return found


def mirror(name, remote, wanted):
    folder = os.path.join(STATE, f"{name}.git")
    if not os.path.isdir(folder):
        os.makedirs(STATE, exist_ok=True)
        git(["clone", "--quiet", "--bare", "--filter=blob:none", remote, folder], env=ssh_env(remote), timeout=180)
    if any(not has(folder, sha) for sha in wanted):
        git(["-C", folder, "fetch", "--quiet", "--prune", "--filter=blob:none", remote, "+refs/heads/*:refs/heads/*"],
            env=ssh_env(remote), timeout=120)
    return folder


def has(folder, sha):
    try:
        git(["-C", folder, "cat-file", "-e", f"{sha}^{{commit}}"])
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def full(folder, sha):
    """A short commit from a server, made full when the mirror knows it."""
    if not sha or not SHA.match(sha):
        return None
    if folder and has(folder, sha):
        return git(["-C", folder, "rev-parse", f"{sha}^{{commit}}"])
    return sha


def commit(folder, sha):
    if not sha:
        return None
    if not folder or not has(folder, sha):
        return {"sha": sha}
    author, at = git(["-C", folder, "log", "-1", "--format=%an%x00%cI", sha]).split("\0")
    when = datetime.fromisoformat(at).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"sha": sha, "author": author[:40], "at": when}


def ahead(folder, base, tip):
    """Commits in `tip` that `base` lacks."""
    if not folder or not base or not tip or not has(folder, base) or not has(folder, tip):
        return None
    return int(git(["-C", folder, "rev-list", "--count", f"{base}..{tip}"]))


def fetch(url):
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "auditisa-pipeline"})
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 fixed https addresses
            return response.status, response.read(4096)
    except Exception:  # noqa: BLE001 a site that does not answer is a state, not an error
        return None, b""


def version(url):
    status, body = fetch(url)
    if status != 200:
        return {"up": False}
    try:
        data = json.loads(body)
    except ValueError:
        return {"up": False}
    sha = data.get("sha") if isinstance(data, dict) else None
    started = data.get("startedAt") if isinstance(data, dict) else None
    return {
        "up": True,
        "sha": sha if isinstance(sha, str) and FULL_SHA.match(sha) else None,
        "started_at": started if isinstance(started, str) and INSTANT.match(started) else None,
    }


def staging():
    status, _body = fetch(STAGING_HEALTH_URL)
    result = {"up": status == 200}
    status, body = fetch(STAGING_STATE_URL)
    if status == 200:
        try:
            data = json.loads(body)
        except ValueError:
            data = {}
        if isinstance(data, dict):
            release = data.get("release")
            result["release"] = release if isinstance(release, str) and SHA.match(release) else None
            result["mail_off"] = data.get("mail_off") is True
            result["band_on"] = data.get("band_on") is True
    return result


def tool(name, remote, running):
    """Heads, their commits, and the counts between the stages. `running`: {stage: sha} known elsewhere."""
    out = {"github": "ok", "branches": {}, "running": {}, "ahead": {}}
    if remote.startswith("git@") and not os.path.exists(ODOO_KEY):
        out["github"] = "no_key"
        return out
    try:
        found = heads(remote)
        folder = mirror(name, remote, list(found.values()))
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        out["github"] = "unreachable"
        return out
    for branch, sha in found.items():
        out["branches"][branch] = commit(folder, sha)
    for stage, sha in running.items():
        sha = full(folder, sha)
        out["running"][stage] = commit(folder, sha)
    return out | {"_folder": folder}


def collect():
    prod, dev = version(NEXT_PROD_URL), version(NEXT_DEV_URL)
    stage = staging()
    next_tool = tool("next", NEXT_REMOTE, {"staging": dev.get("sha"), "production": prod.get("sha")})
    odoo_tool = tool("odoo", ODOO_REMOTE, {"staging": stage.get("release")})

    def counts(item, pairs):
        folder = item.pop("_folder", None)
        for label, base, tip in pairs:
            item["ahead"][label] = ahead(folder, base, tip)

    def sha_of(item, kind, key):
        entry = item[kind].get(key)
        return entry["sha"] if entry else None

    counts(next_tool, [
        ("development_over_staging", sha_of(next_tool, "running", "staging"), sha_of(next_tool, "branches", "dev")),
        ("staging_over_production", sha_of(next_tool, "running", "production"), sha_of(next_tool, "running", "staging")),
        ("main_over_production", sha_of(next_tool, "running", "production"), sha_of(next_tool, "branches", "main")),
    ])
    staging_tip = sha_of(odoo_tool, "running", "staging") or sha_of(odoo_tool, "branches", "staging") or sha_of(odoo_tool, "branches", "dev")
    counts(odoo_tool, [
        ("development_over_staging", staging_tip, sha_of(odoo_tool, "branches", "dev")),
        ("staging_over_main", sha_of(odoo_tool, "branches", "main"), staging_tip),
    ])
    return {
        "schema": 1,
        "generated": now(),
        "next": next_tool | {"sites": {"staging": {"up": dev["up"], "started_at": dev.get("started_at")},
                                        "production": {"up": prod["up"], "started_at": prod.get("started_at")}}},
        "odoo": odoo_tool | {"sites": {"staging": {k: v for k, v in stage.items() if k != "release"}}},
    }


UNIT = "auditisa-pipeline-collect"


def install():
    target = "/usr/local/sbin/pipeline-collect"
    with open(__file__, "rb") as source, open(target, "wb") as copy:
        copy.write(source.read())
    os.chmod(target, 0o755)
    with open(f"/etc/systemd/system/{UNIT}.service", "w", encoding="ascii") as unit:
        unit.write(f"[Unit]\nDescription=AuditISA: what the Pipeline screen shows\n[Service]\nType=oneshot\n"
                   f"ExecStart=/usr/bin/python3 -I {target}\nNice=10\nTimeoutStartSec=170\n")
    with open(f"/etc/systemd/system/{UNIT}.timer", "w", encoding="ascii") as unit:
        unit.write("[Unit]\nDescription=AuditISA: Pipeline readings each minute\n[Timer]\nOnBootSec=1min\n"
                   "OnUnitActiveSec=1min\nAccuracySec=5s\n[Install]\nWantedBy=timers.target\n")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", f"{UNIT}.timer"], check=True)


def uninstall():
    subprocess.run(["systemctl", "disable", "--now", f"{UNIT}.timer"], check=False)
    for path in (f"/etc/systemd/system/{UNIT}.service", f"/etc/systemd/system/{UNIT}.timer", "/usr/local/sbin/pipeline-collect"):
        if os.path.exists(path):
            os.unlink(path)
    subprocess.run(["systemctl", "daemon-reload"], check=False)


def write(data, path):
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=folder, prefix=".pipeline-state.")
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump(data, out, sort_keys=True, indent=1)
    os.chmod(temporary, 0o644)  # Odoo, which runs as another user, reads it.
    os.replace(temporary, path)


def main(argv):
    if "--install" in argv:
        install()
        return 0
    if "--uninstall" in argv:
        uninstall()
        return 0
    data = collect()
    if "--print" in argv:
        json.dump(data, sys.stdout, sort_keys=True, indent=1)
        return 0
    write(data, argv[argv.index("--out") + 1] if "--out" in argv else OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
