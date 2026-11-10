#!/usr/bin/env bash
# Rehearses the firm's side of the client add-ons with the real scripts, a real Odoo and a real
# throwaway database, as root on a machine that has both. Not part of CI: it needs root and PostgreSQL.
#
#   firm-addons-rehearsal.sh SOURCE_DIR
#
# SOURCE_DIR holds addons/ and deploy/. The database must be named ci_tenants*. What is real: the
# scripts, firm-apply-desired, firm-addons, firm-update, odoo-bin, module installs, database copies
# and renames. What is replaced, by small shims listed below: systemctl and curl for the local Odoo,
# because no service may be touched on the machine this runs on, and firm-backup, which needs
# storage. No real firm server, nginx, systemd unit, restic or provider is involved.
set -euo pipefail

SOURCE=${1:?source folder}
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
# A release holds base addons too, so a request can name one. The test never installs those.
mkdir -p "$ROOT/opt/auditisa-odoo/releases/rel-one/addons"
for addon in ea_audit_addons ea_audit_firm_agent ea_client_addon_sample ea_audit_reports; do
  cp -r "$SOURCE/addons/$addon" "$ROOT/opt/auditisa-odoo/releases/rel-one/addons/"
done
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
    cat; } | runuser -u odoo -- "$PY" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$DB" --no-http --logfile=/dev/null > "$WORK/shell.log" 2>&1 || true
  grep -E '^(RESULT|ERROR) ' "$WORK/shell.log" || { tail -n 20 "$WORK/shell.log"; true; }
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

echo "== what the release in use does not offer is refused whole"
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
for addon in ea_audit_addons ea_audit_firm_agent ea_client_addon_sample; do
  cp -r "$SOURCE/addons/$addon" "$WORK/bundle/addons/"
done
sed -i 's/"version": "19.0.1.0.0"/"version": "19.0.1.0.1"/' "$WORK/bundle/addons/$SAMPLE/__manifest__.py"
cp -r "$SOURCE/deploy/firm" "$WORK/bundle/deploy/firm"
mkdir -p "$WORK/bundle/addons/ea_client_addon_dormant"
printf '' > "$WORK/bundle/addons/ea_client_addon_dormant/__init__.py"
cat > "$WORK/bundle/addons/ea_client_addon_dormant/__manifest__.py" <<'EOF'
{"name": "Dormant", "version": "19.0.1.0.0", "license": "LGPL-3", "author": "CI", "depends": ["ea_audit_addons"],
 "installable": True, "ea_client_addon": True}
EOF
SHA=aaaaaaaaaaaa
tar -C "$WORK/bundle" -czf "$WORK/published/$SHA.tar.gz" addons deploy
DIGEST=$(sha256sum "$WORK/published/$SHA.tar.gz" | cut -d' ' -f1)
# A SHA-256 that is not the bundle's: refused before anything changes, with no signature involved.
if "$BIN/firm-update.sh" "$SHA" "$(printf 'b%.0s' {1..64})" > "$WORK/refused.log" 2>&1; then
  cat "$WORK/refused.log"; fail "firm-update took a bundle whose SHA-256 is not the console's"
fi
grep -q "bundle refused" "$WORK/refused.log" || { cat "$WORK/refused.log"; fail "the refusal does not say why"; }
[ "$(cat "$ROOT/var/lib/auditisa-firm/status/update_state")" = rolled_back ] || fail "update state after a refused bundle"
[ "$(module_state $SAMPLE)" = installed ] || fail "a refused bundle changed the firm"
ok "a bundle whose SHA-256 is not the console's is refused, and nothing changes"
"$BIN/firm-update.sh" "$SHA" "$DIGEST" > "$WORK/update.log" 2>&1 || { cat "$WORK/update.log"; fail "firm-update failed"; }
stub_backup
tail -n 1 "$WORK/update.log"
[ "$(cat "$ROOT/var/lib/auditisa-firm/status/update_state")" = ok ] || fail "update state"
[ "$(module_state ea_client_addon_dormant)" != installed ] || fail "the update installed an add-on nobody asked for"
ok "the update did not install an add-on nobody asked for"
[ "$(module_state $SAMPLE)" = installed ] || fail "the update lost the installed add-on"
[ "$(as_db "SELECT latest_version FROM ir_module_module WHERE name = '$SAMPLE'" "$DB")" = 19.0.1.0.1 ] || fail "the installed add-on was not updated"
ok "the update carried the add-on that is installed"
[ "$(as_db 'SELECT count(*) FROM ea_client_sample_note' "$DB")" = 1 ] || fail "the update lost data"
ok "its data came through the update"
ask "{\"addons\":[\"$SAMPLE\",\"ea_client_addon_dormant\"]}"
[ "$(module_state ea_client_addon_dormant)" = installed ] || fail "the dormant add-on did not install on request"
ok "an add-on new in the release installs on request, once the release is in"
ask "{\"addons\":[\"$SAMPLE\"]}"


