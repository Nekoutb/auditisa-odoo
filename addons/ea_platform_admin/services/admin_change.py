"""Changing or adding a firm's administrator from the console (owner's request of 2026-11-18). Pure.

The operator types a name and an email on the firm's page. The request travels the way every other
request does: in the signed answer to the firm's next heartbeat (nothing over SSH). The firm's server
makes the change, and its next heartbeat brings back the request's reference, one word, and, for a new
account, the one-time invitation link (72 hours, one use). The console shows that link once.

The rules below are checked again on the firm's server (ea_audit_firm_agent/services/collect.py and
ea_audit_timesheet/models/firm_admin.py): services/tests/test_admin_change.py checks that they agree.
"""

import re

from .messages import _
from .validation import parse_domain_list

ACTIONS = ("add", "replace")
ACTION_CHOICES = [
    ("add", "Add a firm administrator"),
    ("replace", "Replace the firm administrator"),
]
MAX_NAME = 128
MAX_EMAIL = 254
REF = re.compile(r"^[0-9a-f]{16}$")
EMAIL = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,63}$")
# The invitation link the firm's server makes: https, its own address, Odoo's sign-up page and a query
# of the characters a URL-encoded database name and token use. No free text can pass.
LINK = re.compile(r"^https://[a-z0-9.-]{3,253}(:[0-9]{2,5})?/web/signup\?[A-Za-z0-9._~%&=+-]{1,1000}$")
LINK_HOURS = 72

# What the firm's server answers, as one word (heartbeat figure admin_request_result).
# Same words as ea_audit_firm_agent/services/collect.py ADMIN_RESULTS.
RESULTS = ("done", "email", "domain", "account", "unavailable", "failed")
STATES = [
    ("none", "Nothing asked from the console"),
    ("waiting", "Waiting for the firm's next check-in"),
    ("done", "Done"),
    ("email", "Email address refused"),
    ("domain", "Outside the allowed email domains"),
    ("account", "This account cannot be a firm administrator"),
    ("unavailable", "Not possible on this firm's release"),
    ("failed", "Not done"),
]
MESSAGES = {
    "none": _("Nothing has been asked from the console."),
    "waiting": _(
        "Waiting for the firm's next check-in (within 15 minutes). The result shows here; reload the page to see it."
    ),
    "email": _("Not done: the firm's server refused this email address. Check it, then ask again."),
    "domain": _(
        "Not done: this email address is not in the firm's allowed email domains. Use an address of the firm, "
        "or have the firm administrator add the domain first."
    ),
    "account": _(
        "Not done: this email address belongs to an account that cannot be a firm administrator (for example a "
        "client's account). Use another address."
    ),
    "unavailable": _(
        "Not done: the firm's server runs an older release that cannot do this. Update it, then ask again."
    ),
    "failed": _("Not done: the firm's server could not make the change. Ask again; if it fails again, tell the developer."),
}


def clean_name(value):
    return " ".join((value or "").split())


def clean_email(value):
    return (value or "").strip().lower()


def domain_of(email):
    return email.rsplit("@", 1)[1] if "@" in email else ""


def request_errors(name, email, allowed_domains_text):
    """Messages in plain words; empty means the request can be queued.

    The firm's list of allowed email domains is the console's copy, as given at onboarding. An empty list
    allows every domain, as on the firm's server.
    """
    found = []
    name = clean_name(name)
    email = clean_email(email)
    if not name:
        found.append(_("Give the person's name."))
    elif len(name) > MAX_NAME or any(ord(char) < 32 for char in name):
        found.append(_("The name is too long, or it holds an invisible character."))
    if not email or len(email) > MAX_EMAIL or not EMAIL.match(email):
        found.append(_("Give one email address, for example awa@cabinet.cm."))
        return found
    domains, _errors = parse_domain_list(allowed_domains_text)
    if domains and domain_of(email) not in domains:
        found.append(_(
            "This email address is not in the firm's allowed email domains (%(domains)s). Use an address of the firm.",
            domains=", ".join(domains),
        ))
    return found


def request(ref, action, name, email):
    """What the heartbeat answer carries. ValueError if it would be refused on the firm's server."""
    data = {"ref": ref, "action": action, "name": clean_name(name), "email": clean_email(email)}
    if not valid_request(data):
        raise ValueError("refused")
    return data


def valid_request(data):
    """The firm's own check of the request (ea_audit_firm_agent/services/collect.py), repeated here."""
    return (
        isinstance(data, dict) and set(data) == {"ref", "action", "name", "email"}
        and isinstance(data["ref"], str) and bool(REF.match(data["ref"]))
        and data["action"] in ACTIONS
        and isinstance(data["name"], str) and 0 < len(data["name"]) <= MAX_NAME
        and not any(ord(char) < 32 for char in data["name"])
        and isinstance(data["email"], str) and len(data["email"]) <= MAX_EMAIL and bool(EMAIL.match(data["email"]))
    )
