#!/usr/bin/env bash
# firm-backup.sh: an encrypted backup of this firm, to this firm's own storage.
#
#   firm-backup [--tag nightly|pre-update|export] [--dry-run]
#
# backup_firm.sh makes and verifies the dump and the filestore archive. restic then encrypts them
# with this firm's key, sends them to this firm's bucket and applies the retention. The plain copy
# is removed as soon as the upload is confirmed. The result goes in the status folder either way:
# the control plane shows it and raises the alert, and also raises it if no result ever comes.
#
# Retention: 14 daily, 8 weekly, 12 monthly. Backups taken before an update and exports are kept
# for 90 days. To be confirmed by the owner against the firm's own retention duties.

set -euo pipefail
umask 077
SCRIPT_NAME=firm-backup
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/firm/firm-lib.sh
. "$HERE/firm-lib.sh"

TAG=nightly DRY_RUN=0
while [ $# -gt 0 ]; do
  case "$1" in
    --tag) TAG=${2:?}; shift ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) fl_die "unknown option $1" ;;
  esac
  shift
done
case "$TAG" in nightly|pre-update|export) ;; *) fl_die "unknown tag $TAG" ;; esac
load_firm_env
DEST=$FIRM_PREFIX/var/backups/auditisa-firm

if [ "$DRY_RUN" = 1 ]; then
  fl_log "DRY RUN: nothing is changed"
  fl_log "dump and filestore of $FIRM_DB -> $DEST (backup_firm.sh)"
  fl_log "restic backup --tag $TAG, to this firm's bucket, with this firm's key; the plain copy is then removed"
  fl_log "restic forget --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune"
  exit 0
fi

[ "$(id -u)" = 0 ] || fl_die "run as root"
exec 9>/run/lock/firm-backup.lock
flock -w 3600 9 || fl_die "another backup is running"

fail() {
  local rc=$?
  trap - EXIT
  if [ "$rc" != 0 ]; then
    set_status last_backup_at "$(now_utc)"
    set_status last_backup_ok 0
    fl_warn "backup failed (exit $rc)"
  fi
  rm -rf "${DEST:?}/$FIRM_DB"
  exit "$rc"
}
trap fail EXIT

load_backup_env
bash "$PROVISION_DIR/backup_firm.sh" --db "$FIRM_DB" --dest "$DEST" --keep-days 0
target=$(find "$DEST/$FIRM_DB" -mindepth 1 -maxdepth 1 -type d -name '20*Z' | sort | tail -n 1)
[ -n "$target" ] || fl_die "backup_firm.sh left nothing"

restic backup --quiet --tag "$TAG" --host "$FIRM_SLUG" "$target"
restic forget --quiet --tag nightly --host "$FIRM_SLUG" --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune
restic forget --quiet --tag pre-update --host "$FIRM_SLUG" --keep-within 90d --prune
# The upload is proved by reading the list back, not by the exit code alone.
# grep reads it all: with -q it stops early, restic dies of SIGPIPE and pipefail calls that a
# failure (first real firm, 2026-11-09).
restic snapshots --quiet --tag "$TAG" --latest 1 --host "$FIRM_SLUG" | grep . >/dev/null || fl_die "the snapshot is not in the repository"

set_status last_backup_at "$(now_utc)"
set_status last_backup_ok 1
fl_log "backup done ($TAG)"