echo "== a support visit, from the spool to the named read-only account, through root's script"
HASH=$(printf 'rehearsal-link-token-000000000000000000000' | sha256sum | cut -d' ' -f1)
ask "{\"support_visit\":{\"id\":41,\"minutes\":30,\"token_sha256\":\"$HASH\",\"operator\":\"Rehearsal Operator\",\"reason\":\"Check the lead schedule'); import os; ('\"}}"
cat "$WORK/last.log"
[ "$(as_db "SELECT state FROM ea_firm_support_visit WHERE platform_ref = 41" "$DB")" = open ] || fail "the visit did not open"
ok "root's script opened the visit asked in the authenticated answer"
[ "$(as_db "SELECT reason FROM ea_firm_support_visit WHERE platform_ref = 41" "$DB")" = "Check the lead schedule'); import os; ('" ] || fail "the reason was not kept as text"
ok "the reason stays text: nothing in it runs"
[ "$(as_db "SELECT active FROM res_users WHERE login = 'auditisa-support'" "$DB")" = t ] || fail "the support account is not on"
ok "the named support account is on"
grep -q "support-asked-open" "$ROOT/var/log/auditisa-firm/break-glass.log" || fail "root wrote nothing in the access log"
[ "$(as_db "SELECT count(*) FROM ea_firm_access_log WHERE event = 'support-visit-open'" "$DB")" = 1 ] || fail "Odoo's access log has no entry"
ok "the visit is in the firm's access log"
result=$(odoo_shell <<'PY'
from odoo.exceptions import AccessError
support = env["res.users"].search([("login", "=", "auditisa-support")])
senv = env(user=support)
partner = env["res.partner"].sudo().search([], limit=1)
senv["res.partner"].browse(partner.id).web_read({"name": {}})
try:
    senv["res.partner"].sudo().browse(partner.id).write({"name": "changed"})
    print("RESULT write allowed")
except AccessError:
    print("RESULT write refused")
visit = env["ea.firm.support.visit"].search([("platform_ref", "=", 41)])
print("RESULT trace", visit.trace_ids.mapped("model"))
env.cr.rollback()
PY
)
printf '%s\n' "$result"
grep -q "RESULT write refused" <<<"$result" || fail "the support account could write"
grep -q "RESULT trace \['res.partner'\]" <<<"$result" || fail "the screen opened was not traced"
ok "the support account reads, cannot write, and what it opens is traced"
ask '{"support_visit":{"id":42,"minutes":999,"token_sha256":"00","operator":"x","reason":"y"}}'
[ -z "$(as_db "SELECT 1 FROM ea_firm_support_visit WHERE platform_ref = 42" "$DB")" ] || fail "a malformed visit was opened"
ok "a malformed visit request opens nothing"
ask '{"support_visit_end":41}'
[ "$(as_db "SELECT state FROM ea_firm_support_visit WHERE platform_ref = 41" "$DB")" = ended ] || fail "the visit did not end"
[ "$(as_db "SELECT active FROM res_users WHERE login = 'auditisa-support'" "$DB")" = f ] || fail "the support account is still on"
ok "the platform ends the visit and the account goes off"

echo "firm-addons-rehearsal: $passed checks passed. The folder $WORK stays for the caller, with the database."
