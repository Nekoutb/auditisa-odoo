#!/usr/bin/env bash
# Rehearses the firm's side of the client add-ons with the real scripts, a real Odoo and a real
# throwaway database, as root on a machine that has both. Not part of CI: it needs root and PostgreSQL.
#
#   firm-addons-rehearsal.sh SOURCE_DIR [HEARTBEAT_URL ADMIN_TOKEN_FILE SLUG]
#
# SOURCE_DIR holds addons/ and deploy/. The database must be named ci_tenants*. What is real: the
# scripts, firm-apply-desired, firm-addons, firm-update, odoo-bin, module installs, database copies
# and renames. What is replaced, by small shims listed below: systemctl and curl for the local Odoo,
# because no service may be touched on the machine this runs on, and firm-backup, which needs
# storage. No real firm server, nginx, systemd unit, restic or provider is involved.
#
# With a heartbeat address, it also sends real signed heartbeats to a running admin Odoo and follows
# its answers all the way down.
set -euo pipefail

SOURCE=${1:?source folder}
HEARTBEAT_URL=${2:-}
TOKEN_FILE=${3:-}
SLUG=${4:-}
DB=${CI_FIRM_DB:-ci_tenants_firm}
[[ $DB == ci_tenants* ]] || { echo "refusing: $DB is not a ci_tenants database" >&2; exit 2; }
WORK=/tmp/ci_tenants_rehearsal
ROOT=$WORK/root
SAMPLE=ea_client_addon_sample
ODOO_SRC=${ODOO_SRC:-/opt/odoo19/src}
PY=${PY:-/opt/odoo19/venv/bin/python}

rm -rf "$WORK"
mkdir -p "$WORK/shims" "$WORK/log" "$WORK/spool"
passed=0
ok() { passed=$((passed + 1)); printf 'ok %s - %s\n' "$passed" "$*"; }
fail() { printf 'FAILED: %s\n' "$*" >&2; exit 1; }

cat > "$WORK/shims/systemctl" <<EOF
#!/bin/bash
echo "systemctl \$*" >> $WORK/calls.log
EOF
cat > "$WORK/shims/curl" <<EOF
#!/bin/bash
# The local checks always answer 200; a file:// download is a real curl.
for arg in "\$@"; do case "\$arg" in file://*) exec /usr/bin/curl "\$@" ;; esac; done
printf 200
EOF
chmod 755 "$WORK/shims/"*
export PATH=$WORK/shims:$PATH
export FIRM_PREFIX=$ROOT
export ODOO_PY=$PY ODOO_BIN=$ODOO_SRC/odoo-bin ODOO_LOG_DIR=$WORK/log HEALTH_ATTEMPTS=1
export ODOO_CONF=$WORK/odoo.conf

mkdir -p "$ROOT/etc/auditisa-firm/secrets" "$ROOT/var/lib/auditisa-firm/status" "$ROOT/var/lib/auditisa-firm/spool" \
  "$ROOT/var/log/auditisa-firm" "$ROOT/opt/auditisa-firm/bin" "$ROOT/opt/auditisa-odoo/releases/rel-one"
cp -r "$SOURCE/addons" "$ROOT/opt/auditisa-odoo/releases/rel-one/addons"
rm -rf "$ROOT/opt/auditisa-odoo/releases/rel-one/addons/ea_platform_admin"
ln -sfn "$ROOT/opt/auditisa-odoo/releases/rel-one" "$ROOT/opt/auditisa-odoo/current"
cp "$SOURCE/deploy/firm/"*.sh "$SOURCE/deploy/firm/recipe.env" "$ROOT/opt/auditisa-firm/bin/"
stub_backup() {
  cat > "$ROOT/opt/auditisa-firm/bin/firm-backup.sh" <<EOF
#!/bin/bash
echo "firm-backup \$*" >> $WORK/calls.log
EOF
  chmod 700 "$ROOT/opt/auditisa-firm/bin/"*.sh
}
stub_backup
BIN=$ROOT/opt/auditisa-firm/bin
cat > "$ROOT/etc/auditisa-firm/firm.env" <<EOF
FIRM_SLUG=ci-rehearsal
FIRM_HOST=ci-rehearsal.invalid
FIRM_DB=$DB
RELEASE_BASE_URL=file://$WORK/published
EOF
chown -R odoo "$WORK/log" "$WORK/spool"
chmod -R a+rX "$WORK" "$ROOT"
sed -E -e "s#^addons_path.*#addons_path = $ROOT/opt/auditisa-odoo/current/addons,$ODOO_SRC/odoo/addons#" \
  -e "s#^db_name.*#db_name = $DB#" -e "s#^dbfilter.*#dbfilter = ^$DB\$#" -e "s#^logfile.*#logfile = $WORK/log/odoo.log#" \
  -e 's#^http_port.*#http_port = 8108#' -e 's#^gevent_port.*#gevent_port = 8208#' -e 's#^max_cron_threads.*#max_cron_threads = 0#' \
  /etc/odoo/uat_copy.conf > "$ODOO_CONF"
