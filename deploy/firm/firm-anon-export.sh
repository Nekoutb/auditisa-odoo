#!/usr/bin/env bash
# firm-anon-export.sh: an anonymised copy of this firm's database, for rebuilding staging.
#
#   firm-anon-export <ref> [--dry-run]
#
# <ref> is 16 hexadecimal characters, named by the control plane in a heartbeat answer. It carries no
# instruction: all this script can do is what is written here, and the result stays on this server.
#
# Refused unless firm.env holds ANON_EXPORT_ALLOWED=1. The operator sets it on this server, with the
# firm's agreement, so that nothing on the control plane can start this alone.
#
# In order:
#   1. copies the live database into a throwaway one, without stopping the firm (pg_dump, pg_restore)
#   2. firm_anon.py: checks every table, text column and model against the manifest; replaces names,
#      addresses, tax numbers and free text; removes chatter, logs, files and credentials; keeps
#      figures; reads the finished dump back and stops if anything identifying is still in it
#   3. writes /var/lib/auditisa-firm/anon-exports/anon-<ref>.tar: db.dump, ANON-REPORT.json, SHA256SUMS
#      readable by root only. The filestore is never read, so evidence files cannot be in it.
#   4. drops the throwaway database, whatever happened
#
# Only the state and the SHA-256 go to the control plane, in the heartbeat. The operator carries the
# file to staging: see docs/runbook/PIPELINE.md. Older files are removed when a new one is made.

set -euo pipefail
umask 077
SCRIPT_NAME=firm-anon-export
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/firm/firm-lib.sh
. "$HERE/firm-lib.sh"

REF=${1:-} DRY_RUN=0
[ "${2:-}" != "--dry-run" ] || DRY_RUN=1
valid_anon_ref "$REF" || fl_die "invalid reference"
load_firm_env

: "${ANON_TOOL_DIR:=$CURRENT_LINK/deploy/firm}"
: "${ANON_DB_PREFIX:=anon_}"
COPY_DB=$ANON_DB_PREFIX$REF
OUT=$FIRM_VAR/anon-exports
FILE=$OUT/anon-$REF.tar

allowed() { [ "${ANON_EXPORT_ALLOWED:-0}" = 1 ]; }

if [ "$DRY_RUN" = 1 ]; then
  fl_log "DRY RUN: nothing is changed"
  if allowed; then fl_log "this firm allows anonymised exports"; else fl_log "this firm does NOT allow anonymised exports: the real run would refuse"; fi
  fl_log "pg_dump $FIRM_DB | pg_restore into $COPY_DB; firm_anon.py run; tar to $FILE; drop $COPY_DB"
  exit 0
fi

[ "$(id -u)" = 0 ] || fl_die "run as root"
exec 7>"${ANON_LOCK:-/run/lock/firm-anon-export.lock}"
flock -n 7 || fl_die "another anonymised export is running"
WORK=""

report() {
  set_status anon_export_ref "$REF"
  set_status anon_export_at "$(now_utc)"
  set_status anon_export_state "$1"
}

on_exit() {
  local rc=$?
  trap - EXIT
  set +e
  psql_q "DROP DATABASE IF EXISTS \"$COPY_DB\" WITH (FORCE)" >/dev/null
  [ -z "$WORK" ] || rm -rf "$WORK"
  if [ "$rc" != 0 ]; then
    rm -f "$FILE"
    report failed
    rm -f "$FIRM_STATUS/anon_export_sha256"
    fl_warn "anonymised export did not finish (exit $rc): nothing was kept"
  fi
  exit "$rc"
}

if ! allowed; then
  report refused
  fl_die "this firm does not allow anonymised exports (ANON_EXPORT_ALLOWED)"
fi

trap on_exit EXIT
report running
rm -f "$FIRM_STATUS/anon_export_sha256"
install -d -m 700 "$OUT"
WORK=$(mktemp -d "${TMPDIR:-/var/tmp}/firm-anon.XXXXXX")
chmod 700 "$WORK"
# A release is not readable by postgres, so it works from its own copy of the tool. It writes the dump
# and the report here, then root takes them back.
cp "$ANON_TOOL_DIR/firm_anon.py" "$ANON_TOOL_DIR/anon-manifest.json" "$WORK/"
chown -R postgres "$WORK"

SIZE=$(psql_q "SELECT pg_database_size('$FIRM_DB')")
FREE=$(($(df --output=avail -B1 "$WORK" | tail -n 1)))
[ "$FREE" -gt "$((SIZE * 3))" ] || fl_die "not enough disk: this needs three times the database's size"

psql_q "DROP DATABASE IF EXISTS \"$COPY_DB\" WITH (FORCE)" >/dev/null
runuser -u postgres -- createdb -E UTF8 -T template0 --lc-collate=C --lc-ctype=C.UTF-8 "$COPY_DB"
runuser -u postgres -- pg_dump --format=custom --no-owner --no-acl "$FIRM_DB" \
  | runuser -u postgres -- pg_restore --no-owner --no-acl --exit-on-error -d "$COPY_DB"

runuser -u postgres -- "$ODOO_PY" -I "$WORK/firm_anon.py" run --db "$COPY_DB" \
  --manifest "$WORK/anon-manifest.json" --dump "$WORK/db.dump" --report "$WORK/ANON-REPORT.json"

chown -R root:root "$WORK"
(cd "$WORK" && sha256sum db.dump ANON-REPORT.json > SHA256SUMS)
find "$OUT" -maxdepth 1 -type f -name 'anon-*.tar' -delete
tar -cf "$FILE.part" -C "$WORK" db.dump ANON-REPORT.json SHA256SUMS
mv -T "$FILE.part" "$FILE"
DIGEST=$(sha256sum "$FILE" | cut -d' ' -f1)

set_status anon_export_sha256 "$DIGEST"
report "done"
# Recorded in the server's access log, like an export or a login (no longer a screen of the firm's).
printf '%s anon-export %s %s\n' "$(now_utc)" "$(id -un)" "$REF" >> "$BREAK_GLASS_LOG"
fl_log "anonymised export ready: $FILE"
fl_log "sha256 $DIGEST"
