"""The Status page's environments: what the console reads about staging and the practice spaces. Pure.

deploy/control-plane/env-sync.py runs as root on the console, outside Odoo, like pipeline-collect.py. It asks
staging's restricted agent (deploy/staging/auditisa-env-agent.py) for figures and for the list of test
accounts, and writes /var/lib/auditisa-platform/env-state.json. Odoo reads that file and keeps only what passes
the closed patterns below. Odoo holds no SSH key and opens no connection.

Account actions go the other way: Odoo writes one small request file per action into a spool folder; the root
service picks it up, runs it through the agent and reports the outcome in the next env-state.json. A request
carries a password HASH, never a password: the console draws the password, shows it once, and keeps nothing.

A production firm is never reached this way: the agent knows only staging and the practice spaces.
"""

import json
import re
from datetime import datetime, timedelta

try:
    from odoo.addons.ea_platform_admin.services.messages import _
except ImportError:  # The pure tests run without Odoo: see conftest.py.
    from ea_platform_admin.services.messages import _

SCHEMA = 1
MAX_BYTES = 262144
FRESH = timedelta(minutes=5)
GITHUB_REPO_URL = "https://github.com/Nekoutb/auditisa-odoo"

# The firm roles of ea_audit_core, the agent maps each to its group. Plain words, in the order of power.
ROLES = [
    ("read_only", "Read only"),
    ("staff", "Staff"),
    ("senior", "Senior"),
    ("manager", "Manager"),
    ("eqr_reviewer", "Quality reviewer (EQR)"),
    ("partner", "Partner"),
    ("firm_admin", "Firm administrator"),
]
ROLE_CODES = tuple(code for code, _label in ROLES)
REPORTED_ROLES = ROLE_CODES + ("admin", "user")
ACTIONS = ("create", "disable", "reset")

SHA = re.compile(r"^[0-9a-f]{7,40}$")
RELEASE = re.compile(r"^[0-9a-f]{7,40}$|^[a-z][a-z0-9-]{1,30}$")
INSTANT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SLUG = re.compile(r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$")
LOGIN = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63})+$")
NAME = re.compile(r"^[^\x00-\x1f\x7f<>\"\\]{1,80}$")
MODULE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
VERSION = re.compile(r"^[0-9][0-9.]{0,30}$")
REF = re.compile(r"^[0-9a-f]{16}$")
CODE = re.compile(r"^[a-z_]{1,40}$")
HASH = re.compile(r"^\$pbkdf2-sha512\$[0-9]{1,7}\$[A-Za-z0-9./]{10,64}\$[A-Za-z0-9./]{40,120}$")
SUBJECT = re.compile(r"^[^\x00-\x1f\x7f]{1,160}$")
AUTHOR = re.compile(r"^[^\x00-\x1f<>]{1,40}$")

# What the agent may answer when an action fails: each code has its plain sentence on screen.
FAILURE_CODES = {
    "exists": _("An account with this email already exists there."),
    "not_found": _("There is no such account there."),
    "protected": _("This account is protected: an administrator, or the practice space's first administrator. Change it on the server itself."),
    "bad_request": _("The request was refused as malformed. Nothing was changed."),
    "unknown_space": _("This practice space does not exist on the practice computer."),
    "odoo_failed": _("Odoo refused the change. Nothing was changed."),
    "unreachable": _("The console could not reach staging. Nothing was changed: try again."),
    "expired": _("No answer from staging within 15 minutes. Check the account list before trying again."),
}


def target_ok(target):
    """'staging' or 'practice:<slug>'. Never anything else: a firm's server is not a target."""
    if target == "staging":
        return True
    return isinstance(target, str) and target.startswith("practice:") and bool(SLUG.match(target[9:]))


def request_errors(action, target, login, name=None, role=None, password_hash=None):
    """Why an account request is refused before it is written, as messages. Empty: it may go."""
    errors = []
    if action not in ACTIONS:
        errors.append(_("Unknown action."))
    if not target_ok(target):
        errors.append(_("Accounts are made only on staging or in a practice space."))
    if not LOGIN.match(login or ""):
        errors.append(_("The email address is not valid."))
    if action == "create":
        if not NAME.match((name or "").strip()):
            errors.append(_("The name is required: 1 to 80 characters, without < > or quotes."))
        if role not in ROLE_CODES:
            errors.append(_("Choose a role."))
    if action in ("create", "reset") and not HASH.match(password_hash or ""):
        errors.append(_("The password could not be prepared. Nothing was sent."))
    return errors


def request_payload(ref, action, target, login, name=None, role=None, password_hash=None):
    """The spool file's content. The agent checks every value again."""
    payload = {"schema": SCHEMA, "id": ref, "action": action, "target": target, "login": login.strip().lower()}
    if action == "create":
        payload.update(name=name.strip(), role=role)
    if action in ("create", "reset"):
        payload["password_hash"] = password_hash
    return payload


def _instant(value):
    return value if isinstance(value, str) and INSTANT.match(value) else None


def _int(value, high=10 ** 9):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < high else None


def _text(value, pattern):
    return value if isinstance(value, str) and pattern.match(value) else None