chown odoo "$ODOO_CONF"
chmod 600 "$ODOO_CONF"

as_db() { runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -At -d "${2:-postgres}" -c "$1"; }
module_state() { as_db "SELECT state FROM ir_module_module WHERE name = '$1'" "$DB"; }
approved() { cat "$ROOT/var/lib/auditisa-firm/addons/approved.json" 2>/dev/null || true; }
refused() { cat "$ROOT/var/lib/auditisa-firm/status/addons_refused" 2>/dev/null || true; }
count_calls() { grep -c -- "$1" "$WORK/calls.log" 2>/dev/null || true; }
ask() { printf '%s' "$1" > "$ROOT/var/lib/auditisa-firm/spool/desired.json"; "$BIN/firm-apply-desired.sh" > "$WORK/last.log" 2>&1 || true; }

# Odoo shell, as the odoo user: runs the Python on stdin with `env`, and the approved list's path set.
odoo_shell() {
  { cat <<EOF
from odoo.addons.ea_audit_addons.models import addon_switch
addon_switch.APPROVED_FILE = "$ROOT/var/lib/auditisa-firm/addons/approved.json"
EOF
    cat; } | runuser -u odoo -- "$PY" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$DB" --no-http --logfile=/dev/null 2>&1 \
    | grep -E '^(RESULT|ERROR) ' || true
}

echo "== a new firm: the agent and the switches, no client add-on"
runuser -u postgres -- dropdb --if-exists "$DB"
runuser -u postgres -- createdb -O odoo "$DB"
runuser -u odoo -- "$PY" "$ODOO_BIN" -c "$ODOO_CONF" -d "$DB" -i ea_audit_firm_agent --without-demo=all --stop-after-init --no-http --logfile="$WORK/log/install.log"
[ "$(module_state ea_audit_firm_agent)" = installed ] || fail "agent not installed"
[ "$(module_state ea_audit_addons)" = installed ] || fail "the switch came with the agent"
[ "$(module_state $SAMPLE)" != installed ] || fail "the sample is installed before anyone asked"
ok "a firm that never asked has no client add-on installed"

echo "== the first request: root installs, with a backup first, and Odoo stopped"
ask "{\"addons\":[\"$SAMPLE\"],\"export_requested\":false}"
cat "$WORK/last.log"
[ "$(module_state $SAMPLE)" = installed ] || fail "first switch-on did not install"
ok "first switch-on installs the add-on"
[ "$(approved)" = "{\"on\":[\"$SAMPLE\"]}" ] || fail "approved list: $(approved)"
ok "root's approved list names it"
[ "$(sed -n 1p "$WORK/calls.log")" = "firm-backup --tag pre-addon" ] || fail "no backup first"
grep -qx "systemctl stop odoo" "$WORK/calls.log" && grep -qx "systemctl start odoo" "$WORK/calls.log" || fail "no stop or start"
ok "backup first, Odoo stopped and started"
[ -z "$(as_db "SELECT 1 FROM pg_database WHERE datname = '${DB}_preaddon'")" ] || fail "the copy was left behind"
ok "the database copy is dropped after success"

