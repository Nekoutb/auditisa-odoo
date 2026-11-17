"""A firm's outgoing mail settings, as the console's "Email for this firm" screen takes them. Pure.

Owner's ruling of 2026-11-17: each client firm's own mailbox sends its email (password resets,
invitations), and the operator enters its settings on the console instead of logging in to the firm's
server. The rules are those of deploy/firm/firm_mail.py, which the firm's server applies again before
anything is saved: services/tests/test_mail_settings.py checks that both accept and refuse the same.

The password is checked here and handed on; nothing in this module keeps it.
"""

import ipaddress
import re

from .messages import _

PORTS = (25, 465, 587, 2525)
ENCRYPTIONS = ("starttls", "ssl")
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
HOST = re.compile(r"^(?=.{1,253}$)%s(?:\.%s)+$" % (_LABEL, _LABEL))
SENDER = re.compile(r"^(?:[A-Za-z0-9._%%+-]{1,64}@)?(?=.{1,253}$)%s(?:\.%s)+$" % (_LABEL, _LABEL))
USER = re.compile(r"^[^\s\x00-\x1f]{1,254}$")
MAX_PASSWORD = 512

# The usual providers. Their settings fill the form; the operator can still change each field.
PRESETS = {
    "microsoft365": {"host": "smtp.office365.com", "port": 587, "encryption": "starttls"},
    "google": {"host": "smtp.gmail.com", "port": 587, "encryption": "starttls"},
    "hostinger": {"host": "smtp.hostinger.com", "port": 465, "encryption": "ssl"},
    "mailersend": {"host": "smtp.mailersend.net", "port": 587, "encryption": "starttls"},
}
PRESET_CHOICES = [
    ("microsoft365", "Microsoft 365"),
    ("google", "Google Workspace"),
    ("hostinger", "Hostinger"),
    ("mailersend", "MailerSend"),
    ("other", "Another provider"),
]
ENCRYPTION_CHOICES = [("starttls", "STARTTLS"), ("ssl", "SSL")]

FIELDS = ("host", "port", "encryption", "user", "password", "sender")

# What the firm's server answers, as one word (heartbeat figure mail_request_result), and what the
# console says about it. "waiting", "expired" and "no_answer" are the console's own.
RESULTS = ("on", "off", "login", "connect", "tls", "sender", "staging", "refused", "failed")
STATES = [
    ("none", "Not set from the console"),
    ("waiting", "Waiting for the firm's server"),
    ("on", "Sending is on"),
    ("off", "Sending is off"),
    ("login", "Username or password refused"),
    ("connect", "Mail server not reached"),
    ("tls", "Encryption or port to check"),
    ("sender", "Sender address refused"),
    ("staging", "Test environment: never sends"),
    ("refused", "Settings refused"),
    ("failed", "Test failed"),
    ("expired", "Not collected in time"),
    ("no_answer", "No answer from the firm's server"),
]
MESSAGES = {
    "none": _("Nothing has been sent from the console yet. Use Email for this firm to enter the firm's mailbox settings."),
    "waiting": _(
        "Sent. The firm's server collects the settings at its next check-in (within 15 minutes), tests them "
        "without sending any message, and the result shows here (within 30 minutes). Reload the page to see it."
    ),
    "on": _("Test passed: the firm's server now sends its email (password resets, invitations) from this mailbox."),
    "off": _("Sending is off: the firm's server sends no email. \"Forgot your password?\" is hidden on its login page."),
    "login": _(
        "The mailbox refused the username or the password. Check them with the firm. Microsoft 365 and Google "
        "often need an app password, or SMTP sending switched on for this mailbox. Sending stays off."
    ),
    "connect": _("The firm's server could not reach the mail server. Check the server name and the port. Sending stays off."),
    "tls": _(
        "The connection did not work with this encryption and this port. Usually: STARTTLS with port 587, "
        "or SSL with port 465. Sending stays off."
    ),
    "sender": _("The mail server refused the sender address. Use the mailbox's own address. Sending stays off."),
    "staging": _("This is a test environment: it never sends email, by policy. Nothing was changed."),
    "refused": _("The firm's server refused these settings. Check each field and send them again. Sending stays off."),
    "failed": _("The connection test did not pass. Check the settings with the firm, then send them again. Sending stays off."),
    "expired": _(
        "The firm's server did not collect the settings in time, so the console erased them. Enter them again "
        "once the firm's server is running."
    ),
    "no_answer": _(
        "The firm's server collected the settings but has not answered. Its release may be older than this "
        "screen: update it, then send the settings again."
    ),
}


def clean(values):
    """The screen's values, trimmed. The password is kept exactly as typed."""
    port = values.get("port")
    if isinstance(port, str):
        port = int(port) if port.strip().isdigit() else None
    return {
        "host": (values.get("host") or "").strip().lower(),
        "port": port if type(port) is int else None,
        "encryption": (values.get("encryption") or "").strip().lower(),
        "user": (values.get("user") or "").strip(),
        "password": values.get("password") or "",
        "sender": (values.get("sender") or "").strip(),
    }


def errors(values):
    """{field: [message]} in plain words. Empty means firm_mail.py will accept these settings."""
    data = clean(values)
    found = {}

    def add(field, message):
        found.setdefault(field, []).append(message)

    host = data["host"]
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if not address.is_global:
            add("host", _("Server: a local or private address is refused. Use the provider's server name."))
    elif not HOST.match(host) or host == "localhost" or host.endswith(".localhost"):
        add("host", _("Server: give the provider's server name, for example smtp.office365.com."))
    if data["port"] not in PORTS:
        add("port", _("Port: 587 or 465 (25 and 2525 also work)."))
    if data["encryption"] not in ENCRYPTIONS:
        add("encryption", _("Encryption: choose STARTTLS or SSL."))
    user, password = data["user"], data["password"]
    if bool(user) != bool(password):
        add("password" if user else "user", _("Username and password go together: fill in both, or neither."))
    if user and not USER.match(user):
        add("user", _("Username: no spaces."))
    if len(password) > MAX_PASSWORD or any(ord(c) < 32 for c in password):
        add("password", _("Password: too long, or it holds an invisible character."))
    if not SENDER.match(data["sender"]):
        add("sender", _("Sender address: an address such as cabinet@example.com."))
    return found


def filled(values):
    """True when the operator has started on the settings (the New firm form's step is optional)."""
    data = clean(values)
    return bool(data["host"] or data["user"] or data["password"] or data["sender"])


def settings(values):
    """What the firm's server receives, once. ValueError if the values are refused."""
    if errors(values):
        raise ValueError("refused")
    data = clean(values)
    return {
        "host": data["host"], "port": data["port"], "encryption": data["encryption"],
        "user": data["user"], "password": data["password"], "from": data["sender"],
    }


def summary(values):
    """One line for the screens and the platform log. Never the password."""
    data = clean(values)
    parts = ["%s:%s %s" % (data["host"], data["port"] or "", data["encryption"].upper())]
    if data["user"]:
        parts.append(data["user"])
    if data["sender"] and data["sender"] != data["user"]:
        parts.append(data["sender"])
    return ", ".join(parts)


def preset(code):
    """The server, port and encryption of a known provider; empty for another one."""
    return dict(PRESETS.get(code or "", {}))
