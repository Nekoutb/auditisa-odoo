#!/usr/bin/env bash
# Rehearses scripts/provision and deploy/deploy-staging.sh on a throwaway GitHub runner. Runs as
# root. Builds what the staging server has (role without CREATEDB, odoo.conf, odoo.service), then
# tests the success paths and every rollback path. Only ever touches this runner.
set -euo pipefail

WORK=$PWD
NEW_FIRM=$WORK/scripts/provision/new_firm.sh
BACKUP=$WORK/scripts/provision/backup_firm.sh
DEPLOY=$WORK/deploy/deploy-staging.sh
STAGING_DB=ea_audit_odoo_staging
REPO=/tmp/smoke-repo
ROOT=/opt/auditisa-odoo

export REPO_URL=$REPO EDGE_CHECK=0 HEALTH_ATTEMPTS=20
cd / # the odoo and postgres users cannot enter the runner's work folder

section() { printf '\n===== %s =====\n' "$*"; }
fail() { printf 'FAILED: %s\n' "$*" >&2; dump_logs; exit 1; }
dump_logs() {
  tail -n 40 /var/log/odoo/odoo.log 2>/dev/null >&2 || true
  journalctl -u odoo --no-pager -n 20 >&2 || true
}
q() { runuser -u postgres -- psql -XAt -d "$1" -c "$2"; }
assert_eq() { [ "$2" = "$3" ] || fail "$1: expected '$3', got '$2'"; }
current_sha() { sed -n 's/^sha=//p' "$ROOT/current/RELEASE"; }

section "Server baseline"
systemctl start postgresql
useradd --system --home-dir /opt/odoo19 --no-create-home --shell /bin/bash odoo
install -d -o odoo -g odoo /var/lib/odoo /var/log/odoo
install -d -o root -g odoo -m 750 /etc/odoo
DB_PASSWORD=$(openssl rand -hex 16)
q postgres "CREATE ROLE odoo LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD '$DB_PASSWORD'" >/dev/null
SRC=/opt/odoo19/src
cat > /etc/odoo/odoo.conf <<EOF
[options]
admin_passwd = $(openssl rand -hex 16)
db_host = localhost
db_user = odoo
db_password = $DB_PASSWORD
db_name = $STAGING_DB
dbfilter = ^$STAGING_DB\$
list_db = False
addons_path = $ROOT/current/addons,$SRC/addons,$SRC/odoo/addons
data_dir = /var/lib/odoo
logfile = /var/log/odoo/odoo.log
http_interface = 127.0.0.1
http_port = 8069
proxy_mode = True
workers = 0
max_cron_threads = 1
email_from = False
smtp_server = False
EOF
chown root:odoo /etc/odoo/odoo.conf
chmod 640 /etc/odoo/odoo.conf
cat > /etc/systemd/system/odoo.service <<EOF
[Unit]
After=network.target postgresql.service
Requires=postgresql.service
[Service]
User=odoo
ExecStart=/opt/odoo19/venv/bin/python $SRC/odoo-bin -c /etc/odoo/odoo.conf
Restart=on-failure
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload

section "new_firm.sh: guards"
if bash "$NEW_FIRM" --db "$STAGING_DB" --name x --admin-email a@example.invalid 2>/dev/null; then
  fail "new_firm.sh accepted the staging database"
fi
bash "$NEW_FIRM" --dry-run --db firm_smoke --name "Cabinet" --admin-email a@example.invalid | grep "DRY RUN"
assert_eq "dry-run writes nothing" "$(q postgres "SELECT count(*) FROM pg_database WHERE datname = 'firm_smoke'")" 0
[ ! -e /root/.auditisa/firms/firm_smoke.admin ] || fail "dry-run wrote the secret file"

section "new_firm.sh: real run"
NF_OUT=$(mktemp)
bash "$NEW_FIRM" --db firm_smoke --name "Cabinet d'Essai Douala" --admin-email admin@example.invalid \
  --addons base,web,mail 2>&1 | tee "$NF_OUT"
