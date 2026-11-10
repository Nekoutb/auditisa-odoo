"""The decisions of the pipeline. Pure: no Odoo, no network.

What is promoted is a registered release, named by its commit and the SHA-256 of its bundle. A firm's
server installs only a bundle with that SHA-256, which it receives from the console over its
authenticated heartbeat. Who may promote is who may sign in to the console as its owner.
"""

import ipaddress
import re

try:
    from odoo.addons.ea_platform_admin.services.messages import _
except ImportError:  # The pure tests run without Odoo: see conftest.py.
    from ea_platform_admin.services.messages import _

MIN_REASON_LENGTH = 10

_REF = re.compile(r"^[0-9a-f]{16}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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


def owner_addresses(text):
    """The owner's address list for Promote and Rebuild, as written in the system parameter."""
    return [part for part in re.split(r"[\s,;]+", (text or "").strip()) if part]


def owner_address_ok(remote_address, cidrs):
    """No list is the owner's choice: no address check (ruling of 2026-11-08, the control room opens
    from anywhere; sign-in and two-factor stay: access to the console is the security).
    A list, once written, refuses every other address, and one that holds no valid range refuses all."""
    if not cidrs:
        return True
    return address_allowed(remote_address, cidrs)


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

