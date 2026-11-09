#!/usr/bin/env bash
# practice-update.sh: takes every practice space to a new release, or leaves them all as they were.
#
#   practice-update --bundle FILE --digest SHA256         a signed release bundle (FILE.sig beside it)
#   practice-update --release-dir DIR                      the preview only: a release staging already runs
#
# The practice computer gets a new release BEFORE any firm's real server: the control room offers
# it to a firm only after the holding period (7 days unless the owner says otherwise). In order:
#
#   1. the bundle's digest and signature are checked (the same rule as the firms': a signer this computer
#      already trusts), and it is unpacked
#   2. Odoo stops; each space is copied to upd_practice_<slug>, closed to connections
#   3. `current` switches; every space's addons are updated
#   4. Odoo starts; every space must answer its login page
#   5. on any failure: the previous release, and every space from its copy. All or nothing: the
#      spaces share one code.
#   6. the demo template is built again on the new release (resets need it; until then they refuse)
#   7. the release's list of trusted signers is taken if it is newer (deploy/firm/release_trust.py)

set -euo pipefail
umask 022
SCRIPT_NAME=practice-update
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/practice/practice-lib.sh
. "$HERE/practice-lib.sh"

BUNDLE="" DIGEST="" SOURCE_DIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --bundle) BUNDLE=${2:?}; shift ;;
    --digest) DIGEST=${2:?}; shift ;;
    --release-dir) SOURCE_DIR=${2:?}; shift ;;
    -h|--help) sed -n '2,17p' "$0"; exit 0 ;;
    *) pl_die "unknown option $1" ;;
  esac
  shift
done
load_practice_env
[ "$(id -u)" = 0 ] || pl_die "run as root"
cd /

PHASE=idle PREVIOUS="" TARGET="" NAME=""
SPACES=() SNAPPED=()

snapshot_of() { printf 'upd_practice_%s' "$1"; }

unpack() {
  if [ -n "$SOURCE_DIR" ]; then
    [ "$PRACTICE_PREVIEW" = 1 ] || pl_die "--release-dir is for the preview only: the practice computer takes signed bundles"
    [ -d "$SOURCE_DIR/addons" ] || pl_die "$SOURCE_DIR has no addons/"
    NAME=$(sed -n 's/^sha=//p' "$SOURCE_DIR/RELEASE" 2>/dev/null | cut -c1-12 || true)
    [ -n "$NAME" ] || NAME=$(basename "$SOURCE_DIR")
  else
    [ -r "$BUNDLE" ] && [ -r "$BUNDLE.sig" ] || pl_die "--bundle FILE (and FILE.sig) required"
    [[ $DIGEST =~ ^[0-9a-f]{64}$ ]] || pl_die "--digest must be a sha256"
    printf '%s  %s\n' "$DIGEST" "$BUNDLE" | sha256sum -c --status - || pl_die "the bundle's digest differs"
    practice_signature_holds "$BUNDLE" "$BUNDLE.sig" "$DIGEST" \
      || pl_die "the bundle's signature is refused: not signed by a signer this computer trusts"
    NAME=$(basename "$BUNDLE" .tar.gz | cut -c1-12)
  fi
  valid_release "$NAME" || pl_die "cannot tell the release's name"
  TARGET=$PRACTICE_RELEASES/$NAME
  [ ! -d "$TARGET" ] || return 0
  rm -rf "$TARGET.tmp"
  install -d -m 750 "$TARGET.tmp"
  if [ -n "$SOURCE_DIR" ]; then
    cp -a "$SOURCE_DIR/addons" "$TARGET.tmp/"
  else
    tar -xzf "$BUNDLE" -C "$TARGET.tmp"
  fi
  rm -rf "$TARGET.tmp/addons"/ea_platform_*
  chown -R root:"$ODOO_USER" "$TARGET.tmp"
  chmod -R u=rwX,g=rX,o= "$TARGET.tmp"
  mv -T "$TARGET.tmp" "$TARGET"
}

switch_to() {
  ln -sfn "$1" "$PRACTICE_CURRENT.tmp"
  mv -Tf "$PRACTICE_CURRENT.tmp" "$PRACTICE_CURRENT"
}

