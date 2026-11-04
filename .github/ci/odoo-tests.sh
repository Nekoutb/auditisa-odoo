#!/usr/bin/env bash
# Installs the repository's addons on a new database with --test-enable and runs their tests.
# Before any addon exists, it initialises a base database instead, which proves Odoo starts.
set -euo pipefail

SRC=/opt/odoo19/src
LOG=${RUNNER_TEMP:-/tmp}/odoo-tests.log

mapfile -t addons < <(find addons -mindepth 2 -maxdepth 2 -name __manifest__.py -printf '%h\n' 2>/dev/null | xargs -r -n1 basename | sort)

odoo_args=(
  --addons-path="$SRC/addons,$SRC/odoo/addons"
  --db_host=localhost --db_port=5432 --db_user=odoo --db_password="$ODOO_DB_PASSWORD"
  -d ci_test --stop-after-init --max-cron-threads=0 --logfile="$LOG"
)

if [ ${#addons[@]} = 0 ]; then
  echo "No addon yet: initialising a base database."
  odoo_args+=(-i base)
else
  list=$(IFS=,; echo "${addons[*]}")
  tags=$(printf '/%s,' "${addons[@]}")
  echo "Installing and testing: $list"
  # The test tags keep Odoo from running the tests of base, web, mail and the other dependencies.
  odoo_args[0]="--addons-path=$PWD/addons,$SRC/addons,$SRC/odoo/addons"
  odoo_args+=(-i "$list" --test-enable --test-tags="${tags%,}" --http-port=8069)
fi

rc=0
/opt/odoo19/venv/bin/python "$SRC/odoo-bin" "${odoo_args[@]}" || rc=$?

grep -E 'odoo\.tests\.(stats|result)|tests in ' "$LOG" | tail -n 10 || true
# A failing test or a broken data file does not always change the exit code, so the log decides too.
if [ "$rc" != 0 ] || grep -qE ' (ERROR|CRITICAL) ' "$LOG"; then
  echo "Odoo exit code: $rc"
  grep -E -A25 ' (ERROR|CRITICAL) ' "$LOG" | tail -n 150 || tail -n 50 "$LOG"
  exit 1
fi
# A clean log alone is not enough: the registry must have loaded.
loaded=$(grep -E 'Registry loaded|Modules loaded' "$LOG" | tail -n 2 | cut -c1-160) || true
if [ -z "$loaded" ]; then
  echo "Odoo never loaded a registry"
  tail -n 50 "$LOG"
  exit 1
fi
echo "$loaded"
echo "Odoo finished without errors."
