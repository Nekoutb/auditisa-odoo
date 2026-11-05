"""The hash chain of the platform log. Pure.

Each entry's hash covers the previous entry's hash, so a change made behind the application (the
database trigger refuses one, a superuser can still try) breaks the chain from that row on.
"""

import hashlib
import json

GENESIS = "0" * 64


def entry_hash(previous, fields):
    payload = json.dumps(fields, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256((previous + "\n" + payload).encode("utf-8")).hexdigest()


def first_break(entries):
    """Index of the first entry whose hash is wrong, or None. Entries are (previous, fields, hash)."""
    expected = GENESIS
    for index, (previous, fields, value) in enumerate(entries):
        if previous != expected or entry_hash(previous, fields) != value:
            return index
        expected = value
    return None