update_space() {
  local slug=$1 db installed wanted name to_install=() to_update=() args=() log
  db=$(space_db "$slug")
  require_space_db "$db"
  load_space "$slug"
  wanted=$(base_addons "$TARGET/addons")${SPACE_ADDONS:+,$SPACE_ADDONS}
  installed=$(psql_q "SELECT name FROM ir_module_module WHERE state = 'installed'" "$db")
  IFS=, read -ra names <<<"$wanted"
  for name in "${names[@]}"; do
    if grep -qx "$name" <<<"$installed"; then to_update+=("$name"); else to_install+=("$name"); fi
  done
  if [ ${#to_install[@]} -gt 0 ]; then args+=(-i "$(IFS=,; echo "${to_install[*]}")"); fi
  if [ ${#to_update[@]} -gt 0 ]; then args+=(-u "$(IFS=,; echo "${to_update[*]}")"); fi
  log=$ODOO_LOGS/update-$NAME-$slug-$(date -u +%Y%m%dT%H%M%SZ).log
  pl_log "$slug: install ${to_install[*]:-none}; update ${#to_update[@]} addons (log: $log)"
  odoo_run "$db" "$log" "${args[@]}" --without-demo=True 7>&- || { show_errors "$log"; pl_die "$slug: update failed, see $log"; }
  if log_has_errors "$log"; then show_errors "$log"; pl_die "$slug: update logged errors, see $log"; fi
}

restore_all() {
  local slug db snap
  systemctl stop "$PRACTICE_SERVICE" || true
  [ -z "$PREVIOUS" ] || switch_to "$PREVIOUS"
  for slug in ${SNAPPED[@]+"${SNAPPED[@]}"}; do
    db=$(space_db "$slug")
    snap=$(snapshot_of "$slug")
    psql_q "DROP DATABASE IF EXISTS \"$db\" WITH (FORCE)" >/dev/null
    psql_q "ALTER DATABASE \"$snap\" RENAME TO \"$db\"" >/dev/null
    psql_q "ALTER DATABASE \"$db\" ALLOW_CONNECTIONS true" >/dev/null
    pl_warn "$slug: back as it was before the update"
  done
  systemctl start "$PRACTICE_SERVICE"
}

on_exit() {
  local rc=$?
  trap - EXIT
  [ "$PHASE" != idle ] && [ "$PHASE" != finished ] || exit "$rc"
  set +e
  [ "$rc" != 0 ] || rc=1
  pl_warn "the update to $NAME failed in phase $PHASE: putting everything back"
  restore_all
  printf 'rolled_back %s %s\n' "$NAME" "$(now_utc)" > "$PRACTICE_STATUS/update_state"
  audit_line "update release=$NAME rolled back"
  exit "$rc"
}

exec 7>/run/lock/practice-space.lock
flock -w 600 7 || pl_die "another practice operation is running"
trap "" HUP
unpack
PREVIOUS=$(readlink -f "$PRACTICE_CURRENT" || true)
if [ "$PREVIOUS" = "$TARGET" ]; then
  pl_log "already on $NAME"
  exit 0
fi
mapfile -t SPACES < <(list_spaces)
for slug in ${SPACES[@]+"${SPACES[@]}"}; do
  db_exists "$(snapshot_of "$slug")" && pl_die "$(snapshot_of "$slug") exists: an earlier update did not finish"
done
trap on_exit EXIT

PHASE=stopped
systemctl stop "$PRACTICE_SERVICE"
for slug in ${SPACES[@]+"${SPACES[@]}"}; do
  db_exists "$(space_db "$slug")" || continue
  psql_q "CREATE DATABASE \"$(snapshot_of "$slug")\" TEMPLATE \"$(space_db "$slug")\" OWNER \"$DB_ROLE\"" >/dev/null
  psql_q "ALTER DATABASE \"$(snapshot_of "$slug")\" ALLOW_CONNECTIONS false" >/dev/null
  SNAPPED+=("$slug")
done
PHASE=switched
switch_to "$TARGET"
for slug in ${SNAPPED[@]+"${SNAPPED[@]}"}; do update_space "$slug"; done
systemctl start "$PRACTICE_SERVICE"
service_healthy || pl_die "the service does not answer"
for slug in ${SNAPPED[@]+"${SNAPPED[@]}"}; do
  space_answers "$slug" || pl_die "$slug does not answer its login page"
done

PHASE=finished
for slug in ${SNAPPED[@]+"${SNAPPED[@]}"}; do
  psql_q "ALTER DATABASE \"$(snapshot_of "$slug")\" ALLOW_CONNECTIONS true" >/dev/null
  psql_q "DROP DATABASE \"$(snapshot_of "$slug")\" WITH (FORCE)" >/dev/null || pl_warn "could not drop $(snapshot_of "$slug")"
done
printf '%s\n' "$NAME" > "$PRACTICE_STATUS/release"
# A newer list of trusted signers, if this release (verified above) carries one.
practice_adopt_trust "$TARGET"
printf 'ok %s %s\n' "$NAME" "$(now_utc)" > "$PRACTICE_STATUS/update_state"
audit_line "update release=$NAME spaces=${#SNAPPED[@]}"
pl_log "every space is on $NAME; building the demo template on it"
exec 7>&-
"$HERE/practice-template.sh" build
