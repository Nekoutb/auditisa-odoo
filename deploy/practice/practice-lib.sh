#!/usr/bin/env bash
# shellcheck disable=SC2034  # used by the scripts that source this file
# practice-lib.sh: what the practice computer's scripts share. Sourced, never run.
#
# The practice computer runs ONE Odoo service for many practice spaces. Each space is its own
# database, practice_<slug>, chosen by the first part of the host name (dbfilter ^practice_%d$):
# demo-akwa.practice.auditisa.com opens practice_demo-akwa and nothing else.
#
# Every space is a copy of the demo template database (TEMPLATE_DB), which holds made-up data
# only. Real client data never comes here: no script takes a dump, the database manager is off,
# and practice-guard refuses to serve any database that was not copied from the template.
#
# PRACTICE_PREFIX is empty on a real server. The dry runs and the tests set it to a folder, so
# that nothing outside that folder is ever written.
#
# Layout:
#   /etc/auditisa-practice/practice.env             who this computer is (no secret)
#   /etc/auditisa-practice/secrets/                 root 700: master.password, heartbeat.token
#   /etc/auditisa-practice/secrets/logins/<slug>    root 600: a space's first administrator
#   /var/lib/auditisa-practice/spaces/<slug>.env    what a space is: name, add-ons, last reset
#   /var/lib/auditisa-practice/template.env         which release and id the template has
#   /var/lib/auditisa-practice/status/              figures for the heartbeat
#   /opt/auditisa-practice/releases/<sha>, current  the code, as on a firm's server
#   /var/log/auditisa-practice/                     what the scripts did

: "${PRACTICE_PREFIX:=}"
PRACTICE_ETC=$PRACTICE_PREFIX/etc/auditisa-practice
PRACTICE_SECRETS=$PRACTICE_ETC/secrets
PRACTICE_LOGINS=$PRACTICE_SECRETS/logins
PRACTICE_VAR=$PRACTICE_PREFIX/var/lib/auditisa-practice
PRACTICE_SPACES=$PRACTICE_VAR/spaces
PRACTICE_STATUS=$PRACTICE_VAR/status
PRACTICE_LOGS=$PRACTICE_PREFIX/var/log/auditisa-practice
PRACTICE_ROOT=$PRACTICE_PREFIX/opt/auditisa-practice
PRACTICE_RELEASES=$PRACTICE_ROOT/releases
PRACTICE_CURRENT=$PRACTICE_ROOT/current
PRACTICE_BIN=$PRACTICE_ROOT/bin

# Fixed here, not in practice.env: nothing a file or the environment says can widen them.
readonly SPACE_DB_PREFIX=practice_
readonly TEMPLATE_DB=tpl_practice_demo
readonly TEMPLATE_BUILD_DB=tpl_practice_demo_build
# Names a space can never have: they are parts of the address, or would read as something else.
readonly RESERVED_SLUGS="www practice template tpl admin api status mail test demo static"

: "${ODOO_PY:=/opt/odoo19/venv/bin/python}"
: "${ODOO_BIN:=/opt/odoo19/src/odoo-bin}"
# The practice service has its own system user and PostgreSQL role. On a shared machine (the
# preview) that keeps it away from the other databases: it owns the practice ones only.
readonly ODOO_USER=odoo-practice
readonly DB_ROLE=odoo_practice

pl_log() { printf '[%s] %s\n' "${SCRIPT_NAME:-practice}" "$*"; }
pl_warn() { printf '[%s] WARNING: %s\n' "${SCRIPT_NAME:-practice}" "$*" >&2; }
pl_die() { printf '[%s] ERROR: %s\n' "${SCRIPT_NAME:-practice}" "$*" >&2; exit 1; }

now_utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# ---------------------------------------------------------------------------- release integrity

# True when the bundle's SHA-256 is the digest the control room gave in its heartbeat answer, which
# practice-heartbeat kept only after checking it against this computer's token (HMAC, over HTTPS).
# The releases bucket and the download address are not trusted: only that digest decides.
practice_digest_holds() {
  local bundle=$1 digest=$2
  [[ $digest =~ ^[0-9a-f]{64}$ ]] || return 1
  printf '%s  %s\n' "$digest" "$bundle" | sha256sum -c --status -
}

# ---------------------------------------------------------------------------- names

