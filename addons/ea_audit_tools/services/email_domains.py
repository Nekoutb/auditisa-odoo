"""lib/email-domains.ts: the domains an engagement-team invitation may go to (F070).

The domain is the part after the last '@', lower-cased, and must EQUAL a listed
domain: subdomains do not match their parent. An empty list means no restriction.
"""
import re

from ._js import JS_S, js_sorted, js_trim
from .errors import EmailDomainError, ServiceError

_DOMAIN = re.compile(r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\Z")
_SEPARATORS = re.compile("[" + JS_S + ",;]+")


def parse_domain_list(raw):
    """One domain per line or separated by commas, semicolons or spaces, a leading
    "@" tolerated, into a sorted, de-duplicated, lower-case list."""
    entries = []
    for piece in _SEPARATORS.split(raw):
        entry = js_trim(piece).lower()
        if entry.startswith("@"):
            entry = entry[1:]
        if entry:
            entries.append(entry)
    for domain in entries:
        if not _DOMAIN.match(domain):
            raise ServiceError("invalid-email-domain")
    return js_sorted(set(entries))


def email_domain(email):
    """The domain of an address, lower-cased; None when there is none."""
    trimmed = js_trim(email)
    at = trimmed.rfind("@")
    if at < 1:
        return None
    return trimmed[at + 1:].lower() or None


def email_domain_allowed(email, allowed):
    """True when the address may be invited under the list (empty list: always)."""
    if not allowed:
        return True
    domain = email_domain(email)
    return domain is not None and any(d.lower() == domain for d in allowed)


def assert_email_domain_allowed(allowed, email):
    """Raises EmailDomainError when the address is outside the firm's list."""
    if not email_domain_allowed(email, allowed):
        raise EmailDomainError(allowed)
