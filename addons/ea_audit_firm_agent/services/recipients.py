"""Who an outgoing email may go to, on a practice space. Pure: standard library only.

A practice space (deploy/practice) carries `ea_firm_agent.recipient_gate` = 1. Its emails then go only to
the addresses of `ea_firm_agent.recipient_allowlist`, which the practice computer copies from the console's
setting "Practice spaces may email only these addresses". Every other recipient is dropped and logged
(masked: first letter and domain). An empty list means no email at all, which is the default.

A firm's own server has no gate: nothing changes for it.
"""

import re
from email.utils import formataddr, getaddresses

HEADERS = ("To", "Cc", "Bcc", "X-Forge-To")
MAX_ADDRESSES = 50
_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,63}$")
_REPLY_TO_MAX = 254


def parse_allowlist(text):
    """The allowed addresses, lower case. Anything that is not an address is ignored."""
    found = set()
    for item in re.split(r"[\s,;]+", text or ""):
        if item and _EMAIL.match(item):
            found.add(item.lower())
    return frozenset(sorted(found)[:MAX_ADDRESSES])


def mask(address):
    """o***@example.com: enough to recognise in a log, not the whole address."""
    local, _sep, domain = (address or "").partition("@")
    return "%s***@%s" % (local[:1], domain) if domain else "***"


def filter_message(message, allowlist):
    """Keeps only allowed recipients in the message's headers. Returns (kept, dropped) addresses."""
    kept, dropped = [], []
    for header in HEADERS:
        values = message.get_all(header)
        if not values:
            continue
        pairs = getaddresses([str(value) for value in values])
        allowed = []
        for name, address in pairs:
            if not address:
                continue
            if address.lower() in allowlist:
                allowed.append((name, address))
                kept.append(address.lower())
            else:
                dropped.append(address.lower())
        del message[header]
        if allowed:
            message[header] = ", ".join(formataddr(pair) for pair in allowed)
    return sorted(set(kept)), sorted(set(dropped))


def valid_reply_to(value):
    """The console's reply address for this firm's emails: "" (none) or one address."""
    return isinstance(value, str) and (value == "" or (len(value) <= _REPLY_TO_MAX and bool(_EMAIL.match(value))))


NO_REPLY_PREFIX = "(No reply) "


def no_reply_subject(subject):
    """The subject of an email from an address that takes no replies: "(No reply) " before it, once."""
    subject = subject or ""
    if subject.lstrip().lower().startswith(NO_REPLY_PREFIX.strip().lower()):
        return subject
    return NO_REPLY_PREFIX + subject
