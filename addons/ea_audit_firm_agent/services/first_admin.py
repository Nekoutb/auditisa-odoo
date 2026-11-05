"""The rules of the one-time link that creates the firm's first administrator. Pure.

The server holds only the SHA-256 of the link's token, so nothing on it can rebuild the link.
"""

import hashlib
import hmac
import re

MIN_PASSWORD_LENGTH = 12
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,128}$")


def token_hash(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def token_matches(token, stored_hash):
    """Constant time. A malformed token or an empty stored hash never matches."""
    if not stored_hash or not token or not _TOKEN.match(token):
        return False
    return hmac.compare_digest(token_hash(token), stored_hash)


def is_expired(expires_at, now):
    return not expires_at or now >= expires_at


def password_problem(password, confirmation):
    """"too_short", "mismatch" or None. The controller words it in the reader's language."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return "too_short"
    if password != confirmation:
        return "mismatch"
    return None
