#!/usr/bin/env bash
# Installs the repository's addons on a new database with --test-enable and runs their tests.
# Before any addon exists, it initialises a base database instead, which proves Odoo starts.
#
# Two databases, as in real life: the firm's addons together, and the control plane's addon alone.
# ea_platform_admin refuses to install beside any ea_audit_* addon.
set -euo pipefail

SRC=/opt/odoo19/src

mapfile -t all_addons < <(find addons -mindepth 2 -maxdepth 2 -name __manifest__.py -printf '%h\n' 2>/dev/null | xargs -r -n1 basename | sort)
firm_addons=()
platform_addons=()
for addon in "${all_addons[@]}"; do
  case "$addon" in
    ea_platform_*) platform_addons+=("$addon") ;;
    *) firm_addons+=("$addon") ;;
  esac
done

# run_tests <database> <addon>...
run_tests() {
  local database=$1
  shift
  local log=${RUNNER_TEMP:-/tmp}/odoo-tests-$database.log
  local odoo_args=(
    --addons-path="$SRC/addons,$SRC/odoo/addons"
    --db_host=localhost --db_port=5432 --db_user=odoo --db_password="$ODOO_DB_PASSWORD"
    -d "$database" --db-filter="^$database\$" --stop-after-init --max-cron-threads=0 --logfile="$log"
  )
  if [ $# = 0 ]; then
    echo "No addon yet: initialising a base database."
    odoo_args+=(-i base)
  else
    local list tags
    list=$(IFS=,; echo "$*")
    tags=$(printf '/%s,' "$@")
    echo "Installing and testing on $database: $list"
    # The test tags keep Odoo from running the tests of base, web, mail and the other dependencies.
    odoo_args[0]="--addons-path=$PWD/addons,$SRC/addons,$SRC/odoo/addons"
    odoo_args+=(-i "$list" --test-enable --test-tags="${tags%,}" --http-port=8069)
  fi

  local rc=0
  /opt/odoo19/venv/bin/python "$SRC/odoo-bin" "${odoo_args[@]}" || rc=$?

  grep -E 'odoo\.tests\.(stats|result)|tests in ' "$log" | tail -n 10 || true
  # A failing test or a broken data file does not always change the exit code, so the log decides too.
  # Two tests of ea_audit_firm_agent log an error on purpose, under their own logger name: not a failure.
  if [ "$rc" != 0 ] || grep -E ' (ERROR|CRITICAL) ' "$log" | grep -qvF ' odoo.addons.ea_audit_firm_agent.tests: '; then
    echo "Odoo exit code: $rc"
    grep -E -A60 ' (ERROR|CRITICAL) ' "$log" | tail -n 200 || tail -n 50 "$log"
    exit 1
  fi
  # A clean log alone is not enough: the registry must have loaded.
  local loaded
  loaded=$(grep -E 'Registry loaded|Modules loaded' "$log" | tail -n 2 | cut -c1-160) || true
  if [ -z "$loaded" ]; then
    echo "Odoo never loaded a registry"
    tail -n 50 "$log"
    exit 1
  fi
  echo "$loaded"
  echo "Odoo finished without errors on $database."
}

run_tests ci_test "${firm_addons[@]}"
if [ ${#platform_addons[@]} != 0 ]; then
  run_tests ci_platform "${platform_addons[@]}"
fi