# A slug is the first part of the address: lower case letters, digits and inner hyphens.
valid_slug() {
  local slug=$1 reserved
  [[ $slug =~ ^[a-z][a-z0-9-]{1,30}[a-z0-9]$ ]] || return 1
  [[ $slug != *--* ]] || return 1
  for reserved in $RESERVED_SLUGS; do
    [ "$slug" != "$reserved" ] || return 1
  done
}

space_db() { printf '%s%s' "$SPACE_DB_PREFIX" "$1"; }

# require_space_db <name>: the one gate every destructive command goes through. Refuses anything
# that is not exactly practice_<valid slug>: the staging, firm and system databases, the template,
# snapshots, and names with quotes or spaces.
require_space_db() {
  local db=$1
  [[ $db == "$SPACE_DB_PREFIX"* ]] || pl_die "refused: '$db' is not a practice space (practice_<slug>)"
  valid_slug "${db#"$SPACE_DB_PREFIX"}" || pl_die "refused: '$db' is not a valid practice space name"
}

# The slug of a space database, or nothing.
slug_of_db() {
  local db=$1
  [[ $db == "$SPACE_DB_PREFIX"* ]] || return 1
  valid_slug "${db#"$SPACE_DB_PREFIX"}" || return 1
  printf '%s' "${db#"$SPACE_DB_PREFIX"}"
}

valid_release() { [[ $1 =~ ^[0-9a-f]{8,40}$ ]]; }
valid_addon() { [[ $1 =~ ^[a-z][a-z0-9_]{2,39}$ ]] && [[ $1 != ea_platform_* ]]; }
valid_login() { [[ $1 =~ ^[A-Za-z0-9._+-]{1,64}(@[A-Za-z0-9.-]{1,190})?$ ]]; }
valid_lang() { [[ $1 =~ ^[a-z]{2,3}_[A-Z]{2}$ ]]; }

# ---------------------------------------------------------------------------- configuration

load_practice_env() {
  [ -r "$PRACTICE_ETC/practice.env" ] || pl_die "$PRACTICE_ETC/practice.env is missing: is this the practice computer?"
  # Written by install-practice-server.sh with values it checked; read again with the same rule.
  if grep -Evq "^([A-Z0-9_]+='[A-Za-z0-9 ._:@/%+=,-]*'|#.*|)$" "$PRACTICE_ETC/practice.env"; then
    pl_die "$PRACTICE_ETC/practice.env holds an unexpected line"
  fi
  # shellcheck disable=SC1091
  . "$PRACTICE_ETC/practice.env"
  : "${PRACTICE_NAME:?}" "${PRACTICE_DOMAIN:?}" "${PRACTICE_PORT:?}" "${PRACTICE_SERVICE:?}" "${PRACTICE_CONF:?}"
  : "${PRACTICE_DATA_DIR:?}" "${PRACTICE_PUBLIC_URL:?}"
  : "${PRACTICE_PREVIEW:=0}" "${PRACTICE_STRICT_CLUSTER:=1}" "${PRACTICE_LANG:=fr_FR}"
  : "${PRACTICE_HEARTBEAT_URL:=}" "${PRACTICE_UPDATE_MEM:=1400M}" "${PRACTICE_RELEASE_BASE_URL:=}"
  : "${PRACTICE_ENTRY_URL:=$PRACTICE_PUBLIC_URL/web/login}"
  # Practice email stays off unless the owner decides otherwise (docs/runbook/PLATFORM-EMAIL.md).
  : "${PRACTICE_MAIL_ALLOWED:=0}"
  ODOO_CONF=$PRACTICE_PREFIX$PRACTICE_CONF
  # Written by the odoo-practice user: its own folder, not root's.
  ODOO_LOGS=$PRACTICE_PREFIX/var/log/$PRACTICE_SERVICE
}

# The address of a space (its web.base.url): https://<slug>.practice.auditisa.com, or on the
# preview one shared address. The entry link is what a person clicks: on the preview it chooses
# the space with a cookie (see install-practice-server.sh).
space_public_url() { printf '%s' "${PRACTICE_PUBLIC_URL//%s/$1}"; }
space_entry_url() { printf '%s' "${PRACTICE_ENTRY_URL//%s/$1}"; }

# The address the server uses to reach a space itself (PDF reports): *.localhost is the loopback
# for glibc, so no DNS, no certificate and no hairpin through the public address are needed.
space_local_url() { printf 'http://%s.practice.localhost:%s' "$1" "$PRACTICE_PORT"; }

