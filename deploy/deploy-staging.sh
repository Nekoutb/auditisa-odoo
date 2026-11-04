#!/usr/bin/env bash
# deploy-staging.sh: gated deployment of the AuditISA addons to test.auditisa.com.
# Modelled on deploy-ea-audit.sh of the current tool.
#
#   deploy-staging.sh deploy [ref] [--force] [--no-fetch]   deploy <ref> (default: dev); it must be on dev
#   deploy-staging.sh check                                 report whether a deployment could run; changes nothing
#   deploy-staging.sh status                                what is running
#   deploy-staging.sh rollback                              back to the previous release, code only
#
#   --force     run the module update again for the release already running
#   --no-fetch  do not contact GitHub (use the mirror as it is)
#
# Runs as root on the server. Each release is a `git archive` of the commit in
# $ROOT/releases/<sha12>; `current` is the only thing Odoo sees. A deployment:
#
#   1. refuses a commit that is not on dev, and refuses to start if `check` finds a problem
#   2. stops Odoo and copies the database to <db>_predeploy
#   3. switches `current`, installs new addons and updates the others
#   4. starts Odoo and checks /web/health, /web/login, the module states and nginx
#   5. on success drops the copy; on any failure puts back the previous release and the
#      copied database, keeps the failed one as <db>_failed_<sha>_<stamp>, and exits non-zero
#
# The filestore needs no copy: it only gains files during an update, and nothing removes
# files while Odoo is stopped. The manual `rollback` restores code only, because the copy is
# gone by then: a module update that changed the schema needs a restore from the nightly backup.
# Python packages from requirements.txt go into the shared virtualenv and are not rolled back.
#
# One-time setup (not done by this script; `check` reports what is missing):
#   - add /opt/auditisa-odoo/current/addons to addons_path in /etc/odoo/odoo.conf, before
#     /opt/ea-odoo-addons. Odoo skips a path that does not exist yet with a warning.
#   - a read-only GitHub deploy key at /root/.ssh/auditisa_odoo_deploy (the repository is private)
#
# With more than one firm database on this server, only $DB is updated: others need their own run.

set -euo pipefail
umask 022
cd /

: "${REPO_URL:=git@github.com:Nekoutb/auditisa-odoo.git}"
: "${DEPLOY_KEY:=/root/.ssh/auditisa_odoo_deploy}"
: "${MIRROR:=/opt/auditisa-odoo-src.git}"
: "${ROOT:=/opt/auditisa-odoo}"
: "${BRANCH:=dev}"
: "${DB:=ea_audit_odoo_staging}"
: "${SERVICE:=odoo}"
: "${ODOO_USER:=odoo}"
: "${ODOO_PY:=/opt/odoo19/venv/bin/python}"
: "${ODOO_BIN:=/opt/odoo19/src/odoo-bin}"
: "${ODOO_CONF:=/etc/odoo/odoo.conf}"
: "${ODOO_LOG_DIR:=/var/log/odoo}"
: "${HOST:=test.auditisa.com}"
: "${PORT:=8069}"
: "${EDGE_CHECK:=1}"            # 0 skips the check through nginx
: "${EDGE_EXPECT:=401}"         # staging sits behind basic auth, so nginx must answer 401 without credentials
: "${KEEP_RELEASES:=3}"
: "${UPDATE_MEM:=1400M}"        # cgroup ceiling for the module update
: "${MIN_FREE_MB:=800}"         # memory + swap available before a deployment starts
: "${HEALTH_ATTEMPTS:=30}"

LOCK=/run/lock/auditisa-odoo-deploy.lock
DEPLOY_LOG=$ROOT/deployed-shas.log
SNAPSHOT=${DB}_predeploy

# Where a deployment is, for the exit trap: idle | stopped | snapshotted | switched
PHASE=idle
CUR="" PREV_BEFORE="" REL="" SHA="" SHORT="" TREE="" REF="" NO_FETCH=0 FORCE=0
MODULES=()

