#!/usr/bin/env bash
# firm-update.sh: takes this firm to a signed release, or leaves it as it was.
#
#   firm-update <sha> <bundle sha256> [--dry-run]
#
# Started by firm-apply-desired when the control plane names a new release. Modelled on
# deploy/deploy-staging.sh, with a signed bundle instead of a git mirror: a firm has no access to
# the repository. In order:
#
#   1. fetches the bundle and refuses it unless its digest and signature hold. The signing key is
#      not on the control plane, so the control plane can only choose among signed releases.
#   2. backs up, encrypted, to the firm's storage. No backup, no update.
#   3. stops Odoo, copies the database, switches `current`, updates the addons, starts Odoo
#   4. checks /web/health, /web/login, the module states and nginx
#   5. on failure puts back the previous release and the copied database and keeps the failed one
#      as <db>_failed_<sha>_<stamp>
#
# The result is in the status folder for the next heartbeat: ok, rolled_back (running the previous
# release) or failed (needs the operator). A refused release is not tried twice.

set -euo pipefail
umask 022
SCRIPT_NAME=firm-update
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/firm/firm-lib.sh
. "$HERE/firm-lib.sh"

SHA=${1:-} DIGEST=${2:-} DRY_RUN=0
[ "${3:-}" != "--dry-run" ] || DRY_RUN=1
valid_release "$SHA" || fl_die "invalid release '$SHA'"
valid_digest "$DIGEST" || fl_die "invalid digest"
load_firm_env
: "${RELEASE_BASE_URL:?}"

: "${SERVICE:=odoo}"
: "${ODOO_USER:=odoo}"
: "${ODOO_LOG_DIR:=/var/log/odoo}"
: "${HEALTH_ATTEMPTS:=60}"
SNAPSHOT=${FIRM_DB}_predeploy
TARGET=$RELEASES_DIR/$SHA
REFUSED=$FIRM_VAR/refused-releases
PHASE=idle
PREVIOUS=""
MODULES=()

if [ "$DRY_RUN" = 1 ]; then
  fl_log "DRY RUN: nothing is changed"
  fl_log "fetch and verify $RELEASE_BASE_URL/$SHA.tar.gz (digest and signature)"
  fl_log "firm-backup --tag pre-update; stop Odoo; copy $FIRM_DB to $SNAPSHOT"
  fl_log "switch current to $TARGET; update the addons; start Odoo; health check"
  fl_log "on failure: previous release and copied database back, result rolled_back or failed"
  exit 0
fi

[ "$(id -u)" = 0 ] || fl_die "run as root"
cd /
exec 8>/run/lock/firm-update.lock
flock -n 8 || fl_die "another update is running"
trap "" HUP

mark_refused() { printf '%s\n' "$SHA" >> "$REFUSED"; }

result() {
  set_status update_state "$1"
  set_status update_release "$SHA"
}

healthy() {
  local i code=""
  for ((i = 1; i <= HEALTH_ATTEMPTS; i++)); do
    code=$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' http://127.0.0.1:8069/web/health || true)
    if [ "$code" = 200 ]; then
      code=$(curl -s --max-time 90 -o /dev/null -w '%{http_code}' -H "Host: $FIRM_HOST" http://127.0.0.1:8069/web/login || true)
      if [ "$code" = 200 ]; then break; fi
    fi
    sleep 5
  done
  if [ "$code" != 200 ]; then
    fl_warn "health check failed: last answer was ${code:-none}"
    return 1
  fi
  code=$(curl -sk --max-time 30 -o /dev/null -w '%{http_code}' --resolve "$FIRM_HOST:443:127.0.0.1" "https://$FIRM_HOST/web/login" || true)
  if [ "$code" != 200 ]; then
    fl_warn "Odoo is up but nginx answers $code"
    return 1
  fi
}

switch_to() {
  ln -sfn "$1" "$CURRENT_LINK.tmp"
  mv -Tf "$CURRENT_LINK.tmp" "$CURRENT_LINK"
}

restore_previous() {
  systemctl stop "$SERVICE"
  switch_to "$PREVIOUS"
  local failed
  failed=${FIRM_DB}_failed_${SHA:0:12}_$(date -u +%Y%m%d%H%M%S)
  psql_q "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$FIRM_DB', '$SNAPSHOT') AND pid <> pg_backend_pid()" >/dev/null
  if psql_q "ALTER DATABASE \"$FIRM_DB\" RENAME TO \"$failed\"" >/dev/null \
    && psql_q "ALTER DATABASE \"$SNAPSHOT\" RENAME TO \"$FIRM_DB\"" >/dev/null; then
    fl_warn "database restored from the copy; the failed one is kept as $failed"
  else
    fl_warn "COULD NOT RESTORE THE DATABASE: check $FIRM_DB, $failed and $SNAPSHOT by hand"
    return 1
  fi
  systemctl start "$SERVICE"
  healthy
}

on_exit() {
  local rc=$?
  trap - EXIT
  [ "$PHASE" != "done" ] || exit 0
  set +e
  [ "$rc" != 0 ] || rc=1
  mark_refused
  case "$PHASE" in
    idle)
      # Nothing was changed.
      result rolled_back ;;
    stopped)
      systemctl start "$SERVICE"
      if healthy; then result rolled_back; else result failed; fi ;;
    snapshotted)
      psql_q "DROP DATABASE IF EXISTS \"$SNAPSHOT\"" >/dev/null
      systemctl start "$SERVICE"
      if healthy; then result rolled_back; else result failed; fi ;;
    switched)
      if restore_previous; then
        fl_warn "rolled back: Odoo is healthy on $(basename "$PREVIOUS")"
        result rolled_back
      else
        fl_warn "Odoo is STILL UNHEALTHY after the rollback"
        result failed
      fi ;;
  esac
  exit "$rc"
}
trap on_exit EXIT

