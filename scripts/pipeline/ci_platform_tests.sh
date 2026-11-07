#!/usr/bin/env bash
# ci_platform_tests.sh: the Odoo tests of the two control-plane addons, on a throwaway database. On a server, as root.
#
#   ci_platform_tests.sh TOOL_DIR [--keep]
#
# Installs ea_platform_admin and ea_platform_pipeline in ci_pipeline_cp and runs their tests. Writes the French
# template to TOOL_DIR/pipeline.pot. No audit addon is on its addons path, as on the real control plane.
# --keep leaves the database for a look through a tunnel; otherwise it goes.

set -uo pipefail
TOOL=${1:?tool folder}
KEEP=${2:-}
DB=ci_pipeline_cp
LOG=/tmp/ci_pipeline_cp.log
PY=/opt/odoo19/venv/bin/python
q() { runuser -u postgres -- psql -X -At -d postgres -c "$1"; }

free -m | sed -n 2p
q "DROP DATABASE IF EXISTS $DB WITH (FORCE)" >/dev/null
q "CREATE DATABASE $DB OWNER odoo" >/dev/null
ADDONS=/tmp/ci_pipeline_cp_addons
rm -rf "$ADDONS"; mkdir -p "$ADDONS"
cp -r "$TOOL/addons/ea_platform_admin" "$TOOL/addons/ea_platform_pipeline" "$ADDONS/"
chmod -R a+rX "$ADDONS"
CONF=$(mktemp /tmp/ci_pipeline_cp.XXXXXX.conf)
sed -e "s#^addons_path *=.*#addons_path = $ADDONS,/opt/odoo19/src/odoo/addons#" \
    -e "s#^db_name *=.*#db_name = $DB#" -e "s#^dbfilter *=.*#dbfilter = ^$DB\$#" \
    -e "s#^logfile *=.*#logfile = $LOG#" -e "s#^data_dir *=.*#data_dir = /tmp/ci_pipeline_data#" /etc/odoo/uat_copy.conf > "$CONF"
chgrp odoo "$CONF"; chmod 640 "$CONF"
mkdir -p /tmp/ci_pipeline_data; chown odoo /tmp/ci_pipeline_data
: > "$LOG"; chown odoo "$LOG"
run() { runuser -u odoo -- "$PY" /opt/odoo19/src/odoo-bin -c "$CONF" -d "$DB" --no-http --max-cron-threads=0 --workers=0 --stop-after-init --logfile="$LOG" "$@"; }
if ! grep -q '^\[options\]' "$CONF"; then echo "no conf"; exit 2; fi

run -i ea_platform_admin,ea_platform_pipeline --without-demo=True --load-language=fr_FR
echo "install exit $?; errors: $(grep -cE ' (ERROR|CRITICAL) ' "$LOG")"
grep -E ' (ERROR|CRITICAL) ' "$LOG" | cut -c1-220 | head -n 8
: > "$LOG"
sed -i -e 's/^http_port *=.*/http_port = 8097/' -e 's/^gevent_port *=.*/gevent_port = 8098/' "$CONF"
grep -q '^http_port' "$CONF" || echo 'http_port = 8097' >> "$CONF"
runuser -u odoo -- "$PY" /opt/odoo19/src/odoo-bin -c "$CONF" -d "$DB" --max-cron-threads=0 --workers=0 --stop-after-init --logfile="$LOG" \
  --http-port=8097 --gevent-port=8098 --test-enable --test-tags "${TEST_TAGS:-/ea_platform_pipeline,/ea_platform_admin}" -u ea_platform_pipeline
echo "tests exit $?"
grep -E 'tests in|failed, |odoo.tests.result|: [0-9]+ tests' "$LOG" | tail -n 6 | cut -c1-200
grep -E ' (ERROR|CRITICAL) ' "$LOG" | cut -c1-260 | head -n 30
grep -E '^(FAIL|ERROR):|^Traceback|Error:|^AssertionError' "$LOG" | cut -c1-260 | sort | uniq -c | sort -rn | head -n 30
: > "$LOG"
run --i18n-export="$TOOL/pipeline.pot" --language=fr_FR --modules=ea_platform_pipeline 2>/dev/null || true
if [ "$KEEP" != --keep ]; then
  q "DROP DATABASE IF EXISTS $DB WITH (FORCE)" >/dev/null
  rm -rf "$ADDONS"
fi
rm -f "$CONF"
echo "PLATFORM TESTS DONE"
