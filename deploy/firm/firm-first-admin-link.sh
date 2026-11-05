#!/usr/bin/env bash
# firm-first-admin-link.sh: a new one-time link for the firm's first administrator.
#
#   firm-first-admin-link
#
# Only when the link from the control plane was lost or has expired. Run over SSH, after recording
# the access in the control plane. Prints the link once; the server keeps only its hash. Refused
# once the firm has an administrator who has logged in: the firm's own password reset takes over.

set -euo pipefail
SCRIPT_NAME=firm-first-admin-link
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/firm/firm-lib.sh
. "$HERE/firm-lib.sh"
load_firm_env
[ "$(id -u)" = 0 ] || fl_die "run as root"

logged_in=$(psql_q "SELECT count(*) FROM res_users_log l JOIN res_users u ON u.id = l.create_uid WHERE u.login NOT IN ('__system__', 'default')" "$FIRM_DB")
[ "$logged_in" = 0 ] || fl_die "someone has already logged in on this firm: no new link"

TOKEN=$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '=\n')
HASH=$(printf '%s' "$TOKEN" | sha256sum | cut -d' ' -f1)

cat <<'PY' | runuser -u odoo -- env P_HASH="$HASH" "$ODOO_PY" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$FIRM_DB" --no-http --max-cron-threads=0 >/dev/null
import datetime
import os

params = env["ir.config_parameter"].sudo()
params.set_param("ea_firm_agent.first_admin_hash", os.environ["P_HASH"])
expires = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) + datetime.timedelta(hours=72)
params.set_param("ea_firm_agent.first_admin_expires", expires.strftime("%Y-%m-%d %H:%M:%S"))
env.cr.commit()
PY
printf '%s first-admin-link %s -\n' "$(now_utc)" "$(id -un)" >> "$BREAK_GLASS_LOG"
printf 'https://%s/ea-firm/first-admin/%s\n' "$FIRM_HOST" "$TOKEN"
