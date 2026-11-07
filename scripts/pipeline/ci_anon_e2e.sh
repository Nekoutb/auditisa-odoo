#!/usr/bin/env bash
# ci_anon_e2e.sh: end-to-end proof of the anonymiser, on throwaway databases. On a server, as root.
#
#   ci_anon_e2e.sh SOURCE_DB TOOL_DIR
#
# SOURCE_DB is read only (pg_dump) and must hold demo data. TOOL_DIR holds this repository's deploy/firm and
# scripts/pipeline. Everything it creates is named ci_pipeline_*, or sits in a temporary folder, and goes
# at the end. Prints a line per check, and the totals. A value planted here is fictional.

set -uo pipefail
SOURCE=${1:?source database}
TOOL=${2:?tool folder}
PY=${ODOO_PY:-/opt/odoo19/venv/bin/python}
PREFIX=$(mktemp -d /tmp/ci_pipeline_prefix.XXXXXX)
SRC=ci_pipeline_src
LOG=$PREFIX/log
PASS=0 FAIL=0

ok() { PASS=$((PASS + 1)); printf 'ok    %s\n' "$*"; }
bad() { FAIL=$((FAIL + 1)); printf 'FAIL  %s\n' "$*"; }
pg() { runuser -u postgres -- psql -X -q -v ON_ERROR_STOP=1 "$@"; }
q() { runuser -u postgres -- psql -X -At -v ON_ERROR_STOP=1 -d "$1" -c "$2"; }
cleanup() {
  for db in $(q postgres "SELECT datname FROM pg_database WHERE datname LIKE 'ci\_pipeline\_%' AND datname <> 'ci_pipeline_cp' AND datname <> 'ci_pipeline_stg'"); do
    q postgres "DROP DATABASE \"$db\" WITH (FORCE)" >/dev/null
  done
  rm -rf "$PREFIX"
}
trap cleanup EXIT

mkdir -p "$PREFIX/etc/auditisa-firm/secrets" "$PREFIX/var/lib/auditisa-firm/status" "$PREFIX/var/log/auditisa-firm" "$PREFIX/opt"
touch "$PREFIX/var/log/auditisa-firm/break-glass.log"
chmod 755 "$PREFIX"
env_file() {
  cat > "$PREFIX/etc/auditisa-firm/firm.env" <<EOF
FIRM_SLUG=ci-firm
FIRM_HOST=ci.invalid
FIRM_DB=$1
ANON_EXPORT_ALLOWED=$2
EOF
}
export FIRM_PREFIX=$PREFIX ANON_TOOL_DIR=$TOOL/deploy/firm ANON_DB_PREFIX=ci_pipeline_anon_ ANON_LOCK=$PREFIX/lock ODOO_PY=$PY TMPDIR=$PREFIX
EXPORT=$TOOL/deploy/firm/firm-anon-export.sh
OUT=$PREFIX/var/lib/auditisa-firm/anon-exports
status() { cat "$PREFIX/var/lib/auditisa-firm/status/$1" 2>/dev/null; }
new_ref() { openssl rand -hex 8; }
copy_of() { # A fresh database from the planted one: name, then SQL to spoil it.
  q postgres "DROP DATABASE IF EXISTS \"$1\" WITH (FORCE)" >/dev/null
  q postgres "CREATE DATABASE \"$1\" TEMPLATE \"$SRC\"" >/dev/null
  [ -z "${2:-}" ] || q "$1" "$2" >/dev/null
}
no_copy_left() { [ -z "$(q postgres "SELECT 1 FROM pg_database WHERE datname LIKE 'ci\_pipeline\_anon\_%'")" ]; }
must_stop() { # name, expected word in the output, database
  local name=$1 word=$2 db=$3 ref rc
  ref=$(new_ref)
  env_file "$db" 1
  bash "$EXPORT" "$ref" > "$LOG" 2>&1
  rc=$?
  if [ "$rc" = 0 ]; then bad "$name: the export went through"; return; fi
  if grep -q "$word" "$LOG"; then ok "$name: stopped ($word)"; else bad "$name: stopped, but not for $word"; sed -n 1,5p "$LOG" | cut -c1-120; fi
  if [ -e "$OUT/anon-$ref.tar" ]; then bad "$name: a file stayed"; else ok "$name: no file left"; fi
  if no_copy_left; then ok "$name: no copy left"; else bad "$name: a copy stayed"; fi
  [ "$(status anon_export_state)" = failed ] && ok "$name: reports failed" || bad "$name: reports $(status anon_export_state)"
}

