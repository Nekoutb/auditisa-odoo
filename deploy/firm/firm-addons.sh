#!/usr/bin/env bash
# firm-addons.sh: which optional client add-ons are switched on, on this firm's server.
#
#   firm-addons apply [--dry-run] -- [code ...]     the codes are the complete list of what is on
#
# Started by firm-apply-desired with what the control plane asked. The rules, in order:
#
#   1. the request is checked against the manifests of the signed release in use. Any code that is
#      not an optional add-on of that release refuses the WHOLE request: nothing changes, and the
#      next heartbeat says so. A base feature can never be asked for or switched off this way.
#   2. an add-on on for the first time is installed: backup, Odoo stopped, database copied, the
#      module installed, Odoo started, health check. On failure the copy comes back, and that add-on
#      is not tried again on this release until the operator switches it off and on.
#   3. the approved list goes in $FIRM_VAR/addons/approved.json, root's file, read by Odoo:
#      ea_audit_addons applies it within five minutes.
#
# Off hides an add-on and keeps its tables. NOTHING HERE EVER UNINSTALLS: Odoo's uninstall drops
# tables, and audit records have retention rules (owner's ruling, docs/decisions.md).

set -euo pipefail
umask 022
SCRIPT_NAME=firm-addons
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
# shellcheck source=deploy/firm/firm-lib.sh
. "$HERE/firm-lib.sh"

[ "${1:-}" = apply ] || fl_die "usage: firm-addons apply [--dry-run] -- [code ...]"
shift
DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then DRY_RUN=1; shift; fi
[ "${1:-}" != "--" ] || shift
ASKED=("$@")
load_firm_env

: "${SERVICE:=odoo}"
: "${ODOO_USER:=odoo}"
: "${ODOO_LOG_DIR:=/var/log/odoo}"
: "${HEALTH_ATTEMPTS:=60}"
ADDONS_DIR=$FIRM_VAR/addons
APPROVED=$ADDONS_DIR/approved.json
REFUSED=$FIRM_VAR/refused-addons
SNAPSHOT=${FIRM_DB}_preaddon

refuse() {
  fl_warn "request refused, nothing changed: $1"
  [ "$DRY_RUN" = 1 ] || set_status addons_refused "${2:-1}"
  exit 3
}

# The optional add-ons of the signed release in use: firm-update.sh verified it and root owns it.
allowed_addons() {
  "$ODOO_PY" -I - "$1" <<'PY'
import ast
import pathlib
import sys

for manifest in sorted(pathlib.Path(sys.argv[1]).glob("*/__manifest__.py")):
    data = ast.literal_eval(manifest.read_text(encoding="utf-8"))
    name = manifest.parent.name
    if (
        data.get("ea_client_addon") is True and data.get("installable", True)
        and (manifest.parent / "__init__.py").is_file() and not name.startswith("ea_platform_")
    ):
        print(name)
PY
}

RELEASE_DIR=$(readlink -f "$CURRENT_LINK") || fl_die "no current release"
ALLOWED=$(allowed_addons "$RELEASE_DIR/addons") || fl_die "a manifest of the current release cannot be read"
RELEASE_NAME=$(basename "$RELEASE_DIR")

bad=0
for code in ${ASKED[@]+"${ASKED[@]}"}; do
  if ! [[ $code =~ ^[a-z][a-z0-9_]{2,39}$ ]] || ! grep -qxF -- "$code" <<<"$ALLOWED"; then
    # A name from the control plane goes in no log as it is: it was not found in the release.
    bad=$((bad + 1))
  fi
done
[ "$bad" = 0 ] || refuse "$bad code(s) are not optional add-ons of release $RELEASE_NAME" "$bad"

if [ "$DRY_RUN" = 1 ]; then
  fl_log "DRY RUN: nothing is changed"
  fl_log "optional add-ons of release $RELEASE_NAME: $(tr '\n' ' ' <<<"$ALLOWED")"
  fl_log "would switch on: ${ASKED[*]+"${ASKED[*]}"}"
  fl_log "an add-on on for the first time: firm-backup --tag pre-addon; stop Odoo; copy $FIRM_DB to $SNAPSHOT; install; start; health check"
  exit 0
fi

mkdir -p "$ADDONS_DIR"
chmod 755 "$ADDONS_DIR"