space_file() { printf '%s/%s.env' "$PRACTICE_SPACES" "$1"; }
login_file() { printf '%s/%s' "$PRACTICE_LOGINS" "$1"; }

# Reads a space's record into SPACE_* variables. The file is root's; every value is checked again.
load_space() {
  local slug=$1 file
  file=$(space_file "$slug")
  [ -r "$file" ] || pl_die "no practice space '$slug'"
  SPACE_NAME_B64="" SPACE_ADMIN_LOGIN="" SPACE_ADDONS="" SPACE_LANG="" SPACE_CREATED_AT="" SPACE_RESET_AT=""
  SPACE_TEMPLATE_ID="" SPACE_RESET_GEN=0 SPACE_FIRST_ADMIN_HASH=""
  local key value
  while IFS='=' read -r key value; do
    value=${value#\'}
    value=${value%\'}
    case "$key" in
      NAME_B64) [[ $value =~ ^[A-Za-z0-9+/=]*$ ]] && SPACE_NAME_B64=$value ;;
      ADMIN_LOGIN) valid_login "$value" && SPACE_ADMIN_LOGIN=$value ;;
      ADDONS) [[ $value =~ ^([a-z][a-z0-9_]*(,[a-z][a-z0-9_]*)*)?$ ]] && SPACE_ADDONS=$value ;;
      LANG) valid_lang "$value" && SPACE_LANG=$value ;;
      CREATED_AT) [[ $value =~ ^[0-9TZ:-]{20}$ ]] && SPACE_CREATED_AT=$value ;;
      RESET_AT) [[ $value =~ ^[0-9TZ:-]{20}$ ]] && SPACE_RESET_AT=$value ;;
      TEMPLATE_ID) [[ $value =~ ^[0-9a-f]{32}$ ]] && SPACE_TEMPLATE_ID=$value ;;
      RESET_GEN) [[ $value =~ ^[0-9]{1,9}$ ]] && SPACE_RESET_GEN=$value ;;
      FIRST_ADMIN_HASH) [[ $value =~ ^[0-9a-f]{64}$ ]] && SPACE_FIRST_ADMIN_HASH=$value ;;
    esac
  done < "$file"
  [ -n "$SPACE_ADMIN_LOGIN" ] && [ -n "$SPACE_TEMPLATE_ID" ] || pl_die "the record of space '$slug' is damaged: $file"
}

write_space() {
  local slug=$1 file tmp
  file=$(space_file "$slug")
  mkdir -p "$PRACTICE_SPACES"
  tmp=$(mktemp "$PRACTICE_SPACES/.$slug.XXXXXX")
  {
    printf "SLUG='%s'\nNAME_B64='%s'\nADMIN_LOGIN='%s'\nADDONS='%s'\nLANG='%s'\n" \
      "$slug" "$SPACE_NAME_B64" "$SPACE_ADMIN_LOGIN" "$SPACE_ADDONS" "$SPACE_LANG"
    printf "CREATED_AT='%s'\nRESET_AT='%s'\nTEMPLATE_ID='%s'\n" "$SPACE_CREATED_AT" "$SPACE_RESET_AT" "$SPACE_TEMPLATE_ID"
    printf "RESET_GEN='%s'\nFIRST_ADMIN_HASH='%s'\n" "${SPACE_RESET_GEN:-0}" "${SPACE_FIRST_ADMIN_HASH:-}"
  } > "$tmp"
  chmod 640 "$tmp"
  mv -f "$tmp" "$file"
}

