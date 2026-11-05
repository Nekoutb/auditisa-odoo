#!/usr/bin/env bash
# firm-status.sh: refreshes the figures only root can see: the certificate, the SSH logins.
# The agent in Odoo reads them and adds memory, disk and its counts.
#
#   firm-status

set -euo pipefail
SCRIPT_NAME=firm-status
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/firm/firm-lib.sh
. "$HERE/firm-lib.sh"
load_firm_env

CERT=/etc/letsencrypt/live/$FIRM_HOST/fullchain.pem
if [ -r "$CERT" ]; then
  end=$(openssl x509 -in "$CERT" -noout -enddate | cut -d= -f2)
  set_status cert_expires_on "$(date -u -d "$end" +%Y-%m-%d)"
else
  rm -f "$FIRM_STATUS/cert_expires_on"
fi

since=$(date -u -d '24 hours ago' +%Y-%m-%dT%H:%M:%SZ)
if [ -r "$BREAK_GLASS_LOG" ]; then
  count=$(awk -v since="$since" '$2 == "ssh-login" && $1 >= since {n++} END {print n + 0}' "$BREAK_GLASS_LOG")
  last=$(awk '$2 == "ssh-login" {t = $1} END {print t}' "$BREAK_GLASS_LOG")
  set_status ssh_sessions_24h "$count"
  if [ -n "$last" ]; then set_status last_ssh_at "$last"; fi
fi
