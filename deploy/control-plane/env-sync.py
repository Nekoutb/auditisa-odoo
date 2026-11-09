#!/usr/bin/env python3
"""env-sync.py: staging's and the practice spaces' figures and accounts, for the Status page. On the console.

    env-sync.py               reads once, carries out the account requests waiting, writes the state file
    env-sync.py --print       reads once and prints, carries out nothing, writes nothing
    env-sync.py --install     copies itself to /usr/local/sbin, adds a timer (each minute) and a path unit
                              (at once when the console drops a request)
    env-sync.py --uninstall   removes them
    env-sync.py --new-key     makes the restricted key /root/.ssh/auditisa_env_agent (once) and prints its
                              PUBLIC half, to install on staging with auditisa-env-agent --install-key

Runs as root, outside Odoo, like pipeline-collect.py: the console's Odoo holds no SSH key and opens no
connection. It talks to one program only, staging's auditisa-env-agent, through a key that staging restricts
to that program (see docs/runbook/ENVIRONMENTS.md).

Files:
  /var/lib/auditisa-platform/env-requests/   Odoo drops one <ref>.json per account action (owned by odoo, 700).
                                             Each carries a password HASH, never a password. Deleted once
                                             carried out, whatever the outcome.
  /var/lib/auditisa-platform/env-state.json  what Odoo reads: figures, accounts (name, email, role, last login,
                                             online now) and the outcome of each request. 640 root:odoo.

Standard library only.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

BASE = os.environ.get("ENV_SYNC_DIR", "/var/lib/auditisa-platform")
SPOOL = os.path.join(BASE, "env-requests")
OUT = os.path.join(BASE, "env-state.json")
OUTCOMES = os.path.join(BASE, "env-outcomes.json")
KEY = os.environ.get("ENV_AGENT_KEY", "/root/.ssh/auditisa_env_agent")
HOST = os.environ.get("ENV_AGENT_HOST", "root@108.61.209.30")
ODOO_USER = os.environ.get("ENV_SYNC_ODOO_USER", "odoo")
REF = re.compile(r"^[0-9a-f]{16}$")
UNIT = "auditisa-env-sync"
KEEP_OUTCOMES = timedelta(days=2)
MAX_REQUEST_BYTES = 4096


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ssh(verb, payload=None, timeout=60):
    """One call to the agent. The verb goes in SSH_ORIGINAL_COMMAND; the agent ignores anything else."""
    result = subprocess.run(
        ["ssh", "-i", KEY, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
         "-o", "StrictHostKeyChecking=accept-new", "-T", HOST, verb],
        input=payload, capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise OSError("agent refused or unreachable")
    return json.loads(result.stdout)


def load_outcomes():
    try:
        with open(OUTCOMES, encoding="utf-8") as handle:
            rows = json.load(handle)
    except (OSError, ValueError):
        return []
    cutoff = (datetime.now(timezone.utc) - KEEP_OUTCOMES).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [row for row in rows if isinstance(row, dict) and str(row.get("at", "")) >= cutoff][-500:]


def carry_out(outcomes):
    """Each waiting request, oldest first. The file goes whatever happens: the console shows the outcome."""
    try:
        names = sorted(os.listdir(SPOOL), key=lambda name: os.stat(os.path.join(SPOOL, name)).st_mtime)
    except OSError:
        return outcomes
    for name in names:
        path = os.path.join(SPOOL, name)
        ref = name[:-5] if name.endswith(".json") else ""
        if not REF.match(ref) or not os.path.isfile(path) or os.path.islink(path):
            # Anything else has no business here, and would wake the path unit again and again.
            try:
                if os.path.islink(path) or os.path.isfile(path):
                    os.unlink(path)
                else:
                    shutil.rmtree(path)
            except OSError:
                pass
            continue
        try:
            with open(path, encoding="utf-8") as handle:
                raw = handle.read(MAX_REQUEST_BYTES + 1)
            os.unlink(path)
        except OSError:
            continue
        outcome = {"id": ref, "state": "failed", "code": "bad_request", "at": now()}
        if len(raw) <= MAX_REQUEST_BYTES:
            try:
                answer = ssh("account", raw, timeout=330)
                if answer.get("id") == ref and answer.get("state") in ("done", "failed"):
                    outcome.update(state=answer["state"], code=answer.get("code") or "")
            except (OSError, ValueError, subprocess.TimeoutExpired):
                outcome["code"] = "unreachable"
        outcomes.append(outcome)
    return outcomes


def collect(act):
    outcomes = load_outcomes()
    if act:
        outcomes = carry_out(outcomes)
    try:
        data = ssh("state")
        if not isinstance(data, dict):
            raise ValueError
    except (OSError, ValueError, subprocess.TimeoutExpired):
        data = {"staging": {"reachable": False}, "practice": {"reachable": False}}
    data.update(schema=1, generated=now(), requests=outcomes)
    return data, outcomes


def write(path, data, mode, group=None):
    folder = os.path.dirname(path)
    handle, temporary = tempfile.mkstemp(dir=folder, prefix=".env-state.")
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        json.dump(data, out, sort_keys=True, indent=1)
    os.chmod(temporary, mode)
    if group:
        shutil.chown(temporary, "root", group)
    os.replace(temporary, path)


def prepare():
    os.makedirs(BASE, exist_ok=True)
    if not os.path.isdir(SPOOL):
        os.makedirs(SPOOL, mode=0o700)
    shutil.chown(SPOOL, ODOO_USER, ODOO_USER)
    os.chmod(SPOOL, 0o700)


def install():
    target = "/usr/local/sbin/env-sync"
    with open(__file__, "rb") as source, open(target + ".tmp", "wb") as copy:
        copy.write(source.read())
    os.chmod(target + ".tmp", 0o755)
    os.replace(target + ".tmp", target)
    prepare()
    units = {
        f"{UNIT}.service": "[Unit]\nDescription=AuditISA: staging and practice figures and test accounts\n[Service]\n"
                           f"Type=oneshot\nExecStart=/usr/bin/python3 -I {target}\nNice=10\nTimeoutStartSec=600\n",
        f"{UNIT}.timer": "[Unit]\nDescription=AuditISA: staging and practice readings each minute\n[Timer]\nOnBootSec=1min\n"
                         "OnUnitActiveSec=1min\nAccuracySec=5s\n[Install]\nWantedBy=timers.target\n",
        f"{UNIT}.path": "[Unit]\nDescription=AuditISA: an account request was dropped\n[Path]\n"
                        f"DirectoryNotEmpty={SPOOL}\nUnit={UNIT}.service\n[Install]\nWantedBy=paths.target\n",
    }
    for name, text in units.items():
        with open(f"/etc/systemd/system/{name}", "w", encoding="ascii") as unit:
            unit.write(text)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", f"{UNIT}.timer", f"{UNIT}.path"], check=True)
    print(f"installed {target}, {UNIT}.timer and {UNIT}.path")


def uninstall():
    subprocess.run(["systemctl", "disable", "--now", f"{UNIT}.timer", f"{UNIT}.path"], check=False)
    for name in (f"{UNIT}.service", f"{UNIT}.timer", f"{UNIT}.path"):
        path = f"/etc/systemd/system/{name}"
        if os.path.exists(path):
            os.unlink(path)
    if os.path.exists("/usr/local/sbin/env-sync"):
        os.unlink("/usr/local/sbin/env-sync")
    subprocess.run(["systemctl", "daemon-reload"], check=False)
    print("removed (the state file and the key stay: remove them by hand if wanted)")


def new_key():
    if not os.path.exists(KEY):
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "auditisa-console-env", "-f", KEY], check=True)
    os.chmod(KEY, 0o600)
    with open(KEY + ".pub", encoding="ascii") as handle:
        print(handle.read().strip())


def main(argv):
    if "--install" in argv:
        install()
        return 0
    if "--uninstall" in argv:
        uninstall()
        return 0
    if "--new-key" in argv:
        new_key()
        return 0
    if "--print" in argv:
        data, _outcomes = collect(act=False)
        json.dump(data, sys.stdout, sort_keys=True, indent=1)
        return 0
    prepare()
    data, outcomes = collect(act=True)
    write(OUTCOMES, outcomes, 0o600)
    write(OUT, data, 0o640, group=ODOO_USER)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