echo "== Odoo applies root's list"
result=$(odoo_shell <<'PY'
env["ea.addon.switch"]._cron_apply()
user = env["res.users"].with_context(no_reset_password=True).create({"name": "ci", "login": "ci_rehearsal", "group_ids": [(6, 0, [env.ref("base.group_user").id])]})
menu = env.ref("ea_client_addon_sample.menu_note")
print("RESULT", "on" if env["ea.addon.switch"]._is_on("ea_client_addon_sample") else "off", menu.id in env["ir.ui.menu"].with_user(user)._visible_menu_ids())
env["ea.client.sample.note"].with_user(user).create({"name": "kept across the switch"})
print("RESULT", env["ea.firm.agent"]._build_figures()["addons_on"])
env.cr.commit()
PY
)
printf '%s\n' "$result"
grep -q "RESULT on True" <<<"$result" || fail "not on or menu hidden"
grep -q "RESULT \['$SAMPLE'\]" <<<"$result" || fail "the heartbeat does not report it"
ok "on: the menu shows, a user works, the heartbeat reports the code"

BACKUPS=$(count_calls firm-backup)
echo "== off: hidden, kept"
ask '{"addons":[]}'
[ "$(approved)" = '{"on":[]}' ] || fail "approved list: $(approved)"
result=$(odoo_shell <<'PY'
from odoo.exceptions import AccessError, UserError
env["ea.addon.switch"]._cron_apply()
env.registry.clear_cache("groups")
user = env["res.users"].search([("login", "=", "ci_rehearsal")])
menu = env.ref("ea_client_addon_sample.menu_note")
print("RESULT menu", menu.id in env["ir.ui.menu"].with_user(user)._visible_menu_ids())
try:
    env["ea.client.sample.note"].with_user(user).search([])
    print("RESULT read allowed")
except AccessError:
    print("RESULT read refused")
try:
    env["ea.client.sample.note"].sudo().create({"name": "no"})
    print("RESULT superuser write allowed")
except UserError:
    print("RESULT superuser write refused")
print("RESULT figures", env["ea.firm.agent"]._build_figures()["addons_on"])
env.cr.rollback()
PY
)
printf '%s\n' "$result"
grep -q "RESULT menu False" <<<"$result" || fail "off: menu still shows"
grep -q "RESULT read refused" <<<"$result" || fail "off: a user still reads"
grep -q "RESULT superuser write refused" <<<"$result" || fail "off: code still writes"
grep -q "RESULT figures \[\]" <<<"$result" || fail "off: the heartbeat still reports it"
ok "off: menu hidden, model refused to users and to superuser code, heartbeat says off"
[ "$(module_state $SAMPLE)" = installed ] || fail "off uninstalled it"
ok "off: the module stays installed"
[ "$(as_db 'SELECT count(*) FROM ea_client_sample_note' "$DB")" = 1 ] || fail "off: the row is gone"
ok "off: the table and its row are still there"

echo "== on again: restored, no install, no outage"
ask "{\"addons\":[\"$SAMPLE\"]}"
[ "$(count_calls firm-backup)" = "$BACKUPS" ] || fail "on again ran a second install"
ok "on again installs nothing and backs up nothing"
result=$(odoo_shell <<'PY'
env["ea.addon.switch"]._cron_apply()
env.registry.clear_cache("groups")
user = env["res.users"].search([("login", "=", "ci_rehearsal")])
print("RESULT", env["ea.client.sample.note"].with_user(user).search([]).mapped("name"))
print("RESULT menu", env.ref("ea_client_addon_sample.menu_note").id in env["ir.ui.menu"].with_user(user)._visible_menu_ids())
env.cr.commit()
PY
)
printf '%s\n' "$result"
grep -q "kept across the switch" <<<"$result" || fail "on again: the row is not back"
grep -q "RESULT menu True" <<<"$result" || fail "on again: the menu is not back"
ok "on again: the same row, the same menu"

echo "== what the signed release does not offer is refused whole"
BEFORE=$(approved)
for bad in ea_audit_firm_agent ea_audit_reports base ea_platform_admin nothing_like_this; do
  ask "{\"addons\":[\"$SAMPLE\",\"$bad\"]}"
  [ "$(approved)" = "$BEFORE" ] || fail "$bad changed the list"
  [ "$(refused)" = 1 ] || fail "$bad not reported as refused: $(refused)"
