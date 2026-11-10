#!/usr/bin/env bash
# register-release.sh: on the console server, as root.
#
#   register-release.sh DIR "label"            registers the release in DIR and loads its catalogue
#   DRY_RUN=1 register-release.sh DIR "label"  the same, then undoes everything (a rehearsal)
#
# Usually run by publish-release.sh, after the upload. The release then shows on the Status page as
# "New version ready". A commit already registered with another SHA-256 is refused: a release never changes.
set -euo pipefail
DIR=$(realpath "${1:?usage: register-release.sh DIR [label]}")
STAGE=$(mktemp -d /tmp/release-register.XXXXXX)
trap 'rm -rf "$STAGE"' EXIT
cp "$DIR"/* "$STAGE"/
chown -R odoo: "$STAGE"; chmod 700 "$STAGE"
cd /opt/odoo19
runuser -u odoo -- env HOME=/opt/odoo19 RELEASE_DIR="$STAGE" RELEASE_LABEL="${2:-}" DRY_RUN="${DRY_RUN:-}" \
  /opt/odoo19/venv/bin/python /opt/odoo19/src/odoo-bin shell -c /etc/odoo/odoo.conf -d auditisa_platform \
  --no-http --logfile= --log-level=warn < "$(dirname "$(realpath "$0")")/register-release.py"