free -m | sed -n 2p
echo "== planting in a throwaway copy of the demo data"
q postgres "DROP DATABASE IF EXISTS $SRC WITH (FORCE)" >/dev/null
q postgres "CREATE DATABASE $SRC" >/dev/null
runuser -u postgres -- pg_dump --format=custom --no-owner --no-acl "$SOURCE" | runuser -u postgres -- pg_restore --no-owner --no-acl --exit-on-error -d "$SRC" 2>&1 | tail -n 2
AMOUNTS="SELECT (SELECT count(*) FROM ea_audit_gl_line), (SELECT coalesce(sum(debit),0) FROM ea_audit_gl_line), (SELECT coalesce(sum(credit),0) FROM ea_audit_gl_line), (SELECT count(*) FROM ea_audit_tb_line), (SELECT coalesce(sum(closing),0) FROM ea_audit_tb_line), (SELECT count(*) FROM ea_audit_dataset_row), (SELECT count(*) FROM ea_audit_engagement)"
if ! q "$SRC" "$AMOUNTS" > "$PREFIX/figures.before"; then bad "the figures query did not run"; fi

runuser -u postgres -- "$PY" -I "$TOOL/scripts/pipeline/anon_plant.py" --db "$SRC" --manifest "$TOOL/deploy/firm/anon-manifest.json" | tee "$PREFIX/planted.json"

echo "== a firm that has not allowed it"
env_file "$SRC" 0
REF=$(new_ref)
if bash "$EXPORT" "$REF" > "$LOG" 2>&1; then bad "refused without ANON_EXPORT_ALLOWED"; else ok "refused without ANON_EXPORT_ALLOWED"; fi
[ "$(status anon_export_state)" = refused ] && ok "reports refused" || bad "reports $(status anon_export_state)"

echo "== the export itself, with everything planted"
env_file "$SRC" 1
REF=$(new_ref)
if bash "$EXPORT" "$REF" > "$LOG" 2>&1; then
  ok "the export finished"
else
  bad "the export stopped"; cut -c1-150 "$LOG" | tail -n 90
