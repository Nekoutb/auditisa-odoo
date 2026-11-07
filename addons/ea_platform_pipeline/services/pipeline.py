"""The decisions of the pipeline. Pure: no Odoo, no network.

What is promoted is a release signed offline. The control plane holds only the public half of that
key: it can check a signature and cannot make one, so nothing done here can produce a release that a
firm would accept.
"""

import base64
import ipaddress
import re
from datetime import timedelta

try:
    from odoo.addons.ea_platform_admin.services.messages import _
except ImportError:  # The pure tests run without Odoo: see conftest.py.
    from ea_platform_admin.services.messages import _

ATTESTATION_PREFIX = "ea-promotion-v1"
MIN_REASON_LENGTH = 10
HEARTBEAT_FRESH = timedelta(minutes=45)
BACKUP_FRESH = timedelta(hours=26)

_REF = re.compile(r"^[0-9a-f]{16}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def attestation_message(sha, bundle_sha256):
    """What the owner signs, offline, alongside the bundle. scripts/pipeline/sign_promotion.sh writes it."""
    return f"{ATTESTATION_PREFIX}\n{sha}\n{bundle_sha256}\n".encode("ascii")


def attestation_holds(public_pem, sha, bundle_sha256, attestation_b64):
    """Whether this commit and digest were signed with the offline key. False on anything unexpected."""
    if not public_pem or not attestation_b64:
        return False
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
    except ImportError:
        return False
    try:
        key = load_pem_public_key(public_pem.encode("ascii"))
        signature = base64.b64decode("".join(attestation_b64.split()), validate=True)
    except (ValueError, TypeError, UnicodeError):
        return False
    if not isinstance(key, Ed25519PublicKey):
        return False
    try:
        key.verify(signature, attestation_message(sha, bundle_sha256))
    except InvalidSignature:
        return False
    return True


def same_commit(first, second):
    """A heartbeat may carry a short commit, a release a longer one."""
    if not first or not second:
        return False
    return first.startswith(second) or second.startswith(first)


def phrase(kind, target, lang=None):
    """What must be typed to go ahead. It names the target, so a reflex cannot confirm the wrong thing."""
    french = (lang or "").startswith("fr")
    word = {
        "promote": "PROMOUVOIR" if french else "PROMOTE",
        "rollback": "REVENIR" if french else "ROLLBACK",
        "rebuild": "RECONSTRUIRE" if french else "REBUILD",
        "main": "MAIN",
        "rebuilt": "RECONSTRUIT" if french else "REBUILT",
    }[kind]
    return f"{word} {target}"


def confirmation_errors(expected, typed, reason):
    errors = []
    if (typed or "").strip() != expected:
        errors.append(_("Type exactly: %(phrase)s", phrase=expected))
    if len((reason or "").strip()) < MIN_REASON_LENGTH:
        errors.append(_("Give a reason of at least %(count)s characters.", count=MIN_REASON_LENGTH))
    return errors


def address_allowed(remote_address, cidrs):
    """Second lock behind nginx. No list, or an address that cannot be read, refuses."""
    if not remote_address or not cidrs:
        return False
    try:
        address = ipaddress.ip_address(remote_address)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if address in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def check(code, ok, detail):
    return {"code": code, "ok": bool(ok), "detail": detail}


def test_check(runs):
    """`runs`: dicts with `suite`, `passed`, `failed`, newest first, for this commit. The newest per suite counts."""
    if not runs:
        return check("tests", False, _("No test run is recorded for this commit."))
    newest = {}
    for run in runs:
        newest.setdefault(run["suite"], run)
    failing = sorted(suite for suite, run in newest.items() if run["failed"] or not run["passed"])
    if failing:
        return check("tests", False, _("Not green: %(suites)s.", suites=", ".join(failing)))
    return check("tests", True, _("Green on this commit: %(suites)s.", suites=", ".join(sorted(newest))))


def staging_check(staging, sha, now):
    """`staging`: the figures of the firm row that stands for the staging server, or None."""
    if not staging:
        return check("staging", False, _("No server is marked as staging: its health is unknown."))
    heartbeat = staging.get("last_heartbeat_at")
    if not heartbeat or now - heartbeat > HEARTBEAT_FRESH:
        return check("staging", False, _("Staging has not reported recently."))
    if staging.get("health_color") == "red":
        return check("staging", False, _("Staging is red."))
    if not same_commit(staging.get("release"), sha):
        return check("staging", False, _("Staging is not running this commit."))
    if staging.get("mail_enabled"):
        return check("staging", False, _("Staging reports that mail is on."))
    return check("staging", True, _("Staging runs this commit and is healthy."))


def backup_check(firms, now):
    """`firms`: name, last_backup_at, last_backup_ok. Each server backs up again before it updates."""
    if not firms:
        return check("backup", False, _("No firm is selected."))
    old = sorted(
        firm["name"] for firm in firms
        if not firm.get("last_backup_at") or not firm.get("last_backup_ok") or now - firm["last_backup_at"] > BACKUP_FRESH
    )
    if old:
        return check("backup", False, _("No good backup in the last 26 hours: %(firms)s.", firms=", ".join(old)))
    return check("backup", True, _("Every firm has a good backup from the last 26 hours."))


def rebuild_transition(state, figures, ref):
    """New state of an open rebuild from a firm's heartbeat, or None. Another reference changes nothing."""
    if figures.get("anon_export_ref") != ref:
        return None
    reported = figures.get("anon_export_state")
    if state in ("requested", "running"):
        if reported == "running":
            return "running"
        if reported == "done" and _SHA256.match(figures.get("anon_export_sha256") or ""):
            return "exported"
        if reported in ("failed", "refused"):
            return "failed" if reported == "failed" else "refused"
    return None


# The whole public document. status.auditisa.com is public: anything outside these keys is dropped by
# the generator as well, and no key names a firm, a person or a reason.
PUBLIC_KEYS = (
    "schema", "generated_at", "firms_total", "firms_on_target", "target_release", "rollout_state",
    "rollout_done", "rollout_total", "last_promotion_at", "last_promotion_release", "last_rebuild_at",
    "last_rebuild_state", "staging_release", "staging_health",
)


def public_state(values):
    return {name: values.get(name) for name in PUBLIC_KEYS}
