#!/usr/bin/env bash
# staging-rebuild.sh: rebuilds the staging database from a firm's anonymised copy. On the staging server.
#
#   staging-rebuild --dump FILE --sha256 DIGEST [--db NAME] [--apply] [--no-service]
#   staging-rebuild --rollback STAMP [--db NAME] [--apply] [--no-service]
#   staging-rebuild --help
#
#   --dump FILE       anon-<ref>.tar, made by firm-anon-export at a firm's server
#   --sha256 DIGEST   the digest the Pipeline screen shows
#   --db NAME         the database to replace (default: the db_name of /etc/odoo/odoo.conf)
#   --apply           really do it. Without it, this only checks the file and says what would happen
#   --no-service      leave the Odoo service alone: for a throwaway database only (names ci_pipeline_*)
#   --rollback STAMP  puts back the database this script kept aside as <db>_before_<STAMP>
#
# Refuses to run on a firm's server, on a file whose digest differs, on a file that holds anything but the
# three expected members or that does not read as anonymised, and on a database another agent uses.
#
# In order, and the database in service is not touched until step 6:
#   1. checks the file: digest, members, inner digests, the anonymiser's report
#   2. a backup of the current database in /var/backups/odoo/before-rebuild/
#   3. restores the copy under a new name, <db>_new_<stamp>
#   4. checks the copy is anonymised: its mark, no real email, no password
#   5. the staging safeguards, on the new database, each read back afterwards. If one does not hold, the
#      new database is dropped and nothing else has changed:
#        mail off, band on, every password reset, every cron off, web.base.url frozen,
#        no heartbeat to a control plane under a firm's name
#   6. stops Odoo, swaps the names (the old one stays as <db>_before_<stamp>, with its filestore), updates
#      the addons, re-seats the owner's login with add_contact_user.py and starts Odoo
#   7. checks Odoo answers. If not: the old database and filestore go back, and Odoo restarts on them
#
# No outside mail, no call to any firm or control plane. Prints no password, none is passed on a command line.

set -euo pipefail
umask 077
cd /

log() { printf '[staging-rebuild] %s\n' "$*"; }
warn() { printf '[staging-rebuild] WARNING: %s\n' "$*" >&2; }
die() { printf '[staging-rebuild] ERROR: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,31p' "$0"; exit 64; }

: "${ODOO_CONF:=/etc/odoo/odoo.conf}"
: "${ODOO_PY:=/opt/odoo19/venv/bin/python}"
: "${ODOO_BIN:=/opt/odoo19/src/odoo-bin}"
: "${ODOO_USER:=odoo}"
: "${SERVICE:=odoo}"
: "${HOST_URL:=https://test.auditisa.com}"
: "${CONTACT_SCRIPT:=/root/add_contact_user.py}"
: "${BACKUP_DIR:=/var/backups/odoo/before-rebuild}"
: "${HEALTH_PORT:=8069}"
: "${HEALTH_ATTEMPTS:=60}"
: "${LOCK_FILE:=/run/lock/staging-rebuild.lock}"

DUMP="" DIGEST="" DB="" APPLY=0 NO_SERVICE=0 ROLLBACK=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dump) DUMP=${2:?}; shift ;;
    --sha256) DIGEST=${2:?}; shift ;;
    --db) DB=${2:?}; shift ;;
    --apply) APPLY=1 ;;
    --no-service) NO_SERVICE=1 ;;
    --rollback) ROLLBACK=${2:?}; shift ;;
    -h|--help) usage ;;
    *) die "unknown option $1 (see --help)" ;;
  esac
  shift
done

conf_value() { sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$ODOO_CONF" | tail -n 1; }
[ -n "$DB" ] || DB=$(conf_value db_name)
[[ $DB =~ ^[a-z][a-z0-9_]{1,50}$ ]] || die "invalid database name"
case "$DB" in
  postgres|template0|template1|uat_copy) die "this database is not to be replaced: $DB" ;;
esac
if [ -e /etc/auditisa-firm/firm.env ]; then die "this is a firm's server: this script belongs on staging only"; fi
if [ "$NO_SERVICE" = 1 ] && [[ $DB != ci_pipeline_* ]]; then die "--no-service is for a throwaway database (ci_pipeline_*)"; fi
[ "$(id -u)" = 0 ] || die "run as root"

DATA_DIR=$(conf_value data_dir); DATA_DIR=${DATA_DIR:-/var/lib/odoo}
FILESTORE=$DATA_DIR/filestore
STAMP=$(date -u +%Y%m%d%H%M%S)
NEW_DB=${DB}_new_$STAMP
OLD_DB=${DB}_before_$STAMP

q() { runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -At -d "${2:-postgres}" -c "$1"; }
db_exists() { [ -n "$(q "SELECT 1 FROM pg_database WHERE datname = '$1'")" ]; }

WORK=""
cleanup_work() { if [ -n "$WORK" ]; then rm -rf "$WORK"; WORK=""; fi; }

health() {
  local i code=""
  for ((i = 1; i <= HEALTH_ATTEMPTS; i++)); do
    code=$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$HEALTH_PORT/web/health" || true)
    if [ "$code" = 200 ]; then
      code=$(curl -s --max-time 90 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$HEALTH_PORT/web/login" || true)
      [ "$code" != 200 ] || return 0
    fi
    sleep 5
  done
  warn "Odoo did not answer: last code ${code:-none}"
  return 1
}

service_stop() { [ "$NO_SERVICE" = 1 ] || systemctl stop "$SERVICE"; }
service_start() { [ "$NO_SERVICE" = 1 ] || systemctl start "$SERVICE"; }
service_healthy() { [ "$NO_SERVICE" = 1 ] || health; }

swap_back() { # stamp: the database and filestore that were kept aside become the ones in service
  local before=${DB}_before_$1 failed=${DB}_failed_$STAMP
  db_exists "$before" || die "there is no $before"
  q "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$DB', '$before') AND pid <> pg_backend_pid()" >/dev/null
  if db_exists "$DB"; then q "ALTER DATABASE \"$DB\" RENAME TO \"$failed\"" >/dev/null; fi
  q "ALTER DATABASE \"$before\" RENAME TO \"$DB\"" >/dev/null
  if [ -d "$FILESTORE/$DB" ]; then mv -T "$FILESTORE/$DB" "$FILESTORE/$failed"; fi
  if [ -d "$FILESTORE/$before" ]; then mv -T "$FILESTORE/$before" "$FILESTORE/$DB"; fi
  log "kept aside as $failed"
}

if [ -n "$ROLLBACK" ]; then
  [[ $ROLLBACK =~ ^[0-9]{14}$ ]] || die "invalid stamp"
  db_exists "${DB}_before_$ROLLBACK" || die "there is no ${DB}_before_$ROLLBACK"
  if [ "$APPLY" != 1 ]; then
    log "DRY RUN: would stop Odoo, put ${DB}_before_$ROLLBACK back as $DB, and start Odoo. Add --apply."
    exit 0
  fi
  exec 9>"$LOCK_FILE"; flock -n 9 || die "another rebuild is running"
  service_stop
  swap_back "$ROLLBACK"
  service_start
  service_healthy
  log "rolled back to the database of $ROLLBACK"
  exit 0
fi

[ -n "$DUMP" ] && [ -n "$DIGEST" ] || usage
[[ $DIGEST =~ ^[0-9a-f]{64}$ ]] || die "invalid digest"
[ -f "$DUMP" ] || die "no file at $DUMP"

# 1. The file
[ "$(sha256sum "$DUMP" | cut -d' ' -f1)" = "$DIGEST" ] || die "the file's digest is not the one on the Pipeline screen"
MEMBERS=$(tar -tf "$DUMP" | LC_ALL=C sort | tr '\n' ' ')
[ "$MEMBERS" = "ANON-REPORT.json SHA256SUMS db.dump " ] || die "unexpected members in the file: this is not an anonymised export"
WORK=$(mktemp -d "${TMPDIR:-/var/tmp}/staging-rebuild.XXXXXX")
trap cleanup_work EXIT
tar -xf "$DUMP" -C "$WORK"
(cd "$WORK" && sha256sum --status -c SHA256SUMS) || die "inner digests differ"
"$ODOO_PY" -I - "$WORK/ANON-REPORT.json" <<'PY' || die "the report does not say this copy is clean"
import json
import sys

report = json.load(open(sys.argv[1], encoding="ascii"))
if not (report.get("anonymised") is True and report.get("survivors") == 0
        and report.get("figures_unchanged") is True and report.get("files_included") is False):
    sys.exit(1)
PY
log "file checked: digest, members, inner digests, report"

if [ "$APPLY" != 1 ]; then
  log "DRY RUN: nothing has changed. With --apply:"
  log "  back up $DB to $BACKUP_DIR"
  log "  restore into $NEW_DB, check it is anonymised, apply and read back the safeguards"
  log "  stop $([ "$NO_SERVICE" = 1 ] && echo nothing || echo "$SERVICE"), rename $DB to $OLD_DB and $NEW_DB to $DB; update addons; re-seat the owner's login; start; health"
  log "  on failure: $OLD_DB goes back. Later: staging-rebuild --rollback $STAMP --apply"
  exit 0
fi

exec 9>"$LOCK_FILE"
flock -n 9 || die "another rebuild is running"
db_exists "$DB" || die "there is no database $DB to replace"

# From here on, a failure before the swap only has to remove the new database.
PHASE=restoring
on_exit() {
  local rc=$?
  trap - EXIT
  set +e
  cleanup_work
  if [ "$PHASE" = restoring ]; then
    if db_exists "$NEW_DB"; then q "DROP DATABASE \"$NEW_DB\" WITH (FORCE)" >/dev/null; fi
    [ "$rc" = 0 ] || warn "stopped before the swap: $DB is untouched and $NEW_DB is gone"
  elif [ "$PHASE" = swapped ]; then
    warn "failed after the swap: putting $OLD_DB back"
    service_stop
    if swap_back "$STAMP"; then
      service_start
      service_healthy || warn "Odoo is STILL UNHEALTHY on the old database: see the runbook"
    else
      warn "COULD NOT PUT THE OLD DATABASE BACK: check $DB and $OLD_DB by hand"
    fi
  fi
  exit "$rc"
}
trap on_exit EXIT

# 2. A backup of what is about to go
install -d -m 700 "$BACKUP_DIR"
BACKUP=$BACKUP_DIR/$DB-$STAMP.dump
runuser -u postgres -- pg_dump --format=custom --no-owner --no-acl "$DB" > "$BACKUP"
runuser -u postgres -- pg_restore --list "$BACKUP" >/dev/null < /dev/null || true
pg_restore --list "$BACKUP" >/dev/null
log "backup: $BACKUP"

# 3. Restore
chmod 755 "$WORK"; chmod 644 "$WORK/db.dump"
q "CREATE DATABASE \"$NEW_DB\" OWNER \"$ODOO_USER\" ENCODING 'UTF8' TEMPLATE template0 LC_COLLATE 'C' LC_CTYPE 'C.UTF-8'" >/dev/null
runuser -u postgres -- pg_restore --no-owner --role="$ODOO_USER" --exit-on-error -d "$NEW_DB" "$WORK/db.dump"
log "restored into $NEW_DB"

# 4. Is it really anonymised? Checked here too, whatever the firm's side said.
[ "$(q "SELECT value FROM ir_config_parameter WHERE key = 'ea_audit.anonymised'" "$NEW_DB")" = 1 ] \
  || die "this copy does not carry the anonymised mark"
n=$(q "SELECT count(*) FROM res_partner WHERE email IS NOT NULL AND email <> '' AND email NOT LIKE '%@anon.invalid'" "$NEW_DB")
[ "$n" = 0 ] || die "$n partner emails are not anonymised"
n=$(q "SELECT count(*) FROM res_users WHERE password IS NOT NULL" "$NEW_DB")
[ "$n" = 0 ] || die "$n passwords came with this copy"
n=$(q "SELECT count(*) FROM ir_attachment WHERE store_fname IS NOT NULL OR db_datas IS NOT NULL" "$NEW_DB")
[ "$n" = 0 ] || die "$n files came with this copy"
log "the copy reads as anonymised"

# 5. The safeguards
SAFEGUARDS=$(cat <<'SQL'
UPDATE ir_cron SET active = false;
DELETE FROM ir_mail_server;
DELETE FROM fetchmail_server;
DELETE FROM mail_mail;
INSERT INTO ir_config_parameter (key, value) VALUES
    ('ea_audit.staging_band', '1'),
    ('web.base.url', :'base_url'),
    ('web.base.url.freeze', 'True'),
    ('database.secret', :'secret'),
    ('database.uuid', :'uuid')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
DELETE FROM ir_config_parameter WHERE key IN ('mail.catchall.domain', 'mail.catchall.alias', 'mail.bounce.alias', 'mail.default.from', 'ea_firm_agent.heartbeat_url', 'ea_firm_agent.slug', 'ea_firm_agent.mail_tested');
DELETE FROM auth_totp_device;
DELETE FROM res_users_apikeys;
UPDATE res_users SET password = NULL, totp_secret = NULL;
SQL
)
printf '%s\n' "$SAFEGUARDS" | runuser -u postgres -- psql -X -q -v ON_ERROR_STOP=1 -d "$NEW_DB" \
  -v base_url="$HOST_URL" -v secret="$(openssl rand -hex 32)" -v uuid="$(cat /proc/sys/kernel/random/uuid)"

verify_safeguards() { # database: every safeguard read back. Exits on the first that does not hold.
  local db=$1 n
  n=$(q "SELECT count(*) FROM ir_cron WHERE active" "$db"); [ "$n" = 0 ] || die "safeguard: $n crons are on"
  n=$(q "SELECT count(*) FROM ir_mail_server" "$db"); [ "$n" = 0 ] || die "safeguard: $n outgoing mail servers"
  n=$(q "SELECT count(*) FROM fetchmail_server" "$db"); [ "$n" = 0 ] || die "safeguard: $n incoming mail servers"
  n=$(q "SELECT count(*) FROM mail_mail" "$db"); [ "$n" = 0 ] || die "safeguard: $n mails waiting"
  [ "$(q "SELECT value FROM ir_config_parameter WHERE key = 'ea_audit.staging_band'" "$db")" = 1 ] || die "safeguard: the band is not on"
  [ "$(q "SELECT value FROM ir_config_parameter WHERE key = 'web.base.url'" "$db")" = "$HOST_URL" ] || die "safeguard: web.base.url"
  [ "$(q "SELECT value FROM ir_config_parameter WHERE key = 'web.base.url.freeze'" "$db")" = True ] || die "safeguard: web.base.url is not frozen"
  n=$(q "SELECT count(*) FROM ir_config_parameter WHERE key IN ('ea_firm_agent.heartbeat_url', 'ea_firm_agent.slug')" "$db"); [ "$n" = 0 ] || die "safeguard: a heartbeat setting remains"
  n=$(q "SELECT count(*) FROM auth_totp_device" "$db"); [ "$n" = 0 ] || die "safeguard: a two-factor device remains"
  n=$(q "SELECT count(*) FROM res_users_apikeys" "$db"); [ "$n" = 0 ] || die "safeguard: an API key remains"
}
verify_safeguards "$NEW_DB"
n=$(q "SELECT count(*) FROM res_users WHERE password IS NOT NULL" "$NEW_DB"); [ "$n" = 0 ] || die "safeguard: a password remains"
smtp=$(conf_value smtp_server)
case "$smtp" in ""|False|false) ;; *) die "safeguard: this server's Odoo configuration has an outgoing mail server" ;; esac
log "safeguards applied and read back"