SECRET=/root/.auditisa/firms/firm_smoke.admin
assert_eq "secret file mode" "$(stat -c '%a %U' "$SECRET")" "600 root"
PW=$(sed -n 's/^password=//p' "$SECRET")
[ ${#PW} = 48 ] || fail "password length"
if grep -rqF "$PW" "$NF_OUT" /var/log/odoo/; then fail "the password reached the output or a log"; fi
assert_eq "firm name" "$(q firm_smoke "SELECT name FROM res_company WHERE id = 1")" "Cabinet d'Essai Douala"
ADMIN="FROM res_users u JOIN res_partner p ON p.id = u.partner_id WHERE u.login = 'admin@example.invalid'"
assert_eq "admin language and zone" "$(q firm_smoke "SELECT p.lang, p.tz $ADMIN")" "fr_FR|Africa/Douala"
assert_eq "language active" "$(q firm_smoke "SELECT active FROM res_lang WHERE code = 'fr_FR'")" t
[ "$(q firm_smoke "SELECT count(*) FROM ir_ui_menu WHERE name ? 'fr_FR'")" -gt 0 ] || fail "no French translations loaded"
assert_eq "no demo data" "$(q firm_smoke "SELECT bool_or(demo) FROM ir_module_module WHERE state = 'installed'")" f
assert_eq "mail cron off" "$(q firm_smoke "SELECT c.active FROM ir_cron c JOIN ir_model_data d ON d.res_id = c.id AND d.model = 'ir.cron' WHERE d.name = 'ir_cron_mail_scheduler_action'")" f
# The generated password must really open the account.
printf 'import os\nu = env["res.users"].search([("login", "=", "admin@example.invalid")])\nu.with_user(u)._check_credentials({"type": "password", "password": %s}, {"interactive": False})\nprint("PASSWORD_OK")\n' "\"$PW\"" \
  | runuser -u odoo -- /opt/odoo19/venv/bin/python "$SRC/odoo-bin" shell -c /etc/odoo/odoo.conf -d firm_smoke --no-http --logfile=/tmp/odoo-shell.log \
  | grep -x PASSWORD_OK >/dev/null || fail "the generated password does not authenticate"
if bash "$NEW_FIRM" --db firm_smoke --name x --admin-email a@example.invalid 2>/dev/null; then
  fail "new_firm.sh ran over an existing database"
fi

section "backup_firm.sh"
bash "$BACKUP" --dry-run --db firm_smoke | grep "DRY RUN"
[ ! -e /var/backups/odoo/firms/firm_smoke ] || fail "dry-run wrote a backup"
bash "$BACKUP" --db firm_smoke
B=$(find /var/backups/odoo/firms/firm_smoke -mindepth 1 -maxdepth 1 -type d)
assert_eq "backup folder mode" "$(stat -c '%a %U' "$B")" "700 root"
(cd "$B" && sha256sum -c --quiet SHA256SUMS) || fail "checksums"
[ -s "$B/filestore.tar.gz" ] || fail "no filestore archive"
runuser -u postgres -- createdb -O odoo -E UTF8 -T template0 --lc-collate=C --lc-ctype=C.UTF-8 firm_restored
runuser -u postgres -- pg_restore --no-owner --role=odoo -d firm_restored < "$B/db.dump"
assert_eq "restored firm" "$(q firm_restored "SELECT name FROM res_company WHERE id = 1")" "Cabinet d'Essai Douala"
if bash "$BACKUP" --db no_such_db 2>/dev/null; then fail "backup of a missing database succeeded"; fi

section "deploy-staging.sh: refuses cleanly while the repository has no addon"
runuser -u postgres -- createdb -O odoo -E UTF8 -T template0 --lc-collate=C --lc-ctype=C.UTF-8 "$STAGING_DB"
runuser -u odoo -- /opt/odoo19/venv/bin/python "$SRC/odoo-bin" -c /etc/odoo/odoo.conf -d "$STAGING_DB" \
  -i base,web --without-demo=True --no-http --max-cron-threads=0 --stop-after-init --logfile=/tmp/odoo-seed.log
systemctl start odoo
git init -q -b dev "$REPO"
git -C "$REPO" config user.name smoke
git -C "$REPO" config user.email smoke@example.invalid
git -C "$REPO" commit -q --allow-empty -m "empty"
if bash "$DEPLOY" deploy dev; then fail "deployed a commit without addons"; fi
assert_eq "service untouched" "$(systemctl is-active odoo)" active

# Writes the probe addon. $1 = extra field lines for the model, $2 = manifest data list.
probe() {
  mkdir -p "$REPO/addons/smoke_probe/models"
  printf 'from . import models\n' > "$REPO/addons/smoke_probe/__init__.py"
  printf 'from . import probe\n' > "$REPO/addons/smoke_probe/models/__init__.py"
  cat > "$REPO/addons/smoke_probe/models/probe.py" <<EOF
from odoo import fields, models


class SmokeProbe(models.Model):
    _name = "smoke.probe"
    _description = "Smoke probe"
    name = fields.Char()
$1
EOF
  printf '{"name": "Smoke probe", "version": "19.0.1.0.0", "license": "LGPL-3", "depends": ["base"], "data": [%s]}\n' "$2" \
    > "$REPO/addons/smoke_probe/__manifest__.py"
  git -C "$REPO" add -A
  git -C "$REPO" commit -q -m "$3"
  git -C "$REPO" rev-parse HEAD
}

section "deploy-staging.sh: first release, module installed"
SHA_A=$(probe "" "" "A")
bash "$DEPLOY" deploy dev
assert_eq "current is A" "$(current_sha)" "$SHA_A"
assert_eq "module installed" "$(q "$STAGING_DB" "SELECT state FROM ir_module_module WHERE name = 'smoke_probe'")" installed
assert_eq "copy dropped" "$(q postgres "SELECT count(*) FROM pg_database WHERE datname = '${STAGING_DB}_predeploy'")" 0
assert_eq "code not writable by odoo" "$(stat -c '%U' "$ROOT/current/addons/smoke_probe/__manifest__.py")" root
q "$STAGING_DB" "INSERT INTO smoke_probe (name) VALUES ('sentinel')" >/dev/null

section "deploy-staging.sh: second release, module updated"
SHA_B=$(probe "    note = fields.Char()" "" "B")
bash "$DEPLOY" deploy "$SHA_B"
assert_eq "current is B" "$(current_sha)" "$SHA_B"
assert_eq "new column" "$(q "$STAGING_DB" "SELECT count(*) FROM information_schema.columns WHERE table_name = 'smoke_probe' AND column_name = 'note'")" 1
bash "$DEPLOY" deploy "$SHA_B" | grep "nothing to do" || fail "same sha should be a no-op"

section "deploy-staging.sh: commit outside dev is refused"
git -C "$REPO" checkout -q -b other
git -C "$REPO" commit -q --allow-empty -m "elsewhere"
SHA_OTHER=$(git -C "$REPO" rev-parse HEAD)
git -C "$REPO" checkout -q dev
if bash "$DEPLOY" deploy "$SHA_OTHER"; then fail "deployed a commit that is not on dev"; fi
assert_eq "current still B" "$(current_sha)" "$SHA_B"

section "deploy-staging.sh: failed update rolls back code and database"
mkdir -p "$REPO/addons/smoke_probe/data"
cat > "$REPO/addons/smoke_probe/data/bad.xml" <<'EOF'
<odoo>
  <record id="bad_probe" model="smoke.probe"><field name="no_such_field">x</field></record>
</odoo>
EOF
SHA_C=$(probe "    bad_col = fields.Char()" '"data/bad.xml"' "C: broken data file")
if bash "$DEPLOY" deploy "$SHA_C"; then fail "broken release reported success"; fi
assert_eq "current back on B" "$(current_sha)" "$SHA_B"
assert_eq "service healthy" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8069/web/login)" 200
assert_eq "schema change undone" "$(q "$STAGING_DB" "SELECT count(*) FROM information_schema.columns WHERE table_name = 'smoke_probe' AND column_name = 'bad_col'")" 0
assert_eq "data kept" "$(q "$STAGING_DB" "SELECT count(*) FROM smoke_probe WHERE name = 'sentinel'")" 1
[ "$(q postgres "SELECT count(*) FROM pg_database WHERE datname LIKE '${STAGING_DB}_failed_%'")" = 1 ] || fail "failed database not kept"
assert_eq "copy consumed" "$(q postgres "SELECT count(*) FROM pg_database WHERE datname = '${STAGING_DB}_predeploy'")" 0
assert_eq "rollback record unchanged" "$(sed -n 's/^previous=//p' "$ROOT/current.previous")" "$ROOT/releases/${SHA_A:0:12}"

section "deploy-staging.sh: update passes, service fails its health check, rolls back"
git -C "$REPO" rm -q -r addons/smoke_probe/data
SHA_D=$(probe "    bad_col_two = fields.Char()" "" "D: breaks at service start")
cat >> "$REPO/addons/smoke_probe/__init__.py" <<'EOF'
import sys
if "--stop-after-init" not in sys.argv:
    raise RuntimeError("smoke probe: fails when the service starts")
EOF
git -C "$REPO" add -A
git -C "$REPO" commit -q -m "D2: breaks at service start"
SHA_D=$(git -C "$REPO" rev-parse HEAD)
if bash "$DEPLOY" deploy "$SHA_D"; then fail "release failing its health check reported success"; fi
assert_eq "current back on B" "$(current_sha)" "$SHA_B"
assert_eq "service healthy" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8069/web/login)" 200
assert_eq "second schema change undone" "$(q "$STAGING_DB" "SELECT count(*) FROM information_schema.columns WHERE table_name = 'smoke_probe' AND column_name = 'bad_col_two'")" 0

section "deploy-staging.sh: check, status, manual rollback"
bash "$DEPLOY" check
bash "$DEPLOY" status
bash "$DEPLOY" rollback
assert_eq "current back on A" "$(current_sha)" "$SHA_A"
assert_eq "service healthy" "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8069/web/login)" 200

section "All rehearsals passed"
