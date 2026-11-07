#!/usr/bin/env bash
# firm-mail-server.sh: sets this firm's outgoing mail server. An onboarding step, run by root.
#
#   firm-mail-server [--dry-run] [FILE]
#
# FILE (default /etc/auditisa-firm/secrets/mail.env) is written at onboarding, root:root, chmod 600:
# MAIL_HOST, MAIL_PORT, MAIL_ENCRYPTION (starttls or ssl), MAIL_USER, MAIL_PASSWORD, MAIL_FROM, one
# KEY=value per line (see firm_mail.py). It is read, never sourced.
#
# No firm user reaches the mail server from a screen, the firm administrator included (owner,
# 2026-11-07): this script is the only way in. It saves the server switched off, tests the
# connection (Odoo's own test, which sends no message), and switches sending on only if the test
# passed. The password goes to Odoo inside its input, never on a command line, in the environment or
# in the output. A test environment (staging) saves nothing and never sends: refused here, and by Odoo.
#
# Run it again after changing the file: the new settings are tested again before anything is sent.

set -euo pipefail
SCRIPT_NAME=firm-mail-server
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/firm/firm-lib.sh
. "$HERE/firm-lib.sh"
: "${ODOO_USER:=odoo}"

DRY_RUN=0
FILE=
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -*) fl_die "usage: firm-mail-server [--dry-run] [FILE]" ;;
    *) [ -z "$FILE" ] || fl_die "one file only"; FILE=$arg ;;
  esac
done
: "${FILE:=$FIRM_SECRETS/mail.env}"
load_firm_env
[ "$DRY_RUN" = 1 ] || [ "$(id -u)" = 0 ] || fl_die "run as root"

# The file's checks and its reading, in plain Python with no Odoo (firm_mail.py).
SUMMARY=$("$ODOO_PY" -I "$HERE/firm_mail.py" check "$FILE") || fl_die "the mail file was refused (see above)"

if [ "$DRY_RUN" = 1 ]; then
  fl_log "DRY RUN: would set the outgoing mail server of $FIRM_DB to $SUMMARY, test it, and switch sending on if the test passes"
  exit 0
fi

staging=$(psql_q "SELECT value FROM ir_config_parameter WHERE key = 'ea_audit.staging_band'" "$FIRM_DB")
case "$staging" in
  1|True|true) fl_die "$FIRM_DB is a test environment: it never sends email" ;;
esac

PAYLOAD=$("$ODOO_PY" -I "$HERE/firm_mail.py" payload "$FILE") || fl_die "the mail file was refused"
[[ $PAYLOAD =~ ^[A-Za-z0-9+/=]+$ ]] || fl_die "unexpected settings"

printf '%s mail-server-set %s -\n' "$(now_utc)" "$(id -un)" >> "$BREAK_GLASS_LOG" || true
OUT=$(
  {
    printf 'import base64, json\n'
    printf 'settings = json.loads(base64.b64decode("%s"))\n' "$PAYLOAD"
    printf 'result = env["ea.audit.firm.admin"]._ea_fm_root_configure(settings)\n'
    printf 'env.cr.commit()\n'
    printf 'state = result["state"]\n'
    printf 'print("EA_MAIL_RESULT " + json.dumps({"ok": result["ok"], "state": state["state"], "message": result["message"][:300]}))\n'
  } | runuser -u "$ODOO_USER" -- "$ODOO_PY" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$FIRM_DB" \
      --no-http --max-cron-threads=0 --logfile=/dev/null 2>/dev/null
) || fl_die "Odoo did not take the settings"
unset PAYLOAD

RESULT=$(printf '%s\n' "$OUT" | sed -n 's/^EA_MAIL_RESULT //p' | tail -n 1)
[ -n "$RESULT" ] || fl_die "Odoo did not answer"
STATE=$("$ODOO_PY" -I -c 'import json, sys; print(json.loads(sys.argv[1])["state"])' "$RESULT")
MESSAGE=$("$ODOO_PY" -I -c 'import json, sys; print(json.loads(sys.argv[1])["message"])' "$RESULT")
if [ "$STATE" = on ]; then
  fl_log "outgoing mail set to $SUMMARY: test passed, sending is on"
else
  fl_die "outgoing mail saved ($SUMMARY), sending stays off: $MESSAGE"
fi