# 6. The swap
service_stop
PHASE=swapped
q "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$DB', '$NEW_DB') AND pid <> pg_backend_pid()" >/dev/null
q "ALTER DATABASE \"$DB\" RENAME TO \"$OLD_DB\"" >/dev/null
q "ALTER DATABASE \"$NEW_DB\" RENAME TO \"$DB\"" >/dev/null
if [ -d "$FILESTORE/$DB" ]; then mv -T "$FILESTORE/$DB" "$FILESTORE/$OLD_DB"; fi
install -d -o "$ODOO_USER" -m 750 "$FILESTORE/$DB"
log "swapped: $DB is the anonymised copy; the old one is $OLD_DB"

MODULES=$(q "SELECT string_agg(name, ',') FROM ir_module_module WHERE state = 'installed' AND name LIKE 'ea\\_audit%'" "$DB")
ULOG=$(dirname "$(conf_value logfile)")/rebuild-$STAMP.log
runuser -u "$ODOO_USER" -- "$ODOO_PY" "$ODOO_BIN" -c "$ODOO_CONF" -d "$DB" -u "$MODULES" \
  --no-http --max-cron-threads=0 --workers=0 --stop-after-init --logfile="$ULOG" 9>&- \
  || die "the addons did not update on the copy, see $ULOG"