fetch_and_verify() {
  local work
  work=$(mktemp -d /var/tmp/firm-update.XXXXXX)
  curl -fsSL --retry 3 --max-time 600 -o "$work/bundle.tar.gz" "$RELEASE_BASE_URL/$SHA.tar.gz"
  curl -fsSL --retry 3 --max-time 60 -o "$work/bundle.sig" "$RELEASE_BASE_URL/$SHA.tar.gz.sig"
  verify_bundle "$work/bundle.tar.gz" "$work/bundle.sig" "$DIGEST" || { rm -rf "$work"; fl_die "bundle refused"; }
  if [ ! -d "$TARGET" ]; then
    rm -rf "$TARGET.tmp"
    install -d -m 750 "$TARGET.tmp"
    tar -xzf "$work/bundle.tar.gz" -C "$TARGET.tmp"
    chown -R root:"$ODOO_USER" "$TARGET.tmp"
    chmod -R u=rwX,g=rX,o= "$TARGET.tmp"
    mv -T "$TARGET.tmp" "$TARGET"
  fi
  rm -rf "$work"
}

read_modules() {
  local names
  names=$("$ODOO_PY" - "$TARGET/addons" <<'PY'
import ast
import pathlib
import sys

for manifest in sorted(pathlib.Path(sys.argv[1]).glob("*/__manifest__.py")):
    data = ast.literal_eval(manifest.read_text(encoding="utf-8"))
    if data.get("installable", True) and (manifest.parent / "__init__.py").is_file():
        print(("client:" if data.get("ea_client_addon") is True else "") + manifest.parent.name)
PY
  ) || fl_die "a manifest of this release cannot be read"
  # An optional client add-on is updated where it was once installed, even if switched off, so its
  # data follows the code. It is installed only by firm-addons, when this firm first asks for it.
  local all_names installed m
  mapfile -t all_names <<<"$names"
  installed=$(psql_q "SELECT name FROM ir_module_module WHERE state = 'installed'" "$FIRM_DB")
  MODULES=()
  for m in "${all_names[@]}"; do
    if [[ $m == client:* ]]; then
      if grep -qx "${m#client:}" <<<"$installed"; then MODULES+=("${m#client:}"); fi
    elif [ -n "$m" ]; then
      MODULES+=("$m")
    fi
  done
  [ -n "${MODULES[0]:-}" ] || fl_die "this release has no addon"
  for m in "${MODULES[@]}"; do
    [[ $m =~ ^[a-z][a-z0-9_]*$ ]] || fl_die "invalid addon name '$m'"
    # Never on a firm's server, whatever a bundle holds.
    [[ $m != ea_platform_* ]] || fl_die "this bundle holds the control plane's addon"
  done
}

update_modules() {
  local installed to_install=() to_update=() m args=() ulog
  installed=$(psql_q "SELECT name FROM ir_module_module WHERE state = 'installed'" "$FIRM_DB")
  for m in "${MODULES[@]}"; do
    if grep -qx "$m" <<<"$installed"; then to_update+=("$m"); else to_install+=("$m"); fi
  done
  if [ ${#to_install[@]} -gt 0 ]; then args+=(-i "$(IFS=,; echo "${to_install[*]}")"); fi
  if [ ${#to_update[@]} -gt 0 ]; then args+=(-u "$(IFS=,; echo "${to_update[*]}")"); fi
  ulog=$ODOO_LOG_DIR/update-${SHA:0:12}-$(date -u +%Y%m%dT%H%M%SZ).log
  runuser -u "$ODOO_USER" -- "$ODOO_PY" "$ODOO_BIN" -c "$ODOO_CONF" -d "$FIRM_DB" "${args[@]}" \
    --without-demo=True --no-http --max-cron-threads=0 --workers=0 --stop-after-init --logfile="$ulog" 8>&- \
    || fl_die "module update failed, see $ulog"
  if grep -qE ' (ERROR|CRITICAL) ' "$ulog"; then fl_die "module update logged errors, see $ulog"; fi
  local list n
  list=$(printf "'%s'," "${MODULES[@]}")
  n=$(psql_q "SELECT count(*) FROM ir_module_module WHERE state = 'installed' AND name IN (${list%,})" "$FIRM_DB")
  [ "$n" = "${#MODULES[@]}" ] || fl_die "not every addon is installed after the update, see $ulog"
}

set_status update_state updating
set_status update_release "$SHA"
PREVIOUS=$(readlink -f "$CURRENT_LINK")
[ -n "$PREVIOUS" ] || fl_die "no current release"
if db_exists "$SNAPSHOT"; then fl_die "$SNAPSHOT exists: an earlier run did not finish, see INCIDENT.md"; fi

fetch_and_verify
read_modules
"$BIN_DIR/firm-backup.sh" --tag pre-update

PHASE=stopped
systemctl stop "$SERVICE"
psql_q "CREATE DATABASE \"$SNAPSHOT\" TEMPLATE \"$FIRM_DB\" OWNER \"$ODOO_USER\"" >/dev/null
PHASE=snapshotted
PHASE=switched
switch_to "$TARGET"
update_modules
systemctl start "$SERVICE"
healthy

PHASE="done"
psql_q "DROP DATABASE IF EXISTS \"$SNAPSHOT\"" >/dev/null || fl_warn "could not drop $SNAPSHOT"
set_status release "$SHA"
result ok
# The server's own scripts come with the release, once it is known to work.
cp -f "$TARGET/deploy/firm/"*.sh "$TARGET/deploy/firm/recipe.env" "$BIN_DIR/"
chmod 700 "$BIN_DIR"/*
fl_log "now running $SHA"
