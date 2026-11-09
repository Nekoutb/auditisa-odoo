#!/usr/bin/env python3
"""auditisa-env-agent: the console's only way into staging, through one restricted SSH key. On staging, as root.

The console's root service (deploy/control-plane/env-sync.py) logs in with a key that can run this program and
nothing else. Its line in /root/.ssh/authorized_keys, written by --install-key:

    restrict,command="/usr/local/sbin/auditisa-env-agent" ssh-ed25519 AAAA... auditisa-console-env

`restrict` means no shell, no terminal, no port or agent forwarding. What the console asks for arrives in
SSH_ORIGINAL_COMMAND, and only two verbs exist:

    state      staging's and the practice spaces' figures, and the list of their accounts. Read-only.
    account    one account action, as JSON on stdin: create, disable or reset, on staging or in one practice
               space. The request carries a password HASH, made by the console: no password ever comes here.

It reads and changes nothing but staging's database (db_name of /etc/odoo/odoo.conf) and the practice_<slug>
databases of registered practice spaces. It never touches a firm: a firm's server is not reachable from here.
It never sends mail: accounts are created with no invitation, and staging's outgoing mail is closed anyway.

    auditisa-env-agent --install-key PUBLIC_KEY_FILE    installs itself and the restricted key line
    auditisa-env-agent --uninstall                      removes the key line and itself
    auditisa-env-agent --self-test                      prints `state` locally

Standard library only.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

STAGING_CONF = os.environ.get("ENV_AGENT_STAGING_CONF", "/etc/odoo/odoo.conf")
PRACTICE_CONF = "/etc/odoo/practice.conf"
PRACTICE_SPACES = "/var/lib/auditisa-practice/spaces"
PRACTICE_CURRENT = "/opt/auditisa-practice/current"
PRACTICE_ACTIONS = "/var/log/auditisa-practice/actions.log"
RELEASES_ROOT = "/opt/auditisa-odoo"
PYTHON = "/opt/odoo19/venv/bin/python"
ODOO_BIN = "/opt/odoo19/src/odoo-bin"
TARGET = "/usr/local/sbin/auditisa-env-agent"
KEY_COMMENT = "auditisa-console-env"
AUTHORIZED = "/root/.ssh/authorized_keys"

SLUG = re.compile(r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$")
REF = re.compile(r"^[0-9a-f]{16}$")
LOGIN = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63})+$")
NAME = re.compile(r"^[^\x00-\x1f\x7f<>\"\\]{1,80}$")
HASH = re.compile(r"^\$pbkdf2-sha512\$[0-9]{1,7}\$[A-Za-z0-9./]{10,64}\$[A-Za-z0-9./]{40,120}$")
RELEASE = re.compile(r"^[0-9a-f]{7,40}$|^[a-z][a-z0-9-]{1,30}$")
DBNAME = re.compile(r"^[a-z][a-z0-9_-]{1,62}$")
ROLES = ("read_only", "staff", "senior", "manager", "eqr_reviewer", "partner", "firm_admin")
LADDER = ("firm_admin", "partner", "eqr_reviewer", "manager", "senior", "staff", "read_only")


def utc(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, timeout=kwargs.pop("timeout", 60), **kwargs)


def psql(db, sql):
    if not DBNAME.match(db):
        raise ValueError("bad database name")
    result = run(["runuser", "-u", "postgres", "--", "psql", "-X", "-A", "-t", "-q", "-v", "ON_ERROR_STOP=1", "-d", db, "-c", sql])
    if result.returncode != 0:
        raise RuntimeError("psql failed")
    return result.stdout.strip()


def conf_value(path, key):
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                match = re.match(rf"^\s*{key}\s*=\s*(.*?)\s*$", line)
                if match:
                    return match.group(1)
    except OSError:
        pass
    return None


def db_exists(db):
    return DBNAME.match(db) and psql("postgres", f"SELECT 1 FROM pg_database WHERE datname = '{db}'") == "1"


def service(unit):
    active = run(["systemctl", "is-active", unit]).stdout.strip() == "active"
    since = None
    raw = run(["systemctl", "show", unit, "-p", "ActiveEnterTimestamp", "--value"]).stdout.strip()
    if active and raw:
        parsed = run(["date", "-u", "-d", raw, "+%Y-%m-%dT%H:%M:%SZ"]).stdout.strip()
        since = parsed or None
    return active, since


def mail_closed(conf):
    return (conf_value(conf, "smtp_server") or "False") in ("False", "", "false")


USERS_SQL = """
SELECT coalesce(json_agg(t ORDER BY t.login), '[]') FROM (
  SELECT u.login, p.name, u.active,
         to_char((SELECT max(l.create_date) FROM res_users_log l WHERE l.create_uid = u.id),
                 'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS last_login,
         {online} AS online,
         (SELECT string_agg(d.module || '.' || d.name, ',') FROM res_groups_users_rel r
            JOIN ir_model_data d ON d.model = 'res.groups' AND d.res_id = r.gid
           WHERE r.uid = u.id AND ((d.module = 'ea_audit_core' AND d.name LIKE 'group\\_%')
                 OR (d.module = 'base' AND d.name = 'group_system'))) AS groups,
         u.id IN (SELECT res_id FROM ir_model_data WHERE model = 'res.users' AND module = 'base' AND name = 'user_admin') AS is_admin_user
    FROM res_users u JOIN res_partner p ON p.id = u.partner_id
   WHERE u.share = false
     AND u.id NOT IN (SELECT res_id FROM ir_model_data WHERE model = 'res.users' AND module = 'base'
                      AND name IN ('user_root', 'public_user', 'default_user', 'template_portal_user_id'))
) t
"""
ONLINE_SQL = ("coalesce((SELECT pr.status = 'online' AND pr.last_poll > (now() AT TIME ZONE 'utc') - interval '3 minutes' "
              "FROM mail_presence pr WHERE pr.user_id = u.id), false)")


def users(db, protected_login=None):
    has_presence = psql(db, "SELECT to_regclass('mail_presence') IS NOT NULL") == "t"
    rows = json.loads(psql(db, USERS_SQL.format(online=ONLINE_SQL if has_presence else "false")) or "[]")
    out = []
    for row in rows:
        groups = set((row.get("groups") or "").split(","))
        role = next((code for code in LADDER if f"ea_audit_core.group_{code}" in groups), "user")
        admin = "base.group_system" in groups or row.get("is_admin_user")
        if admin and role == "user":
            role = "admin"
        out.append({
            "login": row["login"], "name": (row.get("name") or "")[:80], "role": role, "active": bool(row["active"]),
            "last_login": row.get("last_login"), "online": bool(row.get("online")),
            "protected": bool(admin or (protected_login and row["login"].lower() == protected_login.lower())),
        })
    return out


def server_figures(db):
    base = psql(db, "SELECT latest_version FROM ir_module_module WHERE name = 'base'") or ""
    modules = [line.split("|", 1) for line in psql(db, (
        "SELECT name || '|' || coalesce(latest_version, '') FROM ir_module_module "
        "WHERE state = 'installed' AND name LIKE 'ea\\_%' ORDER BY name")).splitlines() if "|" in line]
    servers = int(psql(db, "SELECT count(*) FROM ir_mail_server WHERE active") or 0)
    return {
        "odoo_version": ".".join(base.split(".")[:2]) or None,
        "modules": [[name, version] for name, version in modules if version],
        "db_size_mb": int(psql(db, "SELECT pg_database_size(current_database()) / 1048576") or 0),
        "mail_servers": servers,
    }


def space_admin_login(slug):
    try:
        with open(os.path.join(PRACTICE_SPACES, f"{slug}.env"), encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("ADMIN_LOGIN="):
                    return line.split("=", 1)[1].strip().strip("'\"")
    except OSError:
        pass
    return None


def spaces():
    try:
        names = sorted(name[:-4] for name in os.listdir(PRACTICE_SPACES) if name.endswith(".env"))
    except OSError:
        return []
    return [slug for slug in names if SLUG.match(slug) and db_exists(f"practice_{slug}")]


def staging_state():
    db = conf_value(STAGING_CONF, "db_name") or ""
    out = {"reachable": True}
    active, since = service("odoo")
    out.update(service_active=active, up_since=since)
    match = re.search(r"/opt/auditisa-odoo/([^/,]+)/addons", conf_value(STAGING_CONF, "addons_path") or "")
    current = match.group(1) if match else None
    out["revision"] = current if current and RELEASE.match(current) else None
    if db and db_exists(db):
        figures = server_figures(db)
        out.update({k: v for k, v in figures.items() if k != "mail_servers"})
        out["mail_off"] = mail_closed(STAGING_CONF) and figures["mail_servers"] == 0
        out["users"] = users(db)
    releases = []
    try:
        for name in os.listdir(RELEASES_ROOT):
            path = os.path.join(RELEASES_ROOT, name)
            # Release folders are named by their commit. Other folders there (agents' trial copies) are not deploys.
            if re.match(r"^[0-9a-f]{7,40}$", name) and os.path.isdir(os.path.join(path, "addons")):
                releases.append((os.stat(path).st_mtime, name))
    except OSError:
        pass
    out["releases"] = [
        {"name": name, "at": utc(datetime.fromtimestamp(when, timezone.utc)), "result": "running" if name == current else "replaced"}
        for when, name in sorted(releases, reverse=True)[:12]
    ]
    return out


def practice_state():
    if not os.path.exists(PRACTICE_CONF):
        return {"reachable": False}
    out = {"reachable": True}
    active, since = service("odoo-practice")
    out.update(service_active=active, up_since=since)
    current = os.path.basename(os.path.realpath(PRACTICE_CURRENT)) if os.path.exists(PRACTICE_CURRENT) else None
    out["revision"] = current if current and RELEASE.match(current) else None
    updates = []
    try:
        with open(PRACTICE_ACTIONS, encoding="utf-8") as handle:
            for line in handle:
                match = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) practice-update update release=([0-9a-f]{7,40})( spaces=\d+| rolled back)\s*$", line)
                if match:
                    updates.append({"name": match.group(2), "at": match.group(1),
                                    "result": "rolled_back" if "rolled" in match.group(3) else "ok"})
    except OSError:
        pass
    out["releases"] = list(reversed(updates))[:12]
    rows, servers, first = [], 0, None
    for slug in spaces():
        db = f"practice_{slug}"
        figures = server_figures(db)
        first = first or figures
        servers += figures["mail_servers"]
        rows.append({"slug": slug, "db_size_mb": figures["db_size_mb"], "users": users(db, space_admin_login(slug))})
    if first:
        out.update(odoo_version=first["odoo_version"], modules=first["modules"])
    out["mail_off"] = mail_closed(PRACTICE_CONF) and servers == 0
    out["spaces"] = rows
    return out


def state():
    data = {"schema": 1}
    for key, function in (("staging", staging_state), ("practice", practice_state)):
        try:
            data[key] = function()
        except Exception:  # noqa: BLE001 - one side failing must not hide the other
            data[key] = {"reachable": False}
    return data


SHELL_SCRIPT = r"""
import json, os
req = json.loads(os.environ["EA_ENV_REQUEST"])
protected = (os.environ.get("EA_ENV_PROTECTED") or "").lower()
Users = env["res.users"].sudo().with_context(
    active_test=False, no_reset_password=True, mail_create_nolog=True, mail_create_nosubscribe=True,
    mail_notrack=True, tracking_disable=True)

def answer(state, code=""):
    print("EA_ENV_RESULT " + json.dumps({"state": state, "code": code}))

user = Users.search([("login", "=ilike", req["login"])], limit=1)
untouchable = {env.ref("base.user_root").id, env.ref("base.user_admin").id}
if req["action"] == "create":
    if user:
        answer("failed", "exists")
    else:
        role = env.ref("ea_audit_core.group_" + req["role"])
        user = Users.create({"name": req["name"], "login": req["login"], "email": req["login"],
                             "group_ids": [(6, 0, [env.ref("base.group_user").id, role.id])]})
        env.cr.execute("UPDATE res_users SET password = %s WHERE id = %s", (req["password_hash"], user.id))
        env.cr.commit()
        answer("done")
elif not user:
    answer("failed", "not_found")
elif user.id in untouchable or user.share or user.has_group("base.group_system") or user.login.lower() == protected:
    answer("failed", "protected")
elif req["action"] == "disable":
    user.write({"active": False})
    env.cr.commit()
    answer("done")
else:
    env.cr.execute("UPDATE res_users SET password = %s WHERE id = %s", (req["password_hash"], user.id))
    env.cr.commit()
    answer("done")
"""


def check_request(data):
    if not isinstance(data, dict) or data.get("schema") != 1 or not REF.match(str(data.get("id", ""))):
        return False
    if data.get("action") not in ("create", "disable", "reset") or not LOGIN.match(str(data.get("login", ""))):
        return False
    target = data.get("target")
    if target != "staging" and not (isinstance(target, str) and target.startswith("practice:") and SLUG.match(target[9:])):
        return False
    if data["action"] == "create" and (not NAME.match(str(data.get("name", ""))) or data.get("role") not in ROLES):
        return False
    if data["action"] in ("create", "reset") and not HASH.match(str(data.get("password_hash", ""))):
        return False
    allowed = {"schema", "id", "action", "target", "login", "name", "role", "password_hash"}
    return not set(data) - allowed


def account(raw):
    try:
        data = json.loads(raw)
    except ValueError:
        return {"state": "failed", "code": "bad_request"}
    if not check_request(data):
        return {"id": data.get("id") if isinstance(data, dict) and REF.match(str(data.get("id", ""))) else None,
                "state": "failed", "code": "bad_request"}
    if data["target"] == "staging":
        conf, user, db, protected = STAGING_CONF, "odoo", conf_value(STAGING_CONF, "db_name") or "", ""
    else:
        slug = data["target"][9:]
        if slug not in spaces():
            return {"id": data["id"], "state": "failed", "code": "unknown_space"}
        conf, user, db, protected = PRACTICE_CONF, "odoo-practice", f"practice_{slug}", space_admin_login(slug) or ""
    if not DBNAME.match(db) or not db_exists(db):
        return {"id": data["id"], "state": "failed", "code": "unknown_space"}
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "HOME": "/tmp",
           "EA_ENV_REQUEST": json.dumps(data), "EA_ENV_PROTECTED": protected}
    result = subprocess.run(
        ["runuser", "-u", user, "--", PYTHON, ODOO_BIN, "shell", "-c", conf, "-d", db, "--no-http",
         "--log-level=warn", "--logfile=/dev/null", "--max-cron-threads=0"],
        input=SHELL_SCRIPT, capture_output=True, text=True, timeout=300, env=env, cwd="/tmp",
    )
    for line in result.stdout.splitlines():
        if line.startswith("EA_ENV_RESULT "):
            outcome = json.loads(line[len("EA_ENV_RESULT "):])
            code = outcome.get("code") if outcome.get("code") in ("exists", "not_found", "protected") else ""
            return {"id": data["id"], "state": "done" if outcome.get("state") == "done" else "failed", "code": code}
    return {"id": data["id"], "state": "failed", "code": "odoo_failed"}


def install_key(path):
    with open(path, encoding="ascii") as handle:
        key = handle.read().strip()
    if not re.match(r"^ssh-ed25519 [A-Za-z0-9+/=]{60,100}( \S+)?$", key):
        raise SystemExit("not an ed25519 public key")
    with open(__file__, "rb") as source, open(TARGET + ".tmp", "wb") as copy:
        copy.write(source.read())
    os.chmod(TARGET + ".tmp", 0o700)
    os.replace(TARGET + ".tmp", TARGET)
    body = " ".join(key.split()[:2])
    line = f'restrict,command="{TARGET}" {body} {KEY_COMMENT}\n'
    os.makedirs(os.path.dirname(AUTHORIZED), mode=0o700, exist_ok=True)
    existing = open(AUTHORIZED, encoding="utf-8").read().splitlines(True) if os.path.exists(AUTHORIZED) else []
    kept = [row for row in existing if KEY_COMMENT not in row]
    with open(AUTHORIZED + ".tmp", "w", encoding="utf-8") as out:
        out.writelines(kept + [line])
    os.chmod(AUTHORIZED + ".tmp", 0o600)
    os.replace(AUTHORIZED + ".tmp", AUTHORIZED)
    print(f"installed {TARGET} and the restricted key line ({KEY_COMMENT})")


def uninstall():
    if os.path.exists(AUTHORIZED):
        rows = open(AUTHORIZED, encoding="utf-8").read().splitlines(True)
        with open(AUTHORIZED + ".tmp", "w", encoding="utf-8") as out:
            out.writelines(row for row in rows if KEY_COMMENT not in row)
        os.chmod(AUTHORIZED + ".tmp", 0o600)
        os.replace(AUTHORIZED + ".tmp", AUTHORIZED)
    if os.path.exists(TARGET):
        os.unlink(TARGET)
    print("removed")


def main(argv):
    if argv[:1] == ["--install-key"] and len(argv) == 2:
        install_key(argv[1])
        return 0
    if argv == ["--uninstall"]:
        uninstall()
        return 0
    if argv == ["--self-test"]:
        json.dump(state(), sys.stdout, indent=1)
        return 0
    verb = (os.environ.get("SSH_ORIGINAL_COMMAND") or "").strip()
    if verb == "state":
        json.dump(state(), sys.stdout, separators=(",", ":"))
        return 0
    if verb == "account":
        json.dump(account(sys.stdin.read(8192)), sys.stdout, separators=(",", ":"))
        return 0
    sys.stderr.write("refused\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