done
ok "base features, the admin addon and unknown names are refused, and nothing changes"
ask '{"addons":["x;reboot"]}'
[ "$(approved)" = "$BEFORE" ] || fail "a bad shape changed the list"
grep -q "not a list of add-on codes" "$WORK/last.log" || fail "a bad shape was not refused"
ok "a name of the wrong shape never reaches firm-addons"
ask '{"addons":"everything"}'
[ "$(approved)" = "$BEFORE" ] || fail "a string changed the list"
ok "a value that is not a list is refused"
[ "$(module_state ea_platform_admin)" != installed ] || fail "the admin addon got installed"
ok "the admin addon stayed out of the firm's database"
ask "{\"export_requested\":false}"
[ "$(approved)" = "$BEFORE" ] || fail "no request changed the list"
ok "an answer with no request changes nothing"

echo "== a client add-on that fails to install: the copy comes back"
RELEASE_ADDONS=$ROOT/opt/auditisa-odoo/current/addons
mkdir -p "$RELEASE_ADDONS/ea_client_addon_broken/views"
printf '' > "$RELEASE_ADDONS/ea_client_addon_broken/__init__.py"
cat > "$RELEASE_ADDONS/ea_client_addon_broken/__manifest__.py" <<'EOF'
{"name": "Broken", "version": "19.0.1.0.0", "license": "LGPL-3", "author": "CI", "depends": ["ea_audit_addons"],
 "data": ["views/broken.xml"], "installable": True, "ea_client_addon": True}
EOF
cat > "$RELEASE_ADDONS/ea_client_addon_broken/views/broken.xml" <<'EOF'
<odoo><record id="x" model="no.such.model"><field name="name">x</field></record></odoo>
EOF
chmod -R a+rX "$RELEASE_ADDONS/ea_client_addon_broken"
as_db "UPDATE ea_client_sample_note SET name = name || ' before the failure'" "$DB" >/dev/null
ask "{\"addons\":[\"$SAMPLE\",\"ea_client_addon_broken\"]}"
cat "$WORK/last.log"
[ "$(module_state ea_client_addon_broken)" != installed ] || fail "broken add-on installed"
ok "the failed install left the add-on out"
[ "$(module_state $SAMPLE)" = installed ] || fail "the good add-on was lost"
[ "$(as_db 'SELECT count(*) FROM ea_client_sample_note' "$DB")" = 1 ] || fail "data lost"
ok "the database is back, with its add-on and its data"
[ "$(approved)" = "{\"on\":[\"$SAMPLE\"]}" ] || fail "approved list after the failure: $(approved)"
[ "$(refused)" = 1 ] || fail "failure not reported: $(refused)"
ok "the good add-on stays on and the failure is reported"
FAILED_DB=$(as_db "SELECT datname FROM pg_database WHERE datname LIKE '${DB}_failed_addon_%'")
[ -n "$FAILED_DB" ] || fail "the failed database was not kept for analysis"
ok "the failed database is kept for analysis"
runuser -u postgres -- dropdb "$FAILED_DB"
BACKUPS=$(count_calls firm-backup)
ask "{\"addons\":[\"$SAMPLE\",\"ea_client_addon_broken\"]}"
[ "$(count_calls firm-backup)" = "$BACKUPS" ] || fail "a refused add-on was tried again"
ok "a failed add-on is not tried again on this release"
ask "{\"addons\":[\"$SAMPLE\"]}"
[ "$(refused)" = 0 ] || fail "the refusal did not clear: $(refused)"
[ ! -s "$ROOT/var/lib/auditisa-firm/refused-addons" ] || fail "the refusal is still listed"
ok "switching it off clears the refusal, which is how the operator asks again"
rm -rf "$RELEASE_ADDONS/ea_client_addon_broken"

