#!/usr/bin/env bash
# firm-support-visit.sh: opens or ends a support visit by the operator, on this firm's server.
#
#   firm-support-visit open <request number> <minutes> <link fingerprint (sha256)>
#   firm-support-visit end <request number>
#
# Started by firm-apply-desired with what the control plane's signed answer asked. Every value is
# checked again here: the spool file is writable by the odoo user. Nothing here holds or makes a
# password: the operator signs in with a one-time link whose fingerprint alone reaches this server,
# as the named account "auditisa-support", only while the visit is open. The firm's administrator
# sees the visit and can end it; with the firm's setting on, it waits for their approval first.
# The access log the firm reads (Settings > Operator access) records each step.

set -euo pipefail
SCRIPT_NAME=firm-support-visit
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/firm/firm-lib.sh
. "$HERE/firm-lib.sh"
load_firm_env
: "${ODOO_USER:=odoo}"

ACTION=${1:-}
REF=${2:-}
[[ $REF =~ ^[1-9][0-9]{0,8}$ ]] || fl_die "invalid request number"
case "$ACTION" in
  open)
    MINUTES=${3:-}
    HASH=${4:-}
    [[ $MINUTES =~ ^[1-9][0-9]{0,2}$ ]] && [ "$MINUTES" -le 240 ] || fl_die "invalid length"
    [[ $HASH =~ ^[0-9a-f]{64}$ ]] || fl_die "invalid fingerprint"
    CODE="env['ea.firm.support.visit']._root_request($REF, $MINUTES, '$HASH'); env.cr.commit()"
    ;;
  end)
    CODE="env['ea.firm.support.visit']._end_from_platform($REF); env.cr.commit()"
    ;;
  *) fl_die "usage: firm-support-visit open|end ..." ;;
esac

# Root's own line in the append-only file, beside the ones Odoo writes when the visit moves on.
printf '%s support-asked-%s %s \n' "$(now_utc)" "$ACTION" "$REF" >> "$BREAK_GLASS_LOG" || true
printf '%s\n' "$CODE" | runuser -u "$ODOO_USER" -- "$ODOO_PY" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$FIRM_DB" \
  --no-http --logfile=/dev/null >/dev/null 2>&1 || fl_die "Odoo did not take the request"
fl_log "support visit $REF: $ACTION done"
