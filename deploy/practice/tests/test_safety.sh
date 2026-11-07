#!/usr/bin/env bash
# shellcheck disable=SC2015,SC2016  # "A && ok || bad" is the point; nginx variables are literal
# The practice computer's safety rules, without a server: the name gate, the guard's verdicts, the
# scripts refusing before they touch anything, the rendered configuration, no secret printed and
# no way to load a dump. Writes under a temporary folder only; contacts nothing.
#
#   bash deploy/practice/tests/test_safety.sh
set -uo pipefail

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
PASSED=0 FAILED=0

ok() { PASSED=$((PASSED + 1)); }
bad() { printf 'FAILED: %s\n' "$*" >&2; FAILED=$((FAILED + 1)); }
expect_ok() { local name=$1; shift; if "$@" >/dev/null 2>&1; then ok; else bad "$name"; fi; }
expect_refused() { local name=$1; shift; if "$@" >/dev/null 2>&1; then bad "$name"; else ok; fi; }
has() { if grep -q -- "$2" "$1"; then ok; else bad "$1 does not have: $2"; fi; }
lacks() { if grep -q -- "$2" "$1"; then bad "$1 should not have: $2"; else ok; fi; }

echo "== the name gate"
# shellcheck source=deploy/practice/practice-lib.sh
gate() { ( PRACTICE_PREFIX=$WORK/none; . "$HERE/practice-lib.sh"; require_space_db "$1" ); }
for db in practice_demo-akwa practice_abc practice_cabinet-x2; do
  expect_ok "accepts $db" gate "$db"
done
for db in ea_audit_staging_v2 ea_audit_staging_prev ea_audit_odoo_staging uat_copy firm_cabinet_exemple postgres \
          template0 template1 tpl_practice_demo tpl_practice_demo_build upd_practice_abc practice_ practice_a \
          practice_ABC practice_www practice_tpl practice_test practice_ab_cd practice_-abc practice_abc- \
          practice_a--bc "practice_ab;drop" "practice_ab cd" "practice_ab'c" 'practice_ab"c' Practice_abc \
          xpractice_abc "practice_$(printf 'a%.0s' {1..40})"; do
  expect_refused "refuses $db" gate "$db"
done

echo "== the guard's verdicts"
judge() { PRACTICE_PREFIX=$WORK/none bash "$HERE/practice-guard.sh" judge "$@"; }
T=0123456789abcdef0123456789abcdef
U=fedcba9876543210fedcba9876543210
v() { local want=$1; shift; local got; got=$(judge "$@"); if [ "$got" = "$want" ] || { [ "$want" = finding ] && [ "$got" != ok ]; }; then ok; else bad "judge $*: got '$got', want $want"; fi; }
v ok        practice_abc 1 1 abc "$T" "$T" 0
v finding   practice_abc 1 0 abc "$T" "$T" 0      # not registered: loaded some other way
v finding   practice_abc 1 1 abc "$T" "$T" 1      # a firm's or an anonymised copy's marks
v finding   practice_abc 1 1 ""  ""   "$T" 0      # no marks at all: a dump
v finding   practice_abc 1 1 xyz "$T" "$T" 0      # another space's copy renamed
v finding   practice_abc 1 1 abc "$U" "$T" 0      # a copy of another template
v finding   practice_abc 1 1 abc ""   ""   0      # no template recorded
v finding   practice_abc 0 1 abc "$T" "$T" 1      # preview too
v finding   ea_audit_staging_v2 1 0 "" "" "" 0    # strict: any other database is a finding
v ok        ea_audit_staging_v2 0 0 "" "" "" 0    # preview: staging's own databases are not looked at
v finding   practice_ABC 0 0 "" "" "" 0           # a practice-looking name that is not valid
v finding   tpl_practice_other 0 0 "" "" "" 0
v ok        tpl_practice_demo 1 0 "" "" "" 0
v ok        upd_practice_abc 1 0 "" "" "" 0

echo "== the scripts refuse before touching anything"
STUBS=$WORK/stubs
CALLS=$WORK/calls
mkdir -p "$STUBS"
for tool in runuser psql createdb dropdb systemd-run systemctl pg_restore curl; do
  printf '#!/bin/sh\necho "%s $*" >> "%s"\nexit 1\n' "$tool" "$CALLS" > "$STUBS/$tool"
  chmod +x "$STUBS/$tool"
done
P=$WORK/root
mkdir -p "$P/etc/auditisa-practice"
sed -e "s/^PRACTICE_PREVIEW=.*//" "$HERE/sample.env" > "$P/etc/auditisa-practice/practice.env"
space() { PATH=$STUBS:$PATH PRACTICE_PREFIX=$P bash "$HERE/practice-space.sh" "$@"; }
: > "$CALLS"
expect_refused "delete of the staging database" space delete --slug ea_audit_staging_v2 --yes
expect_refused "delete of a firm database" space delete --slug firm_cabinet --yes
expect_refused "delete of the template" space delete --slug tpl_practice_demo --yes
expect_refused "reset with a path" space reset --slug ../etc
expect_refused "create of www" space create --slug www --name X --admin-login a@b.example
expect_refused "create with a quote" space create --slug "ab'c" --name X --admin-login a@b.example
expect_refused "delete without --yes" space delete --slug demo-akwa
expect_refused "add-on of the control room" space addons --slug demo-akwa --set ea_platform_admin
[ ! -s "$CALLS" ] && ok || bad "a refused command still called: $(cat "$CALLS")"
expect_refused "update from a folder outside a preview" \
  env PATH="$STUBS:$PATH" PRACTICE_PREFIX="$P" bash "$HERE/practice-update.sh" --release-dir "$WORK"