fi
TAR=$OUT/anon-$REF.tar
if [ -f "$TAR" ]; then
  LISTING=$(tar -tf "$TAR" | sort | tr '\n' ' ')
  [ "$LISTING" = "ANON-REPORT.json SHA256SUMS db.dump " ] && ok "the file holds db.dump, the report and digests, no filestore" || bad "listing: $LISTING"
  [ "$(status anon_export_state)" = done ] && ok "reports done" || bad "reports $(status anon_export_state)"
  [ "$(status anon_export_sha256)" = "$(sha256sum "$TAR" | cut -d' ' -f1)" ] && ok "reports the file's digest" || bad "digest"
  [ "$(status anon_export_ref)" = "$REF" ] && ok "reports the reference" || bad "reference"
  [ "$(stat -c %a "$TAR")" = 600 ] && ok "root only" || bad "mode $(stat -c %a "$TAR")"
  no_copy_left && ok "no copy left" || bad "a copy stayed"
  mkdir -p "$PREFIX/x"; chmod 755 "$PREFIX/x"; tar -xf "$TAR" -C "$PREFIX/x"; chmod 644 "$PREFIX/x"/*
  (cd "$PREFIX/x" && sha256sum -c --status SHA256SUMS) && ok "digests hold" || bad "digests"
  runuser -u postgres -- pg_restore --file=- "$PREFIX/x/db.dump" > "$PREFIX/plain.sql"
  echo "   plain dump: $(wc -c < "$PREFIX/plain.sql") bytes"
  for word in planted dupont mbarga 012345678901 '699 12 34 56' 'RC/DLA/2021' planted-client; do
    n=$(grep -ci -- "$word" "$PREFIX/plain.sql" || true)
    [ "$n" = 0 ] && ok "no '$word' anywhere in the dump" || { bad "'$word' on $n lines"; grep -i -- "$word" "$PREFIX/plain.sql" | cut -c1-100 | head -n 3; }
  done
  n=$(grep -ci -E 'planted|dupont|012345678901' "$LOG" || true)
  [ "$n" = 0 ] && ok "the tool's own output names nothing" || bad "its output has $n such lines"
  # Restored, and asked directly, table by table.
  RESTORED=ci_pipeline_chk
  q postgres "CREATE DATABASE $RESTORED" >/dev/null
  runuser -u postgres -- pg_restore --no-owner --no-acl --exit-on-error -d "$RESTORED" "$PREFIX/x/db.dump" 2>&1 | tail -n 2
  q "$RESTORED" "$AMOUNTS" > "$PREFIX/figures.after"
  if cmp -s "$PREFIX/figures.before" "$PREFIX/figures.after"; then ok "figures kept: $(cat "$PREFIX/figures.after")"; else bad "figures moved: $(cat "$PREFIX/figures.before") -> $(cat "$PREFIX/figures.after")"; fi
  for t in ir_attachment mail_message mail_tracking_value mail_mail mail_activity ir_logging ea_audit_firm_log res_users_log res_device_log auth_totp_device res_users_apikeys ea_firm_access_log; do
    n=$(q "$RESTORED" "SELECT count(*) FROM $t")
    [ "$n" = 0 ] && ok "$t is empty" || bad "$t holds $n rows"
  done
  n=$(q "$RESTORED" "SELECT count(*) FROM ea_audit_paper_answer WHERE value LIKE '[anon %'")
  [ "$n" -ge 50 ] && ok "answers replaced: $n" || bad "answers replaced: $n"
  n=$(q "$RESTORED" "SELECT count(*) FROM ea_audit_paper_answer WHERE value = 'yes'")
  [ "$n" -gt 0 ] && ok "yes and no answers kept: $n" || bad "no yes answer left"
  n=$(q "$RESTORED" "SELECT count(*) FROM res_users WHERE password IS NOT NULL")
  [ "$n" = 0 ] && ok "no password kept" || bad "$n passwords kept"
  n=$(q "$RESTORED" "SELECT count(*) FROM res_partner WHERE email IS NOT NULL AND email <> '' AND email NOT LIKE '%@anon.invalid'")
  [ "$n" = 0 ] && ok "every partner email is @anon.invalid" || bad "$n partner emails kept"
  n=$(q "$RESTORED" "SELECT count(*) FROM ir_config_parameter WHERE key IN ('database.secret', 'database.uuid', 'web.base.url')")
  [ "$n" = 0 ] && ok "the firm's database secret and address are gone" || bad "$n such parameters kept"
  [ "$(q "$RESTORED" "SELECT value FROM ir_config_parameter WHERE key = 'ea_audit.anonymised'")" = 1 ] && ok "carries the anonymised mark" || bad "no anonymised mark"
  q postgres "DROP DATABASE $RESTORED WITH (FORCE)" >/dev/null
  if [ -n "${KEEP_DUMP_TO:-}" ]; then cp "$TAR" "$KEEP_DUMP_TO"; chmod 600 "$KEEP_DUMP_TO"; fi
fi

echo "== what must stop the export"
copy_of ci_pipeline_n1 'CREATE TABLE x_unlisted (id serial PRIMARY KEY, note text)'
must_stop "a table not on the list" unlisted-table ci_pipeline_n1
copy_of ci_pipeline_n2 'ALTER TABLE ea_audit_client ADD COLUMN x_note text'
must_stop "a text column not on the list" unlisted-column ci_pipeline_n2
copy_of ci_pipeline_n3 "INSERT INTO ir_model (model, name, state, \"order\") VALUES ('x.unlisted', '{\"en_US\": \"x\"}', 'manual', 'id')"
must_stop "a model not on the list" unlisted-model ci_pipeline_n3
copy_of ci_pipeline_n4 'CREATE MATERIALIZED VIEW x_copy AS SELECT name FROM ea_audit_client'
must_stop "a materialised view" unlisted-relation ci_pipeline_n4
copy_of ci_pipeline_n5 "UPDATE ir_ui_menu SET name = '{\"en_US\": \"Societe Planted Agro SA\"}' WHERE id = (SELECT min(id) FROM ir_ui_menu)"
must_stop "the client's name in a table kept as it is" survivors ci_pipeline_n5
copy_of ci_pipeline_n6 "UPDATE mail_template SET email_from = 'someone@another-client.cm' WHERE id = (SELECT min(id) FROM mail_template)"
must_stop "an unknown email in a table kept as it is" survivors ci_pipeline_n6
copy_of ci_pipeline_n7 "UPDATE ir_module_module SET summary = '{\"en_US\": \"NIU P987654321098Z\"}' WHERE id = (SELECT min(id) FROM ir_module_module)"
must_stop "a tax number in a table kept as it is" survivors ci_pipeline_n7

printf 'TOTAL: %s passed, %s failed\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ]
