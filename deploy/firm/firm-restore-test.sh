#!/usr/bin/env bash
# firm-restore-test.sh: proves the last backup can be restored. Scheduled weekly.
#
#   firm-restore-test [--dry-run]
#
# Fetches the latest backup from the firm's storage into a temporary folder, checks its digests,
# restores the database under a temporary name, checks the rows that matter and the filestore,
# then removes it all. The firm's live database is not touched. The result is reported: a test that
# fails, or that does not run, turns the firm red on the control plane.

set -euo pipefail
umask 077
SCRIPT_NAME=firm-restore-test
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/firm/firm-lib.sh
. "$HERE/firm-lib.sh"
load_firm_env

TEST_DB=restore_test_${FIRM_DB}
if [ "${1:-}" = "--dry-run" ]; then
  fl_log "DRY RUN: nothing is changed"
  fl_log "restic restore latest -> temporary folder; sha256sum -c; pg_restore into $TEST_DB; checks; drop"
  exit 0
fi

[ "$(id -u)" = 0 ] || fl_die "run as root"
exec 9>/run/lock/firm-backup.lock
flock -w 3600 9 || fl_die "a backup is running"
WORK=$(mktemp -d /var/tmp/firm-restore.XXXXXX)

cleanup() {
  local rc=$?
  trap - EXIT
  set +e
  psql_q "DROP DATABASE IF EXISTS \"$TEST_DB\"" >/dev/null
  rm -rf "$WORK"
  set_status last_restore_test_at "$(now_utc)"
  if [ "$rc" = 0 ]; then
    set_status last_restore_test_ok 1
    fl_log "restore test passed"
  else
    set_status last_restore_test_ok 0
    fl_warn "restore test FAILED (exit $rc)"
  fi
  exit "$rc"
}
trap cleanup EXIT

load_backup_env
restic restore latest --quiet --tag nightly --host "$FIRM_SLUG" --target "$WORK"
dump=$(find "$WORK" -type f -name db.dump | head -n 1)
[ -n "$dump" ] || fl_die "the backup holds no database dump"
folder=$(dirname "$dump")
(cd "$folder" && sha256sum --status -c SHA256SUMS) || fl_die "digests of the restored files differ"

psql_q "DROP DATABASE IF EXISTS \"$TEST_DB\"" >/dev/null
runuser -u postgres -- createdb -O odoo -E UTF8 -T template0 --lc-collate=C --lc-ctype=C.UTF-8 "$TEST_DB"
runuser -u postgres -- pg_restore --no-owner --role=odoo -d "$TEST_DB" < "$dump"

users=$(psql_q "SELECT count(*) FROM res_users" "$TEST_DB")
[ "$users" -ge 1 ] || fl_die "no user in the restored database"
installed=$(psql_q "SELECT count(*) FROM ir_module_module WHERE name = 'ea_audit_firm_agent' AND state = 'installed'" "$TEST_DB")
[ "$installed" = 1 ] || fl_die "the restored database is not a firm's"

referenced=$(psql_q "SELECT count(DISTINCT store_fname) FROM ir_attachment WHERE store_fname IS NOT NULL" "$TEST_DB")
if [ "$referenced" -gt 0 ]; then
  [ -f "$folder/filestore.tar.gz" ] || fl_die "the database refers to files but the backup has no filestore"
  held=$(tar -tzf "$folder/filestore.tar.gz" | grep -vc '/$' || true)
  [ "$held" -ge "$referenced" ] || fl_die "the filestore holds $held files, the database refers to $referenced"
fi

# Reads a sample of the repository's data as well as its index.
restic check --quiet --read-data-subset=5%