echo "== no way to load a dump"
# No practice script restores, loads or copies a database from a file or another machine.
if grep -nE 'pg_restore|pg_dump|pg_basebackup|psql[^|]* -f ' "$HERE"/*.sh "$HERE"/*.py | grep -vE '^[^:]+:[0-9]+: *#'; then
  bad "a practice script can load a database from a file"
else
  ok
fi
# A database is only ever created empty (template0) or as a copy of the demo template.
if grep -nE '(createdb|CREATE DATABASE)' "$HERE"/*.sh | grep -vE '^[^:]+:[0-9]+: *#' \
   | grep -vE -- '-T template0|-T "\$TEMPLATE_DB"|TEMPLATE \\"\$\(space_db'; then
  bad "a database is created from something other than template0 or the demo template"
else
  ok
fi

echo "== the rendered configuration (dry run)"
R=$WORK/real
bash "$HERE/install-practice-server.sh" --env "$HERE/sample.env" --dry-run --root "$R" > "$WORK/real.log" 2>&1 || bad "dry run failed: $(tail -n 3 "$WORK/real.log")"
CONF=$R/etc/odoo/practice.conf
has "$CONF" '^dbfilter = ^practice_%d\$$'
has "$CONF" '^list_db = False$'
has "$CONF" '^http_interface = 127.0.0.1$'
has "$CONF" '^smtp_server = False$'
has "$CONF" '^db_user = odoo_practice$'
has "$CONF" '^workers = 3$'
lacks "$CONF" '^db_name'
lacks "$CONF" 'ea_platform'
[ "$(stat -c %a "$CONF")" = 640 ] && ok || bad "practice.conf is not 640"
for secret in master.password db.password heartbeat.token; do
  [ "$(stat -c %a "$R/etc/auditisa-practice/secrets/$secret")" = 600 ] && ok || bad "$secret is not 600"
  if grep -qF -- "$(cat "$R/etc/auditisa-practice/secrets/$secret")" "$WORK/real.log"; then bad "$secret was printed"; else ok; fi
done
SITE=$R/etc/nginx/sites-available/practice.conf
has "$SITE" 'location ~ ^/web/database { return 404; }'
has "$SITE" 'proxy_set_header X-Odoo-Database "";'
has "$SITE" 'server_name ~^(?<practice_slug>\[a-z\]\[a-z0-9-\]{1,30}\[a-z0-9\])\\.practice\\.auditisa\\.com\$;'
has "$SITE" 'proxy_set_header Host $practice_slug.practice.auditisa.com;'
has "$SITE" 'ssl_reject_handshake on;'
[ "$(grep -c 'proxy_set_header Host ' "$SITE")" = 2 ] && ok || bad "the websocket location must repeat the Host header"
has "$WORK/real.log" 'ufw default deny outgoing'
has "$WORK/real.log" 'ufw reject out 25,465,587,2525/tcp'
lacks "$WORK/real.log" 'ufw allow out 25'
has "$WORK/real.log" 'ufw allow from 203.0.113.10/32 to any port 22'
lacks "$WORK/real.log" 'ufw allow 22'
UNIT=$R/etc/systemd/system/odoo-practice.service
has "$UNIT" '^User=odoo-practice$'
has "$UNIT" '^ExecStartPre=+/usr/local/sbin/practice-guard check$'
has "$UNIT" '^NoNewPrivileges=yes$'
has "$R/etc/systemd/system/practice-guard.timer" 'OnCalendar='
has "$R/etc/systemd/system/practice-heartbeat.timer" 'OnCalendar='
has "$R/etc/auditisa-practice/practice.env" "^PRACTICE_STRICT_CLUSTER='1'$"

echo "== the preview's configuration (dry run)"
V=$WORK/preview
bash "$HERE/install-practice-server.sh" --env "$HERE/preview-staging.env" --preview --dry-run --root "$V" > "$WORK/preview.log" 2>&1 || bad "preview dry run failed: $(tail -n 3 "$WORK/preview.log")"
expect_refused "a preview env without --preview" bash "$HERE/install-practice-server.sh" --env "$HERE/preview-staging.env" --dry-run --root "$WORK/x"
PSITE=$V/etc/nginx/sites-available/practice-preview.conf
has "$PSITE" 'listen 8443 ssl;'
has "$PSITE" 'server_name test.auditisa.com;'
has "$PSITE" 'if ($practice_gate = "") { return 403'
has "$PSITE" 'location ~ ^/web/database { return 404; }'
has "$PSITE" 'proxy_set_header Host $practice_preview_slug.practice.auditisa.com;'
has "$PSITE" 'proxy_set_header Origin $practice_ws_origin;'
has "$PSITE" 'proxy_set_header X-Odoo-Database "";'
lacks "$PSITE" 'listen 443'
lacks "$PSITE" 'uat\|manual'
has "$V/etc/odoo/practice.conf" '^workers = 0$'
has "$V/etc/odoo/practice.conf" '^http_port = 8099$'
has "$V/etc/auditisa-practice/practice.env" "^PRACTICE_STRICT_CLUSTER='0'$"
has "$WORK/preview.log" 'ufw allow 8443/tcp'
lacks "$WORK/preview.log" 'ufw --force reset'
lacks "$WORK/preview.log" 'ufw default'
lacks "$WORK/preview.log" 'apt-get'

printf '%d passed, %d failed\n' "$PASSED" "$FAILED"
[ "$FAILED" = 0 ]
