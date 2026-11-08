#!/usr/bin/env bash
# Rehearses the firm server's recipe without a server: every script in dry-run mode, the rendered
# files checked one by one, the isolation test on two rendered firms, the release signature.
# Writes under a temporary folder only. Contacts nothing.
set -euo pipefail

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
A=$WORK/firm-a
B=$WORK/firm-b

fail() { printf 'FAILED: %s\n' "$*" >&2; exit 1; }
has() { grep -q -- "$2" "$1" || fail "$1 does not have: $2"; }
lacks() { if grep -q -- "$2" "$1"; then fail "$1 should not have: $2"; fi; }

sed -e "s/cabinet-exemple/cabinet-b/g" -e "s/0001/0002/g" -e "s/Q2FiaW5ldCBFeGVtcGxl/Q2FiaW5ldCBC/" deploy/firm/sample.env > "$WORK/b.env"

echo "== install-firm-server.sh --dry-run, two firms"
bash deploy/firm/install-firm-server.sh --env deploy/firm/sample.env --dry-run --root "$A" > "$WORK/a.log"
bash deploy/firm/install-firm-server.sh --env "$WORK/b.env" --dry-run --root "$B" > "$WORK/b.log"
tail -n 1 "$WORK/a.log"

echo "== a second run changes nothing"
find "$A" -type f -print0 | sort -z | xargs -0 sha256sum > "$WORK/before"
bash deploy/firm/install-firm-server.sh --env deploy/firm/sample.env --dry-run --root "$A" > "$WORK/a2.log"
find "$A" -type f -print0 | sort -z | xargs -0 sha256sum > "$WORK/after"
diff <(grep -v firm-install-state "$WORK/before") <(grep -v firm-install-state "$WORK/after") || fail "the second run changed files"

echo "== no secret is printed"
for secret in heartbeat.token db.password master.password restic.key; do
  value=$(cat "$A/etc/auditisa-firm/secrets/$secret")
  if grep -qF -- "$value" "$WORK/a.log"; then fail "$secret was printed"; fi
done
lacks "$WORK/a.log" "DRYRUNACCESSKEY"
lacks "$WORK/a.log" "dry-run-storage-secret"

echo "== guardrails in the rendered files"
SSHD=$A/etc/ssh/sshd_config.d/00-ea-hardening.conf
has "$SSHD" '^PasswordAuthentication no'
has "$SSHD" '^KbdInteractiveAuthentication no'
has "$SSHD" '^PermitRootLogin prohibit-password'
has "$WORK/a.log" 'passwd --lock root'
[ "$(grep -c . "$A/root/.ssh/authorized_keys")" = 1 ] || fail "more than one SSH key"
[ "$(cat "$A/root/.ssh/authorized_keys")" != "$(cat "$B/root/.ssh/authorized_keys")" ] || fail "two firms share an SSH key"

has "$WORK/a.log" 'ufw default deny incoming'
has "$WORK/a.log" 'ufw allow from 8.8.8.8/32 to any port 22 proto tcp'
lacks "$WORK/a.log" 'ufw allow 22'
has "$WORK/a.log" 'ufw allow 80/tcp'
has "$WORK/a.log" 'ufw allow 443/tcp'
has "$A/etc/fail2ban/jail.d/auditisa.local" '^\[sshd\]'
has "$A/etc/apt/apt.conf.d/20auto-upgrades" 'Unattended-Upgrade "1"'

CONF=$A/etc/odoo/odoo.conf
has "$CONF" '^list_db = False'
has "$CONF" '^dbfilter = ^firm_cabinet_exemple\$$'
has "$CONF" '^http_interface = 127.0.0.1'
has "$CONF" '^proxy_mode = True'
lacks "$CONF" '^smtp_server'
lacks "$CONF" 'ea_platform'
[ "$(sed -n 's/^admin_passwd = //p' "$CONF")" != "$(sed -n 's/^admin_passwd = //p' "$B/etc/odoo/odoo.conf")" ] || fail "two firms share a master password"
[ "$(sed -n 's/^db_password = //p' "$CONF")" != "$(sed -n 's/^db_password = //p' "$B/etc/odoo/odoo.conf")" ] || fail "two firms share a database password"
[ "$(wc -c < "$A/etc/auditisa-firm/secrets/restic.key")" -ge 64 ] || fail "backup key too short"
cmp -s "$A/etc/auditisa-firm/secrets/restic.key" "$B/etc/auditisa-firm/secrets/restic.key" && fail "two firms share a backup key"
[ "$(stat -c %a "$A/etc/auditisa-firm/secrets/restic.key")" = 600 ] || fail "backup key is not private"
has "$(find "$A/etc/postgresql" -name auditisa.conf)" "^listen_addresses = 'localhost'"

