#!/usr/bin/env bash
# firm-add-domain.sh: adds the firm's own domain as a second name for this server.
#
#   firm-add-domain audit.cabinet.cm
#
# Once the firm's CNAME points at <slug>.auditisa.com. The platform's address keeps working.

set -euo pipefail
SCRIPT_NAME=firm-add-domain
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/firm/firm-lib.sh
. "$HERE/firm-lib.sh"
load_firm_env
[ "$(id -u)" = 0 ] || fl_die "run as root"

DOMAIN=${1:-}
[[ $DOMAIN =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$ ]] || fl_die "invalid domain '$DOMAIN'"
if grep -qxF "$DOMAIN" "$FIRM_ETC/domains"; then
  fl_log "$DOMAIN is already set"
else
  printf '%s\n' "$DOMAIN" >> "$FIRM_ETC/domains"
fi
"$BIN_DIR/firm-cert.sh"
printf '%s add-domain %s -\n' "$(now_utc)" "$(id -un)" >> "$BREAK_GLASS_LOG"
