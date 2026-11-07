#!/usr/bin/env bash
# firm-support-visit.sh: opens or ends a support visit by the operator, on this firm's server.
#
#   firm-support-visit open <base64 of the JSON request: id, minutes, token_sha256, operator, reason>
#   firm-support-visit end <visit number>
#
# Started by firm-apply-desired with what the control plane's signed answer asked. Every value is
# checked again here: the spool file is writable by the odoo user. Nothing here holds or makes a
# password: the operator signs in with a one-time link whose fingerprint alone reaches this server,
# as the named account "auditisa-support", only while the visit is open, and that account reads
# only. The firm's administrator is told on screen, sees the numbered record of the visit with every
# screen opened, and can end it. The server's access log (collected, no longer a screen of the
# firm's) records each step.

set -euo pipefail
SCRIPT_NAME=firm-support-visit
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/firm/firm-lib.sh
. "$HERE/firm-lib.sh"
load_firm_env
: "${ODOO_USER:=odoo}"

ACTION=${1:-}
ARG=${2:-}
case "$ACTION" in
  open)
    # Only base64 characters reach the Python below; the module decodes and checks every field.
    [[ $ARG =~ ^[A-Za-z0-9+/=]{1,2000}$ ]] || fl_die "invalid request"
    REF=$("$ODOO_PY" -I -c 'import base64, json, sys; print(int(json.loads(base64.b64decode(sys.argv[1]))["id"]))' "$ARG") || fl_die "invalid request"
    CODE="from odoo.addons.ea_audit_firm_agent.models.support import decode_request; env['ea.firm.support.visit']._root_request(*decode_request('$ARG')); env.cr.commit()"
    ;;
  end)
    [[ $ARG =~ ^[1-9][0-9]{0,8}$ ]] || fl_die "invalid visit number"
    REF=$ARG
    CODE="env['ea.firm.support.visit']._end_from_platform($REF); env.cr.commit()"
    ;;
  *) fl_die "usage: firm-support-visit open|end ..." ;;
esac

# Root's own line in the append-only file, beside the ones Odoo writes when the visit moves on.
printf '%s support-asked-%s %s \n' "$(now_utc)" "$ACTION" "$REF" >> "$BREAK_GLASS_LOG" || true
printf '%s\n' "$CODE" | runuser -u "$ODOO_USER" -- "$ODOO_PY" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$FIRM_DB" \
  --no-http --logfile=/dev/null >/dev/null 2>&1 || fl_die "Odoo did not take the request"
fl_log "support visit $REF: $ACTION done"
