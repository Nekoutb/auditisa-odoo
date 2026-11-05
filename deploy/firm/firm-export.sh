#!/usr/bin/env bash
# firm-export.sh: this firm's data, for the firm, when it leaves.
#
#   firm-export [--dry-run]
#
# Writes /var/lib/auditisa-firm/exports/<slug>-<stamp>.tar.gz (database dump, filestore, digests),
# readable by root only, and an encrypted copy in the firm's own storage. The file itself never
# goes to the control plane: only its SHA-256 does, in the heartbeat. The operator fetches it over
# SSH and hands it to the firm: see docs/runbook/OFFBOARDING.md.

set -euo pipefail
umask 077
SCRIPT_NAME=firm-export
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/firm/firm-lib.sh
. "$HERE/firm-lib.sh"
load_firm_env

OUT=$FIRM_VAR/exports
if [ "${1:-}" = "--dry-run" ]; then
  fl_log "DRY RUN: nothing is changed"
  fl_log "backup_firm.sh of $FIRM_DB -> $OUT/$FIRM_SLUG-<stamp>.tar.gz, restic backup --tag export, digest reported"
  exit 0
fi

[ "$(id -u)" = 0 ] || fl_die "run as root"
exec 7>/run/lock/firm-export.lock
flock -n 7 || fl_die "another export is running"
WORK=$(mktemp -d /var/tmp/firm-export.XXXXXX)

on_exit() {
  local rc=$?
  trap - EXIT
  rm -rf "$WORK"
  if [ "$rc" != 0 ]; then
    set_status export_state failed
    fl_warn "export failed (exit $rc)"
  fi
  exit "$rc"
}
trap on_exit EXIT

set_status export_state running
install -d -m 700 "$OUT"
bash "$PROVISION_DIR/backup_firm.sh" --db "$FIRM_DB" --dest "$WORK" --keep-days 0
stamp=$(date -u +%Y%m%dT%H%M%SZ)
file=$OUT/$FIRM_SLUG-$stamp.tar.gz
tar -czf "$file.part" -C "$WORK" .
tar -tzf "$file.part" >/dev/null
mv -T "$file.part" "$file"
digest=$(sha256sum "$file" | cut -d' ' -f1)
printf '%s  %s\n' "$digest" "$(basename "$file")" > "$file.sha256"

load_backup_env
restic backup --quiet --tag export --host "$FIRM_SLUG" "$file"

set_status export_sha256 "$digest"
set_status export_at "$(now_utc)"
set_status export_state done
printf '%s export %s -\n' "$(now_utc)" "$(id -un)" >> "$BREAK_GLASS_LOG"
fl_log "export ready: $file"