healthy() {
  local i code=""
  for ((i = 1; i <= HEALTH_ATTEMPTS; i++)); do
    code=$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' http://127.0.0.1:8069/web/health || true)
    if [ "$code" = 200 ]; then
      code=$(curl -s --max-time 90 -o /dev/null -w '%{http_code}' -H "Host: $FIRM_HOST" http://127.0.0.1:8069/web/login || true)
      if [ "$code" = 200 ]; then return 0; fi
    fi
    sleep 5
  done
  fl_warn "health check failed: last answer was ${code:-none}"
  return 1
}

# Switching off clears a refusal, which is how the operator asks for another try.
forget_refusals_not_asked() {
  [ -f "$REFUSED" ] || return 0
  local kept="" line code
  while read -r line; do
    code=${line#* }
    if printf '%s\n' ${ASKED[@]+"${ASKED[@]}"} | grep -qxF -- "$code"; then kept+="$line"$'\n'; fi
  done < "$REFUSED"
  printf '%s' "$kept" > "$REFUSED"
}

install_step() {
  local list=$1 ulog code state
  ulog=$ODOO_LOG_DIR/addon-$(date -u +%Y%m%dT%H%M%SZ).log
  runuser -u "$ODOO_USER" -- "$ODOO_PY" "$ODOO_BIN" -c "$ODOO_CONF" -d "$FIRM_DB" -i "$list" \
    --without-demo=True --no-http --max-cron-threads=0 --workers=0 --stop-after-init --logfile="$ulog" 8>&- \
    || { fl_warn "the install failed, see $ulog"; return 1; }
  if grep -qE ' (ERROR|CRITICAL) ' "$ulog"; then
    fl_warn "the install logged errors, see $ulog"
    return 1
  fi
  for code in ${list//,/ }; do
    state=$(psql_q "SELECT state FROM ir_module_module WHERE name = '$code'" "$FIRM_DB")
    [ "$state" = installed ] || { fl_warn "$code is '$state' after the install, see $ulog"; return 1; }
  done
  systemctl start "$SERVICE" || return 1
  healthy
}

put_the_copy_back() {
  local failed
  systemctl stop "$SERVICE" || true
  failed=${FIRM_DB}_failed_addon_$(date -u +%Y%m%d%H%M%S)
  psql_q "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$FIRM_DB', '$SNAPSHOT') AND pid <> pg_backend_pid()" >/dev/null
  if psql_q "ALTER DATABASE \"$FIRM_DB\" RENAME TO \"$failed\"" >/dev/null \
    && psql_q "ALTER DATABASE \"$SNAPSHOT\" RENAME TO \"$FIRM_DB\"" >/dev/null; then
    fl_warn "database restored from the copy; the failed one is kept as $failed"
  else
    fl_warn "COULD NOT RESTORE THE DATABASE: check $FIRM_DB, $failed and $SNAPSHOT by hand"
    return 1
  fi
  systemctl start "$SERVICE" && healthy
}

# Returns 0 when installed, 1 when refused and back as it was, and sets the state on anything worse.
install_first_time() {
  local list=$1
  exec 8>/run/lock/firm-update.lock
  flock -n 8 || { fl_warn "an update is running: this waits for the next pass"; return 2; }
  if db_exists "$SNAPSHOT"; then
    fl_warn "$SNAPSHOT exists: an earlier run did not finish, see INCIDENT.md"
    return 1
  fi
  # No backup, no install.
  "$BIN_DIR/firm-backup.sh" --tag pre-addon || { fl_warn "no backup, so no install"; return 1; }
  systemctl stop "$SERVICE"
  if ! psql_q "CREATE DATABASE \"$SNAPSHOT\" TEMPLATE \"$FIRM_DB\" OWNER \"$ODOO_USER\"" >/dev/null; then
    systemctl start "$SERVICE" || true
    fl_warn "could not copy the database, so no install"
    return 1
  fi
  if install_step "$list"; then
    psql_q "DROP DATABASE IF EXISTS \"$SNAPSHOT\"" >/dev/null || fl_warn "could not drop $SNAPSHOT"
    return 0
  fi
  if ! put_the_copy_back; then
    fl_warn "Odoo is STILL UNHEALTHY after putting the copy back"
    set_status update_state failed
  fi
  return 1
}

write_approved() {
  local tmp body="" code
  for code in "$@"; do body+="\"$code\","; done
  tmp=$(mktemp "$ADDONS_DIR/.approved.XXXXXX")
  printf '{"on":[%s]}\n' "${body%,}" > "$tmp"
  chmod 644 "$tmp"
  mv -f "$tmp" "$APPROVED"
}

forget_refusals_not_asked

INSTALLED=$(psql_q "SELECT name FROM ir_module_module WHERE state = 'installed'" "$FIRM_DB")
TO_INSTALL=()
REFUSED_COUNT=0
for code in ${ASKED[@]+"${ASKED[@]}"}; do
  grep -qx -- "$code" <<<"$INSTALLED" && continue
  if grep -qxF -- "$RELEASE_NAME $code" "$REFUSED" 2>/dev/null; then
    REFUSED_COUNT=$((REFUSED_COUNT + 1))
  else
    TO_INSTALL+=("$code")
  fi
done

if [ ${#TO_INSTALL[@]} -gt 0 ]; then
  fl_log "installing for the first time: ${TO_INSTALL[*]}"
  rc=0
  install_first_time "$(IFS=,; echo "${TO_INSTALL[*]}")" || rc=$?
  if [ "$rc" = 1 ]; then
    for code in "${TO_INSTALL[@]}"; do
      printf '%s %s\n' "$RELEASE_NAME" "$code" >> "$REFUSED"
      REFUSED_COUNT=$((REFUSED_COUNT + 1))
    done
  elif [ "$rc" = 2 ]; then
    exit 0
  fi
  INSTALLED=$(psql_q "SELECT name FROM ir_module_module WHERE state = 'installed'" "$FIRM_DB")
fi

ON=()
for code in ${ASKED[@]+"${ASKED[@]}"}; do
  if grep -qx -- "$code" <<<"$INSTALLED"; then ON+=("$code"); fi
done
write_approved ${ON[@]+"${ON[@]}"}
set_status addons_refused "$REFUSED_COUNT"
