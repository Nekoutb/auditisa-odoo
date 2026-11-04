#!/usr/bin/env bash
# backup_firm.sh: back up one firm's database and filestore.
#
#   backup_firm.sh --db <name> [--dest DIR] [--keep-days N] [--dry-run]
#
#   --db NAME       database to back up
#   --dest DIR      backup root (default: /var/backups/odoo/firms)
#   --keep-days N   delete this firm's backups older than N days; 0 keeps all (default: 14)
#   --dry-run       print what would be done and change nothing
#
# Runs as root. Result, readable by root only:
#   <dest>/<db>/<UTC stamp>/{db.dump,filestore.tar.gz,SHA256SUMS}
# The folder is named only once everything verified, so a partial backup keeps a .part suffix.
# The dump comes first: a filestore taken after it holds every file the dump refers to.
#
# Restore into a new database <new>:
#   sudo -u postgres createdb -O odoo -E UTF8 -T template0 --lc-collate=C --lc-ctype=C.UTF-8 <new>
#   sudo -u postgres pg_restore --no-owner --role=odoo -d <new> db.dump
#   mkdir -p <data_dir>/filestore
#   tar -xzf filestore.tar.gz -C <data_dir>/filestore && mv <data_dir>/filestore/<db> <data_dir>/filestore/<new>
#   chown -R odoo:odoo <data_dir>/filestore/<new>

set -euo pipefail
umask 077

: "${ODOO_CONF:=/etc/odoo/odoo.conf}"

DB="" DEST=/var/backups/odoo/firms KEEP_DAYS=14 DRY_RUN=0

log() { printf '[backup_firm] %s\n' "$*"; }
warn() { printf '[backup_firm] WARNING: %s\n' "$*" >&2; }
die() { printf '[backup_firm] ERROR: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,22p' "$0"; exit 64; }

while [ $# -gt 0 ]; do
  case "$1" in
    --db) DB=${2:?--db needs a value}; shift ;;
    --dest) DEST=${2:?--dest needs a value}; shift ;;
    --keep-days) KEEP_DAYS=${2:?--keep-days needs a value}; shift ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) usage ;;
    *) die "unknown option $1 (see --help)" ;;
  esac
  shift
done

[ -n "$DB" ] || usage
[[ $DB =~ ^[a-z][a-z0-9_]{1,62}$ ]] || die "invalid database name '$DB'"
[[ $KEEP_DAYS =~ ^[0-9]+$ ]] || die "--keep-days must be a number"

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
TARGET=$DEST/$DB/$STAMP

data_dir() {
  sed -n 's/^[[:space:]]*data_dir[[:space:]]*=[[:space:]]*//p' "$ODOO_CONF" 2>/dev/null | head -n 1
}

if [ "$DRY_RUN" = 1 ]; then
  log "DRY RUN: nothing is changed"
  log "dump:      pg_dump --format=custom $DB -> $TARGET/db.dump"
  log "filestore: $(data_dir || true)/filestore/$DB -> $TARGET/filestore.tar.gz"
  log "retention: $([ "$KEEP_DAYS" = 0 ] && echo 'keep all' || echo "delete backups of $DB older than $KEEP_DAYS days")"
  exit 0
fi

[ "$(id -u)" = 0 ] || die "run as root"
cd /
for tool in runuser psql pg_dump pg_restore tar sha256sum; do
  command -v "$tool" >/dev/null || die "$tool is not installed"
done
[ -n "$(runuser -u postgres -- psql -XAtc "SELECT 1 FROM pg_database WHERE datname = '$DB'")" ] \
  || die "database $DB does not exist"

DATA_DIR=$(data_dir || true)
[ -n "$DATA_DIR" ] || die "no data_dir in $ODOO_CONF"
FILESTORE=$DATA_DIR/filestore/$DB

install -d -o root -g root -m 700 "$DEST" "$DEST/$DB"
PART=$TARGET.part
install -d -m 700 "$PART"

log "dumping $DB"
runuser -u postgres -- pg_dump --format=custom "$DB" > "$PART/db.dump"
toc=$(pg_restore --list "$PART/db.dump") || die "the dump is not readable; $PART is left for inspection"
for table in res_users res_company ir_attachment ir_module_module; do
  grep -q "TABLE DATA public $table " <<<"$toc" \
    || die "the dump has no data for '$table'; $PART is left for inspection"
done

if [ -d "$FILESTORE" ]; then
  log "archiving the filestore"
  tar -czf "$PART/filestore.tar.gz" -C "$DATA_DIR/filestore" "$DB"
  tar -tzf "$PART/filestore.tar.gz" >/dev/null || die "the filestore archive is not readable"
else
  warn "no filestore at $FILESTORE: the backup holds the database only"
fi

(cd "$PART" && sha256sum -- * > SHA256SUMS)
mv -T "$PART" "$TARGET"
log "backup verified: $TARGET ($(du -sh "$TARGET" | cut -f1))"

if [ "$KEEP_DAYS" != 0 ]; then
  find "$DEST/$DB" -mindepth 1 -maxdepth 1 -type d -name '20*Z' -mtime "+$KEEP_DAYS" -exec rm -rf -- {} +
fi
