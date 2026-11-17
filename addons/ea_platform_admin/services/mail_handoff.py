"""Where a firm's mail password waits on the console until the firm's server collects it. No Odoo.

The password is never written to the console's database (owner's ruling of 2026-11-17). Between the
operator's "Save and test" and the firm's next heartbeat (15 minutes at most), it waits in one file per
firm, encrypted, in a folder that only the console's own system user can open (700, files 600), like
the firms' maintenance keys (firm_keys.py). The key that opens these files is derived from the
console database's own secret, so neither the folder alone nor the database alone gives a password.

A file is erased as the heartbeat answer takes it, and in any case after a few hours (models/firm_mail.py).
A form that holds a password the operator typed but has not sent yet uses a file of its own, erased with
the form.
"""

import os
import re
import tempfile
import time

FOLDER_PARAM = "ea_platform.firm_mail_dir"
# Inside the console service's own data folder: the only place its systemd unit lets it write
# (ProtectSystem=strict, ReadWritePaths=/var/lib/odoo). Not part of the console's backup.
FOLDER_DEFAULT = "/var/lib/odoo/firm-mail"

_NAME = re.compile(r"^(firm-[a-z][a-z0-9-]{1,30}[a-z0-9]|form-[a-z][a-z-]{1,60}-[0-9]{1,12})$")


def firm_name(slug):
    return f"firm-{slug}"


def form_name(table, record_id):
    return "form-%s-%d" % (table.replace("_", "-"), record_id)


def path(folder, name):
    """The file of one firm or one form. The name is checked: it can never name another file."""
    if not _NAME.match(name or "") or "--" in name:
        raise ValueError("bad name")
    return os.path.join(folder, name)


def store(folder, name, data):
    """Writes `data` (bytes), readable by the console's own user only. Replaces an earlier file."""
    target = path(folder, name)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    os.chmod(folder, 0o700)
    handle, tmp = tempfile.mkstemp(dir=folder, prefix=".new-")
    try:
        os.fchmod(handle, 0o600) if hasattr(os, "fchmod") else os.chmod(tmp, 0o600)
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(tmp, target)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return target


def read(folder, name):
    """The file's bytes, or None when there is none."""
    try:
        with open(path(folder, name), "rb") as handle:
            return handle.read(65536)
    except FileNotFoundError:
        return None


def take(folder, name):
    """The file's bytes, and the file is erased. None when there is none."""
    data = read(folder, name)
    if data is not None:
        discard(folder, name)
    return data


def discard(folder, name):
    """Erases the file. True if there was one."""
    try:
        os.unlink(path(folder, name))
    except FileNotFoundError:
        return False
    return True


def sweep(folder, max_age_seconds, prefix="", now=None):
    """Erases every file whose name starts with `prefix` and older than `max_age_seconds`. Returns their names."""
    now = time.time() if now is None else now
    try:
        names = os.listdir(folder)
    except FileNotFoundError:
        return []
    erased = []
    for name in names:
        if not name.startswith(prefix):
            continue
        full = os.path.join(folder, name)
        try:
            if now - os.lstat(full).st_mtime > max_age_seconds:
                os.unlink(full)
                erased.append(name)
        except OSError:
            continue
    return sorted(erased)
