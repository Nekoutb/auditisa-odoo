#!/usr/bin/env bash
# set-owner.sh: makes (or updates) the owner's sign-in on the console. As root, on the console.
#
#   set-owner.sh --login EMAIL --name "NAME" [--lang en_US|fr_FR] [--tz Africa/Douala] < password-on-stdin
#
# The password is read from stdin, first line, and reaches Odoo through stdin again: it is never on a
# command line, never echoed, never written to a file or a log. The owner changes it at first sign-in
# (preferences > Account security), where two-factor sign-in is switched on too.
# Groups: Administrator (base.group_system) and Platform owner (ea_platform_admin.group_platform_owner).
# No invitation mail is sent: there is no outgoing mail server.

set -euo pipefail
umask 077
LOGIN="" NAME="" LANG_CODE=en_US TZ_NAME=Africa/Douala
while [ $# -gt 0 ]; do
  case "$1" in
    --login) LOGIN=${2:?}; shift ;;
    --name) NAME=${2:?}; shift ;;
    --lang) LANG_CODE=${2:?}; shift ;;
    --tz) TZ_NAME=${2:?}; shift ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) printf 'unknown option %s\n' "$1" >&2; exit 64 ;;
  esac
  shift
done
die() { printf 'ERROR: %s\n' "$*" >&2; exit 64; }
[ "$(id -u)" = 0 ] || die "run as root"
[[ $LOGIN =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || die "--login must be an e-mail address"
[ -n "$NAME" ] && [ ${#NAME} -le 80 ] || die "--name is required (80 characters at most)"
case "$LANG_CODE" in en_US|fr_FR) ;; *) die "--lang en_US or fr_FR" ;; esac
[[ $TZ_NAME =~ ^[A-Za-z_]+(/[A-Za-z_+-]+)*$ ]] || die "bad --tz"

IFS= read -r PASSWORD || true
[ ${#PASSWORD} -ge 8 ] || die "a password of at least 8 characters is expected on stdin"

# Everything goes to Odoo through stdin. base64 reads the password on its own stdin, not its command line.
{
  printf 'import base64\n'
  printf 'OWNER_PASSWORD = base64.b64decode("%s").decode("utf-8")\n' "$(printf '%s' "$PASSWORD" | base64 -w0)"
  cat <<'PY'
import os

Users = env["res.users"].sudo().with_context(no_reset_password=True, active_test=False)
groups_field = "group_ids" if "group_ids" in Users._fields else "groups_id"
wanted = env.ref("base.group_system") | env.ref("ea_platform_admin.group_platform_owner")
values = {
    "name": os.environ["P_NAME"],
    "email": os.environ["P_LOGIN"],
    "lang": os.environ["P_LANG"],
    "tz": os.environ["P_TZ"],
    "notification_type": "inbox",
    "active": True,
}
user = Users.search([("login", "=", os.environ["P_LOGIN"])], limit=1)
if user:
    user.write(values)
else:
    user = Users.create(dict(values, login=os.environ["P_LOGIN"]))
user.write({groups_field: [(4, group.id) for group in wanted]})
user.write({"password": OWNER_PASSWORD})
del OWNER_PASSWORD
env.cr.commit()
missing = wanted - user[groups_field]
print("SET-OWNER-RESULT", user.id, "groups-ok" if not missing else "groups-missing")
PY
} | runuser -u odoo -- env HOME=/opt/odoo19 P_LOGIN="$LOGIN" P_NAME="$NAME" P_LANG="$LANG_CODE" P_TZ="$TZ_NAME" \
    /opt/odoo19/venv/bin/python /opt/odoo19/src/odoo-bin shell -c /etc/odoo/odoo.conf -d auditisa_platform \
    --no-http --max-cron-threads=0 --workers=0 | grep '^SET-OWNER-RESULT' || die "Odoo did not confirm"
unset PASSWORD
