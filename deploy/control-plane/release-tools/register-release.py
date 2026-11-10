# register-release.py: run inside `odoo-bin shell` on the console (see register-release.sh).
# Registers one release in Platform > Updates > Releases and loads its catalogue. It then shows on the
# Status page as "New version ready", for the owner's Promote to Staging.
# Environment: RELEASE_DIR (the folder with the files), RELEASE_LABEL, DRY_RUN=1 to undo everything at the end.
import hashlib
import os
import re
import sys

from odoo.exceptions import UserError

folder = os.environ["RELEASE_DIR"]
dry = os.environ.get("DRY_RUN") == "1"
label = os.environ.get("RELEASE_LABEL") or ""
names = [n for n in os.listdir(folder) if re.fullmatch(r"[0-9a-f]{40}\.tar\.gz", n)]
if len(names) != 1:
    sys.exit("RELEASE_DIR must hold exactly one <sha>.tar.gz")
sha = names[0][:-7]


def read(name, required=True):
    path = os.path.join(folder, name)
    if not os.path.exists(path):
        if required:
            sys.exit(f"missing: {name}")
        return None
    with open(path, "rb") as handle:
        return handle.read()


digest = hashlib.sha256(read(f"{sha}.tar.gz")).hexdigest()
catalogue = read(f"{sha}.catalogue.json")
odoo_commit = (read("odoo-commit", required=False) or b"").decode("ascii").strip()

Release = env["platform.release"].sudo()
outcome = 0
env.cr.execute("SAVEPOINT register_release")
try:
    release = Release.with_context(active_test=False).search([("sha", "=", sha)], limit=1)
    if release:
        if release.bundle_sha256 != digest:
            raise UserError(f"{sha[:12]} is already registered with another digest: a release does not change.")
        print(f"already registered: {sha[:12]}")
    else:
        values = {"sha": sha, "bundle_sha256": digest, "label": label}
        if odoo_commit:
            values["odoo_commit"] = odoo_commit
        release = Release.create(values)
        print(f"registered: {sha[:12]} digest {digest}")
    release._load_catalogue(catalogue)
    print(f"catalogue loaded; add-ons: {len(release.addon_line_ids)}")
except UserError as refused:
    env.cr.execute("ROLLBACK TO SAVEPOINT register_release")
    print(f"REFUSED by the console: {refused.args[0] if refused.args else refused}")
    outcome = 2
if dry:
    env.cr.rollback()
    print("DRY_RUN: everything undone, nothing kept")
elif outcome == 0:
    env.cr.commit()
    print("saved")
else:
    env.cr.rollback()
print(f"RESULT={outcome}")