if grep -qE ' (ERROR|CRITICAL) ' "$ULOG"; then die "the addon update logged errors, see $ULOG"; fi
# The update re-reads module data: the safeguards are read again.
verify_safeguards "$DB"
log "addons updated: safeguards still hold"

# Every password has been reset to nothing, so nobody signs in until this is done. Its own output only
# gives ids and counts; RESULT lines prove it ran.
[ -r "$CONTACT_SCRIPT" ] || die "$CONTACT_SCRIPT is missing"
SEATED=$(runuser -u "$ODOO_USER" -- "$ODOO_PY" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$DB" --no-http --logfile=/dev/null 9>&- \
  < <(cat "$CONTACT_SCRIPT") 2>/dev/null | grep '^RESULT' || true)
printf '%s\n' "$SEATED" | grep -E '^RESULT visible [1-9]' >/dev/null || die "the owner's login was not re-seated on any engagement"
log "owner's login re-seated: $(printf '%s' "$SEATED" | tr '\n' ' ' | cut -c1-120)"
verify_safeguards "$DB"
n=$(q "SELECT count(*) FROM res_users WHERE password IS NOT NULL AND login <> 'contact@cm-ea.com'" "$DB")
[ "$n" = 0 ] || die "safeguard: $n passwords other than the owner's"

# 7. Start
service_start
service_healthy
PHASE=done
log "done. To go back: staging-rebuild --db $DB --rollback $STAMP --apply"
log "kept aside: $OLD_DB, $FILESTORE/$OLD_DB, $BACKUP. Remove them yourself when you no longer need them."
