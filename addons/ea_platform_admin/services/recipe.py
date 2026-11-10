"""The first-boot instructions of a firm server. Pure.

The cloud-init text carries the pins and the few values the server cannot make itself. It stays at
the provider and on the server's metadata address, so it holds only what is listed in `SECRET_KEYS`;
the install script blocks the metadata address for everything but root and deletes its copy. It
never holds a database password, a master password, an admin password or a backup key: the server
generates those itself and they never leave it.
"""

import re

# Odoo and the rest of the pinned recipe live in deploy/firm/recipe.env, inside the release bundle.
USER_DATA_LIMIT_BYTES = 64 * 1024

SAFE_VALUE = re.compile(r"^[A-Za-z0-9 ._:@/+=,-]*$")

REQUIRED_KEYS = (
    "FIRM_SLUG",
    "FIRM_NAME_B64",
    "FIRM_HOST",
    "FIRM_SIZE",
    "FIRM_LANG",
    "FIRM_ADMIN_EMAIL",
    "FIRM_ALLOWED_DOMAINS",
    "RELEASE_SHA",
    "RELEASE_BUNDLE_SHA256",
    "RELEASE_BASE_URL",
    "HEARTBEAT_URL",
    "HEARTBEAT_TOKEN",
    "FIRST_ADMIN_TOKEN_SHA256",
    "SSH_ALLOWLIST",
    "S3_ENDPOINT",
    "S3_REGION",
    "S3_BUCKET",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
)

# Always written, empty when absent. The releases bucket is private: the console makes a download
# address for the bundle (base64, so that the address's characters pass the install script's check),
# valid three days. Without it (simulation, rehearsals) the server downloads from RELEASE_BASE_URL.
# Not a secret: it opens one file for a short time, and the server installs that file only if its
# SHA-256 is RELEASE_BUNDLE_SHA256, which comes from the console in this same text.
OPTIONAL_KEYS = ("RELEASE_BUNDLE_URL_B64",)
ALL_KEYS = REQUIRED_KEYS + OPTIONAL_KEYS

# The secrets in the text. A test keeps this list from growing unnoticed.
SECRET_KEYS = frozenset({"HEARTBEAT_TOKEN", "S3_ACCESS_KEY", "S3_SECRET_KEY"})

TEMPLATE = """#cloud-config
# AuditISA firm server: {slug}. See deploy/firm/install-firm-server.sh.
ssh_pwauth: false
disable_root: false
package_update: false
write_files:
  - path: /etc/auditisa-firm/bootstrap.env
    owner: root:root
    permissions: '0600'
    content: |
{env_block}
  - path: /etc/auditisa-firm/ssh_authorized_key
    owner: root:root
    permissions: '0600'
    content: |
      {ssh_public_key}
runcmd:
  - [bash, -c, "set -euo pipefail; . /etc/auditisa-firm/bootstrap.env; cd /root; bundle_url=\\"$RELEASE_BASE_URL/$RELEASE_SHA.tar.gz\\"; if [ -n \\"$RELEASE_BUNDLE_URL_B64\\" ]; then bundle_url=$(printf %s \\"$RELEASE_BUNDLE_URL_B64\\" | base64 -d); fi; curl -fsSL --retry 5 --retry-all-errors -o bundle.tar.gz \\"$bundle_url\\"; echo \\"$RELEASE_BUNDLE_SHA256  bundle.tar.gz\\" | sha256sum -c - || {{ echo 'release refused: its SHA-256 is not the one the console gave' >&2; exit 1; }}; mkdir -p /root/firm-bundle; tar -xzf bundle.tar.gz -C /root/firm-bundle; bash /root/firm-bundle/deploy/firm/install-firm-server.sh --env /etc/auditisa-firm/bootstrap.env --bundle /root/bundle.tar.gz"]
"""


def render_user_data(values, ssh_public_key):
    """The cloud-init text. Raises ValueError on a missing, unknown or unsafe value."""
    missing = [key for key in REQUIRED_KEYS if not values.get(key) and key != "FIRM_ALLOWED_DOMAINS"]
    if missing:
        raise ValueError("missing: " + ", ".join(missing))
    unknown = set(values) - set(ALL_KEYS)
    if unknown:
        raise ValueError("unknown: " + ", ".join(sorted(unknown)))
    for key in ALL_KEYS:
        if not SAFE_VALUE.match(str(values.get(key, ""))):
            raise ValueError(f"unsafe value for {key}")
    if not re.match(r"^ssh-ed25519 [A-Za-z0-9+/=]+( [A-Za-z0-9@._-]+)?$", ssh_public_key.strip()):
        raise ValueError("unsafe ssh key")
    env_block = "\n".join(f"      {key}='{values.get(key, '')}'" for key in ALL_KEYS)
    text = TEMPLATE.format(
        slug=values["FIRM_SLUG"],
        env_block=env_block,
        ssh_public_key=ssh_public_key.strip(),
    )
    if len(text.encode("utf-8")) > USER_DATA_LIMIT_BYTES:
        raise ValueError("user data too large")
    return text
