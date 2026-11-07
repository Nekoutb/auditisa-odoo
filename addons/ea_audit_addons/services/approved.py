"""Reading the list of add-ons that root approved. Pure.

deploy/firm/firm-addons.sh writes it after checking the request against the signed release. The
file is root's and only readable here, and it is still read with care. No file means no request,
so a database not built for a firm's server keeps its state. Anything malformed changes nothing.
"""

import json
import re

CODE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
MAX_CODES = 24


def parse_approved(text):
    """The approved codes as a sorted list, or None if this is not a valid list."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    codes = data.get("on") if isinstance(data, dict) else None
    if not isinstance(codes, list) or len(codes) > MAX_CODES:
        return None
    if not all(isinstance(code, str) and CODE.match(code) for code in codes):
        return None
    return sorted(set(codes))


def read_approved(path):
    try:
        with open(path, encoding="ascii") as handle:
            return parse_approved(handle.read(4096))
    except (OSError, UnicodeDecodeError):
        return None