list_spaces() {
  local file slug
  for file in "$PRACTICE_SPACES"/*.env; do
    [ -e "$file" ] || continue
    slug=$(basename "$file" .env)
    valid_slug "$slug" && printf '%s\n' "$slug"
  done
}

template_id() { sed -n "s/^TEMPLATE_ID='\([0-9a-f]\{32\}\)'$/\1/p" "$PRACTICE_VAR/template.env" 2>/dev/null || true; }

# ---------------------------------------------------------------------------- progress of an update

# How far an update has gone, for the control room's Status page. One small file, closed words only:
# a step number, a step code, the space concerned, and on failure a reason code. Never a free text.
# practice-heartbeat reads it, and is started at once so the control room learns within seconds
# (one start per step change, never in a loop: the control room limits heartbeats per minute).
readonly PROGRESS_CODES="download copy space start template done"
readonly PROGRESS_REASONS="download digest bundle busy leftover copy space_update no_answer template other"

# progress_write <target> <step> <total> <code> [slug] [reason]    a reason means: it failed
progress_write() {
  local target=$1 step=$2 total=$3 code=$4 slug=${5:-} reason=${6:-} failed=0 tmp
  [[ $target =~ ^[0-9a-f]{7,40}$ && $step =~ ^[0-9]{1,3}$ && $total =~ ^[0-9]{1,3}$ ]] || return 0
  case " $PROGRESS_CODES " in *" $code "*) ;; *) return 0 ;; esac
  if [ -n "$slug" ] && ! valid_slug "$slug"; then slug=""; fi
  if [ -n "$reason" ]; then
    failed=1
    case " $PROGRESS_REASONS " in *" $reason "*) ;; *) reason=other ;; esac
  fi
  mkdir -p "$PRACTICE_STATUS" 2>/dev/null || return 0
  tmp=$(mktemp "$PRACTICE_STATUS/.progress.XXXXXX" 2>/dev/null) || return 0
  if printf "TARGET='%s'\nSTEP='%s'\nTOTAL='%s'\nCODE='%s'\nSLUG='%s'\nFAILED='%s'\nREASON='%s'\nAT='%s'\n" \
       "$target" "$step" "$total" "$code" "$slug" "$failed" "$reason" "$(now_utc)" > "$tmp" \
     && chmod 644 "$tmp" && mv -f "$tmp" "$PRACTICE_STATUS/progress"; then
    progress_tell
  else
    rm -f "$tmp"
  fi
  return 0
}

# Starts the heartbeat without waiting for it. Nothing here may stop an update: every failure is ignored.
# Not under a test prefix: a dry run contacts nothing.
progress_tell() {
  [ -z "$PRACTICE_PREFIX" ] || return 0
  systemctl start --no-block practice-heartbeat.service >/dev/null 2>&1 || true
}

# True when the progress file says the update to this release failed.
progress_failed_for() {
  local sha=$1 target
  [ -r "$PRACTICE_STATUS/progress" ] || return 1
  grep -qx "FAILED='1'" "$PRACTICE_STATUS/progress" || return 1
  target=$(sed -n "s/^TARGET='\([0-9a-f]\{7,40\}\)'$/\1/p" "$PRACTICE_STATUS/progress")
  [ -n "$target" ] || return 1
  [[ $sha == "$target"* ]] || [[ $target == "$sha"* ]]
}

# ---------------------------------------------------------------------------- PostgreSQL

psql_q() { runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -At -d "${2:-postgres}" -c "$1"; }
db_exists() { [ -n "$(psql_q "SELECT 1 FROM pg_database WHERE datname = '$1'")" ]; }
terminate_connections() { psql_q "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$1' AND pid <> pg_backend_pid()" >/dev/null; }

# Every database of the cluster but PostgreSQL's own.
cluster_databases() { psql_q "SELECT datname FROM pg_database WHERE datname NOT IN ('postgres', 'template0', 'template1') ORDER BY 1"; }

# ---------------------------------------------------------------------------- Odoo

current_release() { if [ -L "$PRACTICE_CURRENT" ]; then basename "$(readlink -f "$PRACTICE_CURRENT")"; fi; }

# odoo_run <database> <log> <odoo args...>: a one-off Odoo run on the current code, under a memory
# ceiling so it cannot squeeze the service, as the odoo user.
odoo_run() {
  local db=$1 log=$2
  shift 2
  systemd-run --quiet --scope --collect -p "MemoryMax=$PRACTICE_UPDATE_MEM" -p MemorySwapMax=2G \
    nice -n 10 runuser -u "$ODOO_USER" -- "$ODOO_PY" "$ODOO_BIN" -c "$ODOO_CONF" -d "$db" --db-filter="^$db\$" \
    --no-http --max-cron-threads=0 --workers=0 --stop-after-init --logfile="$log" "$@"
}

# odoo_shell <database> <log> [NAME=value ...], the script on stdin. The values are for names and
# settings only: a secret travels on stdin, never in argv or the environment.
odoo_shell() {
  local db=$1 log=$2
  shift 2
  systemd-run --quiet --scope --collect -p "MemoryMax=$PRACTICE_UPDATE_MEM" -p MemorySwapMax=2G \
    nice -n 10 runuser -u "$ODOO_USER" -- env "$@" "$ODOO_PY" "$ODOO_BIN" shell -c "$ODOO_CONF" -d "$db" --db-filter="^$db\$" \
    --no-http --max-cron-threads=0 --logfile="$log"
}

log_has_errors() { grep -qE ' (ERROR|CRITICAL) ' "$1"; }
show_errors() { grep -E ' (ERROR|CRITICAL) ' "$1" | tail -n 5 | cut -c1-300 >&2 || true; }

# The installable addons of a release, except the control room's (never on this computer).
release_addons() {
  "$ODOO_PY" -I - "$1" <<'PY'
import ast
import pathlib
import sys

for manifest in sorted(pathlib.Path(sys.argv[1]).glob("*/__manifest__.py")):
    data = ast.literal_eval(manifest.read_text(encoding="utf-8"))
    name = manifest.parent.name
    if name.startswith("ea_platform_"):
        continue
    if data.get("installable", True) and (manifest.parent / "__init__.py").is_file():
        print(name)
PY
}