log() { printf '[deploy] %s\n' "$*"; }
warn() { printf '[deploy] WARNING: %s\n' "$*" >&2; }
die() { printf '[deploy] ERROR: %s\n' "$*" >&2; exit 1; }

if [ -f "$DEPLOY_KEY" ]; then
  export GIT_SSH_COMMAND="ssh -i $DEPLOY_KEY -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new"
fi

psql_q() { runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -At -d "${2:-postgres}" -c "$1"; }
db_exists() { [ -n "$(psql_q "SELECT 1 FROM pg_database WHERE datname = '$1'")" ]; }

current_release() { if [ -L "$ROOT/current" ]; then readlink -f "$ROOT/current"; fi; }
previous_release() { sed -n 's/^previous=//p' "$ROOT/current.previous" 2>/dev/null || true; }
sha_of_release() { sed -n 's/^sha=//p' "$1/RELEASE" 2>/dev/null || true; }

take_lock() {
  exec 9>"$LOCK"
  flock -n 9 || die "another deployment or rollback is running"
}

# From here on a dropped ssh session cannot kill the run half-way through a switch.
shield() {
  install -d -m 750 "$ROOT/logs"
  local runlog
  runlog=$ROOT/logs/$1-$(date -u +%Y%m%dT%H%M%SZ).log
  : > "$runlog"
  tail --pid=$$ -f -n +1 "$runlog" 9>&- &
  trap "" HUP
  exec >>"$runlog" 2>&1
  log "run log: $runlog"
}

ensure_mirror() {
  if [ ! -d "$MIRROR" ]; then
    log "cloning a mirror of the repository"
    (umask 077; git clone --quiet --mirror "$REPO_URL" "$MIRROR") \
      || die "cannot clone $REPO_URL (is the deploy key $DEPLOY_KEY installed and registered on GitHub?)"
  elif [ "$NO_FETCH" = 0 ]; then
    git -C "$MIRROR" fetch --quiet --prune || die "git fetch failed (--no-fetch uses the mirror as it is)"
  fi
}

resolve_ref() {
  [[ $REF != -* ]] || die "invalid ref '$REF'"
  SHA=$(git -C "$MIRROR" rev-parse --verify --quiet "${REF}^{commit}") || die "ref '$REF' not found"
  SHORT=${SHA:0:12}
  TREE=$(git -C "$MIRROR" rev-parse "$SHA^{tree}")
  git -C "$MIRROR" merge-base --is-ancestor "$SHA" "refs/heads/$BRANCH" \
    || die "$SHORT is not on the $BRANCH branch: staging only takes commits of $BRANCH"
  REL=$ROOT/releases/$SHORT
}

