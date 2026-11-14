#!/usr/bin/env bash
# shellcheck disable=SC2015  # "A && ok || bad" is the point: ok never fails
# ci_rebuild.sh: proves staging-rebuild.sh on throwaway databases. On a server, as root.
#
#   [SOURCE_DB=name] ci_rebuild.sh DUMP TOOL_DIR
#
# DUMP is a file made by firm-anon-export. The target is ci_pipeline_stg, a copy of SOURCE_DB (default
# uat_copy, read only), in a configuration of its own, on a port of its own. The live staging is not touched.
# Leaves ci_pipeline_stg for a look through a tunnel; ci_rebuild_cleanup removes it.

set -uo pipefail
DUMP=${1:?dump}
TOOL=${2:?tool folder}
SOURCE=${SOURCE_DB:-uat_copy}
TARGET=ci_pipeline_stg
SCRIPT=$TOOL/deploy/staging/staging-rebuild.sh
WORK=$(mktemp -d /tmp/ci_pipeline_rebuild.XXXXXX)
chmod 755 "$WORK"
PASS=0 FAIL=0
ok() { PASS=$((PASS + 1)); printf 'ok    %s\n' "$*"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL  %s\n' "$*"; }
q() { runuser -u postgres -- psql -X -At -v ON_ERROR_STOP=1 -d "$1" -c "$2"; }
trap 'rm -rf "$WORK"' EXIT

ADDONS=$(sed -n 's/^addons_path *= *//p' /etc/odoo/uat_copy.conf)
# The release under test, when given: otherwise the copy's own.
ADDONS=${ADDONS_OVERRIDE:-$ADDONS}
cat > "$WORK/odoo.conf" <<EOF
[options]
db_host = False
db_user = odoo
db_name = $TARGET
dbfilter = ^$TARGET\$
list_db = False
addons_path = $ADDONS
data_dir = $WORK/data
logfile = $WORK/log/odoo.log
http_interface = 127.0.0.1
http_port = 8097
gevent_port = 8098
workers = 0
max_cron_threads = 0
limit_memory_soft = 629145600
limit_memory_hard = 943718400
smtp_server = False
EOF
grep -E '^db_password' /etc/odoo/uat_copy.conf >> "$WORK/odoo.conf"
sed -i '/^db_host = False/d' "$WORK/odoo.conf"; grep -E '^db_host' /etc/odoo/uat_copy.conf >> "$WORK/odoo.conf"; grep -E '^db_port' /etc/odoo/uat_copy.conf >> "$WORK/odoo.conf"
mkdir -p "$WORK/data/filestore" "$WORK/log"
chown -R odoo "$WORK/data" "$WORK/log"
chgrp odoo "$WORK/odoo.conf"; chmod 640 "$WORK/odoo.conf"
export ODOO_CONF=$WORK/odoo.conf BACKUP_DIR=$WORK/backups LOCK_FILE=$WORK/lock HEALTH_PORT=8097 TMPDIR=$WORK

fresh_target() {
  q postgres "DROP DATABASE IF EXISTS $TARGET WITH (FORCE)" >/dev/null 2>&1
  for old in $(q postgres "SELECT datname FROM pg_database WHERE datname LIKE '${TARGET}\_%'"); do q postgres "DROP DATABASE \"$old\" WITH (FORCE)" >/dev/null; done
  q postgres "CREATE DATABASE $TARGET OWNER odoo" >/dev/null
  runuser -u postgres -- pg_dump --format=custom --no-owner --no-acl "$SOURCE" | runuser -u postgres -- pg_restore --no-owner --role=odoo -d "$TARGET" >/dev/null 2>&1
  q "$TARGET" "UPDATE res_partner SET name = 'Marqueur avant reconstruction' WHERE id = (SELECT min(id) FROM res_partner)" >/dev/null
  # What a person enters on staging: this is what must be warned about.
  q "$TARGET" "INSERT INTO ea_audit_client (name, partner_id, legal_form, framework, create_uid, write_uid, create_date, write_date)
    SELECT 'CLIENT SAISI SARL', (SELECT min(id) FROM res_partner), legal_form, framework, 2, 2, now() at time zone 'utc', now() at time zone 'utc'
      FROM ea_audit_client LIMIT 1" >/dev/null
}
accept_count() { sed -n 's/.*--accept-loss \([0-9]*\)\..*/\1/p; s/.*--accept-loss \([0-9]*\)$/\1/p' "$1" | head -n 1; }
mark() { q "$TARGET" "SELECT count(*) FROM res_partner WHERE name = 'Marqueur avant reconstruction'"; }

DIGEST=$(sha256sum "$DUMP" | cut -d' ' -f1)
RUN() { bash "$SCRIPT" --db "$TARGET" --no-service "$@"; }

echo "== refusals"
if bash "$SCRIPT" --db ea_audit_staging_v2 --no-service --dump "$DUMP" --sha256 "$DIGEST" >/dev/null 2>&1; then bad "--no-service on the live name"; else ok "--no-service is refused on a name that is not ci_pipeline_*"; fi
if bash "$SCRIPT" --db uat_copy --dump "$DUMP" --sha256 "$DIGEST" >/dev/null 2>&1; then bad "uat_copy accepted"; else ok "uat_copy is refused"; fi
if RUN --dump "$DUMP" --sha256 "$(printf '0%.0s' {1..64})" >/dev/null 2>&1; then bad "wrong digest accepted"; else ok "a wrong digest is refused"; fi
echo nothing > "$WORK/not-a-dump.tar"
tar -cf "$WORK/other.tar" -C "$WORK" not-a-dump.tar
if RUN --dump "$WORK/other.tar" --sha256 "$(sha256sum "$WORK/other.tar" | cut -d' ' -f1)" >/dev/null 2>&1; then bad "another tar accepted"; else ok "a file with other members is refused"; fi

echo "== dry run, the default"
fresh_target
BEFORE=$(q "$TARGET" "SELECT md5(string_agg(id::text || name, ',' ORDER BY id)) FROM res_partner")
if RUN --dump "$DUMP" --sha256 "$DIGEST" > "$WORK/dry" 2>&1; then ok "the dry run passes"; else bad "the dry run failed"; cut -c1-160 "$WORK/dry"; fi
grep -q 'DRY RUN' "$WORK/dry" && ok "it says it is a dry run" || bad "no mention of a dry run"
grep -q 'CLIENT SAISI SARL' "$WORK/dry" && ok "it names the client entered on staging" || bad "the client entered on staging is not named"
grep -q 'REPLACES THESE' "$WORK/dry" && ok "it warns about what would be replaced" || bad "no warning"
grep -q 'ea_audit_staging_prev\|staging_prev' "$WORK/dry" && ok "it says the earlier deployment's database stops the next switch" || ok "no earlier deployment's database here"
LOSS=$(accept_count "$WORK/dry")
[ -n "$LOSS" ] && ok "it gives the count to accept: $LOSS" || bad "no count to accept"
if RUN --apply --dump "$DUMP" --sha256 "$DIGEST" > "$WORK/noaccept" 2>&1; then bad "--apply went through without accepting the loss"; else ok "--apply alone is refused"; fi
if RUN --apply --accept-loss 1 --dump "$DUMP" --sha256 "$DIGEST" > "$WORK/wrongaccept" 2>&1; then bad "--apply went through with the wrong count"; else ok "--apply with the wrong count is refused"; fi
[ "$(mark)" = 1 ] && ok "and staging is untouched" || bad "staging changed"
q postgres "CREATE DATABASE ${DEPLOY_NEW_DB_TEST:=ci_pipeline_fake_new}" >/dev/null
if DEPLOY_NEW_DB=$DEPLOY_NEW_DB_TEST RUN --dump "$DUMP" --sha256 "$DIGEST" > "$WORK/deploying" 2>&1; then bad "went on during a deployment"; else ok "it stops while a deployment's new database exists"; fi
q postgres "DROP DATABASE $DEPLOY_NEW_DB_TEST" >/dev/null
[ "$BEFORE" = "$(q "$TARGET" "SELECT md5(string_agg(id::text || name, ',' ORDER BY id)) FROM res_partner")" ] && ok "the dry run changes nothing" || bad "the dry run changed the database"

echo "== a copy that is not anonymised is refused, and staging stays"
FAKE=$WORK/fake; mkdir -p "$FAKE"; chmod 755 "$FAKE"
runuser -u postgres -- pg_dump --format=custom --no-owner --no-acl "$SOURCE" > "$FAKE/db.dump"
echo '{"anonymised":true,"survivors":0,"figures_unchanged":true,"files_included":false}' > "$FAKE/ANON-REPORT.json"
(cd "$FAKE" && sha256sum db.dump ANON-REPORT.json > SHA256SUMS)
tar -cf "$WORK/fake.tar" -C "$FAKE" db.dump ANON-REPORT.json SHA256SUMS
if RUN --apply --accept-loss "$LOSS" --dump "$WORK/fake.tar" --sha256 "$(sha256sum "$WORK/fake.tar" | cut -d' ' -f1)" > "$WORK/fake.out" 2>&1; then bad "a real dump with a forged report went through"; else ok "a real dump with a forged report is refused: $(grep -m1 ERROR "$WORK/fake.out" | cut -c1-90)"; fi
[ "$(mark)" = 1 ] && ok "staging is untouched" || bad "staging changed"
[ -z "$(q postgres "SELECT 1 FROM pg_database WHERE datname LIKE '${TARGET}\_new\_%'")" ] && ok "the new database is gone" || bad "the new database stayed"

echo "== a safeguard that does not hold: the copy goes, staging stays"
sed 's/^UPDATE ir_cron SET active = false;$/UPDATE ir_cron SET active = true;/' "$SCRIPT" > "$WORK/broken.sh"
if bash "$WORK/broken.sh" --db "$TARGET" --no-service --apply --accept-loss "$LOSS" --dump "$DUMP" --sha256 "$DIGEST" > "$WORK/broken.out" 2>&1; then bad "a failed safeguard went through"; else ok "$(grep -m1 ERROR "$WORK/broken.out" | cut -c1-90)"; fi
[ "$(mark)" = 1 ] && ok "staging is untouched" || bad "staging changed"
[ -z "$(q postgres "SELECT 1 FROM pg_database WHERE datname LIKE '${TARGET}\_new\_%'")" ] && ok "the new database is gone" || bad "the new database stayed"

echo "== for real, on the throwaway database"
free -m | sed -n 2p
if RUN --apply --accept-loss "$LOSS" --dump "$DUMP" --sha256 "$DIGEST" > "$WORK/apply" 2>&1; then ok "the rebuild finished"; else bad "the rebuild failed"; fi
cut -c1-150 "$WORK/apply"
[ "$(mark)" = 0 ] && ok "the database is the anonymised copy" || bad "the old database is still there"
STAMP=$(sed -n 's/.*--rollback \([0-9]\{14\}\) --apply.*/\1/p' "$WORK/apply" | tail -n 1)
expect() { [ "$(q "$TARGET" "$2")" = "$3" ] && ok "$1" || bad "$1: $(q "$TARGET" "$2")"; }
expect "crons off" "SELECT count(*) FROM ir_cron WHERE active" 0
expect "no outgoing mail server" "SELECT count(*) FROM ir_mail_server" 0
expect "no incoming mail server" "SELECT count(*) FROM fetchmail_server" 0
expect "no mail waiting" "SELECT count(*) FROM mail_mail" 0
expect "band on" "SELECT value FROM ir_config_parameter WHERE key = 'ea_audit.staging_band'" 1
expect "web.base.url" "SELECT value FROM ir_config_parameter WHERE key = 'web.base.url'" "https://test.auditisa.com"
expect "web.base.url frozen" "SELECT value FROM ir_config_parameter WHERE key = 'web.base.url.freeze'" True
expect "no heartbeat setting" "SELECT count(*) FROM ir_config_parameter WHERE key LIKE 'ea_firm_agent.%'" 0
expect "the owner's password only" "SELECT count(*) FROM res_users WHERE password IS NOT NULL AND login <> 'contact@cm-ea.com'" 0
expect "the owner's login is there" "SELECT count(*) FROM res_users WHERE login = 'contact@cm-ea.com' AND active AND password IS NOT NULL" 1
n=$(q "$TARGET" "SELECT count(*) FROM ea_audit_team_member m JOIN res_users u ON u.id = m.user_id WHERE u.login = 'contact@cm-ea.com' AND m.state = 'accepted'")
[ "$n" -gt 0 ] && ok "the owner is seated on $n engagements" || bad "the owner is on no engagement"
n=$(q "$TARGET" "SELECT count(*) FROM ea_audit_engagement")
[ "$n" -gt 0 ] && ok "$n engagements came through" || bad "no engagement"
expect "public sign-up closed" "SELECT value FROM ir_config_parameter WHERE key = 'auth_signup.invitation_scope'" b2b
expect "demo and portal logins off" "SELECT count(*) FROM res_users WHERE active AND login IN ('demo', 'portal')" 0
expect "no alias domain" "SELECT count(*) FROM mail_alias_domain" 0
expect "the client entered before is not in the copy" "SELECT count(*) FROM ea_audit_client WHERE name = 'CLIENT SAISI SARL'" 0
if grep -qiE 'password *=|admin_passwd|db_password' "$WORK/apply"; then bad "the output mentions a password"; else ok "the output holds no password"; fi
RUN --dump "$DUMP" --sha256 "$DIGEST" > "$WORK/dry2" 2>&1
grep -q 'since the last rebuild' "$WORK/dry2" && grep -q '^\[staging-rebuild\]   none' "$WORK/dry2" && ok "just after a rebuild, nothing new to warn about" || { bad "the count after a rebuild"; cut -c1-120 "$WORK/dry2" | head -n 12; }
BEFORE_DB=$(q postgres "SELECT datname FROM pg_database WHERE datname LIKE '${TARGET}\_before\_%' LIMIT 1")
[ "$(q "$BEFORE_DB" "SELECT count(*) FROM ea_audit_client WHERE name = 'CLIENT SAISI SARL'")" = 1 ] && ok "the client entered before stays in the database kept aside" || bad "kept-aside database"

echo "== rollback"
if [ -n "$STAMP" ] && RUN --rollback "$STAMP" --apply > "$WORK/rollback" 2>&1; then ok "rollback runs"; else bad "rollback"; cut -c1-150 "$WORK/rollback" 2>/dev/null; fi
[ "$(mark)" = 1 ] && ok "the old database is back" || bad "the old database is not back"
for old in $(q postgres "SELECT datname FROM pg_database WHERE datname LIKE '${TARGET}\_failed\_%'"); do
  q postgres "DROP DATABASE \"$TARGET\" WITH (FORCE)" >/dev/null
  q postgres "ALTER DATABASE \"$old\" RENAME TO \"$TARGET\"" >/dev/null
  ok "the anonymised copy stays for a look through the tunnel"
done
for old in $(q postgres "SELECT datname FROM pg_database WHERE datname LIKE '${TARGET}\_%'"); do q postgres "DROP DATABASE \"$old\" WITH (FORCE)" >/dev/null; done

printf 'TOTAL: %s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ]