def _users(value):
    users = []
    for row in (value if isinstance(value, list) else [])[:500]:
        if not isinstance(row, dict) or not _text(row.get("login"), re.compile(r"^[^\x00-\x1f\x7f<>]{1,120}$")):
            continue
        users.append({
            "login": row["login"],
            "name": _text(row.get("name"), NAME) or row["login"],
            "role": row.get("role") if row.get("role") in REPORTED_ROLES else "user",
            "active": row.get("active") is True,
            "last_login": _instant(row.get("last_login")),
            "online": row.get("online") is True,
            "protected": row.get("protected") is True,
        })
    return users


def _server(value):
    """The part every server answer shares: versions, size, revision, uptime, mail."""
    value = value if isinstance(value, dict) else {}
    modules = []
    for row in (value.get("modules") if isinstance(value.get("modules"), list) else [])[:60]:
        if isinstance(row, list) and len(row) == 2 and _text(row[0], MODULE) and _text(row[1], VERSION):
            modules.append((row[0], row[1]))
    return {
        "reachable": value.get("reachable") is True,
        "service_active": value.get("service_active") is True,
        "odoo_version": _text(value.get("odoo_version"), VERSION),
        "modules": modules,
        "revision": _text(value.get("revision"), RELEASE),
        "up_since": _instant(value.get("up_since")),
        "mail_off": value.get("mail_off") is True,
    }


def _releases(value):
    rows = []
    for row in (value if isinstance(value, list) else [])[:20]:
        if isinstance(row, dict) and _text(row.get("name"), RELEASE) and _instant(row.get("at")):
            result = row.get("result") if row.get("result") in ("ok", "rolled_back", "running", "replaced") else None
            rows.append({"name": row["name"], "at": row["at"], "result": result})
    return rows


def read_env_state(raw, now):
    """The checked state, or None. `now` is a naive UTC datetime."""
    if not raw or len(raw) > MAX_BYTES:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA or not _instant(data.get("generated")):
        return None
    generated = datetime.strptime(data["generated"], "%Y-%m-%dT%H:%M:%SZ")
    staging = data.get("staging") if isinstance(data.get("staging"), dict) else {}
    practice = data.get("practice") if isinstance(data.get("practice"), dict) else {}
    spaces = []
    for row in (practice.get("spaces") if isinstance(practice.get("spaces"), list) else [])[:300]:
        if isinstance(row, dict) and _text(row.get("slug"), SLUG):
            spaces.append({
                "slug": row["slug"],
                "db_size_mb": _int(row.get("db_size_mb"), 10 ** 7),
                "users": _users(row.get("users")),
            })
    requests = {}
    for row in (data.get("requests") if isinstance(data.get("requests"), list) else [])[:500]:
        if isinstance(row, dict) and _text(row.get("id"), REF) and row.get("state") in ("done", "failed"):
            requests[row["id"]] = {
                "state": row["state"],
                "code": row.get("code") if row.get("code") in FAILURE_CODES else None,
                "at": _instant(row.get("at")),
            }
    return {
        "generated": generated,
        "stale": now - generated > FRESH,
        "staging": _server(staging) | {
            "db_size_mb": _int(staging.get("db_size_mb"), 10 ** 7),
            "releases": _releases(staging.get("releases")),
            "users": _users(staging.get("users")),
        },
        "practice": _server(practice) | {"releases": _releases(practice.get("releases")), "spaces": spaces},
        "requests": requests,
    }


# ---------------------------------------------------------------------------- commits and changes


def commit_log(value):
    """Commits on a branch, newest first, as the collector writes them. Subjects are kept as plain text."""
    rows = []
    for row in (value if isinstance(value, list) else [])[:30]:
        if not isinstance(row, dict) or not _text(row.get("sha"), SHA):
            continue
        subject = row.get("subject")
        rows.append({
            "sha": row["sha"],
            "author": _text(row.get("author"), AUTHOR),
            "at": _instant(row.get("at")),
            "subject": subject[:160] if isinstance(subject, str) and SUBJECT.match(subject[:160]) else None,
        })
    return rows


def same_commit(first, second):
    if not first or not second:
        return False
    return first.startswith(second) or second.startswith(first)


def changes_between(log, old, new):
    """The commits that `new` brings over `old`, from a branch's log (newest first).

    None when the log cannot tell (one of the two is not in it): the screen then says so, it does not guess.
    """
    if not log or not new:
        return None
    shas = [row["sha"] for row in log]
    start = next((index for index, sha in enumerate(shas) if same_commit(sha, new)), None)
    if start is None:
        return None
    if not old:
        return log[start:]
    end = next((index for index, sha in enumerate(shas) if same_commit(sha, old)), None)
    if end is None or end < start:
        return None
    return log[start:end]


def sign_commands(sha):
    """What the owner runs on the computer that holds the signing key. From console-live/first-release.md."""
    sha = sha if sha and SHA.match(sha) else "<commit>"
    return [
        f"bash scripts/provision/build_release.sh {sha} --unsigned --out <release folder>",
        f"bash scripts/provision/build_release.sh --sign <release folder>/{sha}.tar.gz "
        "--key <your signing key>.pem --pub <your signing key>.pub",
    ]


def revision_url(sha):
    return f"{GITHUB_REPO_URL}/commit/{sha}" if sha and SHA.match(sha) else None


def size_text(megabytes):
    if megabytes is None:
        return None
    return f"{megabytes / 1024:.1f} GB" if megabytes >= 1024 else f"{megabytes} MB"