# Prints problems; returns the number found. Reads only.
preflight() {
  local problems=0 tool
  bad() { printf '  problem: %s\n' "$*"; problems=$((problems + 1)); }

  [ "$(id -u)" = 0 ] || { bad "not running as root"; return 1; }
  for tool in git flock curl runuser psql systemd-run systemctl tar; do
    command -v "$tool" >/dev/null || bad "$tool is not installed"
  done
  [ -x "$ODOO_PY" ] && [ -f "$ODOO_BIN" ] || bad "Odoo not found at $ODOO_PY, $ODOO_BIN"
  id "$ODOO_USER" >/dev/null 2>&1 || bad "system user $ODOO_USER does not exist"
  systemctl cat "$SERVICE" >/dev/null 2>&1 || bad "service $SERVICE does not exist"

  if [ -r "$ODOO_CONF" ]; then
    grep -Eq "^[[:space:]]*addons_path[[:space:]]*=.*$ROOT/current/addons" "$ODOO_CONF" \
      || bad "addons_path in $ODOO_CONF does not contain $ROOT/current/addons (one-time setup, see the header)"
  else
    bad "$ODOO_CONF is not readable"
  fi

  if db_exists "$DB"; then
    if db_exists "$SNAPSHOT"; then
      bad "$SNAPSHOT exists: an earlier run did not finish. Compare it with $DB and drop or restore it by hand"
    fi
    local need_mb free_mb
    need_mb=$(( $(psql_q "SELECT pg_database_size('$DB')") * 2 / 1048576 + 200 ))
    free_mb=$(df -Pm /var/lib/postgresql | awk 'NR==2 {print $4}')
    [ "$free_mb" -ge "$need_mb" ] || bad "only $free_mb MB free for the database copy; need $need_mb MB"
  else
    bad "database $DB does not exist"
  fi

  local avail_mb
  avail_mb=$(awk '/^(MemAvailable|SwapFree):/ {t += $2} END {print int(t / 1024)}' /proc/meminfo)
  [ "$avail_mb" -ge "$MIN_FREE_MB" ] || bad "only $avail_mb MB of memory and swap available; need $MIN_FREE_MB MB"

  if [ "$EDGE_CHECK" = 1 ]; then
    local code
    code=$(edge_code)
    [ "$code" = "$EDGE_EXPECT" ] || bad "https://$HOST/ through nginx answers $code, expected $EDGE_EXPECT, before anything changed"
  fi
  return "$problems"
}

edge_code() {
  curl -sk --max-time 15 -o /dev/null -w '%{http_code}' --resolve "$HOST:443:127.0.0.1" "https://$HOST/web/login" || true
}

export_release() {
  if [ -f "$REL/RELEASE" ]; then
    log "release $SHORT is already on disk"
  else
    git -C "$MIRROR" cat-file -e "$SHA:addons" 2>/dev/null || die "$SHORT has no addons/ folder: nothing to deploy"
    local paths=(addons) tmp=$REL.tmp
    if git -C "$MIRROR" cat-file -e "$SHA:requirements.txt" 2>/dev/null; then paths+=(requirements.txt); fi
    rm -rf "$tmp"
    install -d -m 750 "$ROOT/releases" "$tmp"
    git -C "$MIRROR" archive --format=tar "$SHA" "${paths[@]}" | tar -x -C "$tmp"
    printf 'sha=%s\nref=%s\ntree=%s\nexported=%s\n' "$SHA" "$REF" "$TREE" "$(date -u +%FT%TZ)" > "$tmp/RELEASE"
    # Odoo reads the code and never writes it.
    chown -R root:"$ODOO_USER" "$tmp"
    chmod -R u=rwX,g=rX,o= "$tmp"
    mv -T "$tmp" "$REL"
  fi
  chown root:"$ODOO_USER" "$ROOT" "$ROOT/releases"
  chmod 750 "$ROOT" "$ROOT/releases"

  local names
  names=$("$ODOO_PY" - "$REL/addons" <<'PY'
import ast
import pathlib
import sys

for manifest in sorted(pathlib.Path(sys.argv[1]).glob("*/__manifest__.py")):
    data = ast.literal_eval(manifest.read_text(encoding="utf-8"))
    if data.get("installable", True) and (manifest.parent / "__init__.py").is_file():
        print(manifest.parent.name)
PY
  ) || die "a manifest of $SHORT cannot be read"
  mapfile -t MODULES <<<"$names"
  [ -n "${MODULES[0]:-}" ] || die "$SHORT has no installable addon: nothing to deploy"
  local m
  for m in "${MODULES[@]}"; do
    [[ $m =~ ^[a-z][a-z0-9_]*$ ]] || die "invalid addon name '$m'"
  done
  log "addons: ${MODULES[*]}"
}

install_requirements() {
  local req=$REL/requirements.txt
  if [ -f "$req" ] && grep -qvE '^[[:space:]]*(#|$)' "$req"; then
    log "installing requirements.txt into the shared virtualenv"
    uv pip install --quiet --python "$ODOO_PY" -r "$req" || die "requirements.txt could not be installed"
  fi
}

