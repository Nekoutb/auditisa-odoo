"""The canonical form of a definition, byte for byte the one scripts/papers/platform.ts
computes: keys sorted, no whitespace, non-ASCII kept. No Odoo import."""

import hashlib
import json


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def digest(value):
    """SHA-256 of the canonical form. Identical in TypeScript and Python."""
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()
