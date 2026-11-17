#!/usr/bin/env bash
# firm-mail-server.sh: sets this firm's outgoing mail server. Run by root.
#
#   firm-mail-server [--dry-run] [FILE]
#   firm-mail-server --request SPOOL     what the console's "Email for this firm" screen asked
#   firm-mail-server --off               switches sending off
#
# FILE (default /etc/auditisa-firm/secrets/mail.env) is root:root, chmod 600: MAIL_HOST, MAIL_PORT,
# MAIL_ENCRYPTION (starttls or ssl), MAIL_USER, MAIL_PASSWORD, MAIL_FROM, one KEY=value per line
# (see firm_mail.py). It is read, never sourced.
#
# Since 2026-11-17 (owner's ruling) the operator enters the settings on the console, on the firm's
# page. The console's signed heartbeat answer carries them once; the agent leaves them in the spool
# folder; firm-apply-desired runs this script with --request, which checks them again, writes FILE,
# erases the spool file and goes on as below. The result goes back to the console as a code in the
# next heartbeat (status files mail_request_ref and mail_request_result), never as text.
#
# No firm user reaches the mail server from a screen, the firm administrator included (owner,
# 2026-11-07). This script saves the server switched off, tests the connection (Odoo's own test,
# which sends no message), and switches sending on only if the test passed. The password goes to
# Odoo inside its input, never on a command line, in the environment or in the output. A test
# environment (staging) saves nothing and never sends: refused here, and by Odoo.
#
# Run it again after changing the file: the new settings are tested again before anything is sent.

set -euo pipefail
SCRIPT_NAME=firm-mail-server
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/firm/firm-lib.sh
. "$HERE/firm-lib.sh"
: "${ODOO_USER:=odoo}"

USAGE="usage: firm-mail-server [--dry-run] [FILE] | --request SPOOL | --off"
DRY_RUN=0
FILE=
REQUEST=
OFF=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --off) OFF=1; shift ;;
    --request) [ $# -ge 2 ] || fl_die "$USAGE"; REQUEST=$2; shift 2 ;;
    -*) fl_die "$USAGE" ;;
    *) [ -z "$FILE" ] || fl_die "one file only"; FILE=$1; shift ;;
  esac
done
: "${FILE:=$FIRM_SECRETS/mail.env}"
load_firm_env
[ "$DRY_RUN" = 1 ] || [ "$(id -u)" = 0 ] || fl_die "run as root"
if [ -n "$REQUEST" ] && { [ "$DRY_RUN" = 1 ] || [ "$OFF" = 1 ]; }; then fl_die "$USAGE"; fi

# What the console is told, when the console asked: a reference and one word.
REF=
report() {
  [ -n "$REF" ] || return 0
  set_status mail_request_result "$1"
  set_status mail_request_ref "$REF"  # last: the console only reads a result under its own reference
}
stop() { report "$1"; fl_die "$2"; }

odoo_shell() {
  runuser -u "$ODOO_USER" -- "$ODOO_PY" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$FIRM_DB" \
    --no-http --max-cron-threads=0 --logfile=/dev/null 2>/dev/null
}

switch_off() {
  printf '%s mail-server-off %s -\n' "$(now_utc)" "$(id -un)" >> "$BREAK_GLASS_LOG" || true
  printf 'env["ea.audit.firm.admin"]._ea_fm_root_disable()\nenv.cr.commit()\nprint("EA_MAIL_OFF")\n' \
    | odoo_shell | grep -x EA_MAIL_OFF >/dev/null || stop failed "Odoo did not switch sending off"
  report off
  fl_log "outgoing mail: sending is off"
  exit 0
}

if [ -n "$REQUEST" ]; then
  # firm_mail.py checks the request with the same rules as a file written by hand, erases the
  # spool file whatever it holds, and writes FILE (chmod 600) only for a good request.
  line=$(umask 077; "$ODOO_PY" -I "$HERE/firm_mail.py" request "$REQUEST" "$FILE") || fl_die "the console's request cannot be read"
  read -r REF ACTION <<<"$line"
  [[ $REF =~ ^[0-9a-f]{16}$ ]] || { REF=; fl_die "the console's request has no valid reference"; }
  case "$ACTION" in
    off) switch_off ;;
    set) ;;
    *) stop refused "the console's request was refused (see above)" ;;
  esac
elif [ "$OFF" = 1 ]; then
  [ "$DRY_RUN" = 0 ] || { fl_log "DRY RUN: would switch sending off"; exit 0; }
  switch_off
fi

# The file's checks and its reading, in plain Python with no Odoo (firm_mail.py).
SUMMARY=$("$ODOO_PY" -I "$HERE/firm_mail.py" check "$FILE") || stop refused "the mail file was refused (see above)"

if [ "$DRY_RUN" = 1 ]; then
  fl_log "DRY RUN: would set the outgoing mail server of $FIRM_DB to $SUMMARY, test it, and switch sending on if the test passes"
  exit 0
fi

staging=$(psql_q "SELECT value FROM ir_config_parameter WHERE key = 'ea_audit.staging_band'" "$FIRM_DB")
case "$staging" in
  1|True|true) stop staging "$FIRM_DB is a test environment: it never sends email" ;;
esac

PAYLOAD=$("$ODOO_PY" -I "$HERE/firm_mail.py" payload "$FILE") || stop refused "the mail file was refused"
[[ $PAYLOAD =~ ^[A-Za-z0-9+/=]+$ ]] || stop refused "unexpected settings"

printf '%s mail-server-set %s -\n' "$(now_utc)" "$(id -un)" >> "$BREAK_GLASS_LOG" || true
OUT=$(
  {
    printf 'import base64, json\n'
    printf 'settings = json.loads(base64.b64decode("%s"))\n' "$PAYLOAD"
    printf 'result = env["ea.audit.firm.admin"]._ea_fm_root_configure(settings)\n'
    printf 'env.cr.commit()\n'
    printf 'state = result["state"]\n'
    printf 'print("EA_MAIL_RESULT " + json.dumps({"ok": result["ok"], "state": state["state"], "kind": result.get("kind", ""), "message": result["message"][:300]}))\n'
  } | odoo_shell
) || stop failed "Odoo did not take the settings"
unset PAYLOAD

RESULT=$(printf '%s\n' "$OUT" | sed -n 's/^EA_MAIL_RESULT //p' | tail -n 1)
[ -n "$RESULT" ] || stop failed "Odoo did not answer"
read_result() { "$ODOO_PY" -I -c 'import json, sys; print(json.loads(sys.argv[1]).get(sys.argv[2]) or "")' "$RESULT" "$1"; }
STATE=$(read_result state)
MESSAGE=$(read_result message)
KIND=$(read_result kind)
case "$KIND" in login|connect|tls|sender) ;; *) KIND=failed ;; esac
if [ "$STATE" = on ]; then
  report on
  fl_log "outgoing mail set to $SUMMARY: test passed, sending is on"
else
  stop "$KIND" "outgoing mail saved ($SUMMARY), sending stays off: $MESSAGE"
fi
