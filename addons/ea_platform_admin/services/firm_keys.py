"""The maintenance key the console makes for a firm when the owner supplies none. No Odoo, no network.

Owner's ruling of 2026-11-11: the owner never has to supply an SSH key. When the New firm form's key field
is left empty, the console makes a fresh ed25519 pair for that firm. The public half is registered exactly
as a pasted one is. The private half is written to one file per firm in a folder that only the console's
own system user can open (700, files 600), on the console's server. It is never put in the database, on a
screen, in a log, in a heartbeat or in an export, and the file is removed when the firm is destroyed.

So the console's server now holds the maintenance keys of the firms it made a key for: see
docs/runbook/SECURITY-MODEL.md.
"""

import os
import re
import tempfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

KEYS_DIR_PARAM = "ea_platform.firm_keys_dir"
# Inside the console service's own data folder: the only place its systemd unit lets it write
# (ProtectSystem=strict, ReadWritePaths=/var/lib/odoo). Not part of the console's backup.
KEYS_DIR_DEFAULT = "/var/lib/odoo/firm-keys"

_SLUG = re.compile(r"^[a-z][a-z0-9-]{1,30}[a-z0-9]$")


def generate(slug):
    """(private, public): a new ed25519 pair. `private` is the OpenSSH private key file's bytes; `public` the
    one line of a .pub file, with a comment that names the firm."""
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    return private, f"{public.decode('ascii')} auditisa-console-{slug}"


def key_path(folder, slug):
    """Where a firm's private half is kept. The slug is checked: it can never name another file."""
    if not _SLUG.match(slug or "") or "--" in slug:
        raise ValueError("bad slug")
    return os.path.join(folder, slug)


def store(folder, slug, private):
    """Writes the private half, readable by the console's own user only. Returns its path."""
    path = key_path(folder, slug)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    os.chmod(folder, 0o700)
    handle, tmp = tempfile.mkstemp(dir=folder, prefix=".new-")
    try:
        os.fchmod(handle, 0o600) if hasattr(os, "fchmod") else os.chmod(tmp, 0o600)
        with os.fdopen(handle, "wb") as out:
            out.write(private)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


def remove(folder, slug):
    """Erases a firm's private half. True if there was one."""
    path = key_path(folder, slug)
    try:
        os.unlink(path)
    except FileNotFoundError:
        return False
    return True