SITE=$A/etc/nginx/sites-available/firm-https.conf
has "$SITE" 'location ~ ^/web/database { return 404; }'
has "$SITE" 'Strict-Transport-Security'
has "$SITE" 'access_log off'
has "$SITE" 'server_name cabinet-exemple.auditisa.example'
has "$A/etc/nginx/sites-available/firm-http.conf" 'return 301 https://'

for unit in firm-backup firm-restore-test firm-status firm-apply-desired firm-cert; do
  [ -f "$A/etc/systemd/system/$unit.timer" ] || fail "no timer for $unit"
done
has "$A/etc/systemd/system/firm-backup.timer" 'Persistent=true'
has "$A/etc/systemd/system/odoo.service" 'NoNewPrivileges=yes'
has "$A/usr/local/sbin/firm-metadata-block" '169.254.169.254'
has "$A/etc/ssh/sshrc" 'break-glass.log'

echo "== the other scripts, dry run"
for script in firm-backup firm-restore-test firm-export firm-apply-desired; do
  FIRM_PREFIX=$A bash "deploy/firm/$script.sh" --dry-run > "$WORK/$script.log"
done
FIRM_PREFIX=$A bash deploy/firm/firm-update.sh "abcdef123456" "$(printf 'a%.0s' {1..64})" --dry-run > "$WORK/update.log"
has "$WORK/update.log" 'firm-backup --tag pre-update'
has "$WORK/firm-backup.log" 'keep-daily 14'
if FIRM_PREFIX=$A bash deploy/firm/firm-update.sh 'x;reboot' abc --dry-run >/dev/null 2>&1; then fail "firm-update took a bad release"; fi

echo "== the add-ons asked are checked against the release, dry run"
mkdir -p "$A/opt/auditisa-odoo/releases/dry"
cp -r addons "$A/opt/auditisa-odoo/releases/dry/addons"
ln -sfn "$A/opt/auditisa-odoo/releases/dry" "$A/opt/auditisa-odoo/current"
PYTHON=$(command -v python3)
FIRM_PREFIX=$A ODOO_PY=$PYTHON bash deploy/firm/firm-addons.sh apply --dry-run -- ea_client_addon_sample > "$WORK/addons.log"
has "$WORK/addons.log" 'would switch on: ea_client_addon_sample'
for refused in ea_audit_reports ea_audit_core ea_platform_admin base nothing_like_this; do
  if FIRM_PREFIX=$A ODOO_PY=$PYTHON bash deploy/firm/firm-addons.sh apply --dry-run -- "$refused" >/dev/null 2>&1; then fail "firm-addons took $refused"; fi
done
if FIRM_PREFIX=$A ODOO_PY=$PYTHON bash deploy/firm/firm-addons.sh apply --dry-run -- 'x;reboot' >/dev/null 2>&1; then fail "firm-addons took a bad code"; fi
has "$A/etc/systemd/system/odoo.service" 'ReadWritePaths=/var/lib/odoo /var/log/odoo /var/lib/auditisa-firm/spool$'

