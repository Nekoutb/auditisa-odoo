#!/usr/bin/env bash
# ci_base.sh: a throwaway database on this release's schema, with demo data. On a server, as root.
#
#   ci_base.sh TOOL_DIR [SOURCE_DB]
#
# ci_pipeline_base is a copy of SOURCE_DB (default uat_copy, read only) with this release's addons updated, and
# its inventory written to TOOL_DIR/inventory/, for scripts/pipeline/anon_manifest_gen.py. No outside mail: the
# update runs with no cron and no HTTP.

set -euo pipefail
TOOL=${1:?tool folder}
SOURCE=${2:-uat_copy}
BASE=ci_pipeline_base
GEN=$TOOL/scripts/pipeline/anon_manifest_gen.py
OUT=$TOOL/inventory
PY=/opt/odoo19/venv/bin/python
q() { runuser -u postgres -- psql -X -v ON_ERROR_STOP=1 -At "$@"; }

free -m | sed -n 2p
q -d postgres -c "DROP DATABASE IF EXISTS $BASE WITH (FORCE)" >/dev/null
q -d postgres -c "CREATE DATABASE $BASE OWNER odoo" >/dev/null
runuser -u postgres -- pg_dump --format=custom --no-owner --no-acl "$SOURCE" | runuser -u postgres -- pg_restore --no-owner --role=odoo --exit-on-error -d "$BASE"

CONF=$(mktemp /tmp/ci_pipeline_base.XXXXXX.conf)
trap 'rm -f "$CONF"' EXIT
sed -e "s#^addons_path *=.*#addons_path = $TOOL/addons,/opt/ea-odoo-addons,/opt/odoo19/src/odoo/addons#" \
    -e "s#^db_name *=.*#db_name = $BASE#" -e "s#^dbfilter *=.*#dbfilter = ^$BASE\$#" \
    -e "s#^logfile *=.*#logfile = /tmp/ci_pipeline_base.log#" -e "s#^data_dir *=.*#data_dir = /tmp/ci_pipeline_data#" /etc/odoo/uat_copy.conf > "$CONF"
chgrp odoo "$CONF"; chmod 640 "$CONF"
mkdir -p /tmp/ci_pipeline_data; chown odoo /tmp/ci_pipeline_data
: > /tmp/ci_pipeline_base.log; chown odoo /tmp/ci_pipeline_base.log
MODULES=$(q -d "$BASE" -c "SELECT string_agg(name, ',') FROM ir_module_module WHERE state = 'installed' AND name LIKE 'ea\\_audit%'")
runuser -u odoo -- "$PY" /opt/odoo19/src/odoo-bin -c "$CONF" -d "$BASE" -u "$MODULES" --no-http --max-cron-threads=0 --workers=0 --stop-after-init --logfile=/tmp/ci_pipeline_base.log
echo "update errors: $(grep -cE ' (ERROR|CRITICAL) ' /tmp/ci_pipeline_base.log || true)"
grep -E ' (ERROR|CRITICAL) ' /tmp/ci_pipeline_base.log | cut -c1-200 | head -n 5 || true

mkdir -p "$OUT"
"$PY" -I - "$GEN" "$OUT/columns.sql" "$OUT/selections.sql" <<'PY'
import re, sys
source = open(sys.argv[1], encoding="utf-8").read()
for name, path in (("COLUMNS_SQL", sys.argv[2]), ("SELECTIONS_SQL", sys.argv[3])):
    open(path, "w", encoding="utf-8").write(re.search(name + r' = """(.*?)"""', source, re.S).group(1))
PY
runuser -u postgres -- psql -X -At -F$'\t' -d "$BASE" < "$OUT/columns.sql" > "$OUT/columns.tsv"
runuser -u postgres -- psql -X -At -F$'\t' -d "$BASE" < "$OUT/selections.sql" > "$OUT/selections.tsv"
q -d "$BASE" -c "SELECT model FROM ir_model ORDER BY 1" > "$OUT/models.txt"
wc -l "$OUT"/columns.tsv "$OUT"/selections.tsv "$OUT"/models.txt
echo "BASE DONE"
