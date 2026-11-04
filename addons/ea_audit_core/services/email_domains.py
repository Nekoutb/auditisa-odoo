"""Port of the pure half of lib/email-domains.ts (F070)."""
import re

_DOMAIN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_SEPARATORS = re.compile(r"[\s,;]+")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InvalidDomainError(ValueError):
    """invalid-email-domain"""


def parse_domain_list(raw):
    """One domain per line, or separated by commas, semicolons or spaces; a
    leading "@" is tolerated. Sorted, de-duplicated, lower-case."""
    entries = [s.strip().lower().removeprefix("@") for s in _SEPARATORS.split(raw or "")]
    entries = [e for e in entries if e]
    for entry in entries:
        if not _DOMAIN.match(entry):
            raise InvalidDomainError(entry)
    return sorted(set(entries))


def email_domain(email):
    """The domain of an address, lower-cased; None when there is none."""
    email = (email or "").strip()
    at = email.rfind("@")
    if at < 1:
        return None
    return email[at + 1 :].lower() or None


def email_domain_allowed(email, allowed):
    """Exact match, ignoring case; an empty list allows every domain."""
    if not allowed:
        return True
    domain = email_domain(email)
    return domain is not None and any(d.lower() == domain for d in allowed)


def is_valid_email(email):
    return bool(_EMAIL.match(email or ""))