echo "== the firm's outgoing mail, set by root at onboarding, dry run"
MAIL_PW="dry-run-mail-secret-$RANDOM"
MAIL_FILE=$A/etc/auditisa-firm/secrets/mail.env
printf 'MAIL_HOST=smtp.example.cm\nMAIL_PORT=587\nMAIL_ENCRYPTION=starttls\nMAIL_USER=cabinet@example.cm\nMAIL_PASSWORD=%s\nMAIL_FROM=cabinet@example.cm\n' "$MAIL_PW" > "$MAIL_FILE"
chmod 600 "$MAIL_FILE"
FIRM_PREFIX=$A ODOO_PY=$PYTHON bash deploy/firm/firm-mail-server.sh --dry-run > "$WORK/mail.log" 2>&1
has "$WORK/mail.log" 'smtp.example.cm:587 STARTTLS'
lacks "$WORK/mail.log" "$MAIL_PW"
chmod 644 "$MAIL_FILE"
if FIRM_PREFIX=$A ODOO_PY=$PYTHON bash deploy/firm/firm-mail-server.sh --dry-run > "$WORK/mail-loose.log" 2>&1; then fail "firm-mail-server took a file others can read"; fi
lacks "$WORK/mail-loose.log" "$MAIL_PW"
chmod 600 "$MAIL_FILE"
sed -i 's/^MAIL_ENCRYPTION=.*/MAIL_ENCRYPTION=none/' "$MAIL_FILE"
if FIRM_PREFIX=$A ODOO_PY=$PYTHON bash deploy/firm/firm-mail-server.sh --dry-run >/dev/null 2>&1; then fail "firm-mail-server took an unencrypted password"; fi
rm -f "$MAIL_FILE"
lacks "$A/etc/systemd/system/odoo.service" 'ReadWritePaths=.*auditisa-firm/addons'

echo "== the isolation test finds every planted fault"
bash scripts/provision/verify_firm_isolation.sh --rehearse "$A" "$B"

echo "== control plane, dry run: open to all (OPERATOR_IPS=any, the owner's ruling)"
CP=$WORK/control-plane
bash deploy/control-plane/install-control-plane.sh --env deploy/control-plane/sample.env --dry-run --root "$CP" > "$WORK/cp.log"
SITE=$CP/etc/nginx/sites-available/control-plane.conf
has "$SITE" 'location = /platform/heartbeat'
has "$SITE" 'limit_except POST { deny all; }'
has "$SITE" 'location / { return 404; }'
has "$SITE" 'location ~ ^/web/database { return 404; }'
has "$SITE" 'location ~ ^/web/signup { return 404; }'
has "$SITE" 'location = /web/session/authenticate'
has "$SITE" 'limit_req zone=odoo_login'
has "$SITE" 'Strict-Transport-Security'
has "$SITE" 'ssl_reject_handshake on;'
lacks "$SITE" 'allow '
lacks "$SITE" 'deny all;$'
# The heartbeat address has the heartbeat only, unless FIRM_DOORS says otherwise.
lacks "$SITE" 'location ~ ^/platform/support/(ticket|sync|trace)'
lacks "$SITE" 'location = /platform/practice-heartbeat {$'
has "$CP/etc/nginx/sites-available/control-plane-http.conf" 'return 301 https://'
has "$CP/etc/odoo/odoo.conf" '^list_db = False'
has "$CP/etc/odoo/odoo.conf" '^smtp_server = False'
has "$CP/etc/odoo/odoo.conf" '^workers = 2'
lacks "$CP/etc/odoo/odoo.conf" 'token'
has "$CP/etc/systemd/system/odoo.service" 'LoadCredential=vultr-token:/etc/auditisa-platform/vultr.token'
has "$CP/etc/fail2ban/jail.d/auditisa.local" '^\[odoo-login\]'
has "$CP/etc/fail2ban/jail.d/auditisa.local" '^\[sshd\]'
has "$CP/etc/ssh/sshd_config.d/00-ea-hardening.conf" '^PasswordAuthentication no'
has "$CP/etc/ssh/sshd_config.d/00-ea-hardening.conf" '^PermitRootLogin prohibit-password'
has "$WORK/cp.log" 'ufw allow 22/tcp'
has "$WORK/cp.log" 'auth_totp'
has "$CP/usr/local/sbin/console-backup" '^KEEP_DAYS=14$'
bash -n "$CP/usr/local/sbin/console-backup" "$CP/usr/local/sbin/console-restore-test"
# fail2ban's filter catches Odoo's line for a failed sign-in, and not a successful one.
FILTER=$(sed -n 's/^failregex = //p' "$CP/etc/fail2ban/filter.d/odoo-login.conf" | sed 's/<HOST>/(?P<host>[0-9.]+)/')
python3 - "$FILTER" <<'PY'
import re, sys
pattern = re.compile(sys.argv[1])
failed = " 1234 INFO auditisa_platform odoo.addons.base.models.res_users: Login failed for login:x from 203.0.113.9"
passed = " 1234 INFO auditisa_platform odoo.addons.base.models.res_users: Login successful for login:x from 203.0.113.9"
assert pattern.match(failed).group("host") == "203.0.113.9"
assert not pattern.match(passed)
PY