echo "== an update through firm-update.sh: dormant add-ons stay out, an installed one follows"
mkdir -p "$WORK/published" "$WORK/bundle/addons" "$WORK/bundle/deploy"
cp -r "$RELEASE_ADDONS/." "$WORK/bundle/addons/"
cp -r "$SOURCE/deploy/firm" "$WORK/bundle/deploy/firm"
mkdir -p "$WORK/bundle/addons/ea_client_addon_dormant"
printf '' > "$WORK/bundle/addons/ea_client_addon_dormant/__init__.py"
cat > "$WORK/bundle/addons/ea_client_addon_dormant/__manifest__.py" <<'EOF'
{"name": "Dormant", "version": "19.0.1.0.0", "license": "LGPL-3", "author": "CI", "depends": ["ea_audit_addons"],
 "installable": True, "ea_client_addon": True}
EOF
SHA=aaaaaaaaaaaa
tar -C "$WORK/bundle" -czf "$WORK/published/$SHA.tar.gz" addons deploy
openssl genpkey -algorithm ed25519 -out "$WORK/signing.pem" 2>/dev/null
openssl pkey -in "$WORK/signing.pem" -pubout -out "$ROOT/etc/auditisa-firm/release-signing.pub"
openssl pkeyutl -sign -inkey "$WORK/signing.pem" -rawin -in "$WORK/published/$SHA.tar.gz" -out "$WORK/published/$SHA.tar.gz.sig"
DIGEST=$(sha256sum "$WORK/published/$SHA.tar.gz" | cut -d' ' -f1)
sed -i -E "s#^addons_path.*#addons_path = $ROOT/opt/auditisa-odoo/releases/$SHA/addons,$ROOT/opt/auditisa-odoo/releases/rel-one/addons,$ODOO_SRC/odoo/addons#" "$ODOO_CONF"
"$BIN/firm-update.sh" "$SHA" "$DIGEST" > "$WORK/update.log" 2>&1 || { cat "$WORK/update.log"; fail "firm-update failed"; }
stub_backup
tail -n 1 "$WORK/update.log"
[ "$(cat "$ROOT/var/lib/auditisa-firm/status/update_state")" = ok ] || fail "update state"
[ "$(module_state ea_client_addon_dormant)" != installed ] || fail "the update installed an add-on nobody asked for"
ok "the update did not install an add-on nobody asked for"
[ "$(module_state $SAMPLE)" = installed ] || fail "the update lost the installed add-on"
grep -q "\-u .*$SAMPLE\|$SAMPLE" "$(ls -t "$WORK"/log/update-*.log | head -1)" || fail "the installed add-on was not updated"
ok "the update carried the add-on that is installed"
ask "{\"addons\":[\"$SAMPLE\",\"ea_client_addon_dormant\"]}"
[ "$(module_state ea_client_addon_dormant)" = installed ] || fail "the dormant add-on did not install on request"
ok "an add-on new in the release installs on request, once the release is signed in"
ask "{\"addons\":[\"$SAMPLE\"]}"

if [ -n "$HEARTBEAT_URL" ]; then
  echo "== all the way: real signed heartbeats to a running admin Odoo"
  chmod 750 "$WORK"
  chgrp odoo "$WORK"
  install -m 640 -o root -g odoo "$TOKEN_FILE" "$WORK/token"
  printf '%s\n' "$SHA" > "$ROOT/var/lib/auditisa-firm/status/release"
  chown odoo "$ROOT/var/lib/auditisa-firm/spool"
  beat() {
    odoo_shell <<PY
from odoo.addons.ea_audit_firm_agent.models import firm_agent
firm_agent.STATUS_DIR = "$ROOT/var/lib/auditisa-firm/status"
firm_agent.SPOOL_FILE = "$ROOT/var/lib/auditisa-firm/spool/desired.json"
env["ea.addon.switch"]._cron_apply()
env.cr.commit()
agent = env["ea.firm.agent"]
token = open("$WORK/token").read().strip()
print("RESULT sent", agent._post("$HEARTBEAT_URL", "$SLUG", token, agent._build_figures()))
print("RESULT on", agent._build_figures()["addons_on"])
env.cr.commit()
PY
  }
  beat_and_apply() {
    beat
    "$BIN/firm-apply-desired.sh" 2>&1 | sed -n '1,3p' || true
    cat "$ROOT/var/lib/auditisa-firm/spool/desired.json"; echo
    beat
  }
  beat_and_apply
  ok "the heartbeat round completed; the caller reads the admin side"
fi

echo "firm-addons-rehearsal: $passed checks passed"