# The optional client add-ons of a release: what a firm can switch on, and so a space too.
optional_addons() {
  "$ODOO_PY" -I - "$1" <<'PY'
import ast
import pathlib
import sys

for manifest in sorted(pathlib.Path(sys.argv[1]).glob("*/__manifest__.py")):
    data = ast.literal_eval(manifest.read_text(encoding="utf-8"))
    name = manifest.parent.name
    if (data.get("ea_client_addon") is True and data.get("installable", True)
            and (manifest.parent / "__init__.py").is_file() and not name.startswith("ea_platform_")):
        print(name)
PY
}

# The firm addons every space has, from the template: base, web, mail and each ea_audit_* addon.
base_addons() {
  local addons=base,web,mail name
  while read -r name; do
    case "$name" in ea_audit_*) addons="$addons,$name" ;; esac
  done < <(release_addons "$1")
  printf '%s' "$addons"
}

# Health of one space through Odoo itself, with the host name that selects it.
space_answers() {
  local slug=$1 code
  code=$(curl -s --max-time 90 -o /dev/null -w '%{http_code}' "$(space_local_url "$slug")/web/login" || true)
  [ "$code" = 200 ]
}

service_healthy() {
  local i code=""
  for ((i = 1; i <= ${HEALTH_ATTEMPTS:-40}; i++)); do
    code=$(curl -s --max-time 10 -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PRACTICE_PORT/web/health" || true)
    [ "$code" != 200 ] || return 0
    sleep 3
  done
  pl_warn "the practice service does not answer on port $PRACTICE_PORT (last: ${code:-none})"
  return 1
}

# Tells the running service that a space's settings changed under it (its caches reload).
signal_space() {
  psql_q "INSERT INTO orm_signaling_registry DEFAULT VALUES" "$(space_db "$1")" >/dev/null
}

audit_line() {
  mkdir -p "$PRACTICE_LOGS"
  printf '%s %s %s\n' "$(now_utc)" "${SCRIPT_NAME:-practice}" "$*" >> "$PRACTICE_LOGS/actions.log"
}

# The Python packages the addons need beyond Odoo's own: the release's requirements.txt, pinned, held to
# the versions Odoo pins (2026-11-20). Never fails an install or an update (see deploy/firm/firm-lib.sh).
install_python_extras() {
  local release=$1 req constraints
  req=$release/requirements.txt
  if [ ! -f "$req" ] || ! grep -qE '^[A-Za-z]' "$req"; then return 0; fi
  if [ ! -x /usr/local/bin/uv ]; then pl_warn "uv is missing: the extra Python packages are not installed"; return 0; fi
  constraints=$(mktemp /tmp/odoo-constraints.XXXXXX)
  sed -E 's/^psycopg2\b/psycopg2-binary/' /opt/odoo19/src/requirements.txt > "$constraints" 2>/dev/null || :
  if timeout 600 /usr/local/bin/uv pip install -q --python "$ODOO_PY" -r "$req" -c "$constraints" 7>&-; then
    chmod -R a+rX /opt/odoo19/venv 2>/dev/null || :
    pl_log "extra Python packages installed ($req)"
  else
    pl_warn "the extra Python packages could not be installed: the features that need them say so"
  fi
  rm -f "$constraints"
}