echo "== control plane, dry run: a list of addresses, and the two extra doors"
sed -e 's/^OPERATOR_IPS=.*/OPERATOR_IPS="8.8.8.8 2001:db8::\/48"/' -e 's/^FIRM_DOORS=.*/FIRM_DOORS="heartbeat support practice"/' \
  deploy/control-plane/sample.env > "$WORK/cp-list.env"
CPL=$WORK/control-plane-list
bash deploy/control-plane/install-control-plane.sh --env "$WORK/cp-list.env" --dry-run --root "$CPL" > "$WORK/cpl.log"
SITE=$CPL/etc/nginx/sites-available/control-plane.conf
has "$SITE" 'allow 8.8.8.8;'
has "$SITE" 'allow 2001:db8::/48;'
has "$SITE" '    deny all;$'
has "$SITE" 'location ~ ^/platform/support/(ticket|sync|trace)\$'
has "$SITE" 'location = /platform/practice-heartbeat {$'
has "$WORK/cpl.log" 'ufw allow from 8.8.8.8 to any port 22'
lacks "$WORK/cpl.log" 'ufw allow 22/tcp'

echo "== control plane: what is refused"
refused() {
  if bash deploy/control-plane/install-control-plane.sh --env "$1" --dry-run --root "$WORK/refused" >/dev/null 2>&1; then
    fail "install-control-plane.sh accepted $2"
  fi
}
for bad in 'OPERATOR_IPS=0.0.0.0/0' 'OPERATOR_IPS=::/0' 'OPERATOR_IPS="any 8.8.8.8"' 'OPERATOR_IPS="8.8.8.8;reboot"' \
           'FIRM_DOORS=everything' 'FIRM_DOORS=support' 'ADMIN_HOST=hb.auditisa.com'; do
  { cat deploy/control-plane/sample.env; printf '%s\n' "$bad"; } > "$WORK/bad.env"
  refused "$WORK/bad.env" "$bad"
done

echo "== a release is signed, verified, and refused once changed"
KEYS=$WORK/keys
mkdir -p "$KEYS"
bash scripts/provision/build_release.sh --new-key "$KEYS/signing.pem" > "$WORK/key.log"
sed -n '/BEGIN PUBLIC KEY/,/END PUBLIC KEY/p' "$WORK/key.log" > "$KEYS/signing.pub"
if bash scripts/provision/build_release.sh --new-key "$KEYS/signing.pem" >/dev/null 2>&1; then fail "the signing key was overwritten"; fi
SHA=$(git rev-parse HEAD)
bash scripts/provision/build_release.sh HEAD --key "$KEYS/signing.pem" --out "$WORK/out" > "$WORK/build.log"
BUNDLE=$WORK/out/$SHA.tar.gz
bash scripts/provision/build_release.sh --verify "$BUNDLE" --pub "$KEYS/signing.pub" >/dev/null
[ -s "$WORK/out/$SHA.catalogue.json" ] || fail "no catalogue beside the bundle"
openssl pkeyutl -verify -pubin -inkey "$KEYS/signing.pub" -rawin -in "$WORK/out/$SHA.catalogue.json" -sigfile "$WORK/out/$SHA.catalogue.json.sig" >/dev/null || fail "the catalogue's signature does not hold"
has "$WORK/out/$SHA.catalogue.json" '"code": "ea_audit_reports"'
lacks "$WORK/out/$SHA.catalogue.json" 'ea_platform'
tar -tzf "$BUNDLE" > "$WORK/list"
has "$WORK/list" '^deploy/firm/install-firm-server.sh'
has "$WORK/list" '^scripts/provision/new_firm.sh'
has "$WORK/list" '^addons/ea_audit_firm_agent/'
lacks "$WORK/list" 'ea_platform'
lacks "$WORK/list" '^deploy/control-plane'
cp "$BUNDLE" "$WORK/tampered.tar.gz"
cp "$BUNDLE.sig" "$WORK/tampered.tar.gz.sig"
printf 'x' >> "$WORK/tampered.tar.gz"
if bash scripts/provision/build_release.sh --verify "$WORK/tampered.tar.gz" --pub "$KEYS/signing.pub" >/dev/null 2>&1; then fail "a changed bundle passed"; fi

echo "firm-dry-run: all good"