snapshot_db() {
  log "copying $DB to $SNAPSHOT"
  # OWNER matters: Odoo only sees databases its role owns, and after a rollback this copy is $DB.
  psql_q "CREATE DATABASE \"$SNAPSHOT\" TEMPLATE \"$DB\" OWNER \"$ODOO_USER\"" >/dev/null || die "cannot copy $DB (still in use?)"
}

drop_snapshot() {
  psql_q "DROP DATABASE IF EXISTS \"$SNAPSHOT\"" >/dev/null
}

# switch_to <release> [previous]: re-point current and record what to roll back to. By
# default that is what current pointed at; the automatic rollback passes the pre-deployment
# value, so a failed release never becomes the previous one.
switch_to() {
  local cur
  cur=$(current_release)
  [ "$1" != "$cur" ] || return 0
  local prev=${2-$cur}
  if [ -n "$prev" ]; then printf 'previous=%s\n' "$prev" > "$ROOT/current.previous"; else rm -f "$ROOT/current.previous"; fi
  ln -sfn "$1" "$ROOT/current.tmp"
  mv -Tf "$ROOT/current.tmp" "$ROOT/current"
}

update_modules() {
  local installed to_install=() to_update=() m
  installed=$(psql_q "SELECT name FROM ir_module_module WHERE state = 'installed'" "$DB")
  for m in "${MODULES[@]}"; do
    if grep -qx "$m" <<<"$installed"; then to_update+=("$m"); else to_install+=("$m"); fi
  done

  local ulog args=()
  ulog=$ODOO_LOG_DIR/update-$SHORT-$(date -u +%Y%m%dT%H%M%SZ).log
  if [ ${#to_install[@]} -gt 0 ]; then args+=(-i "$(IFS=,; echo "${to_install[*]}")"); fi
  if [ ${#to_update[@]} -gt 0 ]; then args+=(-u "$(IFS=,; echo "${to_update[*]}")"); fi
  log "install: ${to_install[*]:-none}; update: ${to_update[*]:-none} (log: $ulog)"

  systemd-run --quiet --scope --collect -p "MemoryMax=$UPDATE_MEM" -p MemorySwapMax=2G \
    nice -n 10 runuser -u "$ODOO_USER" -- "$ODOO_PY" "$ODOO_BIN" -c "$ODOO_CONF" -d "$DB" "${args[@]}" \
    --without-demo=True --no-http --max-cron-threads=0 --stop-after-init --logfile="$ulog" 9>&- \
    || { show_errors "$ulog"; die "module update failed, see $ulog"; }
  if grep -qE ' (ERROR|CRITICAL) ' "$ulog"; then
    show_errors "$ulog"
    die "module update logged errors, see $ulog"
  fi
  modules_installed || die "not every addon is installed after the update, see $ulog"
}

show_errors() { grep -E ' (ERROR|CRITICAL) ' "$1" | tail -n 10 | cut -c1-300 >&2 || true; }

modules_installed() {
  local list n
  list=$(printf "'%s'," "${MODULES[@]}")
  n=$(psql_q "SELECT count(*) FROM ir_module_module WHERE state = 'installed' AND name IN (${list%,})" "$DB")
  [ "$n" = "${#MODULES[@]}" ]
}

# /web/health answers without touching a database, so /web/login is what proves the registry
# of the staging database loaded. The first request after a start also builds the assets.
healthy() {
  local i code=""
  for ((i = 1; i <= HEALTH_ATTEMPTS; i++)); do
    code=$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/web/health" || true)
    if [ "$code" = 200 ]; then
      code=$(curl -s --max-time 90 -o /dev/null -w '%{http_code}' -H "Host: $HOST" "http://127.0.0.1:$PORT/web/login" || true)
      if [ "$code" = 200 ]; then break; fi
    fi
    sleep 3
  done
  if [ "$code" != 200 ]; then
    warn "health check failed: last answer from port $PORT was ${code:-none}"
    return 1
  fi
  if [ "$EDGE_CHECK" = 1 ]; then
    code=$(edge_code)
    if [ "$code" != "$EDGE_EXPECT" ]; then
      warn "Odoo is up but https://$HOST/ through nginx answers $code, expected $EDGE_EXPECT"
      return 1
    fi
  fi
}

# Puts back the code and the database as they were before the deployment.
restore_previous() {
  systemctl stop "$SERVICE"
  if [ -n "$CUR" ]; then
    switch_to "$CUR" "$PREV_BEFORE"
  else
    rm -f "$ROOT/current" "$ROOT/current.previous"
  fi
  local failed
  failed=${DB}_failed_${SHORT}_$(date -u +%Y%m%d%H%M%S)
  psql_q "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$DB', '$SNAPSHOT') AND pid <> pg_backend_pid()" >/dev/null
  if psql_q "ALTER DATABASE \"$DB\" RENAME TO \"$failed\"" >/dev/null \
    && psql_q "ALTER DATABASE \"$SNAPSHOT\" RENAME TO \"$DB\"" >/dev/null; then
    warn "database restored from the copy; the failed one is kept as $failed (drop it when finished with it)"
  else
    warn "COULD NOT RESTORE THE DATABASE: check $DB, $failed and $SNAPSHOT by hand before starting $SERVICE"
    return 1
  fi
  systemctl start "$SERVICE"
  healthy
}

on_exit() {
  local rc=$?
  trap - EXIT
  [ "$PHASE" != idle ] || exit "$rc"
  set +e
  [ "$rc" != 0 ] || rc=1
  warn "deployment of $SHORT failed in phase '$PHASE'; recovering"
  case "$PHASE" in
    stopped)
      systemctl start "$SERVICE" ;;
    snapshotted)
      drop_snapshot
      systemctl start "$SERVICE" ;;
    switched)
      if restore_previous; then
        warn "rolled back: $SERVICE is healthy on ${CUR:-no release}"
      else
        warn "$SERVICE is STILL UNHEALTHY after the rollback: investigate now"
      fi ;;
  esac
  exit "$rc"
}

cmd_check() {
  local rc=0
  log "checking the server"
  preflight || rc=$?
  if [ -d "$MIRROR" ]; then
    git -C "$MIRROR" ls-remote --exit-code origin "refs/heads/$BRANCH" >/dev/null 2>&1 \
      || { printf '  problem: GitHub cannot be reached with the deploy key\n'; rc=$((rc + 1)); }
  elif ! git ls-remote --exit-code "$REPO_URL" "refs/heads/$BRANCH" >/dev/null 2>&1; then
    printf '  problem: %s cannot be read (deploy key %s)\n' "$REPO_URL" "$DEPLOY_KEY"
    rc=$((rc + 1))
  fi
  if [ "$rc" = 0 ]; then log "ready"; else die "$rc problem(s)"; fi
}

cmd_status() {
  local rel prev
  rel=$(current_release)
  if [ -n "$rel" ]; then
    printf 'running  %s  ref=%s\n' "$(sha_of_release "$rel" | cut -c1-12)" "$(sed -n 's/^ref=//p' "$rel/RELEASE" 2>/dev/null)"
  else
    printf 'running  no release yet\n'
  fi
  prev=$(previous_release)
  if [ -n "$prev" ]; then printf 'previous %s\n' "$(basename "$prev")"; fi
  printf 'service  %s\n' "$(systemctl is-active "$SERVICE" 2>/dev/null || true)"
  if db_exists "$SNAPSHOT"; then printf 'WARNING  %s exists: an earlier run did not finish\n' "$SNAPSHOT"; fi
  psql_q "SELECT datname FROM pg_database WHERE datname LIKE '${DB}\_failed\_%' ORDER BY 1" \
    | sed 's/^/kept     /' || true
}

cmd_rollback() {
  [ $# = 0 ] || die "rollback takes no argument"
  take_lock
  local cur prev
  cur=$(current_release)
  prev=$(previous_release)
  [ -n "$cur" ] || die "no current release"
  [ -n "$prev" ] && [ -f "$prev/RELEASE" ] || die "no previous release recorded"
  [ "$prev" != "$cur" ] || die "the previous release is the one running"
  grep -q "^$(sha_of_release "$prev") " "$DEPLOY_LOG" 2>/dev/null \
    || die "$(basename "$prev") never deployed successfully here: refusing to roll back onto it"
  shield rollback
  warn "$(basename "$cur") -> $(basename "$prev"): code only, the database is NOT reverted"
  switch_to "$prev"
  systemctl restart "$SERVICE"
  healthy || die "unhealthy after the rollback: current is left on $(basename "$prev"); investigate now"
  printf '%s %s rollback %s\n' "$(sha_of_release "$prev")" "$(basename "$prev")" "$(date -u +%FT%TZ)" >> "$DEPLOY_LOG"
  log "now running $(basename "$prev")"
}

prune_releases() {
  local cur prev d
  cur=$(current_release)
  prev=$(previous_release)
  find "$ROOT/releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' | sort -rn \
    | tail -n +$((KEEP_RELEASES + 1)) | cut -d' ' -f2- | while read -r d; do
      [ "$d" != "$cur" ] && [ "$d" != "$prev" ] || continue
      log "pruning old release $(basename "$d")"
      rm -rf "$d"
    done
}

cmd_deploy() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --force) FORCE=1 ;;
      --no-fetch) NO_FETCH=1 ;;
      -*) die "unknown option $1" ;;
      *) [ -z "$REF" ] || die "one ref only"; REF=$1 ;;
    esac
    shift
  done
  REF=${REF:-$BRANCH}

  [ "$(id -u)" = 0 ] || die "run as root"
  take_lock
  install -d -m 750 "$ROOT" "$ROOT/releases"
  ensure_mirror
  resolve_ref
  log "$REF ($SHORT): $(git -C "$MIRROR" log -1 --format=%s "$SHA" | cut -c1-70)"
  CUR=$(current_release)
  PREV_BEFORE=$(previous_release)
  if [ "$CUR" = "$REL" ] && [ "$FORCE" = 0 ]; then
    grep -q "^$SHA " "$DEPLOY_LOG" 2>/dev/null || warn "$SHORT is not in $DEPLOY_LOG: an earlier run did not finish"
    log "already running $SHORT: nothing to do (--force updates the modules again)"
    exit 0
  fi
  preflight || die "preflight found problems: nothing was changed"
  [ -n "$CUR" ] || warn "no current release: a failed deployment leaves the database restored and no release active"

  shield "deploy-$SHORT"
  trap on_exit EXIT
  export_release
  install_requirements

  log "stopping $SERVICE"
  PHASE=stopped
  systemctl stop "$SERVICE"
  snapshot_db
  PHASE=snapshotted

  PHASE=switched
  switch_to "$REL"
  update_modules

  log "starting $SERVICE"
  systemctl start "$SERVICE"
  healthy || die "health check failed"

  printf '%s %s %s %s tree=%s\n' "$SHA" "$SHORT" "$REF" "$(date -u +%FT%TZ)" "$TREE" >> "$DEPLOY_LOG"
  PHASE=idle
  drop_snapshot || warn "could not drop $SNAPSHOT: drop it by hand, the next deployment refuses to start otherwise"
  prune_releases
  log "now running $SHORT"
}

case "${1:-}" in
  deploy) shift; cmd_deploy "$@" ;;
  check) shift; cmd_check ;;
  status) cmd_status ;;
  rollback) shift; cmd_rollback "$@" ;;
  *) sed -n '2,35p' "$0"; exit 64 ;;
esac
